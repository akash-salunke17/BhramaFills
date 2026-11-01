"""Unit and integration tests for web source ingestion and Supabase persistence."""

import asyncio
from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import asyncpg
from fastapi import Depends, FastAPI, status
from fastapi.testclient import TestClient
import pytest

from app.core.auth import get_current_user
from app.core.ownership import OwnedProjectContext, get_owned_project
from app.core.config import Settings
from app.db.connection import (
    DatabaseManager,
    DatabaseNotConfiguredError,
    DatabaseUnavailableError,
    get_db_manager,
)
from app.services.sources.exceptions import (
    EmptyExtractedContentError,
    ProjectNotFoundError,
    SourceNotFoundError,
)
from app.services.sources.schemas import (
    ProjectWebSourceRequest,
    ProjectWebSourceResponse,
    SourceDetailResponse,
    SourceSummaryResponse,
)
from app.services.sources.web_source_service import (
    WebSourceIngestionService,
    get_web_source_service,
)
from app.services.web.exceptions import (
    ContentTooLargeError,
    FetchNetworkError,
    FetchTimeoutError,
    InvalidURLError,
    SSRFBlockedError,
    UnsupportedContentTypeError,
)
from app.services.web.safe_fetcher import FetchedWebContent, SafeWebFetcher, get_safe_fetcher
from tests.conftest import TEST_USER_ID


SAMPLE_HTML_PAYLOAD = """
<!DOCTYPE html>
<html>
<head>
    <title>Understanding Information Gaps in Scientific Research</title>
    <meta name="description" content="An in-depth article analyzing knowledge gaps.">
    <meta name="author" content="Dr. Jane Doe">
</head>
<body>
    <h1>Information Gap Methodology</h1>
    <p>This is a thorough explanation of information gaps, providing critical evidence for research inquiries and decision matrices.</p>
    <h2>Key Principles</h2>
    <p>Empirical evidence must be systematically collected from primary sources and evaluated for consistency and logical coherence.</p>
</body>
</html>
"""


# =============================================================================
# 1. Pydantic Schema Validation Tests
# =============================================================================

def test_project_web_source_request_validation():
    """Verify ProjectWebSourceRequest accepts valid URL and rejects empty or oversized URLs."""
    valid = ProjectWebSourceRequest(url="https://example.com/test")
    assert valid.url == "https://example.com/test"

    with pytest.raises(Exception):
        ProjectWebSourceRequest(url="")

    with pytest.raises(Exception):
        ProjectWebSourceRequest(url="https://example.com/" + ("a" * 2050))


def test_project_web_source_response_schema():
    """Verify ProjectWebSourceResponse serializes all required fields."""
    now = datetime.now(timezone.utc)
    res = ProjectWebSourceResponse(
        source_id=uuid4(),
        project_id=uuid4(),
        original_url="https://example.com/test",
        final_url="https://example.com/test",
        title="Example Article",
        ingestion_status="completed",
        extracted_content_id=uuid4(),
        word_count=120,
        character_count=850,
        content_hash="abc123hash",
        is_duplicate=False,
        extracted_at=now,
        created_at=now,
    )
    assert res.word_count == 120
    assert res.is_duplicate is False


# =============================================================================
# 2. DatabaseManager acquire_connection Tests
# =============================================================================

@pytest.mark.asyncio
async def test_acquire_connection_unconfigured_raises():
    """Verify acquire_connection raises DatabaseNotConfiguredError when URL is None."""
    manager = DatabaseManager(settings=Settings(SUPABASE_DB_URL=None, _env_file=None))
    with pytest.raises(DatabaseNotConfiguredError):
        async with manager.acquire_connection():
            pass


@pytest.mark.asyncio
async def test_acquire_connection_pool_none_raises():
    """Verify acquire_connection raises DatabaseUnavailableError when pool initialization fails."""
    manager = DatabaseManager(settings=Settings(SUPABASE_DB_URL="postgresql://user:pass@localhost:5432/db", _env_file=None))
    with patch.object(manager, "initialize", AsyncMock()):
        manager._pool = None
        with pytest.raises(DatabaseUnavailableError):
            async with manager.acquire_connection():
                pass


