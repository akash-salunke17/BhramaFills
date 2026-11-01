"""Integration tests for database health endpoint and secret isolation."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.connection import DatabaseCheckResult, DatabaseManager, get_db_manager
from app.main import create_app


def test_basic_health_remains_independent_of_database(client: TestClient):
    """Verify basic /api/v1/health returns 200 regardless of database configuration."""
    response = client.get("/api/v1/health")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == "ok"
    assert "service" in data
    assert "version" in data
    assert "database" not in data


def test_database_health_not_configured():
    """Verify /api/v1/health/database returns 200 not_configured when URL is absent."""
    settings = Settings(SUPABASE_DB_URL=None)
    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.get("/api/v1/health/database")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data == {
        "status": "not_configured",
        "database": "not_configured",
    }


def test_database_health_connected_returns_200():
    """Verify /api/v1/health/database returns 200 connected when connectivity check succeeds."""
    mock_db_manager = MagicMock(spec=DatabaseManager)
    mock_db_manager.check_connection = AsyncMock(
        return_value=DatabaseCheckResult(status="ok", database="connected", latency_ms=12.5)
    )

    app = create_app()
    app.dependency_overrides[get_db_manager] = lambda: mock_db_manager
    client = TestClient(app)

    response = client.get("/api/v1/health/database")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "status": "ok",
        "database": "connected",
    }


def test_database_health_unavailable_returns_503():
    """Verify /api/v1/health/database returns 503 when connection fails."""
    mock_db_manager = MagicMock(spec=DatabaseManager)
    mock_db_manager.check_connection = AsyncMock(
        return_value=DatabaseCheckResult(status="error", database="unavailable", detail="Service down")
    )

    app = create_app()
    app.dependency_overrides[get_db_manager] = lambda: mock_db_manager
    client = TestClient(app)

    response = client.get("/api/v1/health/database")
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json() == {
        "status": "error",
        "database": "unavailable",
    }


def test_database_health_response_never_leaks_secrets():
    """Verify that error responses do not leak database passwords, hosts, or tokens."""
    sensitive_url = "postgresql://secret_user:super_secret_pw@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
    settings = Settings(SUPABASE_DB_URL=sensitive_url)
    app = create_app(settings=settings)

    mock_db_manager = MagicMock(spec=DatabaseManager)
    mock_db_manager.check_connection = AsyncMock(
        return_value=DatabaseCheckResult(status="error", database="unavailable", detail="Failed to connect")
    )
    app.dependency_overrides[get_db_manager] = lambda: mock_db_manager
    client = TestClient(app)

    response = client.get("/api/v1/health/database")
    body_text = response.text

    assert "super_secret_pw" not in body_text
    assert "secret_user" not in body_text
    assert "aws-0-us-east-1" not in body_text
    assert "pooler.supabase.com" not in body_text
    assert "Traceback" not in body_text
