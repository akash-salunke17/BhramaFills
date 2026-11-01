"""Pydantic data models and enums for Information Gap Detection.

Provides validated, immutable schemas for:
- GapType, GapPriority, GapStatus, GapSubtype, GapReviewStatus (controlled enums)
- AIGapCandidatePayload (untrusted candidate output directly from AI models)
- AIGapDetectionPayload (complete structured response payload from AI models)
- ValidatedGapFinding (backend validation envelope with grounding checks and warnings)
- InformationGapResponse (persisted entity representation for database / API layer)
- GapReviewUpdate (user review request schema with restricted status transitions)
- GapDetectionResult (execution envelope for the gap detection service)

Enforces strict separation between:
1. Untrusted AI output vs. backend-validated findings.
2. Absence of evidence in supplied sources vs. objective falsehood in reality.
3. Model-generated fields vs. backend/database-owned properties (UUIDs, timestamps, user review status).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import json
import math
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Controlled Enums
# ---------------------------------------------------------------------------

class GapType(str, Enum):
    """Categorization of information gaps matching PostgreSQL check constraint `chk_information_gaps_type`."""

    NO_EVIDENCE = "no_evidence"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    UNVERIFIED = "unverified"


class GapPriority(str, Enum):
    """Priority level of an information gap matching PostgreSQL check constraint `chk_information_gaps_priority`."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class GapStatus(str, Enum):
    """Review and lifecycle status of an information gap matching PostgreSQL check constraint `chk_information_gaps_status`."""

    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class GapSubtype(str, Enum):
    """Granular classification of the specific nature of an information deficit."""

    UNANSWERED_QUESTION = "unanswered_question"
    MISSING_TOPIC = "missing_topic"
    INCOMPLETE_DETAIL = "incomplete_detail"
    SINGLE_SOURCE_ASSERTION = "single_source_assertion"
    TEMPORAL_COVERAGE_GAP = "temporal_coverage_gap"
    CONTRADICTORY_EVIDENCE = "contradictory_evidence"


class GapReviewStatus(str, Enum):
    """Restricted status choices for user review updates (cannot transition back to open)."""

    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


# ---------------------------------------------------------------------------
# Helper Validators
# ---------------------------------------------------------------------------

def _check_non_empty_str(field_name: str, value: str | None) -> str | None:
    """Validate that a string is not empty or purely whitespace."""
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        raise ValueError(f"Field '{field_name}' cannot be empty or pure whitespace.")
    return trimmed


# ---------------------------------------------------------------------------
# Tier 1: AI Model Candidate Payload (Untrusted Output)
# ---------------------------------------------------------------------------

class AIGapCandidatePayload(BaseModel):
    """Candidate information gap proposed by the AI model.

    This model represents unverified output from Level 4 (UNVERIFIED_OUTPUT).
    It strictly forbids database-owned fields (UUIDs, timestamps, review status)
    and validates numeric/string boundaries.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: int = Field(
        ...,
        ge=1,
        le=100,
        description="Sequential integer candidate identifier (1 to 100).",
    )
    target_subquestion: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Specific subquestion or research aspect that remains unanswered or unsupported.",
    )
    gap_description: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="Objective description of what specific information is missing or unverified in the supplied sources.",
    )
    explanation: str = Field(
        ...,
        min_length=5,
        max_length=2000,
        description="Detailed explanation of why this absence matters for answering the primary research question.",
    )
    gap_type: GapType = Field(
        ...,
        description="Gap classification matching PostgreSQL check constraint.",
    )
    gap_subtype: GapSubtype = Field(
        ...,
        description="Granular subtype describing the nature of the information deficit.",
    )
    priority: GapPriority = Field(
        ...,
        description="Model-assessed urgency for resolving this gap.",
    )
    suggested_query: str | None = Field(
        default=None,
        max_length=300,
        description="Optional targeted search query to find missing evidence.",
    )
    related_topic_name: str | None = Field(
        default=None,
        max_length=100,
        description="Optional high-level research topic or domain category.",
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Self-assessed confidence score between 0.0 and 1.0.",
    )
    reasoning: str = Field(
        ...,
        min_length=3,
        max_length=2000,
        description="Step-by-step rationale for why the available evidence fails to address this subquestion.",
    )

    @field_validator("confidence_score", mode="before")
    @classmethod
    def validate_finite_confidence(cls, v: Any) -> Any:
        """Reject non-finite confidence values (NaN, +inf, -inf)."""
        if isinstance(v, (int, float)):
            if math.isnan(v) or math.isinf(v):
                raise ValueError("confidence_score must be a finite number between 0.0 and 1.0.")
        return v

    @field_validator("target_subquestion", "gap_description", "explanation", "reasoning", mode="before")
    @classmethod
    def validate_required_strings(cls, v: Any, info: Any) -> Any:
        """Ensure required text fields are not purely whitespace."""
        if v is None:
            raise ValueError(f"Field '{info.field_name}' cannot be None.")
        res = _check_non_empty_str(info.field_name, str(v))
        assert res is not None
        return res

    @field_validator("suggested_query", "related_topic_name")
    @classmethod
    def validate_optional_strings(cls, v: str | None, info: Any) -> str | None:
        """Strip optional text fields and reject empty strings."""
        return _check_non_empty_str(info.field_name, v)


class AIGapDetectionPayload(BaseModel):
    """Top-level structured response payload returned by the AI provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gaps: list[AIGapCandidatePayload] = Field(
        default_factory=list,
        max_length=50,
        description="Candidate gaps identified by the model (up to 50).",
    )
    analysis_summary: str = Field(
        ...,
        min_length=3,
        max_length=2000,
        description="High-level synthesis of corpus coverage and critical gaps.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        max_length=50,
        description="Model-reported caveats, source limitations, or ambiguities.",
    )

    @field_validator("analysis_summary")
    @classmethod
    def validate_summary(cls, v: str) -> str:
        res = _check_non_empty_str("analysis_summary", v)
        assert res is not None
        return res

    @field_validator("warnings")
    @classmethod
    def validate_warnings(cls, v: list[str]) -> list[str]:
        cleaned: list[str] = []
        for i, w in enumerate(v):
            if not isinstance(w, str) or not w.strip():
                raise ValueError(f"Warning at index {i} must be a non-empty string.")
            cleaned.append(w.strip())
        return cleaned

    @model_validator(mode="after")
    def validate_unique_candidate_ids(self) -> AIGapDetectionPayload:
        """Ensure all candidates have distinct candidate_id values."""
        seen_ids: set[int] = set()
        for candidate in self.gaps:
            if candidate.candidate_id in seen_ids:
                raise ValueError(
                    f"Duplicate candidate_id {candidate.candidate_id} found in gaps list."
                )
            seen_ids.add(candidate.candidate_id)
        return self


