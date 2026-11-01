"""Core Supabase JWT verification module, JWKS caching, and FastAPI authentication dependencies."""

import logging
import time
from typing import Any
from uuid import UUID

import jwt
from jwt import PyJWKClient, PyJWKSet
from jwt.exceptions import (
    DecodeError,
    ExpiredSignatureError,
    ImmatureSignatureError,
    InvalidAlgorithmError as PyJWTInvalidAlgorithmError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError as PyJWTInvalidSignatureError,
    InvalidTokenError as PyJWTInvalidTokenError,
    MissingRequiredClaimError,
    PyJWKClientConnectionError,
    PyJWKClientError,
)
from fastapi import Depends, HTTPException, Request, status

from app.core.auth_schemas import (
    AuthenticatedUser,
    AuthenticationConfigurationError,
    AuthenticationError,
    ExpiredTokenError,
    InvalidAlgorithmError,
    InvalidSignatureError,
    InvalidTokenError,
    JWKSUnavailableError,
    MissingTokenError,
)
from app.core.config import Settings, get_settings

logger = logging.getLogger("bharmafills.auth")


class ResilientJWKClient:
    """Wrapper around PyJWKClient providing outbound rate limiting and failure containment."""

    def __init__(
        self,
        jwks_url: str,
        cache_ttl_seconds: float = 3600.0,
        refresh_cooldown_seconds: float = 10.0,
        inner_client: PyJWKClient | None = None,
    ) -> None:
        self.jwks_url = jwks_url
        self.cache_ttl_seconds = int(cache_ttl_seconds)
        self.refresh_cooldown_seconds = refresh_cooldown_seconds
        self._last_refresh_time: float = 0.0

        if inner_client is not None:
            self._client = inner_client
        else:
            self._client = PyJWKClient(
                uri=self.jwks_url,
                cache_keys=True,
                max_cached_keys=16,
                cache_jwk_set=True,
                lifespan=self.cache_ttl_seconds,
                timeout=10,
            )

    def get_signing_key(self, token: str) -> Any:
        """Retrieve signing key for token while enforcing refresh cooldown on unknown kid."""
        now = time.monotonic()
        try:
            return self._client.get_signing_key_from_jwt(token)
        except (PyJWKClientError, PyJWKClientConnectionError) as exc:
            # Check if this was a refresh attempt that exceeded cooldown
            time_since_last_refresh = now - self._last_refresh_time
            if time_since_last_refresh < self.refresh_cooldown_seconds:
                logger.warning(
                    "JWKS key lookup failed; forced refresh throttled by cooldown (%.1fs < %.1fs)",
                    time_since_last_refresh,
                    self.refresh_cooldown_seconds,
                )
                raise JWKSUnavailableError(
                    "Signing key lookup throttled due to rapid refresh attempts."
                ) from exc

            self._last_refresh_time = now
            logger.warning("JWKS lookup error from %s: %s", self.jwks_url, exc.__class__.__name__)
            raise JWKSUnavailableError(
                "Unable to retrieve signing key from identity provider JWKS endpoint."
            ) from exc
        except Exception as exc:
            logger.error("Unexpected error in JWKS client: %s", exc.__class__.__name__)
            raise JWKSUnavailableError("Unexpected error during JWKS key retrieval.") from exc


