"""Pydantic schemas for research project source ingestion, responses, and listings."""

from datetime import datetime
from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field


class ProjectWebSourceRequest(BaseModel):
    """Input payload for ingesting a web source into a research project."""

    url: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        description="Public HTTP or HTTPS website URL to fetch, extract, and persist",
        examples=["https://en.wikipedia.org/wiki/Information_gap_task"],
    )


class ProjectWebSourceResponse(BaseModel):
    """Structured response returned when a web source is ingested or identified as duplicate."""

    source_id: UUID = Field(..., description="Unique source identifier")
    project_id: UUID = Field(..., description="Associated research project identifier")
    original_url: str = Field(..., description="Original URL submitted by the client")
    final_url: str = Field(..., description="Final URL resolved after redirect verification")
    title: str = Field(..., description="Page or document title")
    ingestion_status: str = Field(..., description="Ingestion processing status ('completed', 'failed', 'pending')")
    extracted_content_id: UUID | None = Field(default=None, description="Identifier of the linked extracted_content record")
    word_count: int = Field(default=0, ge=0, description="Total word count of extracted text")
    character_count: int = Field(default=0, ge=0, description="Total character count of extracted text")
    content_hash: str | None = Field(default=None, description="SHA-256 hash of extracted clean text")
    is_duplicate: bool = Field(default=False, description="Flag indicating if the source already existed in the project")
    extracted_at: datetime = Field(..., description="UTC timestamp of extraction")
    created_at: datetime = Field(..., description="UTC timestamp of source creation")


class SourceSummaryResponse(BaseModel):
    """Summary item for sources associated with a project."""

    id: UUID = Field(..., description="Source identifier")
    project_id: UUID = Field(..., description="Parent project identifier")
    source_type: str = Field(..., description="Source type ('url' or 'pdf')")
    title: str = Field(..., description="Document or page title")
    original_url: str | None = Field(default=None, description="Source URL if type is url")
    original_filename: str | None = Field(default=None, description="Filename if type is pdf")
    ingestion_status: str = Field(..., description="Ingestion status")
    content_hash: str | None = Field(default=None, description="Content hash")
    word_count: int = Field(default=0, ge=0, description="Word count from metadata")
    character_count: int = Field(default=0, ge=0, description="Character count from metadata")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class SourceDetailResponse(BaseModel):
    """Full detail view for a specific source including extracted text and metadata."""

    id: UUID = Field(..., description="Source identifier")
    project_id: UUID = Field(..., description="Parent project identifier")
    source_type: str = Field(..., description="Source type ('url' or 'pdf')")
    title: str = Field(..., description="Document or page title")
    original_url: str | None = Field(default=None, description="Source URL if type is url")
    original_filename: str | None = Field(default=None, description="Filename if type is pdf")
    file_metadata: dict[str, Any] = Field(default_factory=dict, description="File and fetch metadata")
    ingestion_status: str = Field(..., description="Ingestion status")
    content_hash: str | None = Field(default=None, description="Content hash")
    extracted_content_id: UUID | None = Field(default=None, description="Identifier of the extracted content record")
    extracted_text: str | None = Field(default=None, description="Clean extracted text content")
    extraction_metadata: dict[str, Any] = Field(default_factory=dict, description="Parser extraction metadata")
    extraction_method: str | None = Field(default=None, description="Extraction parser method")
    extraction_version: str | None = Field(default=None, description="Extraction engine version")
    extracted_at: datetime | None = Field(default=None, description="Extraction timestamp")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

