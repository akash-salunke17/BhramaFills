"""Unit, transaction, idempotency, retrieval, and API endpoint tests for Evidence Persistence.

Step 9B.3 Test Suite covering:
- Group A: Schema and migration tests for add_evidence_claims_and_runs.sql
- Group B: EvidencePersistenceService unit tests (facts, claims, locations, runs)
- Group C: Transaction & rollback tests (atomic isolation, error recovery)
- Group D: Idempotency tests (idempotency key, re-extraction traceability)
- Group E: Evidence retrieval tests (source/project queries, filters, pagination)
- Group F: FastAPI route integration tests (POST persist, GET evidence, GET extraction-runs)
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, status
from fastapi.testclient import TestClient
import pytest

from app.core.auth import get_current_user
from app.core.ownership import OwnedProjectContext, get_owned_project
from app.core.config import Settings
from app.db.connection import (
    DatabaseManager,
    DatabaseNotConfiguredError,
    DatabaseUnavailableError,
)
from app.db.migrator import DatabaseMigrator
from app.services.ai.evidence_schemas import (
    BatchEvidenceExtractionResult,
    ClaimType,
    EvidenceExtractionResult,
    EvidenceLocation,
    EvidenceSourceType,
    ExtractionStatus,
    ExtractedFact,
    FactType,
    RepresentationType,
    SourceClaim,
)
from app.services.evidence import (
    DuplicateExtractionRunError,
    EvidencePersistenceError,
    EvidencePersistenceService,
    EvidenceTransactionError,
    ExtractionRunListResponse,
    ExtractionRunNotFoundError,
    ExtractionRunResponse,
    InvalidEvidencePayloadError,
    PersistEvidenceRequest,
    PersistedClaimResponse,
    PersistedEvidenceRunResponse,
    PersistedFactResponse,
    ProjectEvidenceResponse,
    SourceMismatchError,
    get_evidence_persistence_service,
)
from app.services.sources.exceptions import ProjectNotFoundError, SourceNotFoundError
from tests.conftest import TEST_USER_ID


# =============================================================================
# Fixtures & Sample Data
# =============================================================================

SAMPLE_PROJECT_ID = uuid4()
SAMPLE_SOURCE_ID = uuid4()
SAMPLE_RUN_ID = uuid4()
SAMPLE_FACT_DB_ID = uuid4()
SAMPLE_CLAIM_DB_ID = uuid4()

MOCK_PROJECT_ROW = {
    "id": SAMPLE_PROJECT_ID,
    "user_id": TEST_USER_ID,
    "title": "Climate Study",
    "status": "Draft",
    "research_question": "Ice loss rate?",
}

SAMPLE_FACT = ExtractedFact(
    fact_id="fact-001",
    statement="Antarctic ice sheet lost 252 billion metric tons of ice annually between 2009 and 2017.",
    fact_type=FactType.STATISTICAL,
    location=EvidenceLocation(
        source_id=str(SAMPLE_SOURCE_ID),
        source_type=EvidenceSourceType.WEB,
        start_char=0,
        end_char=92,
        url="https://example.com/antarctic-study",
        heading_path=["Introduction", "Ice Loss"],
        paragraph_index=0,
    ),
    evidence_text="Antarctic ice sheet lost 252 billion metric tons of ice annually between 2009 and 2017.",
    representation_type=RepresentationType.DIRECT_QUOTE,
    confidence=0.96,
    qualifiers=["between 2009 and 2017"],
    uncertainty_notes=None,
    extraction_warnings=[],
)

SAMPLE_CLAIM = SourceClaim(
    claim_id="claim-001",
    claim_text="Sea levels could rise by up to 1 meter by 2100 under high carbon emissions.",
    claim_type=ClaimType.PREDICTION,
    source_id=str(SAMPLE_SOURCE_ID),
    evidence_location=EvidenceLocation(
        source_id=str(SAMPLE_SOURCE_ID),
        source_type=EvidenceSourceType.WEB,
        start_char=93,
        end_char=192,
        url="https://example.com/antarctic-study",
        heading_path=["Projections"],
        paragraph_index=0,
    ),
    representation_type=RepresentationType.PARAPHRASE,
    confidence=0.88,
    qualifiers=["under high carbon emissions", "by 2100"],
    uncertainty_notes="Projected based on carbon models",
    extraction_warnings=[],
)

SAMPLE_EXTRACTION_RESULT = EvidenceExtractionResult(
    source_id=str(SAMPLE_SOURCE_ID),
    source_type=EvidenceSourceType.WEB,
    facts=[SAMPLE_FACT],
    claims=[SAMPLE_CLAIM],
    extraction_status=ExtractionStatus.SUCCESS,
    warnings=[],
    errors=[],
    source_truncated=False,
    source_character_count=2500,
    processed_character_count=2500,
    extracted_at=datetime.now(timezone.utc),
)


@pytest.fixture
def migrations_dir() -> Path:
    """Return workspace supabase migrations directory."""
    return Path(__file__).resolve().parents[2] / "supabase" / "migrations"


@pytest.fixture
def new_migration_file(migrations_dir: Path) -> Path:
    """Return the Step 9B.3 migration SQL file."""
    files = list(migrations_dir.glob("*_add_evidence_claims_and_runs.sql"))
    assert len(files) == 1, f"Expected 1 migration file, found: {files}"
    return files[0]


@pytest.fixture
def new_migration_sql(new_migration_file: Path) -> str:
    """Return raw SQL content of new migration."""
    return new_migration_file.read_text(encoding="utf-8")


def create_mock_db_manager() -> tuple[DatabaseManager, AsyncMock, MagicMock]:
    """Helper creating a mocked DatabaseManager with async connection and transaction."""
    mock_db = MagicMock(spec=DatabaseManager)
    mock_db.is_configured = True

    mock_conn = AsyncMock()
    mock_tx = AsyncMock()
    mock_tx.__aenter__.return_value = None
    mock_tx.__aexit__.return_value = None
    mock_conn.transaction = MagicMock(return_value=mock_tx)

    mock_acquire = AsyncMock()
    mock_acquire.__aenter__.return_value = mock_conn
    mock_acquire.__aexit__.return_value = None

    mock_db.acquire_connection.return_value = mock_acquire
    return mock_db, mock_conn, mock_tx


# =============================================================================
# Group A: Schema and Migration Tests
# =============================================================================

def test_new_migration_file_exists_and_naming_convention(new_migration_file: Path):
    """Verify migration file exists and adheres to timestamped naming conventions."""
    assert new_migration_file.exists()
    assert new_migration_file.name.endswith("_add_evidence_claims_and_runs.sql")
    version = new_migration_file.name.split("_")[0]
    assert version.isdigit()
    assert len(version) >= 14


def test_new_migration_sql_contains_no_destructive_statements(new_migration_sql: str):
    """Verify migration contains zero destructive statements (no DROP, TRUNCATE)."""
    sql_upper = new_migration_sql.upper()
    assert "DROP TABLE" not in sql_upper
    assert "DROP SCHEMA" not in sql_upper
    assert "TRUNCATE TABLE" not in sql_upper
    assert " TRUNCATE " not in sql_upper


def test_new_migration_creates_required_tables_and_columns(new_migration_sql: str):
    """Verify migration creates extraction_runs, source_claims, and alters evidence."""
    assert "CREATE TABLE IF NOT EXISTS public.extraction_runs" in new_migration_sql
    assert "CREATE TABLE IF NOT EXISTS public.source_claims" in new_migration_sql
    assert "ALTER TABLE public.evidence" in new_migration_sql
    assert "extraction_run_id UUID" in new_migration_sql
    assert "fact_type" in new_migration_sql
    assert "representation_type" in new_migration_sql


def test_new_migration_enforces_rls_and_indexes(new_migration_sql: str):
    """Verify migration enables Row Level Security and creates unique constraints."""
    assert "ALTER TABLE public.extraction_runs ENABLE ROW LEVEL SECURITY;" in new_migration_sql
    assert "ALTER TABLE public.source_claims ENABLE ROW LEVEL SECURITY;" in new_migration_sql
    assert "idx_evidence_run_fact_id_unique" in new_migration_sql
    assert "idx_source_claims_run_claim_id_unique" in new_migration_sql


def test_new_migration_checksum_deterministic(new_migration_sql: str):
    """Verify checksum calculation on migration content is deterministic."""
    c1 = DatabaseMigrator.compute_checksum(new_migration_sql)
    c2 = DatabaseMigrator.compute_checksum(new_migration_sql)
    assert c1 == c2
    assert len(c1) == 64


# =============================================================================
# Group B: EvidencePersistenceService Unit Tests
# =============================================================================

@pytest.mark.asyncio
async def test_persist_extraction_result_happy_path():
    """Verify persisting an extraction result inserts run, facts, and claims in a transaction."""
    mock_db, mock_conn, mock_tx = create_mock_db_manager()

    # Setup mock returns
    mock_conn.fetchrow.side_effect = [
        # 1. validate_project_exists
        MOCK_PROJECT_ROW,
        # 2. validate_source_exists
        {"id": SAMPLE_SOURCE_ID, "project_id": SAMPLE_PROJECT_ID, "title": "Study.pdf", "source_type": "web", "original_url": "https://example.com"},
        # 3. insert extraction_runs
        {"id": SAMPLE_RUN_ID, "created_at": datetime.now(timezone.utc)},
        # 4. insert fact
        {"id": SAMPLE_FACT_DB_ID, "created_at": datetime.now(timezone.utc)},
        # 5. insert claim
        {"id": SAMPLE_CLAIM_DB_ID, "created_at": datetime.now(timezone.utc)},
    ]

    service = EvidencePersistenceService(db_manager=mock_db)
    response = await service.persist_extraction_result(
        project_id=SAMPLE_PROJECT_ID,
        source_id=SAMPLE_SOURCE_ID,
        result=SAMPLE_EXTRACTION_RESULT,
        user_id=TEST_USER_ID,
    )

    assert isinstance(response.run.id, UUID)
    assert response.run.project_id == SAMPLE_PROJECT_ID
    assert response.run.source_id == SAMPLE_SOURCE_ID
    assert response.run.facts_count == 1
    assert response.run.claims_count == 1
    assert len(response.facts) == 1
    assert len(response.claims) == 1
    assert response.facts[0].extraction_run_id == response.run.id
    assert response.claims[0].extraction_run_id == response.run.id
    assert response.facts[0].fact_id == "fact-001"
    assert response.claims[0].claim_id == "claim-001"
    mock_tx.__aenter__.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_extraction_result_empty_content():
    """Verify empty extraction result persists run with zero facts/claims and NO_CONTENT status."""
    mock_db, mock_conn, mock_tx = create_mock_db_manager()

    empty_result = EvidenceExtractionResult(
        source_id=str(SAMPLE_SOURCE_ID),
        source_type=EvidenceSourceType.WEB,
        facts=[],
        claims=[],
        extraction_status=ExtractionStatus.NO_CONTENT,
        warnings=["Source document contains no extractable readable text."],
        errors=[],
    )

    mock_conn.fetchrow.side_effect = [
        MOCK_PROJECT_ROW,
        {"id": SAMPLE_SOURCE_ID, "project_id": SAMPLE_PROJECT_ID, "title": "Doc", "source_type": "web", "original_url": "https://example.com"},
        {"id": SAMPLE_RUN_ID, "created_at": datetime.now(timezone.utc)},
    ]

    service = EvidencePersistenceService(db_manager=mock_db)
    response = await service.persist_extraction_result(
        project_id=SAMPLE_PROJECT_ID,
        source_id=SAMPLE_SOURCE_ID,
        result=empty_result,
        user_id=TEST_USER_ID,
    )

    assert response.run.extraction_status == ExtractionStatus.NO_CONTENT
    assert response.run.facts_count == 0
    assert response.run.claims_count == 0
    assert len(response.facts) == 0
    assert len(response.claims) == 0


@pytest.mark.asyncio
async def test_persist_extraction_result_partial_status():
    """Verify partial extraction preserves truncation flag and character counts."""
    mock_db, mock_conn, mock_tx = create_mock_db_manager()

    partial_result = EvidenceExtractionResult(
        source_id=str(SAMPLE_SOURCE_ID),
        source_type=EvidenceSourceType.WEB,
        facts=[SAMPLE_FACT],
        claims=[],
        extraction_status=ExtractionStatus.PARTIAL,
        source_truncated=True,
        source_character_count=50000,
        processed_character_count=20000,
        warnings=["Source text was truncated."],
    )

    mock_conn.fetchrow.side_effect = [
        MOCK_PROJECT_ROW,
        {"id": SAMPLE_SOURCE_ID, "project_id": SAMPLE_PROJECT_ID, "title": "Doc", "source_type": "web", "original_url": "https://example.com"},
        {"id": SAMPLE_RUN_ID, "created_at": datetime.now(timezone.utc)},
        {"id": SAMPLE_FACT_DB_ID, "created_at": datetime.now(timezone.utc)},
    ]

    service = EvidencePersistenceService(db_manager=mock_db)
    response = await service.persist_extraction_result(
        project_id=SAMPLE_PROJECT_ID,
        source_id=SAMPLE_SOURCE_ID,
        result=partial_result,
        user_id=TEST_USER_ID,
    )

    assert response.run.extraction_status == ExtractionStatus.PARTIAL
    assert response.run.source_truncated is True
    assert response.run.source_character_count == 50000
    assert response.run.processed_character_count == 20000


@pytest.mark.asyncio
async def test_persist_source_mismatch_raises_source_mismatch_error():
    """Verify exception raised when source belongs to a different project."""
    mock_db, mock_conn, _ = create_mock_db_manager()

    other_project_id = uuid4()
    mock_conn.fetchrow.side_effect = [
        MOCK_PROJECT_ROW,
        # Source belongs to other_project_id!
        {"id": SAMPLE_SOURCE_ID, "project_id": other_project_id, "title": "Doc", "source_type": "web", "original_url": "https://example.com"},
    ]

    service = EvidencePersistenceService(db_manager=mock_db)
    with pytest.raises(SourceMismatchError, match="belongs to project"):
        await service.persist_extraction_result(
            project_id=SAMPLE_PROJECT_ID,
            source_id=SAMPLE_SOURCE_ID,
            result=SAMPLE_EXTRACTION_RESULT,
            user_id=TEST_USER_ID,
        )


@pytest.mark.asyncio
async def test_persist_source_not_found_raises_source_not_found_error():
    """Verify SourceNotFoundError raised when source does not exist."""
    mock_db, mock_conn, _ = create_mock_db_manager()

    mock_conn.fetchrow.side_effect = [
        MOCK_PROJECT_ROW,
        None,  # Source not found
    ]

    service = EvidencePersistenceService(db_manager=mock_db)
    with pytest.raises(SourceNotFoundError):
        await service.persist_extraction_result(
            project_id=SAMPLE_PROJECT_ID,
            source_id=SAMPLE_SOURCE_ID,
            result=SAMPLE_EXTRACTION_RESULT,
            user_id=TEST_USER_ID,
        )


@pytest.mark.asyncio
async def test_persist_project_not_found_raises_project_not_found_error():
    """Verify ProjectNotFoundError raised when project does not exist."""
    mock_db, mock_conn, _ = create_mock_db_manager()

    mock_conn.fetchrow.return_value = None  # Project not found

    service = EvidencePersistenceService(db_manager=mock_db)
    with pytest.raises(ProjectNotFoundError):
        await service.persist_extraction_result(
            project_id=SAMPLE_PROJECT_ID,
            source_id=SAMPLE_SOURCE_ID,
            result=SAMPLE_EXTRACTION_RESULT,
            user_id=TEST_USER_ID,
        )


@pytest.mark.asyncio
async def test_persist_source_id_payload_mismatch_raises_invalid_payload():
    """Verify InvalidEvidencePayloadError when source_id argument mismatches result.source_id."""
    mock_db, _, _ = create_mock_db_manager()
    service = EvidencePersistenceService(db_manager=mock_db)

    different_source_uuid = uuid4()
    with pytest.raises(InvalidEvidencePayloadError, match="does not match"):
        await service.persist_extraction_result(
            project_id=SAMPLE_PROJECT_ID,
            source_id=different_source_uuid,
            result=SAMPLE_EXTRACTION_RESULT,
            user_id=TEST_USER_ID,
        )


# =============================================================================
# Group C: Transaction & Rollback Tests
# =============================================================================

@pytest.mark.asyncio
async def test_transaction_rollback_on_fact_insertion_failure():
    """Verify database transaction rolls back if fact insertion raises exception."""
    mock_db, mock_conn, mock_tx = create_mock_db_manager()

    mock_conn.fetchrow.side_effect = [
        MOCK_PROJECT_ROW,
        {"id": SAMPLE_SOURCE_ID, "project_id": SAMPLE_PROJECT_ID, "title": "Doc", "source_type": "web", "original_url": "https://example.com"},
        {"id": SAMPLE_RUN_ID, "created_at": datetime.now(timezone.utc)},
        # Fact insertion fails with asyncpg exception
        RuntimeError("Fatal database write error during fact insertion"),
    ]

    service = EvidencePersistenceService(db_manager=mock_db)
    with pytest.raises(EvidenceTransactionError, match="Failed to persist fact"):
        await service.persist_extraction_result(
            project_id=SAMPLE_PROJECT_ID,
            source_id=SAMPLE_SOURCE_ID,
            result=SAMPLE_EXTRACTION_RESULT,
            user_id=TEST_USER_ID,
        )

    # Context manager __aexit__ was invoked (triggering rollback)
    mock_tx.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_transaction_rollback_on_claim_insertion_failure():
    """Verify database transaction rolls back if claim insertion raises exception."""
    mock_db, mock_conn, mock_tx = create_mock_db_manager()

    mock_conn.fetchrow.side_effect = [
        MOCK_PROJECT_ROW,
        {"id": SAMPLE_SOURCE_ID, "project_id": SAMPLE_PROJECT_ID, "title": "Doc", "source_type": "web", "original_url": "https://example.com"},
        {"id": SAMPLE_RUN_ID, "created_at": datetime.now(timezone.utc)},
        {"id": SAMPLE_FACT_DB_ID, "created_at": datetime.now(timezone.utc)},
        # Claim insertion fails
        RuntimeError("Unique constraint violation on claim"),
    ]

    service = EvidencePersistenceService(db_manager=mock_db)
    with pytest.raises(EvidenceTransactionError, match="Failed to persist claim"):
        await service.persist_extraction_result(
            project_id=SAMPLE_PROJECT_ID,
            source_id=SAMPLE_SOURCE_ID,
            result=SAMPLE_EXTRACTION_RESULT,
            user_id=TEST_USER_ID,
        )

    mock_tx.__aexit__.assert_awaited_once()


# =============================================================================
# Group D: Idempotency & Batch Isolation Tests
# =============================================================================

@pytest.mark.asyncio
async def test_idempotent_retry_returns_existing_run():
    """Verify submitting identical idempotency key returns existing run without re-inserting."""
    mock_db, mock_conn, mock_tx = create_mock_db_manager()

    idempotency_key = "idemp-test-run-12345"

    # Mock validate project and source
    mock_conn.fetchrow.side_effect = [
        MOCK_PROJECT_ROW,
        {"id": SAMPLE_SOURCE_ID, "project_id": SAMPLE_PROJECT_ID, "title": "Doc", "source_type": "web", "original_url": "https://example.com"},
        # Idempotency lookup finds existing run!
        {
            "id": SAMPLE_RUN_ID,
            "project_id": SAMPLE_PROJECT_ID,
            "source_id": SAMPLE_SOURCE_ID,
            "batch_id": None,
            "provider": "openrouter",
            "model_name": "nvidia/nemotron-3-ultra-550b-a55b:free",
            "extraction_status": "success",
            "source_truncated": False,
            "source_character_count": 2500,
            "processed_character_count": 2500,
            "facts_count": 1,
            "claims_count": 1,
            "warnings": "[]",
            "errors": "[]",
            "run_metadata": json.dumps({"idempotency_key": idempotency_key}),
            "extracted_at": datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc),
        },
    ]

    # Mock fetch for facts and claims
    mock_conn.fetch.side_effect = [
        [
            {
                "id": SAMPLE_FACT_DB_ID,
                "project_id": SAMPLE_PROJECT_ID,
                "source_id": SAMPLE_SOURCE_ID,
                "extraction_run_id": SAMPLE_RUN_ID,
                "fact_id": "fact-001",
                "claim": "Statement text",
                "fact_type": "statistical",
                "supporting_excerpt": "Excerpt text",
                "representation_type": "direct_quote",
                "confidence_score": 0.95,
                "location_reference": json.dumps({"source_id": str(SAMPLE_SOURCE_ID), "source_type": "web"}),
                "qualifiers": "[]",
                "uncertainty_notes": None,
                "extraction_warnings": "[]",
                "created_at": datetime.now(timezone.utc),
            }
        ],
        [],  # Claims
    ]

    service = EvidencePersistenceService(db_manager=mock_db)
    response = await service.persist_extraction_result(
        project_id=SAMPLE_PROJECT_ID,
        source_id=SAMPLE_SOURCE_ID,
        result=SAMPLE_EXTRACTION_RESULT,
        idempotency_key=idempotency_key,
        user_id=TEST_USER_ID,
    )

    assert response.run.id == SAMPLE_RUN_ID
    # Transaction for insertion was NOT entered because existing run was resolved
    mock_tx.__aenter__.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_persistence_per_source_failure_isolation():
    """Verify batch persistence isolates failures so failure on source B doesn't fail source A."""
    mock_db, mock_conn, _ = create_mock_db_manager()

    source_a_uuid = uuid4()
    source_b_uuid = uuid4()

    result_a = EvidenceExtractionResult(
        source_id=str(source_a_uuid),
        source_type=EvidenceSourceType.WEB,
        facts=[],
        claims=[],
        extraction_status=ExtractionStatus.SUCCESS,
    )
    result_b = EvidenceExtractionResult(
        source_id=str(source_b_uuid),
        source_type=EvidenceSourceType.WEB,
        facts=[],
        claims=[],
        extraction_status=ExtractionStatus.SUCCESS,
    )

    batch_input = BatchEvidenceExtractionResult(
        results=[result_a, result_b],
        total_sources=2,
        successful_sources=2,
    )

    # Source A succeeds; Source B raises SourceMismatchError
    mock_conn.fetchrow.side_effect = [
        # Source A validations
        MOCK_PROJECT_ROW,
        {"id": source_a_uuid, "project_id": SAMPLE_PROJECT_ID, "title": "A", "source_type": "web", "original_url": "https://a.com"},
        {"id": uuid4(), "created_at": datetime.now(timezone.utc)},  # run_id
        # Source B validations
        MOCK_PROJECT_ROW,
        {"id": source_b_uuid, "project_id": uuid4(), "title": "B", "source_type": "web", "original_url": "https://b.com"},  # Mismatch!
    ]

    service = EvidencePersistenceService(db_manager=mock_db)
    batch_res = await service.persist_batch_extraction_results(
        project_id=SAMPLE_PROJECT_ID,
        batch_result=batch_input,
        user_id=TEST_USER_ID,
    )

    assert batch_res.total_sources == 2
    assert batch_res.successful_runs == 1
    assert batch_res.failed_runs == 1
    assert len(batch_res.errors) == 1
    assert "belongs to project" in batch_res.errors[0]


