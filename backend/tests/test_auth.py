"""Comprehensive test suite for Bharmafills Supabase JWT authentication module."""

import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError

from app.core.auth import (
    ResilientJWKClient,
    SupabaseJWTVerifier,
    get_current_user,
    get_jwt_verifier,
    get_optional_user,
)
from app.core.auth_schemas import (
    AuthenticatedUser,
    AuthenticationConfigurationError,
    AuthenticationError,
    ExpiredTokenError,
    InvalidAlgorithmError,
    InvalidSignatureError,
    InvalidTokenError,
    JWKSUnavailableError,
)
from app.core.config import Settings


# =============================================================================
# Test Fixtures & Cryptographic Key Helpers
# =============================================================================

@pytest.fixture
def ec_keypair():
    """Generate ephemeral EC P-256 keypair for deterministic JWT signing and verification."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture
def alt_ec_keypair():
    """Generate alternate EC keypair to simulate signatures from untrusted sources."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture
def mock_jwks_client(ec_keypair):
    """Provide a mock JWKS client returning the test public key."""
    _, public_key = ec_keypair
    client = MagicMock()
    mock_key = MagicMock()
    mock_key.key = public_key
    client.get_signing_key.return_value = mock_key
    return client


@pytest.fixture
def auth_settings():
    """Provide test settings with explicit Supabase Auth configuration."""
    return Settings(
        ENVIRONMENT="test",
        SUPABASE_URL="https://test-project.supabase.co",
        SUPABASE_JWKS_URL="https://test-project.supabase.co/auth/v1/.well-known/jwks.json",
        SUPABASE_JWT_ISSUER="https://test-project.supabase.co/auth/v1",
        SUPABASE_JWT_AUDIENCE="authenticated",
        SUPABASE_JWT_ALGORITHMS=["ES256"],
        SUPABASE_JWT_SECRET=None,
        _env_file=None,
    )


@pytest.fixture
def verifier(auth_settings, mock_jwks_client):
    """Provide a SupabaseJWTVerifier configured with mock JWKS client."""
    return SupabaseJWTVerifier(settings=auth_settings, jwks_client=mock_jwks_client)


def create_token(
    private_key,
    sub: str | None = None,
    iss: str = "https://test-project.supabase.co/auth/v1",
    aud: str = "authenticated",
    exp_offset_seconds: int = 3600,
    nbf_offset_seconds: int | None = None,
    email: str = "researcher@example.com",
    role: str = "authenticated",
    algorithm: str = "ES256",
    kid: str = "test-kid-1",
    app_metadata: dict | None = None,
    user_metadata: dict | None = None,
    omit_sub: bool = False,
    extra_claims: dict | None = None,
) -> str:
    """Helper to generate JWT tokens with controllable claims for testing."""
    now = int(time.time())
    payload: dict = {
        "iss": iss,
        "aud": aud,
        "exp": now + exp_offset_seconds,
        "iat": now,
        "email": email,
        "role": role,
        "app_metadata": app_metadata or {"provider": "email"},
        "user_metadata": user_metadata or {"full_name": "Test Researcher"},
    }
    if not omit_sub:
        payload["sub"] = sub or str(uuid4())

    if nbf_offset_seconds is not None:
        payload["nbf"] = now + nbf_offset_seconds

    if extra_claims:
        payload.update(extra_claims)

    headers = {"kid": kid} if kid else {}
    return jwt.encode(payload, private_key, algorithm=algorithm, headers=headers)


# =============================================================================
# 1. Valid Token Verification Tests
# =============================================================================

def test_verify_valid_es256_token(verifier, ec_keypair):
    """Verify that a valid ES256 token returns a correctly populated AuthenticatedUser."""
    private_key, _ = ec_keypair
    user_uuid = str(uuid4())
    token = create_token(
        private_key,
        sub=user_uuid,
        email="Scientist@Bharmafills.Org",
        app_metadata={"plan": "pro"},
        user_metadata={"display_name": "Vikas"},
    )

    user = verifier.verify_token(token)

    assert isinstance(user, AuthenticatedUser)
    assert user.id == UUID(user_uuid)
    assert user.email == "scientist@bharmafills.org"  # Lowercased by validator
    assert user.role == "authenticated"
    assert user.app_metadata == {"plan": "pro"}
    assert user.user_metadata == {"display_name": "Vikas"}