@pytest.mark.asyncio
async def test_acquire_connection_success():
    """Verify acquire_connection yields connection when pool is available."""
    manager = DatabaseManager(settings=Settings(SUPABASE_DB_URL="postgresql://user:pass@localhost:5432/db", _env_file=None))
    mock_conn = AsyncMock()
    mock_acquire = AsyncMock()
    mock_acquire.__aenter__.return_value = mock_conn
    mock_acquire.__aexit__.return_value = None

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire
    manager._pool = mock_pool

    async with manager.acquire_connection() as conn:
        assert conn is mock_conn


@pytest.mark.asyncio
async def test_acquire_connection_timeout_raises_unavailable():
    """Verify acquire_connection translates asyncio.TimeoutError to DatabaseUnavailableError."""
    manager = DatabaseManager(settings=Settings(SUPABASE_DB_URL="postgresql://user:pass@localhost:5432/db", _env_file=None))
    mock_acquire = AsyncMock()
    mock_acquire.__aenter__.side_effect = asyncio.TimeoutError()

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire
    manager._pool = mock_pool

    with pytest.raises(DatabaseUnavailableError):
        async with manager.acquire_connection():
            pass


# =============================================================================
# 3. WebSourceIngestionService Business Logic Tests
# =============================================================================

@pytest.mark.asyncio
async def test_validate_project_exists_success():
    """Verify validate_project_exists returns project row dict when project is found and owned."""
    project_id = uuid4()
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": project_id,
        "title": "Test Project",
        "status": "Draft",
        "user_id": TEST_USER_ID,
    }

    service = WebSourceIngestionService()
    result = await service.validate_project_exists(mock_conn, project_id, user_id=TEST_USER_ID)
    assert result["id"] == project_id
    assert result["title"] == "Test Project"


@pytest.mark.asyncio
async def test_validate_project_exists_not_found():
    """Verify validate_project_exists raises ProjectNotFoundError when project does not exist."""
    project_id = uuid4()
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None

    service = WebSourceIngestionService()
    with pytest.raises(ProjectNotFoundError) as exc_info:
        await service.validate_project_exists(mock_conn, project_id, user_id=TEST_USER_ID)
    assert str(project_id) in exc_info.value.message


@pytest.mark.asyncio
async def test_ingest_web_source_successful_transaction():
    """Verify ingest_web_source executes atomic transaction to insert source and content."""
    project_id = uuid4()
    source_id = uuid4()
    content_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_conn = AsyncMock()
    # 1. Project exists
    mock_conn.fetchrow.side_effect = [
        {"id": project_id, "title": "AI Project", "status": "Draft", "user_id": TEST_USER_ID},  # validate_project_exists
        None,  # find_existing_by_url -> not duplicate
        None,  # find_existing_by_hash -> not duplicate
        {"id": source_id, "created_at": now},  # INSERT INTO sources
        {"id": content_id},  # INSERT INTO extracted_content
    ]

    mock_tx = MagicMock()
    mock_tx.__aenter__ = AsyncMock(return_value=None)
    mock_tx.__aexit__ = AsyncMock(return_value=None)
    mock_conn.transaction = MagicMock(return_value=mock_tx)

    mock_db = MagicMock(spec=DatabaseManager)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_conn
    mock_ctx.__aexit__.return_value = None
    mock_db.acquire_connection.return_value = mock_ctx

    mock_fetcher = MagicMock(spec=SafeWebFetcher)
    mock_fetcher.fetch = AsyncMock(
        return_value=FetchedWebContent(
            url="https://example.com/research",
            final_url="https://example.com/research",
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
            html_content=SAMPLE_HTML_PAYLOAD,
            redirect_count=0,
        )
    )

    service = WebSourceIngestionService(db_manager=mock_db, fetcher=mock_fetcher)
    response = await service.ingest_web_source(project_id, "https://example.com/research", user_id=TEST_USER_ID)

    assert response.source_id == source_id
    assert response.project_id == project_id
    assert response.extracted_content_id == content_id
    assert response.is_duplicate is False
    assert response.ingestion_status == "completed"
    assert response.word_count > 0
    assert "Information Gaps" in response.title
    mock_conn.transaction.assert_called_once()