# =============================================================================
# Group E: Evidence Retrieval Tests
# =============================================================================

@pytest.mark.asyncio
async def test_get_source_evidence_returns_paginated_facts_and_claims():
    """Verify get_source_evidence returns structured facts and claims with pagination metadata."""
    mock_db, mock_conn, _ = create_mock_db_manager()

    mock_conn.fetchrow.side_effect = [
        MOCK_PROJECT_ROW,
        {"id": SAMPLE_SOURCE_ID, "project_id": SAMPLE_PROJECT_ID, "title": "Doc", "source_type": "web", "original_url": "https://example.com"},
    ]
    # Counts
    mock_conn.fetchval.side_effect = [1, 1]

    # Fetch rows
    mock_conn.fetch.side_effect = [
        # Facts
        [
            {
                "id": SAMPLE_FACT_DB_ID,
                "project_id": SAMPLE_PROJECT_ID,
                "source_id": SAMPLE_SOURCE_ID,
                "extraction_run_id": SAMPLE_RUN_ID,
                "fact_id": "fact-001",
                "claim": "Statement text",
                "fact_type": "statistical",
                "supporting_excerpt": "Excerpt text",
                "representation_type": "direct_quote",
                "confidence_score": 0.95,
                "location_reference": json.dumps({"source_id": str(SAMPLE_SOURCE_ID), "source_type": "web"}),
                "qualifiers": "[]",
                "uncertainty_notes": None,
                "extraction_warnings": "[]",
                "created_at": datetime.now(timezone.utc),
            }
        ],
        # Claims
        [
            {
                "id": SAMPLE_CLAIM_DB_ID,
                "project_id": SAMPLE_PROJECT_ID,
                "source_id": SAMPLE_SOURCE_ID,
                "extraction_run_id": SAMPLE_RUN_ID,
                "claim_id": "claim-001",
                "claim_text": "Assertion text",
                "claim_type": "prediction",
                "representation_type": "paraphrase",
                "confidence_score": 0.88,
                "location_reference": json.dumps({"source_id": str(SAMPLE_SOURCE_ID), "source_type": "web"}),
                "qualifiers": "[]",
                "uncertainty_notes": None,
                "extraction_warnings": "[]",
                "created_at": datetime.now(timezone.utc),
            }
        ],
    ]

    service = EvidencePersistenceService(db_manager=mock_db)
    evidence = await service.get_source_evidence(
        project_id=SAMPLE_PROJECT_ID,
        source_id=SAMPLE_SOURCE_ID,
        user_id=TEST_USER_ID,
        limit=20,
        offset=0,
    )

    assert evidence.project_id == SAMPLE_PROJECT_ID
    assert evidence.source_id == SAMPLE_SOURCE_ID
    assert evidence.total_facts == 1
    assert evidence.total_claims == 1
    assert len(evidence.facts) == 1
    assert len(evidence.claims) == 1
    assert evidence.facts[0].fact_id == "fact-001"
    assert evidence.claims[0].claim_id == "claim-001"


