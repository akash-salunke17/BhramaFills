"""Unit and structure tests for Bharmafills database migrations and DatabaseMigrator."""

import hashlib
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.db.connection import DatabaseManager
from app.db.migrator import (
    EXPECTED_BHARMAFILLS_TABLES,
    DatabaseMigrator,
    MigrationRecord,
    SchemaVerificationResult,
)


@pytest.fixture
def migrations_dir() -> Path:
    """Return workspace supabase migrations directory."""
    return Path(__file__).resolve().parents[2] / "supabase" / "migrations"


@pytest.fixture
def initial_migration_file(migrations_dir: Path) -> Path:
    """Return the initial migration SQL file."""
    files = list(migrations_dir.glob("*_initial_bharmafills_schema.sql"))
    assert len(files) == 1, f"Expected 1 initial migration file, found: {files}"
    return files[0]


@pytest.fixture
def migration_sql(initial_migration_file: Path) -> str:
    """Return the raw SQL content of the initial migration."""
    return initial_migration_file.read_text(encoding="utf-8")


def test_migration_file_exists_and_named_correctly(initial_migration_file: Path):
    """Verify the migration file exists and adheres to timestamped naming conventions."""
    assert initial_migration_file.exists()
    assert initial_migration_file.name.endswith("_initial_bharmafills_schema.sql")
    # Verify timestamp prefix has at least 14 digits (YYYYMMDDHHMMSS)
    version = initial_migration_file.name.split("_")[0]
    assert version.isdigit()
    assert len(version) >= 14


def test_migration_sql_contains_no_destructive_statements(migration_sql: str):
    """Verify migration has zero destructive operations (no DROP, TRUNCATE, or cascade drops)."""
    sql_upper = migration_sql.upper()
    assert "DROP TABLE" not in sql_upper
    assert "DROP SCHEMA" not in sql_upper
    assert "TRUNCATE" not in sql_upper
    assert "CASCADE" not in sql_upper or "ON DELETE CASCADE" in sql_upper  # ON DELETE CASCADE on FK is allowed


def test_migration_sql_creates_all_expected_tables(migration_sql: str):
    """Verify all 10 required domain tables and the schema_migrations table are created."""
    for table_name in EXPECTED_BHARMAFILLS_TABLES:
        pattern = f"CREATE TABLE public.{table_name}"
        assert pattern in migration_sql, f"Missing table creation: {pattern}"

    assert "CREATE TABLE IF NOT EXISTS public.schema_migrations" in migration_sql


def test_migration_sql_enforces_uuid_and_timestamptz(migration_sql: str):
    """Verify primary keys default to gen_random_uuid() and timestamps use TIMESTAMPTZ."""
    assert "gen_random_uuid()" in migration_sql
    assert "TIMESTAMPTZ NOT NULL DEFAULT now()" in migration_sql


def test_migration_sql_enforces_domain_constraints(migration_sql: str):
    """Verify critical integrity check constraints are declared in the migration SQL."""
    # Status and category checks on research_projects
    assert "chk_research_projects_status" in migration_sql
    assert "chk_research_projects_category" in migration_sql
    assert "chk_research_projects_title_len" in migration_sql

    # Source integrity checks
    assert "chk_sources_source_type" in migration_sql
    assert "chk_sources_url_required" in migration_sql
    assert "chk_sources_pdf_required" in migration_sql

    # Confidence score numeric bounds (0.000 to 1.000)
    assert "chk_evidence_confidence_bounds" in migration_sql
    assert "confidence_score >= 0.000 AND confidence_score <= 1.000" in migration_sql

    # Information gaps & checklist constraints
    assert "chk_information_gaps_type" in migration_sql
    assert "chk_verification_checklist_mutual_target" in migration_sql


def test_migration_sql_enables_row_level_security_on_all_tables(migration_sql: str):
    """Verify Row Level Security (RLS) is explicitly enabled on all application tables."""
    for table_name in EXPECTED_BHARMAFILLS_TABLES:
        pattern = f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY;"
        assert pattern in migration_sql, f"Missing RLS activation: {pattern}"


def test_migration_checksum_deterministic(initial_migration_file: Path, migration_sql: str):
    """Verify compute_checksum generates reproducible SHA-256 hash."""
    expected_hash = hashlib.sha256(migration_sql.encode("utf-8")).hexdigest()
    actual_hash = DatabaseMigrator.compute_checksum(migration_sql)
    assert actual_hash == expected_hash
    assert len(actual_hash) == 64


