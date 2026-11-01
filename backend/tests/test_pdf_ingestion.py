"""Unit and integration tests for PDF upload validation, PyMuPDF extraction, and database persistence."""

from datetime import datetime, timezone
import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, status
from fastapi.testclient import TestClient
import pymupdf
import pytest

from app.core.auth import get_current_user
from app.core.ownership import OwnedProjectContext, get_owned_project
from app.core.config import Settings, get_settings
from app.db.connection import (
    DatabaseManager,
    DatabaseUnavailableError,
    get_db_manager,
)
from app.services.pdf.exceptions import (
    EmptyPDFError,
    InvalidPDFError,
    OversizedPageCountError,
    OversizedPDFError,
    PasswordProtectedPDFError,
    UnsupportedMediaTypeError,
)
from app.services.pdf.extractor import PDFExtractor
from app.services.pdf.schemas import (
    PDFExtractResult,
    PDFPageItem,
    ProjectPDFSourceResponse,
)
from app.services.pdf.service import (
    PDFSourceIngestionService,
    get_pdf_source_service,
)
from app.services.pdf.validator import PDFValidator
from app.services.sources.exceptions import ProjectNotFoundError
from tests.conftest import TEST_USER_ID


# =============================================================================
# Synthetic PDF Fixture Generators
# =============================================================================

def generate_pdf(
    pages_text: list[str] | None = None,
    metadata: dict[str, str] | None = None,
    password: str | None = None,
) -> bytes:
    """Generate an in-memory PDF binary with optional text, metadata, and encryption."""
    doc = pymupdf.open()
    if metadata:
        doc.set_metadata(metadata)
    if pages_text is not None:
        for text in pages_text:
            page = doc.new_page()
            if text:
                page.insert_text((50, 72), text)
    else:
        doc.new_page().insert_text((50, 72), "Sample standard research document text.")

    if password:
        pdf_bytes = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password)
    else:
        pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


# =============================================================================
# 1. PDFValidator Unit Tests
# =============================================================================

def test_validator_accepts_valid_pdf_signature():
    """Verify validate_signature_and_size passes on legitimate PDF bytes."""
    valid_pdf = generate_pdf(["Page content"])
    PDFValidator.validate_signature_and_size(valid_pdf, max_bytes=1024 * 1024)


def test_validator_rejects_empty_bytes():
    """Verify validate_signature_and_size raises EmptyPDFError on 0-byte input."""
    with pytest.raises(EmptyPDFError) as exc_info:
        PDFValidator.validate_signature_and_size(b"")
    assert "empty" in exc_info.value.message.lower()


def test_validator_rejects_oversized_pdf():
    """Verify validate_signature_and_size raises OversizedPDFError when bytes exceed limit."""
    valid_pdf = generate_pdf(["Some content"])
    with pytest.raises(OversizedPDFError) as exc_info:
        PDFValidator.validate_signature_and_size(valid_pdf, max_bytes=50)
    assert "maximum allowed size" in exc_info.value.message


def test_validator_rejects_missing_pdf_signature():
    """Verify validate_signature_and_size raises InvalidPDFError when %PDF- is missing."""
    corrupted = b"NOT_A_PDF_HEADER" + (b"0" * 100)
    with pytest.raises(InvalidPDFError) as exc_info:
        PDFValidator.validate_signature_and_size(corrupted)
    assert "%PDF-" in exc_info.value.message


def test_validator_validate_mime_type():
    """Verify MIME type validation accepts application/pdf and rejects non-PDF types."""
    PDFValidator.validate_mime_type("application/pdf")
    PDFValidator.validate_mime_type("application/pdf; charset=binary")
    PDFValidator.validate_mime_type("application/octet-stream")
    PDFValidator.validate_mime_type(None)

    with pytest.raises(UnsupportedMediaTypeError) as exc_info:
        PDFValidator.validate_mime_type("image/png")
    assert "image/png" in exc_info.value.message


