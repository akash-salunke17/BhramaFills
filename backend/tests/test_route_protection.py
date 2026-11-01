"""Automated tests verifying route protection boundaries and public route accessibility."""

import time
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import Depends, FastAPI, status
from fastapi.testclient import TestClient

from app.core.auth import get_current_user
from app.core.ownership import OwnedProjectContext, get_owned_project
from app.services.ai import EvidenceExtractionService, get_evidence_extraction_service
from app.services.evidence import EvidencePersistenceService, get_evidence_persistence_service
from app.services.pdf.service import PDFSourceIngestionService, get_pdf_source_service
from app.services.sources.exceptions import ProjectNotFoundError
from app.services.sources.web_source_service import WebSourceIngestionService, get_web_source_service


# Dummy project and source IDs for testing route boundaries
DUMMY_PROJECT_ID = "00000000-0000-4000-b000-000000000001"
DUMMY_SOURCE_ID = "00000000-0000-4000-b000-000000000002"
DUMMY_RUN_ID = "00000000-0000-4000-b000-000000000003"


# =============================================================================
# 1. Protected Endpoints Table Matrix
# =============================================================================

PROTECTED_ENDPOINTS = [
    # (method, path, body/data)
    ("POST", f"/api/v1/projects/{DUMMY_PROJECT_ID}/sources/web", {"url": "https://example.com"}),
    ("POST", f"/api/v1/projects/{DUMMY_PROJECT_ID}/sources/pdf", None),  # multipart upload
    ("GET", f"/api/v1/projects/{DUMMY_PROJECT_ID}/sources", None),
    ("GET", f"/api/v1/projects/{DUMMY_PROJECT_ID}/sources/{DUMMY_SOURCE_ID}", None),
    ("POST", f"/api/v1/projects/{DUMMY_PROJECT_ID}/sources/{DUMMY_SOURCE_ID}/extract", {}),
    ("POST", f"/api/v1/projects/{DUMMY_PROJECT_ID}/sources/{DUMMY_SOURCE_ID}/persist", {
        "result": {
            "source_id": DUMMY_SOURCE_ID,
            "source_type": "web",
            "facts": [],
            "claims": [],
            "extraction_status": "no_content",
            "warnings": [],
            "errors": [],
            "source_truncated": False,
            "source_character_count": 0,
            "processed_character_count": 0,
            "extracted_at": "2026-11-01T12:00:00Z"
        }
    }),
    ("GET", f"/api/v1/projects/{DUMMY_PROJECT_ID}/sources/{DUMMY_SOURCE_ID}/evidence", None),
    ("GET", f"/api/v1/projects/{DUMMY_PROJECT_ID}/evidence", None),
    ("GET", f"/api/v1/projects/{DUMMY_PROJECT_ID}/sources/{DUMMY_SOURCE_ID}/extraction-runs", None),
    ("GET", f"/api/v1/projects/{DUMMY_PROJECT_ID}/extraction-runs/{DUMMY_RUN_ID}", None),
]


# =============================================================================
# 2. Mock Services Fixture to Isolate Route Boundary from DB Pool
# =============================================================================

@pytest.fixture(autouse=True)
def override_domain_services(app: FastAPI):
    """Override downstream service dependencies so route tests purely exercise the auth boundary."""
    mock_web = MagicMock(spec=WebSourceIngestionService)
    mock_web.ingest_web_source = AsyncMock(side_effect=ProjectNotFoundError("Project not found"))
    mock_web.list_project_sources = AsyncMock(side_effect=ProjectNotFoundError("Project not found"))
    mock_web.get_project_source_detail = AsyncMock(side_effect=ProjectNotFoundError("Project not found"))

    mock_pdf = MagicMock(spec=PDFSourceIngestionService)
    mock_pdf.ingest_pdf = AsyncMock(side_effect=ProjectNotFoundError("Project not found"))
    mock_pdf.ingest_pdf_source = AsyncMock(side_effect=ProjectNotFoundError("Project not found"))

    mock_extract = MagicMock(spec=EvidenceExtractionService)
    mock_extract.is_configured = True
    mock_extract.extract_source_evidence = AsyncMock(side_effect=ProjectNotFoundError("Project not found"))

    mock_persist = MagicMock(spec=EvidencePersistenceService)
    mock_persist.is_configured = True
    mock_persist.persist_extraction_result = AsyncMock(side_effect=ProjectNotFoundError("Project not found"))
    mock_persist.get_source_evidence = AsyncMock(side_effect=ProjectNotFoundError("Project not found"))
    mock_persist.get_project_evidence = AsyncMock(side_effect=ProjectNotFoundError("Project not found"))
    mock_persist.list_extraction_runs = AsyncMock(side_effect=ProjectNotFoundError("Project not found"))
    mock_persist.get_extraction_run_detail = AsyncMock(side_effect=ProjectNotFoundError("Project not found"))

    app.dependency_overrides[get_web_source_service] = lambda: mock_web
    app.dependency_overrides[get_pdf_source_service] = lambda: mock_pdf
    app.dependency_overrides[get_evidence_extraction_service] = lambda: mock_extract
    app.dependency_overrides[get_evidence_persistence_service] = lambda: mock_persist
    app.dependency_overrides[get_owned_project] = (
        lambda project_id, current_user=Depends(get_current_user): OwnedProjectContext(
            id=project_id,
            user_id=current_user.id,
            title="Test Project",
        )
    )
    yield
    app.dependency_overrides.pop(get_web_source_service, None)
    app.dependency_overrides.pop(get_pdf_source_service, None)
    app.dependency_overrides.pop(get_evidence_extraction_service, None)
    app.dependency_overrides.pop(get_evidence_persistence_service, None)
    app.dependency_overrides.pop(get_owned_project, None)