@pytest.mark.asyncio
async def test_ingest_web_source_duplicate_url():
    """Verify duplicate URL returns existing source with is_duplicate=True without re-fetching."""
    project_id = uuid4()
    source_id = uuid4()
    content_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = [
        {"id": project_id, "title": "AI Project", "status": "Draft", "user_id": TEST_USER_ID},  # validate_project_exists
        {  # find_existing_by_url -> found
            "id": source_id,
            "project_id": project_id,
            "title": "Existing Title",
            "original_url": "https://example.com/duplicate",
            "ingestion_status": "completed",
            "content_hash": "existinghash123",
            "file_metadata": {"final_url": "https://example.com/duplicate", "word_count": 50, "character_count": 300},
            "created_at": now,
            "extracted_content_id": content_id,
            "extracted_at": now,
            "extraction_metadata": {},
        },
    ]

    mock_db = MagicMock(spec=DatabaseManager)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_conn
    mock_ctx.__aexit__.return_value = None
    mock_db.acquire_connection.return_value = mock_ctx

    mock_fetcher = MagicMock(spec=SafeWebFetcher)
    mock_fetcher.fetch = AsyncMock()

    service = WebSourceIngestionService(db_manager=mock_db, fetcher=mock_fetcher)
    response = await service.ingest_web_source(project_id, "https://example.com/duplicate", user_id=TEST_USER_ID)

    assert response.source_id == source_id
    assert response.is_duplicate is True
    assert response.title == "Existing Title"
    assert response.word_count == 50
    # Fetcher should NOT have been called
    mock_fetcher.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_web_source_duplicate_content_hash():
    """Verify duplicate content hash from different URL returns existing source with is_duplicate=True."""
    project_id = uuid4()
    source_id = uuid4()
    content_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = [
        {"id": project_id, "title": "AI Project", "status": "Draft", "user_id": TEST_USER_ID},  # validate_project_exists
        None,  # find_existing_by_url -> none
        {  # find_existing_by_hash -> duplicate hash found!
            "id": source_id,
            "project_id": project_id,
            "title": "Original Ingested Page",
            "original_url": "https://example.com/first-url",
            "ingestion_status": "completed",
            "content_hash": "matched_hash",
            "file_metadata": {"final_url": "https://example.com/first-url", "word_count": 60, "character_count": 400},
            "created_at": now,
            "extracted_content_id": content_id,
            "extracted_at": now,
            "extraction_metadata": {},
        },
    ]

    mock_db = MagicMock(spec=DatabaseManager)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_conn
    mock_ctx.__aexit__.return_value = None
    mock_db.acquire_connection.return_value = mock_ctx

    mock_fetcher = MagicMock(spec=SafeWebFetcher)
    mock_fetcher.fetch = AsyncMock(
        return_value=FetchedWebContent(
            url="https://example.com/second-url",
            final_url="https://example.com/second-url",
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
            html_content=SAMPLE_HTML_PAYLOAD,
            redirect_count=0,
        )
    )

    service = WebSourceIngestionService(db_manager=mock_db, fetcher=mock_fetcher)
    response = await service.ingest_web_source(project_id, "https://example.com/second-url", user_id=TEST_USER_ID)

    assert response.source_id == source_id
    assert response.is_duplicate is True
    assert response.title == "Original Ingested Page"
    # No insert should have occurred
    mock_conn.transaction.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_web_source_empty_content_raises():
    """Verify empty extracted text raises EmptyExtractedContentError."""
    project_id = uuid4()
    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = [
        {"id": project_id, "title": "AI Project", "status": "Draft", "user_id": TEST_USER_ID},
        None,  # no url duplicate
    ]

    mock_db = MagicMock(spec=DatabaseManager)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_conn
    mock_ctx.__aexit__.return_value = None
    mock_db.acquire_connection.return_value = mock_ctx

    mock_fetcher = MagicMock(spec=SafeWebFetcher)
    mock_fetcher.fetch = AsyncMock(
        return_value=FetchedWebContent(
            url="https://example.com/empty",
            final_url="https://example.com/empty",
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
            html_content="<html><head></head><body><!-- empty --></body></html>",
            redirect_count=0,
        )
    )

    service = WebSourceIngestionService(db_manager=mock_db, fetcher=mock_fetcher)
    with pytest.raises(EmptyExtractedContentError):
        await service.ingest_web_source(project_id, "https://example.com/empty", user_id=TEST_USER_ID)


