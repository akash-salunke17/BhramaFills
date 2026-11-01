"""Pydantic schemas for web extraction requests, responses, and intermediate structures."""

from datetime import datetime
from pydantic import BaseModel, Field


class WebExtractRequest(BaseModel):
    """Input payload for web URL content extraction."""

    url: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        description="Public HTTP or HTTPS website URL to fetch and extract",
        examples=["https://example.org/articles/quantum-computing"],
    )


class HeadingItem(BaseModel):
    """Extracted structural heading from document body."""

    level: int = Field(..., ge=1, le=6, description="Heading level (1-6)")
    text: str = Field(..., description="Clean heading text")


class WebExtractResponse(BaseModel):
    """Structured extraction output containing text, metadata, and provenance."""

    url: str = Field(..., description="Original requested URL")
    final_url: str = Field(..., description="Final URL after following safe redirects")
    status_code: int = Field(..., description="HTTP status code received from origin")
    title: str | None = Field(default=None, description="Page title from <title> or <h1>")
    meta_description: str | None = Field(default=None, description="Meta or OpenGraph description")
    author: str | None = Field(default=None, description="Author or publisher if identified")
    language: str | None = Field(default=None, description="Document language from <html> tag")
    canonical_url: str | None = Field(default=None, description="Canonical link href if declared")
    clean_text: str = Field(..., description="Normalized readable text content")
    headings: list[HeadingItem] = Field(default_factory=list, description="Extracted headings")
    paragraphs: list[str] = Field(default_factory=list, description="Extracted distinct text paragraphs")
    word_count: int = Field(..., ge=0, description="Word count of clean text")
    character_count: int = Field(..., ge=0, description="Character count of clean text")
    content_hash: str = Field(..., description="SHA-256 hash of clean text for deduplication")
    redirect_count: int = Field(default=0, ge=0, description="Number of safe redirects followed")
    extracted_at: datetime = Field(..., description="Extraction timestamp in UTC")

