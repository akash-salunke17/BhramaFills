"""Web source ingestion service orchestrating validation, extraction, and Supabase persistence."""

from datetime import datetime, timezone
import json
import logging
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import asyncpg
from fastapi import Depends

from app.core.ownership import ProjectAccessDeniedError, verify_project_ownership
from app.db.connection import DatabaseManager, get_db_manager
from app.services.sources.exceptions import (
    EmptyExtractedContentError,
    ProjectNotFoundError,
    SourceNotFoundError,
)
from app.services.sources.schemas import (
    ProjectWebSourceResponse,
    SourceDetailResponse,
    SourceSummaryResponse,
)
from app.services.web.content_extractor import WebContentExtractor
from app.services.web.safe_fetcher import SafeWebFetcher, get_safe_fetcher
from app.services.web.url_validator import URLValidator

logger = logging.getLogger("bharmafills.services.sources")


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


class WebSourceIngestionService:
    """Orchestrates web source validation, safe fetching, clean text extraction, and atomic DB storage."""

    def __init__(
        self,
        db_manager: DatabaseManager | None = None,
        fetcher: SafeWebFetcher | None = None,
    ) -> None:
        self._db_manager = db_manager or get_db_manager()
        self._fetcher = fetcher or get_safe_fetcher()

    async def validate_project_exists(
        self,
        conn: asyncpg.Connection,
        project_id: UUID,
        user_id: UUID,
    ) -> dict[str, Any]:
        """Verify that the target research project exists, is active, and owned by user.

        Raises:
            TypeError: If user_id is not a UUID instance.
            ProjectNotFoundError: If the project is not found, soft-deleted, or not owned by user_id.
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
            # Mask unauthorized/unowned projects as generic 404 to prevent resource existence disclosure
            raise ProjectNotFoundError(f"Research project '{project_id}' not found.") from exc

    async def find_existing_by_url(
        self,
        conn: asyncpg.Connection,
        project_id: UUID,
        url: str,
    ) -> dict[str, Any] | None:
        """Find an active source record matching the given project and original URL."""
        row = await conn.fetchrow(
            """
            SELECT s.id, s.project_id, s.title, s.original_url, s.ingestion_status, s.content_hash,
                   s.file_metadata, s.created_at,
                   ec.id AS extracted_content_id, ec.extracted_at, ec.extraction_metadata
            FROM public.sources s
            LEFT JOIN public.extracted_content ec ON ec.source_id = s.id
            WHERE s.project_id = $1 AND s.original_url = $2 AND s.deleted_at IS NULL
            ORDER BY ec.extracted_at DESC
            LIMIT 1;
            """,
            project_id,
            url,
        )
        return dict(row) if row else None

    async def find_existing_by_hash(
        self,
        conn: asyncpg.Connection,
        project_id: UUID,
        content_hash: str,
    ) -> dict[str, Any] | None:
        """Find an active source record matching the given project and clean text content hash."""
        row = await conn.fetchrow(
            """
            SELECT s.id, s.project_id, s.title, s.original_url, s.ingestion_status, s.content_hash,
                   s.file_metadata, s.created_at,
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

    async def ingest_web_source(
        self,
        project_id: UUID,
        url: str,
        user_id: UUID,
    ) -> ProjectWebSourceResponse:
        """Execute the end-to-end web source ingestion pipeline into Supabase.

        1. Validates target URL syntax and SSRF rules.
        2. Validates project existence and ownership in PostgreSQL.
        3. Checks for existing identical URL in this project (deduplication).
        4. Safely fetches HTML with DNS pinning and streaming bounds.
        5. Parses clean readable text, headings, word counts, and SHA-256 hash.
        6. Rejects empty extracted text.
        7. Checks for existing identical content hash in this project (content deduplication).
        8. Atomically persists records in `sources` and `extracted_content`.
        9. Returns structured summary with ingestion status and metadata.
        """
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")

        # 1. Validate URL syntax and SSRF security policy
        URLValidator.validate_url(url)

        async with self._db_manager.acquire_connection() as conn:
            # 2. Confirm project exists and is owned by caller
            await self.validate_project_exists(conn, project_id, user_id=user_id)

            # 3. Check for existing identical URL in project
            existing_by_url = await self.find_existing_by_url(conn, project_id, url)
            if existing_by_url:
                logger.info(
                    "URL '%s' already ingested for project '%s' (source ID: %s)",
                    url,
                    project_id,
                    existing_by_url["id"],
                )
                file_meta = _parse_json_field(existing_by_url.get("file_metadata"))
                return ProjectWebSourceResponse(
                    source_id=existing_by_url["id"],
                    project_id=project_id,
                    original_url=existing_by_url["original_url"],
                    final_url=file_meta.get("final_url") or existing_by_url["original_url"],
                    title=existing_by_url["title"],
                    ingestion_status=existing_by_url["ingestion_status"],
                    extracted_content_id=existing_by_url["extracted_content_id"],
                    word_count=file_meta.get("word_count", 0),
                    character_count=file_meta.get("character_count", 0),
                    content_hash=existing_by_url["content_hash"],
                    is_duplicate=True,
                    extracted_at=existing_by_url["extracted_at"] or existing_by_url["created_at"],
                    created_at=existing_by_url["created_at"],
                )

            # 4. Safely fetch HTML content
            fetched = await self._fetcher.fetch(url)

            # 5. Extract readable text, headings, metadata, and hash
            extracted = WebContentExtractor.extract(
                html=fetched.html_content,
                original_url=fetched.url,
                final_url=fetched.final_url,
                status_code=fetched.status_code,
                redirect_count=fetched.redirect_count,
            )

            # 6. Reject empty content
            if not extracted.clean_text or not extracted.clean_text.strip():
                logger.warning("Empty content extracted from URL '%s'", url)
                raise EmptyExtractedContentError("Extracted page content is empty or contains no readable text.")

            # 7. Check for duplicate content hash within project
            existing_by_hash = await self.find_existing_by_hash(conn, project_id, extracted.content_hash)
            if existing_by_hash:
                logger.info(
                    "Identical content hash '%s' already exists in project '%s' (source ID: %s)",
                    extracted.content_hash,
                    project_id,
                    existing_by_hash["id"],
                )
                file_meta = _parse_json_field(existing_by_hash.get("file_metadata"))
                return ProjectWebSourceResponse(
                    source_id=existing_by_hash["id"],
                    project_id=project_id,
                    original_url=existing_by_hash["original_url"],
                    final_url=file_meta.get("final_url") or existing_by_hash["original_url"],
                    title=existing_by_hash["title"],
                    ingestion_status=existing_by_hash["ingestion_status"],
                    extracted_content_id=existing_by_hash["extracted_content_id"],
                    word_count=file_meta.get("word_count", 0),
                    character_count=file_meta.get("character_count", 0),
                    content_hash=existing_by_hash["content_hash"],
                    is_duplicate=True,
                    extracted_at=existing_by_hash["extracted_at"] or existing_by_hash["created_at"],
                    created_at=existing_by_hash["created_at"],
                )

            # 8. Prepare metadata and title for insertion
            clean_title = (extracted.title or "").strip()
            if not clean_title:
                clean_title = urlparse(extracted.final_url).netloc or "Web Source"
            # Ensure VARCHAR(255) constraint
            clean_title = clean_title[:255]

            file_metadata = {
                "final_url": extracted.final_url,
                "status_code": extracted.status_code,
                "redirect_count": extracted.redirect_count,
                "language": extracted.language,
                "canonical_url": extracted.canonical_url,
                "meta_description": extracted.meta_description,
                "author": extracted.author,
                "word_count": extracted.word_count,
                "character_count": extracted.character_count,
            }

            extraction_metadata = {
                "headings": [h.model_dump() for h in extracted.headings],
                "paragraphs_count": len(extracted.paragraphs),
                "canonical_url": extracted.canonical_url,
                "language": extracted.language,
                "meta_description": extracted.meta_description,
                "author": extracted.author,
            }

            # Atomic transaction to insert sources and extracted_content
            async with conn.transaction():
                source_row = await conn.fetchrow(
                    """
                    INSERT INTO public.sources (
                        project_id,
                        source_type,
                        title,
                        original_url,
                        file_metadata,
                        ingestion_status,
                        content_hash
                    )
                    VALUES ($1, 'url', $2, $3, $4::jsonb, 'completed', $5)
                    RETURNING id, created_at;
                    """,
                    project_id,
                    clean_title,
                    url,
                    json.dumps(file_metadata),
                    extracted.content_hash,
                )
                source_id = source_row["id"]
                source_created_at = source_row["created_at"]

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
                    VALUES ($1, $2, $3::jsonb, 'beautifulsoup4', '1.0', $4)
                    RETURNING id;
                    """,
                    source_id,
                    extracted.clean_text,
                    json.dumps(extraction_metadata),
                    extracted.extracted_at,
                )
                extracted_content_id = content_row["id"]

            logger.info(
                "Successfully persisted web source '%s' (content ID: %s) for project '%s'",
                source_id,
                extracted_content_id,
                project_id,
            )

            return ProjectWebSourceResponse(
                source_id=source_id,
                project_id=project_id,
                original_url=url,
                final_url=extracted.final_url,
                title=clean_title,
                ingestion_status="completed",
                extracted_content_id=extracted_content_id,
                word_count=extracted.word_count,
                character_count=extracted.character_count,
                content_hash=extracted.content_hash,
                is_duplicate=False,
                extracted_at=extracted.extracted_at,
                created_at=source_created_at,
            )

    async def list_project_sources(
        self,
        project_id: UUID,
        user_id: UUID,
    ) -> list[SourceSummaryResponse]:
        """Fetch all non-deleted sources for a research project."""
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")

        async with self._db_manager.acquire_connection() as conn:
            await self.validate_project_exists(conn, project_id, user_id=user_id)

            rows = await conn.fetch(
                """
                SELECT s.id, s.project_id, s.source_type, s.title, s.original_url, s.original_filename,
                       s.ingestion_status, s.content_hash, s.file_metadata, s.created_at, s.updated_at
                FROM public.sources s
                WHERE s.project_id = $1 AND s.deleted_at IS NULL
                ORDER BY s.created_at DESC;
                """,
                project_id,
            )

            results = []
            for row in rows:
                meta = _parse_json_field(row["file_metadata"])
                results.append(
                    SourceSummaryResponse(
                        id=row["id"],
                        project_id=row["project_id"],
                        source_type=row["source_type"],
                        title=row["title"],
                        original_url=row["original_url"],
                        original_filename=row["original_filename"],
                        ingestion_status=row["ingestion_status"],
                        content_hash=row["content_hash"],
                        word_count=meta.get("word_count", 0),
                        character_count=meta.get("character_count", 0),
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )
                )
            return results

    async def get_project_source_detail(
        self,
        project_id: UUID,
        source_id: UUID,
        user_id: UUID,
    ) -> SourceDetailResponse:
        """Fetch full details and extracted content for a specific project source."""
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")

        async with self._db_manager.acquire_connection() as conn:
            await self.validate_project_exists(conn, project_id, user_id=user_id)

            row = await conn.fetchrow(
                """
                SELECT s.id, s.project_id, s.source_type, s.title, s.original_url, s.original_filename,
                       s.file_metadata, s.ingestion_status, s.content_hash, s.created_at, s.updated_at,
                       ec.id AS extracted_content_id, ec.extracted_text, ec.extraction_metadata,
                       ec.extraction_method, ec.extraction_version, ec.extracted_at
                FROM public.sources s
                LEFT JOIN public.extracted_content ec ON ec.source_id = s.id
                WHERE s.id = $1 AND s.project_id = $2 AND s.deleted_at IS NULL
                ORDER BY ec.extracted_at DESC
                LIMIT 1;
                """,
                source_id,
                project_id,
            )
            if not row:
                logger.warning("Source '%s' not found in project '%s'", source_id, project_id)
                raise SourceNotFoundError(f"Source '{source_id}' not found in project '{project_id}'.")

            file_meta = _parse_json_field(row["file_metadata"])
            ext_meta = _parse_json_field(row["extraction_metadata"])

            return SourceDetailResponse(
                id=row["id"],
                project_id=row["project_id"],
                source_type=row["source_type"],
                title=row["title"],
                original_url=row["original_url"],
                original_filename=row["original_filename"],
                file_metadata=file_meta,
                ingestion_status=row["ingestion_status"],
                content_hash=row["content_hash"],
                extracted_content_id=row["extracted_content_id"],
                extracted_text=row["extracted_text"],
                extraction_metadata=ext_meta,
                extraction_method=row["extraction_method"],
                extraction_version=row["extraction_version"],
                extracted_at=row["extracted_at"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )


def get_web_source_service(
    db_manager: DatabaseManager = Depends(get_db_manager),
    fetcher: SafeWebFetcher = Depends(get_safe_fetcher),
) -> WebSourceIngestionService:
    """Dependency provider for WebSourceIngestionService."""
    return WebSourceIngestionService(db_manager=db_manager, fetcher=fetcher)
