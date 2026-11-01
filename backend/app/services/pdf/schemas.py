"""Pydantic schemas for PDF upload, extraction metrics, and response models."""

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class PDFPageItem(BaseModel):
    """Extracted text and structural metrics for an individual PDF page."""

    page_number: int = Field(..., ge=1, description="1-based page number")
    text: str = Field(default="", description="Clean normalized readable text from this page")
    character_count: int = Field(default=0, ge=0, description="Character count of page text")
    word_count: int = Field(default=0, ge=0, description="Word count of page text")
    has_text: bool = Field(default=False, description="True if page contains extractable text")


class PDFExtractResult(BaseModel):
    """Complete document-level extraction results from PyMuPDF."""

    title: str | None = Field(default=None, description="Document title from PDF metadata if declared")
    author: str | None = Field(default=None, description="Document author from PDF metadata if declared")
    subject: str | None = Field(default=None, description="Document subject from PDF metadata")
    creator: str | None = Field(default=None, description="Application that created original document")
    producer: str | None = Field(default=None, description="PDF producer or conversion software")
    creation_date: str | None = Field(default=None, description="Creation date string from PDF metadata")
    modification_date: str | None = Field(default=None, description="Modification date string from PDF metadata")
    page_count: int = Field(default=0, ge=0, description="Total pages in the PDF document")
    extracted_pages_count: int = Field(default=0, ge=0, description="Count of pages yielding readable text")
    empty_pages: list[int] = Field(default_factory=list, description="List of 1-based page numbers with no text")
    pages: list[PDFPageItem] = Field(default_factory=list, description="Page-by-page extracted records")
    combined_text: str = Field(default="", description="Combined normalized readable text from all readable pages")
    word_count: int = Field(default=0, ge=0, description="Total word count across all pages")
    character_count: int = Field(default=0, ge=0, description="Total character count across all pages")
    binary_hash: str = Field(..., description="SHA-256 hash of original PDF binary bytes")
    text_hash: str | None = Field(default=None, description="SHA-256 hash of combined clean text")
    pdf_version: str | None = Field(default=None, description="PDF specification format version")
    readability_status: str = Field(
        ...,
        description="Document readability classification ('fully_readable', 'partially_readable', 'no_extractable_text', 'empty')",
    )
    extracted_at: datetime = Field(..., description="UTC extraction timestamp")


class ProjectPDFSourceResponse(BaseModel):
    """Structured response payload returned after PDF source ingestion or duplicate resolution."""

    source_id: UUID = Field(..., description="Unique source identifier")
    project_id: UUID = Field(..., description="Associated research project identifier")
    original_filename: str = Field(..., description="Sanitized original filename of the uploaded PDF")
    source_type: str = Field(default="pdf", description="Source type ('pdf')")
    title: str = Field(..., description="Document title derived from PDF metadata or filename fallback")
    author: str | None = Field(default=None, description="Document author from metadata if present")
    ingestion_status: str = Field(..., description="Ingestion processing status ('completed', 'failed', 'pending')")
    readability_status: str = Field(
        ...,
        description="Document readability ('fully_readable', 'partially_readable', 'no_extractable_text', 'empty')",
    )
    extracted_content_id: UUID | None = Field(default=None, description="Identifier of the linked extracted_content record")
    page_count: int = Field(default=0, ge=0, description="Total pages in the PDF")
    extracted_pages_count: int = Field(default=0, ge=0, description="Count of pages with readable text")
    empty_pages: list[int] = Field(default_factory=list, description="1-based page numbers containing no readable text")
    word_count: int = Field(default=0, ge=0, description="Total word count of extracted text")
    character_count: int = Field(default=0, ge=0, description="Total character count of extracted text")
    content_hash: str = Field(..., description="SHA-256 hash of original PDF binary bytes")
    is_duplicate: bool = Field(default=False, description="Flag indicating if identical PDF was already ingested in this project")
    extracted_at: datetime = Field(..., description="UTC timestamp of extraction")
    created_at: datetime = Field(..., description="UTC timestamp of source record creation")

