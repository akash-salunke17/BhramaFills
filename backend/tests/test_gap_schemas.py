"""Unit tests for Information Gap Detection Pydantic schemas and enums.

Verifies:
- Controlled enums match PostgreSQL check constraints and expected domain values.
- Untrusted AI candidate payload (AIGapCandidatePayload) validation:
  * String length boundaries and whitespace rejection.
  * Numerical bounds for candidate_id and confidence_score.
  * Rejection of NaN, +inf, -inf.
  * Rejection of unexpected extra fields (anti-injection / anti-leakage).
  * Immutability (frozen=True).
- Top-level AI detection payload (AIGapDetectionPayload):
  * Uniqueness of candidate_id values.
  * Empty gaps list handling.
  * Max list constraints (gaps <= 50, warnings <= 50).
- Backend validation envelope (ValidatedGapFinding):
  * Verdict literal constraints.
  * Non-negative facts count.
- Persisted entity schema (InformationGapResponse):
  * Required database fields and UUIDs.
- User review update schema (GapReviewUpdate):
  * Allowed review statuses (investigating, resolved, dismissed).
  * Strict rejection of reverting to 'open' or arbitrary statuses.
- GapDetectionResult execution envelope.
"""

from datetime import datetime, timezone
import math
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.services.ai.gap_schemas import (
    AIGapCandidatePayload,
    AIGapDetectionPayload,
    GapDetectionResult,
    GapPriority,
    GapReviewStatus,
    GapReviewUpdate,
    GapStatus,
    GapSubtype,
    GapType,
    InformationGapResponse,
    ValidatedGapFinding,
)


# ---------------------------------------------------------------------------
# Fixtures & Sample Data
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_candidate_dict() -> dict:
    return {
        "candidate_id": 1,
        "target_subquestion": "What are the eligibility criteria for the pilot program?",
        "gap_description": "The provided sources describe funding levels but omit non-resident eligibility rules.",
        "explanation": "Understanding eligibility restrictions is required to determine potential participants.",
        "gap_type": "insufficient_evidence",
        "gap_subtype": "incomplete_detail",
        "priority": "high",
        "suggested_query": "pilot program residency eligibility requirements",
        "related_topic_name": "Eligibility",
        "confidence_score": 0.88,
        "reasoning": "Sources 1 and 2 mention budget figures but contain zero statements regarding who qualifies.",
    }


# ---------------------------------------------------------------------------
# Enum Tests
# ---------------------------------------------------------------------------

class TestGapEnums:
    """Verify all controlled enum definitions match exact database constraints."""

    def test_gap_type_members(self) -> None:
        expected = {"no_evidence", "insufficient_evidence", "conflicting_evidence", "unverified"}
        assert {e.value for e in GapType} == expected

    def test_gap_priority_members(self) -> None:
        expected = {"low", "medium", "high", "critical"}
        assert {e.value for e in GapPriority} == expected

    def test_gap_status_members(self) -> None:
        expected = {"open", "investigating", "resolved", "dismissed"}
        assert {e.value for e in GapStatus} == expected

    def test_gap_subtype_members(self) -> None:
        expected = {
            "unanswered_question",
            "missing_topic",
            "incomplete_detail",
            "single_source_assertion",
            "temporal_coverage_gap",
            "contradictory_evidence",
        }
        assert {e.value for e in GapSubtype} == expected

    def test_gap_review_status_members(self) -> None:
        """User review must NOT permit setting status back to 'open'."""
        expected = {"investigating", "resolved", "dismissed"}
        assert {e.value for e in GapReviewStatus} == expected
        assert "open" not in {e.value for e in GapReviewStatus}


# ---------------------------------------------------------------------------
# AIGapCandidatePayload Tests
# ---------------------------------------------------------------------------