def test_validator_sanitize_filename():
    """Verify sanitize_filename cleans path traversal and unsafe characters."""
    assert PDFValidator.sanitize_filename("report.pdf") == "report.pdf"
    assert PDFValidator.sanitize_filename("../../etc/passwd.pdf") == "passwd.pdf"
    assert PDFValidator.sanitize_filename("C:\\Windows\\System32\\test.pdf") == "test.pdf"
    assert PDFValidator.sanitize_filename("no_extension") == "no_extension.pdf"
    assert PDFValidator.sanitize_filename("") == "uploaded_document.pdf"
    assert PDFValidator.sanitize_filename(None) == "uploaded_document.pdf"

    # Truncation check
    huge_name = ("a" * 300) + ".pdf"
    sanitized = PDFValidator.sanitize_filename(huge_name)
    assert len(sanitized) == 255
    assert sanitized.endswith(".pdf")


def test_validator_rejects_password_protected_pdf():
    """Verify open_and_validate_structure raises PasswordProtectedPDFError on encrypted PDF."""
    encrypted_pdf = generate_pdf(["Secret"], password="pass123")
    with pytest.raises(PasswordProtectedPDFError) as exc_info:
        PDFValidator.open_and_validate_structure(encrypted_pdf)
    assert "password-protected" in exc_info.value.message.lower()


def test_validator_rejects_oversized_page_count():
    """Verify open_and_validate_structure raises OversizedPageCountError when pages exceed limit."""
    multi_page = generate_pdf(["P1", "P2", "P3", "P4", "P5"])
    with pytest.raises(OversizedPageCountError) as exc_info:
        PDFValidator.open_and_validate_structure(multi_page, max_pages=3)
    assert "exceeds maximum allowed limit" in exc_info.value.message


def test_validator_rejects_malformed_structure():
    """Verify open_and_validate_structure raises InvalidPDFError on corrupted PDF data."""
    malformed = b"%PDF-1.4\nCorrupted garbage data that cannot be parsed by PyMuPDF..."
    with pytest.raises(InvalidPDFError):
        PDFValidator.open_and_validate_structure(malformed)


# =============================================================================
# 2. PDFExtractor Unit Tests
# =============================================================================

def test_extractor_single_page_text():
    """Verify single-page text extraction returns 1-based page numbering, text, and word counts."""
    content = "Bharmafills is an AI-assisted Information Gap Detection Platform."
    pdf_bytes = generate_pdf([content])

    result = PDFExtractor.extract(pdf_bytes)
    assert result.page_count == 1
    assert result.extracted_pages_count == 1
    assert len(result.empty_pages) == 0
    assert result.readability_status == "fully_readable"
    assert result.pages[0].page_number == 1
    assert result.pages[0].has_text is True
    assert content in result.pages[0].text
    assert result.word_count == len(content.split())
    assert result.binary_hash == hashlib.sha256(pdf_bytes).hexdigest()
    assert result.text_hash is not None


def test_extractor_multi_page_ordering_and_numbering():
    """Verify multi-page PDF preserves 1-based page numbers and distinct page text."""
    pages = ["Page one content.", "Page two content with additional text.", "Page three content."]
    pdf_bytes = generate_pdf(pages)

    result = PDFExtractor.extract(pdf_bytes)
    assert result.page_count == 3
    assert result.extracted_pages_count == 3
    assert [p.page_number for p in result.pages] == [1, 2, 3]
    assert "Page one" in result.pages[0].text
    assert "Page two" in result.pages[1].text
    assert "Page three" in result.pages[2].text
    assert result.readability_status == "fully_readable"


def test_extractor_metadata_extraction():
    """Verify document metadata (title, author, subject) is extracted accurately."""
    meta = {
        "title": "Quantum Information Gaps 2026",
        "author": "Dr. Sarah Connor",
        "subject": "Quantum Computing",
    }
    pdf_bytes = generate_pdf(["Content"], metadata=meta)

    result = PDFExtractor.extract(pdf_bytes)
    assert result.title == "Quantum Information Gaps 2026"
    assert result.author == "Dr. Sarah Connor"
    assert result.subject == "Quantum Computing"


