"""Core project ownership verification, child resource relationship validation, and authorization models."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import Depends, HTTPException, status

from app.core.auth import get_current_user
from app.core.auth_schemas import AuthenticatedUser
from app.db.connection import (
    DatabaseManager,
    DatabaseNotConfiguredError,
    DatabaseUnavailableError,
    get_db_manager,
)

logger = logging.getLogger("bharmafills.auth.ownership")


# =============================================================================
# 1. Ownership Context & Domain Exceptions
# =============================================================================

@dataclass(frozen=True)
class OwnedProjectContext:
    """Immutable representation of a research project whose ownership has been verified."""

    id: UUID
    user_id: UUID
    title: str
    status: str = "Draft"


class ProjectAccessDeniedError(Exception):
    """Raised internally when an authenticated caller attempts to access a project owned by another user or unowned."""

    def __init__(
        self,
        project_id: UUID,
        user_id: UUID,
        message: str = "Access denied to research project.",
    ) -> None:
        super().__init__(message)
        self.project_id = project_id
        self.user_id = user_id
        self.error_code = "ACCESS_DENIED"


class ResourceMismatchError(Exception):
    """Raised when a child resource does not belong to the specified target research project."""

    def __init__(
        self,
        resource_type: str,
        resource_id: UUID | str,
        project_id: UUID,
        actual_project_id: UUID | None = None,
        message: str | None = None,
    ) -> None:
        default_msg = (
            f"{resource_type.capitalize()} '{resource_id}' does not belong to research project '{project_id}'."
        )
        super().__init__(message or default_msg)
        self.resource_type = resource_type
        self.resource_id = str(resource_id)
        self.project_id = project_id
        self.actual_project_id = actual_project_id
        self.error_code = "RESOURCE_MISMATCH"


class ProjectNotFoundError(Exception):
    """Raised when the specified research project does not exist or has been soft-deleted."""

    def __init__(
        self,
        message: str = "Research project not found.",
        project_id: UUID | None = None,
        status_code: int = 404,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.project_id = project_id
        self.status_code = status_code
        self.error_code = "PROJECT_NOT_FOUND"


# =============================================================================
# 2. Reusable Ownership Verification Functions
# =============================================================================

async def verify_project_ownership(
    conn: asyncpg.Connection,
    project_id: UUID,
    user_id: UUID,
) -> OwnedProjectContext:
    """Verify that a research project exists, is active (not soft-deleted), and is owned by the specified user.

    Requirements:
    1. Uses parameterized SQL ($1).
    2. Excludes soft-deleted projects (deleted_at IS NULL).
    3. Rejects ownerless projects (user_id IS NULL) with ProjectAccessDeniedError.
    4. Rejects foreign-owned projects (user_id != caller_user_id) with ProjectAccessDeniedError.
    5. Rejects nonexistent projects with ProjectNotFoundError.
    6. Never automatically assigns an owner.
    7. Never mutates the database record.
    8. Enforces mandatory UUID identity; fails closed on invalid or missing identity.

    Returns:
        OwnedProjectContext: Validated immutable project ownership context.

    Raises:
        TypeError: If project_id or user_id is not a valid UUID instance.
        ProjectNotFoundError: If the project does not exist or has been soft-deleted.
        ProjectAccessDeniedError: If the project is owned by another user or lacks an owner.
    """
    if not isinstance(user_id, UUID):
        raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")
    if not isinstance(project_id, UUID):
        raise TypeError(f"project_id must be a UUID instance, got {type(project_id).__name__}")

    row = await conn.fetchrow(
        """
        SELECT id, user_id, title, status
        FROM public.research_projects
        WHERE id = $1 AND deleted_at IS NULL;
        """,
        project_id,
    )
    if not row:
        logger.warning("Project not found or soft-deleted: %s", project_id)
        raise ProjectNotFoundError(f"Research project '{project_id}' was not found.", project_id=project_id)

    stored_owner_id = row["user_id"]

    # Reject ownerless legacy projects (NULL owner) or projects owned by a different user
    if stored_owner_id is None:
        logger.warning(
            "Access denied: research project %s is unowned (user_id is NULL); rejected for caller %s",
            project_id,
            user_id,
        )
        raise ProjectAccessDeniedError(
            project_id=project_id,
            user_id=user_id,
            message=f"Research project '{project_id}' is unowned and cannot be accessed.",
        )

    if stored_owner_id != user_id:
        logger.warning(
            "Access denied: caller %s does not own research project %s",
            user_id,
            project_id,
        )
        raise ProjectAccessDeniedError(
            project_id=project_id,
            user_id=user_id,
            message=f"Caller does not own research project '{project_id}'.",
        )

    return OwnedProjectContext(
        id=row["id"],
        user_id=stored_owner_id,
        title=row["title"],
        status=row["status"],
    )


# =============================================================================
# 3. Child Resource Relationship Verification Helpers
# =============================================================================

async def _resolve_and_verify_ownership(
    conn: asyncpg.Connection,
    project_id: UUID,
    user_or_context: UUID | OwnedProjectContext,
) -> OwnedProjectContext:
    """Validate user identity or verified context, ensuring project ownership is confirmed.

    Fails closed:
    - If user_or_context is None or an invalid type, raises TypeError.
    - If user_or_context is OwnedProjectContext, verifies it matches project_id.
    - If user_or_context is UUID, executes verify_project_ownership.
    """
    if isinstance(user_or_context, OwnedProjectContext):
        if user_or_context.id != project_id:
            raise ResourceMismatchError(
                resource_type="project context",
                resource_id=user_or_context.id,
                project_id=project_id,
                message=f"Provided OwnedProjectContext project '{user_or_context.id}' does not match target project '{project_id}'.",
            )
        return user_or_context
    elif isinstance(user_or_context, UUID):
        return await verify_project_ownership(conn, project_id, user_or_context)
    else:
        raise TypeError(
            f"user_id must be a valid UUID or OwnedProjectContext instance, got {type(user_or_context).__name__}"
        )


async def verify_source_belongs_to_project(
    conn: asyncpg.Connection,
    project_id: UUID,
    source_id: UUID,
    user_id: UUID | OwnedProjectContext,
) -> dict[str, Any]:
    """Verify that a source exists, is active, and belongs to the specified project and owner.

    Raises:
        TypeError: If user_id is missing or not a UUID/OwnedProjectContext.
        ProjectNotFoundError: If project is not found or not owned.
        ResourceMismatchError: If source belongs to a different project.
    """
    await _resolve_and_verify_ownership(conn, project_id, user_id)

    row = await conn.fetchrow(
        """
        SELECT id, project_id, title, source_type, original_url, original_filename, ingestion_status
        FROM public.sources
        WHERE id = $1 AND deleted_at IS NULL;
        """,
        source_id,
    )
    if not row:
        raise ResourceMismatchError(
            resource_type="source",
            resource_id=source_id,
            project_id=project_id,
            message=f"Source '{source_id}' was not found in project '{project_id}'.",
        )

    if row["project_id"] != project_id:
        raise ResourceMismatchError(
            resource_type="source",
            resource_id=source_id,
            project_id=project_id,
            actual_project_id=row["project_id"],
        )

    return dict(row)


async def verify_evidence_belongs_to_project(
    conn: asyncpg.Connection,
    project_id: UUID,
    evidence_id: UUID,
    user_id: UUID | OwnedProjectContext,
) -> dict[str, Any]:
    """Verify that an evidence record exists and belongs to the specified project and owner.

    Raises:
        TypeError: If user_id is missing or not a UUID/OwnedProjectContext.
        ProjectNotFoundError: If project is not found or not owned.
        ResourceMismatchError: If evidence belongs to a different project.
    """
    await _resolve_and_verify_ownership(conn, project_id, user_id)

    row = await conn.fetchrow(
        """
        SELECT id, project_id, source_id, extraction_run_id, claim, fact_type, representation_type
        FROM public.evidence
        WHERE id = $1;
        """,
        evidence_id,
    )
    if not row:
        raise ResourceMismatchError(
            resource_type="evidence",
            resource_id=evidence_id,
            project_id=project_id,
            message=f"Evidence item '{evidence_id}' was not found in project '{project_id}'.",
        )

    if row["project_id"] != project_id:
        raise ResourceMismatchError(
            resource_type="evidence",
            resource_id=evidence_id,
            project_id=project_id,
            actual_project_id=row["project_id"],
        )

    return dict(row)


async def verify_extraction_run_belongs_to_project(
    conn: asyncpg.Connection,
    project_id: UUID,
    run_id: UUID,
    user_id: UUID | OwnedProjectContext,
) -> dict[str, Any]:
    """Verify that an extraction run belongs to the specified project and owner.

    Raises:
        TypeError: If user_id is missing or not a UUID/OwnedProjectContext.
        ProjectNotFoundError: If project is not found or not owned.
        ResourceMismatchError: If run belongs to a different project.
    """
    await _resolve_and_verify_ownership(conn, project_id, user_id)

    row = await conn.fetchrow(
        """
        SELECT id, project_id, source_id, provider, model_name, extraction_status
        FROM public.extraction_runs
        WHERE id = $1;
        """,
        run_id,
    )
    if not row:
        raise ResourceMismatchError(
            resource_type="extraction run",
            resource_id=run_id,
            project_id=project_id,
            message=f"Extraction run '{run_id}' was not found in project '{project_id}'.",
        )

    if row["project_id"] != project_id:
        raise ResourceMismatchError(
            resource_type="extraction run",
            resource_id=run_id,
            project_id=project_id,
            actual_project_id=row["project_id"],
        )

    return dict(row)


async def verify_source_claim_belongs_to_project(
    conn: asyncpg.Connection,
    project_id: UUID,
    claim_id: UUID,
    user_id: UUID | OwnedProjectContext,
) -> dict[str, Any]:
    """Verify that a source claim belongs to the specified project and owner.

    Raises:
        TypeError: If user_id is missing or not a UUID/OwnedProjectContext.
        ProjectNotFoundError: If project is not found or not owned.
        ResourceMismatchError: If claim belongs to a different project.
    """
    await _resolve_and_verify_ownership(conn, project_id, user_id)

    row = await conn.fetchrow(
        """
        SELECT id, project_id, source_id, extraction_run_id, claim_id, claim_type
        FROM public.source_claims
        WHERE id = $1;
        """,
        claim_id,
    )
    if not row:
        raise ResourceMismatchError(
            resource_type="source claim",
            resource_id=claim_id,
            project_id=project_id,
            message=f"Source claim '{claim_id}' was not found in project '{project_id}'.",
        )

    if row["project_id"] != project_id:
        raise ResourceMismatchError(
            resource_type="source claim",
            resource_id=claim_id,
            project_id=project_id,
            actual_project_id=row["project_id"],
        )

    return dict(row)


async def verify_gap_belongs_to_project(
    conn: asyncpg.Connection,
    project_id: UUID,
    gap_id: UUID,
    user_id: UUID | OwnedProjectContext,
) -> dict[str, Any]:
    """Verify that an information gap exists and belongs to the specified project and owner.

    Security & Privacy:
    - Verifies caller owns the project (fails closed with ProjectNotFoundError/ProjectAccessDeniedError).
    - Verifies gap belongs to project_id; if missing or belongs to another project, raises ResourceMismatchError.

    Raises:
        TypeError: If user_id is missing or not a UUID/OwnedProjectContext.
        ProjectNotFoundError: If project is not found or not owned.
        ResourceMismatchError: If gap belongs to a different project or does not exist.
    """
    await _resolve_and_verify_ownership(conn, project_id, user_id)

    if not isinstance(gap_id, UUID):
        raise TypeError(f"gap_id must be a UUID instance, got {type(gap_id).__name__}")

    row = await conn.fetchrow(
        """
        SELECT id, project_id, topic_id, gap_description, explanation, suggested_query,
               priority, status, gap_type, confidence_metadata, created_at, updated_at
        FROM public.information_gaps
        WHERE id = $1;
        """,
        gap_id,
    )
    if not row:
        raise ResourceMismatchError(
            resource_type="information gap",
            resource_id=gap_id,
            project_id=project_id,
            message=f"Information gap '{gap_id}' was not found in project '{project_id}'.",
        )

    if row["project_id"] != project_id:
        raise ResourceMismatchError(
            resource_type="information gap",
            resource_id=gap_id,
            project_id=project_id,
            actual_project_id=row["project_id"],
        )

    return dict(row)


# =============================================================================
# 4. Generic FastAPI Authorization Dependency
# =============================================================================

async def get_owned_project(
    project_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> OwnedProjectContext:
    """FastAPI route dependency validating project existence and caller ownership.

    Security & Privacy Invariant:
    - Rejects missing, deleted, ownerless, and foreign-owned projects with identical HTTP 404.
    - Never leaks the fact that a project exists or who owns it.
    - Downstream route handlers receive a cryptographically verified OwnedProjectContext.
    """
    try:
        async with db_manager.acquire_connection() as conn:
            try:
                return await verify_project_ownership(
                    conn=conn,
                    project_id=project_id,
                    user_id=current_user.id,
                )
            except (ProjectNotFoundError, ProjectAccessDeniedError) as exc:
                # Mask both unowned and nonexistent projects with an identical generic 404
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Research project '{project_id}' was not found.",
                ) from exc
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable while verifying project ownership: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc


__all__ = [
    "OwnedProjectContext",
    "ProjectAccessDeniedError",
    "ResourceMismatchError",
    "ProjectNotFoundError",
    "verify_project_ownership",
    "verify_source_belongs_to_project",
    "verify_evidence_belongs_to_project",
    "verify_extraction_run_belongs_to_project",
    "verify_source_claim_belongs_to_project",
    "verify_gap_belongs_to_project",
    "get_owned_project",
]