# ---------------------------------------------------------------------------
# Tier 2: Backend Validation Envelope
# ---------------------------------------------------------------------------

ValidationVerdict = Literal[
    "confirmed",
    "partially_covered",
    "disputed_by_evidence",
    "redundant",
]


class ValidatedGapFinding(BaseModel):
    """Backend-verified information gap finding.

    Wraps an AI candidate with grounding verification results, corpus limitation
    warnings, and covered evidence citations. The AI cannot generate this model.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: AIGapCandidatePayload = Field(
        ...,
        description="The source AI candidate evaluated.",
    )
    validation_verdict: ValidationVerdict = Field(
        ...,
        description="Outcome of backend evidence grounding and cross-referencing.",
    )
    grounded_facts_count: int = Field(
        default=0,
        ge=0,
        description="Number of existing evidence facts relevant to this gap.",
    )
    covered_evidence_ids: list[UUID] = Field(
        default_factory=list,
        description="UUIDs of existing evidence items that partially cover or relate to this gap.",
    )
    corpus_truncation_warning: bool = Field(
        default=False,
        description="Whether any sources were truncated or omitted during prompt assembly.",
    )
    grounding_notes: str = Field(
        default="",
        max_length=2000,
        description="Backend validation reasoning or cross-referencing details.",
    )
    source_omission_warning: str | None = Field(
        default=None,
        max_length=500,
        description="Warning detailing sources that were omitted from context due to token/character limits.",
    )


# ---------------------------------------------------------------------------
# Tier 3: Database Entity / Response Model
# ---------------------------------------------------------------------------

class InformationGapResponse(BaseModel):
    """Full representation of a persisted information gap entity matching `public.information_gaps`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(..., description="Unique gap identifier.")
    project_id: UUID = Field(..., description="Parent project identifier.")
    topic_id: UUID | None = Field(default=None, description="Optional associated topic identifier.")
    gap_description: str = Field(..., description="Description of the information deficit.")
    explanation: str = Field(..., description="Detailed explanation of the gap significance.")
    suggested_query: str | None = Field(default=None, description="Suggested follow-up query.")
    priority: GapPriority = Field(..., description="Priority level.")
    status: GapStatus = Field(..., description="Current status in the review workflow.")
    gap_type: GapType = Field(..., description="Type of gap.")
    confidence_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata including AI confidence, subtype, reasoning, and validation notes.",
    )
    created_at: datetime = Field(..., description="Creation timestamp (UTC).")
    updated_at: datetime = Field(..., description="Last update timestamp (UTC).")

    @field_validator("confidence_metadata", mode="before")
    @classmethod
    def validate_confidence_metadata(cls, v: Any) -> dict[str, Any]:
        """Safely parse JSON string if delivered by asyncpg or mock."""
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return {}
        if isinstance(v, dict):
            return v
        return {}