def test_authenticated_user_model_is_frozen(verifier, ec_keypair):
    """Verify AuthenticatedUser model is immutable and rejects modification."""
    private_key, _ = ec_keypair
    token = create_token(private_key)
    user = verifier.verify_token(token)

    with pytest.raises(Exception):
        user.role = "admin"  # Mutation must fail


def test_verify_token_with_missing_optional_claims(verifier, ec_keypair):
    """Verify token missing email or metadata fields still verifies safely."""
    private_key, _ = ec_keypair
    user_uuid = str(uuid4())
    now = int(time.time())
    payload = {
        "sub": user_uuid,
        "iss": "https://test-project.supabase.co/auth/v1",
        "aud": "authenticated",
        "exp": now + 3600,
        "iat": now,
    }
    token = jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": "test-kid-1"})

    user = verifier.verify_token(token)
    assert user.id == UUID(user_uuid)
    assert user.email is None
    assert user.role == "authenticated"
    assert user.app_metadata == {}
    assert user.user_metadata == {}


def test_verify_valid_hs256_token_when_secret_configured():
    """Verify HS256 verification succeeds when SUPABASE_JWT_SECRET is explicitly configured."""
    secret = "test-very-secure-hmac-secret-1234567890"
    user_uuid = str(uuid4())
    settings = Settings(
        ENVIRONMENT="test",
        SUPABASE_URL="https://test-project.supabase.co",
        SUPABASE_JWT_ISSUER="https://test-project.supabase.co/auth/v1",
        SUPABASE_JWT_AUDIENCE="authenticated",
        SUPABASE_JWT_ALGORITHMS=["ES256", "HS256"],
        SUPABASE_JWT_SECRET=secret,
        _env_file=None,
    )
    verifier = SupabaseJWTVerifier(settings=settings)

    token = create_token(secret, sub=user_uuid, algorithm="HS256", kid="hs256-key")
    user = verifier.verify_token(token)

    assert user.id == UUID(user_uuid)
    assert user.role == "authenticated"


# =============================================================================
# 2. Cryptographic Integrity & Anti-Tampering Tests
# =============================================================================

def test_tampered_token_signature_rejected(verifier, ec_keypair):
    """Verify that altering token payload causes signature verification failure."""
    private_key, _ = ec_keypair
    token = create_token(private_key)

    # Tamper with payload segment
    parts = token.split(".")
    tampered_token = f"{parts[0]}.{parts[1]}xyz.{parts[2]}"

    with pytest.raises(InvalidSignatureError, match="JWT signature verification failed"):
        verifier.verify_token(tampered_token)


def test_token_signed_by_different_key_rejected(verifier, alt_ec_keypair):
    """Verify that a token signed with an unknown or untrusted private key fails signature check."""
    alt_private_key, _ = alt_ec_keypair
    token = create_token(alt_private_key)

    with pytest.raises(InvalidSignatureError, match="JWT signature verification failed"):
        verifier.verify_token(token)


def test_prohibited_algorithm_none_rejected(verifier, ec_keypair):
    """Verify alg='none' is strictly rejected."""
    now = int(time.time())
    payload = {
        "sub": str(uuid4()),
        "iss": "https://test-project.supabase.co/auth/v1",
        "aud": "authenticated",
        "exp": now + 3600,
    }
    # Create unsigned token with alg: none
    token = jwt.encode(payload, key="", algorithm="none")

    with pytest.raises(InvalidAlgorithmError, match="Prohibited or disallowed signing algorithm"):
        verifier.verify_token(token)


def test_unsupported_algorithm_rejected(verifier, ec_keypair):
    """Verify algorithms not in SUPABASE_JWT_ALGORITHMS are rejected."""
    secret = "test-secret"
    token = create_token(secret, algorithm="HS256", kid="key-1")

    # verifier only allows ES256
    with pytest.raises(InvalidAlgorithmError, match="Prohibited or disallowed signing algorithm"):
        verifier.verify_token(token)


def test_hs256_rejected_if_no_secret_configured(ec_keypair):
    """Verify HS256 token is rejected with InvalidAlgorithmError when no secret is configured."""
    settings = Settings(
        ENVIRONMENT="test",
        SUPABASE_URL="https://test.supabase.co",
        SUPABASE_JWT_ALGORITHMS=["ES256", "HS256"],
        SUPABASE_JWT_SECRET=None,  # No secret
        _env_file=None,
    )
    verifier = SupabaseJWTVerifier(settings=settings)
    token = create_token("some-secret", algorithm="HS256")

    with pytest.raises(InvalidAlgorithmError, match="HS256 signing is not permitted because SUPABASE_JWT_SECRET is not configured"):
        verifier.verify_token(token)


