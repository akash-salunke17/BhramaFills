"""Comprehensive HTTP-level security tests for Phase D3: Protected API Route Integration & Ownership Enforcement.

Verifies:
1. Mandatory project ownership rule: research_projects.user_id == authenticated_user.id
2. Generic 404 masking: unauthorized, ownerless, soft-deleted, and nonexistent projects return identical 404.
3. Source access ownership enforcement across all 5 sources endpoints.
4. Evidence and extraction-run ownership enforcement across all 5 evidence endpoints.
5. Child-resource IDOR protection: cross-project resource IDs (sources, runs, evidence) return 404.
6. Background/inline persistence preserves authenticated user identity without substitution.
7. Security regression: unauthenticated/malformed tokens return 401; public endpoints remain accessible.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import time
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
import jwt
import pytest

from app.core.auth import SupabaseJWTVerifier, get_jwt_verifier
from app.core.auth_schemas import AuthenticatedUser
from app.core.config import Settings
from app.core.ownership import (
    OwnedProjectContext,
    ProjectAccessDeniedError,
    ProjectNotFoundError,
    ResourceMismatchError,
    get_owned_project,
)
from app.db.connection import DatabaseManager, get_db_manager
from app.main import create_app
from app.services.ai import (
    EvidenceExtractionResult,
    EvidenceExtractionService,
    EvidenceLocation,
    EvidenceSourceType,
    ExtractionStatus,
    ExtractedFact,
    FactType,
    RepresentationType,
    SourceClaim,
    get_evidence_extraction_service,
)
from app.services.evidence import (
    EvidencePersistenceService,
    ExtractionRunListResponse,
    ExtractionRunNotFoundError,
    ExtractionRunResponse,
    PersistedEvidenceRunResponse,
    PersistedFactResponse,
    ProjectEvidenceResponse,
    SourceMismatchError,
    get_evidence_persistence_service,
)
from app.services.pdf.schemas import ProjectPDFSourceResponse
from app.services.pdf.service import PDFSourceIngestionService, get_pdf_source_service
from app.services.sources.exceptions import SourceNotFoundError
from app.services.sources.schemas import (
    ProjectWebSourceResponse,
    SourceDetailResponse,
    SourceSummaryResponse,
)
from app.services.sources.web_source_service import (
    WebSourceIngestionService,
    get_web_source_service,
)


# =============================================================================
# Identifiers & Synthetic Fixtures
# =============================================================================

USER_A_ID = UUID("00000000-0000-4000-a000-000000000001")
USER_B_ID = UUID("00000000-0000-4000-a000-000000000002")

PROJECT_A_ID = UUID("11111111-1111-4000-a000-000000000001")
PROJECT_B_ID = UUID("22222222-2222-4000-a000-000000000002")
PROJECT_UNOWNED_ID = UUID("33333333-3333-4000-a000-000000000003")
PROJECT_DELETED_ID = UUID("44444444-4444-4000-a000-000000000004")
PROJECT_NONEXISTENT_ID = UUID("55555555-5555-4000-a000-000000000005")

SOURCE_A_ID = UUID("aaaa1111-1111-4000-a000-000000000001")
SOURCE_B_ID = UUID("bbbb2222-2222-4000-a000-000000000002")

RUN_A_ID = UUID("aaaa3333-1111-4000-a000-000000000001")
RUN_B_ID = UUID("bbbb3333-2222-4000-a000-000000000002")

NOW = datetime.now(timezone.utc)


def create_token_for_user(user_id: UUID, email: str, private_key) -> str:
    """Helper generating signed ES256 JWT for arbitrary user identity."""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": "authenticated",
        "iss": "https://test-project.supabase.co/auth/v1",
        "aud": "authenticated",
        "exp": now + 7200,
        "iat": now,
        "app_metadata": {"provider": "email"},
        "user_metadata": {"user_id": str(user_id)},
    }
    return jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": "test-session-kid-1"})


# =============================================================================
# Test Setup & Isolation Fixtures
# =============================================================================

@pytest.fixture
def mock_db_manager() -> DatabaseManager:
    """Mock DatabaseManager with truthful simulated database state for ownership checks."""
    mock_db = MagicMock(spec=DatabaseManager)
    mock_db.is_configured = True

    mock_conn = AsyncMock()

    async def mock_fetchrow(query: str, *args):
        # 1. Project queries
        if "FROM public.research_projects" in query:
            project_id = args[0]
            if project_id == PROJECT_A_ID:
                return {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "Project A", "status": "In Progress"}
            elif project_id == PROJECT_B_ID:
                return {"id": PROJECT_B_ID, "user_id": USER_B_ID, "title": "Project B", "status": "Active"}
            elif project_id == PROJECT_UNOWNED_ID:
                return {"id": PROJECT_UNOWNED_ID, "user_id": None, "title": "Unowned", "status": "Draft"}
            elif project_id == PROJECT_DELETED_ID:
                # Query has deleted_at IS NULL -> soft-deleted projects return None
                return None
            elif project_id == PROJECT_NONEXISTENT_ID:
                return None
            return None

        # 2. Source queries
        if "FROM public.sources" in query:
            source_id = args[0]
            if source_id == SOURCE_A_ID:
                return {
                    "id": SOURCE_A_ID,
                    "project_id": PROJECT_A_ID,
                    "title": "Source A",
                    "source_type": "url",
                    "original_url": "https://example.com/a",
                    "original_filename": None,
                    "ingestion_status": "completed",
                }
            elif source_id == SOURCE_B_ID:
                return {
                    "id": SOURCE_B_ID,
                    "project_id": PROJECT_B_ID,
                    "title": "Source B",
                    "source_type": "url",
                    "original_url": "https://example.com/b",
                    "original_filename": None,
                    "ingestion_status": "completed",
                }
            return None

        return None

    mock_conn.fetchrow.side_effect = mock_fetchrow

    mock_acquire = AsyncMock()
    mock_acquire.__aenter__.return_value = mock_conn
    mock_acquire.__aexit__.return_value = None
    mock_db.acquire_connection.return_value = mock_acquire

    return mock_db


@pytest.fixture
def test_app_with_ownership(test_settings: Settings, test_verifier: SupabaseJWTVerifier, mock_db_manager: DatabaseManager) -> FastAPI:
    """Create FastAPI application wired with real get_owned_project dependency and mock DB."""
    app = create_app(settings=test_settings)
    app.dependency_overrides[get_jwt_verifier] = lambda: test_verifier
    app.dependency_overrides[get_db_manager] = lambda: mock_db_manager
    return app


@pytest.fixture
def client_a(test_app_with_ownership: FastAPI, test_ec_keypair) -> TestClient:
    """TestClient authenticated as User A."""
    private_key, _ = test_ec_keypair
    token_a = create_token_for_user(USER_A_ID, "user.a@bharmafills.org", private_key)
    return TestClient(test_app_with_ownership, base_url="http://testserver", headers={"Authorization": f"Bearer {token_a}"})


@pytest.fixture
def client_b(test_app_with_ownership: FastAPI, test_ec_keypair) -> TestClient:
    """TestClient authenticated as User B."""
    private_key, _ = test_ec_keypair
    token_b = create_token_for_user(USER_B_ID, "user.b@bharmafills.org", private_key)
    return TestClient(test_app_with_ownership, base_url="http://testserver", headers={"Authorization": f"Bearer {token_b}"})


@pytest.fixture
def unauth_client(test_app_with_ownership: FastAPI) -> TestClient:
    """TestClient without Authorization header."""
    return TestClient(test_app_with_ownership, base_url="http://testserver")


# =============================================================================
# Domain Service Mocks Fixture
# =============================================================================

@pytest.fixture(autouse=True)
def mock_domain_services(test_app_with_ownership: FastAPI):
    """Wire mock domain services simulating business logic and child-resource checks."""
    mock_web = MagicMock(spec=WebSourceIngestionService)
    mock_pdf = MagicMock(spec=PDFSourceIngestionService)
    mock_extract = MagicMock(spec=EvidenceExtractionService)
    mock_persist = MagicMock(spec=EvidencePersistenceService)

    mock_extract.is_configured = True
    mock_persist.is_configured = True

    # 1. Web Service Mocks
    async def mock_ingest_web_source(project_id: UUID, url: str, user_id: UUID):
        assert isinstance(user_id, UUID)
        return ProjectWebSourceResponse(
            source_id=uuid4(),
            project_id=project_id,
            original_url=url,
            final_url=url,
            title="Ingested Web Source",
            ingestion_status="completed",
            extracted_content_id=uuid4(),
            word_count=100,
            character_count=600,
            content_hash="mockhash",
            is_duplicate=False,
            extracted_at=NOW,
            created_at=NOW,
        )

    async def mock_list_project_sources(project_id: UUID, user_id: UUID):
        assert isinstance(user_id, UUID)
        return [
            SourceSummaryResponse(
                id=SOURCE_A_ID if project_id == PROJECT_A_ID else SOURCE_B_ID,
                project_id=project_id,
                source_type="url",
                title="Mock Source",
                original_url="https://example.com",
                original_filename=None,
                ingestion_status="completed",
                content_hash="mockhash",
                word_count=50,
                character_count=300,
                created_at=NOW,
                updated_at=NOW,
            )
        ]

    async def mock_get_project_source_detail(project_id: UUID, source_id: UUID, user_id: UUID):
        assert isinstance(user_id, UUID)
        # Verify source belongs to project!
        if (project_id == PROJECT_A_ID and source_id == SOURCE_A_ID) or (project_id == PROJECT_B_ID and source_id == SOURCE_B_ID):
            return SourceDetailResponse(
                id=source_id,
                project_id=project_id,
                source_type="url",
                title="Source Detail",
                original_url="https://example.com/detail",
                original_filename=None,
                ingestion_status="completed",
                content_hash="mockhash",
                extracted_content_id=uuid4(),
                extracted_text="Content text for evidence extraction.",
                extraction_metadata={},
                extraction_method="bs4",
                extraction_version="1.0",
                extracted_at=NOW,
                word_count=50,
                character_count=300,
                created_at=NOW,
                updated_at=NOW,
            )
        raise SourceNotFoundError(f"Source '{source_id}' was not found in project '{project_id}'.")

    mock_web.ingest_web_source.side_effect = mock_ingest_web_source
    mock_web.list_project_sources.side_effect = mock_list_project_sources
    mock_web.get_project_source_detail.side_effect = mock_get_project_source_detail

    # 2. PDF Service Mocks
    async def mock_ingest_pdf(project_id: UUID, filename: str, content_type: str, pdf_bytes: bytes, user_id: UUID):
        assert isinstance(user_id, UUID)
        return ProjectPDFSourceResponse(
            source_id=uuid4(),
            project_id=project_id,
            original_filename=filename,
            source_type="pdf",
            title="Ingested PDF",
            author="Author",
            ingestion_status="completed",
            readability_status="fully_readable",
            extracted_content_id=uuid4(),
            page_count=1,
            extracted_pages_count=1,
            empty_pages=[],
            word_count=120,
            character_count=800,
            content_hash="pdfhash",
            is_duplicate=False,
            extracted_at=NOW,
            created_at=NOW,
        )

    mock_pdf.ingest_pdf.side_effect = mock_ingest_pdf

    # 3. Extraction Service Mocks
    async def mock_extract_source_evidence(source_id: str, **kwargs):
        fact = ExtractedFact(
            fact_id="fact-1",
            statement="Ice sheet lost mass rapidly.",
            fact_type=FactType.STATISTICAL,
            location=EvidenceLocation(source_id=source_id, source_type=EvidenceSourceType.WEB),
            evidence_text="Ice sheet lost mass rapidly.",
            representation_type=RepresentationType.DIRECT_QUOTE,
            confidence=0.95,
        )
        return EvidenceExtractionResult(
            source_id=source_id,
            source_type=EvidenceSourceType.WEB,
            facts=[fact],
            claims=[],
            extraction_status=ExtractionStatus.SUCCESS,
            warnings=[],
            errors=[],
            extracted_at=NOW,
        )

    mock_extract.extract_source_evidence.side_effect = mock_extract_source_evidence

    # 4. Persistence Service Mocks
    async def mock_persist_extraction_result(project_id: UUID, source_id: UUID, result, user_id: UUID, **kwargs):
        assert isinstance(user_id, UUID)
        # Child resource check: Source A belongs to Project A; Source B belongs to Project B
        if (project_id == PROJECT_A_ID and source_id != SOURCE_A_ID) or (project_id == PROJECT_B_ID and source_id != SOURCE_B_ID):
            raise SourceMismatchError(f"Source '{source_id}' does not belong to project '{project_id}'.")

        run = ExtractionRunResponse(
            id=RUN_A_ID if project_id == PROJECT_A_ID else RUN_B_ID,
            project_id=project_id,
            source_id=source_id,
            provider="openrouter",
            model_name="nemotron",
            extraction_status=ExtractionStatus.SUCCESS,
            source_truncated=False,
            source_character_count=1000,
            processed_character_count=1000,
            facts_count=1,
            claims_count=0,
            warnings=[],
            errors=[],
            run_metadata={},
            extracted_at=NOW,
            created_at=NOW,
        )
        return PersistedEvidenceRunResponse(run=run, facts=[], claims=[])

    async def mock_get_source_evidence(project_id: UUID, source_id: UUID, user_id: UUID, **kwargs):
        assert isinstance(user_id, UUID)
        if (project_id == PROJECT_A_ID and source_id != SOURCE_A_ID) or (project_id == PROJECT_B_ID and source_id != SOURCE_B_ID):
            raise SourceMismatchError(f"Source '{source_id}' does not belong to project '{project_id}'.")
        return ProjectEvidenceResponse(
            project_id=project_id,
            source_id=source_id,
            total_facts=1,
            total_claims=0,
            limit=50,
            offset=0,
            facts=[],
            claims=[],
        )

    async def mock_get_project_evidence(project_id: UUID, user_id: UUID, source_id: UUID | None = None, **kwargs):
        assert isinstance(user_id, UUID)
        if source_id and ((project_id == PROJECT_A_ID and source_id != SOURCE_A_ID) or (project_id == PROJECT_B_ID and source_id != SOURCE_B_ID)):
            raise SourceMismatchError(f"Source '{source_id}' does not belong to project '{project_id}'.")
        return ProjectEvidenceResponse(
            project_id=project_id,
            source_id=source_id,
            total_facts=2,
            total_claims=1,
            limit=50,
            offset=0,
            facts=[],
            claims=[],
        )

    async def mock_list_extraction_runs(project_id: UUID, user_id: UUID, source_id: UUID | None = None, **kwargs):
        assert isinstance(user_id, UUID)
        if source_id and ((project_id == PROJECT_A_ID and source_id != SOURCE_A_ID) or (project_id == PROJECT_B_ID and source_id != SOURCE_B_ID)):
            raise SourceMismatchError(f"Source '{source_id}' does not belong to project '{project_id}'.")
        run = ExtractionRunResponse(
            id=RUN_A_ID if project_id == PROJECT_A_ID else RUN_B_ID,
            project_id=project_id,
            source_id=source_id or SOURCE_A_ID,
            provider="openrouter",
            model_name="nemotron",
            extraction_status=ExtractionStatus.SUCCESS,
            source_truncated=False,
            source_character_count=1000,
            processed_character_count=1000,
            facts_count=1,
            claims_count=0,
            warnings=[],
            errors=[],
            run_metadata={},
            extracted_at=NOW,
            created_at=NOW,
        )
        return ExtractionRunListResponse(total_runs=1, limit=20, offset=0, runs=[run])

    async def mock_get_extraction_run_detail(project_id: UUID, run_id: UUID, user_id: UUID):
        assert isinstance(user_id, UUID)
        if (project_id == PROJECT_A_ID and run_id != RUN_A_ID) or (project_id == PROJECT_B_ID and run_id != RUN_B_ID):
            raise ExtractionRunNotFoundError(f"Extraction run '{run_id}' not found in project '{project_id}'.")
        run = ExtractionRunResponse(
            id=run_id,
            project_id=project_id,
            source_id=SOURCE_A_ID if project_id == PROJECT_A_ID else SOURCE_B_ID,
            provider="openrouter",
            model_name="nemotron",
            extraction_status=ExtractionStatus.SUCCESS,
            source_truncated=False,
            source_character_count=1000,
            processed_character_count=1000,
            facts_count=1,
            claims_count=0,
            warnings=[],
            errors=[],
            run_metadata={},
            extracted_at=NOW,
            created_at=NOW,
        )
        return PersistedEvidenceRunResponse(run=run, facts=[], claims=[])

    mock_persist.persist_extraction_result.side_effect = mock_persist_extraction_result
    mock_persist.get_source_evidence.side_effect = mock_get_source_evidence
    mock_persist.get_project_evidence.side_effect = mock_get_project_evidence
    mock_persist.list_extraction_runs.side_effect = mock_list_extraction_runs
    mock_persist.get_extraction_run_detail.side_effect = mock_get_extraction_run_detail

    test_app_with_ownership.dependency_overrides[get_web_source_service] = lambda: mock_web
    test_app_with_ownership.dependency_overrides[get_pdf_source_service] = lambda: mock_pdf
    test_app_with_ownership.dependency_overrides[get_evidence_extraction_service] = lambda: mock_extract
    test_app_with_ownership.dependency_overrides[get_evidence_persistence_service] = lambda: mock_persist
    yield
    test_app_with_ownership.dependency_overrides.pop(get_web_source_service, None)
    test_app_with_ownership.dependency_overrides.pop(get_pdf_source_service, None)
    test_app_with_ownership.dependency_overrides.pop(get_evidence_extraction_service, None)
    test_app_with_ownership.dependency_overrides.pop(get_evidence_persistence_service, None)


# =============================================================================
# 1. Project Ownership & Generic 404 Masking Tests
# =============================================================================

def test_owner_accesses_own_project_successfully(client_a: TestClient):
    """Verify User A can successfully list sources for Project A (which User A owns)."""
    resp = client_a.get(f"/api/v1/projects/{PROJECT_A_ID}/sources")
    assert resp.status_code == status.HTTP_200_OK
    assert len(resp.json()) == 1


def test_foreign_user_receives_generic_404_on_project_access(client_b: TestClient):
    """Verify User B receives generic 404 when attempting to access Project A (owned by User A).

    IDOR Privacy Invariant:
    Must NOT leak whether Project A exists or who owns it.
    """
    resp = client_b.get(f"/api/v1/projects/{PROJECT_A_ID}/sources")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["detail"] == f"Research project '{PROJECT_A_ID}' was not found."


def test_ownerless_project_receives_identical_generic_404(client_a: TestClient):
    """Verify ownerless project (user_id IS NULL) receives identical generic 404 response."""
    resp = client_a.get(f"/api/v1/projects/{PROJECT_UNOWNED_ID}/sources")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["detail"] == f"Research project '{PROJECT_UNOWNED_ID}' was not found."


def test_soft_deleted_project_receives_identical_generic_404(client_a: TestClient):
    """Verify soft-deleted project (deleted_at IS NOT NULL) receives identical generic 404."""
    resp = client_a.get(f"/api/v1/projects/{PROJECT_DELETED_ID}/sources")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["detail"] == f"Research project '{PROJECT_DELETED_ID}' was not found."


def test_nonexistent_project_receives_identical_generic_404(client_a: TestClient):
    """Verify nonexistent project receives identical generic 404 format."""
    resp = client_a.get(f"/api/v1/projects/{PROJECT_NONEXISTENT_ID}/sources")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["detail"] == f"Research project '{PROJECT_NONEXISTENT_ID}' was not found."


# =============================================================================
# 2. Source Access Ownership Enforcement (All 5 Sources Endpoints)
# =============================================================================

def test_owner_can_ingest_web_source_foreign_user_blocked(client_a: TestClient, client_b: TestClient):
    """Verify owner can ingest web source into Project A; User B receives 404."""
    payload = {"url": "https://example.com/test"}
    # Owner succeeds
    resp_a = client_a.post(f"/api/v1/projects/{PROJECT_A_ID}/sources/web", json=payload)
    assert resp_a.status_code == status.HTTP_201_CREATED

    # Foreign user blocked with 404
    resp_b = client_b.post(f"/api/v1/projects/{PROJECT_A_ID}/sources/web", json=payload)
    assert resp_b.status_code == status.HTTP_404_NOT_FOUND
    assert resp_b.json()["detail"] == f"Research project '{PROJECT_A_ID}' was not found."


def test_owner_can_ingest_pdf_foreign_user_blocked(client_a: TestClient, client_b: TestClient):
    """Verify owner can upload PDF into Project A; User B receives 404."""
    pdf_file = {"file": ("paper.pdf", b"%PDF-1.4 sample pdf content", "application/pdf")}
    # Owner succeeds
    resp_a = client_a.post(f"/api/v1/projects/{PROJECT_A_ID}/sources/pdf", files=pdf_file)
    assert resp_a.status_code == status.HTTP_201_CREATED

    # Foreign user blocked with 404
    pdf_file_b = {"file": ("paper.pdf", b"%PDF-1.4 sample pdf content", "application/pdf")}
    resp_b = client_b.post(f"/api/v1/projects/{PROJECT_A_ID}/sources/pdf", files=pdf_file_b)
    assert resp_b.status_code == status.HTTP_404_NOT_FOUND
    assert resp_b.json()["detail"] == f"Research project '{PROJECT_A_ID}' was not found."


def test_owner_can_list_sources_foreign_user_blocked(client_a: TestClient, client_b: TestClient):
    """Verify owner can list sources in Project A; User B receives 404."""
    resp_a = client_a.get(f"/api/v1/projects/{PROJECT_A_ID}/sources")
    assert resp_a.status_code == status.HTTP_200_OK

    resp_b = client_b.get(f"/api/v1/projects/{PROJECT_A_ID}/sources")
    assert resp_b.status_code == status.HTTP_404_NOT_FOUND


def test_owner_can_get_source_detail_foreign_user_blocked(client_a: TestClient, client_b: TestClient):
    """Verify owner can view source detail; User B receives 404."""
    resp_a = client_a.get(f"/api/v1/projects/{PROJECT_A_ID}/sources/{SOURCE_A_ID}")
    assert resp_a.status_code == status.HTTP_200_OK

    resp_b = client_b.get(f"/api/v1/projects/{PROJECT_A_ID}/sources/{SOURCE_A_ID}")
    assert resp_b.status_code == status.HTTP_404_NOT_FOUND


def test_owner_can_extract_evidence_foreign_user_blocked(client_a: TestClient, client_b: TestClient):
    """Verify owner can trigger evidence extraction; User B receives 404."""
    resp_a = client_a.post(f"/api/v1/projects/{PROJECT_A_ID}/sources/{SOURCE_A_ID}/extract", json={})
    assert resp_a.status_code == status.HTTP_200_OK
    assert resp_a.json()["is_persisted"] is True

    resp_b = client_b.post(f"/api/v1/projects/{PROJECT_A_ID}/sources/{SOURCE_A_ID}/extract", json={})
    assert resp_b.status_code == status.HTTP_404_NOT_FOUND


# =============================================================================
# 3. Evidence & Extraction-Run Ownership Enforcement (All 5 Evidence Endpoints)
# =============================================================================

def test_owner_can_persist_evidence_foreign_user_blocked(client_a: TestClient, client_b: TestClient):
    """Verify owner can persist evidence into Project A; User B receives 404."""
    persist_payload = {
        "result": {
            "source_id": str(SOURCE_A_ID),
            "source_type": "web",
            "facts": [],
            "claims": [],
            "extraction_status": "success",
            "warnings": [],
            "errors": [],
            "source_truncated": False,
            "source_character_count": 500,
            "processed_character_count": 500,
            "extracted_at": NOW.isoformat(),
        }
    }
    # Owner succeeds
    resp_a = client_a.post(f"/api/v1/projects/{PROJECT_A_ID}/sources/{SOURCE_A_ID}/persist", json=persist_payload)
    assert resp_a.status_code == status.HTTP_201_CREATED

    # Foreign user blocked with 404
    resp_b = client_b.post(f"/api/v1/projects/{PROJECT_A_ID}/sources/{SOURCE_A_ID}/persist", json=persist_payload)
    assert resp_b.status_code == status.HTTP_404_NOT_FOUND


def test_owner_can_get_source_evidence_foreign_user_blocked(client_a: TestClient, client_b: TestClient):
    """Verify owner can retrieve source evidence; User B receives 404."""
    resp_a = client_a.get(f"/api/v1/projects/{PROJECT_A_ID}/sources/{SOURCE_A_ID}/evidence")
    assert resp_a.status_code == status.HTTP_200_OK

    resp_b = client_b.get(f"/api/v1/projects/{PROJECT_A_ID}/sources/{SOURCE_A_ID}/evidence")
    assert resp_b.status_code == status.HTTP_404_NOT_FOUND


def test_owner_can_get_project_evidence_foreign_user_blocked(client_a: TestClient, client_b: TestClient):
    """Verify owner can retrieve project evidence; User B receives 404."""
    resp_a = client_a.get(f"/api/v1/projects/{PROJECT_A_ID}/evidence")
    assert resp_a.status_code == status.HTTP_200_OK

    resp_b = client_b.get(f"/api/v1/projects/{PROJECT_A_ID}/evidence")
    assert resp_b.status_code == status.HTTP_404_NOT_FOUND


def test_owner_can_list_extraction_runs_foreign_user_blocked(client_a: TestClient, client_b: TestClient):
    """Verify owner can list extraction runs; User B receives 404."""
    resp_a = client_a.get(f"/api/v1/projects/{PROJECT_A_ID}/sources/{SOURCE_A_ID}/extraction-runs")
    assert resp_a.status_code == status.HTTP_200_OK

    resp_b = client_b.get(f"/api/v1/projects/{PROJECT_A_ID}/sources/{SOURCE_A_ID}/extraction-runs")
    assert resp_b.status_code == status.HTTP_404_NOT_FOUND


def test_owner_can_get_extraction_run_detail_foreign_user_blocked(client_a: TestClient, client_b: TestClient):
    """Verify owner can get extraction run detail; User B receives 404."""
    resp_a = client_a.get(f"/api/v1/projects/{PROJECT_A_ID}/extraction-runs/{RUN_A_ID}")
    assert resp_a.status_code == status.HTTP_200_OK

    resp_b = client_b.get(f"/api/v1/projects/{PROJECT_A_ID}/extraction-runs/{RUN_A_ID}")
    assert resp_b.status_code == status.HTTP_404_NOT_FOUND


# =============================================================================
# 4. Cross-Project Resource IDOR & Substitution Tests
# =============================================================================

def test_cross_project_source_access_returns_404(client_a: TestClient):
    """Verify querying User A's project with User B's source ID returns 404 (child IDOR prevention)."""
    resp = client_a.get(f"/api/v1/projects/{PROJECT_A_ID}/sources/{SOURCE_B_ID}")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert f"Source '{SOURCE_B_ID}' was not found in project '{PROJECT_A_ID}'." in resp.json()["detail"]


def test_cross_project_source_evidence_returns_404(client_a: TestClient):
    """Verify querying evidence for Source B via Project A URL returns 404 without leaking Project B."""
    resp = client_a.get(f"/api/v1/projects/{PROJECT_A_ID}/sources/{SOURCE_B_ID}/evidence")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    # Must NOT reveal Project B's UUID in response
    assert str(PROJECT_B_ID) not in resp.text
    assert f"Source '{SOURCE_B_ID}' was not found in research project '{PROJECT_A_ID}'." == resp.json()["detail"]


def test_cross_project_extraction_runs_returns_404(client_a: TestClient):
    """Verify querying extraction runs for Source B via Project A URL returns 404."""
    resp = client_a.get(f"/api/v1/projects/{PROJECT_A_ID}/sources/{SOURCE_B_ID}/extraction-runs")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert str(PROJECT_B_ID) not in resp.text
    assert f"Source '{SOURCE_B_ID}' was not found in research project '{PROJECT_A_ID}'." == resp.json()["detail"]


def test_cross_project_extraction_run_detail_returns_404(client_a: TestClient):
    """Verify querying Run B via Project A URL returns 404 without leaking Project B."""
    resp = client_a.get(f"/api/v1/projects/{PROJECT_A_ID}/extraction-runs/{RUN_B_ID}")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert str(PROJECT_B_ID) not in resp.text


def test_cross_project_persist_attempt_returns_404(client_a: TestClient):
    """Verify User A attempting to persist evidence for Source B via Project A returns 404."""
    persist_payload = {
        "result": {
            "source_id": str(SOURCE_B_ID),
            "source_type": "web",
            "facts": [],
            "claims": [],
            "extraction_status": "success",
            "warnings": [],
            "errors": [],
            "source_truncated": False,
            "source_character_count": 500,
            "processed_character_count": 500,
            "extracted_at": NOW.isoformat(),
        }
    }
    resp = client_a.post(f"/api/v1/projects/{PROJECT_A_ID}/sources/{SOURCE_B_ID}/persist", json=persist_payload)
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert str(PROJECT_B_ID) not in resp.text


# =============================================================================
# 5. Background Task Identity Integrity
# =============================================================================

def test_extract_endpoint_automatic_persistence_preserves_owner_identity(client_a: TestClient, test_app_with_ownership: FastAPI):
    """Verify that the extract endpoint's automatic persistence receives current_user.id."""
    captured_persistence_user_id = None

    mock_persist = test_app_with_ownership.dependency_overrides[get_evidence_persistence_service]()

    async def mock_persist_spy(project_id: UUID, source_id: UUID, result, user_id: UUID, **kwargs):
        nonlocal captured_persistence_user_id
        captured_persistence_user_id = user_id
        run = ExtractionRunResponse(
            id=RUN_A_ID,
            project_id=project_id,
            source_id=source_id,
            provider="openrouter",
            model_name="nemotron",
            extraction_status=ExtractionStatus.SUCCESS,
            source_truncated=False,
            source_character_count=1000,
            processed_character_count=1000,
            facts_count=1,
            claims_count=0,
            warnings=[],
            errors=[],
            run_metadata={},
            extracted_at=NOW,
            created_at=NOW,
        )
        return PersistedEvidenceRunResponse(run=run, facts=[], claims=[])

    mock_persist.persist_extraction_result.side_effect = mock_persist_spy

    # User A triggers extraction
    resp = client_a.post(f"/api/v1/projects/{PROJECT_A_ID}/sources/{SOURCE_A_ID}/extract", json={})
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["is_persisted"] is True
    # Crucial assertion: the persistence step strictly used User A's verified ID!
    assert captured_persistence_user_id == USER_A_ID


