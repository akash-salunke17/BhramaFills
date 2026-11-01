"""Pydantic data models and enums for evidence extraction.

Provides validated, immutable schemas for:
- EvidenceLocation (provenance and physical position within source documents)
- ExtractedFact (discrete factual statements extracted from a source)
- SourceClaim (assertions or policies claimed by a source, without implicit verification)
- EvidenceExtractionResult (structured envelope for single-source extraction results)

Enforces strict separation between:
1. What a source explicitly states (facts/claims) vs. what the AI inferred.
2. Direct quotations vs. faithful paraphrases.
3. Source evidence vs. verification or objective ground truth.
4. Complete extractions vs. partial extractions from truncated sources.
"""

from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Controlled Enums
# ---------------------------------------------------------------------------

class RepresentationType(str, Enum):
    """How the extracted evidence represents the original source text.

    Distinguishes direct quotes from paraphrases to prevent AI-generated
    summaries from being presented as verbatim source citations.
    """

    DIRECT_QUOTE = "direct_quote"
    PARAPHRASE = "paraphrase"


class EvidenceSourceType(str, Enum):
    """Source medium classification matching project conventions."""

    WEB = "web"
    PDF = "pdf"


class FactType(str, Enum):
    """Categorization of extracted factual statements."""

    GENERAL = "general"
    STATISTICAL = "statistical"
    PROCEDURAL = "procedural"
    ELIGIBILITY = "eligibility"
    DEFINITIONAL = "definitional"
    TEMPORAL = "temporal"


class ClaimType(str, Enum):
    """Classification of assertions made by a source.

    Note: A claim represents what a source asserts, NOT that the claim is true.
    """

    FACTUAL_ASSERTION = "factual_assertion"
    RECOMMENDATION = "recommendation"
    POLICY_STATEMENT = "policy_statement"
    PREDICTION = "prediction"
    OPINION = "opinion"
    ELIGIBILITY_CONDITION = "eligibility_condition"
    NUMERICAL_OR_STATISTICAL = "numerical_or_statistical"