# ---------------------------------------------------------------------------
# Tier 4: User Review Request Model
# ---------------------------------------------------------------------------

class GapReviewUpdate(BaseModel):
    """Request payload for updating the status and user notes of an information gap."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: GapReviewStatus = Field(
        ...,
        description="New lifecycle status. Must be 'investigating', 'resolved', or 'dismissed'.",
    )
    user_notes: str | None = Field(
        default=None,
        max_length=2000,
        description="User-supplied explanation or notes on why the status was updated.",
    )

    @field_validator("user_notes")
    @classmethod
    def validate_notes(cls, v: str | None) -> str | None:
        return _check_non_empty_str("user_notes", v)


# ---------------------------------------------------------------------------
# Execution Result Envelope (Service Layer)
# ---------------------------------------------------------------------------

class GapDetectionResult(BaseModel):
    """Comprehensive result envelope returned by the Information Gap Detection Service."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID = Field(..., description="Target project identifier.")
    research_question: str = Field(..., description="Primary research question investigated.")
    total_gaps_detected: int = Field(ge=0, description="Total number of validated gaps identified.")
    gaps: list[ValidatedGapFinding] = Field(
        default_factory=list,
        description="List of validated gap findings.",
    )
    analysis_summary: str = Field(..., description="Synthesis of overall corpus coverage.")
    warnings: list[str] = Field(
        default_factory=list,
        description="Corpus warnings and model-reported caveats.",
    )
    has_corpus_truncation: bool = Field(
        default=False,
        description="Indicates whether any input sources were truncated or omitted.",
    )
    sources_evaluated: int = Field(
        default=0,
        ge=0,
        description="Number of distinct sources included in the evaluation.",
    )
    facts_evaluated: int = Field(
        default=0,
        ge=0,
        description="Number of evidence facts examined during detection.",
    )
    claims_evaluated: int = Field(
        default=0,
        ge=0,
        description="Number of source claims examined during detection.",
    )
    topics_evaluated: int = Field(
        default=0,
        ge=0,
        description="Number of research topics considered during detection.",
    )
    ai_analysis_executed: bool = Field(
        default=True,
        description="Indicates whether an external AI completion was executed.",
    )
    diagnostic_message: str | None = Field(
        default=None,
        description="Diagnostic explanation when detection was skipped or limited.",
    )
    detected_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the detection execution.",
    )


# ---------------------------------------------------------------------------
# Persistence Response Models (Step 10D.1)
# ---------------------------------------------------------------------------

class PersistedGapBatchResponse(BaseModel):
    """Batch persistence summary returned by GapPersistenceService.persist_detection_result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID = Field(..., description="Target research project identifier.")
    total_findings_evaluated: int = Field(ge=0, description="Total candidate findings evaluated.")
    total_persisted: int = Field(ge=0, description="Total gaps persisted (inserted + updated).")
    inserted_count: int = Field(ge=0, description="Number of new gap records inserted.")
    updated_count: int = Field(ge=0, description="Number of existing gap records updated with new detection data.")
    preserved_count: int = Field(ge=0, description="Number of existing gap records preserved without modification.")
    gaps: list[InformationGapResponse] = Field(
        default_factory=list,
        description="List of all current persisted gaps for the project.",
    )
    persisted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the persistence operation.",
    )


class InformationGapListResponse(BaseModel):
    """Container for paginated project gap retrieval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID = Field(..., description="Target research project identifier.")
    total_count: int = Field(ge=0, description="Total matching gaps in project.")
    limit: int = Field(ge=1, description="Page limit applied.")
    offset: int = Field(ge=0, description="Page offset applied.")
    gaps: list[InformationGapResponse] = Field(
        default_factory=list,
        description="Retrieved gap entities.",
    )


class DetectGapsRequest(BaseModel):
    """Optional request payload for information gap detection."""

    model_config = ConfigDict(extra="forbid")

    custom_instructions: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional domain directives or specific focus instructions for gap detection.",
    )


class GapDetectionAndPersistenceResponse(BaseModel):
    """Response returned by POST /api/v1/projects/{project_id}/gaps/detect."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID = Field(..., description="Target research project identifier.")
    detection: GapDetectionResult = Field(..., description="Information gap detection result envelope.")
    persistence: PersistedGapBatchResponse = Field(..., description="Transactional database persistence summary.")


__all__ = [
    "GapType",
    "GapPriority",
    "GapStatus",
    "GapSubtype",
    "GapReviewStatus",
    "AIGapCandidatePayload",
    "AIGapDetectionPayload",
    "ValidationVerdict",
    "ValidatedGapFinding",
    "InformationGapResponse",
    "GapReviewUpdate",
    "GapDetectionResult",
    "PersistedGapBatchResponse",
    "InformationGapListResponse",
    "DetectGapsRequest",
    "GapDetectionAndPersistenceResponse",
]
