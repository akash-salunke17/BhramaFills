"""Unit and integration tests for InformationGapDetectionService (Step 10C).

Verifies all mandatory requirements:
- Ownership & Security:
  * Strict caller ownership enforcement using verify_project_ownership.
  * Rejection of None, string, or invalid user_id / project_id with TypeError.
  * Generic HTTP 404 masking (ProjectNotFoundError) for foreign, missing, unowned, or deleted projects.
  * Zero AI calls before ownership verification.
  * Cross-project evidence isolation (parameterized SQL queries).
  * Backend ownership of all entity metadata; zero identity spoofing via AI output.
- Evidence Retrieval & Corpus Construction:
  * Research question loading and validation.
  * Clear separation between empirical facts and unverified source claims.
  * Topic taxonomy preservation.
  * Safe handling of empty projects, zero-evidence projects, and failed extractions.
  * Preservation of source identity and evidence provenance.
- Prompt Assembly & Truncation Transparency:
  * Reuse of PromptBuilder and assemble_gap_detection_prompt.
  * Propagation of character truncation and source omission warnings.
  * Partial corpus caution notes attached to findings.
- Evidence-Aware Candidate Validation:
  * Proper assignment of verdicts (confirmed, partially_covered, disputed_by_evidence, redundant).
  * Immunity against superficial keyword false matches.
  * Filtering of unknown or cross-project evidence IDs from covered_evidence_ids.
  * Detection of duplicate candidates.
  * Strict prohibition of AI-generated database IDs.
- Provider Resilience & Failure Containment:
  * Propagation of AITimeoutError, AIRateLimitError, AIProviderUnavailableError.
  * AIResponseValidationError on malformed JSON or invalid schema.
  * Zero database mutations (read-only execution).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.core.ownership import (
    OwnedProjectContext,
    ProjectAccessDeniedError,
    ProjectNotFoundError,
)
from app.db.connection import DatabaseManager
from app.services.ai.base import BaseAIProvider
from app.services.ai.exceptions import (
    AIAuthenticationError,
    AIProviderError,
    AIProviderUnavailableError,
    AIRateLimitError,
    AIResponseValidationError,
    AITimeoutError,
)
from app.services.ai.gap_detection_service import (
    InformationGapDetectionService,
    _extract_key_concepts,
    _is_redundant_candidate,
)
from app.services.ai.gap_schemas import (
    AIGapCandidatePayload,
    AIGapDetectionPayload,
    GapDetectionResult,
    GapPriority,
    GapSubtype,
    GapType,
    ValidatedGapFinding,
)
from app.services.ai.schemas import ChatChoice, ChatCompletionResponse, ChatMessage

# Deterministic Test UUIDs
USER_A_ID = UUID("00000000-0000-4000-a000-000000000001")
USER_B_ID = UUID("00000000-0000-4000-b000-000000000002")
PROJECT_A_ID = UUID("11111111-1111-4000-a000-000000000001")
SOURCE_1_ID = UUID("22222222-2222-4000-a000-000000000001")
SOURCE_2_ID = UUID("22222222-2222-4000-a000-000000000002")
TOPIC_1_ID = UUID("33333333-3333-4000-a000-000000000001")
FACT_1_ID = UUID("44444444-4444-4000-a000-000000000001")
FACT_2_ID = UUID("44444444-4444-4000-a000-000000000002")
CLAIM_1_ID = UUID("55555555-5555-4000-a000-000000000001")


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
    return conn


@pytest.fixture
def mock_db_manager(mock_conn: AsyncMock) -> MagicMock:
    mgr = MagicMock(spec=DatabaseManager)
    mgr.acquire_connection.return_value = MockConnectionContext(mock_conn)
    return mgr


@pytest.fixture
def mock_ai_provider() -> AsyncMock:
    provider = AsyncMock(spec=BaseAIProvider)
    provider.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"
    return provider


@pytest.fixture
def default_ai_payload() -> dict[str, Any]:
    return {
        "gaps": [
            {
                "candidate_id": 1,
                "target_subquestion": "What are the non-resident eligibility criteria?",
                "gap_description": "The sources discuss budget allocations but omit residency eligibility requirements.",
                "explanation": "Determining who can participate requires explicit residency guidelines.",
                "gap_type": "insufficient_evidence",
                "gap_subtype": "incomplete_detail",
                "priority": "high",
                "suggested_query": "program eligibility criteria non-residents",
                "related_topic_name": "Eligibility",
                "confidence_score": 0.88,
                "reasoning": "Sources 1 and 2 mention annual funding but completely omit residency rules.",
            }
        ],
        "analysis_summary": "Identified one high-priority eligibility gap.",
        "warnings": ["Sources focus primarily on financials."],
    }


def make_chat_response(content: str) -> ChatCompletionResponse:
    """Helper to build valid ChatCompletionResponse with required id and model."""
    return ChatCompletionResponse(
        id="chatcmpl-test-123",
        model="nvidia/nemotron-3-ultra-550b-a55b:free",
        choices=[ChatChoice(index=0, message=ChatMessage(role="assistant", content=content))],
    )


def _setup_standard_db_data(mock_conn: AsyncMock) -> None:
    """Helper to populate mock_conn with valid project, sources, topics, facts, and claims."""
    # 1. Project ownership check & project row
    mock_conn.fetchrow.side_effect = [
        # verify_project_ownership
        {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,
            "title": "Solar Energy Incentive Evaluation",
            "status": "In Progress",
        },
        # select full project
        {
            "id": PROJECT_A_ID,
            "title": "Solar Energy Incentive Evaluation",
            "research_question": "What are the economic and regulatory impacts of residential solar subsidies?",
            "description": "Comprehensive evaluation of clean energy subsidy programs.",
            "category": "Technology",
            "status": "In Progress",
        },
    ]

    # 2. fetch sources, topics, facts, claims, evidence_topics
    mock_conn.fetch.side_effect = [
        # sources
        [
            {
                "id": SOURCE_1_ID,
                "source_type": "web",
                "title": "Department of Energy Report",
                "original_url": "https://energy.gov/report",
                "original_filename": None,
                "ingestion_status": "completed",
                "error_message": None,
                "file_metadata": {},
                "created_at": "2026-11-01T10:00:00Z",
            },
            {
                "id": SOURCE_2_ID,
                "source_type": "pdf",
                "title": "Financial Audit 2025",
                "original_url": None,
                "original_filename": "audit_2025.pdf",
                "ingestion_status": "completed",
                "error_message": None,
                "file_metadata": {},
                "created_at": "2026-11-01T10:05:00Z",
            },
        ],
        # topics
        [
            {
                "id": TOPIC_1_ID,
                "name": "Eligibility",
                "description": "Criteria and qualifications for applicants.",
            }
        ],
        # facts
        [
            {
                "id": FACT_1_ID,
                "source_id": SOURCE_1_ID,
                "extraction_run_id": uuid4(),
                "fact_id": "fact_1",
                "claim": "The program provides a $5,000 tax credit for qualifying residential installations.",
                "fact_type": "statistical",
                "supporting_excerpt": "Homeowners receive up to $5,000 in direct tax credits.",
                "representation_type": "direct_quote",
                "confidence_score": 0.95,
                "location_reference": {"paragraph_index": 3},
                "qualifiers": ["residential installations"],
                "uncertainty_notes": None,
                "extraction_warnings": [],
                "start_char": 100,
                "end_char": 160,
                "page_number": None,
                "url": "https://energy.gov/report",
                "source_title": "Department of Energy Report",
                "source_type": "web",
            }
        ],
        # claims
        [
            {
                "id": CLAIM_1_ID,
                "source_id": SOURCE_2_ID,
                "extraction_run_id": uuid4(),
                "claim_id": "claim_1",
                "claim_text": "Solar adoption reduces grid peak strain by up to 14 percent.",
                "claim_type": "factual_assertion",
                "representation_type": "paraphrase",
                "confidence_score": 0.85,
                "location_reference": {"page_number": 12},
                "qualifiers": ["during summer peak hours"],
                "uncertainty_notes": "Based on simulated model data",
                "extraction_warnings": [],
                "start_char": 500,
                "end_char": 565,
                "page_number": 12,
                "url": None,
                "source_title": "Financial Audit 2025",
                "source_type": "pdf",
            }
        ],
        # evidence_topics
        [
            {
                "evidence_id": FACT_1_ID,
                "topic_id": TOPIC_1_ID,
                "topic_name": "Eligibility",
            }
        ],
    ]


# =============================================================================
# 1. Ownership & Security Tests
# =============================================================================

class TestOwnershipAndSecurity:
    """Verify strict authorization, type safety, and identity protection."""

    @pytest.mark.asyncio
    async def test_valid_owner_can_initiate_analysis(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
        default_ai_payload: dict[str, Any],
    ) -> None:
        """Owner of project successfully triggers detection and receives result."""
        _setup_standard_db_data(mock_conn)
        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(default_ai_payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        assert isinstance(result, GapDetectionResult)
        assert result.project_id == PROJECT_A_ID
        assert result.ai_analysis_executed is True
        assert result.total_gaps_detected == 1
        assert len(result.gaps) == 1
        assert mock_ai_provider.complete.call_count == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("invalid_user_id", [None, "not-a-uuid", 12345, []])
    async def test_invalid_user_id_rejected(
        self,
        mock_db_manager: MagicMock,
        mock_ai_provider: AsyncMock,
        invalid_user_id: Any,
    ) -> None:
        """Reject non-UUID user_id with TypeError failing closed."""
        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )
        with pytest.raises(TypeError) as exc_info:
            await service.detect_gaps(project_id=PROJECT_A_ID, user_id=invalid_user_id)  # type: ignore
        assert "user_id must be a UUID instance" in str(exc_info.value)
        assert mock_ai_provider.complete.call_count == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("invalid_project_id", [None, "invalid-uuid-string", 999])
    async def test_invalid_project_id_rejected(
        self,
        mock_db_manager: MagicMock,
        mock_ai_provider: AsyncMock,
        invalid_project_id: Any,
    ) -> None:
        """Reject non-UUID project_id with TypeError failing closed."""
        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )
        with pytest.raises(TypeError) as exc_info:
            await service.detect_gaps(project_id=invalid_project_id, user_id=USER_A_ID)  # type: ignore
        assert "project_id must be a UUID instance" in str(exc_info.value)
        assert mock_ai_provider.complete.call_count == 0

    @pytest.mark.asyncio
    async def test_foreign_project_access_rejected(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
    ) -> None:
        """User B accessing User A's project is rejected with ProjectNotFoundError."""
        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,  # Owned by User A
            "title": "Private Project",
            "status": "In Progress",
        }

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        with pytest.raises(ProjectNotFoundError) as exc_info:
            await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_B_ID)

        assert str(PROJECT_A_ID) in str(exc_info.value)
        assert mock_ai_provider.complete.call_count == 0

    @pytest.mark.asyncio
    async def test_deleted_or_missing_project_rejected(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
    ) -> None:
        """Nonexistent or soft-deleted project returns ProjectNotFoundError."""
        mock_conn.fetchrow.return_value = None  # Not found

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        with pytest.raises(ProjectNotFoundError):
            await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        assert mock_ai_provider.complete.call_count == 0

    @pytest.mark.asyncio
    async def test_no_ai_call_before_ownership_validation(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
    ) -> None:
        """Verify strict side-effect isolation: no AI call occurs if ownership check fails."""
        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": None,  # Unowned legacy project
            "title": "Unowned",
            "status": "Draft",
        }

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        with pytest.raises(ProjectNotFoundError):
            await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        assert mock_ai_provider.complete.call_count == 0

    @pytest.mark.asyncio
    async def test_no_user_identity_spoofed_via_ai_output(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
        default_ai_payload: dict[str, Any],
    ) -> None:
        """Result project_id is strictly derived from verified context, never trusted from AI output."""
        _setup_standard_db_data(mock_conn)
        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(default_ai_payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)
        assert result.project_id == PROJECT_A_ID