class ExtractionStatus(str, Enum):
    """Integrity and completeness status of an extraction operation."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    NO_CONTENT = "no_content"


# ---------------------------------------------------------------------------
# Helper Validators
# ---------------------------------------------------------------------------

_DISALLOWED_URL_CHARS = re.compile(r"[\x00-\x1f\x7f\s]")


def _validate_safe_url(url: str | None) -> str | None:
    """Validate a web URL string for safe protocol and structure."""
    if url is None:
        return None
    trimmed = url.strip()
    if not trimmed:
        raise ValueError("URL cannot be empty or pure whitespace.")
    if len(trimmed) > 2048:
        raise ValueError(f"URL length ({len(trimmed)}) exceeds maximum bound (2048).")
    if _DISALLOWED_URL_CHARS.search(trimmed):
        raise ValueError("URL contains illegal whitespace or control characters.")
    parsed = urlparse(trimmed)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"URL scheme '{parsed.scheme}' must be 'http' or 'https'.")
    if not parsed.netloc:
        raise ValueError("URL is missing a network location (domain).")
    return trimmed


# ---------------------------------------------------------------------------
# Evidence Location Model
# ---------------------------------------------------------------------------

class EvidenceLocation(BaseModel):
    """Precise location of evidence within its original source document.

    Supports both web sources (URLs, headings, paragraph indices) and
    PDF sources (page numbers, character offsets).
    """

    source_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique identifier of the source document",
    )
    source_type: EvidenceSourceType = Field(
        ...,
        description="Source type ('web' or 'pdf')",
    )
    page_number: int | None = Field(
        default=None,
        ge=1,
        description="1-based page number for PDF evidence",
    )
    url: str | None = Field(
        default=None,
        max_length=2048,
        description="Web URL reference for web evidence",
    )
    heading_path: list[str] | None = Field(
        default=None,
        description="Hierarchy of headings or section titles leading to the evidence",
    )
    paragraph_index: int | None = Field(
        default=None,
        ge=0,
        description="0-based paragraph index within the document or page",
    )
    start_char: int | None = Field(
        default=None,
        ge=0,
        description="0-based starting character offset within source text where reliable",
    )
    end_char: int | None = Field(
        default=None,
        ge=0,
        description="0-based ending character offset within source text where reliable",
    )
    location_description: str | None = Field(
        default=None,
        max_length=500,
        description="Human-readable location fallback (e.g. 'Section 3.2, Paragraph 4')",
    )

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("source_id", mode="before")
    @classmethod
    def _validate_source_id(cls, v: Any) -> str:
        if v is None:
            raise ValueError("source_id cannot be None.")
        s = str(v).strip()
        if not s:
            raise ValueError("source_id cannot be empty or pure whitespace.")
        if len(s) > 100:
            raise ValueError(f"source_id length ({len(s)}) exceeds maximum bound (100).")
        return s

    @field_validator("source_type", mode="before")
    @classmethod
    def _normalize_source_type(cls, v: Any) -> EvidenceSourceType:
        if isinstance(v, str):
            lowered = v.strip().lower()
            if lowered == "url":
                return EvidenceSourceType.WEB
            try:
                return EvidenceSourceType(lowered)
            except ValueError:
                raise ValueError(
                    f"Unsupported source_type '{v}'. Must be 'web' (or 'url') or 'pdf'."
                )
        return v

    @field_validator("url")
    @classmethod
    def _validate_url_field(cls, v: str | None) -> str | None:
        return _validate_safe_url(v)

    @field_validator("heading_path")
    @classmethod
    def _clean_heading_path(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        cleaned = [h.strip() for h in v if h and h.strip()]
        return cleaned if cleaned else None

    @model_validator(mode="after")
    def _validate_offsets_and_type_consistency(self) -> "EvidenceLocation":
        # Character offset order validation
        if self.start_char is not None and self.end_char is not None:
            if self.end_char <= self.start_char:
                raise ValueError(
                    f"end_char ({self.end_char}) must be greater than start_char ({self.start_char})."
                )

        # PDF page validation
        if self.source_type == EvidenceSourceType.PDF and self.page_number is not None:
            if self.page_number < 1:
                raise ValueError(f"PDF page_number ({self.page_number}) must be >= 1.")

        return self


# ---------------------------------------------------------------------------
# Extracted Fact Model
# ---------------------------------------------------------------------------

class ExtractedFact(BaseModel):
    """A discrete factual statement extracted from one source.

    Distinguishes direct quotes from paraphrases and preserves uncertainty,
    conditions, exceptions, and extraction warnings.
    """

    fact_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique identifier for the extracted fact",
    )
    statement: str = Field(
        ...,
        min_length=3,
        max_length=5000,
        description="The extracted factual statement",
    )
    fact_type: FactType = Field(
        default=FactType.GENERAL,
        description="Factual category (statistical, procedural, eligibility, etc.)",
    )
    location: EvidenceLocation = Field(
        ...,
        description="Precise source provenance and location",
    )
    evidence_text: str = Field(
        ...,
        min_length=3,
        max_length=10000,
        description="Supporting verbatim or excerpted text from the source",
    )
    representation_type: RepresentationType = Field(
        ...,
        description="Whether statement is a direct quote or faithful paraphrase",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Extraction confidence score between 0.0 and 1.0",
    )
    qualifiers: list[str] = Field(
        default_factory=list,
        description="Conditions, dates, exceptions, or eligibility restrictions",
    )
    uncertainty_notes: str | None = Field(
        default=None,
        max_length=1000,
        description="Notes on ambiguities, caveats, or what remains unproven",
    )
    extraction_warnings: list[str] = Field(
        default_factory=list,
        description="Warnings or anomalies encountered during fact extraction",
    )

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("fact_id", "statement", "evidence_text", mode="before")
    @classmethod
    def _strip_and_validate_non_empty_strings(cls, v: Any, info: Any) -> str:
        if v is None:
            raise ValueError(f"{info.field_name} cannot be None.")
        s = str(v).strip()
        if not s:
            raise ValueError(f"{info.field_name} cannot be empty or pure whitespace.")
        return s

    @field_validator("qualifiers", "extraction_warnings")
    @classmethod
    def _clean_string_list(cls, v: list[str]) -> list[str]:
        if not v:
            return []
        return [item.strip() for item in v if item and item.strip()]


# ---------------------------------------------------------------------------
# Source Claim Model
# ---------------------------------------------------------------------------

class SourceClaim(BaseModel):
    """A claim made by a source.

    Represents what the source claims (which may be an assertion, opinion,
    policy, prediction, or recommendation). Does NOT imply the claim is
    objectively true or verified.
    """

    claim_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique identifier for the source claim",
    )
    claim_text: str = Field(
        ...,
        min_length=3,
        max_length=5000,
        description="The statement or assertion claimed by the source",
    )
    claim_type: ClaimType = Field(
        ...,
        description="Classification of claim (assertion, recommendation, policy, opinion, etc.)",
    )
    source_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Identifier of the claiming source",
    )
    evidence_location: EvidenceLocation = Field(
        ...,
        description="Location within the source where the claim appears",
    )
    representation_type: RepresentationType = Field(
        ...,
        description="Whether claim text is a direct quote or paraphrase",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in extraction fidelity (NOT truth of the claim)",
    )
    qualifiers: list[str] = Field(
        default_factory=list,
        description="Conditions, exceptions, dates, or scope limiting the claim",
    )
    uncertainty_notes: str | None = Field(
        default=None,
        max_length=1000,
        description="Notes on subjectivity, hedging, or lack of grounding in the source",
    )
    extraction_warnings: list[str] = Field(
        default_factory=list,
        description="Warnings encountered during claim extraction",
    )

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("claim_id", "claim_text", "source_id", mode="before")
    @classmethod
    def _strip_and_validate_non_empty_strings(cls, v: Any, info: Any) -> str:
        if v is None:
            raise ValueError(f"{info.field_name} cannot be None.")
        s = str(v).strip()
        if not s:
            raise ValueError(f"{info.field_name} cannot be empty or pure whitespace.")
        return s

    @field_validator("qualifiers", "extraction_warnings")
    @classmethod
    def _clean_string_list(cls, v: list[str]) -> list[str]:
        if not v:
            return []
        return [item.strip() for item in v if item and item.strip()]

    @model_validator(mode="after")
    def _validate_source_id_consistency(self) -> "SourceClaim":
        if self.source_id != self.evidence_location.source_id:
            raise ValueError(
                f"Source ID mismatch: claim source_id '{self.source_id}' does not "
                f"match evidence_location.source_id '{self.evidence_location.source_id}'."
            )
        return self


# ---------------------------------------------------------------------------
# Evidence Extraction Result Envelope
# ---------------------------------------------------------------------------

class EvidenceExtractionResult(BaseModel):
    """Structured envelope representing evidence extraction results from one source.

    Enforces data integrity:
    - Consistency of source IDs across facts, claims, and locations.
    - Explicit tracking of source truncation and character processing ratios.
    - Prohibits representing truncated extractions as unqualified 'success'.
    - Preserves warnings and errors without silent loss.
    """

    source_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique identifier of the analyzed source document",
    )
    source_type: EvidenceSourceType = Field(
        ...,
        description="Source type ('web' or 'pdf')",
    )
    facts: list[ExtractedFact] = Field(
        default_factory=list,
        description="List of discrete extracted facts",
    )
    claims: list[SourceClaim] = Field(
        default_factory=list,
        description="List of extracted source claims",
    )
    extraction_status: ExtractionStatus = Field(
        ...,
        description="Operational status ('success', 'partial', 'failed', 'no_content')",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="List of extraction warnings or non-fatal anomalies",
    )
    errors: list[str] = Field(
        default_factory=list,
        description="List of error descriptions if extraction failed or was impaired",
    )
    source_truncated: bool = Field(
        default=False,
        description="Whether the source was truncated before or during extraction",
    )
    source_character_count: int = Field(
        default=0,
        ge=0,
        description="Total character count of original source content",
    )
    processed_character_count: int = Field(
        default=0,
        ge=0,
        description="Total character count processed by the extraction engine",
    )
    extracted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of extraction completion",
    )
    run_id: UUID | None = Field(
        default=None,
        description="Optional database extraction_run_id if the result was persisted",
    )
    is_persisted: bool = Field(
        default=False,
        description="Whether the result has been persisted to the database",
    )

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("source_id", mode="before")
    @classmethod
    def _validate_source_id(cls, v: Any) -> str:
        if v is None:
            raise ValueError("source_id cannot be None.")
        s = str(v).strip()
        if not s:
            raise ValueError("source_id cannot be empty or pure whitespace.")
        if len(s) > 100:
            raise ValueError(f"source_id length ({len(s)}) exceeds maximum bound (100).")
        return s

    @field_validator("source_type", mode="before")
    @classmethod
    def _normalize_source_type(cls, v: Any) -> EvidenceSourceType:
        if isinstance(v, str):
            lowered = v.strip().lower()
            if lowered == "url":
                return EvidenceSourceType.WEB
            try:
                return EvidenceSourceType(lowered)
            except ValueError:
                raise ValueError(
                    f"Unsupported source_type '{v}'. Must be 'web' (or 'url') or 'pdf'."
                )
        return v

    @field_validator("warnings", "errors")
    @classmethod
    def _clean_string_list(cls, v: list[str]) -> list[str]:
        if not v:
            return []
        return [item.strip() for item in v if item and item.strip()]

    @model_validator(mode="after")
    def _validate_result_integrity(self) -> "EvidenceExtractionResult":
        # 1. Source ID cross-field consistency
        for i, fact in enumerate(self.facts):
            if fact.location.source_id != self.source_id:
                raise ValueError(
                    f"Fact at index {i} has source_id '{fact.location.source_id}' which does "
                    f"not match result source_id '{self.source_id}'."
                )

        for i, claim in enumerate(self.claims):
            if claim.source_id != self.source_id:
                raise ValueError(
                    f"Claim at index {i} has source_id '{claim.source_id}' which does "
                    f"not match result source_id '{self.source_id}'."
                )

        # 2. Status integrity invariants
        if self.extraction_status == ExtractionStatus.FAILED:
            if not self.errors:
                raise ValueError("An extraction with status 'failed' must provide at least one error.")

        if self.extraction_status == ExtractionStatus.NO_CONTENT:
            if self.facts or self.claims:
                raise ValueError(
                    "An extraction with status 'no_content' cannot contain facts or claims."
                )

        # 3. Truncation integrity: A truncated source must not be represented as complete 'success'
        if self.source_truncated and self.extraction_status == ExtractionStatus.SUCCESS:
            raise ValueError(
                "A truncated source cannot have extraction_status 'success'; use 'partial' "
                "to reflect incomplete corpus coverage."
            )

        # 4. Character counts ordering
        if self.source_character_count > 0 and self.processed_character_count > self.source_character_count:
            raise ValueError(
                f"processed_character_count ({self.processed_character_count}) cannot exceed "
                f"source_character_count ({self.source_character_count})."
            )

        return self


# ---------------------------------------------------------------------------
# Model Extraction Payload Contract (Model Output vs. Backend Result)
# ---------------------------------------------------------------------------

class EvidenceExtractionPayload(BaseModel):
    """Model-generated extraction payload before backend envelope assembly.

    Represents the exact JSON structure expected from the AI model completion.
    Excludes backend-owned fields (source_id, source_type, extraction_status,
    source_truncated, source_character_count, processed_character_count,
    extracted_at, backend errors) which are authoritatively managed and
    populated by the backend extraction service.
    """

    facts: list[ExtractedFact] = Field(
        default_factory=list,
        description="List of discrete extracted facts conforming to ExtractedFact",
    )
    claims: list[SourceClaim] = Field(
        default_factory=list,
        description="List of extracted source claims conforming to SourceClaim",
    )
    extraction_warnings: list[str] = Field(
        default_factory=list,
        description="Extraction-level warnings or anomalies noted by the model",
    )

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("extraction_warnings")
    @classmethod
    def _clean_warnings(cls, v: list[str]) -> list[str]:
        if not v:
            return []
        return [item.strip() for item in v if item and item.strip()]


# ---------------------------------------------------------------------------
# Batch Extraction Result Envelope
# ---------------------------------------------------------------------------

class BatchEvidenceExtractionResult(BaseModel):
    """Container for batch evidence extraction across multiple sources with summary counts."""

    results: list[EvidenceExtractionResult] = Field(
        default_factory=list,
        description="List of individual per-source EvidenceExtractionResult envelopes",
    )
    total_sources: int = Field(default=0, ge=0, description="Total sources processed in the batch")
    successful_sources: int = Field(default=0, ge=0, description="Sources successfully extracted without limitations")
    partial_sources: int = Field(default=0, ge=0, description="Sources with partial extraction (truncation or warnings)")
    failed_sources: int = Field(default=0, ge=0, description="Sources that failed extraction")
    empty_sources: int = Field(default=0, ge=0, description="Sources that contained no readable content")

    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# API Request Models
# ---------------------------------------------------------------------------

class ExtractEvidenceRequest(BaseModel):
    """Optional request payload for tailoring evidence extraction."""

    research_question: str | None = Field(
        default=None,
        description="Optional research question guiding topical relevance of extracted evidence.",
        max_length=1000,
    )
    custom_instructions: str | None = Field(
        default=None,
        description="Optional custom directives for extraction emphasis or exclusions.",
        max_length=1000,
    )

    model_config = ConfigDict(extra="forbid")



