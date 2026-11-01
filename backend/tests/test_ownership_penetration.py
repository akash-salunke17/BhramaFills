"""Phase D4: Comprehensive Ownership Regression & Penetration Audit Test Suite.

Audits and verifies:
1. Side-effect isolation: Unauthorized requests trigger ZERO downstream side effects (no web fetching, no PDF parsing, no AI completions, no database persistence).
2. Identity spoofing immunity: Injected body, query, or header parameters cannot override cryptographically verified JWT identity.
3. Cryptographic token regressions: Wrong issuer, wrong audience, invalid signature, expired tokens, and invalid UUID subjects fail closed with HTTP 401.
4. Service-layer direct bypass audit: Calling domain services directly with invalid, missing, or mismatched identities fails closed.
5. Child-resource IDOR & generic 404 uniformity: Verifies exact generic error responses across all failure permutations without foreign UUID or resource leakage.
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
    _resolve_and_verify_ownership,
    get_owned_project,
    verify_evidence_belongs_to_project,
    verify_extraction_run_belongs_to_project,
    verify_project_ownership,
    verify_source_belongs_to_project,
    verify_source_claim_belongs_to_project,
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
    get_evidence_extraction_service,
)
from app.services.evidence import (
    EvidencePersistenceService,
    ExtractionRunNotFoundError,
    ExtractionRunResponse,
    PersistedEvidenceRunResponse,
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
ATTACKER_ID = UUID("66666666-6666-4000-a000-000000000666")

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


def create_token(
    user_id: UUID | str,
    private_key,
    email: str = "researcher@bharmafills.org",
    issuer: str = "https://test-project.supabase.co/auth/v1",
    audience: str = "authenticated",
    expires_in: int = 3600,
) -> str:
    """Helper generating customized ES256 JWTs for testing edge cases."""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": "authenticated",
        "iss": issuer,
        "aud": audience,
        "exp": now + expires_in,
        "iat": now,
        "app_metadata": {"provider": "email"},
        "user_metadata": {"user_id": str(user_id)},
    }
    return jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": "test-session-kid-1"})


# =============================================================================
# Database and Application Test Fixtures
# =============================================================================

@pytest.fixture
def mock_db_manager() -> DatabaseManager:
    """Mock DatabaseManager with simulated database records."""
    mock_db = MagicMock(spec=DatabaseManager)
    mock_db.is_configured = True

    mock_conn = AsyncMock()

    async def mock_fetchrow(query: str, *args):
        if "FROM public.research_projects" in query:
            project_id = args[0]
            if project_id == PROJECT_A_ID:
                return {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "Project A", "status": "In Progress"}
            elif project_id == PROJECT_B_ID:
                return {"id": PROJECT_B_ID, "user_id": USER_B_ID, "title": "Project B", "status": "Active"}
            elif project_id == PROJECT_UNOWNED_ID:
                return {"id": PROJECT_UNOWNED_ID, "user_id": None, "title": "Unowned", "status": "Draft"}
            elif project_id == PROJECT_DELETED_ID:
                return None
            elif project_id == PROJECT_NONEXISTENT_ID:
                return None
            return None

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
def audit_app(test_settings: Settings, test_verifier: SupabaseJWTVerifier, mock_db_manager: DatabaseManager) -> FastAPI:
    """FastAPI app instance configured for ownership audit."""
    app = create_app(settings=test_settings)
    app.dependency_overrides[get_jwt_verifier] = lambda: test_verifier
    app.dependency_overrides[get_db_manager] = lambda: mock_db_manager
    return app


@pytest.fixture
def client_a(audit_app: FastAPI, test_ec_keypair) -> TestClient:
    """Client authenticated as User A (Owner of Project A)."""
    private_key, _ = test_ec_keypair
    token = create_token(USER_A_ID, private_key)
    return TestClient(audit_app, base_url="http://testserver", headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def client_b(audit_app: FastAPI, test_ec_keypair) -> TestClient:
    """Client authenticated as User B (Foreign user)."""
    private_key, _ = test_ec_keypair
    token = create_token(USER_B_ID, private_key)
    return TestClient(audit_app, base_url="http://testserver", headers={"Authorization": f"Bearer {token}"})


# =============================================================================
# 1. Side-Effect Verification Tests (Section 6)
# =============================================================================

def test_unauthorized_web_ingestion_has_zero_side_effects(client_b: TestClient, audit_app: FastAPI):
    """Verify unauthorized web ingestion request triggers ZERO web fetches or DB writes."""
    mock_web = MagicMock(spec=WebSourceIngestionService)
    audit_app.dependency_overrides[get_web_source_service] = lambda: mock_web

    resp = client_b.post(f"/api/v1/projects/{PROJECT_A_ID}/sources/web", json={"url": "https://example.com/test"})
    assert resp.status_code == status.HTTP_404_NOT_FOUND

    # Side-effect assertion: service was NEVER called!
    assert mock_web.ingest_web_source.call_count == 0


def test_unauthorized_pdf_ingestion_has_zero_side_effects(client_b: TestClient, audit_app: FastAPI):
    """Verify unauthorized PDF upload triggers ZERO PDF parsing or DB writes."""
    mock_pdf = MagicMock(spec=PDFSourceIngestionService)
    audit_app.dependency_overrides[get_pdf_source_service] = lambda: mock_pdf

    files = {"file": ("paper.pdf", b"%PDF-1.4 mock content", "application/pdf")}
    resp = client_b.post(f"/api/v1/projects/{PROJECT_A_ID}/sources/pdf", files=files)
    assert resp.status_code == status.HTTP_404_NOT_FOUND

    # Side-effect assertion: PDF service was NEVER called!
    assert mock_pdf.ingest_pdf.call_count == 0


def test_unauthorized_extraction_has_zero_ai_or_persistence_side_effects(client_b: TestClient, audit_app: FastAPI):
    """Verify unauthorized evidence extraction triggers ZERO AI provider calls and ZERO persistence calls."""
    mock_web = MagicMock(spec=WebSourceIngestionService)
    mock_extract = MagicMock(spec=EvidenceExtractionService)
    mock_persist = MagicMock(spec=EvidencePersistenceService)
    mock_extract.is_configured = True
    mock_persist.is_configured = True

    audit_app.dependency_overrides[get_web_source_service] = lambda: mock_web
    audit_app.dependency_overrides[get_evidence_extraction_service] = lambda: mock_extract
    audit_app.dependency_overrides[get_evidence_persistence_service] = lambda: mock_persist

    resp = client_b.post(f"/api/v1/projects/{PROJECT_A_ID}/sources/{SOURCE_A_ID}/extract", json={})
    assert resp.status_code == status.HTTP_404_NOT_FOUND

    # Crucial side-effect assertions: neither AI nor persistence was ever called!
    assert mock_web.get_project_source_detail.call_count == 0
    assert mock_extract.extract_source_evidence.call_count == 0
    assert mock_persist.persist_extraction_result.call_count == 0


def test_unauthorized_persistence_has_zero_database_side_effects(client_b: TestClient, audit_app: FastAPI):
    """Verify unauthorized direct evidence persistence triggers ZERO DB persistence calls."""
    mock_persist = MagicMock(spec=EvidencePersistenceService)
    mock_persist.is_configured = True
    audit_app.dependency_overrides[get_evidence_persistence_service] = lambda: mock_persist

    payload = {
        "result": {
            "source_id": str(SOURCE_A_ID),
            "source_type": "web",
            "facts": [],
            "claims": [],
            "extraction_status": "success",
            "warnings": [],
            "errors": [],
            "source_truncated": False,
            "source_character_count": 100,
            "processed_character_count": 100,
            "extracted_at": NOW.isoformat(),
        }
    }
    resp = client_b.post(f"/api/v1/projects/{PROJECT_A_ID}/sources/{SOURCE_A_ID}/persist", json=payload)
    assert resp.status_code == status.HTTP_404_NOT_FOUND

    assert mock_persist.persist_extraction_result.call_count == 0


# =============================================================================
# 2. Identity Spoofing & Query Tampering Immunity Tests (Section 4.A & 4.E)
# =============================================================================

def test_request_body_cannot_override_authenticated_identity(client_b: TestClient, audit_app: FastAPI):
    """Verify providing owner User A's ID in request body does NOT bypass ownership check."""
    mock_web = MagicMock(spec=WebSourceIngestionService)
    audit_app.dependency_overrides[get_web_source_service] = lambda: mock_web

    # User B attempts to impersonate User A by passing user_id in the JSON body
    spoofed_payload = {
        "url": "https://example.com/spoofed",
        "user_id": str(USER_A_ID),
    }
    resp = client_b.post(f"/api/v1/projects/{PROJECT_A_ID}/sources/web", json=spoofed_payload)
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert mock_web.ingest_web_source.call_count == 0


