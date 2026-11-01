"""Centralized application configuration management for Bharmafills."""

from functools import lru_cache
from typing import Literal
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings resolved from environment variables and defaults."""

    # Project Metadata
    PROJECT_NAME: str = Field(
        default="Bharmafills API",
        description="Public name of the API service",
    )
    VERSION: str = Field(
        default="0.1.0",
        description="Application semantic version",
    )
    DESCRIPTION: str = Field(
        default="AI-assisted Information Gap Detection Platform API",
        description="Brief summary of API capabilities",
    )

    # API Routing & Versioning
    API_V1_PREFIX: str = Field(
        default="/api/v1",
        description="Global prefix for Version 1 API routes",
    )

    # Runtime Environment
    ENVIRONMENT: Literal["development", "test", "staging", "production"] = Field(
        default="development",
        description="Active execution environment",
    )

    # Server Host & Port
    BACKEND_HOST: str = Field(
        default="127.0.0.1",
        description="Host interface for server binding",
    )
    BACKEND_PORT: int = Field(
        default=8000,
        ge=1024,
        le=65535,
        description="Port for server listener",
    )

    # CORS Configuration
    CORS_ORIGINS: list[str] = Field(
        default=["http://localhost:5173", "http://127.0.0.1:5173"],
        description="Allowed frontend origin URLs for CORS headers",
    )

    # Documentation Endpoints
    DOCS_URL: str | None = Field(
        default="/docs",
        description="Swagger UI path in development environments",
    )
    OPENAPI_URL: str | None = Field(
        default="/openapi.json",
        description="OpenAPI specification path",
    )
    REDOC_URL: str | None = Field(
        default="/redoc",
        description="ReDoc documentation path",
    )

    # Database Configuration (Supabase PostgreSQL Session Pooler)
    SUPABASE_DB_URL: str | None = Field(
        default=None,
        description="Supabase PostgreSQL Session Pooler connection URL",
    )
    DATABASE_CONNECT_TIMEOUT_SECONDS: float = Field(
        default=5.0,
        ge=0.5,
        le=30.0,
        description="Timeout in seconds for database connection attempts",
    )

    # Supabase Authentication & JWT Configuration
    SUPABASE_URL: str | None = Field(
        default=None,
        description="Base URL for Supabase project (e.g. https://<project-ref>.supabase.co)",
    )
    SUPABASE_JWKS_URL: str | None = Field(
        default=None,
        description="Public JWKS endpoint for asymmetric JWT verification",
    )
    SUPABASE_JWT_ISSUER: str | None = Field(
        default=None,
        description="Expected JWT issuer claim (e.g. https://<project-ref>.supabase.co/auth/v1)",
    )
    SUPABASE_JWT_AUDIENCE: str = Field(
        default="authenticated",
        description="Expected JWT audience claim",
    )
    SUPABASE_JWT_ALGORITHMS: list[str] = Field(
        default=["ES256"],
        description="Allowed signing algorithms for Supabase JWT verification",
    )
    SUPABASE_JWT_SECRET: str | None = Field(
        default=None,
        repr=False,
        description="Optional separate secret for legacy/local HS256 JWT verification",
    )
    SUPABASE_JWKS_CACHE_TTL_SECONDS: float = Field(
        default=3600.0,
        ge=60.0,
        le=86400.0,
        description="JWKS public key cache time-to-live in seconds",
    )
    SUPABASE_JWKS_REFRESH_COOLDOWN_SECONDS: float = Field(
        default=10.0,
        ge=1.0,
        le=300.0,
        description="Minimum cooldown period in seconds between forced JWKS cache refreshes",
    )

    # Web Extraction & SSRF Defense Configuration
    WEB_FETCH_MAX_REDIRECTS: int = Field(
        default=5,
        ge=0,
        le=10,
        description="Maximum redirect hops allowed during web fetching",
    )
    WEB_FETCH_MAX_RESPONSE_BYTES: int = Field(
        default=2 * 1024 * 1024,  # 2 MB
        ge=1024,
        le=20 * 1024 * 1024,
        description="Maximum allowed HTML response body size in bytes",
    )
    WEB_FETCH_TIMEOUT_CONNECT_SECONDS: float = Field(
        default=5.0,
        ge=0.5,
        le=30.0,
        description="Socket connection timeout for web fetching in seconds",
    )
    WEB_FETCH_TIMEOUT_READ_SECONDS: float = Field(
        default=10.0,
        ge=1.0,
        le=60.0,
        description="Response streaming read timeout for web fetching in seconds",
    )
    WEB_FETCH_USER_AGENT: str = Field(
        default="Bharmafills-Extractor/1.0 (+https://bharmafills.hackathon)",
        description="Controlled HTTP User-Agent header for web extraction",
    )

    # PDF Extraction Configuration
    PDF_MAX_UPLOAD_BYTES: int = Field(
        default=20 * 1024 * 1024,  # 20 MB
        ge=1024,
        le=100 * 1024 * 1024,
        description="Maximum allowed PDF upload size in bytes (default 20 MB)",
    )
    PDF_MAX_PAGES: int = Field(
        default=200,
        ge=1,
        le=2000,
        description="Maximum allowed pages per PDF document",
    )
    PDF_EXTRACTION_TIMEOUT_SECONDS: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Maximum timeout for PDF text extraction in seconds",
    )

    # AI Provider Configuration (OpenRouter + NVIDIA Nemotron 3 Ultra)
    OPENROUTER_API_KEY: str | None = Field(
        default=None,
        description="OpenRouter API key for LLM chat completions",
    )
    OPENROUTER_MODEL: str = Field(
        default="nvidia/nemotron-3-ultra-550b-a55b:free",
        description="Active OpenRouter model identifier (runtime-configurable)",
    )
    OPENROUTER_BASE_URL: str = Field(
        default="https://openrouter.ai/api/v1",
        description="Base API endpoint URL for OpenRouter completions",
    )
    OPENROUTER_TIMEOUT_SECONDS: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Maximum timeout in seconds for OpenRouter API requests",
    )

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, value: str | list[str]) -> list[str]:
        """Parse comma-separated strings or list of origins."""
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            # Split comma-separated string
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        if isinstance(value, (list, tuple)):
            return [str(origin).strip() for origin in value if str(origin).strip()]
        raise ValueError(f"Invalid CORS_ORIGINS format: {value}")

    @field_validator("API_V1_PREFIX")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        """Ensure API prefix starts with / and does not end with /."""
        cleaned = value.strip()
        if not cleaned.startswith("/"):
            cleaned = f"/{cleaned}"
        if cleaned.endswith("/") and len(cleaned) > 1:
            cleaned = cleaned.rstrip("/")
        return cleaned

    @field_validator("SUPABASE_DB_URL", mode="before")
    @classmethod
    def validate_database_url(cls, value: str | None) -> str | None:
        """Validate and normalize SUPABASE_DB_URL format."""
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return None
            if not (cleaned.startswith("postgresql://") or cleaned.startswith("postgres://")):
                raise ValueError("Invalid SUPABASE_DB_URL scheme: must start with postgresql:// or postgres://")
            return cleaned
        raise ValueError(f"Invalid SUPABASE_DB_URL format: expected string or None, got {type(value).__name__}")

    @field_validator("SUPABASE_URL", "SUPABASE_JWKS_URL", "SUPABASE_JWT_ISSUER", mode="before")
    @classmethod
    def validate_auth_urls(cls, value: str | None) -> str | None:
        """Validate URL scheme for Supabase auth endpoints if provided."""
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return None
            if not (cleaned.startswith("https://") or cleaned.startswith("http://")):
                raise ValueError("Auth URLs must start with https:// or http://")
            return cleaned.rstrip("/")
        raise ValueError(f"Invalid auth URL format: expected string or None, got {type(value).__name__}")

    @field_validator("SUPABASE_JWT_ALGORITHMS", mode="before")
    @classmethod
    def assemble_jwt_algorithms(cls, value: str | list[str]) -> list[str]:
        """Parse comma-separated string or list of algorithms."""
        if isinstance(value, str):
            cleaned = [alg.strip() for alg in value.split(",") if alg.strip()]
            return cleaned or ["ES256"]
        if isinstance(value, (list, tuple)):
            cleaned = [str(alg).strip() for alg in value if str(alg).strip()]
            return cleaned or ["ES256"]
        raise ValueError(f"Invalid SUPABASE_JWT_ALGORITHMS format: {value}")

    @field_validator("SUPABASE_JWT_SECRET", mode="before")
    @classmethod
    def validate_jwt_secret(cls, value: str | None) -> str | None:
        """Clean and trim optional HS256 secret."""
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned if cleaned else None
        return None

    @field_validator("OPENROUTER_API_KEY", mode="before")
    @classmethod
    def validate_openrouter_api_key(cls, value: str | None) -> str | None:
        """Validate and clean OPENROUTER_API_KEY."""
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned if cleaned else None
        return None

    @field_validator("OPENROUTER_BASE_URL", mode="before")
    @classmethod
    def validate_openrouter_base_url(cls, value: str | None) -> str:
        """Validate OpenRouter API base URL."""
        if not value or not isinstance(value, str):
            return "https://openrouter.ai/api/v1"
        cleaned = value.strip().rstrip("/")
        if not (cleaned.startswith("https://") or cleaned.startswith("http://")):
            raise ValueError("OPENROUTER_BASE_URL must start with https:// or http://")
        return cleaned

    @field_validator("OPENROUTER_MODEL", mode="before")
    @classmethod
    def validate_openrouter_model(cls, value: str | None) -> str:
        """Ensure OpenRouter model identifier is a non-empty string."""
        if not value or not isinstance(value, str) or not value.strip():
            return "nvidia/nemotron-3-ultra-550b-a55b:free"
        return value.strip()

    @property
    def is_ai_configured(self) -> bool:
        """Helper to determine whether an OpenRouter API key is configured."""
        return bool(self.OPENROUTER_API_KEY and self.OPENROUTER_API_KEY.strip())

    @property
    def is_database_configured(self) -> bool:
        """Helper to determine whether database URL is present and configured."""
        return bool(self.SUPABASE_DB_URL and self.SUPABASE_DB_URL.strip())

    @property
    def effective_supabase_url(self) -> str | None:
        """Return explicit SUPABASE_URL or safely derive project URL from SUPABASE_DB_URL."""
        if self.SUPABASE_URL and self.SUPABASE_URL.strip():
            return self.SUPABASE_URL.strip().rstrip("/")
        if self.SUPABASE_DB_URL:
            try:
                import urllib.parse
                parsed = urllib.parse.urlparse(self.SUPABASE_DB_URL)
                user = parsed.username or ""
                if "." in user:
                    project_ref = user.split(".", 1)[1]
                    if project_ref and project_ref.replace("-", "").isalnum():
                        return f"https://{project_ref}.supabase.co"
            except Exception:
                pass
        return None

    @property
    def effective_jwks_url(self) -> str | None:
        """Return explicit SUPABASE_JWKS_URL or derive from effective_supabase_url."""
        if self.SUPABASE_JWKS_URL and self.SUPABASE_JWKS_URL.strip():
            return self.SUPABASE_JWKS_URL.strip()
        base = self.effective_supabase_url
        if base:
            return f"{base}/auth/v1/.well-known/jwks.json"
        return None

    @property
    def effective_jwt_issuer(self) -> str | None:
        """Return explicit SUPABASE_JWT_ISSUER or derive from effective_supabase_url."""
        if self.SUPABASE_JWT_ISSUER and self.SUPABASE_JWT_ISSUER.strip():
            return self.SUPABASE_JWT_ISSUER.strip()
        base = self.effective_supabase_url
        if base:
            return f"{base}/auth/v1"
        return None

    @property
    def is_auth_configured(self) -> bool:
        """Helper to determine whether JWT verification parameters are available."""
        return bool(self.effective_jwks_url or self.SUPABASE_JWT_SECRET)

    @property
    def is_development(self) -> bool:
        """Helper to determine if running in local development mode."""
        return self.ENVIRONMENT == "development"

    @property
    def is_test(self) -> bool:
        """Helper to determine if running under pytest test runner."""
        return self.ENVIRONMENT == "test"

    @property
    def is_production(self) -> bool:
        """Helper to determine if running in production mode."""
        return self.ENVIRONMENT == "production"


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton instance of application settings."""
    return Settings()
