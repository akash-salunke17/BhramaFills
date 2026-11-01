"""Pytest fixtures for Bharmafills backend test suite with deterministic authentication."""

import time
from collections.abc import AsyncGenerator, Generator
from unittest.mock import MagicMock
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.core.auth import SupabaseJWTVerifier, get_jwt_verifier
from app.core.auth_schemas import AuthenticatedUser
from app.core.config import Settings
from app.main import create_app

# Canonical deterministic test user UUID
TEST_USER_ID = UUID("00000000-0000-4000-a000-000000000001")
TEST_USER_EMAIL = "test.researcher@bharmafills.org"


@pytest.fixture(scope="session")
def test_ec_keypair():
    """Session-scoped ephemeral EC keypair for generating test JWTs."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture
def test_user() -> AuthenticatedUser:
    """Provide a verified AuthenticatedUser instance for tests."""
    return AuthenticatedUser(
        id=TEST_USER_ID,
        email=TEST_USER_EMAIL,
        role="authenticated",
        app_metadata={"provider": "email"},
        user_metadata={"full_name": "Test Researcher"},
    )


@pytest.fixture
def test_jwt_token(test_ec_keypair, test_user: AuthenticatedUser) -> str:
    """Generate a cryptographically valid ES256 JWT for the test user."""
    private_key, _ = test_ec_keypair
    now = int(time.time())
    payload = {
        "sub": str(test_user.id),
        "email": test_user.email,
        "role": test_user.role,
        "iss": "https://test-project.supabase.co/auth/v1",
        "aud": "authenticated",
        "exp": now + 7200,
        "iat": now,
        "app_metadata": test_user.app_metadata,
        "user_metadata": test_user.user_metadata,
    }
    return jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": "test-session-kid-1"})


@pytest.fixture
def auth_headers(test_jwt_token: str) -> dict[str, str]:
    """Provide standard Bearer authorization header for authenticated requests."""
    return {"Authorization": f"Bearer {test_jwt_token}"}


@pytest.fixture
def test_settings() -> Settings:
    """Provide isolated test settings with mock auth configuration."""
    return Settings(
        ENVIRONMENT="test",
        PROJECT_NAME="Bharmafills API (Test)",
        VERSION="0.1.0-test",
        API_V1_PREFIX="/api/v1",
        CORS_ORIGINS=["http://localhost:5173", "http://127.0.0.1:5173", "http://testserver"],
        SUPABASE_DB_URL=None,
        SUPABASE_URL="https://test-project.supabase.co",
        SUPABASE_JWKS_URL="https://test-project.supabase.co/auth/v1/.well-known/jwks.json",
        SUPABASE_JWT_ISSUER="https://test-project.supabase.co/auth/v1",
        SUPABASE_JWT_AUDIENCE="authenticated",
        SUPABASE_JWT_ALGORITHMS=["ES256"],
        SUPABASE_JWT_SECRET=None,
        OPENROUTER_API_KEY=None,
        _env_file=None,
    )


@pytest.fixture
def mock_jwks_client(test_ec_keypair):
    """Provide a mock JWKS client that resolves the test public key without network calls."""
    _, public_key = test_ec_keypair
    client = MagicMock()
    mock_key = MagicMock()
    mock_key.key = public_key
    client.get_signing_key.return_value = mock_key
    return client


@pytest.fixture
def test_verifier(test_settings: Settings, mock_jwks_client) -> SupabaseJWTVerifier:
    """Provide a SupabaseJWTVerifier configured with in-memory test public key."""
    return SupabaseJWTVerifier(settings=test_settings, jwks_client=mock_jwks_client)


@pytest.fixture
def app(test_settings: Settings, test_verifier: SupabaseJWTVerifier) -> FastAPI:
    """Create a fresh FastAPI application instance configured with test verifier."""
    application = create_app(settings=test_settings)
    application.dependency_overrides[get_jwt_verifier] = lambda: test_verifier
    return application


@pytest.fixture
def client(app: FastAPI, auth_headers: dict[str, str]) -> Generator[TestClient, None, None]:
    """Synchronous test client authenticated with valid test JWT by default."""
    with TestClient(app, base_url="http://testserver", headers=auth_headers) as test_client:
        yield test_client


@pytest.fixture
async def async_client(app: FastAPI, auth_headers: dict[str, str]) -> AsyncGenerator[AsyncClient, None]:
    """Asynchronous HTTPX test client authenticated with valid test JWT by default."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver", headers=auth_headers) as ac:
        yield ac


@pytest.fixture
def unauthenticated_client(app: FastAPI) -> Generator[TestClient, None, None]:
    """Synchronous test client without Authorization header for testing 401 boundaries."""
    with TestClient(app, base_url="http://testserver") as test_client:
        yield test_client


@pytest.fixture
async def unauthenticated_async_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Asynchronous test client without Authorization header for testing 401 boundaries."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
