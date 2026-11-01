"""Comprehensive HTTP-level security, validation, and integration tests for research project CRUD routes."""

from __future__ import annotations

from datetime import datetime, timezone
import time
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from fastapi import FastAPI, status
from fastapi.testclient import TestClient
import jwt
import pytest

from app.core.auth import SupabaseJWTVerifier, get_jwt_verifier
from app.core.config import Settings
from app.db.connection import (
    DatabaseManager,
    DatabaseNotConfiguredError,
    DatabaseUnavailableError,
    get_db_manager,
)
from app.main import create_app

# Canonical deterministic test user UUIDs
USER_A_ID = UUID("00000000-0000-4000-a000-000000000001")
USER_B_ID = UUID("00000000-0000-4000-a000-000000000002")

PROJECT_A_ID = UUID("11111111-1111-4000-a000-000000000001")
PROJECT_B_ID = UUID("22222222-2222-4000-a000-000000000002")
PROJECT_NONEXISTENT_ID = UUID("99999999-9999-4000-a000-000000000009")

NOW = datetime.now(timezone.utc)


def create_token(user_id: UUID, email: str, private_key) -> str:
    """Helper generating signed ES256 JWT for test user identity."""
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
        "user_metadata": {"full_name": f"User {user_id}"},
    }
    return jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": "test-kid"})


@pytest.fixture
def test_jwt_verifier(test_ec_keypair):
    """Provide a mock JWT verifier with test public key."""
    _, public_key = test_ec_keypair
    verifier = MagicMock(spec=SupabaseJWTVerifier)

    def _verify_mock(token: str):
        try:
            claims = jwt.decode(
                token,
                public_key,
                algorithms=["ES256"],
                audience="authenticated",
                issuer="https://test-project.supabase.co/auth/v1",
            )
            from app.core.auth_schemas import AuthenticatedUser
            return AuthenticatedUser(
                id=UUID(claims["sub"]),
                email=claims["email"],
                role=claims["role"],
                app_metadata=claims.get("app_metadata", {}),
                user_metadata=claims.get("user_metadata", {}),
            )
        except Exception as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc

    verifier.verify_token.side_effect = _verify_mock
    return verifier


@pytest.fixture
def token_user_a(test_ec_keypair) -> str:
    private_key, _ = test_ec_keypair
    return create_token(USER_A_ID, "user_a@bharmafills.org", private_key)


