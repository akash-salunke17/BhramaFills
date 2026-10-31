"""Tests for application Settings and environment configuration management."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


def test_default_settings_validity() -> None:
    """Verify default Settings instance has valid expected attributes."""
    settings = Settings()
    assert settings.PROJECT_NAME == "Bharmafills API"
    assert settings.VERSION == "0.1.0"
    assert settings.API_V1_PREFIX == "/api/v1"
    assert settings.ENVIRONMENT == "development"
    assert settings.BACKEND_PORT == 8000
    assert "http://localhost:5173" in settings.CORS_ORIGINS


def test_environment_override_via_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify environment variables override default settings."""
    monkeypatch.setenv("PROJECT_NAME", "Custom Bharmafills Test")
    monkeypatch.setenv("VERSION", "2.0.0")
    monkeypatch.setenv("BACKEND_PORT", "9000")
    monkeypatch.setenv("ENVIRONMENT", "test")

    settings = Settings()
    assert settings.PROJECT_NAME == "Custom Bharmafills Test"
    assert settings.VERSION == "2.0.0"
    assert settings.BACKEND_PORT == 9000
    assert settings.ENVIRONMENT == "test"


def test_cors_origins_comma_separated_string_parsing() -> None:
    """Verify comma-separated string format for CORS_ORIGINS parses into clean list."""
    settings = Settings(
        CORS_ORIGINS="http://localhost:5173, http://127.0.0.1:5173, https://app.bharmafills.com "  # type: ignore[arg-type]
    )
    assert settings.CORS_ORIGINS == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://app.bharmafills.com",
    ]


def test_cors_origins_empty_string_handling() -> None:
    """Verify empty string for CORS_ORIGINS produces empty list."""
    settings = Settings(CORS_ORIGINS="")  # type: ignore[arg-type]
    assert settings.CORS_ORIGINS == []


def test_api_prefix_formatting() -> None:
    """Verify API_V1_PREFIX normalizes leading and trailing slashes."""
    s1 = Settings(API_V1_PREFIX="api/v2")
    assert s1.API_V1_PREFIX == "/api/v2"

    s2 = Settings(API_V1_PREFIX="/api/v3/")
    assert s2.API_V1_PREFIX == "/api/v3"


def test_invalid_environment_raises_validation_error() -> None:
    """Verify unsupported ENVIRONMENT value raises pydantic ValidationError."""
    with pytest.raises(ValidationError):
        Settings(ENVIRONMENT="invalid_env_mode")  # type: ignore[arg-type]


def test_invalid_port_range_raises_validation_error() -> None:
    """Verify out-of-range port numbers raise pydantic ValidationError."""
    # Port < 1024 (reserved non-root in standard unprivileged contexts)
    with pytest.raises(ValidationError):
        Settings(BACKEND_PORT=80)

    # Port > 65535
    with pytest.raises(ValidationError):
        Settings(BACKEND_PORT=70000)


def test_environment_helper_properties() -> None:
    """Verify is_development, is_test, and is_production boolean helpers."""
    dev = Settings(ENVIRONMENT="development")
    assert dev.is_development is True
    assert dev.is_test is False
    assert dev.is_production is False

    test_env = Settings(ENVIRONMENT="test")
    assert test_env.is_development is False
    assert test_env.is_test is True
    assert test_env.is_production is False

    prod = Settings(ENVIRONMENT="production")
    assert prod.is_development is False
    assert prod.is_test is False
    assert prod.is_production is True


def test_get_settings_singleton_caching() -> None:
    """Verify get_settings returns the same cached instance."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