def test_extractor_missing_metadata_handled_gracefully():
    """Verify missing metadata fields evaluate to None without hallucination."""
    pdf_bytes = generate_pdf(["No metadata content"])
    result = PDFExtractor.extract(pdf_bytes)
    # PyMuPDF sets title to None or empty if absent
    assert result.author is None or result.author == ""
    assert result.subject is None or result.subject == ""


def test_extractor_unicode_text_preservation():
    """Verify multilingual and Unicode characters are preserved correctly."""
    unicode_content = "Crème brûlée, naïve façade, résumé, Español, Über, 100 EUR, ©2026"
    pdf_bytes = generate_pdf([unicode_content])

    result = PDFExtractor.extract(pdf_bytes)
    assert "Crème brûlée" in result.combined_text
    assert "Español" in result.combined_text
    assert "Über" in result.combined_text
    assert "©2026" in result.combined_text


def test_extractor_whitespace_normalization():
    """Verify redundant whitespace and excess blank lines are collapsed."""
    messy_text = "Line 1   with    multiple    spaces.\n\n\n\n\nLine 2 after huge gap."
    pdf_bytes = generate_pdf([messy_text])

    result = PDFExtractor.extract(pdf_bytes)
    assert "Line 1 with multiple spaces." in result.combined_text
    assert "\n\n\n" not in result.combined_text


def test_extractor_detects_empty_and_scanned_pages():
    """Verify empty pages are flagged with has_text=False and recorded in empty_pages."""
    # Page 1 has text, Page 2 is empty/scanned, Page 3 has text
    pdf_bytes = generate_pdf(["Page 1 text", "", "Page 3 text"])

    result = PDFExtractor.extract(pdf_bytes)
    assert result.page_count == 3
    assert result.extracted_pages_count == 2
    assert result.empty_pages == [2]
    assert result.readability_status == "partially_readable"
    assert result.pages[1].has_text is False


def test_extractor_fully_scanned_pdf():
    """Verify completely scanned/image-only PDF classifies as no_extractable_text."""
    # All pages empty of embedded text
    pdf_bytes = generate_pdf(["", "", ""])

    result = PDFExtractor.extract(pdf_bytes)
    assert result.page_count == 3
    assert result.extracted_pages_count == 0
    assert result.empty_pages == [1, 2, 3]
    assert result.readability_status == "no_extractable_text"
    assert result.combined_text == ""
    assert result.word_count == 0
    assert result.text_hash is None


def test_extractor_deterministic_content_hash():
    """Verify identical PDF bytes always produce identical binary hash."""
    pdf_bytes_1 = generate_pdf(["Deterministic test."])
    pdf_bytes_2 = bytes(pdf_bytes_1)

    res1 = PDFExtractor.extract(pdf_bytes_1)
    res2 = PDFExtractor.extract(pdf_bytes_2)
    assert res1.binary_hash == res2.binary_hash
    assert res1.text_hash == res2.text_hash


# =============================================================================
# 3. PDFSourceIngestionService Persistence & Duplicate Tests
# =============================================================================

@pytest.mark.asyncio
async def test_service_project_not_found_raises():
    """Verify service raises ProjectNotFoundError when project ID is missing."""
    project_id = uuid4()
    pdf_bytes = generate_pdf(["Test"])

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None  # Project not found

    mock_db = MagicMock(spec=DatabaseManager)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_conn
    mock_ctx.__aexit__.return_value = None
    mock_db.acquire_connection.return_value = mock_ctx

    service = PDFSourceIngestionService(db_manager=mock_db)
    with pytest.raises(ProjectNotFoundError) as exc_info:
        await service.ingest_pdf(project_id, "test.pdf", "application/pdf", pdf_bytes, user_id=TEST_USER_ID)
    assert str(project_id) in exc_info.value.message