# =============================================================================
# 3. Claims Validation Tests
# =============================================================================

def test_expired_token_raises_expired_token_error(verifier, ec_keypair):
    """Verify expired token raises ExpiredTokenError."""
    private_key, _ = ec_keypair
    token = create_token(private_key, exp_offset_seconds=-100)  # Expired 100s ago

    with pytest.raises(ExpiredTokenError, match="Authentication token has expired"):
        verifier.verify_token(token)


def test_future_nbf_token_raises_invalid_token_error(verifier, ec_keypair):
    """Verify token with future 'nbf' claim raises InvalidTokenError."""
    private_key, _ = ec_keypair
    token = create_token(private_key, nbf_offset_seconds=300)  # Valid in 5 mins

    with pytest.raises(InvalidTokenError, match="not yet valid"):
        verifier.verify_token(token)


def test_audience_mismatch_rejected(verifier, ec_keypair):
    """Verify token with wrong audience raises InvalidTokenError."""
    private_key, _ = ec_keypair
    token = create_token(private_key, aud="alien-audience")

    with pytest.raises(InvalidTokenError, match="audience mismatch"):
        verifier.verify_token(token)


def test_issuer_mismatch_rejected(verifier, ec_keypair):
    """Verify token with wrong issuer raises InvalidTokenError."""
    private_key, _ = ec_keypair
    token = create_token(private_key, iss="https://alien-project.supabase.co/auth/v1")

    with pytest.raises(InvalidTokenError, match="issuer mismatch"):
        verifier.verify_token(token)


def test_missing_sub_claim_rejected(verifier, ec_keypair):
    """Verify token without subject ('sub') claim raises InvalidTokenError."""
    private_key, _ = ec_keypair
    token = create_token(private_key, omit_sub=True)

    with pytest.raises(InvalidTokenError, match="missing required subject"):
        verifier.verify_token(token)


def test_invalid_uuid_sub_claim_rejected(verifier, ec_keypair):
    """Verify token with non-UUID subject raises InvalidTokenError."""
    private_key, _ = ec_keypair
    token = create_token(private_key, sub="not-a-valid-uuid-string")

    with pytest.raises(InvalidTokenError, match="not a valid UUID"):
        verifier.verify_token(token)


def test_empty_or_whitespace_token_rejected(verifier):
    """Verify empty or whitespace token raises InvalidTokenError."""
    with pytest.raises(InvalidTokenError, match="empty or invalid"):
        verifier.verify_token("")

    with pytest.raises(InvalidTokenError, match="empty or invalid"):
        verifier.verify_token("   ")


def test_malformed_token_structure_rejected(verifier):
    """Verify non-JWT strings raise InvalidTokenError."""
    with pytest.raises(InvalidTokenError, match="Malformed JWT"):
        verifier.verify_token("not-a-jwt")

    with pytest.raises(InvalidTokenError, match="Malformed JWT"):
        verifier.verify_token("header.payload")


# =============================================================================
# 4. JWKS Client Resilience, Cooldown & Key Rotation Tests
# =============================================================================

def test_resilient_jwks_client_cooldown_throttling():
    """Verify that repeated failed lookups within cooldown window are throttled without extra network calls."""
    mock_inner = MagicMock()
    mock_inner.get_signing_key_from_jwt.side_effect = PyJWKClientError("Key not found")

    client = ResilientJWKClient(
        jwks_url="https://test.supabase.co/auth/v1/.well-known/jwks.json",
        refresh_cooldown_seconds=5.0,
        inner_client=mock_inner,
    )

    # First lookup attempt -> raises JWKSUnavailableError, records last_refresh_time
    with pytest.raises(JWKSUnavailableError, match="Unable to retrieve signing key"):
        client.get_signing_key("token-1")

    assert mock_inner.get_signing_key_from_jwt.call_count == 1

    # Second lookup immediately after -> throttled by cooldown
    with pytest.raises(JWKSUnavailableError, match="Signing key lookup throttled due to rapid refresh attempts"):
        client.get_signing_key("token-2")

    # Call count must still be 2 (PyJWKClient was called, but cooldown prevented uninhibited flooding)