class SupabaseJWTVerifier:
    """Cryptographic verifier for Supabase Auth JWT tokens supporting ES256 (JWKS) and HS256."""

    def __init__(
        self,
        settings: Settings | None = None,
        jwks_client: Any | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._jwks_url = self._settings.effective_jwks_url
        self._issuer = self._settings.effective_jwt_issuer
        self._audience = self._settings.SUPABASE_JWT_AUDIENCE
        self._allowed_algorithms = set(self._settings.SUPABASE_JWT_ALGORITHMS)
        self._hs256_secret = self._settings.SUPABASE_JWT_SECRET

        if jwks_client is not None:
            self._jwks_client = jwks_client
        elif self._jwks_url:
            self._jwks_client = ResilientJWKClient(
                jwks_url=self._jwks_url,
                cache_ttl_seconds=self._settings.SUPABASE_JWKS_CACHE_TTL_SECONDS,
                refresh_cooldown_seconds=self._settings.SUPABASE_JWKS_REFRESH_COOLDOWN_SECONDS,
            )
        else:
            self._jwks_client = None

    @property
    def is_configured(self) -> bool:
        """Return True if asymmetric JWKS or legacy HS256 is configured."""
        return bool(self._jwks_client or self._hs256_secret)

    def verify_token(self, token: str) -> AuthenticatedUser:
        """Cryptographically verify a JWT and return an AuthenticatedUser model.

        Enforces:
        - Strict algorithm whitelisting (rejecting 'none', algorithm confusion).
        - Signature verification before payload trust.
        - Expiration (exp) and not-before (nbf) validity.
        - Issuer (iss) and audience (aud) checks.
        - Subject (sub) claim present and valid UUID.
        - Never logs or exposes raw tokens or secret key material.
        """
        if not self.is_configured:
            raise AuthenticationConfigurationError(
                "Supabase JWT verification is not configured (missing JWKS URL or secret)."
            )

        if not token or not isinstance(token, str) or not token.strip():
            raise InvalidTokenError("Authentication token is empty or invalid.")

        cleaned_token = token.strip()

        # Step 1: Inspect unverified header to extract algorithm and key id
        try:
            unverified_header = jwt.get_unverified_header(cleaned_token)
        except (DecodeError, PyJWTInvalidTokenError) as exc:
            raise InvalidTokenError("Malformed JWT structure; header cannot be parsed.") from exc

        alg = unverified_header.get("alg")
        if not alg or not isinstance(alg, str):
            raise InvalidAlgorithmError("JWT header is missing 'alg' claim.")

        # Defense against 'none' algorithm and unexpected algorithms
        if alg.lower() == "none" or alg not in self._allowed_algorithms:
            raise InvalidAlgorithmError(f"Prohibited or disallowed signing algorithm: '{alg}'.")

        # Step 2: Route verification according to algorithm
        if alg == "HS256":
            claims = self._verify_hs256(cleaned_token)
        elif alg in {"ES256", "RS256"}:
            claims = self._verify_asymmetric(cleaned_token, alg)
        else:
            raise InvalidAlgorithmError(f"Algorithm '{alg}' is not supported for verification.")

        # Step 3: Validate subject claim and build AuthenticatedUser
        sub = claims.get("sub")
        if not sub:
            raise InvalidTokenError("JWT is missing required subject ('sub') claim.")

        try:
            user_id = UUID(str(sub).strip())
        except (ValueError, TypeError) as exc:
            raise InvalidTokenError(f"JWT subject ('sub') is not a valid UUID: {sub}") from exc

        role = claims.get("role", "authenticated")
        email = claims.get("email")
        app_metadata = claims.get("app_metadata") or {}
        user_metadata = claims.get("user_metadata") or {}

        if not isinstance(app_metadata, dict):
            app_metadata = {}
        if not isinstance(user_metadata, dict):
            user_metadata = {}

        return AuthenticatedUser(
            id=user_id,
            email=str(email) if email is not None else None,
            role=str(role) if role is not None else "authenticated",
            app_metadata=app_metadata,
            user_metadata=user_metadata,
        )

    def _verify_asymmetric(self, token: str, expected_alg: str) -> dict[str, Any]:
        """Verify asymmetric ES256/RS256 token using public key from JWKS."""
        if self._jwks_client is None:
            raise AuthenticationConfigurationError(
                "Asymmetric JWT verification requested, but JWKS client is not configured."
            )

        # Retrieve public signing key from JWKS (PyJWT handles kid matching)
        try:
            signing_key = self._jwks_client.get_signing_key(token)
        except JWKSUnavailableError:
            raise
        except Exception as exc:
            raise JWKSUnavailableError("Failed to resolve public key from JWKS.") from exc

        key = signing_key.key if hasattr(signing_key, "key") else signing_key

        decode_options: dict[str, Any] = {
            "require": ["exp", "sub"],
            "verify_signature": True,
            "verify_exp": True,
            "verify_nbf": True,
            "verify_iat": True,
            "verify_aud": bool(self._audience),
            "verify_iss": bool(self._issuer),
        }

        try:
            return jwt.decode(
                token,
                key,
                algorithms=[expected_alg],
                audience=self._audience,
                issuer=self._issuer,
                options=decode_options,
                leeway=0,
            )
        except ExpiredSignatureError as exc:
            raise ExpiredTokenError("Authentication token has expired.") from exc
        except ImmatureSignatureError as exc:
            raise InvalidTokenError("Authentication token is not yet valid (future nbf).") from exc
        except MissingRequiredClaimError as exc:
            raise InvalidTokenError(f"JWT is missing required subject claim: {exc}") from exc
        except InvalidAudienceError as exc:
            raise InvalidTokenError(f"JWT audience mismatch (expected '{self._audience}').") from exc
        except InvalidIssuerError as exc:
            raise InvalidTokenError("JWT issuer mismatch.") from exc
        except PyJWTInvalidSignatureError as exc:
            raise InvalidSignatureError("JWT signature verification failed.") from exc
        except PyJWTInvalidAlgorithmError as exc:
            raise InvalidAlgorithmError(f"Invalid signing algorithm for asymmetric path: {exc}") from exc
        except (DecodeError, PyJWTInvalidTokenError) as exc:
            raise InvalidTokenError(f"Failed to decode or validate token: {exc}") from exc

    def _verify_hs256(self, token: str) -> dict[str, Any]:
        """Verify symmetric HS256 token using dedicated secret (legacy/local only)."""
        if not self._hs256_secret:
            raise InvalidAlgorithmError(
                "HS256 signing is not permitted because SUPABASE_JWT_SECRET is not configured."
            )

        decode_options: dict[str, Any] = {
            "require": ["exp", "sub"],
            "verify_signature": True,
            "verify_exp": True,
            "verify_nbf": True,
            "verify_iat": True,
            "verify_aud": bool(self._audience),
            "verify_iss": bool(self._issuer),
        }

        try:
            return jwt.decode(
                token,
                self._hs256_secret,
                algorithms=["HS256"],
                audience=self._audience,
                issuer=self._issuer,
                options=decode_options,
                leeway=0,
            )
        except ExpiredSignatureError as exc:
            raise ExpiredTokenError("Authentication token has expired.") from exc
        except ImmatureSignatureError as exc:
            raise InvalidTokenError("Authentication token is not yet valid (future nbf).") from exc
        except MissingRequiredClaimError as exc:
            raise InvalidTokenError(f"JWT is missing required subject claim: {exc}") from exc
        except InvalidAudienceError as exc:
            raise InvalidTokenError(f"JWT audience mismatch (expected '{self._audience}').") from exc
        except InvalidIssuerError as exc:
            raise InvalidTokenError("JWT issuer mismatch.") from exc
        except PyJWTInvalidSignatureError as exc:
            raise InvalidSignatureError("JWT signature verification failed.") from exc
        except (DecodeError, PyJWTInvalidTokenError) as exc:
            raise InvalidTokenError(f"Failed to decode or validate token: {exc}") from exc


# Singleton instance cached
_verifier_instance: SupabaseJWTVerifier | None = None


def get_jwt_verifier(settings: Settings = Depends(get_settings)) -> SupabaseJWTVerifier:
    """FastAPI dependency providing cached SupabaseJWTVerifier instance."""
    global _verifier_instance
    if _verifier_instance is None or _verifier_instance._settings is not settings:
        _verifier_instance = SupabaseJWTVerifier(settings=settings)
    return _verifier_instance


# =============================================================================
# FastAPI Authentication Dependencies
# =============================================================================

async def get_current_user(
    request: Request,
    verifier: SupabaseJWTVerifier = Depends(get_jwt_verifier),
) -> AuthenticatedUser:
    """Enforce authenticated caller identity on protected FastAPI endpoints.

    Extracts Bearer token from the Authorization header, validates signature and claims,
    and returns an AuthenticatedUser. Rejects unauthenticated callers with HTTP 401.

    Headers Emitted on 401:
        WWW-Authenticate: Bearer error="<code_hint>"
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Provide 'Authorization: Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = auth_header.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization scheme. Bearer scheme required.",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_request\""},
        )

    token = parts[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empty bearer token.",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
        )

    try:
        return verifier.verify_token(token)
    except ExpiredTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired.",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\", error_description=\"The token has expired\""},
        )
    except (InvalidSignatureError, InvalidAlgorithmError, InvalidTokenError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or unauthorized authentication token.",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
        )
    except JWKSUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication identity provider is temporarily unavailable.",
            headers={"WWW-Authenticate": "Bearer error=\"temporarily_unavailable\""},
        )
    except AuthenticationConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication service is not properly configured.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as exc:
        logger.error("Unhandled exception during token verification: %s", exc.__class__.__name__)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed.",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_optional_user(
    request: Request,
    verifier: SupabaseJWTVerifier = Depends(get_jwt_verifier),
) -> AuthenticatedUser | None:
    """Extract authenticated caller if Bearer token is provided; otherwise returns None.

    If an Authorization header is provided but invalid/expired, still raises HTTP 401.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.strip():
        return None

    return await get_current_user(request=request, verifier=verifier)