class TestAIGapCandidatePayload:
    """Test AI candidate model validation and boundaries."""

    def test_valid_candidate_creation(self, valid_candidate_dict: dict) -> None:
        candidate = AIGapCandidatePayload(**valid_candidate_dict)
        assert candidate.candidate_id == 1
        assert candidate.gap_type == GapType.INSUFFICIENT_EVIDENCE
        assert candidate.gap_subtype == GapSubtype.INCOMPLETE_DETAIL
        assert candidate.priority == GapPriority.HIGH
        assert candidate.confidence_score == 0.88
        assert candidate.suggested_query == "pilot program residency eligibility requirements"
        assert candidate.related_topic_name == "Eligibility"

    def test_candidate_without_optional_fields(self, valid_candidate_dict: dict) -> None:
        payload = dict(valid_candidate_dict)
        payload["suggested_query"] = None
        payload["related_topic_name"] = None
        candidate = AIGapCandidatePayload(**payload)
        assert candidate.suggested_query is None
        assert candidate.related_topic_name is None

    def test_forbids_unexpected_extra_fields(self, valid_candidate_dict: dict) -> None:
        """Prevent prompt injection from injecting database-owned or arbitrary fields."""
        payload = dict(valid_candidate_dict)
        payload["id"] = str(uuid4())
        payload["status"] = "resolved"
        payload["user_id"] = str(uuid4())

        with pytest.raises(ValidationError) as exc_info:
            AIGapCandidatePayload(**payload)
        err_str = str(exc_info.value)
        assert "extra_forbidden" in err_str

    def test_immutability(self, valid_candidate_dict: dict) -> None:
        candidate = AIGapCandidatePayload(**valid_candidate_dict)
        with pytest.raises(ValidationError):
            candidate.candidate_id = 2  # type: ignore

    @pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
    def test_confidence_score_boundaries_valid(
        self, valid_candidate_dict: dict, confidence: float
    ) -> None:
        payload = dict(valid_candidate_dict, confidence_score=confidence)
        candidate = AIGapCandidatePayload(**payload)
        assert candidate.confidence_score == confidence

    @pytest.mark.parametrize("bad_confidence", [-0.01, 1.01, -10.0, 100.0])
    def test_confidence_score_out_of_bounds(
        self, valid_candidate_dict: dict, bad_confidence: float
    ) -> None:
        payload = dict(valid_candidate_dict, confidence_score=bad_confidence)
        with pytest.raises(ValidationError):
            AIGapCandidatePayload(**payload)

    @pytest.mark.parametrize("bad_val", [float("nan"), float("inf"), float("-inf")])
    def test_confidence_score_rejects_nan_and_inf(
        self, valid_candidate_dict: dict, bad_val: float
    ) -> None:
        payload = dict(valid_candidate_dict, confidence_score=bad_val)
        with pytest.raises(ValidationError) as exc_info:
            AIGapCandidatePayload(**payload)
        assert "finite number" in str(exc_info.value)

    @pytest.mark.parametrize("candidate_id", [1, 50, 100])
    def test_candidate_id_bounds_valid(
        self, valid_candidate_dict: dict, candidate_id: int
    ) -> None:
        payload = dict(valid_candidate_dict, candidate_id=candidate_id)
        candidate = AIGapCandidatePayload(**payload)
        assert candidate.candidate_id == candidate_id

    @pytest.mark.parametrize("bad_id", [0, -1, 101, 500])
    def test_candidate_id_out_of_bounds(
        self, valid_candidate_dict: dict, bad_id: int
    ) -> None:
        payload = dict(valid_candidate_dict, candidate_id=bad_id)
        with pytest.raises(ValidationError):
            AIGapCandidatePayload(**payload)

    def test_string_fields_reject_pure_whitespace(
        self, valid_candidate_dict: dict
    ) -> None:
        for field in ["target_subquestion", "gap_description", "explanation", "reasoning"]:
            payload = dict(valid_candidate_dict)
            payload[field] = "   "
            with pytest.raises(ValidationError) as exc_info:
                AIGapCandidatePayload(**payload)
            assert "cannot be empty or pure whitespace" in str(exc_info.value)

    def test_optional_strings_stripped_or_none(
        self, valid_candidate_dict: dict
    ) -> None:
        payload = dict(valid_candidate_dict)
        payload["suggested_query"] = "  test query  "
        candidate = AIGapCandidatePayload(**payload)
        assert candidate.suggested_query == "test query"

        # Pure whitespace optional string rejected
        payload["suggested_query"] = "   "
        with pytest.raises(ValidationError):
            AIGapCandidatePayload(**payload)


