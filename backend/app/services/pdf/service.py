"""PDF source ingestion service coordinating validation, PyMuPDF extraction, and database persistence."""

from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import Depends
import pymupdf

from app.core.config import Settings, get_settings
from app.core.ownership import ProjectAccessDeniedError, verify_project_ownership
from app.db.connection import DatabaseManager, get_db_manager
from app.services.pdf.extractor import PDFExtractor
from app.services.pdf.schemas import ProjectPDFSourceResponse
from app.services.pdf.validator import PDFValidator
from app.services.sources.exceptions import ProjectNotFoundError

logger = logging.getLogger("bharmafills.services.pdf.service")


def _parse_json_field(val: Any) -> dict[str, Any]:
    """Safely decode JSONB field returned by asyncpg into a dictionary."""
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {}
    return {}


class PDFSourceIngestionService:
    """Orchestrates PDF validation, PyMuPDF extraction, duplicate resolution, and Supabase persistence."""

    def __init__(
        self,
        db_manager: DatabaseManager | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._db_manager = db_manager or get_db_manager()
        self._settings = settings or get_settings()

    async def validate_project_exists(
        self,
        conn: asyncpg.Connection,
        project_id: UUID,
        user_id: UUID,
    ) -> dict[str, Any]:
        """Verify that the target research project exists, is active, and owned by user.

        Raises:
            TypeError: If user_id is not a UUID instance.
            ProjectNotFoundError: If the project does not exist, is soft-deleted, or not owned by user_id.
        """
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")

        try:
            context = await verify_project_ownership(conn, project_id, user_id)
            return {
                "id": context.id,
                "user_id": context.user_id,
                "title": context.title,
                "status": context.status,
            }
        except ProjectAccessDeniedError as exc:
            raise ProjectNotFoundError(f"Research project '{project_id}' not found.") from exc

    async def find_existing_by_hash(
        self,
        conn: asyncpg.Connection,
        project_id: UUID,
        content_hash: str,
    ) -> dict[str, Any] | None:
        """Find an active PDF source record matching the given project and binary content hash."""
        row = await conn.fetchrow(
            """
            SELECT s.id, s.project_id, s.title, s.original_filename, s.source_type, s.ingestion_status,
                   s.content_hash, s.file_metadata, s.created_at,
                   ec.id AS extracted_content_id, ec.extracted_at, ec.extraction_metadata
            FROM public.sources s
            LEFT JOIN public.extracted_content ec ON ec.source_id = s.id
            WHERE s.project_id = $1 AND s.content_hash = $2 AND s.deleted_at IS NULL
            ORDER BY ec.extracted_at DESC
            LIMIT 1;
            """,
            project_id,
            content_hash,
        )
        return dict(row) if row else None

    async def ingest_pdf(
        self,
        project_id: UUID,
        filename: str | None,
        content_type: str | None,
        pdf_bytes: bytes,
        user_id: UUID,
    ) -> ProjectPDFSourceResponse:
        """Execute the end-to-end PDF validation, extraction, and Supabase storage pipeline.

        1. Validates upload Content-Type header.
        2. Validates byte length and magic signature (%PDF-).
        3. Sanitizes original filename.
        4. Calculates SHA-256 binary hash.
        5. Validates project existence and caller ownership in PostgreSQL.
        6. Checks for duplicate identical PDF in this project (binary deduplication).
        7. Parses clean text, metadata, page numbers (1-based), and checks readability.
        8. Atomically records source metadata and extracted content in Supabase.
        9. Returns structured summary.
        """
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")

        # 1. Validate MIME type
        PDFValidator.validate_mime_type(content_type)

        # 2. Validate byte bounds and signature
        PDFValidator.validate_signature_and_size(
            pdf_bytes=pdf_bytes,
            max_bytes=self._settings.PDF_MAX_UPLOAD_BYTES,
        )

        # 3. Sanitize filename
        sanitized_filename = PDFValidator.sanitize_filename(filename)

        # 4. Authoritative binary hash of original PDF bytes
        binary_hash = hashlib.sha256(pdf_bytes).hexdigest()

        # 5. Validate PDF structure, encryption, page limits, and extract text
        extracted = PDFExtractor.extract(
            pdf_bytes=pdf_bytes,
            max_pages=self._settings.PDF_MAX_PAGES,
        )

        async with self._db_manager.acquire_connection() as conn:
            # 6. Validate project existence and ownership
            await self.validate_project_exists(conn, project_id, user_id=user_id)

            # 7. Check for duplicate upload in same project
            existing_duplicate = await self.find_existing_by_hash(conn, project_id, binary_hash)
            if existing_duplicate:
                logger.info(
                    "Duplicate PDF binary '%s' already ingested in project '%s' (source ID: %s)",
                    binary_hash[:8],
                    project_id,
                    existing_duplicate["id"],
                )
                file_meta = _parse_json_field(existing_duplicate.get("file_metadata"))
                return ProjectPDFSourceResponse(
                    source_id=existing_duplicate["id"],
                    project_id=project_id,
                    original_filename=existing_duplicate["original_filename"] or sanitized_filename,
                    source_type="pdf",
                    title=existing_duplicate["title"],
                    author=file_meta.get("author"),
                    ingestion_status=existing_duplicate["ingestion_status"],
                    readability_status=file_meta.get("readability_status", "fully_readable"),
                    extracted_content_id=existing_duplicate["extracted_content_id"],
                    page_count=file_meta.get("page_count", 0),
                    extracted_pages_count=file_meta.get("extracted_pages_count", 0),
                    empty_pages=file_meta.get("empty_pages", []),
                    word_count=file_meta.get("word_count", 0),
                    character_count=file_meta.get("character_count", 0),
                    content_hash=existing_duplicate["content_hash"],
                    is_duplicate=True,
                    extracted_at=existing_duplicate["extracted_at"] or existing_duplicate["created_at"],
                    created_at=existing_duplicate["created_at"],
                )

            # Determine title: prefer document title from metadata, fallback to sanitized filename
            clean_title = (extracted.title or "").strip()
            if not clean_title:
                clean_title = sanitized_filename
            clean_title = clean_title[:255]

            # Ingestion classification
            if extracted.readability_status == "no_extractable_text":
                ingestion_status = "failed"
                error_message = "Document contains no extractable embedded text (scanned or image-only PDF). OCR is not supported."
            else:
                ingestion_status = "completed"
                error_message = None

            file_metadata = {
                "file_size_bytes": len(pdf_bytes),
                "page_count": extracted.page_count,
                "extracted_pages_count": extracted.extracted_pages_count,
                "empty_pages": extracted.empty_pages,
                "word_count": extracted.word_count,
                "character_count": extracted.character_count,
                "readability_status": extracted.readability_status,
                "author": extracted.author,
                "subject": extracted.subject,
                "creator": extracted.creator,
                "producer": extracted.producer,
                "creation_date": extracted.creation_date,
                "modification_date": extracted.modification_date,
                "pdf_version": extracted.pdf_version,
                "text_hash": extracted.text_hash,
                "binary_hash": extracted.binary_hash,
            }

            # 8. Atomic transaction inserting into sources and extracted_content
            async with conn.transaction():
                source_row = await conn.fetchrow(
                    """
                    INSERT INTO public.sources (
                        project_id,
                        source_type,
                        title,
                        original_filename,
                        file_metadata,
                        ingestion_status,
                        error_message,
                        content_hash
                    )
                    VALUES ($1, 'pdf', $2, $3, $4::jsonb, $5, $6, $7)
                    RETURNING id, created_at;
                    """,
                    project_id,
                    clean_title,
                    sanitized_filename,
                    json.dumps(file_metadata),
                    ingestion_status,
                    error_message,
                    extracted.binary_hash,
                )
                source_id = source_row["id"]
                source_created_at = source_row["created_at"]

                extracted_content_id = None
                # Only insert into extracted_content if there is readable text satisfying chk_extracted_content_text_not_empty
                if extracted.combined_text and extracted.combined_text.strip():
                    extraction_metadata = {
                        "page_count": extracted.page_count,
                        "extracted_pages_count": extracted.extracted_pages_count,
                        "empty_pages": extracted.empty_pages,
                        "pages": [p.model_dump() for p in extracted.pages],
                        "author": extracted.author,
                        "subject": extracted.subject,
                        "pdf_version": extracted.pdf_version,
                        "text_hash": extracted.text_hash,
                        "binary_hash": extracted.binary_hash,
                        "readability_status": extracted.readability_status,
                    }

                    content_row = await conn.fetchrow(
                        """
                        INSERT INTO public.extracted_content (
                            source_id,
                            extracted_text,
                            extraction_metadata,
                            extraction_method,
                            extraction_version,
                            extracted_at
                        )
                        VALUES ($1, $2, $3::jsonb, 'pymupdf', $4, $5)
                        RETURNING id;
                        """,
                        source_id,
                        extracted.combined_text,
                        json.dumps(extraction_metadata),
                        pymupdf.__version__,
                        extracted.extracted_at,
                    )
                    extracted_content_id = content_row["id"]

            logger.info(
                "Successfully persisted PDF source '%s' (content ID: %s, %s) for project '%s'",
                source_id,
                extracted_content_id,
                extracted.readability_status,
                project_id,
            )

            return ProjectPDFSourceResponse(
                source_id=source_id,
                project_id=project_id,
                original_filename=sanitized_filename,
                source_type="pdf",
                title=clean_title,
                author=extracted.author,
                ingestion_status=ingestion_status,
                readability_status=extracted.readability_status,
                extracted_content_id=extracted_content_id,
                page_count=extracted.page_count,
                extracted_pages_count=extracted.extracted_pages_count,
                empty_pages=extracted.empty_pages,
                word_count=extracted.word_count,
                character_count=extracted.character_count,
                content_hash=extracted.binary_hash,
                is_duplicate=False,
                extracted_at=extracted.extracted_at,
                created_at=source_created_at,
            )


def get_pdf_source_service(
    db_manager: DatabaseManager = Depends(get_db_manager),
    settings: Settings = Depends(get_settings),
) -> PDFSourceIngestionService:
    """Dependency provider for PDFSourceIngestionService."""
    return PDFSourceIngestionService(db_manager=db_manager, settings=settings)
