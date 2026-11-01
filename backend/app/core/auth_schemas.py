"""Authentication schemas, models, and domain exceptions for Bharmafills."""

from typing import Any
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AuthenticatedUser(BaseModel):
    """Immutable representation of a cryptographically validated user identity.

    Security Notes:
    - `id` corresponds strictly to the verified JWT `sub` claim.
    - `user_metadata` contains arbitrary user-editable values from Supabase Auth
      and MUST NEVER be trusted for authorization, tenant boundary enforcement,
      or project ownership decisions.
    - `role` indicates the Supabase token role (e.g. 'authenticated', 'anon')
      and does NOT imply ownership of any specific research project.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(
        ...,
        description="Unique user UUID extracted from verified JWT subject claim",
    )
    email: str | None = Field(
        default=None,
        description="User email address if present and verified in token claims",
    )
    role: str = Field(
        default="authenticated",
        description="Supabase Auth assigned role claim",
    )
    app_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Application-level metadata assigned by identity provider",
    )
    user_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="User-level metadata (untrusted for authorization decisions)",
    )

    @field_validator("email", mode="before")
    @classmethod
    def sanitize_email(cls, value: Any) -> str | None:
        """Validate and sanitize email if present."""
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip().lower()
            return cleaned if cleaned else None
        return None

    @field_validator("role", mode="before")
    @classmethod
    def validate_role(cls, value: Any) -> str:
        """Ensure role is a non-empty string."""
        if not value or not isinstance(value, str) or not value.strip():
            return "authenticated"
        return value.strip()


# =============================================================================
# Authentication Domain Exceptions
# =============================================================================

class AuthenticationError(Exception):
    """Base domain exception for all authentication failures."""

    def __init__(self, message: str, error_code: str = "AUTHENTICATION_FAILED") -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class MissingTokenError(AuthenticationError):
    """Raised when Authorization header or bearer token is absent."""

    def __init__(self, message: str = "Missing Authorization header or Bearer token.") -> None:
        super().__init__(message, error_code="MISSING_TOKEN")


class InvalidTokenError(AuthenticationError):
    """Raised when a token structure, claim, or format is invalid."""

    def __init__(self, message: str = "Invalid or malformed authentication token.") -> None:
        super().__init__(message, error_code="INVALID_TOKEN")


class ExpiredTokenError(AuthenticationError):
    """Raised when a token has expired."""

    def __init__(self, message: str = "Authentication token has expired.") -> None:
        super().__init__(message, error_code="TOKEN_EXPIRED")


class InvalidSignatureError(AuthenticationError):
    """Raised when cryptographic signature verification fails or token was tampered with."""

    def __init__(self, message: str = "Invalid token signature or cryptographic integrity violation.") -> None:
        super().__init__(message, error_code="INVALID_SIGNATURE")


class InvalidAlgorithmError(AuthenticationError):
    """Raised when token uses an unsupported, prohibited, or unexpected algorithm."""

    def __init__(self, message: str = "Prohibited or unsupported signing algorithm.") -> None:
        super().__init__(message, error_code="INVALID_ALGORITHM")


class JWKSUnavailableError(AuthenticationError):
    """Raised when the JWKS endpoint is unreachable or returns invalid keys."""

    def __init__(self, message: str = "Unable to retrieve public signing keys from identity provider.") -> None:
        super().__init__(message, error_code="JWKS_UNAVAILABLE")


class AuthenticationConfigurationError(AuthenticationError):
    """Raised when required authentication parameters are missing or improperly configured."""

    def __init__(self, message: str = "Authentication service is not properly configured.") -> None:
        super().__init__(message, error_code="AUTH_NOT_CONFIGURED")