@pytest.mark.asyncio
async def test_get_project_evidence_filters_by_item_type():
    """Verify get_project_evidence respects item_type='facts' and ignores claims."""
    mock_db, mock_conn, _ = create_mock_db_manager()

    mock_conn.fetchrow.return_value = MOCK_PROJECT_ROW
    mock_conn.fetchval.return_value = 1  # count facts
    mock_conn.fetch.return_value = [
        {
            "id": SAMPLE_FACT_DB_ID,
            "project_id": SAMPLE_PROJECT_ID,
            "source_id": SAMPLE_SOURCE_ID,
            "extraction_run_id": SAMPLE_RUN_ID,
            "fact_id": "fact-001",
            "claim": "Statement text",
            "fact_type": "statistical",
            "supporting_excerpt": "Excerpt text",
            "representation_type": "direct_quote",
            "confidence_score": 0.95,
            "location_reference": json.dumps({"source_id": str(SAMPLE_SOURCE_ID), "source_type": "web"}),
            "qualifiers": "[]",
            "uncertainty_notes": None,
            "extraction_warnings": "[]",
            "created_at": datetime.now(timezone.utc),
        }
    ]

    service = EvidencePersistenceService(db_manager=mock_db)
    evidence = await service.get_project_evidence(
        project_id=SAMPLE_PROJECT_ID,
        user_id=TEST_USER_ID,
        item_type="facts",
    )

    assert evidence.total_facts == 1
    assert evidence.total_claims == 0
    assert len(evidence.facts) == 1
    assert len(evidence.claims) == 0