def test_query_parameter_cannot_override_authenticated_identity(client_b: TestClient, audit_app: FastAPI):
    """Verify appending ?user_id=<owner_id> query parameter is ignored."""
    mock_web = MagicMock(spec=WebSourceIngestionService)
    audit_app.dependency_overrides[get_web_source_service] = lambda: mock_web

    resp = client_b.get(f"/api/v1/projects/{PROJECT_A_ID}/sources?user_id={USER_A_ID}")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert mock_web.list_project_sources.call_count == 0


def test_extract_endpoint_spoofed_body_identity_is_ignored(client_b: TestClient, audit_app: FastAPI):
    """Verify spoofed identity in extract request body is completely rejected."""
    mock_extract = MagicMock(spec=EvidenceExtractionService)
    mock_extract.is_configured = True
    audit_app.dependency_overrides[get_evidence_extraction_service] = lambda: mock_extract

    resp = client_b.post(
        f"/api/v1/projects/{PROJECT_A_ID}/sources/{SOURCE_A_ID}/extract",
        json={"user_id": str(USER_A_ID)},
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert mock_extract.extract_source_evidence.call_count == 0


# =============================================================================
# 3. Cryptographic Token Regressions (Section 4.F)
# =============================================================================

def test_token_with_wrong_issuer_rejected_with_401(audit_app: FastAPI, test_ec_keypair):
    """Verify token signed with wrong issuer is strictly rejected with 401."""
    private_key, _ = test_ec_keypair
    bad_token = create_token(USER_A_ID, private_key, issuer="https://evil.supabase.co/auth/v1")
    client = TestClient(audit_app, base_url="http://testserver", headers={"Authorization": f"Bearer {bad_token}"})

    resp = client.get(f"/api/v1/projects/{PROJECT_A_ID}/sources")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Invalid or unauthorized" in resp.json()["detail"]


def test_token_with_wrong_audience_rejected_with_401(audit_app: FastAPI, test_ec_keypair):
    """Verify token signed with wrong audience is strictly rejected with 401."""
    private_key, _ = test_ec_keypair
    bad_token = create_token(USER_A_ID, private_key, audience="wrong-audience")
    client = TestClient(audit_app, base_url="http://testserver", headers={"Authorization": f"Bearer {bad_token}"})

    resp = client.get(f"/api/v1/projects/{PROJECT_A_ID}/sources")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Invalid or unauthorized" in resp.json()["detail"]


def test_token_with_expired_timestamp_rejected_with_401(audit_app: FastAPI, test_ec_keypair):
    """Verify expired token is rejected with 401 and RFC 6750 invalid_token challenge."""
    private_key, _ = test_ec_keypair
    expired_token = create_token(USER_A_ID, private_key, expires_in=-3600)
    client = TestClient(audit_app, base_url="http://testserver", headers={"Authorization": f"Bearer {expired_token}"})

    resp = client.get(f"/api/v1/projects/{PROJECT_A_ID}/sources")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert "error=\"invalid_token\"" in resp.headers.get("www-authenticate", "")


def test_token_with_invalid_user_uuid_rejected_with_401(audit_app: FastAPI, test_ec_keypair):
    """Verify token with non-UUID subject string is rejected with 401."""
    private_key, _ = test_ec_keypair
    invalid_sub_token = create_token("not-a-valid-uuid", private_key)
    client = TestClient(audit_app, base_url="http://testserver", headers={"Authorization": f"Bearer {invalid_sub_token}"})

    resp = client.get(f"/api/v1/projects/{PROJECT_A_ID}/sources")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


def test_token_with_untrusted_signature_rejected_with_401(audit_app: FastAPI):
    """Verify token signed with an unauthorized external key fails signature verification."""
    foreign_private_key = ec.generate_private_key(ec.SECP256R1())
    foreign_token = create_token(USER_A_ID, foreign_private_key)
    client = TestClient(audit_app, base_url="http://testserver", headers={"Authorization": f"Bearer {foreign_token}"})

    resp = client.get(f"/api/v1/projects/{PROJECT_A_ID}/sources")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# =============================================================================
# 4. Service-Layer Direct Bypass Audit (Section 5)
# =============================================================================

@pytest.mark.asyncio
async def test_direct_service_call_rejects_missing_identity():
    """Verify direct service invocation fails closed with TypeError if user_id is missing or None."""
    mock_db = MagicMock(spec=DatabaseManager)
    web_service = WebSourceIngestionService(db_manager=mock_db)
    pdf_service = PDFSourceIngestionService(db_manager=mock_db)
    evidence_service = EvidencePersistenceService(db_manager=mock_db)

    # 1. Web service rejects None
    with pytest.raises(TypeError, match="user_id must be a UUID instance"):
        await web_service.ingest_web_source(PROJECT_A_ID, "https://example.com", user_id=None)  # type: ignore

    # 2. PDF service rejects None
    with pytest.raises(TypeError, match="user_id must be a UUID instance"):
        await pdf_service.ingest_pdf(PROJECT_A_ID, "doc.pdf", "application/pdf", b"%PDF", user_id=None)  # type: ignore

    # 3. Evidence service rejects None
    with pytest.raises(TypeError, match="user_id must be a UUID instance"):
        await evidence_service.persist_extraction_result(PROJECT_A_ID, SOURCE_A_ID, MagicMock(), user_id=None)  # type: ignore


@pytest.mark.asyncio
async def test_direct_service_call_enforces_project_ownership_within_connection():
    """Verify direct service calls execute verify_project_ownership inside the DB connection."""
    mock_db = MagicMock(spec=DatabaseManager)
    mock_db.is_configured = True
    mock_conn = AsyncMock()

    # DB returns project owned by USER_A_ID
    mock_conn.fetchrow.return_value = {
        "id": PROJECT_A_ID,
        "user_id": USER_A_ID,
        "title": "Project A",
        "status": "In Progress",
    }

    mock_acquire = AsyncMock()
    mock_acquire.__aenter__.return_value = mock_conn
    mock_acquire.__aexit__.return_value = None
    mock_db.acquire_connection.return_value = mock_acquire

    web_service = WebSourceIngestionService(db_manager=mock_db)

    # Invoking with foreign USER_B_ID raises ProjectNotFoundError (masked from ProjectAccessDeniedError)
    with pytest.raises(ProjectNotFoundError, match="Research project"):
        await web_service.validate_project_exists(mock_conn, PROJECT_A_ID, user_id=USER_B_ID)


@pytest.mark.asyncio
async def test_child_resource_helper_rejects_forged_project_context():
    """Verify providing an OwnedProjectContext from a different project fails with ResourceMismatchError."""
    mock_conn = AsyncMock()
    forged_context = OwnedProjectContext(id=PROJECT_B_ID, user_id=USER_A_ID, title="Project B")

    # Attempting to use Project B's context to access Project A
    with pytest.raises(ResourceMismatchError, match="does not match target project"):
        await _resolve_and_verify_ownership(mock_conn, PROJECT_A_ID, forged_context)


# =============================================================================
# 5. Generic 404 Response & Uniformity Tests (Section 3)
# =============================================================================

def test_generic_404_response_exact_uniformity(client_a: TestClient, client_b: TestClient):
    """Verify identical generic 404 response across all failure permutations.

    Ensures zero IDOR existence oracle across:
    - Foreign-owned projects
    - Ownerless projects
    - Soft-deleted projects
    - Nonexistent projects
    """
    cases = [
        # (client, project_id)
        (client_b, PROJECT_A_ID),          # Foreign-owned
        (client_a, PROJECT_UNOWNED_ID),   # Ownerless
        (client_a, PROJECT_DELETED_ID),    # Soft-deleted
        (client_a, PROJECT_NONEXISTENT_ID), # Nonexistent
    ]

    for test_client, target_project_id in cases:
        resp = test_client.get(f"/api/v1/projects/{target_project_id}/sources")
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.json() == {"detail": f"Research project '{target_project_id}' was not found."}
        # Absolute guarantee: no internal owner ID or foreign project ID disclosed
        assert str(USER_A_ID) not in resp.text
        assert str(USER_B_ID) not in resp.text


def test_invalid_uuid_returns_422_without_leaking_data(client_a: TestClient):
    """Verify non-UUID project string in path returns 422 Unprocessable Entity."""
    resp = client_a.get("/api/v1/projects/not-a-valid-uuid/sources")
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

