"""Database migration runner and schema verification engine for Bharmafills."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
from typing import Any

import asyncpg

from app.core.config import Settings, get_settings
from app.db.connection import DatabaseManager, get_db_manager

logger = logging.getLogger("bharmafills.db.migrator")

# Expected tables created by the initial Bharmafills schema
EXPECTED_BHARMAFILLS_TABLES = [
    "research_projects",
    "sources",
    "extracted_content",
    "topics",
    "evidence",
    "evidence_topics",
    "information_gaps",
    "conflicts",
    "conflict_evidence",
    "verification_checklist",
]


@dataclass(frozen=True)
class MigrationRecord:
    """Record of an applied database migration."""

    version: str
    name: str
    applied_at: datetime
    checksum: str


@dataclass(frozen=True)
class SchemaVerificationResult:
    """Result of schema verification against expected specifications."""

    is_valid: boolean if False else bool
    tables_found: list[str]
    missing_tables: list[str]
    rls_enabled_tables: list[str]
    tables_missing_rls: list[str]
    foreign_keys_count: int
    indexes_count: int
    details: dict[str, Any]


class DatabaseMigrator:
    """Manages transactional migration application and schema integrity verification."""

    def __init__(
        self,
        db_manager: DatabaseManager | None = None,
        migrations_dir: Path | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._db_manager = db_manager or get_db_manager()
        if migrations_dir is not None:
            self._migrations_dir = migrations_dir
        else:
            # Default to <workspace_root>/supabase/migrations
            self._migrations_dir = Path(__file__).resolve().parents[3] / "supabase" / "migrations"

    @property
    def migrations_dir(self) -> Path:
        """Return the active migrations directory."""
        return self._migrations_dir

    def get_migration_files(self) -> list[Path]:
        """Return chronologically sorted list of .sql migration files on disk."""
        if not self._migrations_dir.exists():
            return []
        return sorted([f for f in self._migrations_dir.glob("*.sql") if f.is_file()])

    @staticmethod
    def compute_checksum(content: str) -> str:
        """Compute standard SHA-256 checksum of SQL content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    async def ensure_migrations_table(self, conn: asyncpg.Connection) -> None:
        """Create public.schema_migrations if it does not already exist."""
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS public.schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                checksum VARCHAR(64) NOT NULL
            );
        """)

    async def get_applied_migrations(self, conn: asyncpg.Connection) -> list[MigrationRecord]:
        """Fetch all applied migration records ordered chronologically."""
        await self.ensure_migrations_table(conn)
        rows = await conn.fetch("""
            SELECT version, name, applied_at, checksum
            FROM public.schema_migrations
            ORDER BY version ASC;
        """)
        return [
            MigrationRecord(
                version=row["version"],
                name=row["name"],
                applied_at=row["applied_at"],
                checksum=row["checksum"],
            )
            for row in rows
        ]

    async def apply_all_pending(self) -> list[str]:
        """Apply all pending migrations within individual transactions.

        Returns list of applied migration filenames.
        Raises RuntimeError on drift or execution failure.
        """
        if not self._db_manager.is_configured:
            raise RuntimeError("Database connection is not configured.")

        # Ensure pool is initialized
        if self._db_manager._pool is None:
            await self._db_manager.initialize()

        if self._db_manager._pool is None:
            raise RuntimeError("Could not connect to database pool.")

        applied_names: list[str] = []
        files = self.get_migration_files()
        if not files:
            logger.info("No migration files found in %s", self._migrations_dir)
            return []

        async with self._db_manager._pool.acquire() as conn:
            applied = await self.get_applied_migrations(conn)
            applied_map = {m.version: m for m in applied}

            for file_path in files:
                filename = file_path.name
                # Parse version prefix (e.g. 20261031123000_...)
                version = filename.split("_")[0]
                sql_content = file_path.read_text(encoding="utf-8")
                checksum = self.compute_checksum(sql_content)

                if version in applied_map:
                    # Check checksum to detect tampering
                    if applied_map[version].checksum != checksum:
                        raise RuntimeError(
                            f"Migration drift detected in {filename}. "
                            f"Recorded checksum: {applied_map[version].checksum}, current: {checksum}"
                        )
                    continue

                logger.info("Applying migration: %s (version: %s)", filename, version)
                # Execute in an isolated transaction
                async with conn.transaction():
                    await conn.execute(sql_content)
                    await conn.execute(
                        """
                        INSERT INTO public.schema_migrations (version, name, checksum, applied_at)
                        VALUES ($1, $2, $3, now());
                        """,
                        version,
                        filename,
                        checksum,
                    )
                applied_names.append(filename)
                logger.info("Successfully applied migration: %s", filename)

        return applied_names

    async def verify_schema(self) -> SchemaVerificationResult:
        """Inspect actual database schema and verify existence of tables, foreign keys, and RLS."""
        if not self._db_manager.is_configured:
            raise RuntimeError("Database connection is not configured.")

        if self._db_manager._pool is None:
            await self._db_manager.initialize()

        if self._db_manager._pool is None:
            raise RuntimeError("Could not connect to database pool.")

        async with self._db_manager._pool.acquire() as conn:
            # 1. Existing public tables
            tables_rows = await conn.fetch("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name;
            """)
            found_tables = [r["table_name"] for r in tables_rows]
            missing_tables = [t for t in EXPECTED_BHARMAFILLS_TABLES if t not in found_tables]

            # 2. RLS status for each table
            rls_rows = await conn.fetch("""
                SELECT relname as table_name, relrowsecurity as rls_enabled
                FROM pg_class
                JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace
                WHERE pg_namespace.nspname = 'public' AND relkind = 'r';
            """)
            rls_map = {r["table_name"]: r["rls_enabled"] for r in rls_rows}
            rls_enabled_tables = [t for t in EXPECTED_BHARMAFILLS_TABLES if rls_map.get(t, False)]
            tables_missing_rls = [t for t in EXPECTED_BHARMAFILLS_TABLES if not rls_map.get(t, False)]

            # 3. Foreign key constraints count
            fk_count = await conn.fetchval("""
                SELECT count(*)
                FROM information_schema.table_constraints
                WHERE table_schema = 'public' AND constraint_type = 'FOREIGN KEY';
            """)

            # 4. Indexes count on public schema
            indexes_count = await conn.fetchval("""
                SELECT count(*)
                FROM pg_indexes
                WHERE schemaname = 'public';
            """)

            # 5. Check constraints
            check_constraints = await conn.fetch("""
                SELECT constraint_name, table_name
                FROM information_schema.table_constraints
                WHERE table_schema = 'public' AND constraint_type = 'CHECK'
                ORDER BY table_name, constraint_name;
            """)

            is_valid = len(missing_tables) == 0 and len(tables_missing_rls) == 0

            return SchemaVerificationResult(
                is_valid=is_valid,
                tables_found=found_tables,
                missing_tables=missing_tables,
                rls_enabled_tables=rls_enabled_tables,
                tables_missing_rls=tables_missing_rls,
                foreign_keys_count=int(fk_count or 0),
                indexes_count=int(indexes_count or 0),
                details={
                    "check_constraints_count": len(check_constraints),
                    "check_constraints": [dict(c) for c in check_constraints],
                },
            )


def get_migrator() -> DatabaseMigrator:
    """Return a singleton instance of DatabaseMigrator."""
    return DatabaseMigrator()