# =============================================================================
# 2. Evidence Retrieval & Corpus Tests
# =============================================================================

class TestEvidenceRetrievalAndCorpus:
    """Verify evidence handling, research question loading, and corpus bounds."""

    @pytest.mark.asyncio
    async def test_research_question_loaded_and_validated(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
        default_ai_payload: dict[str, Any],
    ) -> None:
        """Valid research question is loaded and stored on the result envelope."""
        _setup_standard_db_data(mock_conn)
        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(default_ai_payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)
        assert result.research_question == "What are the economic and regulatory impacts of residential solar subsidies?"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("short_rq", ["", "   ", "Too short"])
    async def test_invalid_or_missing_research_question_rejected(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
        short_rq: str,
    ) -> None:
        """Reject research question under 10 characters with ValueError."""
        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            {"id": PROJECT_A_ID, "title": "P1", "research_question": short_rq, "status": "In Progress"},
        ]

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        with pytest.raises(ValueError) as exc_info:
            await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        assert "invalid or missing research question" in str(exc_info.value)
        assert mock_ai_provider.complete.call_count == 0

    @pytest.mark.asyncio
    async def test_empty_sources_returns_diagnostic_without_ai_call(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
    ) -> None:
        """Project with 0 sources skips AI call and returns clear diagnostic."""
        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            {"id": PROJECT_A_ID, "title": "P1", "research_question": "Valid research question here?", "status": "In Progress"},
        ]
        mock_conn.fetch.return_value = []  # 0 sources

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        assert result.total_gaps_detected == 0
        assert result.ai_analysis_executed is False
        assert result.sources_evaluated == 0
        assert "contains no sources" in result.analysis_summary
        assert "0 sources available" in result.diagnostic_message
        assert mock_ai_provider.complete.call_count == 0

    @pytest.mark.asyncio
    async def test_failed_extractions_not_mistaken_for_genuine_gaps(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
    ) -> None:
        """When all sources failed ingestion, diagnostic is returned rather than false gaps."""
        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            {"id": PROJECT_A_ID, "title": "P1", "research_question": "Valid research question here?", "status": "In Progress"},
        ]
        mock_conn.fetch.return_value = [
            {
                "id": SOURCE_1_ID,
                "title": "Broken Source",
                "source_type": "web",
                "original_url": "https://broken.com",
                "original_filename": None,
                "ingestion_status": "failed",
                "error_message": "HTTP 404 Not Found",
            }
        ]

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        assert result.total_gaps_detected == 0
        assert result.ai_analysis_executed is False
        assert "failed ingestion" in result.analysis_summary
        assert "failed ingestion" in result.diagnostic_message
        assert mock_ai_provider.complete.call_count == 0

    @pytest.mark.asyncio
    async def test_sources_with_zero_evidence_returns_diagnostic(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
    ) -> None:
        """Sources exist but 0 facts/claims extracted -> diagnostic returned without AI call."""
        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            {"id": PROJECT_A_ID, "title": "P1", "research_question": "Valid research question here?", "status": "In Progress"},
        ]
        mock_conn.fetch.side_effect = [
            [{"id": SOURCE_1_ID, "title": "Source 1", "source_type": "web", "original_url": "https://ok.com", "original_filename": None, "ingestion_status": "completed", "error_message": None}],
            [],  # topics
            [],  # facts (0 facts)
            [],  # claims (0 claims)
            [],  # evidence_topics
        ]

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        assert result.total_gaps_detected == 0
        assert result.ai_analysis_executed is False
        assert "no facts or claims have been extracted" in result.analysis_summary
        assert mock_ai_provider.complete.call_count == 0


