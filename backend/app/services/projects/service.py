"""Service layer managing research project CRUD operations with mandatory ownership and soft deletion."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.core.ownership import (
    ProjectAccessDeniedError,
    ProjectNotFoundError,
    verify_project_ownership,
)
from app.db.connection import DatabaseManager, get_db_manager
from app.services.projects.schemas import (
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)

logger = logging.getLogger("bharmafills.services.projects")


class ProjectService:
    """Encapsulates business logic, data validation, and database operations for research projects."""

    def __init__(self, db_manager: DatabaseManager | None = None) -> None:
        self._db_manager = db_manager or get_db_manager()

    @property
    def is_configured(self) -> bool:
        """Return True if database manager has valid configuration."""
        return self._db_manager.is_configured

    async def create_project(
        self,
        user_id: UUID,
        payload: ProjectCreateRequest,
    ) -> ProjectResponse:
        """Persist a new research project record bound to the authenticated user.

        Args:
            user_id: Verified caller UUID.
            payload: Validated project creation request.

        Returns:
            ProjectResponse containing the newly generated project.
        """
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")

        async with self._db_manager.acquire_connection() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO public.research_projects (
                    user_id,
                    title,
                    research_question,
                    description,
                    category,
                    status
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id, user_id, title, research_question, description, category, status, created_at, updated_at;
                """,
                user_id,
                payload.title,
                payload.research_question,
                payload.description,
                payload.category.value,
                payload.status.value,
            )

            logger.info("Created research project %s for user %s", row["id"], user_id)
            return ProjectResponse(**dict(row))

    async def list_user_projects(
        self,
        user_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> ProjectListResponse:
        """Retrieve paginated active research projects owned by the authenticated caller.

        Excludes soft-deleted projects and foreign projects.
        """
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")

        limit = max(1, min(limit, 200))
        offset = max(0, offset)

        async with self._db_manager.acquire_connection() as conn:
            total_count = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM public.research_projects
                WHERE user_id = $1 AND deleted_at IS NULL;
                """,
                user_id,
            )

            rows = await conn.fetch(
                """
                SELECT id, user_id, title, research_question, description, category, status, created_at, updated_at
                FROM public.research_projects
                WHERE user_id = $1 AND deleted_at IS NULL
                ORDER BY updated_at DESC
                LIMIT $2 OFFSET $3;
                """,
                user_id,
                limit,
                offset,
            )

            projects = [ProjectResponse(**dict(r)) for r in rows]
            return ProjectListResponse(
                projects=projects,
                total_count=total_count or 0,
                limit=limit,
                offset=offset,
            )

    async def get_user_project(
        self,
        project_id: UUID,
        user_id: UUID,
    ) -> ProjectResponse:
        """Retrieve a specific active research project ensuring caller ownership.

        Raises ProjectNotFoundError if nonexistent, soft-deleted, or owned by another user.
        """
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")
        if not isinstance(project_id, UUID):
            raise TypeError(f"project_id must be a UUID instance, got {type(project_id).__name__}")

        async with self._db_manager.acquire_connection() as conn:
            # Verify ownership (raises ProjectNotFoundError or ProjectAccessDeniedError)
            try:
                await verify_project_ownership(conn, project_id, user_id)
            except ProjectAccessDeniedError as exc:
                # Mask foreign/unowned project existence as 404
                raise ProjectNotFoundError(
                    f"Research project '{project_id}' was not found.",
                    project_id=project_id,
                ) from exc

            row = await conn.fetchrow(
                """
                SELECT id, user_id, title, research_question, description, category, status, created_at, updated_at
                FROM public.research_projects
                WHERE id = $1 AND deleted_at IS NULL;
                """,
                project_id,
            )
            if not row:
                raise ProjectNotFoundError(
                    f"Research project '{project_id}' was not found.",
                    project_id=project_id,
                )

            return ProjectResponse(**dict(row))

    async def update_user_project(
        self,
        project_id: UUID,
        user_id: UUID,
        payload: ProjectUpdateRequest,
    ) -> ProjectResponse:
        """Update fields of an existing research project owned by the caller.

        Preserves existing values for omitted fields and updates `updated_at`.
        """
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")
        if not isinstance(project_id, UUID):
            raise TypeError(f"project_id must be a UUID instance, got {type(project_id).__name__}")

        async with self._db_manager.acquire_connection() as conn:
            try:
                await verify_project_ownership(conn, project_id, user_id)
            except ProjectAccessDeniedError as exc:
                raise ProjectNotFoundError(
                    f"Research project '{project_id}' was not found.",
                    project_id=project_id,
                ) from exc

            # Fetch current values
            current = await conn.fetchrow(
                """
                SELECT id, user_id, title, research_question, description, category, status, created_at, updated_at
                FROM public.research_projects
                WHERE id = $1 AND deleted_at IS NULL;
                """,
                project_id,
            )
            if not current:
                raise ProjectNotFoundError(
                    f"Research project '{project_id}' was not found.",
                    project_id=project_id,
                )

            title = payload.title if payload.title is not None else current["title"]
            research_question = (
                payload.research_question
                if payload.research_question is not None
                else current["research_question"]
            )
            description = (
                payload.description
                if payload.description is not None
                else current["description"]
            )
            category = (
                payload.category.value
                if payload.category is not None
                else current["category"]
            )
            status_val = (
                payload.status.value
                if payload.status is not None
                else current["status"]
            )

            updated_row = await conn.fetchrow(
                """
                UPDATE public.research_projects
                SET title = $1,
                    research_question = $2,
                    description = $3,
                    category = $4,
                    status = $5,
                    updated_at = now()
                WHERE id = $6 AND deleted_at IS NULL
                RETURNING id, user_id, title, research_question, description, category, status, created_at, updated_at;
                """,
                title,
                research_question,
                description,
                category,
                status_val,
                project_id,
            )

            logger.info("Updated research project %s for user %s", project_id, user_id)
            return ProjectResponse(**dict(updated_row))

    async def delete_user_project(
        self,
        project_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Soft-delete a research project owned by the authenticated caller.

        Sets `deleted_at = now()` to maintain referential integrity while hiding from active views.
        """
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")
        if not isinstance(project_id, UUID):
            raise TypeError(f"project_id must be a UUID instance, got {type(project_id).__name__}")

        async with self._db_manager.acquire_connection() as conn:
            try:
                await verify_project_ownership(conn, project_id, user_id)
            except ProjectAccessDeniedError as exc:
                raise ProjectNotFoundError(
                    f"Research project '{project_id}' was not found.",
                    project_id=project_id,
                ) from exc

            result = await conn.execute(
                """
                UPDATE public.research_projects
                SET deleted_at = now(),
                    updated_at = now()
                WHERE id = $1 AND user_id = $2 AND deleted_at IS NULL;
                """,
                project_id,
                user_id,
            )

            logger.info("Soft-deleted research project %s for user %s", project_id, user_id)
            return True


_project_service_instance: ProjectService | None = None


def get_project_service(
    db_manager: DatabaseManager = None,
) -> ProjectService:
    """Dependency provider for FastAPI route injection."""
    if db_manager is not None:
        return ProjectService(db_manager=db_manager)
    global _project_service_instance
    if _project_service_instance is None:
        _project_service_instance = ProjectService()
    return _project_service_instance
