"""Tests for the API health check probe endpoint."""

import pytest
from httpx import AsyncClient
from starlette.testclient import TestClient

from app.core.config import Settings


def test_health_endpoint_sync_returns_200(client: TestClient, test_settings: Settings) -> None:
    """Verify synchronous client receives HTTP 200 and truthful status from /api/v1/health."""
    response = client.get(f"{test_settings.API_V1_PREFIX}/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == test_settings.PROJECT_NAME
    assert data["version"] == test_settings.VERSION


@pytest.mark.asyncio
async def test_health_endpoint_async_returns_200(async_client: AsyncClient, test_settings: Settings) -> None:
    """Verify asynchronous HTTPX client receives HTTP 200 and expected payload."""
    response = await async_client.get(f"{test_settings.API_V1_PREFIX}/health")
    assert response.status_code == 200

    data = response.json()
    assert set(data.keys()) == {"status", "service", "version"}
    assert data["status"] == "ok"


def test_health_endpoint_does_not_expose_secrets_or_env(client: TestClient, test_settings: Settings) -> None:
    """Verify health response never leaks environment keys, file paths, or credentials."""
    response = client.get(f"{test_settings.API_V1_PREFIX}/health")
    data = response.json()

    # Ensure no internal secret keys are present in payload
    forbidden_keys = {"env", "environment", "key", "secret", "token", "password", "database", "supabase", "gemini"}
    for key in data.keys():
        assert key.lower() not in forbidden_keys

    # Check payload values do not contain leaked secrets
    payload_str = response.text.lower()
    assert "key" not in payload_str
    assert "password" not in payload_str
    assert "token" not in payload_str


def test_health_endpoint_unprefixed_path_returns_404(client: TestClient) -> None:
    """Verify /health is not exposed at root; it must be under the configured API prefix."""
    response = client.get("/health")
    assert response.status_code == 404
