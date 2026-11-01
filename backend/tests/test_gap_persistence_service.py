"""Unit and integration tests for GapPersistenceService (Step 10D.1).

Verifies all mandatory requirements:
- Ownership & Security:
  * Strict caller ownership enforcement via verify_project_ownership.
  * Rejection of None, string, or invalid user_id / project_id with TypeError.
  * Generic HTTP 404 masking (ProjectNotFoundError) for foreign, missing, unowned, or deleted projects.
  * Prohibition of foreign gap retrieval or review updates.
  * Zero database mutations prior to ownership verification.
- Persistence & Database Mapping:
  * Proper mapping of ValidatedGapFinding to public.information_gaps columns.
  * Preservation of gap_subtype, validation_verdict, grounding_notes, and warnings in confidence_metadata.
  * Verified topic name mapping; unmapped topics produce topic_id = NULL.
  * Sanitization of covered_evidence_ids strictly against verified project evidence.
  * Explicit labeling of AI confidence; zero claim of external empirical verification.
- Idempotency & Reruns:
  * Deterministic SHA-256 fingerprint generation.
  * Prevention of duplicate rows on repeated detection runs.
  * Preservation of persistent database UUID and creation timestamps.
  * Preservation of user review decisions (investigating, resolved, dismissed).
  * Preservation of user review notes across reruns.
  * Preservation of unknown pre-existing JSONB keys.
  * Gaps omitted from subsequent reruns remain intact and are not automatically deleted.
  * Project-scoped advisory transaction lock serialization.
- Review Updates:
  * Updating lifecycle status to investigating, resolved, dismissed.
  * Rejection of rollback to open or arbitrary status strings.
  * Length limits and sanitization on user notes.
  * Preservation of detection metadata and project identity.
- Retrieval & Transaction Safety:
  * Scoped listing with deterministic priority/creation ordering.
  * Filtering by status, priority, and gap_type.
  * Atomic transactional execution with rollback on database failure.
  * Graceful handling of empty detection envelopes.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import asyncpg
from pydantic import ValidationError
import pytest

from app.core.ownership import (
    OwnedProjectContext,
    ProjectAccessDeniedError,
    ProjectNotFoundError,
    ResourceMismatchError,
    verify_gap_belongs_to_project,
)
from app.db.connection import DatabaseManager
from app.services.ai.gap_persistence_service import (
    GapNotFoundError,
    GapPersistenceError,
    GapPersistenceService,
    GapTransactionError,
    compute_gap_fingerprint,
)
from app.services.ai.gap_schemas import (
    AIGapCandidatePayload,
    GapDetectionResult,
    GapPriority,
    GapReviewStatus,
    GapReviewUpdate,
    GapStatus,
    GapSubtype,
    GapType,
    InformationGapResponse,
    PersistedGapBatchResponse,
    ValidatedGapFinding,
    ValidationVerdict,
)

# Deterministic Test UUIDs
USER_A_ID = UUID("00000000-0000-4000-a000-000000000001")
USER_B_ID = UUID("00000000-0000-4000-b000-000000000002")
PROJECT_A_ID = UUID("11111111-1111-4000-a000-000000000001")
PROJECT_B_ID = UUID("11111111-1111-4000-b000-000000000002")
TOPIC_1_ID = UUID("33333333-3333-4000-a000-000000000001")
TOPIC_2_ID = UUID("33333333-3333-4000-a000-000000000002")
FACT_1_ID = UUID("44444444-4444-4000-a000-000000000001")
FACT_2_ID = UUID("44444444-4444-4000-a000-000000000002")
FOREIGN_FACT_ID = UUID("44444444-4444-4000-b000-000000000099")
GAP_1_ID = UUID("66666666-6666-4000-a000-000000000001")
GAP_2_ID = UUID("66666666-6666-4000-a000-000000000002")


# =============================================================================
# Test Helpers & Fixtures
# =============================================================================

class MockAsyncTransaction:
    """Async context manager simulating asyncpg transaction."""

    async def __aenter__(self) -> MockAsyncTransaction:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


class MockConnectionContext:
    """Async context manager mocking database connection acquisition."""

    def __init__(self, conn: AsyncMock) -> None:
        self.conn = conn

    async def __aenter__(self) -> AsyncMock:
        return self.conn

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


@pytest.fixture
def mock_conn() -> AsyncMock:
    conn = AsyncMock()
    conn.transaction = MagicMock(return_value=MockAsyncTransaction())
    return conn


@pytest.fixture
def mock_db_manager(mock_conn: AsyncMock) -> MagicMock:
    mgr = MagicMock(spec=DatabaseManager)
    mgr.is_configured = True
    mgr.acquire_connection.return_value = MockConnectionContext(mock_conn)
    return mgr


def make_validated_finding(
    candidate_id: int = 1,
    target_subquestion: str = "What are the non-resident eligibility rules?",
    gap_description: str = "The sources omit residency criteria for applicants.",
    explanation: str = "Residency criteria are required for participation scope.",
    gap_type: GapType = GapType.INSUFFICIENT_EVIDENCE,
    gap_subtype: GapSubtype = GapSubtype.INCOMPLETE_DETAIL,
    priority: GapPriority = GapPriority.HIGH,
    suggested_query: str | None = "non-resident eligibility solar",
    related_topic_name: str | None = "Eligibility",
    confidence_score: float = 0.88,
    reasoning: str = "Missing explicit residency guidelines.",
    validation_verdict: ValidationVerdict = "partially_covered",
    grounded_facts_count: int = 1,
    covered_evidence_ids: list[UUID] | None = None,
    corpus_truncation_warning: bool = False,
    grounding_notes: str = "Partially covered by 1 source statement.",
    source_omission_warning: str | None = None,
) -> ValidatedGapFinding:
    """Helper to construct a valid ValidatedGapFinding for testing."""
    cand = AIGapCandidatePayload(
        candidate_id=candidate_id,
        target_subquestion=target_subquestion,
        gap_description=gap_description,
        explanation=explanation,
        gap_type=gap_type,
        gap_subtype=gap_subtype,
        priority=priority,
        suggested_query=suggested_query,
        related_topic_name=related_topic_name,
        confidence_score=confidence_score,
        reasoning=reasoning,
    )
    return ValidatedGapFinding(
        candidate=cand,
        validation_verdict=validation_verdict,
        grounded_facts_count=grounded_facts_count,
        covered_evidence_ids=covered_evidence_ids or [FACT_1_ID],
        corpus_truncation_warning=corpus_truncation_warning,
        grounding_notes=grounding_notes,
        source_omission_warning=source_omission_warning,
    )


def make_detection_result(
    project_id: UUID = PROJECT_A_ID,
    gaps: list[ValidatedGapFinding] | None = None,
) -> GapDetectionResult:
    """Helper to construct a valid GapDetectionResult for testing."""
    findings = gaps if gaps is not None else [make_validated_finding()]
    return GapDetectionResult(
        project_id=project_id,
        research_question="What are solar subsidy rules and eligibility criteria?",
        total_gaps_detected=len(findings),
        gaps=findings,
        analysis_summary="Analysis synthesis of information gaps.",
        warnings=[],
        has_corpus_truncation=False,
        sources_evaluated=2,
        facts_evaluated=4,
        claims_evaluated=2,
        topics_evaluated=1,
        ai_analysis_executed=True,
    )


# =============================================================================
# 1. Ownership & Authorization Tests
# =============================================================================

class TestOwnershipAndAuthorization:
    """Verify strict project ownership and resource boundary enforcement."""

    @pytest.mark.asyncio
    async def test_valid_owner_can_persist_findings(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """1. Valid project owner successfully persists findings into public.information_gaps."""
        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,
            "title": "Solar Research",
            "status": "In Progress",
        }
        mock_conn.fetch.side_effect = [
            [{"id": TOPIC_1_ID, "name": "Eligibility"}],  # topics
            [{"id": FACT_1_ID}],  # evidence
            [],  # existing gaps (none)
            [  # final fetch after insert
                {
                    "id": GAP_1_ID,
                    "project_id": PROJECT_A_ID,
                    "topic_id": TOPIC_1_ID,
                    "gap_description": "The sources omit residency criteria for applicants.",
                    "explanation": "Residency criteria are required for participation scope.",
                    "suggested_query": "non-resident eligibility solar",
                    "priority": "high",
                    "status": "open",
                    "gap_type": "insufficient_evidence",
                    "confidence_metadata": {
                        "bharmafills": {
                            "schema_version": 1,
                            "gap_subtype": "incomplete_detail",
                            "validation_verdict": "partially_covered",
                        }
                    },
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }
            ],
        ]

        service = GapPersistenceService(db_manager=mock_db_manager)
        result = make_detection_result()

        response = await service.persist_detection_result(
            project_id=PROJECT_A_ID,
            user_id=USER_A_ID,
            detection_result=result,
        )

        assert response.project_id == PROJECT_A_ID
        assert response.total_findings_evaluated == 1
        assert response.inserted_count == 1
        assert response.updated_count == 0
        assert len(response.gaps) == 1
        assert response.gaps[0].id == GAP_1_ID

    @pytest.mark.asyncio
    @pytest.mark.parametrize("invalid_user_id", [None, "invalid-uuid", 12345, ""])
    async def test_missing_or_invalid_user_id_rejected(
        self,
        mock_db_manager: MagicMock,
        invalid_user_id: Any,
    ) -> None:
        """2-3. Missing or non-UUID user_id raises TypeError."""
        service = GapPersistenceService(db_manager=mock_db_manager)
        result = make_detection_result()

        with pytest.raises(TypeError, match="user_id must be a UUID instance"):
            await service.persist_detection_result(
                project_id=PROJECT_A_ID,
                user_id=invalid_user_id,
                detection_result=result,
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("invalid_proj_id", [None, "invalid-uuid", 9999])
    async def test_invalid_project_id_rejected(
        self,
        mock_db_manager: MagicMock,
        invalid_proj_id: Any,
    ) -> None:
        """4. Missing or non-UUID project_id raises TypeError."""
        service = GapPersistenceService(db_manager=mock_db_manager)
        result = make_detection_result()

        with pytest.raises(TypeError, match="project_id must be a UUID instance"):
            await service.persist_detection_result(
                project_id=invalid_proj_id,
                user_id=USER_A_ID,
                detection_result=result,
            )

    @pytest.mark.asyncio
    async def test_foreign_owned_project_rejected(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """5. Foreign project access raises ProjectNotFoundError (generic 404 IDOR masking)."""
        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,  # Owned by User A
            "title": "Private Research",
            "status": "In Progress",
        }

        service = GapPersistenceService(db_manager=mock_db_manager)
        result = make_detection_result(project_id=PROJECT_A_ID)

        # User B attempts to persist into User A's project
        with pytest.raises(ProjectNotFoundError):
            await service.persist_detection_result(
                project_id=PROJECT_A_ID,
                user_id=USER_B_ID,
                detection_result=result,
            )

    @pytest.mark.asyncio
    async def test_deleted_project_rejected(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """6. Soft-deleted project returns None from query and raises ProjectNotFoundError."""
        mock_conn.fetchrow.return_value = None  # WHERE deleted_at IS NULL returns nothing

        service = GapPersistenceService(db_manager=mock_db_manager)
        result = make_detection_result()

        with pytest.raises(ProjectNotFoundError):
            await service.persist_detection_result(
                project_id=PROJECT_A_ID,
                user_id=USER_A_ID,
                detection_result=result,
            )

    @pytest.mark.asyncio
    async def test_foreign_gap_uuid_cannot_be_retrieved(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """7. Retrieving a gap with valid ownership of Project A fails if gap belongs to Project B."""
        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            None,  # Gap query: WHERE id = $1 AND project_id = $2 returns nothing
        ]

        service = GapPersistenceService(db_manager=mock_db_manager)

        with pytest.raises(ProjectNotFoundError):
            await service.get_project_gap(
                project_id=PROJECT_A_ID,
                gap_id=GAP_2_ID,
                user_id=USER_A_ID,
            )

    @pytest.mark.asyncio
    async def test_foreign_gap_uuid_cannot_be_updated(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """8. Updating review on a gap not belonging to project raises ProjectNotFoundError."""
        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            None,  # Gap query in transaction returns nothing
        ]

        service = GapPersistenceService(db_manager=mock_db_manager)
        update_data = GapReviewUpdate(status=GapReviewStatus.INVESTIGATING)

        with pytest.raises(ProjectNotFoundError):
            await service.update_gap_review(
                project_id=PROJECT_A_ID,
                gap_id=GAP_2_ID,
                user_id=USER_A_ID,
                update_data=update_data,
            )

    @pytest.mark.asyncio
    async def test_ownership_checked_before_mutation(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """9. Zero database mutations occur if ownership verification fails."""
        mock_conn.fetchrow.return_value = None  # Project not found

        service = GapPersistenceService(db_manager=mock_db_manager)
        result = make_detection_result()

        with pytest.raises(ProjectNotFoundError):
            await service.persist_detection_result(
                project_id=PROJECT_A_ID,
                user_id=USER_A_ID,
                detection_result=result,
            )

        assert mock_conn.execute.call_count == 0


# =============================================================================
# 2. Persistence & Database Mapping Tests
# =============================================================================

class TestPersistenceAndMapping:
    """Verify accurate mapping between validated findings and database schema."""

    @pytest.mark.asyncio
    async def test_validated_finding_maps_correctly_to_db_columns(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """10. Findings map accurately to all public.information_gaps columns."""
        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,
            "title": "P1",
            "status": "In Progress",
        }
        mock_conn.fetch.side_effect = [
            [{"id": TOPIC_1_ID, "name": "Eligibility"}],
            [{"id": FACT_1_ID}],
            [],  # existing gaps
            [  # final fetch
                {
                    "id": GAP_1_ID,
                    "project_id": PROJECT_A_ID,
                    "topic_id": TOPIC_1_ID,
                    "gap_description": "The sources omit residency criteria for applicants.",
                    "explanation": "Residency criteria are required for participation scope.",
                    "suggested_query": "non-resident eligibility solar",
                    "priority": "high",
                    "status": "open",
                    "gap_type": "insufficient_evidence",
                    "confidence_metadata": {
                        "bharmafills": {
                            "schema_version": 1,
                            "gap_subtype": "incomplete_detail",
                            "validation_verdict": "partially_covered",
                        }
                    },
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }
            ],
        ]

        service = GapPersistenceService(db_manager=mock_db_manager)
        result = make_detection_result()

        response = await service.persist_detection_result(
            project_id=PROJECT_A_ID,
            user_id=USER_A_ID,
            detection_result=result,
        )

        # Inspect the INSERT statement executed
        insert_calls = [c for c in mock_conn.execute.call_args_list if "INSERT INTO public.information_gaps" in str(c)]
        assert len(insert_calls) == 1
        args = insert_calls[0][0]

        # Verify column mappings
        assert args[2] == PROJECT_A_ID  # project_id
        assert args[3] == TOPIC_1_ID    # topic_id mapped from 'Eligibility'
        assert args[4] == "The sources omit residency criteria for applicants."  # gap_description
        assert args[5] == "Residency criteria are required for participation scope."  # explanation
        assert args[6] == "non-resident eligibility solar"  # suggested_query
        assert args[7] == "high"  # priority
        assert args[8] == "insufficient_evidence"  # gap_type

    @pytest.mark.asyncio
    async def test_gap_subtype_and_verdict_preserved_in_metadata(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """11-12. Subtype and verdict are stored inside confidence_metadata['bharmafills']."""
        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,
            "title": "P1",
            "status": "In Progress",
        }
        mock_conn.fetch.side_effect = [
            [],  # topics
            [{"id": FACT_1_ID}],  # evidence
            [],  # existing gaps
            [],  # final fetch
        ]

        service = GapPersistenceService(db_manager=mock_db_manager)
        finding = make_validated_finding(
            gap_subtype=GapSubtype.MISSING_TOPIC,
            validation_verdict="confirmed",
        )
        result = make_detection_result(gaps=[finding])

        await service.persist_detection_result(
            project_id=PROJECT_A_ID,
            user_id=USER_A_ID,
            detection_result=result,
        )

        insert_call = [c for c in mock_conn.execute.call_args_list if "INSERT INTO public.information_gaps" in str(c)][0]
        meta_json = json.loads(insert_call[0][9])

        bharmafills_meta = meta_json["bharmafills"]
        assert bharmafills_meta["gap_subtype"] == "missing_topic"
        assert bharmafills_meta["validation_verdict"] == "confirmed"
        assert bharmafills_meta["schema_version"] == 1

    @pytest.mark.asyncio
    async def test_evidence_ids_sanitized_strictly_against_project(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """13-14. Foreign or unknown evidence IDs are discarded from covered_evidence_ids."""
        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,
            "title": "P1",
            "status": "In Progress",
        }
        mock_conn.fetch.side_effect = [
            [],  # topics
            [{"id": FACT_1_ID}],  # Only FACT_1_ID exists in project; FOREIGN_FACT_ID does not
            [],  # existing gaps
            [],  # final fetch
        ]

        service = GapPersistenceService(db_manager=mock_db_manager)
        finding = make_validated_finding(
            covered_evidence_ids=[FACT_1_ID, FOREIGN_FACT_ID],  # Includes foreign ID
        )
        result = make_detection_result(gaps=[finding])

        await service.persist_detection_result(
            project_id=PROJECT_A_ID,
            user_id=USER_A_ID,
            detection_result=result,
        )

        insert_call = [c for c in mock_conn.execute.call_args_list if "INSERT INTO public.information_gaps" in str(c)][0]
        meta_json = json.loads(insert_call[0][9])

        covered = meta_json["bharmafills"]["covered_evidence_ids"]
        assert str(FACT_1_ID) in covered
        assert str(FOREIGN_FACT_ID) not in covered  # Must be stripped

    @pytest.mark.asyncio
    async def test_topic_ids_verified_and_unknown_names_produce_null(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """15-16. Matched topic names set topic_id; unknown topic names produce NULL topic_id."""
        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,
            "title": "P1",
            "status": "In Progress",
        }
        mock_conn.fetch.side_effect = [
            [{"id": TOPIC_1_ID, "name": "Permitting"}],  # Only 'Permitting' exists
            [],  # evidence
            [],  # existing gaps
            [],  # final fetch
        ]

        service = GapPersistenceService(db_manager=mock_db_manager)
        # Candidate references 'Nonexistent Topic'
        finding = make_validated_finding(related_topic_name="Nonexistent Topic")
        result = make_detection_result(gaps=[finding])

        await service.persist_detection_result(
            project_id=PROJECT_A_ID,
            user_id=USER_A_ID,
            detection_result=result,
        )

        insert_call = [c for c in mock_conn.execute.call_args_list if "INSERT INTO public.information_gaps" in str(c)][0]
        assert insert_call[0][3] is None  # topic_id must be None

    @pytest.mark.asyncio
    async def test_topic_lookup_scopes_to_public_topics_and_enforces_project_isolation(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """15b. Topic lookup queries public.topics scoped to project_id and isolates foreign topics."""
        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,
            "title": "P1",
            "status": "In Progress",
        }
        # Only project A's topics are returned by 'SELECT id, name FROM public.topics WHERE project_id = $1;'
        mock_conn.fetch.side_effect = [
            [{"id": TOPIC_1_ID, "name": "Permitting"}],  # topics in Project A
            [],  # evidence
            [],  # existing gaps
            [],  # final fetch
        ]

        service = GapPersistenceService(db_manager=mock_db_manager)

        # Candidate 1: matching topic with whitespace and mixed casing
        finding_matched = make_validated_finding(
            candidate_id=1,
            target_subquestion="Subquestion 1",
            gap_description="Gap description 1",
            related_topic_name="  pErMiTtInG  ",
        )
        # Candidate 2: foreign topic name belonging to Project B (not in Project A)
        finding_foreign = make_validated_finding(
            candidate_id=2,
            target_subquestion="Subquestion 2",
            gap_description="Gap description 2",
            related_topic_name="Project B Exclusive Topic",
        )
        # Candidate 3: unmapped None topic
        finding_none = make_validated_finding(
            candidate_id=3,
            target_subquestion="Subquestion 3",
            gap_description="Gap description 3",
            related_topic_name=None,
        )

        result = make_detection_result(gaps=[finding_matched, finding_foreign, finding_none])

        await service.persist_detection_result(
            project_id=PROJECT_A_ID,
            user_id=USER_A_ID,
            detection_result=result,
        )

        # 1. Verify exact query targets public.topics scoped to project_id = $1
        topic_query_call = mock_conn.fetch.call_args_list[0]
        assert "SELECT id, name FROM public.topics WHERE project_id = $1;" in topic_query_call[0][0]
        assert topic_query_call[0][1] == PROJECT_A_ID

        # 2. Inspect INSERT statements for each candidate
        insert_calls = [c for c in mock_conn.execute.call_args_list if "INSERT INTO public.information_gaps" in str(c)]
        assert len(insert_calls) == 3

        # Candidate 1: Matched topic belonging to project is correctly associated
        assert insert_calls[0][0][3] == TOPIC_1_ID

        # Candidate 2: Foreign topic not in project returns NULL (no foreign key violation)
        assert insert_calls[1][0][3] is None

        # Candidate 3: Missing topic returns NULL
        assert insert_calls[2][0][3] is None

    @pytest.mark.asyncio
    async def test_ai_confidence_labeled_explicitly(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """17. AI confidence is stored as ai_confidence without claiming objective factual certainty."""
        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,
            "title": "P1",
            "status": "In Progress",
        }
        mock_conn.fetch.side_effect = [[], [], [], []]

        service = GapPersistenceService(db_manager=mock_db_manager)
        finding = make_validated_finding(confidence_score=0.876)
        result = make_detection_result(gaps=[finding])

        await service.persist_detection_result(
            project_id=PROJECT_A_ID,
            user_id=USER_A_ID,
            detection_result=result,
        )

        insert_call = [c for c in mock_conn.execute.call_args_list if "INSERT INTO public.information_gaps" in str(c)][0]
        meta_json = json.loads(insert_call[0][9])
        assert meta_json["bharmafills"]["ai_confidence"] == 0.876


# =============================================================================
# 3. Idempotency & Reruns Tests
# =============================================================================

class TestIdempotencyAndReruns:
    """Verify duplicate prevention, review status preservation, and rerun stability."""

    def test_fingerprint_generation_is_deterministic(self) -> None:
        """18. Stable SHA-256 fingerprint produces identical hashes for normalized inputs."""
        fp1 = compute_gap_fingerprint(
            project_id=PROJECT_A_ID,
            target_subquestion="What are the non-resident eligibility rules?",
            gap_description="Omission of residency guidelines.",
            gap_subtype="incomplete_detail",
        )
        fp2 = compute_gap_fingerprint(
            project_id=PROJECT_A_ID,
            target_subquestion="  WHAT ARE THE NON-RESIDENT   ELIGIBILITY RULES?  ",
            gap_description="  omission of residency guidelines.  ",
            gap_subtype="INCOMPLETE_DETAIL",
        )
        assert fp1 == fp2
        assert len(fp1) == 64  # Valid SHA-256 hex string

    @pytest.mark.asyncio
    async def test_same_fingerprint_rerun_does_not_create_duplicate(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """19-20. Rerunning identical finding executes UPDATE instead of INSERT, preserving row UUID."""
        fp = compute_gap_fingerprint(
            project_id=PROJECT_A_ID,
            target_subquestion="What are the non-resident eligibility rules?",
            gap_description="The sources omit residency criteria for applicants.",
            gap_subtype="incomplete_detail",
        )

        existing_record = {
            "id": GAP_1_ID,
            "project_id": PROJECT_A_ID,
            "topic_id": TOPIC_1_ID,
            "gap_description": "Old gap description.",
            "explanation": "Old explanation.",
            "suggested_query": "old query",
            "priority": "medium",
            "status": "investigating",  # User had marked this investigating!
            "gap_type": "insufficient_evidence",
            "confidence_metadata": {
                "custom_tool_tag": "legacy_data",
                "bharmafills": {
                    "schema_version": 1,
                    "fingerprint": fp,
                    "user_review": {"notes": "Reviewed with policy team."},
                },
            },
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,
            "title": "P1",
            "status": "In Progress",
        }
        mock_conn.fetch.side_effect = [
            [],  # topics
            [],  # evidence
            [existing_record],  # existing gaps contains matching fingerprint!
            [existing_record],  # final fetch
        ]

        service = GapPersistenceService(db_manager=mock_db_manager)
        result = make_detection_result()

        response = await service.persist_detection_result(
            project_id=PROJECT_A_ID,
            user_id=USER_A_ID,
            detection_result=result,
        )

        assert response.inserted_count == 0
        assert response.updated_count == 1
        assert response.total_persisted == 1

        # Must execute UPDATE, NOT INSERT
        assert not any("INSERT INTO public.information_gaps" in str(c) for c in mock_conn.execute.call_args_list)
        update_calls = [c for c in mock_conn.execute.call_args_list if "UPDATE public.information_gaps" in str(c)]
        assert len(update_calls) == 1

        # Inspected update call ensures GAP_1_ID was targeted ($8 is id parameter)
        assert update_calls[0][0][8] == GAP_1_ID

    @pytest.mark.asyncio
    @pytest.mark.parametrize("user_status", ["investigating", "resolved", "dismissed"])
    async def test_rerun_preserves_user_review_status(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        user_status: str,
    ) -> None:
        """21-23. Rerun never resets investigating, resolved, or dismissed status back to open."""
        fp = compute_gap_fingerprint(
            project_id=PROJECT_A_ID,
            target_subquestion="What are the non-resident eligibility rules?",
            gap_description="The sources omit residency criteria for applicants.",
            gap_subtype="incomplete_detail",
        )

        existing_record = {
            "id": GAP_1_ID,
            "project_id": PROJECT_A_ID,
            "topic_id": TOPIC_1_ID,
            "gap_description": "The sources omit residency criteria for applicants.",
            "explanation": "Residency criteria required.",
            "suggested_query": "query",
            "priority": "medium",
            "status": user_status,
            "gap_type": "insufficient_evidence",
            "confidence_metadata": {"bharmafills": {"fingerprint": fp}},
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,
            "title": "P1",
            "status": "In Progress",
        }
        mock_conn.fetch.side_effect = [[], [], [existing_record], [existing_record]]

        service = GapPersistenceService(db_manager=mock_db_manager)
        result = make_detection_result()

        await service.persist_detection_result(
            project_id=PROJECT_A_ID,
            user_id=USER_A_ID,
            detection_result=result,
        )

        update_call = [c for c in mock_conn.execute.call_args_list if "UPDATE public.information_gaps" in str(c)][0]
        # In UPDATE statement, status is NOT in the SET clause, guaranteeing status is preserved!
        sql = update_call[0][0]
        assert "status = " not in sql

    @pytest.mark.asyncio
    async def test_rerun_preserves_user_notes_and_custom_keys(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """24-25. User review notes and unknown external JSONB keys are preserved during rerun."""
        fp = compute_gap_fingerprint(
            project_id=PROJECT_A_ID,
            target_subquestion="What are the non-resident eligibility rules?",
            gap_description="The sources omit residency criteria for applicants.",
            gap_subtype="incomplete_detail",
        )

        existing_record = {
            "id": GAP_1_ID,
            "project_id": PROJECT_A_ID,
            "topic_id": None,
            "gap_description": "Old description.",
            "explanation": "Old explanation.",
            "suggested_query": None,
            "priority": "low",
            "status": "open",
            "gap_type": "insufficient_evidence",
            "confidence_metadata": {
                "external_pipeline_id": "ext-12345",  # Custom unknown key
                "bharmafills": {
                    "fingerprint": fp,
                    "user_review": {
                        "notes": "Critical note from compliance officer.",
                        "updated_at": "2026-11-01T10:00:00Z",
                    },
                },
            },
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,
            "title": "P1",
            "status": "In Progress",
        }
        mock_conn.fetch.side_effect = [[], [], [existing_record], [existing_record]]

        service = GapPersistenceService(db_manager=mock_db_manager)
        result = make_detection_result()

        await service.persist_detection_result(
            project_id=PROJECT_A_ID,
            user_id=USER_A_ID,
            detection_result=result,
        )

        update_call = [c for c in mock_conn.execute.call_args_list if "UPDATE public.information_gaps" in str(c)][0]
        meta_json = json.loads(update_call[0][7])

        # Preserves custom unknown key
        assert meta_json["external_pipeline_id"] == "ext-12345"
        # Preserves user review notes
        assert meta_json["bharmafills"]["user_review"]["notes"] == "Critical note from compliance officer."

    @pytest.mark.asyncio
    async def test_omitted_findings_on_rerun_not_automatically_deleted(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """26. Findings present in database but absent from current rerun are NOT deleted or resolved."""
        fp1 = compute_gap_fingerprint(
            project_id=PROJECT_A_ID,
            target_subquestion="Subquestion A",
            gap_description="Gap A",
            gap_subtype="missing_topic",
        )
        fp2 = compute_gap_fingerprint(
            project_id=PROJECT_A_ID,
            target_subquestion="Subquestion B",
            gap_description="Gap B",
            gap_subtype="unanswered_question",
        )

        existing_record_1 = {
            "id": GAP_1_ID,
            "project_id": PROJECT_A_ID,
            "topic_id": None,
            "gap_description": "Gap A",
            "explanation": "Exp A",
            "suggested_query": None,
            "priority": "high",
            "status": "open",
            "gap_type": "no_evidence",
            "confidence_metadata": {"bharmafills": {"fingerprint": fp1}},
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        existing_record_2 = {
            "id": GAP_2_ID,
            "project_id": PROJECT_A_ID,
            "topic_id": None,
            "gap_description": "Gap B",
            "explanation": "Exp B",
            "suggested_query": None,
            "priority": "medium",
            "status": "investigating",  # Preserved!
            "gap_type": "insufficient_evidence",
            "confidence_metadata": {"bharmafills": {"fingerprint": fp2}},
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,
            "title": "P1",
            "status": "In Progress",
        }
        # Result only contains finding 1! Finding 2 is absent!
        mock_conn.fetch.side_effect = [
            [],
            [],
            [existing_record_1, existing_record_2],
            [existing_record_1, existing_record_2],
        ]

        service = GapPersistenceService(db_manager=mock_db_manager)
        finding_1 = make_validated_finding(
            target_subquestion="Subquestion A",
            gap_description="Gap A",
            gap_subtype=GapSubtype.MISSING_TOPIC,
        )
        result = make_detection_result(gaps=[finding_1])

        response = await service.persist_detection_result(
            project_id=PROJECT_A_ID,
            user_id=USER_A_ID,
            detection_result=result,
        )

        assert not any("DELETE FROM public.information_gaps" in str(c) for c in mock_conn.execute.call_args_list)
        assert response.preserved_count == 1
        assert len(response.gaps) == 2

    @pytest.mark.asyncio
    async def test_concurrent_reruns_serialized_via_advisory_lock(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """27. Execution acquires project-scoped advisory transaction lock."""
        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,
            "title": "P1",
            "status": "In Progress",
        }
        mock_conn.fetch.side_effect = [[], [], [], []]

        service = GapPersistenceService(db_manager=mock_db_manager)
        result = make_detection_result()

        await service.persist_detection_result(
            project_id=PROJECT_A_ID,
            user_id=USER_A_ID,
            detection_result=result,
        )

        lock_calls = [c for c in mock_conn.execute.call_args_list if "pg_advisory_xact_lock" in str(c)]
        assert len(lock_calls) == 1
        assert lock_calls[0][0][1] == PROJECT_A_ID


# =============================================================================
# 4. Review Updates Tests
# =============================================================================

class TestReviewUpdates:
    """Verify service-level user review updates and boundaries."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("review_status", "status_str"),
        [
            (GapReviewStatus.INVESTIGATING, "investigating"),
            (GapReviewStatus.RESOLVED, "resolved"),
            (GapReviewStatus.DISMISSED, "dismissed"),
        ],
    )
    async def test_user_can_transition_to_allowed_statuses(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        review_status: GapReviewStatus,
        status_str: str,
    ) -> None:
        """28-30. User can mark a gap investigating, resolved, or dismissed."""
        existing_record = {
            "id": GAP_1_ID,
            "project_id": PROJECT_A_ID,
            "topic_id": TOPIC_1_ID,
            "gap_description": "Gap desc",
            "explanation": "Exp",
            "suggested_query": None,
            "priority": "high",
            "status": "open",
            "gap_type": "no_evidence",
            "confidence_metadata": {"bharmafills": {"ai_confidence": 0.9}},
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        updated_record = dict(existing_record)
        updated_record["status"] = status_str
        updated_record["confidence_metadata"] = {
            "bharmafills": {
                "ai_confidence": 0.9,
                "user_review": {"notes": "Reviewed", "updated_at": "2026-11-01T12:00:00Z"},
            }
        }

        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            existing_record,  # SELECT FOR UPDATE
            updated_record,   # RETURNING row
        ]

        service = GapPersistenceService(db_manager=mock_db_manager)
        update_data = GapReviewUpdate(
            status=review_status,
            user_notes="Reviewed",
        )

        response = await service.update_gap_review(
            project_id=PROJECT_A_ID,
            gap_id=GAP_1_ID,
            user_id=USER_A_ID,
            update_data=update_data,
        )

        assert response.status.value == status_str
        assert response.confidence_metadata["bharmafills"]["user_review"]["notes"] == "Reviewed"

    def test_invalid_status_updates_rejected_by_schema(self) -> None:
        """31-32. Transitioning to 'open' or arbitrary string is rejected by Pydantic schema."""
        with pytest.raises(ValidationError):
            GapReviewUpdate(status="open")  # 'open' is not in GapReviewStatus

        with pytest.raises(ValidationError):
            GapReviewUpdate(status="arbitrary_invalid")

    def test_user_notes_length_limited(self) -> None:
        """33. User notes exceeding 2000 characters are rejected."""
        with pytest.raises(ValidationError):
            GapReviewUpdate(
                status=GapReviewStatus.INVESTIGATING,
                user_notes="a" * 2001,
            )

    @pytest.mark.asyncio
    async def test_review_updates_cannot_modify_detection_metadata(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """34-35. Review updates only touch status and user_review; detection fields are preserved."""
        existing_record = {
            "id": GAP_1_ID,
            "project_id": PROJECT_A_ID,
            "topic_id": TOPIC_1_ID,
            "gap_description": "Protected description.",
            "explanation": "Protected explanation.",
            "suggested_query": "protected query",
            "priority": "critical",
            "status": "open",
            "gap_type": "no_evidence",
            "confidence_metadata": {
                "custom_unrelated_key": "must_be_preserved",
                "bharmafills": {
                    "schema_version": 1,
                    "fingerprint": "stable-fp",
                    "gap_subtype": "missing_topic",
                    "validation_verdict": "confirmed",
                    "ai_confidence": 0.95,
                },
            },
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            existing_record,
            existing_record,  # Updated return
        ]

        service = GapPersistenceService(db_manager=mock_db_manager)
        update_data = GapReviewUpdate(
            status=GapReviewStatus.RESOLVED,
            user_notes="Resolved via source 4.",
        )

        await service.update_gap_review(
            project_id=PROJECT_A_ID,
            gap_id=GAP_1_ID,
            user_id=USER_A_ID,
            update_data=update_data,
        )

        # Inspect the UPDATE statement
        update_call = [c for c in mock_conn.fetchrow.call_args_list if "UPDATE public.information_gaps" in str(c)][0]
        meta_json = json.loads(update_call[0][2])

        # Detection metadata fields were not touched
        assert meta_json["bharmafills"]["gap_subtype"] == "missing_topic"
        assert meta_json["bharmafills"]["validation_verdict"] == "confirmed"
        assert meta_json["bharmafills"]["ai_confidence"] == 0.95
        assert meta_json["custom_unrelated_key"] == "must_be_preserved"
        assert meta_json["bharmafills"]["user_review"]["notes"] == "Resolved via source 4."

    @pytest.mark.asyncio
    async def test_update_gap_review_gap_not_found_raises_gap_not_found_error(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """35b. Updating nonexistent gap in owned project raises GapNotFoundError."""
        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            None,  # Gap not found
        ]

        service = GapPersistenceService(db_manager=mock_db_manager)
        update_data = GapReviewUpdate(status=GapReviewStatus.INVESTIGATING)

        with pytest.raises(GapNotFoundError):
            await service.update_gap_review(
                project_id=PROJECT_A_ID,
                gap_id=GAP_1_ID,
                user_id=USER_A_ID,
                update_data=update_data,
            )

    @pytest.mark.asyncio
    async def test_update_gap_review_omitted_notes_preserves_existing_notes(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """35c. Updating status with omitted user_notes preserves previous notes."""
        existing_record = {
            "id": GAP_1_ID,
            "project_id": PROJECT_A_ID,
            "topic_id": TOPIC_1_ID,
            "gap_description": "Protected description.",
            "explanation": "Protected explanation.",
            "suggested_query": "protected query",
            "priority": "critical",
            "status": "investigating",
            "gap_type": "no_evidence",
            "confidence_metadata": {
                "bharmafills": {
                    "schema_version": 1,
                    "fingerprint": "stable-fp",
                    "user_review": {"notes": "Original investigative note."},
                },
            },
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            existing_record,
            existing_record,
        ]

        service = GapPersistenceService(db_manager=mock_db_manager)
        update_data = GapReviewUpdate(status=GapReviewStatus.RESOLVED)  # user_notes is None

        await service.update_gap_review(
            project_id=PROJECT_A_ID,
            gap_id=GAP_1_ID,
            user_id=USER_A_ID,
            update_data=update_data,
        )

        update_call = [c for c in mock_conn.fetchrow.call_args_list if "UPDATE public.information_gaps" in str(c)][0]
        # $1 status must transition to 'resolved'
        assert update_call[0][1] == "resolved"
        meta_json = json.loads(update_call[0][2])
        # Original note must be preserved
        assert meta_json["bharmafills"]["user_review"]["notes"] == "Original investigative note."


# =============================================================================
# 5. Retrieval & Transaction Safety Tests
# =============================================================================

class TestRetrievalAndTransactionSafety:
    """Verify project scoping, filtering, and transaction rollback."""

    @pytest.mark.asyncio
    async def test_project_gap_list_scoped_correctly(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """36. list_project_gaps queries exclusively within project_id boundary."""
        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,
            "title": "P1",
            "status": "In Progress",
        }
        mock_conn.fetch.return_value = [
            {
                "id": GAP_1_ID,
                "project_id": PROJECT_A_ID,
                "topic_id": None,
                "gap_description": "Gap 1",
                "explanation": "Exp 1",
                "suggested_query": None,
                "priority": "high",
                "status": "open",
                "gap_type": "no_evidence",
                "confidence_metadata": {},
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        ]

        service = GapPersistenceService(db_manager=mock_db_manager)
        gaps = await service.list_project_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        assert len(gaps) == 1
        assert gaps[0].id == GAP_1_ID
        assert gaps[0].project_id == PROJECT_A_ID

        query_sql = mock_conn.fetch.call_args[0][0]
        assert "WHERE project_id = $1" in query_sql

    @pytest.mark.asyncio
    async def test_list_filtering_by_status_priority_gap_type(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """37. list_project_gaps passes filter parameters correctly."""
        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,
            "title": "P1",
            "status": "In Progress",
        }
        mock_conn.fetch.return_value = []

        service = GapPersistenceService(db_manager=mock_db_manager)
        await service.list_project_gaps(
            project_id=PROJECT_A_ID,
            user_id=USER_A_ID,
            status=GapStatus.INVESTIGATING,
            priority=GapPriority.CRITICAL,
            gap_type=GapType.CONFLICTING_EVIDENCE,
            limit=25,
            offset=10,
        )

        call_args = mock_conn.fetch.call_args[0]
        assert call_args[1] == PROJECT_A_ID
        assert call_args[2] == "investigating"
        assert call_args[3] == "critical"
        assert call_args[4] == "conflicting_evidence"
        assert call_args[5] == 25
        assert call_args[6] == 10

    @pytest.mark.asyncio
    async def test_single_gap_retrieval_requires_both_project_and_gap_identity(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """38. get_project_gap queries with both id = $1 AND project_id = $2."""
        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            {
                "id": GAP_1_ID,
                "project_id": PROJECT_A_ID,
                "topic_id": None,
                "gap_description": "Gap 1",
                "explanation": "Exp 1",
                "suggested_query": None,
                "priority": "low",
                "status": "resolved",
                "gap_type": "unverified",
                "confidence_metadata": {},
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            },
        ]

        service = GapPersistenceService(db_manager=mock_db_manager)
        gap = await service.get_project_gap(
            project_id=PROJECT_A_ID,
            gap_id=GAP_1_ID,
            user_id=USER_A_ID,
        )

        assert gap.id == GAP_1_ID
        assert gap.project_id == PROJECT_A_ID

        fetch_call = mock_conn.fetchrow.call_args_list[1]
        assert "WHERE id = $1 AND project_id = $2" in fetch_call[0][0]
        assert fetch_call[0][1] == GAP_1_ID
        assert fetch_call[0][2] == PROJECT_A_ID

    @pytest.mark.asyncio
    async def test_get_project_gap_not_found_raises_gap_not_found_error(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """38b. get_project_gap with nonexistent gap raises GapNotFoundError."""
        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            None,
        ]

        service = GapPersistenceService(db_manager=mock_db_manager)
        with pytest.raises(GapNotFoundError):
            await service.get_project_gap(
                project_id=PROJECT_A_ID,
                gap_id=GAP_1_ID,
                user_id=USER_A_ID,
            )

    @pytest.mark.asyncio
    async def test_list_project_gaps_clamps_limit_and_offset(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """38c. list_project_gaps clamps negative or excessive limit/offset values."""
        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,
            "title": "P1",
            "status": "In Progress",
        }
        mock_conn.fetch.return_value = []

        service = GapPersistenceService(db_manager=mock_db_manager)
        await service.list_project_gaps(
            project_id=PROJECT_A_ID,
            user_id=USER_A_ID,
            limit=9999,  # Should clamp to 200
            offset=-50,  # Should clamp to 0
        )

        call_args = mock_conn.fetch.call_args[0]
        assert call_args[5] == 200
        assert call_args[6] == 0

    @pytest.mark.asyncio
    async def test_database_failure_rolls_back_persistence(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """39. Database error during persistence raises GapTransactionError."""
        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,
            "title": "P1",
            "status": "In Progress",
        }
        # Simulate database error on topic fetch
        mock_conn.fetch.side_effect = asyncpg.PostgresConnectionError("Connection lost")

        service = GapPersistenceService(db_manager=mock_db_manager)
        result = make_detection_result()

        with pytest.raises(GapTransactionError, match="Failed to persist gap batch"):
            await service.persist_detection_result(
                project_id=PROJECT_A_ID,
                user_id=USER_A_ID,
                detection_result=result,
            )

    @pytest.mark.asyncio
    async def test_empty_detection_result_handled_gracefully(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
    ) -> None:
        """40. Empty detection result persists 0 items and reports preserved count without failure."""
        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,
            "title": "P1",
            "status": "In Progress",
        }
        mock_conn.fetch.side_effect = [
            [],  # topics
            [],  # evidence
            [],  # existing gaps
            [],  # final fetch
        ]

        service = GapPersistenceService(db_manager=mock_db_manager)
        result = make_detection_result(gaps=[])

        response = await service.persist_detection_result(
            project_id=PROJECT_A_ID,
            user_id=USER_A_ID,
            detection_result=result,
        )

        assert response.total_findings_evaluated == 0
        assert response.total_persisted == 0
        assert response.inserted_count == 0
        assert response.updated_count == 0

    @pytest.mark.asyncio
    async def test_verify_gap_belongs_to_project_helper(
        self,
        mock_conn: AsyncMock,
    ) -> None:
        """41. verify_gap_belongs_to_project helper validates child relationship."""
        # 41A: Valid gap relationship
        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            {"id": GAP_1_ID, "project_id": PROJECT_A_ID, "status": "open"},
        ]

        gap_dict = await verify_gap_belongs_to_project(
            conn=mock_conn,
            project_id=PROJECT_A_ID,
            gap_id=GAP_1_ID,
            user_id=USER_A_ID,
        )
        assert gap_dict["id"] == GAP_1_ID

        # 41B: Gap belonging to another project raises ResourceMismatchError
        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            {"id": GAP_2_ID, "project_id": PROJECT_B_ID, "status": "open"},  # Project B!
        ]

        with pytest.raises(ResourceMismatchError):
            await verify_gap_belongs_to_project(
                conn=mock_conn,
                project_id=PROJECT_A_ID,
                gap_id=GAP_2_ID,
                user_id=USER_A_ID,
            )

    @pytest.mark.asyncio
    async def test_get_gap_persistence_service_singleton(self) -> None:
        """42. Singleton helper returns cached service instance."""
        from app.services.ai.gap_persistence_service import get_gap_persistence_service
        s1 = get_gap_persistence_service()
        s2 = get_gap_persistence_service()
        assert s1 is s2