@pytest.mark.asyncio
async def test_ingest_web_source_title_fallback_and_truncation():
    """Verify title falls back to URL domain if missing, and is truncated to 255 chars."""
    project_id = uuid4()
    source_id = uuid4()
    content_id = uuid4()
    now = datetime.now(timezone.utc)

    # HTML with an oversized title > 300 characters
    oversized_title = "A" * 350
    html_with_huge_title = f"<html><head><title>{oversized_title}</title></head><body><p>Valid content paragraph with plenty of words to pass length constraints.</p></body></html>"

    captured_title = None

    async def mock_fetchrow(query, *args):
        nonlocal captured_title
        if "research_projects" in query:
            return {"id": project_id, "title": "AI Project", "status": "Draft", "user_id": TEST_USER_ID}
        if "SELECT s.id" in query:
            return None  # no duplicate
        if "INSERT INTO public.sources" in query:
            captured_title = args[1]
            return {"id": source_id, "created_at": now}
        if "INSERT INTO public.extracted_content" in query:
            return {"id": content_id}
        return None

    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = mock_fetchrow
    mock_tx = MagicMock()
    mock_tx.__aenter__ = AsyncMock(return_value=None)
    mock_tx.__aexit__ = AsyncMock(return_value=None)
    mock_conn.transaction = MagicMock(return_value=mock_tx)

    mock_db = MagicMock(spec=DatabaseManager)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_conn
    mock_ctx.__aexit__.return_value = None
    mock_db.acquire_connection.return_value = mock_ctx

    mock_fetcher = MagicMock(spec=SafeWebFetcher)
    mock_fetcher.fetch = AsyncMock(
        return_value=FetchedWebContent(
            url="https://example.com/huge-title",
            final_url="https://example.com/huge-title",
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
            html_content=html_with_huge_title,
            redirect_count=0,
        )
    )

    service = WebSourceIngestionService(db_manager=mock_db, fetcher=mock_fetcher)
    res = await service.ingest_web_source(project_id, "https://example.com/huge-title", user_id=TEST_USER_ID)

    assert len(captured_title) == 255
    assert res.title == captured_title


@pytest.mark.asyncio
async def test_list_project_sources():
    """Verify list_project_sources returns list of source summaries."""
    project_id = uuid4()
    now = datetime.now(timezone.utc)
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {"id": project_id, "title": "AI Project", "status": "Draft", "user_id": TEST_USER_ID}
    mock_conn.fetch.return_value = [
        {
            "id": uuid4(),
            "project_id": project_id,
            "source_type": "url",
            "title": "Source 1",
            "original_url": "https://example.com/1",
            "original_filename": None,
            "ingestion_status": "completed",
            "content_hash": "hash1",
            "file_metadata": {"word_count": 100, "character_count": 600},
            "created_at": now,
            "updated_at": now,
        }
    ]

    mock_db = MagicMock(spec=DatabaseManager)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_conn
    mock_ctx.__aexit__.return_value = None
    mock_db.acquire_connection.return_value = mock_ctx

    service = WebSourceIngestionService(db_manager=mock_db)
    sources = await service.list_project_sources(project_id, user_id=TEST_USER_ID)
    assert len(sources) == 1
    assert sources[0].title == "Source 1"
    assert sources[0].word_count == 100