# =============================================================================
# 6. Security Regression Tests
# =============================================================================

def test_unauthenticated_request_rejected_with_401(unauth_client: TestClient):
    """Verify request with missing Authorization header returns 401."""
    resp = unauth_client.get(f"/api/v1/projects/{PROJECT_A_ID}/sources")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Missing Authorization header" in resp.json()["detail"]


def test_malformed_bearer_token_rejected_with_401(unauth_client: TestClient):
    """Verify request with invalid/malformed Bearer token returns 401."""
    resp = unauth_client.get(f"/api/v1/projects/{PROJECT_A_ID}/sources", headers={"Authorization": "Bearer not-a-valid-token"})
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Invalid or unauthorized" in resp.json()["detail"]


def test_public_health_remains_accessible(unauth_client: TestClient):
    """Verify public health probes remain accessible without auth."""
    resp = unauth_client.get("/api/v1/health")
    assert resp.status_code == status.HTTP_200_OK


def test_public_web_extract_remains_accessible(unauth_client: TestClient):
    """Verify public stateless web extraction remains accessible without auth."""
    # Invalid URL returns 400, proving endpoint is accessible without 401
    resp = unauth_client.post("/api/v1/web/extract", json={"url": "ftp://unsupported"})
    assert resp.status_code != status.HTTP_401_UNAUTHORIZED

