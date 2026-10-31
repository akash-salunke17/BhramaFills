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

    model_config = SettingsConfigDict(
        env_file=".env",
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