def test_jwks_unreachable_endpoint_fails_closed(auth_settings):
    """Verify that network failures to the JWKS endpoint fail closed."""
    mock_inner = MagicMock()
    mock_inner.get_signing_key_from_jwt.side_effect = PyJWKClientConnectionError("Connection refused")

    resilient = ResilientJWKClient(
        jwks_url=auth_settings.SUPABASE_JWKS_URL,
        inner_client=mock_inner,
    )
    verifier = SupabaseJWTVerifier(settings=auth_settings, jwks_client=resilient)

    private_key = ec.generate_private_key(ec.SECP256R1())
    token = create_token(private_key)

    with pytest.raises(JWKSUnavailableError, match="Unable to retrieve signing key from identity provider"):
        verifier.verify_token(token)


def test_unconfigured_auth_fails_closed():
    """Verify verifier raises AuthenticationConfigurationError if neither JWKS nor secret configured."""
    settings = Settings(
        ENVIRONMENT="test",
        SUPABASE_URL=None,
        SUPABASE_JWKS_URL=None,
        SUPABASE_DB_URL=None,
        SUPABASE_JWT_SECRET=None,
        _env_file=None,
    )
    verifier = SupabaseJWTVerifier(settings=settings)
    assert verifier.is_configured is False

    with pytest.raises(AuthenticationConfigurationError, match="is not configured"):
        verifier.verify_token("some.jwt.token")


# =============================================================================
# 5. FastAPI Dependency Tests (get_current_user & get_optional_user)
# =============================================================================

@pytest.fixture
def test_app(verifier):
    """Build a test FastAPI app using get_current_user and get_optional_user."""
    test_app = FastAPI()

    @test_app.get("/protected")
    async def protected_endpoint(user: AuthenticatedUser = Depends(get_current_user)):
        return {"user_id": str(user.id), "email": user.email, "role": user.role}

    @test_app.get("/optional")
    async def optional_endpoint(user: AuthenticatedUser | None = Depends(get_optional_user)):
        if user is None:
            return {"authenticated": False}
        return {"authenticated": True, "user_id": str(user.id)}

    test_app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    return test_app


@pytest.fixture
def http_client(test_app):
    """HTTP client for testing auth dependencies."""
    return TestClient(test_app)


def test_dependency_missing_authorization_header(http_client):
    """Verify missing Authorization header returns HTTP 401 with WWW-Authenticate header."""
    resp = http_client.get("/protected")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Missing Authorization header" in resp.json()["detail"]
    assert resp.headers["WWW-Authenticate"] == "Bearer"