# =============================================================================
# 3. Route Protection Tests (Unauthenticated Requests)
# =============================================================================

@pytest.mark.parametrize("method,path,payload", PROTECTED_ENDPOINTS)
def test_protected_endpoint_rejects_missing_auth_header(unauthenticated_client: TestClient, method: str, path: str, payload):
    """Verify that every protected route strictly returns HTTP 401 when Authorization header is omitted."""
    if method == "GET":
        resp = unauthenticated_client.get(path)
    elif method == "POST":
        if payload is None:
            # Test multipart upload without auth
            resp = unauthenticated_client.post(path, files={"file": ("test.pdf", b"%PDF-1.4 mock", "application/pdf")})
        else:
            resp = unauthenticated_client.post(path, json=payload)
    else:
        pytest.fail(f"Unsupported HTTP method: {method}")

    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Missing Authorization header" in resp.json()["detail"]
    assert resp.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("method,path,payload", PROTECTED_ENDPOINTS)
def test_protected_endpoint_rejects_malformed_bearer_token(unauthenticated_client: TestClient, method: str, path: str, payload):
    """Verify that every protected route returns HTTP 401 when a malformed Bearer token is sent."""
    headers = {"Authorization": "Bearer malformed.jwt.token"}
    if method == "GET":
        resp = unauthenticated_client.get(path, headers=headers)
    elif method == "POST":
        if payload is None:
            resp = unauthenticated_client.post(path, headers=headers, files={"file": ("test.pdf", b"%PDF-1.4 mock", "application/pdf")})
        else:
            resp = unauthenticated_client.post(path, headers=headers, json=payload)
    else:
        pytest.fail(f"Unsupported HTTP method: {method}")

    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Invalid or unauthorized authentication token" in resp.json()["detail"]
    assert 'error="invalid_token"' in resp.headers["WWW-Authenticate"]


@pytest.mark.parametrize("method,path,payload", PROTECTED_ENDPOINTS)
def test_protected_endpoint_rejects_expired_token(unauthenticated_client: TestClient, test_ec_keypair, method: str, path: str, payload):
    """Verify that every protected route returns HTTP 401 when an expired Bearer token is sent."""
    private_key, _ = test_ec_keypair
    now = int(time.time())
    expired_payload = {
        "sub": str(uuid4()),
        "iss": "https://test-project.supabase.co/auth/v1",
        "aud": "authenticated",
        "exp": now - 300,  # Expired 5 minutes ago
        "iat": now - 3600,
    }
    expired_token = jwt.encode(expired_payload, private_key, algorithm="ES256", headers={"kid": "test-session-kid-1"})
    headers = {"Authorization": f"Bearer {expired_token}"}

    if method == "GET":
        resp = unauthenticated_client.get(path, headers=headers)
    elif method == "POST":
        if payload is None:
            resp = unauthenticated_client.post(path, headers=headers, files={"file": ("test.pdf", b"%PDF-1.4 mock", "application/pdf")})
        else:
            resp = unauthenticated_client.post(path, headers=headers, json=payload)
    else:
        pytest.fail(f"Unsupported HTTP method: {method}")

    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert "expired" in resp.json()["detail"].lower()
    assert 'error="invalid_token"' in resp.headers["WWW-Authenticate"]


# =============================================================================
# 4. Authenticated Route Access Tests (Passing Auth Boundary)
# =============================================================================

@pytest.mark.parametrize("method,path,payload", PROTECTED_ENDPOINTS)
def test_protected_endpoint_passes_auth_boundary_with_valid_token(client: TestClient, method: str, path: str, payload):
    """Verify that valid JWT passes the authentication boundary (HTTP status is NOT 401).

    Note: Downstream business logic returns 404 (resource not found), which explicitly
    confirms authentication succeeded and execution proceeded into the endpoint.
    """
    if method == "GET":
        resp = client.get(path)
    elif method == "POST":
        if payload is None:
            resp = client.post(path, files={"file": ("test.pdf", b"%PDF-1.4 mock", "application/pdf")})
        else:
            resp = client.post(path, json=payload)
    else:
        pytest.fail(f"Unsupported HTTP method: {method}")

    # Critical Assertion: The response MUST NOT be 401 Unauthorized!
    assert resp.status_code != status.HTTP_401_UNAUTHORIZED
    # The downstream mock returns 404 ProjectNotFoundError, confirming auth passed!
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert "WWW-Authenticate" not in resp.headers


# =============================================================================
# 5. Public Endpoints Verification Tests (Unauthenticated Allowed)
# =============================================================================

PUBLIC_ENDPOINTS = [
    "/api/v1/health",
    "/api/v1/health/database",
    "/api/v1/health/ai",
    "/docs",
    "/openapi.json",
]


@pytest.mark.parametrize("path", PUBLIC_ENDPOINTS)
def test_public_endpoint_accessible_without_auth(unauthenticated_client: TestClient, path: str):
    """Verify that public health probes and OpenAPI documentation remain accessible without Authorization header."""
    resp = unauthenticated_client.get(path)
    assert resp.status_code == status.HTTP_200_OK


def test_public_health_endpoint_does_not_leak_auth_secrets(unauthenticated_client: TestClient):
    """Verify public health response contains no sensitive key material or auth tokens."""
    resp = unauthenticated_client.get("/api/v1/health")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert "secret" not in str(data).lower()
    assert "token" not in str(data).lower()
    assert "key" not in str(data).lower()