def test_migrator_get_migration_files(migrations_dir: Path):
    """Verify get_migration_files discovers all SQL files in directory."""
    migrator = DatabaseMigrator(migrations_dir=migrations_dir)
    files = migrator.get_migration_files()
    assert len(files) >= 1
    assert any(f.name.endswith("_initial_bharmafills_schema.sql") for f in files)


@pytest.mark.asyncio
async def test_migrator_detects_drift_on_checksum_mismatch(migrations_dir: Path):
    """Verify DatabaseMigrator raises RuntimeError if applied checksum differs from disk."""
    mock_db = MagicMock(spec=DatabaseManager)
    mock_db.is_configured = True
    mock_db._pool = MagicMock()

    mock_conn = AsyncMock()
    # Mock applied migrations with a bogus checksum
    mock_conn.fetch.return_value = [
        {
            "version": "20261031123000",
            "name": "20261031123000_initial_bharmafills_schema.sql",
            "applied_at": "2026-10-31T12:30:00Z",
            "checksum": "tampered_checksum_00000000000000000000000000000000000000000000000000",
        }
    ]

    mock_acquire = AsyncMock()
    mock_acquire.__aenter__.return_value = mock_conn
    mock_acquire.__aexit__.return_value = None
    mock_db._pool.acquire.return_value = mock_acquire

    migrator = DatabaseMigrator(db_manager=mock_db, migrations_dir=migrations_dir)
    with pytest.raises(RuntimeError) as exc_info:
        await migrator.apply_all_pending()

    assert "Migration drift detected" in str(exc_info.value)


@pytest.mark.asyncio
async def test_migrator_apply_all_pending_skips_already_applied(migrations_dir: Path, initial_migration_file: Path, migration_sql: str):
    """Verify DatabaseMigrator safely skips already applied migrations with matching checksum."""
    mock_db = MagicMock(spec=DatabaseManager)
    mock_db.is_configured = True
    mock_db._pool = MagicMock()

    mock_conn = AsyncMock()
    mock_tx = AsyncMock()
    mock_tx.__aenter__.return_value = None
    mock_tx.__aexit__.return_value = None
    mock_conn.transaction.return_value = mock_tx

    applied_records = []
    for f in sorted(migrations_dir.glob("*.sql")):
        content = f.read_text(encoding="utf-8")
        applied_records.append({
            "version": f.name.split("_")[0],
            "name": f.name,
            "applied_at": "2026-10-31T12:30:00Z",
            "checksum": DatabaseMigrator.compute_checksum(content),
        })
    mock_conn.fetch.return_value = applied_records

    mock_acquire = AsyncMock()
    mock_acquire.__aenter__.return_value = mock_conn
    mock_acquire.__aexit__.return_value = None
    mock_db._pool.acquire.return_value = mock_acquire

    migrator = DatabaseMigrator(db_manager=mock_db, migrations_dir=migrations_dir)
    applied = await migrator.apply_all_pending()
    assert applied == []  # No pending migrations executed


@pytest.mark.asyncio
async def test_migrator_verify_schema_reports_integrity(migrations_dir: Path):
    """Verify DatabaseMigrator.verify_schema accurately checks tables, RLS, and constraints."""
    mock_db = MagicMock(spec=DatabaseManager)
    mock_db.is_configured = True
    mock_db._pool = MagicMock()

    mock_conn = AsyncMock()
    # Mock tables query: return all expected tables
    mock_conn.fetch.side_effect = [
        # 1. tables_rows
        [{"table_name": t} for t in EXPECTED_BHARMAFILLS_TABLES],
        # 2. rls_rows
        [{"table_name": t, "rls_enabled": True} for t in EXPECTED_BHARMAFILLS_TABLES],
        # 3. check_constraints
        [{"constraint_name": "chk_mock", "table_name": "research_projects"}],
    ]
    # Mock scalar fetchval returns
    mock_conn.fetchval.side_effect = [
        17,  # fk_count
        41,  # indexes_count
    ]

    mock_acquire = AsyncMock()
    mock_acquire.__aenter__.return_value = mock_conn
    mock_acquire.__aexit__.return_value = None
    mock_db._pool.acquire.return_value = mock_acquire

    migrator = DatabaseMigrator(db_manager=mock_db, migrations_dir=migrations_dir)
    res = await migrator.verify_schema()
    assert res.is_valid is True
    assert res.missing_tables == []
    assert res.tables_missing_rls == []
    assert res.foreign_keys_count == 17
    assert res.indexes_count == 41