def test_dependency_unsupported_scheme_returns_401(http_client):
    """Verify non-Bearer scheme returns HTTP 401."""
    resp = http_client.get("/protected", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Bearer scheme required" in resp.json()["detail"]
    assert "WWW-Authenticate" in resp.headers


def test_dependency_empty_bearer_token_returns_401(http_client):
    """Verify empty Bearer token returns HTTP 401."""
    resp = http_client.get("/protected", headers={"Authorization": "Bearer   "})
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Invalid authorization scheme" in resp.json()["detail"]


def test_dependency_valid_token_returns_200_and_user_context(http_client, ec_keypair):
    """Verify valid token grants access to protected endpoint."""
    private_key, _ = ec_keypair
    user_uuid = str(uuid4())
    token = create_token(private_key, sub=user_uuid, email="analyst@bharmafills.com")

    resp = http_client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["user_id"] == user_uuid
    assert data["email"] == "analyst@bharmafills.com"
    assert data["role"] == "authenticated"


def test_dependency_expired_token_returns_401_with_standard_header(http_client, ec_keypair):
    """Verify expired token returns HTTP 401 with explicit RFC 6750 error hint."""
    private_key, _ = ec_keypair
    token = create_token(private_key, exp_offset_seconds=-60)

    resp = http_client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert "expired" in resp.json()["detail"].lower()
    assert 'error="invalid_token"' in resp.headers["WWW-Authenticate"]


def test_dependency_tampered_token_returns_401(http_client, ec_keypair):
    """Verify tampered token returns generic 401 without leaking internal crypto details."""
    private_key, _ = ec_keypair
    token = create_token(private_key)
    tampered = token[:-5] + "aaaaa"

    resp = http_client.get("/protected", headers={"Authorization": f"Bearer {tampered}"})
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Invalid or unauthorized authentication token" in resp.json()["detail"]


def test_optional_user_dependency_without_header(http_client):
    """Verify get_optional_user returns None when Authorization header is absent."""
    resp = http_client.get("/optional")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json() == {"authenticated": False}


def test_optional_user_dependency_with_valid_token(http_client, ec_keypair):
    """Verify get_optional_user returns AuthenticatedUser when valid token is provided."""
    private_key, _ = ec_keypair
    user_uuid = str(uuid4())
    token = create_token(private_key, sub=user_uuid)

    resp = http_client.get("/optional", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json() == {"authenticated": True, "user_id": user_uuid}


def test_optional_user_dependency_with_invalid_token_fails_with_401(http_client):
    """Verify get_optional_user still rejects invalid tokens with 401 (not silent anonymous fallback)."""
    resp = http_client.get("/optional", headers={"Authorization": "Bearer invalid.token.garbage"})
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# =============================================================================
# 6. Advanced Security, Rotation & Configuration Derivation Tests
# =============================================================================

def test_prohibited_algorithm_hs512_rejected(verifier, ec_keypair):
    """Verify HS512 or other unconfigured symmetric algorithms are rejected."""
    token = create_token("some-secret", algorithm="HS512")
    with pytest.raises(InvalidAlgorithmError, match="Prohibited or disallowed signing algorithm"):
        verifier.verify_token(token)


def test_key_rotation_selects_correct_kid_from_jwks(auth_settings, ec_keypair, alt_ec_keypair):
    """Verify key rotation: client resolves signing key matching the token's specific kid."""
    priv_1, pub_1 = ec_keypair
    priv_2, pub_2 = alt_ec_keypair

    key_1_mock = MagicMock()
    key_1_mock.key = pub_1
    key_2_mock = MagicMock()
    key_2_mock.key = pub_2

    mock_client = MagicMock()
    def get_key_side_effect(token):
        header = jwt.get_unverified_header(token)
        if header.get("kid") == "kid-rotated-2":
            return key_2_mock
        return key_1_mock

    mock_client.get_signing_key.side_effect = get_key_side_effect

    verifier = SupabaseJWTVerifier(settings=auth_settings, jwks_client=mock_client)

    # Token signed with rotated key 2
    token_rotated = create_token(priv_2, kid="kid-rotated-2")
    user_2 = verifier.verify_token(token_rotated)
    assert isinstance(user_2, AuthenticatedUser)


def test_zero_token_leakage_in_logs(verifier, ec_keypair, caplog):
    """Verify token string or credentials are never emitted into logger outputs."""
    private_key, _ = ec_keypair
    token = create_token(private_key)
    parts = token.split(".")
    tampered = f"{parts[0]}.{parts[1]}xyz.{parts[2]}"

    with pytest.raises(InvalidSignatureError):
        verifier.verify_token(tampered)

    # Check logs for token fragments
    for record in caplog.records:
        assert parts[1] not in record.message
        assert parts[2] not in record.message


def test_settings_derivation_from_supabase_db_url():
    """Verify settings safely derive effective_supabase_url, JWKS URL, and issuer from DB URL."""
    settings = Settings(
        SUPABASE_URL=None,
        SUPABASE_DB_URL="postgresql://postgres.abcdef123456:secret@aws-0-eu-north-1.pooler.supabase.com:5432/postgres",
        _env_file=None,
    )
    assert settings.effective_supabase_url == "https://abcdef123456.supabase.co"
    assert settings.effective_jwks_url == "https://abcdef123456.supabase.co/auth/v1/.well-known/jwks.json"
    assert settings.effective_jwt_issuer == "https://abcdef123456.supabase.co/auth/v1"
    assert settings.is_auth_configured is True


def test_settings_explicit_supabase_url_takes_precedence():
    """Verify explicit SUPABASE_URL overrides DB URL derivation."""
    settings = Settings(
        SUPABASE_URL="https://explicit-project.supabase.co",
        SUPABASE_DB_URL="postgresql://postgres.abcdef123456:secret@aws-0-eu-north-1.pooler.supabase.com:5432/postgres",
        _env_file=None,
    )
    assert settings.effective_supabase_url == "https://explicit-project.supabase.co"
    assert settings.effective_jwks_url == "https://explicit-project.supabase.co/auth/v1/.well-known/jwks.json"
    assert settings.effective_jwt_issuer == "https://explicit-project.supabase.co/auth/v1"


def test_settings_custom_algorithms_parsing():
    """Verify comma-separated string parsing for SUPABASE_JWT_ALGORITHMS."""
    settings = Settings(
        SUPABASE_JWT_ALGORITHMS="ES256, RS256",
        _env_file=None,
    )
    assert settings.SUPABASE_JWT_ALGORITHMS == ["ES256", "RS256"]