@pytest.mark.asyncio
async def test_get_project_source_detail_success_and_not_found():
    """Verify get_project_source_detail returns full detail, or raises SourceNotFoundError."""
    project_id = uuid4()
    source_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = [
        {"id": project_id, "title": "AI Project", "status": "Draft", "user_id": TEST_USER_ID},  # validate project
        {  # source found
            "id": source_id,
            "project_id": project_id,
            "source_type": "url",
            "title": "Source Detail",
            "original_url": "https://example.com/detail",
            "original_filename": None,
            "file_metadata": {"word_count": 50},
            "ingestion_status": "completed",
            "content_hash": "hashdetail",
            "created_at": now,
            "updated_at": now,
            "extracted_content_id": uuid4(),
            "extracted_text": "Detailed content text",
            "extraction_metadata": {"headings": []},
            "extraction_method": "beautifulsoup4",
            "extraction_version": "1.0",
            "extracted_at": now,
        },
        {"id": project_id, "title": "AI Project", "status": "Draft", "user_id": TEST_USER_ID},  # second call validate
        None,  # source not found
    ]

    mock_db = MagicMock(spec=DatabaseManager)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_conn
    mock_ctx.__aexit__.return_value = None
    mock_db.acquire_connection.return_value = mock_ctx

    service = WebSourceIngestionService(db_manager=mock_db)
    detail = await service.get_project_source_detail(project_id, source_id, user_id=TEST_USER_ID)
    assert detail.id == source_id
    assert detail.extracted_text == "Detailed content text"

    # Second call should raise SourceNotFoundError
    with pytest.raises(SourceNotFoundError):
        await service.get_project_source_detail(project_id, uuid4(), user_id=TEST_USER_ID)


# =============================================================================
# 4. HTTP API Endpoint Integration Tests (POST /projects/{project_id}/sources/web)
# =============================================================================

@pytest.fixture(autouse=True)
def override_project_ownership(app: FastAPI):
    """Allow domain service tests in this module to assume project ownership is validated."""
    app.dependency_overrides[get_owned_project] = (
        lambda project_id, current_user=Depends(get_current_user): OwnedProjectContext(
            id=project_id,
            user_id=current_user.id,
            title="Test Project",
        )
    )
    yield
    app.dependency_overrides.pop(get_owned_project, None)

