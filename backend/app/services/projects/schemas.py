"""Pydantic schemas and enums for research project management."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectCategory(str, Enum):
    """Controlled domain categories matching PostgreSQL check constraint `chk_research_projects_category`."""

    EDUCATION = "Education"
    TECHNOLOGY = "Technology"
    SCHOLARSHIPS = "Scholarships"
    HEALTHCARE = "Healthcare"
    BUSINESS = "Business"
    GOVERNMENT_SCHEMES = "Government Schemes"
    GENERAL_RESEARCH = "General Research"
    OTHER = "Other"


class ProjectStatus(str, Enum):
    """Project lifecycle statuses matching PostgreSQL check constraint `chk_research_projects_status`."""

    DRAFT = "Draft"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    ARCHIVED = "Archived"


def _validate_trimmed_min_len(val: str, min_len: int, field_name: str) -> str:
    trimmed = val.strip()
    if len(trimmed) < min_len:
        raise ValueError(f"{field_name} must contain at least {min_len} non-whitespace characters.")
    return trimmed


class ProjectCreateRequest(BaseModel):
    """Request payload for creating a new research project."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        ...,
        min_length=3,
        max_length=120,
        description="Concise title for the research project (3-120 chars).",
    )
    research_question: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="The primary research question or gap inquiry (10-1000 chars).",
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional detailed background description or scope (max 2000 chars).",
    )
    category: ProjectCategory = Field(
        default=ProjectCategory.GENERAL_RESEARCH,
        description="Domain category.",
    )
    status: ProjectStatus = Field(
        default=ProjectStatus.DRAFT,
        description="Initial lifecycle status.",
    )

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        return _validate_trimmed_min_len(v, 3, "Title")

    @field_validator("research_question")
    @classmethod
    def validate_question(cls, v: str) -> str:
        return _validate_trimmed_min_len(v, 10, "Research question")

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip()
        return trimmed if trimmed else None


class ProjectUpdateRequest(BaseModel):
    """Request payload for updating an existing research project."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(
        default=None,
        min_length=3,
        max_length=120,
        description="Updated project title.",
    )
    research_question: str | None = Field(
        default=None,
        min_length=10,
        max_length=1000,
        description="Updated core research question.",
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Updated background description or scope.",
    )
    category: ProjectCategory | None = Field(
        default=None,
        description="Updated domain category.",
    )
    status: ProjectStatus | None = Field(
        default=None,
        description="Updated lifecycle status.",
    )

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_trimmed_min_len(v, 3, "Title")

    @field_validator("research_question")
    @classmethod
    def validate_question(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_trimmed_min_len(v, 10, "Research question")

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip()
        return trimmed if trimmed else None


class ProjectResponse(BaseModel):
    """Public representation of an owned research project entity."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: UUID = Field(..., description="Unique project UUID.")
    user_id: UUID = Field(..., description="Owner user UUID.")
    title: str = Field(..., description="Project title.")
    research_question: str = Field(..., description="Primary research question.")
    description: str | None = Field(default=None, description="Detailed description.")
    category: str = Field(..., description="Domain category.")
    status: str = Field(..., description="Current status.")
    created_at: datetime = Field(..., description="UTC creation timestamp.")
    updated_at: datetime = Field(..., description="UTC update timestamp.")


class ProjectListResponse(BaseModel):
    """Paginated collection of owned research projects."""

    model_config = ConfigDict(extra="ignore")

    projects: list[ProjectResponse] = Field(default_factory=list, description="List of research projects.")
    total_count: int = Field(ge=0, description="Total number of active projects owned by the caller.")
    limit: int = Field(default=50, description="Page limit.")
    offset: int = Field(default=0, description="Page offset.")
