"""Pydantic schemas for evidence persistence, extraction runs, and retrieval."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.services.ai.evidence_schemas import (
    ClaimType,
    EvidenceExtractionResult,
    EvidenceLocation,
    ExtractionStatus,
    FactType,
    RepresentationType,
)


class PersistedFactResponse(BaseModel):
    """Structured representation of an extracted fact persisted in PostgreSQL."""

    id: UUID = Field(..., description="Unique database UUID for the evidence record")
    project_id: UUID = Field(..., description="Research project UUID")
    source_id: UUID = Field(..., description="Source document UUID")
    extraction_run_id: UUID | None = Field(default=None, description="Linked extraction run UUID")
    fact_id: str | None = Field(default=None, description="Model-assigned fact identifier")
    statement: str = Field(..., description="Extracted factual statement")
    fact_type: FactType = Field(..., description="Factual category classification")
    evidence_text: str = Field(..., description="Supporting excerpt from source text")
    representation_type: RepresentationType = Field(..., description="Direct quote or paraphrase")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Extraction confidence score")
    location: EvidenceLocation = Field(..., description="Physical position within source document")
    qualifiers: list[str] = Field(default_factory=list, description="Conditions, limits, or dates")
    uncertainty_notes: str | None = Field(default=None, description="Ambiguities or notes")
    extraction_warnings: list[str] = Field(default_factory=list, description="Extraction-level warnings")
    created_at: datetime = Field(..., description="Persistence creation timestamp")

    model_config = ConfigDict(frozen=True, extra="forbid")


class PersistedClaimResponse(BaseModel):
    """Structured representation of a source claim persisted in PostgreSQL."""

    id: UUID = Field(..., description="Unique database UUID for the claim record")
    project_id: UUID = Field(..., description="Research project UUID")
    source_id: UUID = Field(..., description="Source document UUID")
    extraction_run_id: UUID | None = Field(default=None, description="Linked extraction run UUID")
    claim_id: str = Field(..., description="Model-assigned claim identifier")
    claim_text: str = Field(..., description="Assertion or policy statement claimed by source")
    claim_type: ClaimType = Field(..., description="Classification of the claim")
    representation_type: RepresentationType = Field(..., description="Direct quote or paraphrase")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Extraction fidelity confidence")
    evidence_location: EvidenceLocation = Field(..., description="Physical position within source")
    qualifiers: list[str] = Field(default_factory=list, description="Conditions or limiting scope")
    uncertainty_notes: str | None = Field(default=None, description="Subjectivity or hedging notes")
    extraction_warnings: list[str] = Field(default_factory=list, description="Extraction warnings")
    created_at: datetime = Field(..., description="Persistence creation timestamp")

    model_config = ConfigDict(frozen=True, extra="forbid")


class ExtractionRunResponse(BaseModel):
    """Metadata summary of an AI evidence extraction run."""

    id: UUID = Field(..., description="Unique extraction run UUID")
    project_id: UUID = Field(..., description="Research project UUID")
    source_id: UUID | None = Field(default=None, description="Target source UUID if single-source run")
    batch_id: UUID | None = Field(default=None, description="Batch execution group UUID if batch run")
    provider: str = Field(default="openrouter", description="AI provider used")
    model_name: str = Field(..., description="Active AI model identifier")
    extraction_status: ExtractionStatus = Field(..., description="Final run status")
    source_truncated: bool = Field(default=False, description="Whether source was truncated")
    source_character_count: int = Field(default=0, ge=0, description="Original source characters")
    processed_character_count: int = Field(default=0, ge=0, description="Retained source characters")
    facts_count: int = Field(default=0, ge=0, description="Total facts extracted in this run")
    claims_count: int = Field(default=0, ge=0, description="Total claims extracted in this run")
    warnings: list[str] = Field(default_factory=list, description="Run-level warnings")
    errors: list[str] = Field(default_factory=list, description="Run-level errors")
    run_metadata: dict[str, Any] = Field(default_factory=dict, description="Operational metadata")
    extracted_at: datetime = Field(..., description="Timestamp of AI extraction execution")
    created_at: datetime = Field(..., description="Timestamp of database persistence")

    model_config = ConfigDict(frozen=True, extra="forbid")


class PersistedEvidenceRunResponse(BaseModel):
    """Enriched container returning the extraction run and its persisted facts and claims."""

    run: ExtractionRunResponse = Field(..., description="Extraction run record")
    facts: list[PersistedFactResponse] = Field(default_factory=list, description="Persisted facts")
    claims: list[PersistedClaimResponse] = Field(default_factory=list, description="Persisted claims")

    model_config = ConfigDict(frozen=True, extra="forbid")


class BatchPersistenceResponse(BaseModel):
    """Summary of a multi-source batch persistence operation with failure isolation."""

    batch_id: UUID = Field(..., description="Shared batch identifier")
    total_sources: int = Field(default=0, ge=0, description="Total source results processed")
    successful_runs: int = Field(default=0, ge=0, description="Runs successfully persisted")
    failed_runs: int = Field(default=0, ge=0, description="Runs that failed to persist")
    runs: list[PersistedEvidenceRunResponse] = Field(default_factory=list, description="Persisted runs")
    errors: list[str] = Field(default_factory=list, description="Any error messages encountered")

    model_config = ConfigDict(frozen=True, extra="forbid")


class ProjectEvidenceResponse(BaseModel):
    """Paginated collection of evidence facts and claims for a project or source."""

    project_id: UUID = Field(..., description="Target research project UUID")
    source_id: UUID | None = Field(default=None, description="Optional target source UUID filter")
    total_facts: int = Field(default=0, ge=0, description="Total matching facts")
    total_claims: int = Field(default=0, ge=0, description="Total matching claims")
    limit: int = Field(default=50, ge=1, le=200, description="Page limit")
    offset: int = Field(default=0, ge=0, description="Page offset")
    facts: list[PersistedFactResponse] = Field(default_factory=list, description="Retrieved facts")
    claims: list[PersistedClaimResponse] = Field(default_factory=list, description="Retrieved claims")

    model_config = ConfigDict(frozen=True, extra="forbid")


class ExtractionRunListResponse(BaseModel):
    """Paginated list of extraction runs."""

    total_runs: int = Field(default=0, ge=0, description="Total matching runs")
    limit: int = Field(default=20, ge=1, le=100, description="Page limit")
    offset: int = Field(default=0, ge=0, description="Page offset")
    runs: list[ExtractionRunResponse] = Field(default_factory=list, description="Retrieved runs")

    model_config = ConfigDict(frozen=True, extra="forbid")


class PersistEvidenceRequest(BaseModel):
    """Request payload for explicitly persisting an extraction result."""

    result: EvidenceExtractionResult = Field(..., description="Validated EvidenceExtractionResult envelope")
    batch_id: UUID | None = Field(default=None, description="Optional batch association UUID")
    idempotency_key: str | None = Field(default=None, max_length=128, description="Optional idempotency key")

    model_config = ConfigDict(extra="forbid")