# ---------------------------------------------------------------------------
# AIGapDetectionPayload Tests
# ---------------------------------------------------------------------------

class TestAIGapDetectionPayload:
    """Test top-level structured AI response model."""

    def test_valid_detection_payload(self, valid_candidate_dict: dict) -> None:
        candidate = AIGapCandidatePayload(**valid_candidate_dict)
        payload = AIGapDetectionPayload(
            gaps=[candidate],
            analysis_summary="Analysis found one major eligibility gap.",
            warnings=["Source 2 had minor OCR artifacts."],
        )
        assert len(payload.gaps) == 1
        assert payload.analysis_summary == "Analysis found one major eligibility gap."
        assert payload.warnings == ["Source 2 had minor OCR artifacts."]

    def test_empty_gaps_is_valid(self) -> None:
        """When corpus has complete coverage, gaps list can be empty."""
        payload = AIGapDetectionPayload(
            gaps=[],
            analysis_summary="The provided sources thoroughly cover all aspects of the research question.",
            warnings=[],
        )
        assert len(payload.gaps) == 0
        assert payload.warnings == []

    def test_rejects_duplicate_candidate_ids(self, valid_candidate_dict: dict) -> None:
        c1 = AIGapCandidatePayload(**valid_candidate_dict)
        c2_dict = dict(valid_candidate_dict, gap_description="Another distinct description for candidate 2")
        c2 = AIGapCandidatePayload(**c2_dict)

        with pytest.raises(ValidationError) as exc_info:
            AIGapDetectionPayload(
                gaps=[c1, c2],
                analysis_summary="Summary text here.",
            )
        assert "Duplicate candidate_id 1 found" in str(exc_info.value)

    def test_rejects_pure_whitespace_summary(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            AIGapDetectionPayload(
                gaps=[],
                analysis_summary="   ",
            )
        assert "cannot be empty or pure whitespace" in str(exc_info.value)

    def test_rejects_empty_string_in_warnings(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            AIGapDetectionPayload(
                gaps=[],
                analysis_summary="Valid summary",
                warnings=["Valid warning", "   "],
            )
        assert "must be a non-empty string" in str(exc_info.value)

    def test_forbids_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            AIGapDetectionPayload(
                gaps=[],
                analysis_summary="Valid summary",
                unexpected_field="injection_attempt",  # type: ignore
            )


# ---------------------------------------------------------------------------
# ValidatedGapFinding Tests
# ---------------------------------------------------------------------------

class TestValidatedGapFinding:
    """Test backend verification envelope wrapping candidate gaps."""

    def test_valid_creation(self, valid_candidate_dict: dict) -> None:
        candidate = AIGapCandidatePayload(**valid_candidate_dict)
        ev_id = uuid4()
        finding = ValidatedGapFinding(
            candidate=candidate,
            validation_verdict="confirmed",
            grounded_facts_count=3,
            covered_evidence_ids=[ev_id],
            corpus_truncation_warning=False,
            grounding_notes="Cross-referenced against 3 facts in Source 1; eligibility is confirmed unmentioned.",
        )
        assert finding.validation_verdict == "confirmed"
        assert finding.grounded_facts_count == 3
        assert finding.covered_evidence_ids == [ev_id]
        assert finding.corpus_truncation_warning is False

    @pytest.mark.parametrize("verdict", ["confirmed", "partially_covered", "disputed_by_evidence", "redundant"])
    def test_allowed_verdicts(self, valid_candidate_dict: dict, verdict: str) -> None:
        candidate = AIGapCandidatePayload(**valid_candidate_dict)
        finding = ValidatedGapFinding(
            candidate=candidate,
            validation_verdict=verdict,  # type: ignore
        )
        assert finding.validation_verdict == verdict

    def test_invalid_verdict_rejected(self, valid_candidate_dict: dict) -> None:
        candidate = AIGapCandidatePayload(**valid_candidate_dict)
        with pytest.raises(ValidationError):
            ValidatedGapFinding(
                candidate=candidate,
                validation_verdict="fabricated_verdict",  # type: ignore
            )

    def test_negative_facts_count_rejected(self, valid_candidate_dict: dict) -> None:
        candidate = AIGapCandidatePayload(**valid_candidate_dict)
        with pytest.raises(ValidationError):
            ValidatedGapFinding(
                candidate=candidate,
                validation_verdict="confirmed",
                grounded_facts_count=-1,
            )


# ---------------------------------------------------------------------------
# InformationGapResponse Tests
# ---------------------------------------------------------------------------

class TestInformationGapResponse:
    """Test persisted database entity representation."""

    def test_valid_response(self) -> None:
        gap_id = uuid4()
        proj_id = uuid4()
        now = datetime.now(timezone.utc)
        resp = InformationGapResponse(
            id=gap_id,
            project_id=proj_id,
            topic_id=None,
            gap_description="Missing eligibility requirements",
            explanation="Detailed explanation",
            suggested_query="eligibility requirements",
            priority=GapPriority.HIGH,
            status=GapStatus.OPEN,
            gap_type=GapType.INSUFFICIENT_EVIDENCE,
            confidence_metadata={"confidence_score": 0.88, "gap_subtype": "incomplete_detail"},
            created_at=now,
            updated_at=now,
        )
        assert resp.id == gap_id
        assert resp.project_id == proj_id
        assert resp.status == GapStatus.OPEN
        assert resp.priority == GapPriority.HIGH
        assert resp.gap_type == GapType.INSUFFICIENT_EVIDENCE
        assert resp.confidence_metadata["confidence_score"] == 0.88

    def test_forbids_extra_fields(self) -> None:
        now = datetime.now(timezone.utc)
        with pytest.raises(ValidationError):
            InformationGapResponse(
                id=uuid4(),
                project_id=uuid4(),
                gap_description="Desc",
                explanation="Exp",
                priority=GapPriority.LOW,
                status=GapStatus.OPEN,
                gap_type=GapType.NO_EVIDENCE,
                created_at=now,
                updated_at=now,
                malicious_field="hacked",  # type: ignore
            )


# ---------------------------------------------------------------------------
# GapReviewUpdate Tests
# ---------------------------------------------------------------------------

class TestGapReviewUpdate:
    """Test user review update schema with restricted status transitions."""

    @pytest.mark.parametrize("status", [GapReviewStatus.INVESTIGATING, GapReviewStatus.RESOLVED, GapReviewStatus.DISMISSED])
    def test_allowed_review_statuses(self, status: GapReviewStatus) -> None:
        update = GapReviewUpdate(status=status, user_notes="Investigating with new sources.")
        assert update.status == status
        assert update.user_notes == "Investigating with new sources."

    def test_rejects_open_status(self) -> None:
        """User cannot set status back to 'open'."""
        with pytest.raises(ValidationError):
            GapReviewUpdate(status="open")  # type: ignore

    def test_rejects_arbitrary_status(self) -> None:
        with pytest.raises(ValidationError):
            GapReviewUpdate(status="completed")  # type: ignore

    def test_user_notes_optional(self) -> None:
        update = GapReviewUpdate(status=GapReviewStatus.RESOLVED, user_notes=None)
        assert update.user_notes is None

    def test_user_notes_rejects_pure_whitespace(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            GapReviewUpdate(status=GapReviewStatus.RESOLVED, user_notes="   ")
        assert "cannot be empty or pure whitespace" in str(exc_info.value)


# ---------------------------------------------------------------------------
# GapDetectionResult Tests
# ---------------------------------------------------------------------------

class TestGapDetectionResult:
    """Test execution envelope for the detection service."""

    def test_valid_result(self, valid_candidate_dict: dict) -> None:
        candidate = AIGapCandidatePayload(**valid_candidate_dict)
        finding = ValidatedGapFinding(
            candidate=candidate,
            validation_verdict="confirmed",
        )
        proj_id = uuid4()
        result = GapDetectionResult(
            project_id=proj_id,
            research_question="What are the details of the program?",
            total_gaps_detected=1,
            gaps=[finding],
            analysis_summary="One gap detected.",
            warnings=[],
            has_corpus_truncation=False,
            sources_evaluated=2,
        )
        assert result.project_id == proj_id
        assert result.total_gaps_detected == 1
        assert len(result.gaps) == 1
        assert result.sources_evaluated == 2
        assert isinstance(result.detected_at, datetime)