@pytest.mark.asyncio
async def test_service_successful_ingestion_transaction():
    """Verify successful ingestion executes atomic transaction storing sources and extracted_content."""
    project_id = uuid4()
    source_id = uuid4()
    content_id = uuid4()
    now = datetime.now(timezone.utc)
    pdf_bytes = generate_pdf(["Valid scientific publication excerpt."], metadata={"title": "Quantum Paper"})

    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = [
        {"id": project_id, "title": "Research Proj", "status": "Draft", "user_id": TEST_USER_ID},  # validate project
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

    service = PDFSourceIngestionService(db_manager=mock_db)
    res = await service.ingest_pdf(project_id, "quantum_paper.pdf", "application/pdf", pdf_bytes, user_id=TEST_USER_ID)

    assert res.source_id == source_id
    assert res.project_id == project_id
    assert res.title == "Quantum Paper"
    assert res.original_filename == "quantum_paper.pdf"
    assert res.ingestion_status == "completed"
    assert res.readability_status == "fully_readable"
    assert res.extracted_content_id == content_id
    assert res.is_duplicate is False
    assert res.word_count > 0
    mock_conn.transaction.assert_called_once()


@pytest.mark.asyncio
async def test_service_duplicate_binary_hash():
    """Verify identical PDF binary upload in same project resolves as duplicate with is_duplicate=True."""
    project_id = uuid4()
    source_id = uuid4()
    content_id = uuid4()
    now = datetime.now(timezone.utc)
    pdf_bytes = generate_pdf(["Text to duplicate"])
    binary_hash = hashlib.sha256(pdf_bytes).hexdigest()

    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = [
        {"id": project_id, "title": "Research Proj", "status": "Draft", "user_id": TEST_USER_ID},
        {  # duplicate found
            "id": source_id,
            "project_id": project_id,
            "title": "Existing PDF Source",
            "original_filename": "first_upload.pdf",
            "source_type": "pdf",
            "ingestion_status": "completed",
            "content_hash": binary_hash,
            "file_metadata": {
                "author": "Dr. Smith",
                "page_count": 1,
                "extracted_pages_count": 1,
                "empty_pages": [],
                "word_count": 25,
                "character_count": 160,
                "readability_status": "fully_readable",
            },
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

    service = PDFSourceIngestionService(db_manager=mock_db)
    # Different filename but identical PDF bytes
    res = await service.ingest_pdf(project_id, "second_upload_different_name.pdf", "application/pdf", pdf_bytes, user_id=TEST_USER_ID)

    assert res.source_id == source_id
    assert res.is_duplicate is True
    assert res.title == "Existing PDF Source"
    assert res.author == "Dr. Smith"
    # No insert transaction should have been opened
    mock_conn.transaction.assert_not_called()


@pytest.mark.asyncio
async def test_service_scanned_pdf_persisted_as_failed():
    """Verify image-only / scanned PDF is tracked as failed source without extracted_content insertion."""
    project_id = uuid4()
    source_id = uuid4()
    now = datetime.now(timezone.utc)
    scanned_pdf = generate_pdf(["", ""])  # 2 empty pages

    captured_status = None
    captured_error = None

    async def mock_fetchrow(query, *args):
        nonlocal captured_status, captured_error
        if "research_projects" in query:
            return {"id": project_id, "title": "Proj", "status": "Draft", "user_id": TEST_USER_ID}
        if "SELECT s.id" in query:
            return None  # no duplicate
        if "INSERT INTO public.sources" in query:
            captured_status = args[4]
            captured_error = args[5]
            return {"id": source_id, "created_at": now}
        if "INSERT INTO public.extracted_content" in query:
            raise AssertionError("extracted_content must NOT be inserted for scanned document!")
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

    service = PDFSourceIngestionService(db_manager=mock_db)
    res = await service.ingest_pdf(project_id, "scanned_invoice.pdf", "application/pdf", scanned_pdf, user_id=TEST_USER_ID)

    assert res.source_id == source_id
    assert res.ingestion_status == "failed"
    assert res.readability_status == "no_extractable_text"
    assert res.extracted_content_id is None
    assert captured_status == "failed"
    assert "OCR is not supported" in (captured_error or "")


@pytest.mark.asyncio
async def test_service_database_unavailable_raises():
    """Verify DatabaseUnavailableError propagates when database pool fails."""
    project_id = uuid4()
    pdf_bytes = generate_pdf(["Text"])

    mock_db = MagicMock(spec=DatabaseManager)
    mock_db.acquire_connection.side_effect = DatabaseUnavailableError("Connection pool down.")

    service = PDFSourceIngestionService(db_manager=mock_db)
    with pytest.raises(DatabaseUnavailableError):
        await service.ingest_pdf(project_id, "file.pdf", "application/pdf", pdf_bytes, user_id=TEST_USER_ID)


# =============================================================================
# 4. HTTP API Endpoint Integration Tests (POST /projects/{project_id}/sources/pdf)
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

def test_api_ingest_pdf_success_returns_201(app: FastAPI, client: TestClient):
    """Verify POST /api/v1/projects/{project_id}/sources/pdf returns 201 on new PDF."""
    project_id = uuid4()
    source_id = uuid4()
    content_id = uuid4()
    now = datetime.now(timezone.utc)
    pdf_bytes = generate_pdf(["Scientific text on information gaps."])

    mock_service = MagicMock(spec=PDFSourceIngestionService)
    mock_service.ingest_pdf = AsyncMock(
        return_value=ProjectPDFSourceResponse(
            source_id=source_id,
            project_id=project_id,
            original_filename="research.pdf",
            source_type="pdf",
            title="Scientific Research Document",
            author="Dr. Turing",
            ingestion_status="completed",
            readability_status="fully_readable",
            extracted_content_id=content_id,
            page_count=1,
            extracted_pages_count=1,
            empty_pages=[],
            word_count=45,
            character_count=320,
            content_hash="mockbinaryhash123",
            is_duplicate=False,
            extracted_at=now,
            created_at=now,
        )
    )

    app.dependency_overrides[get_pdf_source_service] = lambda: mock_service
    try:
        resp = client.post(
            f"/api/v1/projects/{project_id}/sources/pdf",
            files={"file": ("research.pdf", pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["source_id"] == str(source_id)
        assert data["title"] == "Scientific Research Document"
        assert data["is_duplicate"] is False
        assert data["readability_status"] == "fully_readable"
    finally:
        app.dependency_overrides.pop(get_pdf_source_service, None)


def test_api_ingest_pdf_duplicate_returns_200(app: FastAPI, client: TestClient):
    """Verify POST /api/v1/projects/{project_id}/sources/pdf returns 200 when duplicate resolved."""
    project_id = uuid4()
    source_id = uuid4()
    content_id = uuid4()
    now = datetime.now(timezone.utc)
    pdf_bytes = generate_pdf(["Duplicate content"])

    mock_service = MagicMock(spec=PDFSourceIngestionService)
    mock_service.ingest_pdf = AsyncMock(
        return_value=ProjectPDFSourceResponse(
            source_id=source_id,
            project_id=project_id,
            original_filename="research.pdf",
            source_type="pdf",
            title="Existing PDF",
            author=None,
            ingestion_status="completed",
            readability_status="fully_readable",
            extracted_content_id=content_id,
            page_count=1,
            extracted_pages_count=1,
            empty_pages=[],
            word_count=30,
            character_count=200,
            content_hash="mockduplicatehash",
            is_duplicate=True,
            extracted_at=now,
            created_at=now,
        )
    )

    app.dependency_overrides[get_pdf_source_service] = lambda: mock_service
    try:
        resp = client.post(
            f"/api/v1/projects/{project_id}/sources/pdf",
            files={"file": ("research.pdf", pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["is_duplicate"] is True
    finally:
        app.dependency_overrides.pop(get_pdf_source_service, None)


def test_api_ingest_pdf_project_not_found_returns_404(app: FastAPI, client: TestClient):
    """Verify endpoint returns 404 when project does not exist."""
    project_id = uuid4()
    pdf_bytes = generate_pdf(["Text"])

    mock_service = MagicMock(spec=PDFSourceIngestionService)
    mock_service.ingest_pdf = AsyncMock(
        side_effect=ProjectNotFoundError(f"Research project '{project_id}' not found.")
    )

    app.dependency_overrides[get_pdf_source_service] = lambda: mock_service
    try:
        resp = client.post(
            f"/api/v1/projects/{project_id}/sources/pdf",
            files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_pdf_source_service, None)


def test_api_ingest_pdf_invalid_uuid_returns_422(client: TestClient):
    """Verify endpoint returns 422 when project_id is not a valid UUID."""
    pdf_bytes = generate_pdf(["Text"])
    resp = client.post(
        "/api/v1/projects/not-a-valid-uuid/sources/pdf",
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_api_ingest_pdf_unsupported_media_type_returns_415(client: TestClient):
    """Verify uploading non-PDF MIME type returns 415 Unsupported Media Type."""
    project_id = uuid4()
    resp = client.post(
        f"/api/v1/projects/{project_id}/sources/pdf",
        files={"file": ("test.png", b"\x89PNG\r\n\x1a\nFake PNG", "image/png")},
    )
    assert resp.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE


def test_api_ingest_pdf_missing_header_signature_returns_400(client: TestClient):
    """Verify uploading non-PDF content with .pdf name returns 400 Bad Request."""
    project_id = uuid4()
    resp = client.post(
        f"/api/v1/projects/{project_id}/sources/pdf",
        files={"file": ("test.pdf", b"Plain text file that is not a PDF", "application/pdf")},
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "%PDF-" in resp.json()["detail"]


def test_api_ingest_pdf_empty_file_returns_400(client: TestClient):
    """Verify uploading 0 bytes returns 400 Bad Request."""
    project_id = uuid4()
    resp = client.post(
        f"/api/v1/projects/{project_id}/sources/pdf",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


def test_api_ingest_pdf_password_protected_returns_400(client: TestClient):
    """Verify encrypted/password-protected PDF upload returns 400 Bad Request."""
    project_id = uuid4()
    encrypted = generate_pdf(["Secret"], password="pass")
    resp = client.post(
        f"/api/v1/projects/{project_id}/sources/pdf",
        files={"file": ("encrypted.pdf", encrypted, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "password-protected" in resp.json()["detail"].lower()


def test_api_ingest_pdf_oversized_file_returns_413(app: FastAPI, client: TestClient):
    """Verify file exceeding PDF_MAX_UPLOAD_BYTES returns 413 Payload Too Large."""
    project_id = uuid4()
    tiny_settings = Settings(PDF_MAX_UPLOAD_BYTES=1024, _env_file=None)
    # Generate a PDF with multiple pages exceeding 1024 bytes
    pdf_bytes = generate_pdf([
        "Page 1: Extensive text content designed to exceed 1024 bytes limit.",
        "Page 2: Additional paragraph data pushing the binary well over the threshold.",
        "Page 3: Final confirmation page ensuring the binary is larger than 1 kilobyte.",
    ])
    assert len(pdf_bytes) > 1024

    app.dependency_overrides[get_settings] = lambda: tiny_settings
    try:
        resp = client.post(
            f"/api/v1/projects/{project_id}/sources/pdf",
            files={"file": ("huge.pdf", pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_api_ingest_pdf_database_unavailable_returns_503(app: FastAPI, client: TestClient):
    """Verify database unavailable error returns 503 Service Unavailable."""
    project_id = uuid4()
    pdf_bytes = generate_pdf(["Text"])

    mock_service = MagicMock(spec=PDFSourceIngestionService)
    mock_service.ingest_pdf = AsyncMock(
        side_effect=DatabaseUnavailableError("Database connection down.")
    )

    app.dependency_overrides[get_pdf_source_service] = lambda: mock_service
    try:
        resp = client.post(
            f"/api/v1/projects/{project_id}/sources/pdf",
            files={"file": ("doc.pdf", pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "unavailable" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_pdf_source_service, None)


def test_openapi_schema_documents_pdf_endpoint(client: TestClient):
    """Verify OpenAPI documentation includes POST /api/v1/projects/{project_id}/sources/pdf."""
    resp = client.get("/openapi.json")
    assert resp.status_code == status.HTTP_200_OK
    schema = resp.json()
    paths = schema["paths"]

    pdf_path = "/api/v1/projects/{project_id}/sources/pdf"
    assert pdf_path in paths
    assert "post" in paths[pdf_path]
    operation = paths[pdf_path]["post"]
    assert "Upload and ingest a PDF document" in operation["summary"]