@pytest.mark.asyncio
async def test_list_extraction_runs():
    """Verify list_extraction_runs returns ordered runs with counts."""
    mock_db, mock_conn, _ = create_mock_db_manager()

    mock_conn.fetchrow.return_value = MOCK_PROJECT_ROW
    mock_conn.fetchval.return_value = 1
    mock_conn.fetch.return_value = [
        {
            "id": SAMPLE_RUN_ID,
            "project_id": SAMPLE_PROJECT_ID,
            "source_id": SAMPLE_SOURCE_ID,
            "batch_id": None,
            "provider": "openrouter",
            "model_name": "nvidia/nemotron-3-ultra-550b-a55b:free",
            "extraction_status": "success",
            "source_truncated": False,
            "source_character_count": 2500,
            "processed_character_count": 2500,
            "facts_count": 1,
            "claims_count": 1,
            "warnings": "[]",
            "errors": "[]",
            "run_metadata": "{}",
            "extracted_at": datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc),
        }
    ]

    service = EvidencePersistenceService(db_manager=mock_db)
    runs = await service.list_extraction_runs(project_id=SAMPLE_PROJECT_ID, user_id=TEST_USER_ID)

    assert runs.total_runs == 1
    assert len(runs.runs) == 1
    assert runs.runs[0].id == SAMPLE_RUN_ID


