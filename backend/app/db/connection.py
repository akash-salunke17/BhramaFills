"""Database connection and lifecycle manager for Supabase PostgreSQL."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache
import logging
import time
from typing import Literal

import asyncpg

from app.core.config import Settings, get_settings

logger = logging.getLogger("bharmafills.db")


class DatabaseError(Exception):
    """Base exception for all database-related operations."""


class DatabaseNotConfiguredError(DatabaseError):
    """Raised when an operation requires a database connection but none is configured."""


class DatabaseUnavailableError(DatabaseError):
    """Raised when the database connection pool is unavailable or times out."""


@dataclass(frozen=True)
class DatabaseCheckResult:
    """Sanitized result of a database connectivity verification."""

    status: Literal["ok", "not_configured", "error"]
    database: Literal["connected", "not_configured", "unavailable"]
    latency_ms: float | None = None
    detail: str | None = None


class DatabaseManager:
    """Manages PostgreSQL connection lifecycle, connection pooling, and health checks."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()

    @property
    def is_configured(self) -> bool:
        """Return True if a non-empty database URL is configured."""
        return self._settings.is_database_configured

    async def initialize(self) -> None:
        """Initialize the connection pool if the database is configured.

        Configured specifically for Supabase Session Pooler:
        - statement_cache_size=0 ensures compatibility with PgBouncer.
        - Timeout bound by DATABASE_CONNECT_TIMEOUT_SECONDS.
        - Fails gracefully without leaking credentials in exceptions.
        """
        if not self.is_configured:
            logger.info("Database URL is not configured. Database layer remains inactive.")
            return

        if self._pool is not None:
            return

        async with self._lock:
            if self._pool is not None:
                return

            try:
                self._pool = await asyncpg.create_pool(
                    dsn=self._settings.SUPABASE_DB_URL,
                    min_size=1,
                    max_size=5,
                    timeout=self._settings.DATABASE_CONNECT_TIMEOUT_SECONDS,
                    command_timeout=self._settings.DATABASE_CONNECT_TIMEOUT_SECONDS,
                    statement_cache_size=0,
                )
                logger.info("Database connection pool successfully initialized.")
            except Exception as exc:
                # Log exception class name without DSN or credentials
                logger.error("Failed to initialize database connection pool: %s", type(exc).__name__)
                # Do not raise; pool remains None so check_connection reports unavailable

    async def close(self) -> None:
        """Safely close and drain all database connections."""
        async with self._lock:
            if self._pool is not None:
                try:
                    await self._pool.close()
                    logger.info("Database connection pool closed.")
                except Exception as exc:
                    logger.warning("Error closing database connection pool: %s", type(exc).__name__)
                finally:
                    self._pool = None

    @asynccontextmanager
    async def acquire_connection(self):
        """Acquire a managed database connection from the connection pool.

        Yields:
            asyncpg.Connection: An active database connection from the pool.

        Raises:
            DatabaseNotConfiguredError: If SUPABASE_DB_URL is not configured.
            DatabaseUnavailableError: If pool cannot be initialized or connection fails.
        """
        if not self.is_configured:
            raise DatabaseNotConfiguredError("Database connection is not configured.")

        if self._pool is None:
            await self.initialize()

        if self._pool is None:
            raise DatabaseUnavailableError("Database connection pool could not be initialized.")

        try:
            async with self._pool.acquire(timeout=self._settings.DATABASE_CONNECT_TIMEOUT_SECONDS) as conn:
                yield conn
        except (asyncio.TimeoutError, asyncpg.PostgresError) as exc:
            logger.warning("Database connection error: %s", type(exc).__name__)
            raise DatabaseUnavailableError(f"Database operation failed: {type(exc).__name__}") from exc

    async def check_connection(self) -> DatabaseCheckResult:
        """Perform a minimal, truthful connectivity check using SELECT 1.

        Guarantees:
        - Never exposes credentials, hosts, or tracebacks in the return value.
        - Enforces connection timeouts.
        - Returns not_configured when SUPABASE_DB_URL is absent.
        """
        if not self.is_configured:
            return DatabaseCheckResult(
                status="not_configured",
                database="not_configured",
                detail="Database connection is not configured.",
            )

        start_time = time.perf_counter()
        try:
            # If pool is not yet created, attempt lazy initialization
            if self._pool is None:
                await self.initialize()

            if self._pool is None:
                return DatabaseCheckResult(
                    status="error",
                    database="unavailable",
                    detail="Database connection pool could not be initialized.",
                )

            # Acquire connection with timeout and execute probe query
            async with self._pool.acquire(timeout=self._settings.DATABASE_CONNECT_TIMEOUT_SECONDS) as conn:
                val = await conn.fetchval("SELECT 1;")
                if val != 1:
                    return DatabaseCheckResult(
                        status="error",
                        database="unavailable",
                        detail="Database query returned unexpected result.",
                    )

            latency = round((time.perf_counter() - start_time) * 1000, 2)
            return DatabaseCheckResult(
                status="ok",
                database="connected",
                latency_ms=latency,
            )
        except asyncio.TimeoutError:
            logger.warning("Database connectivity check timed out.")
            return DatabaseCheckResult(
                status="error",
                database="unavailable",
                detail="Database connection timed out.",
            )
        except Exception as exc:
            logger.warning("Database connectivity check failed: %s", type(exc).__name__)
            return DatabaseCheckResult(
                status="error",
                database="unavailable",
                detail="Database connection failed or service unavailable.",
            )


@lru_cache
def get_db_manager() -> DatabaseManager:
    """Return a cached singleton instance of DatabaseManager."""
    return DatabaseManager()

