"""Information Gap Database Persistence Service for Bharmafills.

Manages transactional persistence, idempotent storage, review updates, and project-scoped
retrieval of validated information gap findings in `public.information_gaps`.

Key Architectural Guarantees:
1. Strict Ownership Enforcement: Mandatory `user_id: UUID` validated on every operation;
   verifies project ownership via `verify_project_ownership` inside the database connection.
   Nonexistent, unowned, and foreign-owned projects uniformly return generic `ProjectNotFoundError`
   (HTTP 404 IDOR masking).
2. Deterministic Idempotency & Duplicate Prevention: Stable cryptographic SHA-256 fingerprint
   computed from `(project_id, normalized_target_subquestion, normalized_gap_description, gap_subtype)`.
   Detection reruns update detection metrics without creating duplicate rows, resetting user review
   status (`open`, `investigating`, `resolved`, `dismissed`), or erasing user review notes.
3. Namespaced JSONB Metadata: Structured `confidence_metadata->'bharmafills'` namespace preserving
   unknown pre-existing keys, separating detection metadata from user review decisions.
4. Transactional Atomicity: Project-level advisory transaction lock (`pg_advisory_xact_lock`)
   serializes concurrent execution per project and guarantees atomic batch persistence.
5. Topic & Evidence Reference Integrity: Verifies referenced topics and evidence items belong
   to the active project, safely setting `topic_id = NULL` for unmapped or foreign topic names.
6. Zero API / UI Dependencies: Decoupled service layer callable by FastAPI handlers in Step 10D.2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import logging
from typing import Any, Sequence
from uuid import UUID, uuid4

import asyncpg

from app.core.config import Settings, get_settings
from app.core.ownership import (
    OwnedProjectContext,
    ProjectAccessDeniedError,
    ProjectNotFoundError,
    ResourceMismatchError,
    verify_gap_belongs_to_project,
    verify_project_ownership,
)
from app.db.connection import (
    DatabaseManager,
    DatabaseNotConfiguredError,
    DatabaseUnavailableError,
    get_db_manager,
)
from app.services.ai.gap_schemas import (
    GapDetectionResult,
    GapPriority,
    GapReviewStatus,
    GapReviewUpdate,
    GapStatus,
    GapType,
    InformationGapListResponse,
    InformationGapResponse,
    PersistedGapBatchResponse,
    ValidatedGapFinding,
)

logger = logging.getLogger("bharmafills.services.ai.gap_persistence")


# =============================================================================
# Domain Exceptions
# =============================================================================

class GapPersistenceError(Exception):
    """Base exception for information gap persistence operations."""

    def __init__(self, message: str = "Persistence error occurred.", project_id: UUID | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.project_id = project_id


class GapNotFoundError(ProjectNotFoundError):
    """Raised when an information gap does not exist in the specified research project."""

    def __init__(
        self,
        message: str = "Information gap not found.",
        gap_id: UUID | None = None,
        project_id: UUID | None = None,
    ) -> None:
        super().__init__(message=message, project_id=project_id, status_code=404)
        self.gap_id = gap_id
        self.error_code = "GAP_NOT_FOUND"


class GapTransactionError(GapPersistenceError):
    """Raised when a transactional persistence operation fails unexpectedly."""


# =============================================================================
# Utility & Serialization Helpers
# =============================================================================

def compute_gap_fingerprint(
    project_id: UUID,
    target_subquestion: str,
    gap_description: str,
    gap_subtype: str,
) -> str:
    """Compute a deterministic, stable SHA-256 fingerprint for a candidate information gap.

    Normalizes whitespace and casing to guarantee consistent duplicate detection across reruns.
    """
    norm_subq = " ".join(target_subquestion.strip().lower().split())
    norm_desc = " ".join(gap_description.strip().lower().split())
    norm_subtype = gap_subtype.strip().lower()
    raw = f"{project_id}:{norm_subq}:{norm_desc}:{norm_subtype}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_json(val: Any, default: Any = None) -> Any:
    """Parse JSON field if returned as a string from asyncpg, or return directly."""
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return default
    return default


def _pad_min_len(text: str, min_len: int = 5) -> str:
    """Ensure string satisfies database check constraint minimum length."""
    trimmed = text.strip()
    if len(trimmed) >= min_len:
        return trimmed
    return trimmed.ljust(min_len, ".")


# =============================================================================
# Core Gap Persistence Service
# =============================================================================

class GapPersistenceService:
    """Manages transactional persistence, idempotent storage, review updates, and project retrieval of information gaps."""

    def __init__(
        self,
        db_manager: DatabaseManager | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._db_manager = db_manager or get_db_manager()

    @property
    def is_configured(self) -> bool:
        """Return True if database connection is configured."""
        return self._db_manager.is_configured

    async def persist_detection_result(
        self,
        project_id: UUID,
        user_id: UUID,
        detection_result: GapDetectionResult,
    ) -> PersistedGapBatchResponse:
        """Persist validated gap findings into `public.information_gaps` transactionally and idempotently.

        Args:
            project_id: Target project UUID.
            user_id: Authenticated caller UUID.
            detection_result: Output envelope from InformationGapDetectionService.

        Returns:
            PersistedGapBatchResponse summarizing inserted, updated, and preserved records.

        Raises:
            TypeError: If project_id or user_id is not a UUID instance, or result is invalid.
            ValueError: If detection_result.project_id does not match project_id.
            ProjectNotFoundError: If the project does not exist, is soft-deleted, or not owned.
            GapTransactionError: If the database transaction fails.
        """
        # 1. Type and boundary validation
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")
        if not isinstance(project_id, UUID):
            raise TypeError(f"project_id must be a UUID instance, got {type(project_id).__name__}")
        if not isinstance(detection_result, GapDetectionResult):
            raise TypeError(
                f"detection_result must be a GapDetectionResult instance, got {type(detection_result).__name__}"
            )
        if detection_result.project_id != project_id:
            raise ValueError(
                f"detection_result project_id '{detection_result.project_id}' does not match target project_id '{project_id}'."
            )

        # 2. Acquire connection & verify ownership
        async with self._db_manager.acquire_connection() as conn:
            try:
                await verify_project_ownership(conn, project_id, user_id)
            except ProjectAccessDeniedError as exc:
                logger.warning("Ownership access denied for project %s by user %s", project_id, user_id)
                raise ProjectNotFoundError(f"Research project '{project_id}' was not found.", project_id=project_id) from exc

            # 3. Transactional persistence with advisory lock
            async with conn.transaction():
                try:
                    # Project-scoped advisory transaction lock to serialize concurrent reruns
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtext('bharmafills_gap_persistence_' || $1::text));",
                        project_id,
                    )

                    # Retrieve valid project topics
                    topic_rows = await conn.fetch(
                        "SELECT id, name FROM public.topics WHERE project_id = $1;",
                        project_id,
                    )
                    topic_by_name = {r["name"].strip().lower(): r["id"] for r in topic_rows}

                    # Retrieve valid project evidence IDs for reference sanitation
                    evidence_rows = await conn.fetch(
                        "SELECT id FROM public.evidence WHERE project_id = $1;",
                        project_id,
                    )
                    valid_evidence_ids = {r["id"] for r in evidence_rows}

                    # Retrieve existing gaps for this project
                    existing_rows = await conn.fetch(
                        """
                        SELECT id, project_id, topic_id, gap_description, explanation, suggested_query,
                               priority, status, gap_type, confidence_metadata, created_at, updated_at
                        FROM public.information_gaps
                        WHERE project_id = $1;
                        """,
                        project_id,
                    )

                    existing_by_fp: dict[str, dict[str, Any]] = {}
                    for r in existing_rows:
                        row_dict = dict(r)
                        meta = _parse_json(row_dict.get("confidence_metadata"), default={})
                        if isinstance(meta, dict):
                            bharmafills_meta = meta.get("bharmafills")
                            if isinstance(bharmafills_meta, dict):
                                fp = bharmafills_meta.get("fingerprint")
                                if fp and isinstance(fp, str):
                                    existing_by_fp[fp] = row_dict

                    inserted_count = 0
                    updated_count = 0

                    for finding in detection_result.gaps:
                        cand = finding.candidate
                        fp = compute_gap_fingerprint(
                            project_id=project_id,
                            target_subquestion=cand.target_subquestion,
                            gap_description=cand.gap_description,
                            gap_subtype=cand.gap_subtype.value,
                        )

                        # Match topic name to project topic ID safely
                        matched_topic_id = None
                        if cand.related_topic_name:
                            matched_topic_id = topic_by_name.get(cand.related_topic_name.strip().lower())

                        # Sanitize evidence IDs strictly against verified project evidence
                        sanitized_evidence_ids = [
                            str(eid) for eid in finding.covered_evidence_ids if eid in valid_evidence_ids
                        ]

                        if fp in existing_by_fp:
                            # Idempotent update: preserve database UUID, created_at, status, user notes, and unknown keys
                            existing = existing_by_fp[fp]
                            gap_id = existing["id"]

                            existing_meta = _parse_json(existing.get("confidence_metadata"), default={})
                            if not isinstance(existing_meta, dict):
                                existing_meta = {}
                            existing_bharmafills = existing_meta.get("bharmafills") or {}
                            if not isinstance(existing_bharmafills, dict):
                                existing_bharmafills = {}
                            existing_user_review = existing_bharmafills.get("user_review")

                            # Preserve existing custom keys while updating bharmafills detection namespace
                            new_meta = dict(existing_meta)
                            updated_bharmafills = {
                                "schema_version": 1,
                                "fingerprint": fp,
                                "target_subquestion": cand.target_subquestion,
                                "gap_subtype": cand.gap_subtype.value,
                                "validation_verdict": finding.validation_verdict,
                                "grounding_notes": finding.grounding_notes,
                                "covered_evidence_ids": sanitized_evidence_ids,
                                "corpus_truncation_warning": finding.corpus_truncation_warning,
                                "source_omission_warning": finding.source_omission_warning,
                                "ai_confidence": round(cand.confidence_score, 3),
                                "ai_reasoning": cand.reasoning,
                            }
                            if existing_user_review is not None:
                                updated_bharmafills["user_review"] = existing_user_review
                            new_meta["bharmafills"] = updated_bharmafills

                            await conn.execute(
                                """
                                UPDATE public.information_gaps
                                SET topic_id = $1,
                                    gap_description = $2,
                                    explanation = $3,
                                    suggested_query = $4,
                                    priority = $5,
                                    gap_type = $6,
                                    confidence_metadata = $7::jsonb,
                                    updated_at = now()
                                WHERE id = $8 AND project_id = $9;
                                """,
                                matched_topic_id,
                                _pad_min_len(cand.gap_description, 5),
                                cand.explanation,
                                cand.suggested_query,
                                cand.priority.value,
                                cand.gap_type.value,
                                json.dumps(new_meta),
                                gap_id,
                                project_id,
                            )
                            updated_count += 1
                        else:
                            # New gap finding insertion
                            new_gap_id = uuid4()
                            new_meta = {
                                "bharmafills": {
                                    "schema_version": 1,
                                    "fingerprint": fp,
                                    "target_subquestion": cand.target_subquestion,
                                    "gap_subtype": cand.gap_subtype.value,
                                    "validation_verdict": finding.validation_verdict,
                                    "grounding_notes": finding.grounding_notes,
                                    "covered_evidence_ids": sanitized_evidence_ids,
                                    "corpus_truncation_warning": finding.corpus_truncation_warning,
                                    "source_omission_warning": finding.source_omission_warning,
                                    "ai_confidence": round(cand.confidence_score, 3),
                                    "ai_reasoning": cand.reasoning,
                                    "user_review": None,
                                }
                            }

                            await conn.execute(
                                """
                                INSERT INTO public.information_gaps (
                                    id, project_id, topic_id, gap_description, explanation,
                                    suggested_query, priority, status, gap_type,
                                    confidence_metadata, created_at, updated_at
                                )
                                VALUES (
                                    $1, $2, $3, $4, $5,
                                    $6, $7, 'open', $8,
                                    $9::jsonb, now(), now()
                                );
                                """,
                                new_gap_id,
                                project_id,
                                matched_topic_id,
                                _pad_min_len(cand.gap_description, 5),
                                cand.explanation,
                                cand.suggested_query,
                                cand.priority.value,
                                cand.gap_type.value,
                                json.dumps(new_meta),
                            )
                            inserted_count += 1

                    # Fetch current project gaps in deterministic priority/creation order
                    final_rows = await conn.fetch(
                        """
                        SELECT id, project_id, topic_id, gap_description, explanation, suggested_query,
                               priority, status, gap_type, confidence_metadata, created_at, updated_at
                        FROM public.information_gaps
                        WHERE project_id = $1
                        ORDER BY CASE priority
                            WHEN 'critical' THEN 1
                            WHEN 'high' THEN 2
                            WHEN 'medium' THEN 3
                            WHEN 'low' THEN 4
                            ELSE 5 END ASC,
                            created_at ASC, id ASC;
                        """,
                        project_id,
                    )

                    persisted_gaps: list[InformationGapResponse] = []
                    for r in final_rows:
                        d = dict(r)
                        d["confidence_metadata"] = _parse_json(d.get("confidence_metadata"), default={})
                        persisted_gaps.append(InformationGapResponse(**d))

                    preserved_count = max(0, len(existing_rows) - updated_count)

                    return PersistedGapBatchResponse(
                        project_id=project_id,
                        total_findings_evaluated=len(detection_result.gaps),
                        total_persisted=inserted_count + updated_count,
                        inserted_count=inserted_count,
                        updated_count=updated_count,
                        preserved_count=preserved_count,
                        gaps=persisted_gaps,
                        persisted_at=datetime.now(timezone.utc),
                    )

                except Exception as exc:
                    logger.error("Transactional gap persistence failed for project %s: %s", project_id, type(exc).__name__)
                    raise GapTransactionError(f"Failed to persist gap batch: {type(exc).__name__}") from exc

    async def list_project_gaps(
        self,
        project_id: UUID,
        user_id: UUID,
        status: GapStatus | str | None = None,
        priority: GapPriority | str | None = None,
        gap_type: GapType | str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[InformationGapResponse]:
        """List information gaps for an owned research project with optional filtering and pagination.

        Args:
            project_id: Target project UUID.
            user_id: Authenticated caller UUID.
            status: Optional lifecycle status filter.
            priority: Optional priority filter.
            gap_type: Optional gap type filter.
            limit: Maximum items to return (1-200, default 50).
            offset: Number of items to skip (default 0).

        Returns:
            List of InformationGapResponse entities in deterministic order.

        Raises:
            TypeError: If project_id or user_id is not a UUID instance.
            ProjectNotFoundError: If the project does not exist or caller does not own it.
        """
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")
        if not isinstance(project_id, UUID):
            raise TypeError(f"project_id must be a UUID instance, got {type(project_id).__name__}")

        limit = max(1, min(limit, 200))
        offset = max(0, offset)

        status_val = status.value if isinstance(status, GapStatus) else (status if status else None)
        priority_val = priority.value if isinstance(priority, GapPriority) else (priority if priority else None)
        type_val = gap_type.value if isinstance(gap_type, GapType) else (gap_type if gap_type else None)

        async with self._db_manager.acquire_connection() as conn:
            try:
                await verify_project_ownership(conn, project_id, user_id)
            except ProjectAccessDeniedError as exc:
                logger.warning("Ownership access denied for project %s by user %s", project_id, user_id)
                raise ProjectNotFoundError(f"Research project '{project_id}' was not found.", project_id=project_id) from exc

            rows = await conn.fetch(
                """
                SELECT id, project_id, topic_id, gap_description, explanation, suggested_query,
                       priority, status, gap_type, confidence_metadata, created_at, updated_at
                FROM public.information_gaps
                WHERE project_id = $1
                  AND ($2::text IS NULL OR status = $2)
                  AND ($3::text IS NULL OR priority = $3)
                  AND ($4::text IS NULL OR gap_type = $4)
                ORDER BY CASE priority
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    WHEN 'low' THEN 4
                    ELSE 5 END ASC,
                    created_at ASC, id ASC
                LIMIT $5 OFFSET $6;
                """,
                project_id,
                status_val,
                priority_val,
                type_val,
                limit,
                offset,
            )

            results: list[InformationGapResponse] = []
            for r in rows:
                d = dict(r)
                d["confidence_metadata"] = _parse_json(d.get("confidence_metadata"), default={})
                results.append(InformationGapResponse(**d))
            return results

    async def count_project_gaps(
        self,
        project_id: UUID,
        user_id: UUID,
        status: GapStatus | str | None = None,
        priority: GapPriority | str | None = None,
        gap_type: GapType | str | None = None,
    ) -> int:
        """Count total matching information gaps for an owned research project.

        Args:
            project_id: Target project UUID.
            user_id: Authenticated caller UUID.
            status: Optional lifecycle status filter.
            priority: Optional priority filter.
            gap_type: Optional gap type filter.

        Returns:
            Integer total matching gap count.

        Raises:
            TypeError: If project_id or user_id is not a UUID instance.
            ProjectNotFoundError: If the project does not exist or caller does not own it.
        """
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")
        if not isinstance(project_id, UUID):
            raise TypeError(f"project_id must be a UUID instance, got {type(project_id).__name__}")

        status_val = status.value if isinstance(status, GapStatus) else (status if status else None)
        priority_val = priority.value if isinstance(priority, GapPriority) else (priority if priority else None)
        type_val = gap_type.value if isinstance(gap_type, GapType) else (gap_type if gap_type else None)

        async with self._db_manager.acquire_connection() as conn:
            try:
                await verify_project_ownership(conn, project_id, user_id)
            except ProjectAccessDeniedError as exc:
                logger.warning("Ownership access denied for project %s by user %s", project_id, user_id)
                raise ProjectNotFoundError(f"Research project '{project_id}' was not found.", project_id=project_id) from exc

            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS total
                FROM public.information_gaps
                WHERE project_id = $1
                  AND ($2::text IS NULL OR status = $2)
                  AND ($3::text IS NULL OR priority = $3)
                  AND ($4::text IS NULL OR gap_type = $4);
                """,
                project_id,
                status_val,
                priority_val,
                type_val,
            )
            return int(row["total"]) if row else 0

    async def get_project_gap(
        self,
        project_id: UUID,
        gap_id: UUID,
        user_id: UUID,
    ) -> InformationGapResponse:
        """Retrieve a single information gap by UUID within an owned research project.

        Args:
            project_id: Target project UUID.
            gap_id: Information gap UUID.
            user_id: Authenticated caller UUID.

        Returns:
            InformationGapResponse entity.

        Raises:
            TypeError: If any identifier is not a UUID instance.
            ProjectNotFoundError: If project is not found, not owned, or gap does not belong to project.
        """
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")
        if not isinstance(project_id, UUID):
            raise TypeError(f"project_id must be a UUID instance, got {type(project_id).__name__}")
        if not isinstance(gap_id, UUID):
            raise TypeError(f"gap_id must be a UUID instance, got {type(gap_id).__name__}")

        async with self._db_manager.acquire_connection() as conn:
            try:
                await verify_project_ownership(conn, project_id, user_id)
            except ProjectAccessDeniedError as exc:
                logger.warning("Ownership access denied for project %s by user %s", project_id, user_id)
                raise ProjectNotFoundError(f"Research project '{project_id}' was not found.", project_id=project_id) from exc

            row = await conn.fetchrow(
                """
                SELECT id, project_id, topic_id, gap_description, explanation, suggested_query,
                       priority, status, gap_type, confidence_metadata, created_at, updated_at
                FROM public.information_gaps
                WHERE id = $1 AND project_id = $2;
                """,
                gap_id,
                project_id,
            )
            if not row:
                raise GapNotFoundError(
                    f"Information gap '{gap_id}' was not found in project '{project_id}'.",
                    gap_id=gap_id,
                    project_id=project_id,
                )

            d = dict(row)
            d["confidence_metadata"] = _parse_json(d.get("confidence_metadata"), default={})
            return InformationGapResponse(**d)

    async def update_gap_review(
        self,
        project_id: UUID,
        gap_id: UUID,
        user_id: UUID,
        update_data: GapReviewUpdate,
    ) -> InformationGapResponse:
        """Update user review status and notes on an existing information gap.

        Strict Boundaries:
        - Only updates `status`, `user_review` inside `confidence_metadata`, and `updated_at`.
        - Detection metadata (`gap_subtype`, `validation_verdict`, `grounding_notes`, `ai_confidence`, etc.)
          and entity metadata (`project_id`, `gap_description`, `priority`, `gap_type`) cannot be modified.
        - Preserves all unknown pre-existing top-level JSONB keys.

        Args:
            project_id: Target project UUID.
            gap_id: Target information gap UUID.
            user_id: Authenticated caller UUID.
            update_data: Validated GapReviewUpdate payload.

        Returns:
            Updated InformationGapResponse entity.

        Raises:
            TypeError: If any identifier is not a UUID instance or update_data is invalid.
            ProjectNotFoundError: If project is not found, not owned, or gap does not belong to project.
        """
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")
        if not isinstance(project_id, UUID):
            raise TypeError(f"project_id must be a UUID instance, got {type(project_id).__name__}")
        if not isinstance(gap_id, UUID):
            raise TypeError(f"gap_id must be a UUID instance, got {type(gap_id).__name__}")
        if not isinstance(update_data, GapReviewUpdate):
            raise TypeError(f"update_data must be a GapReviewUpdate instance, got {type(update_data).__name__}")

        async with self._db_manager.acquire_connection() as conn:
            try:
                await verify_project_ownership(conn, project_id, user_id)
            except ProjectAccessDeniedError as exc:
                logger.warning("Ownership access denied for project %s by user %s", project_id, user_id)
                raise ProjectNotFoundError(f"Research project '{project_id}' was not found.", project_id=project_id) from exc

            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT id, project_id, topic_id, gap_description, explanation, suggested_query,
                           priority, status, gap_type, confidence_metadata, created_at, updated_at
                    FROM public.information_gaps
                    WHERE id = $1 AND project_id = $2
                    FOR UPDATE;
                    """,
                    gap_id,
                    project_id,
                )
                if not row:
                    raise GapNotFoundError(
                        f"Information gap '{gap_id}' was not found in project '{project_id}'.",
                        gap_id=gap_id,
                        project_id=project_id,
                    )

                meta = _parse_json(row["confidence_metadata"], default={})
                if not isinstance(meta, dict):
                    meta = {}
                new_meta = dict(meta)
                bharmafills_meta = new_meta.get("bharmafills") or {}
                if not isinstance(bharmafills_meta, dict):
                    bharmafills_meta = {}

                user_review = bharmafills_meta.get("user_review") or {}
                if not isinstance(user_review, dict):
                    user_review = {}

                if update_data.user_notes is not None:
                    user_review["notes"] = update_data.user_notes.strip()
                user_review["updated_at"] = datetime.now(timezone.utc).isoformat()
                bharmafills_meta["user_review"] = user_review
                new_meta["bharmafills"] = bharmafills_meta

                updated_row = await conn.fetchrow(
                    """
                    UPDATE public.information_gaps
                    SET status = $1,
                        confidence_metadata = $2::jsonb,
                        updated_at = now()
                    WHERE id = $3 AND project_id = $4
                    RETURNING id, project_id, topic_id, gap_description, explanation, suggested_query,
                              priority, status, gap_type, confidence_metadata, created_at, updated_at;
                    """,
                    update_data.status.value,
                    json.dumps(new_meta),
                    gap_id,
                    project_id,
                )

                if not updated_row:
                    raise GapNotFoundError(
                        f"Information gap '{gap_id}' was not found in project '{project_id}'.",
                        gap_id=gap_id,
                        project_id=project_id,
                    )

                d = dict(updated_row)
                d["confidence_metadata"] = _parse_json(d.get("confidence_metadata"), default={})
                return InformationGapResponse(**d)


@lru_cache
def get_gap_persistence_service() -> GapPersistenceService:
    """Return a cached singleton instance of GapPersistenceService."""
    return GapPersistenceService()

