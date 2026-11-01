"""Unit tests verifying database configuration in Pydantic Settings."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_database_url_default_is_none():
    """Verify SUPABASE_DB_URL defaults to None and is_database_configured is False."""
    settings = Settings(_env_file=None)
    assert settings.SUPABASE_DB_URL is None
    assert settings.is_database_configured is False


def test_database_url_valid_postgresql_scheme():
    """Verify standard postgresql:// connection scheme is accepted."""
    url = "postgresql://mock_user:mock_pass@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
    settings = Settings(SUPABASE_DB_URL=url)
    assert settings.SUPABASE_DB_URL == url
    assert settings.is_database_configured is True


def test_database_url_valid_postgres_scheme():
    """Verify postgres:// alternative scheme is accepted."""
    url = "postgres://mock_user:mock_pass@mock_host:5432/postgres"
    settings = Settings(SUPABASE_DB_URL=url)
    assert settings.SUPABASE_DB_URL == url
    assert settings.is_database_configured is True


def test_database_url_whitespace_treated_as_none():
    """Verify whitespace-only strings are normalized to None."""
    settings = Settings(SUPABASE_DB_URL="   ")
    assert settings.SUPABASE_DB_URL is None
    assert settings.is_database_configured is False


def test_database_url_invalid_scheme_raises_validation_error():
    """Verify non-PostgreSQL schemes raise ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(SUPABASE_DB_URL="mysql://user:pass@localhost:3306/db")
    assert "Invalid SUPABASE_DB_URL scheme" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        Settings(SUPABASE_DB_URL="http://localhost:5432/postgres")
    assert "Invalid SUPABASE_DB_URL scheme" in str(exc_info.value)


def test_database_url_loaded_from_environment(monkeypatch):
    """Verify SUPABASE_DB_URL is correctly loaded from environment variable."""
    expected_url = "postgresql://env_user:env_pass@pooler.supabase.com:5432/postgres"
    monkeypatch.setenv("SUPABASE_DB_URL", expected_url)
    settings = Settings()
    assert settings.SUPABASE_DB_URL == expected_url
    assert settings.is_database_configured is True


def test_database_connect_timeout_bounds():
    """Verify timeout setting enforces valid positive ranges."""
    settings = Settings(DATABASE_CONNECT_TIMEOUT_SECONDS=10.0)
    assert settings.DATABASE_CONNECT_TIMEOUT_SECONDS == 10.0

    with pytest.raises(ValidationError):
        Settings(DATABASE_CONNECT_TIMEOUT_SECONDS=0.1)  # Below 0.5s min bound

    with pytest.raises(ValidationError):
        Settings(DATABASE_CONNECT_TIMEOUT_SECONDS=60.0)  # Above 30.0s max bound