@pytest.fixture
def token_user_b(test_ec_keypair) -> str:
    private_key, _ = test_ec_keypair
    return create_token(USER_B_ID, "user_b@bharmafills.org", private_key)


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg connection pool with an in-memory store for projects."""
    projects_store = {
        PROJECT_A_ID: {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,
            "title": "Quantum Computing Ethics",
            "research_question": "What are the ethical implications of quantum supremacy?",
            "description": "Exploration of quantum security and philosophical concerns.",
            "category": "Technology",
            "status": "In Progress",
            "created_at": NOW,
            "updated_at": NOW,
            "deleted_at": None,
        },
        PROJECT_B_ID: {
            "id": PROJECT_B_ID,
            "user_id": USER_B_ID,
            "title": "Renewable Microgrids",
            "research_question": "How do decentralized solar grids handle frequency stability?",
            "description": "Grid resilience and battery storage.",
            "category": "Technology",
            "status": "Draft",
            "created_at": NOW,
            "updated_at": NOW,
            "deleted_at": None,
        },
    }

    mock_conn = AsyncMock()

    async def mock_fetchrow(query: str, *args):
        # Insert project
        if "INSERT INTO public.research_projects" in query:
            user_id, title, question, desc, cat, status = args
            new_id = uuid4()
            record = {
                "id": new_id,
                "user_id": user_id,
                "title": title,
                "research_question": question,
                "description": desc,
                "category": cat,
                "status": status,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
                "deleted_at": None,
            }
            projects_store[new_id] = record
            return record

        # Get project or ownership check
        if "FROM public.research_projects" in query and "WHERE id = $1 AND deleted_at IS NULL" in query:
            pid = args[0]
            record = projects_store.get(pid)
            if record and record["deleted_at"] is None:
                return record
            return None

        # Update project
        if "UPDATE public.research_projects" in query and "RETURNING" in query:
            title, question, desc, cat, status, pid = args
            record = projects_store.get(pid)
            if record and record["deleted_at"] is None:
                record["title"] = title
                record["research_question"] = question
                record["description"] = desc
                record["category"] = cat
                record["status"] = status
                record["updated_at"] = datetime.now(timezone.utc)
                return record
            return None

        return None

    async def mock_fetch(query: str, *args):
        if "FROM public.research_projects" in query and "WHERE user_id = $1" in query:
            uid, limit, offset = args
            matched = [
                p for p in projects_store.values()
                if p["user_id"] == uid and p["deleted_at"] is None
            ]
            matched.sort(key=lambda x: x["updated_at"], reverse=True)
            return matched[offset:offset + limit]
        return []

    async def mock_fetchval(query: str, *args):
        if "SELECT COUNT(*)" in query and "WHERE user_id = $1" in query:
            uid = args[0]
            return len([
                p for p in projects_store.values()
                if p["user_id"] == uid and p["deleted_at"] is None
            ])
        return 0

    async def mock_execute(query: str, *args):
        if "UPDATE public.research_projects" in query and "SET deleted_at = now()" in query:
            pid, uid = args
            record = projects_store.get(pid)
            if record and record["user_id"] == uid and record["deleted_at"] is None:
                record["deleted_at"] = datetime.now(timezone.utc)
                return "UPDATE 1"
            return "UPDATE 0"
        return "OK"

    mock_conn.fetchrow.side_effect = mock_fetchrow
    mock_conn.fetch.side_effect = mock_fetch
    mock_conn.fetchval.side_effect = mock_fetchval
    mock_conn.execute.side_effect = mock_execute

    mock_db = MagicMock(spec=DatabaseManager)
    mock_db.is_configured = True

    class ConnContext:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_db.acquire_connection.return_value = ConnContext()
    return mock_db, projects_store


@pytest.fixture
def app_with_mocks(test_jwt_verifier, mock_db_pool):
    mock_db, _ = mock_db_pool
    app = create_app()
    app.dependency_overrides[get_jwt_verifier] = lambda: test_jwt_verifier
    app.dependency_overrides[get_db_manager] = lambda: mock_db
    return app


@pytest.fixture
def client(app_with_mocks):
    return TestClient(app_with_mocks)


# =============================================================================
# 1. Authentication Tests
# =============================================================================

def test_projects_endpoints_require_authentication(client):
    """Verify all /projects endpoints return HTTP 401 when unauthenticated."""
    assert client.get("/api/v1/projects").status_code == status.HTTP_401_UNAUTHORIZED
    assert client.post("/api/v1/projects", json={}).status_code == status.HTTP_401_UNAUTHORIZED
    assert client.get(f"/api/v1/projects/{PROJECT_A_ID}").status_code == status.HTTP_401_UNAUTHORIZED
    assert client.patch(f"/api/v1/projects/{PROJECT_A_ID}", json={}).status_code == status.HTTP_401_UNAUTHORIZED
    assert client.delete(f"/api/v1/projects/{PROJECT_A_ID}").status_code == status.HTTP_401_UNAUTHORIZED


def test_projects_endpoints_reject_invalid_token(client):
    """Verify rejection of malformed Bearer tokens."""
    headers = {"Authorization": "Bearer not-a-valid-jwt"}
    assert client.get("/api/v1/projects", headers=headers).status_code == status.HTTP_401_UNAUTHORIZED


# =============================================================================
# 2. Project Creation & Validation Tests
# =============================================================================

def test_create_project_success(client, token_user_a):
    """Verify successful creation of a research project."""
    headers = {"Authorization": f"Bearer {token_user_a}"}
    payload = {
        "title": "Autonomous Vehicles Gap Analysis",
        "research_question": "What safety guarantees exist for level 4 autonomous vehicles in snow?",
        "description": "Comparative study between radar and vision-only systems in blizzard conditions.",
        "category": "Technology",
        "status": "Draft",
    }
    response = client.post("/api/v1/projects", json=payload, headers=headers)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["title"] == payload["title"]
    assert data["research_question"] == payload["research_question"]
    assert data["description"] == payload["description"]
    assert data["category"] == "Technology"
    assert data["status"] == "Draft"
    assert data["user_id"] == str(USER_A_ID)
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


def test_create_project_validation_failure(client, token_user_a):
    """Verify boundary validation rejections."""
    headers = {"Authorization": f"Bearer {token_user_a}"}

    # Title too short (< 3 chars)
    resp = client.post(
        "/api/v1/projects",
        json={"title": "AB", "research_question": "Valid research question here."},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Question too short (< 10 chars)
    resp = client.post(
        "/api/v1/projects",
        json={"title": "Valid Title", "research_question": "Short"},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Whitespace-only title
    resp = client.post(
        "/api/v1/projects",
        json={"title": "   ", "research_question": "Valid research question here."},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Invalid category
    resp = client.post(
        "/api/v1/projects",
        json={"title": "Valid Title", "research_question": "Valid research question here.", "category": "Bogus"},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# =============================================================================
# 3. Project Listing & Ownership Scoping Tests
# =============================================================================

def test_list_projects_scoped_to_caller(client, token_user_a, token_user_b):
    """Verify that users can only list projects they own."""
    # User A listing
    resp_a = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token_user_a}"})
    assert resp_a.status_code == status.HTTP_200_OK
    data_a = resp_a.json()
    assert data_a["total_count"] >= 1
    assert all(p["user_id"] == str(USER_A_ID) for p in data_a["projects"])

    # User B listing
    resp_b = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token_user_b}"})
    assert resp_b.status_code == status.HTTP_200_OK
    data_b = resp_b.json()
    assert data_b["total_count"] >= 1
    assert all(p["user_id"] == str(USER_B_ID) for p in data_b["projects"])


# =============================================================================
# 4. Project Retrieval & IDOR Protection Tests
# =============================================================================

def test_get_project_owner_access_allowed(client, token_user_a):
    """Verify owner can retrieve their project."""
    resp = client.get(
        f"/api/v1/projects/{PROJECT_A_ID}",
        headers={"Authorization": f"Bearer {token_user_a}"},
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["id"] == str(PROJECT_A_ID)
    assert resp.json()["title"] == "Quantum Computing Ethics"


def test_get_project_foreign_owner_returns_404(client, token_user_b):
    """Verify User B cannot access User A's project (IDOR prevention with 404 masking)."""
    resp = client.get(
        f"/api/v1/projects/{PROJECT_A_ID}",
        headers={"Authorization": f"Bearer {token_user_b}"},
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert "was not found" in resp.json()["detail"]


def test_get_nonexistent_project_returns_404(client, token_user_a):
    """Verify querying non-existent project returns 404."""
    resp = client.get(
        f"/api/v1/projects/{PROJECT_NONEXISTENT_ID}",
        headers={"Authorization": f"Bearer {token_user_a}"},
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# =============================================================================
# 5. Project Update Tests
# =============================================================================

def test_update_project_success(client, token_user_a):
    """Verify updating project fields."""
    headers = {"Authorization": f"Bearer {token_user_a}"}
    update_payload = {
        "title": "Updated Quantum Computing Ethics",
        "status": "Completed",
    }
    resp = client.patch(
        f"/api/v1/projects/{PROJECT_A_ID}",
        json=update_payload,
        headers=headers,
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["title"] == "Updated Quantum Computing Ethics"
    assert data["status"] == "Completed"
    # Unchanged fields preserved
    assert data["category"] == "Technology"
    assert data["research_question"] == "What are the ethical implications of quantum supremacy?"


def test_update_project_foreign_owner_returns_404(client, token_user_b):
    """Verify User B cannot update User A's project."""
    resp = client.patch(
        f"/api/v1/projects/{PROJECT_A_ID}",
        json={"title": "Hacked Title"},
        headers={"Authorization": f"Bearer {token_user_b}"},
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# =============================================================================
# 6. Project Soft Deletion Tests
# =============================================================================

def test_delete_project_soft_delete(client, token_user_a):
    """Verify soft-deleting a project returns 204 and subsequent queries return 404."""
    headers = {"Authorization": f"Bearer {token_user_a}"}
    resp = client.delete(f"/api/v1/projects/{PROJECT_A_ID}", headers=headers)
    assert resp.status_code == status.HTTP_204_NO_CONTENT

    # Subsequent GET returns 404
    get_resp = client.get(f"/api/v1/projects/{PROJECT_A_ID}", headers=headers)
    assert get_resp.status_code == status.HTTP_404_NOT_FOUND


def test_delete_project_foreign_owner_returns_404(client, token_user_b):
    """Verify User B cannot delete User A's project."""
    resp = client.delete(
        f"/api/v1/projects/{PROJECT_A_ID}",
        headers={"Authorization": f"Bearer {token_user_b}"},
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# =============================================================================
# 7. Database Service Availability Tests
# =============================================================================

def test_unconfigured_database_returns_503(app_with_mocks, token_user_a):
    """Verify unconfigured DB manager returns 503."""
    unconfigured_db = MagicMock(spec=DatabaseManager)
    unconfigured_db.is_configured = False
    app_with_mocks.dependency_overrides[get_db_manager] = lambda: unconfigured_db

    client = TestClient(app_with_mocks)
    headers = {"Authorization": f"Bearer {token_user_a}"}

    resp = client.get("/api/v1/projects", headers=headers)
    assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
