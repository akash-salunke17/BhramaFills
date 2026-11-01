"""API route handlers for research project management and CRUD operations."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.core.auth import get_current_user
from app.core.auth_schemas import AuthenticatedUser
from app.core.ownership import ProjectNotFoundError
from app.db.connection import DatabaseManager, DatabaseNotConfiguredError, DatabaseUnavailableError, get_db_manager
from app.services.projects.schemas import (
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)
from app.services.projects.service import ProjectService, get_project_service

logger = logging.getLogger("bharmafills.api.projects")

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new research project",
    description="Creates a research project owned by the authenticated user and persists it in Supabase.",
    responses={
        201: {"description": "Project successfully created"},
        400: {"description": "Validation error or invalid project payload"},
        401: {"description": "Missing or invalid Bearer authentication token"},
        503: {"description": "Database connection unavailable or unconfigured"},
    },
)
async def create_project_endpoint(
    payload: ProjectCreateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> ProjectResponse:
    """Create a new research project for the authenticated caller."""
    service = ProjectService(db_manager=db_manager)
    if not service.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable or unconfigured.",
        )

    try:
        return await service.create_project(
            user_id=current_user.id,
            payload=payload,
        )
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable during project creation: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error creating project: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create research project.",
        ) from exc


@router.get(
    "",
    response_model=ProjectListResponse,
    status_code=status.HTTP_200_OK,
    summary="List research projects owned by the authenticated user",
    description="Returns a paginated list of active (non-deleted) research projects belonging to the caller.",
    responses={
        200: {"description": "List of user research projects"},
        401: {"description": "Missing or invalid Bearer authentication token"},
        503: {"description": "Database connection unavailable or unconfigured"},
    },
)
async def list_projects_endpoint(
    limit: int = Query(default=50, ge=1, le=200, description="Items limit per page"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> ProjectListResponse:
    """List research projects for the authenticated caller."""
    service = ProjectService(db_manager=db_manager)
    if not service.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable or unconfigured.",
        )

    try:
        return await service.list_user_projects(
            user_id=current_user.id,
            limit=limit,
            offset=offset,
        )
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable while listing projects: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error listing projects: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve research projects.",
        ) from exc


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve details of a specific research project",
    description="Retrieves a single research project by ID, verifying caller ownership.",
    responses={
        200: {"description": "Detailed research project record"},
        401: {"description": "Missing or invalid Bearer authentication token"},
        404: {"description": "Research project not found or access denied"},
        503: {"description": "Database connection unavailable or unconfigured"},
    },
)
async def get_project_endpoint(
    project_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> ProjectResponse:
    """Retrieve an owned research project by ID."""
    service = ProjectService(db_manager=db_manager)
    if not service.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable or unconfigured.",
        )

    try:
        return await service.get_user_project(
            project_id=project_id,
            user_id=current_user.id,
        )
    except ProjectNotFoundError:
        # Uniform 404 masking
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research project '{project_id}' was not found.",
        ) from None
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable while getting project: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error getting project: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve research project.",
        ) from exc


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an existing research project",
    description="Updates specified fields of an owned research project.",
    responses={
        200: {"description": "Updated research project record"},
        400: {"description": "Validation error on update payload"},
        401: {"description": "Missing or invalid Bearer authentication token"},
        404: {"description": "Research project not found or access denied"},
        503: {"description": "Database connection unavailable or unconfigured"},
    },
)
async def update_project_endpoint(
    project_id: UUID,
    payload: ProjectUpdateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> ProjectResponse:
    """Update fields on an owned research project."""
    service = ProjectService(db_manager=db_manager)
    if not service.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable or unconfigured.",
        )

    try:
        return await service.update_user_project(
            project_id=project_id,
            user_id=current_user.id,
            payload=payload,
        )
    except ProjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research project '{project_id}' was not found.",
        ) from None
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable while updating project: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error updating project: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update research project.",
        ) from exc


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a research project",
    description="Soft-deletes an owned research project, hiding it from listings while maintaining data integrity.",
    responses={
        204: {"description": "Project successfully soft-deleted"},
        401: {"description": "Missing or invalid Bearer authentication token"},
        404: {"description": "Research project not found or access denied"},
        503: {"description": "Database connection unavailable or unconfigured"},
    },
)
async def delete_project_endpoint(
    project_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> Response:
    """Soft-delete an owned research project."""
    service = ProjectService(db_manager=db_manager)
    if not service.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable or unconfigured.",
        )

    try:
        await service.delete_user_project(
            project_id=project_id,
            user_id=current_user.id,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except ProjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research project '{project_id}' was not found.",
        ) from None
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable while deleting project: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error deleting project: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete research project.",
        ) from exc
