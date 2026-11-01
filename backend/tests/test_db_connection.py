"""Unit tests for DatabaseManager connection lifecycle and probe operations."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.core.config import Settings
from app.db.connection import DatabaseCheckResult, DatabaseManager


@pytest.mark.asyncio
async def test_manager_not_configured():
    """Verify manager returns not_configured result when URL is missing."""
    settings = Settings(SUPABASE_DB_URL=None)
    manager = DatabaseManager(settings=settings)

    assert manager.is_configured is False
    result = await manager.check_connection()

    assert isinstance(result, DatabaseCheckResult)
    assert result.status == "not_configured"
    assert result.database == "not_configured"
    assert result.latency_ms is None


@pytest.mark.asyncio
async def test_manager_initialize_noop_when_not_configured():
    """Verify initialize does not create a pool when database is not configured."""
    settings = Settings(SUPABASE_DB_URL=None)
    manager = DatabaseManager(settings=settings)

    await manager.initialize()
    assert manager._pool is None


@pytest.mark.asyncio
async def test_manager_successful_connection_probe():
    """Verify check_connection returns status=ok when SELECT 1 probe succeeds."""
    settings = Settings(SUPABASE_DB_URL="postgresql://user:pass@pooler:5432/postgres")
    manager = DatabaseManager(settings=settings)

    mock_conn = AsyncMock()
    mock_conn.fetchval.return_value = 1

    mock_acquire_context = AsyncMock()
    mock_acquire_context.__aenter__.return_value = mock_conn
    mock_acquire_context.__aexit__.return_value = None

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire_context

    with patch("asyncpg.create_pool", AsyncMock(return_value=mock_pool)) as mock_create_pool:
        result = await manager.check_connection()

        assert result.status == "ok"
        assert result.database == "connected"
        assert result.latency_ms is not None
        assert result.latency_ms >= 0
        mock_create_pool.assert_called_once()
        mock_conn.fetchval.assert_called_once_with("SELECT 1;")


@pytest.mark.asyncio
async def test_manager_pool_creation_failure():
    """Verify manager gracefully reports unavailable when pool creation raises."""
    settings = Settings(SUPABASE_DB_URL="postgresql://user:pass@pooler:5432/postgres")
    manager = DatabaseManager(settings=settings)

    with patch("asyncpg.create_pool", AsyncMock(side_effect=Exception("Simulated connection failure"))):
        result = await manager.check_connection()

        assert result.status == "error"
        assert result.database == "unavailable"
        assert "Simulated connection failure" not in (result.detail or "")


@pytest.mark.asyncio
async def test_manager_connection_timeout():
    """Verify timeout during connection acquisition returns unavailable with timeout detail."""
    settings = Settings(
        SUPABASE_DB_URL="postgresql://user:pass@pooler:5432/postgres",
        DATABASE_CONNECT_TIMEOUT_SECONDS=1.0,
    )
    manager = DatabaseManager(settings=settings)

    mock_pool = MagicMock()
    mock_acquire = AsyncMock()
    mock_acquire.__aenter__.side_effect = asyncio.TimeoutError()
    mock_pool.acquire.return_value = mock_acquire

    manager._pool = mock_pool

    result = await manager.check_connection()
    assert result.status == "error"
    assert result.database == "unavailable"
    assert "timed out" in (result.detail or "")


@pytest.mark.asyncio
async def test_manager_unexpected_query_result():
    """Verify check_connection reports error if probe does not return 1."""
    settings = Settings(SUPABASE_DB_URL="postgresql://user:pass@pooler:5432/postgres")
    manager = DatabaseManager(settings=settings)

    mock_conn = AsyncMock()
    mock_conn.fetchval.return_value = 0  # Unexpected probe response

    mock_acquire = AsyncMock()
    mock_acquire.__aenter__.return_value = mock_conn
    mock_acquire.__aexit__.return_value = None

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire
    manager._pool = mock_pool

    result = await manager.check_connection()
    assert result.status == "error"
    assert result.database == "unavailable"
    assert "unexpected result" in (result.detail or "")


@pytest.mark.asyncio
async def test_manager_close_safely_drains_pool():
    """Verify close safely calls pool.close and sets pool reference to None."""
    settings = Settings(SUPABASE_DB_URL="postgresql://user:pass@pooler:5432/postgres")
    manager = DatabaseManager(settings=settings)

    mock_pool = AsyncMock()
    manager._pool = mock_pool

    await manager.close()
    mock_pool.close.assert_called_once()
    assert manager._pool is None