@pytest.mark.asyncio
async def test_get_extraction_run_detail_not_found_raises():
    """Verify ExtractionRunNotFoundError raised when run does not exist."""
    mock_db, mock_conn, _ = create_mock_db_manager()

    mock_conn.fetchrow.side_effect = [
        MOCK_PROJECT_ROW,
        None,  # Run not found
    ]

    service = EvidencePersistenceService(db_manager=mock_db)
    with pytest.raises(ExtractionRunNotFoundError):
        await service.get_extraction_run_detail(
            project_id=SAMPLE_PROJECT_ID,
            run_id=SAMPLE_RUN_ID,
            user_id=TEST_USER_ID,
        )


# =============================================================================
# Group F: FastAPI Route Integration Tests
# =============================================================================

@pytest.fixture(autouse=True)
def override_project_ownership(app: FastAPI):
    """Allow domain service tests in this module to assume project ownership is validated."""
    app.dependency_overrides[get_owned_project] = (
        lambda project_id, current_user=Depends(get_current_user): OwnedProjectContext(
            id=project_id,
            user_id=current_user.id,
            title="Test Project",
        )
    )
    yield
    app.dependency_overrides.pop(get_owned_project, None)

def test_api_persist_evidence_success(app: FastAPI, client: TestClient):
    """Verify POST /api/v1/projects/{project_id}/sources/{source_id}/persist returns 201."""
    mock_persistence_service = MagicMock(spec=EvidencePersistenceService)
    mock_persistence_service.is_configured = True

    mock_run = ExtractionRunResponse(
        id=SAMPLE_RUN_ID,
        project_id=SAMPLE_PROJECT_ID,
        source_id=SAMPLE_SOURCE_ID,
        provider="openrouter",
        model_name="nvidia/nemotron-3-ultra-550b-a55b:free",
        extraction_status=ExtractionStatus.SUCCESS,
        source_truncated=False,
        source_character_count=2500,
        processed_character_count=2500,
        facts_count=1,
        claims_count=1,
        warnings=[],
        errors=[],
        run_metadata={},
        extracted_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )

    mock_persisted_response = PersistedEvidenceRunResponse(
        run=mock_run,
        facts=[],
        claims=[],
    )
    mock_persistence_service.persist_extraction_result = AsyncMock(return_value=mock_persisted_response)

    app.dependency_overrides[get_evidence_persistence_service] = lambda: mock_persistence_service

    try:
        resp = client.post(
            f"/api/v1/projects/{SAMPLE_PROJECT_ID}/sources/{SAMPLE_SOURCE_ID}/persist",
            json={"result": SAMPLE_EXTRACTION_RESULT.model_dump(mode="json")},
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["run"]["id"] == str(SAMPLE_RUN_ID)
    finally:
        app.dependency_overrides.pop(get_evidence_persistence_service, None)


def test_api_get_source_evidence_success(app: FastAPI, client: TestClient):
    """Verify GET /api/v1/projects/{project_id}/sources/{source_id}/evidence returns 200."""
    mock_persistence_service = MagicMock(spec=EvidencePersistenceService)
    mock_persistence_service.is_configured = True

    mock_evidence_response = ProjectEvidenceResponse(
        project_id=SAMPLE_PROJECT_ID,
        source_id=SAMPLE_SOURCE_ID,
        total_facts=0,
        total_claims=0,
        limit=50,
        offset=0,
        facts=[],
        claims=[],
    )
    mock_persistence_service.get_source_evidence = AsyncMock(return_value=mock_evidence_response)

    app.dependency_overrides[get_evidence_persistence_service] = lambda: mock_persistence_service

    try:
        resp = client.get(
            f"/api/v1/projects/{SAMPLE_PROJECT_ID}/sources/{SAMPLE_SOURCE_ID}/evidence?limit=10"
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["project_id"] == str(SAMPLE_PROJECT_ID)
        assert data["source_id"] == str(SAMPLE_SOURCE_ID)
    finally:
        app.dependency_overrides.pop(get_evidence_persistence_service, None)


def test_api_get_project_evidence_success(app: FastAPI, client: TestClient):
    """Verify GET /api/v1/projects/{project_id}/evidence returns 200."""
    mock_persistence_service = MagicMock(spec=EvidencePersistenceService)
    mock_persistence_service.is_configured = True

    mock_evidence_response = ProjectEvidenceResponse(
        project_id=SAMPLE_PROJECT_ID,
        total_facts=0,
        total_claims=0,
        limit=50,
        offset=0,
        facts=[],
        claims=[],
    )
    mock_persistence_service.get_project_evidence = AsyncMock(return_value=mock_evidence_response)

    app.dependency_overrides[get_evidence_persistence_service] = lambda: mock_persistence_service

    try:
        resp = client.get(f"/api/v1/projects/{SAMPLE_PROJECT_ID}/evidence")
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["project_id"] == str(SAMPLE_PROJECT_ID)
    finally:
        app.dependency_overrides.pop(get_evidence_persistence_service, None)


def test_api_list_extraction_runs_success(app: FastAPI, client: TestClient):
    """Verify GET /api/v1/projects/{project_id}/sources/{source_id}/extraction-runs returns 200."""
    mock_persistence_service = MagicMock(spec=EvidencePersistenceService)
    mock_persistence_service.is_configured = True

    mock_runs_response = ExtractionRunListResponse(
        total_runs=0,
        limit=20,
        offset=0,
        runs=[],
    )
    mock_persistence_service.list_extraction_runs = AsyncMock(return_value=mock_runs_response)

    app.dependency_overrides[get_evidence_persistence_service] = lambda: mock_persistence_service

    try:
        resp = client.get(
            f"/api/v1/projects/{SAMPLE_PROJECT_ID}/sources/{SAMPLE_SOURCE_ID}/extraction-runs"
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["total_runs"] == 0
    finally:
        app.dependency_overrides.pop(get_evidence_persistence_service, None)


def test_api_get_extraction_run_detail_not_found(app: FastAPI, client: TestClient):
    """Verify GET /api/v1/projects/{project_id}/extraction-runs/{run_id} returns 404 when missing."""
    mock_persistence_service = MagicMock(spec=EvidencePersistenceService)
    mock_persistence_service.is_configured = True
    mock_persistence_service.get_extraction_run_detail = AsyncMock(
        side_effect=ExtractionRunNotFoundError("Run not found.")
    )

    app.dependency_overrides[get_evidence_persistence_service] = lambda: mock_persistence_service

    try:
        resp = client.get(f"/api/v1/projects/{SAMPLE_PROJECT_ID}/extraction-runs/{SAMPLE_RUN_ID}")
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_evidence_persistence_service, None)


def test_api_persist_evidence_db_unavailable_returns_503(app: FastAPI, client: TestClient):
    """Verify 503 is returned when database service is unconfigured or unavailable."""
    mock_persistence_service = MagicMock(spec=EvidencePersistenceService)
    mock_persistence_service.is_configured = False

    app.dependency_overrides[get_evidence_persistence_service] = lambda: mock_persistence_service

    try:
        resp = client.post(
            f"/api/v1/projects/{SAMPLE_PROJECT_ID}/sources/{SAMPLE_SOURCE_ID}/persist",
            json={"result": SAMPLE_EXTRACTION_RESULT.model_dump(mode="json")},
        )
        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "unavailable" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_evidence_persistence_service, None)
