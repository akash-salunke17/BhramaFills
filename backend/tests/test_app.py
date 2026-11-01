"""Tests for FastAPI application creation, metadata, and OpenAPI generation."""

from starlette.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_app_metadata(test_settings: Settings) -> None:
    """Verify application initializes with configured metadata."""
    test_app = create_app(settings=test_settings)
    assert test_app.title == test_settings.PROJECT_NAME
    assert test_app.version == test_settings.VERSION
    assert test_app.description == test_settings.DESCRIPTION


def test_openapi_schema_generation(client: TestClient, test_settings: Settings) -> None:
    """Verify OpenAPI JSON schema is generated and documents the health endpoint."""
    response = client.get(test_settings.OPENAPI_URL or "/openapi.json")
    assert response.status_code == 200

    schema = response.json()
    assert "openapi" in schema
    assert schema["info"]["title"] == test_settings.PROJECT_NAME
    assert schema["info"]["version"] == test_settings.VERSION

    # Verify health endpoint is documented
    health_path = f"{test_settings.API_V1_PREFIX}/health"
    assert health_path in schema["paths"]
    assert "get" in schema["paths"][health_path]


def test_swagger_ui_available_in_non_production(client: TestClient, test_settings: Settings) -> None:
    """Verify Swagger UI docs endpoint responds in development/test."""
    docs_url = test_settings.DOCS_URL or "/docs"
    response = client.get(docs_url)
    assert response.status_code == 200
    assert "swagger" in response.text.lower() or "html" in response.text.lower()


def test_docs_disabled_in_production() -> None:
    """Verify OpenAPI docs and Swagger UI are disabled when ENVIRONMENT=production."""
    prod_settings = Settings(
        ENVIRONMENT="production",
        PROJECT_NAME="Bharmafills API (Prod)",
        VERSION="0.1.0",
        SUPABASE_DB_URL=None,
        OPENROUTER_API_KEY=None,
        _env_file=None,
    )
    prod_app = create_app(settings=prod_settings)
    with TestClient(prod_app) as prod_client:
        # Docs should return 404 in production
        assert prod_client.get("/docs").status_code == 404
        assert prod_client.get("/openapi.json").status_code == 404