def test_api_ingest_web_source_success_returns_201(app: FastAPI, client: TestClient):
    """Verify POST /api/v1/projects/{project_id}/sources/web returns 201 on new source."""
    project_id = uuid4()
    source_id = uuid4()
    content_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_service = MagicMock(spec=WebSourceIngestionService)
    mock_service.ingest_web_source = AsyncMock(
        return_value=ProjectWebSourceResponse(
            source_id=source_id,
            project_id=project_id,
            original_url="https://example.com/article",
            final_url="https://example.com/article",
            title="Extracted Title",
            ingestion_status="completed",
            extracted_content_id=content_id,
            word_count=200,
            character_count=1400,
            content_hash="sha256hash",
            is_duplicate=False,
            extracted_at=now,
            created_at=now,
        )
    )

    app.dependency_overrides[get_web_source_service] = lambda: mock_service
    try:
        resp = client.post(
            f"/api/v1/projects/{project_id}/sources/web",
            json={"url": "https://example.com/article"},
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["source_id"] == str(source_id)
        assert data["is_duplicate"] is False
        assert data["word_count"] == 200
    finally:
        app.dependency_overrides.pop(get_web_source_service, None)


def test_api_ingest_web_source_duplicate_returns_200(app: FastAPI, client: TestClient):
    """Verify POST /api/v1/projects/{project_id}/sources/web returns 200 when duplicate resolved."""
    project_id = uuid4()
    source_id = uuid4()
    content_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_service = MagicMock(spec=WebSourceIngestionService)
    mock_service.ingest_web_source = AsyncMock(
        return_value=ProjectWebSourceResponse(
            source_id=source_id,
            project_id=project_id,
            original_url="https://example.com/dup",
            final_url="https://example.com/dup",
            title="Duplicate Page",
            ingestion_status="completed",
            extracted_content_id=content_id,
            word_count=150,
            character_count=1000,
            content_hash="sha256dup",
            is_duplicate=True,
            extracted_at=now,
            created_at=now,
        )
    )

    app.dependency_overrides[get_web_source_service] = lambda: mock_service
    try:
        resp = client.post(
            f"/api/v1/projects/{project_id}/sources/web",
            json={"url": "https://example.com/dup"},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["is_duplicate"] is True
    finally:
        app.dependency_overrides.pop(get_web_source_service, None)


def test_api_ingest_web_source_project_not_found_returns_404(app: FastAPI, client: TestClient):
    """Verify endpoint returns 404 when research project does not exist."""
    project_id = uuid4()
    mock_service = MagicMock(spec=WebSourceIngestionService)
    mock_service.ingest_web_source = AsyncMock(
        side_effect=ProjectNotFoundError(f"Research project '{project_id}' not found.")
    )

    app.dependency_overrides[get_web_source_service] = lambda: mock_service
    try:
        resp = client.post(
            f"/api/v1/projects/{project_id}/sources/web",
            json={"url": "https://example.com/test"},
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_web_source_service, None)


def test_api_ingest_web_source_invalid_uuid_returns_422(client: TestClient):
    """Verify endpoint returns 422 when project_id is not a valid UUID."""
    resp = client.post(
        "/api/v1/projects/not-a-valid-uuid/sources/web",
        json={"url": "https://example.com/test"},
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_api_ingest_web_source_empty_content_returns_422(app: FastAPI, client: TestClient):
    """Verify endpoint returns 422 when extracted text is empty."""
    project_id = uuid4()
    mock_service = MagicMock(spec=WebSourceIngestionService)
    mock_service.ingest_web_source = AsyncMock(
        side_effect=EmptyExtractedContentError("Extracted page content is empty or contains no readable text.")
    )

    app.dependency_overrides[get_web_source_service] = lambda: mock_service
    try:
        resp = client.post(
            f"/api/v1/projects/{project_id}/sources/web",
            json={"url": "https://example.com/empty"},
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "empty" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_web_source_service, None)


def test_api_ingest_web_source_ssrf_blocked_returns_400(app: FastAPI, client: TestClient):
    """Verify SSRF attempt returns 400."""
    project_id = uuid4()
    mock_service = MagicMock(spec=WebSourceIngestionService)
    mock_service.ingest_web_source = AsyncMock(
        side_effect=SSRFBlockedError("Target resolves to prohibited IP address 127.0.0.1.")
    )

    app.dependency_overrides[get_web_source_service] = lambda: mock_service
    try:
        resp = client.post(
            f"/api/v1/projects/{project_id}/sources/web",
            json={"url": "http://127.0.0.1/admin"},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "prohibited" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_web_source_service, None)


def test_api_ingest_web_source_timeout_returns_504(app: FastAPI, client: TestClient):
    """Verify fetch timeout returns 504 Gateway Timeout."""
    project_id = uuid4()
    mock_service = MagicMock(spec=WebSourceIngestionService)
    mock_service.ingest_web_source = AsyncMock(
        side_effect=FetchTimeoutError("Connection timed out after 5.0 seconds.")
    )

    app.dependency_overrides[get_web_source_service] = lambda: mock_service
    try:
        resp = client.post(
            f"/api/v1/projects/{project_id}/sources/web",
            json={"url": "https://example.com/slow"},
        )
        assert resp.status_code == status.HTTP_504_GATEWAY_TIMEOUT
    finally:
        app.dependency_overrides.pop(get_web_source_service, None)


def test_api_ingest_web_source_network_error_returns_502(app: FastAPI, client: TestClient):
    """Verify upstream network error returns 502 Bad Gateway."""
    project_id = uuid4()
    mock_service = MagicMock(spec=WebSourceIngestionService)
    mock_service.ingest_web_source = AsyncMock(
        side_effect=FetchNetworkError("DNS resolution failed for hostname.")
    )

    app.dependency_overrides[get_web_source_service] = lambda: mock_service
    try:
        resp = client.post(
            f"/api/v1/projects/{project_id}/sources/web",
            json={"url": "https://unresolvable-domain.invalid"},
        )
        assert resp.status_code == status.HTTP_502_BAD_GATEWAY
    finally:
        app.dependency_overrides.pop(get_web_source_service, None)


def test_api_ingest_web_source_content_too_large_returns_413(app: FastAPI, client: TestClient):
    """Verify response exceeding 2 MB returns 413 Payload Too Large."""
    project_id = uuid4()
    mock_service = MagicMock(spec=WebSourceIngestionService)
    mock_service.ingest_web_source = AsyncMock(
        side_effect=ContentTooLargeError("Response body exceeded 2097152 bytes limit.")
    )

    app.dependency_overrides[get_web_source_service] = lambda: mock_service
    try:
        resp = client.post(
            f"/api/v1/projects/{project_id}/sources/web",
            json={"url": "https://example.com/huge"},
        )
        assert resp.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    finally:
        app.dependency_overrides.pop(get_web_source_service, None)


def test_api_ingest_web_source_unsupported_content_type_returns_422(app: FastAPI, client: TestClient):
    """Verify non-HTML content type returns 422 Unprocessable Entity."""
    project_id = uuid4()
    mock_service = MagicMock(spec=WebSourceIngestionService)
    mock_service.ingest_web_source = AsyncMock(
        side_effect=UnsupportedContentTypeError("Unsupported Content-Type: 'application/zip'.")
    )

    app.dependency_overrides[get_web_source_service] = lambda: mock_service
    try:
        resp = client.post(
            f"/api/v1/projects/{project_id}/sources/web",
            json={"url": "https://example.com/file.zip"},
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    finally:
        app.dependency_overrides.pop(get_web_source_service, None)


def test_api_ingest_web_source_database_unavailable_returns_503(app: FastAPI, client: TestClient):
    """Verify database unavailability returns 503 Service Unavailable."""
    project_id = uuid4()
    mock_service = MagicMock(spec=WebSourceIngestionService)
    mock_service.ingest_web_source = AsyncMock(
        side_effect=DatabaseUnavailableError("Database pool could not be initialized.")
    )

    app.dependency_overrides[get_web_source_service] = lambda: mock_service
    try:
        resp = client.post(
            f"/api/v1/projects/{project_id}/sources/web",
            json={"url": "https://example.com/test"},
        )
        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "unavailable" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_web_source_service, None)


def test_api_list_project_sources_returns_200(app: FastAPI, client: TestClient):
    """Verify GET /api/v1/projects/{project_id}/sources returns 200 and list of sources."""
    project_id = uuid4()
    now = datetime.now(timezone.utc)
    mock_service = MagicMock(spec=WebSourceIngestionService)
    mock_service.list_project_sources = AsyncMock(
        return_value=[
            SourceSummaryResponse(
                id=uuid4(),
                project_id=project_id,
                source_type="url",
                title="Source Summary",
                original_url="https://example.com",
                ingestion_status="completed",
                word_count=100,
                character_count=700,
                created_at=now,
                updated_at=now,
            )
        ]
    )

    app.dependency_overrides[get_web_source_service] = lambda: mock_service
    try:
        resp = client.get(f"/api/v1/projects/{project_id}/sources")
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Source Summary"
    finally:
        app.dependency_overrides.pop(get_web_source_service, None)


def test_api_get_project_source_detail_returns_200(app: FastAPI, client: TestClient):
    """Verify GET /api/v1/projects/{project_id}/sources/{source_id} returns 200 with detail."""
    project_id = uuid4()
    source_id = uuid4()
    now = datetime.now(timezone.utc)
    mock_service = MagicMock(spec=WebSourceIngestionService)
    mock_service.get_project_source_detail = AsyncMock(
        return_value=SourceDetailResponse(
            id=source_id,
            project_id=project_id,
            source_type="url",
            title="Detailed Source",
            original_url="https://example.com/detail",
            ingestion_status="completed",
            extracted_text="Full text content here",
            created_at=now,
            updated_at=now,
        )
    )

    app.dependency_overrides[get_web_source_service] = lambda: mock_service
    try:
        resp = client.get(f"/api/v1/projects/{project_id}/sources/{source_id}")
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["id"] == str(source_id)
        assert data["extracted_text"] == "Full text content here"
    finally:
        app.dependency_overrides.pop(get_web_source_service, None)


def test_openapi_schema_documents_sources_endpoints(client: TestClient):
    """Verify OpenAPI documentation includes all new source endpoints."""
    resp = client.get("/openapi.json")
    assert resp.status_code == status.HTTP_200_OK
    schema = resp.json()
    paths = schema["paths"]

    assert "/api/v1/projects/{project_id}/sources/web" in paths
    assert "post" in paths["/api/v1/projects/{project_id}/sources/web"]

    assert "/api/v1/projects/{project_id}/sources" in paths
    assert "get" in paths["/api/v1/projects/{project_id}/sources"]

    assert "/api/v1/projects/{project_id}/sources/{source_id}" in paths
    assert "get" in paths["/api/v1/projects/{project_id}/sources/{source_id}"]
