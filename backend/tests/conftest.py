"""Pytest fixtures for Bharmafills backend test suite."""

import pytest
from collections.abc import AsyncGenerator, Generator
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def test_settings() -> Settings:
    """Provide isolated test settings."""
    return Settings(
        ENVIRONMENT="test",
        PROJECT_NAME="Bharmafills API (Test)",
        VERSION="0.1.0-test",
        API_V1_PREFIX="/api/v1",
        CORS_ORIGINS=["http://localhost:5173", "http://127.0.0.1:5173", "http://testserver"],
    )


@pytest.fixture
def app(test_settings: Settings) -> FastAPI:
    """Create a fresh FastAPI application instance for each test."""
    return create_app(settings=test_settings)


@pytest.fixture
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    """Synchronous test client for rapid HTTP testing."""
    with TestClient(app, base_url="http://testserver") as test_client:
        yield test_client


@pytest.fixture
async def async_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Asynchronous test client using HTTPX for ASGI testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