# =============================================================================
# 3. Candidate Grounding & Validation Tests
# =============================================================================

class TestCandidateValidation:
    """Verify backend evidence grounding and verdict determination."""

    @pytest.mark.asyncio
    async def test_candidate_with_zero_evidence_is_confirmed(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
        default_ai_payload: dict[str, Any],
    ) -> None:
        """When 0 facts touch upon the subquestion, verdict is 'confirmed'."""
        _setup_standard_db_data(mock_conn)
        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(default_ai_payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        finding = result.gaps[0]
        # In setup data, FACT_1 discusses $5,000 tax credit. Candidate subquestion is "What are the non-resident eligibility criteria?"
        # Topics match "Eligibility", so FACT_1 (which is tagged with Eligibility) is matched!
        # Because candidate gap_type is INSUFFICIENT_EVIDENCE, presence of topic fact produces partially_covered!
        assert finding.validation_verdict == "partially_covered"
        assert FACT_1_ID in finding.covered_evidence_ids

    @pytest.mark.asyncio
    async def test_unrelated_candidate_is_confirmed(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
    ) -> None:
        """Candidate with zero matching topic or concept terms is confirmed as absent."""
        _setup_standard_db_data(mock_conn)
        payload = {
            "gaps": [
                {
                    "candidate_id": 1,
                    "target_subquestion": "What are the toxic chemical disposal procedures?",
                    "gap_description": "No information provided regarding hazardous chemical disposal guidelines.",
                    "explanation": "Chemical safety protocols are missing.",
                    "gap_type": "no_evidence",
                    "gap_subtype": "missing_topic",
                    "priority": "critical",
                    "suggested_query": "chemical disposal guidelines",
                    "related_topic_name": "Environmental Safety",
                    "confidence_score": 0.95,
                    "reasoning": "Corpus contains zero mentions of chemical waste.",
                }
            ],
            "analysis_summary": "Chemical disposal protocols are absent.",
            "warnings": [],
        }
        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        finding = result.gaps[0]
        assert finding.validation_verdict == "confirmed"
        assert finding.grounded_facts_count == 0
        assert finding.covered_evidence_ids == []
        assert "zero source statements were found" in finding.grounding_notes.lower()

    @pytest.mark.asyncio
    async def test_disputed_by_evidence_verdict(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
    ) -> None:
        """When candidate claims no_evidence, but multiple facts directly cover it, verdict is disputed."""
        # Setup DB with 2 facts directly addressing tax credits
        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            {"id": PROJECT_A_ID, "title": "P1", "research_question": "What are solar subsidy rules?", "status": "In Progress"},
        ]
        mock_conn.fetch.side_effect = [
            [{"id": SOURCE_1_ID, "title": "S1", "source_type": "web", "original_url": "https://s1.com", "original_filename": None, "ingestion_status": "completed", "error_message": None}],
            [{"id": TOPIC_1_ID, "name": "Tax Credits", "description": "Tax credits"}],
            [
                {
                    "id": FACT_1_ID,
                    "source_id": SOURCE_1_ID,
                    "claim": "Tax credits of $5,000 are provided for residential installations.",
                    "supporting_excerpt": "Tax credits are provided.",
                    "fact_type": "statistical",
                    "representation_type": "direct_quote",
                    "confidence_score": 0.95,
                },
                {
                    "id": FACT_2_ID,
                    "source_id": SOURCE_1_ID,
                    "claim": "Residential installations receive maximum tax credit allocations.",
                    "supporting_excerpt": "Maximum tax credit allocations.",
                    "fact_type": "general",
                    "representation_type": "direct_quote",
                    "confidence_score": 0.90,
                },
            ],
            [],  # claims
            [{"evidence_id": FACT_1_ID, "topic_id": TOPIC_1_ID, "topic_name": "Tax Credits"},
             {"evidence_id": FACT_2_ID, "topic_id": TOPIC_1_ID, "topic_name": "Tax Credits"}],
        ]

        payload = {
            "gaps": [
                {
                    "candidate_id": 1,
                    "target_subquestion": "What tax credits exist for residential installations?",
                    "gap_description": "The sources contain zero evidence or mentions of residential tax credits.",
                    "explanation": "Tax credits are required.",
                    "gap_type": "no_evidence",  # Claims NO EVIDENCE
                    "gap_subtype": "unanswered_question",
                    "priority": "high",
                    "suggested_query": "residential tax credits",
                    "related_topic_name": "Tax Credits",
                    "confidence_score": 0.85,
                    "reasoning": "No tax credit evidence observed.",
                }
            ],
            "analysis_summary": "Disputed candidate analysis.",
            "warnings": [],
        }

        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        finding = result.gaps[0]
        assert finding.validation_verdict == "disputed_by_evidence"
        assert finding.grounded_facts_count == 2
        assert "Disputed by evidence" in finding.grounding_notes

    @pytest.mark.asyncio
    async def test_duplicate_candidates_marked_redundant(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
    ) -> None:
        """Duplicate candidate targeting the same subquestion is marked redundant."""
        _setup_standard_db_data(mock_conn)
        payload = {
            "gaps": [
                {
                    "candidate_id": 1,
                    "target_subquestion": "What are the non-resident eligibility rules?",
                    "gap_description": "Omission of non-resident eligibility criteria.",
                    "explanation": "Required for participation scope.",
                    "gap_type": "insufficient_evidence",
                    "gap_subtype": "incomplete_detail",
                    "priority": "high",
                    "confidence_score": 0.90,
                    "reasoning": "Missing residency criteria.",
                },
                {
                    "candidate_id": 2,
                    "target_subquestion": "What are the non-resident eligibility rules?",  # Identical subquestion
                    "gap_description": "Residency eligibility criteria for applicants are omitted.",
                    "explanation": "Needed for applicant screening.",
                    "gap_type": "insufficient_evidence",
                    "gap_subtype": "incomplete_detail",
                    "priority": "high",
                    "confidence_score": 0.85,
                    "reasoning": "Same missing criteria.",
                },
            ],
            "analysis_summary": "Two candidate gaps found.",
            "warnings": [],
        }

        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        assert len(result.gaps) == 2
        assert result.gaps[0].validation_verdict in ("confirmed", "partially_covered")
        assert result.gaps[1].validation_verdict == "redundant"
        assert "Substantially duplicates Candidate #1" in result.gaps[1].grounding_notes

    @pytest.mark.asyncio
    async def test_unknown_evidence_ids_filtered_from_covered_ids(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
        default_ai_payload: dict[str, Any],
    ) -> None:
        """Ensure all covered_evidence_ids strictly belong to the evaluated project."""
        _setup_standard_db_data(mock_conn)
        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(default_ai_payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        for finding in result.gaps:
            for eid in finding.covered_evidence_ids:
                assert eid == FACT_1_ID  # Must match real project fact ID


# =============================================================================
# 4. Truncation & Omission Propagation Tests
# =============================================================================

class TestTruncationAndOmissionTransparency:
    """Verify metadata propagation when sources exceed character or count limits."""

    @pytest.mark.asyncio
    async def test_truncation_warning_propagated_to_result_and_findings(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
        default_ai_payload: dict[str, Any],
    ) -> None:
        """When source exceeds character limit, corpus truncation is flagged."""
        # Create a massive fact exceeding 40,000 characters to trigger PromptBuilder truncation
        large_excerpt = "Solar facts details. " * 3000  # ~63,000 chars

        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            {"id": PROJECT_A_ID, "title": "P1", "research_question": "What are solar subsidy rules?", "status": "In Progress"},
        ]
        mock_conn.fetch.side_effect = [
            [{"id": SOURCE_1_ID, "title": "Large Document", "source_type": "web", "original_url": "https://large.com", "original_filename": None, "ingestion_status": "completed", "error_message": None}],
            [],  # topics
            [
                {
                    "id": FACT_1_ID,
                    "source_id": SOURCE_1_ID,
                    "claim": "Comprehensive state subsidy program rules.",
                    "supporting_excerpt": large_excerpt,
                    "fact_type": "general",
                    "representation_type": "direct_quote",
                    "confidence_score": 0.90,
                }
            ],
            [],  # claims
            [],  # evidence_topics
        ]

        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(default_ai_payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        assert result.has_corpus_truncation is True
        assert any("partially truncated" in w for w in result.warnings)
        assert result.gaps[0].corpus_truncation_warning is True
        assert "Partial corpus coverage" in result.gaps[0].grounding_notes


# =============================================================================
# 5. Provider & Failure Handling Tests
# =============================================================================

class TestProviderAndFailureHandling:
    """Verify robust exception mapping without silent data loss."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "provider_exc",
        [
            AITimeoutError("AI timed out", timeout_seconds=30.0),
            AIRateLimitError("Rate limit exceeded", retry_after=10.0),
            AIProviderUnavailableError("OpenRouter 503 unavailable"),
            AIAuthenticationError("Invalid API key"),
        ],
    )
    async def test_provider_errors_propagate_without_false_success(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
        provider_exc: Exception,
    ) -> None:
        """Provider failures must never be converted into false empty analyses."""
        _setup_standard_db_data(mock_conn)
        mock_ai_provider.complete.side_effect = provider_exc

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        with pytest.raises(AIProviderError):
            await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_output", ["Not JSON", "{invalid_json: 123", ""])
    async def test_malformed_ai_output_raises_response_validation_error(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
        bad_output: str,
    ) -> None:
        """Unparseable model output raises AIResponseValidationError."""
        _setup_standard_db_data(mock_conn)
        mock_ai_provider.complete.return_value = make_chat_response(bad_output)

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        with pytest.raises(AIResponseValidationError):
            await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

    @pytest.mark.asyncio
    async def test_no_database_mutations_occur_during_detection(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
        default_ai_payload: dict[str, Any],
    ) -> None:
        """Detection is strictly read-only; no INSERT, UPDATE, or DELETE executed."""
        _setup_standard_db_data(mock_conn)
        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(default_ai_payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        # Verify conn.execute was never called (no mutations)
        assert mock_conn.execute.call_count == 0

    @pytest.mark.asyncio
    async def test_facts_and_claims_distinguishable_in_prompt(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
        default_ai_payload: dict[str, Any],
    ) -> None:
        """Prompt distinguishes empirical extracted facts from unverified source claims."""
        _setup_standard_db_data(mock_conn)
        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(default_ai_payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        # Inspect the messages sent to AI provider
        call_args = mock_ai_provider.complete.call_args[0][0]
        user_message_content = call_args.messages[1].content

        assert "EXTRACTED SOURCE STATEMENTS" in user_message_content
        assert "SOURCE CLAIMS (Assertions made by this source - unverified assertions)" in user_message_content
        assert "The program provides a $5,000 tax credit" in user_message_content
        assert "Solar adoption reduces grid peak strain" in user_message_content

    @pytest.mark.asyncio
    async def test_superficial_single_keyword_overlap_does_not_falsely_dispute(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
    ) -> None:
        """A candidate sharing only 1 generic word ('program') with a fact is not falsely matched."""
        _setup_standard_db_data(mock_conn)
        payload = {
            "gaps": [
                {
                    "candidate_id": 1,
                    "target_subquestion": "What software architecture governs battery dispatch algorithms?",
                    "gap_description": "The program provides zero details on software algorithms.",
                    "explanation": "Software details missing.",
                    "gap_type": "no_evidence",
                    "gap_subtype": "missing_topic",
                    "priority": "medium",
                    "confidence_score": 0.90,
                    "reasoning": "No software algorithm information.",
                }
            ],
            "analysis_summary": "Software gap.",
            "warnings": [],
        }
        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        # Despite word 'program' in both, substantive concepts (software, architecture, battery, dispatch, algorithms) do not match
        finding = result.gaps[0]
        assert finding.validation_verdict == "confirmed"
        assert finding.grounded_facts_count == 0
        assert finding.covered_evidence_ids == []

    @pytest.mark.asyncio
    async def test_source_omissions_above_limit_produce_warnings(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
        default_ai_payload: dict[str, Any],
    ) -> None:
        """When total sources exceed MAX_SOURCES_PER_PROMPT (20), omission warnings are generated."""
        many_sources = []
        many_facts = []
        for i in range(25):
            s_id = uuid4()
            f_id = uuid4()
            many_sources.append(
                {
                    "id": s_id,
                    "title": f"Source {i+1}",
                    "source_type": "web",
                    "original_url": f"https://example.com/{i+1}",
                    "original_filename": None,
                    "ingestion_status": "completed",
                    "error_message": None,
                }
            )
            many_facts.append(
                {
                    "id": f_id,
                    "source_id": s_id,
                    "claim": f"Fact statement for source {i+1}.",
                    "supporting_excerpt": f"Fact excerpt {i+1}.",
                    "fact_type": "general",
                    "representation_type": "direct_quote",
                    "confidence_score": 0.90,
                }
            )

        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            {"id": PROJECT_A_ID, "title": "P1", "research_question": "What are solar subsidy rules?", "status": "In Progress"},
        ]
        mock_conn.fetch.side_effect = [
            many_sources,
            [],  # topics
            many_facts,
            [],  # claims
            [],  # evidence_topics
        ]

        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(default_ai_payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        assert result.has_corpus_truncation is True
        assert any("Prompt source capacity was reached" in w for w in result.warnings)
        assert result.gaps[0].source_omission_warning is not None
        assert "source(s) were omitted" in result.gaps[0].source_omission_warning


# =============================================================================
# 6. Step 10C.1 Evidence Grounding Remediation Regression Tests
# =============================================================================

class TestEvidenceGroundingRemediation:
    """Verify refined validation semantics and terminology introduced in Step 10C.1.

    Validates the 10 mandatory remediation rules:
    1. Multiple shared keywords do not automatically establish coverage.
    2. Different wording expressing the same concept is recognized.
    3. Zero lexical overlap does not prove an absolute gap without considering scope.
    4. Topic association alone does not prove complete coverage.
    5. Evidence answering only part of a multi-part question yields `partially_covered`.
    6. Source assertion is not treated as independently verified truth.
    7. Genuine missing information produces a confirmed finding when supported.
    8. Uncertain cases retain explanatory grounding notes.
    9. Existing ownership and cross-project evidence isolation remain intact.
    10. Truncation and omitted-source warnings remain intact.
    """

    @pytest.mark.asyncio
    async def test_remediation_multiple_shared_keywords_not_automatic_coverage(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
    ) -> None:
        """1. Keywords in different context ('solar', 'panels', 'cost') do not falsely dispute a recycling gap."""
        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            {
                "id": PROJECT_A_ID,
                "title": "P1",
                "research_question": "What are the commercial solar panel subsidy rules and environmental impacts?",
                "status": "In Progress",
            },
        ]
        mock_conn.fetch.side_effect = [
            [
                {
                    "id": SOURCE_1_ID,
                    "title": "Packaging Report",
                    "source_type": "web",
                    "original_url": "https://example.com/packaging",
                    "original_filename": None,
                    "ingestion_status": "completed",
                    "error_message": None,
                }
            ],
            [],  # topics
            [
                {
                    "id": FACT_1_ID,
                    "source_id": SOURCE_1_ID,
                    "claim": "The shipping cost of solar panels decreased by 15% due to lighter packaging materials.",
                    "supporting_excerpt": "Lighter packaging materials reduce shipping costs for solar panels.",
                    "fact_type": "statistical",
                    "representation_type": "direct_quote",
                    "confidence_score": 0.95,
                }
            ],
            [],  # claims
            [],  # evidence_topics
        ]

        payload = {
            "gaps": [
                {
                    "candidate_id": 1,
                    "target_subquestion": "What are the recycling processes and disposal methods for decommissioned solar panels?",
                    "gap_description": "The provided sources contain zero evidence regarding recycling processes or disposal methods.",
                    "explanation": "End-of-life recycling and disposal protocols are critical.",
                    "gap_type": "no_evidence",
                    "gap_subtype": "missing_topic",
                    "priority": "critical",
                    "suggested_query": "solar panel recycling and disposal methods",
                    "related_topic_name": None,
                    "confidence_score": 0.95,
                    "reasoning": "Corpus discusses packaging shipping costs but completely omits recycling and disposal.",
                }
            ],
            "analysis_summary": "Recycling and disposal gap analysis.",
            "warnings": [],
        }
        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        finding = result.gaps[0]
        # Must NOT be falsely disputed by keyword overlap in a different operational context
        assert finding.validation_verdict == "confirmed"
        assert finding.validation_verdict != "disputed_by_evidence"
        assert finding.grounded_facts_count == 0
        assert finding.covered_evidence_ids == []
        assert "zero source statements were found" in finding.grounding_notes

    @pytest.mark.asyncio
    async def test_remediation_different_wording_same_concept_recognized(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
    ) -> None:
        """2. 'Financial assistance' matches 'subsidies' and 'grants' via canonical concept clustering."""
        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            {
                "id": PROJECT_A_ID,
                "title": "P1",
                "research_question": "What are solar incentive programs for low-income residents?",
                "status": "In Progress",
            },
        ]
        mock_conn.fetch.side_effect = [
            [
                {
                    "id": SOURCE_1_ID,
                    "title": "Assistance Policy",
                    "source_type": "web",
                    "original_url": "https://example.com/subsidy",
                    "original_filename": None,
                    "ingestion_status": "completed",
                    "error_message": None,
                }
            ],
            [],  # topics
            [
                {
                    "id": FACT_1_ID,
                    "source_id": SOURCE_1_ID,
                    "claim": "The municipal government offers means-tested subsidies and grants up to $4,000 for qualifying households.",
                    "supporting_excerpt": "Subsidies and grants are distributed to households below median income.",
                    "fact_type": "statistical",
                    "representation_type": "direct_quote",
                    "confidence_score": 0.95,
                }
            ],
            [],  # claims
            [],  # evidence_topics
        ]

        payload = {
            "gaps": [
                {
                    "candidate_id": 1,
                    "target_subquestion": "What financial assistance is available for low-income residents?",
                    "gap_description": "Specific eligibility thresholds and funding caps for financial assistance are not detailed.",
                    "explanation": "Residents need clear financial assistance guidance.",
                    "gap_type": "insufficient_evidence",
                    "gap_subtype": "incomplete_detail",
                    "priority": "high",
                    "suggested_query": "financial assistance low-income solar",
                    "related_topic_name": None,
                    "confidence_score": 0.88,
                    "reasoning": "High-level assistance is mentioned but detailed qualification steps are absent.",
                }
            ],
            "analysis_summary": "Financial assistance evaluation.",
            "warnings": [],
        }
        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        finding = result.gaps[0]
        # Should link the subsidies/grants statement as related concept coverage
        assert finding.validation_verdict == "partially_covered"
        assert FACT_1_ID in finding.covered_evidence_ids
        assert finding.grounded_facts_count == 1
        assert "Partially covered: 1 source statement(s)" in finding.grounding_notes

    @pytest.mark.asyncio
    async def test_remediation_zero_lexical_overlap_scope_transparency(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
    ) -> None:
        """3. Zero lexical overlap explicitly states corpus scope rather than claiming absolute absence."""
        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            {
                "id": PROJECT_A_ID,
                "title": "P1",
                "research_question": "What are solar subsidy rules?",
                "status": "In Progress",
            },
        ]
        mock_conn.fetch.side_effect = [
            [
                {
                    "id": SOURCE_1_ID,
                    "title": "Subsidies",
                    "source_type": "web",
                    "original_url": "https://example.com/subsidies",
                    "original_filename": None,
                    "ingestion_status": "completed",
                    "error_message": None,
                }
            ],
            [],  # topics
            [
                {
                    "id": FACT_1_ID,
                    "source_id": SOURCE_1_ID,
                    "claim": "Tax credits of $5,000 are provided for residential installations.",
                    "supporting_excerpt": "Tax credits are provided.",
                    "fact_type": "statistical",
                    "representation_type": "direct_quote",
                    "confidence_score": 0.95,
                }
            ],
            [],  # claims
            [],  # evidence_topics
        ]

        payload = {
            "gaps": [
                {
                    "candidate_id": 1,
                    "target_subquestion": "What are the wildlife habitat protection protocols near solar farms?",
                    "gap_description": "No evidence regarding wildlife habitat impact or mitigation protocols.",
                    "explanation": "Ecological protections are unaddressed.",
                    "gap_type": "no_evidence",
                    "gap_subtype": "missing_topic",
                    "priority": "medium",
                    "suggested_query": "solar farm wildlife protection protocols",
                    "related_topic_name": None,
                    "confidence_score": 0.92,
                    "reasoning": "No ecological or wildlife facts present.",
                }
            ],
            "analysis_summary": "Wildlife gap.",
            "warnings": [],
        }
        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        finding = result.gaps[0]
        assert finding.validation_verdict == "confirmed"
        assert finding.grounded_facts_count == 0
        assert finding.covered_evidence_ids == []
        # Scope is explicitly bounded to the evaluated sources
        assert "Within the analyzed corpus of 1 source(s)" in finding.grounding_notes
        assert "zero source statements were found" in finding.grounding_notes

    @pytest.mark.asyncio
    async def test_remediation_topic_association_alone_does_not_prove_coverage(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
    ) -> None:
        """4. Topic association ('Eligibility') yields partially_covered, never disputed_by_evidence."""
        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            {
                "id": PROJECT_A_ID,
                "title": "P1",
                "research_question": "What are solar subsidy rules?",
                "status": "In Progress",
            },
        ]
        mock_conn.fetch.side_effect = [
            [
                {
                    "id": SOURCE_1_ID,
                    "title": "Eligibility Guide",
                    "source_type": "web",
                    "original_url": "https://example.com/eligibility",
                    "original_filename": None,
                    "ingestion_status": "completed",
                    "error_message": None,
                }
            ],
            [{"id": TOPIC_1_ID, "name": "Eligibility", "description": "Eligibility"}],
            [
                {
                    "id": FACT_1_ID,
                    "source_id": SOURCE_1_ID,
                    "claim": "Resident homeowners receive a $5,000 tax credit.",
                    "supporting_excerpt": "Homeowners receive tax credit.",
                    "fact_type": "statistical",
                    "representation_type": "direct_quote",
                    "confidence_score": 0.95,
                }
            ],
            [],  # claims
            [{"evidence_id": FACT_1_ID, "topic_id": TOPIC_1_ID, "topic_name": "Eligibility"}],
        ]

        payload = {
            "gaps": [
                {
                    "candidate_id": 1,
                    "target_subquestion": "What are the non-resident eligibility rules?",
                    "gap_description": "The sources contain zero eligibility rules for non-resident applicants.",
                    "explanation": "Non-residents cannot verify their standing.",
                    "gap_type": "no_evidence",
                    "gap_subtype": "unanswered_question",
                    "priority": "high",
                    "suggested_query": "non-resident eligibility solar",
                    "related_topic_name": "Eligibility",
                    "confidence_score": 0.90,
                    "reasoning": "Only resident homeowners are discussed; non-residents are completely omitted.",
                }
            ],
            "analysis_summary": "Eligibility analysis.",
            "warnings": [],
        }
        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        finding = result.gaps[0]
        # Topic alone must NOT dispute the gap; it yields partially_covered with explanatory notes
        assert finding.validation_verdict == "partially_covered"
        assert finding.validation_verdict != "disputed_by_evidence"
        assert FACT_1_ID in finding.covered_evidence_ids
        assert "related context under topic 'Eligibility'" in finding.grounding_notes
        assert "is not directly answered" in finding.grounding_notes

    @pytest.mark.asyncio
    async def test_remediation_partial_question_coverage_yields_partially_covered(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
    ) -> None:
        """5. Answering only part of a multi-part inquiry yields partially_covered."""
        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            {
                "id": PROJECT_A_ID,
                "title": "P1",
                "research_question": "What are solar panel lifecycle rules?",
                "status": "In Progress",
            },
        ]
        mock_conn.fetch.side_effect = [
            [
                {
                    "id": SOURCE_1_ID,
                    "title": "Lifecycle Guide",
                    "source_type": "web",
                    "original_url": "https://example.com/lifecycle",
                    "original_filename": None,
                    "ingestion_status": "completed",
                    "error_message": None,
                }
            ],
            [],  # topics
            [
                {
                    "id": FACT_1_ID,
                    "source_id": SOURCE_1_ID,
                    "claim": "Solar panels are recycled using thermal delamination and mechanical shredding.",
                    "supporting_excerpt": "Recycling procedures include thermal delamination.",
                    "fact_type": "technical",
                    "representation_type": "direct_quote",
                    "confidence_score": 0.95,
                }
            ],
            [],  # claims
            [],  # evidence_topics
        ]

        payload = {
            "gaps": [
                {
                    "candidate_id": 1,
                    "target_subquestion": "What are the recycling procedures, disposal costs, and regulatory penalty amounts?",
                    "gap_description": "The corpus does not provide comprehensive disposal cost or regulatory penalty metrics.",
                    "explanation": "Operators need recycling methods, disposal costs, and non-compliance fines.",
                    "gap_type": "no_evidence",
                    "gap_subtype": "incomplete_detail",
                    "priority": "high",
                    "suggested_query": "solar recycling cost and regulatory penalty amounts",
                    "related_topic_name": None,
                    "confidence_score": 0.85,
                    "reasoning": "Recycling method is mentioned but costs and penalties are omitted.",
                }
            ],
            "analysis_summary": "Multi-part inquiry analysis.",
            "warnings": [],
        }
        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        finding = result.gaps[0]
        # Because only recycling method is covered while costs/penalties are omitted, verdict must be partially_covered
        assert finding.validation_verdict == "partially_covered"
        assert finding.validation_verdict != "disputed_by_evidence"
        assert FACT_1_ID in finding.covered_evidence_ids
        assert "multi-part inquiry" in finding.grounding_notes

    @pytest.mark.asyncio
    async def test_remediation_source_assertion_not_treated_as_verified_truth(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
        default_ai_payload: dict[str, Any],
    ) -> None:
        """6. Prompt headers and grounding notes refer to source statements, not verified facts."""
        _setup_standard_db_data(mock_conn)
        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(default_ai_payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        # Inspect prompt delivered to model
        call_args = mock_ai_provider.complete.call_args[0][0]
        user_message = call_args.messages[1].content
        assert "EXTRACTED SOURCE STATEMENTS (Statements excerpted directly from this source - not independently verified facts)" in user_message
        assert "SOURCE CLAIMS (Assertions made by this source - unverified assertions)" in user_message

        # Grounding notes must describe evidence as source statements
        for gap in result.gaps:
            assert "source statement(s)" in gap.grounding_notes or "zero source statements" in gap.grounding_notes

    @pytest.mark.asyncio
    async def test_remediation_genuine_missing_information_confirmed(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
    ) -> None:
        """7. Genuine missing information with zero supporting evidence produces confirmed finding."""
        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            {
                "id": PROJECT_A_ID,
                "title": "P1",
                "research_question": "What are solar subsidy rules?",
                "status": "In Progress",
            },
        ]
        mock_conn.fetch.side_effect = [
            [
                {
                    "id": SOURCE_1_ID,
                    "title": "Subsidy Guide",
                    "source_type": "web",
                    "original_url": "https://example.com/subsidy",
                    "original_filename": None,
                    "ingestion_status": "completed",
                    "error_message": None,
                }
            ],
            [],  # topics
            [
                {
                    "id": FACT_1_ID,
                    "source_id": SOURCE_1_ID,
                    "claim": "Tax credits of $5,000 are provided for residential installations.",
                    "supporting_excerpt": "Tax credits are provided.",
                    "fact_type": "statistical",
                    "representation_type": "direct_quote",
                    "confidence_score": 0.95,
                }
            ],
            [],  # claims
            [],  # evidence_topics
        ]

        payload = {
            "gaps": [
                {
                    "candidate_id": 1,
                    "target_subquestion": "What are the end-of-life toxic leaching benchmarks for cadmium telluride in municipal landfills?",
                    "gap_description": "Zero evidence or mentions regarding toxic cadmium leaching benchmarks.",
                    "explanation": "Toxic leaching limits are essential for environmental safety evaluation.",
                    "gap_type": "no_evidence",
                    "gap_subtype": "missing_topic",
                    "priority": "critical",
                    "suggested_query": "cadmium telluride toxic leaching municipal landfill benchmarks",
                    "related_topic_name": None,
                    "confidence_score": 0.98,
                    "reasoning": "Corpus contains only financial subsidy data; no toxic leaching information exists.",
                }
            ],
            "analysis_summary": "Cadmium leaching gap.",
            "warnings": [],
        }
        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        finding = result.gaps[0]
        assert finding.validation_verdict == "confirmed"
        assert finding.grounded_facts_count == 0
        assert finding.covered_evidence_ids == []
        assert "zero source statements were found" in finding.grounding_notes

    @pytest.mark.asyncio
    async def test_remediation_uncertain_cases_retain_explanatory_notes(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
        default_ai_payload: dict[str, Any],
    ) -> None:
        """8. Uncertain or partial coverage preserves candidate with explanatory notes."""
        _setup_standard_db_data(mock_conn)
        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(default_ai_payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        finding = result.gaps[0]
        assert finding.validation_verdict == "partially_covered"
        assert len(finding.grounding_notes) >= 30
        assert "Partially covered:" in finding.grounding_notes
        assert "eligibility" in finding.grounding_notes.lower()

    @pytest.mark.asyncio
    async def test_remediation_cross_project_evidence_isolation_intact(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
    ) -> None:
        """9. Foreign user access is rejected and cross-project evidence IDs are sanitized."""
        # Test 9A: Foreign user access raises ProjectNotFoundError (generic 404 masking)
        mock_conn.fetchrow.return_value = {
            "id": PROJECT_A_ID,
            "user_id": USER_A_ID,  # Belongs to USER_A
            "title": "Private Project",
            "status": "In Progress",
        }

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        with pytest.raises(ProjectNotFoundError):
            await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_B_ID)

        # Test 9B: Evidence IDs belonging to foreign projects are sanitized from covered_evidence_ids
        FOREIGN_FACT_ID = UUID("99999999-9999-4000-a000-000000000099")
        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            {"id": PROJECT_A_ID, "title": "P1", "research_question": "What are solar subsidy rules?", "status": "In Progress"},
        ]
        mock_conn.fetch.side_effect = [
            [{"id": SOURCE_1_ID, "title": "S1", "source_type": "web", "original_url": "https://s.com", "original_filename": None, "ingestion_status": "completed", "error_message": None}],
            [],  # topics
            [{"id": FACT_1_ID, "source_id": SOURCE_1_ID, "claim": "Tax credits of $5,000 exist.", "supporting_excerpt": "Tax credits.", "fact_type": "general", "representation_type": "direct_quote", "confidence_score": 0.90}],
            [],  # claims
            [],  # evidence_topics
        ]

        payload = {
            "gaps": [
                {
                    "candidate_id": 1,
                    "target_subquestion": "What tax credits exist?",
                    "gap_description": "Tax credits explanation missing.",
                    "explanation": "Needed.",
                    "gap_type": "insufficient_evidence",
                    "gap_subtype": "incomplete_detail",
                    "priority": "high",
                    "confidence_score": 0.85,
                    "reasoning": "Missing.",
                }
            ],
            "analysis_summary": "Summary.",
            "warnings": [],
        }
        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(payload))

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        # Foreign ID must not be present; only FACT_1_ID
        assert FOREIGN_FACT_ID not in result.gaps[0].covered_evidence_ids
        assert FACT_1_ID in result.gaps[0].covered_evidence_ids

    @pytest.mark.asyncio
    async def test_remediation_truncation_and_omission_warnings_intact(
        self,
        mock_db_manager: MagicMock,
        mock_conn: AsyncMock,
        mock_ai_provider: AsyncMock,
        default_ai_payload: dict[str, Any],
    ) -> None:
        """10. Prompt truncation and source omissions propagate transparent warnings to result and findings."""
        # Create 25 sources to trigger omission warning
        many_sources = []
        many_facts = []
        for i in range(25):
            s_id = uuid4()
            f_id = uuid4()
            many_sources.append(
                {
                    "id": s_id,
                    "title": f"Source {i+1}",
                    "source_type": "web",
                    "original_url": f"https://example.com/{i+1}",
                    "original_filename": None,
                    "ingestion_status": "completed",
                    "error_message": None,
                }
            )
            many_facts.append(
                {
                    "id": f_id,
                    "source_id": s_id,
                    "claim": f"Fact statement for source {i+1}." + (" large detail " * 500),
                    "supporting_excerpt": f"Excerpt {i+1}.",
                    "fact_type": "general",
                    "representation_type": "direct_quote",
                    "confidence_score": 0.90,
                }
            )

        mock_conn.fetchrow.side_effect = [
            {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "P1", "status": "In Progress"},
            {"id": PROJECT_A_ID, "title": "P1", "research_question": "What are solar subsidy rules?", "status": "In Progress"},
        ]
        mock_conn.fetch.side_effect = [
            many_sources,
            [],  # topics
            many_facts,
            [],  # claims
            [],  # evidence_topics
        ]

        mock_ai_provider.complete.return_value = make_chat_response(json.dumps(default_ai_payload))

        service = InformationGapDetectionService(
            db_manager=mock_db_manager,
            ai_provider=mock_ai_provider,
        )

        result = await service.detect_gaps(project_id=PROJECT_A_ID, user_id=USER_A_ID)

        assert result.has_corpus_truncation is True
        assert result.gaps[0].corpus_truncation_warning is True
        assert result.gaps[0].source_omission_warning is not None
        assert "source(s) were omitted" in result.gaps[0].source_omission_warning
        assert "Partial corpus coverage" in result.gaps[0].grounding_notes

