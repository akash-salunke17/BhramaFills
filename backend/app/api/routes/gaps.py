"""API route handlers for Information Gap Detection, Persistence, Retrieval, and Review."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status

from app.core.auth import get_current_user
from app.core.auth_schemas import AuthenticatedUser
from app.core.ownership import OwnedProjectContext, get_owned_project
from app.db.connection import DatabaseNotConfiguredError, DatabaseUnavailableError
from app.services.ai.exceptions import (
    AIAuthenticationError,
    AIContentPolicyError,
    AIProviderError,
    AIProviderUnavailableError,
    AIQuotaExceededError,
    AIRateLimitError,
    AIResponseValidationError,
    AITimeoutError,
)
from app.services.ai.gap_detection_service import (
    InformationGapDetectionService,
    get_gap_detection_service,
)
from app.services.ai.gap_persistence_service import (
    GapNotFoundError,
    GapPersistenceError,
    GapPersistenceService,
    GapTransactionError,
    get_gap_persistence_service,
)
from app.services.ai.gap_schemas import (
    DetectGapsRequest,
    GapDetectionAndPersistenceResponse,
    GapPriority,
    GapReviewUpdate,
    GapStatus,
    GapType,
    InformationGapListResponse,
    InformationGapResponse,
)
from app.services.sources.exceptions import ProjectNotFoundError

logger = logging.getLogger("bharmafills.api.gaps")

router = APIRouter(prefix="/projects", tags=["information_gaps"])


@router.post(
    "/{project_id}/gaps/detect",
    response_model=GapDetectionAndPersistenceResponse,
    status_code=http_status.HTTP_200_OK,
    summary="Detect and persist information gaps for a research project",
    description=(
        "Verifies caller ownership, retrieves project sources and evidence, "
        "coordinates AI information gap detection, validates findings against project evidence, "
        "and transactionally persists results into PostgreSQL with rerun deduplication."
    ),
    responses={
        200: {"description": "Gaps successfully detected, validated, and persisted"},
        400: {"description": "Project research question is invalid or missing"},
        401: {"description": "Missing or invalid Bearer authentication token"},
        404: {"description": "Research project was not found"},
        422: {"description": "Request body validation failed"},
        429: {"description": "AI provider rate limit exceeded"},
        500: {"description": "Transactional persistence failure or internal error"},
        502: {"description": "AI provider upstream error or response validation failure"},
        503: {"description": "AI provider unconfigured/unavailable or database unavailable"},
        504: {"description": "AI completion request timed out"},
    },
)
async def detect_and_persist_project_gaps_endpoint(
    project_id: UUID,
    payload: DetectGapsRequest | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
    project_context: OwnedProjectContext = Depends(get_owned_project),
    detection_service: InformationGapDetectionService = Depends(get_gap_detection_service),
    persistence_service: GapPersistenceService = Depends(get_gap_persistence_service),
) -> GapDetectionAndPersistenceResponse:
    """Coordinate information gap detection and transactional persistence for an owned project."""
    if not detection_service.is_configured:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI provider is not configured. OPENROUTER_API_KEY is missing.",
        )

    if not persistence_service.is_configured:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable or unconfigured.",
        )

    custom_instructions = payload.custom_instructions if payload else None

    # 1. Run detection pipeline
    try:
        detection_result = await detection_service.detect_gaps(
            project_id=project_context.id,
            user_id=project_context.user_id,
            custom_instructions=custom_instructions,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except AITimeoutError as exc:
        logger.warning("AI completion timed out for project %s: %s", project_context.id, exc.message)
        raise HTTPException(
            status_code=http_status.HTTP_504_GATEWAY_TIMEOUT,
            detail="AI completion request timed out. Please try again.",
        ) from exc
    except AIRateLimitError as exc:
        logger.warning("AI rate limit reached for project %s: %s", project_context.id, exc.message)
        raise HTTPException(
            status_code=http_status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI service rate limit exceeded. Please retry later.",
        ) from exc
    except AIQuotaExceededError as exc:
        logger.error("AI quota exceeded: %s", exc.message)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI provider quota exceeded.",
        ) from exc
    except AIProviderUnavailableError as exc:
        logger.error("AI provider unavailable: %s", exc.message)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service is temporarily unavailable.",
        ) from exc
    except AIAuthenticationError as exc:
        logger.error("AI provider authentication failure: %s", exc.message)
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail="AI provider authentication failure.",
        ) from exc
    except AIResponseValidationError as exc:
        logger.error("AI response validation failed for project %s: %s", project_context.id, exc.message)
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail="Failed to parse valid structured response from AI model.",
        ) from exc
    except (AIContentPolicyError, AIProviderError) as exc:
        logger.error("AI provider error for project %s: %s", project_context.id, exc.message)
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail="AI service communication error.",
        ) from exc
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable during gap detection: %s", type(exc).__name__)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error during gap detection for project %s: %s", project_context.id, type(exc).__name__)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during information gap detection.",
        ) from exc

    # 2. Transactionally persist findings into PostgreSQL
    try:
        persistence_summary = await persistence_service.persist_detection_result(
            project_id=project_context.id,
            user_id=project_context.user_id,
            detection_result=detection_result,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable during gap persistence: %s", type(exc).__name__)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc
    except GapTransactionError as exc:
        msg = getattr(exc, "message", str(exc))
        logger.error("Transaction failed during gap persistence for project %s: %s", project_context.id, msg)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database transaction failed during gap persistence.",
        ) from exc
    except GapPersistenceError as exc:
        msg = getattr(exc, "message", str(exc))
        logger.error("Persistence failed for project %s: %s", project_context.id, msg)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist information gaps.",
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error persisting gaps for project %s: %s", project_context.id, type(exc).__name__)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while persisting information gaps.",
        ) from exc

    return GapDetectionAndPersistenceResponse(
        project_id=project_context.id,
        detection=detection_result,
        persistence=persistence_summary,
    )


@router.get(
    "/{project_id}/gaps",
    response_model=InformationGapListResponse,
    status_code=http_status.HTTP_200_OK,
    summary="List information gaps for a research project",
    description="Retrieves a paginated list of persisted information gaps for the project with optional filters.",
    responses={
        200: {"description": "Paginated list of project information gaps"},
        401: {"description": "Missing or invalid Bearer authentication token"},
        404: {"description": "Research project was not found"},
        503: {"description": "Database connection unavailable or unconfigured"},
    },
)
async def list_project_gaps_endpoint(
    project_id: UUID,
    status: GapStatus | None = Query(default=None, description="Optional status filter"),
    priority: GapPriority | None = Query(default=None, description="Optional priority filter"),
    gap_type: GapType | None = Query(default=None, description="Optional gap type filter"),
    limit: int = Query(default=50, ge=1, le=200, description="Items limit per page"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    project_context: OwnedProjectContext = Depends(get_owned_project),
    persistence_service: GapPersistenceService = Depends(get_gap_persistence_service),
) -> InformationGapListResponse:
    """List persisted information gaps for an owned project."""
    if not persistence_service.is_configured:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable or unconfigured.",
        )

    try:
        total_count = await persistence_service.count_project_gaps(
            project_id=project_context.id,
            user_id=project_context.user_id,
            status=status,
            priority=priority,
            gap_type=gap_type,
        )
        gaps = await persistence_service.list_project_gaps(
            project_id=project_context.id,
            user_id=project_context.user_id,
            status=status,
            priority=priority,
            gap_type=gap_type,
            limit=limit,
            offset=offset,
        )
        return InformationGapListResponse(
            project_id=project_context.id,
            total_count=total_count,
            limit=limit,
            offset=offset,
            gaps=gaps,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable while listing gaps: %s", type(exc).__name__)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error listing gaps for project %s: %s", project_context.id, type(exc).__name__)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve information gaps.",
        ) from exc


@router.get(
    "/{project_id}/gaps/{gap_id}",
    response_model=InformationGapResponse,
    status_code=http_status.HTTP_200_OK,
    summary="Retrieve details of a single information gap",
    description="Retrieves a single information gap by ID for an owned project.",
    responses={
        200: {"description": "Detailed information gap record"},
        401: {"description": "Missing or invalid Bearer authentication token"},
        404: {"description": "Research project or information gap not found"},
        503: {"description": "Database connection unavailable or unconfigured"},
    },
)
async def get_project_gap_endpoint(
    project_id: UUID,
    gap_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    project_context: OwnedProjectContext = Depends(get_owned_project),
    persistence_service: GapPersistenceService = Depends(get_gap_persistence_service),
) -> InformationGapResponse:
    """Retrieve details of a single information gap in an owned project."""
    if not persistence_service.is_configured:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable or unconfigured.",
        )

    try:
        return await persistence_service.get_project_gap(
            project_id=project_context.id,
            gap_id=gap_id,
            user_id=project_context.user_id,
        )
    except GapNotFoundError:
        # Uniform 404 masking: prevents disclosing whether gap exists in another project
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Information gap '{gap_id}' was not found in research project '{project_id}'.",
        ) from None
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable while retrieving gap: %s", type(exc).__name__)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error retrieving gap %s for project %s: %s", gap_id, project_context.id, type(exc).__name__)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve information gap.",
        ) from exc


@router.patch(
    "/{project_id}/gaps/{gap_id}",
    response_model=InformationGapResponse,
    status_code=http_status.HTTP_200_OK,
    summary="Update user review state on an information gap",
    description="Updates review status ('investigating', 'resolved', 'dismissed') and user notes on an existing gap.",
    responses={
        200: {"description": "Updated information gap record"},
        401: {"description": "Missing or invalid Bearer authentication token"},
        404: {"description": "Research project or information gap not found"},
        422: {"description": "Validation error on review status or notes"},
        500: {"description": "Transaction failed during review update"},
        503: {"description": "Database connection unavailable or unconfigured"},
    },
)
async def update_gap_review_endpoint(
    project_id: UUID,
    gap_id: UUID,
    payload: GapReviewUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    project_context: OwnedProjectContext = Depends(get_owned_project),
    persistence_service: GapPersistenceService = Depends(get_gap_persistence_service),
) -> InformationGapResponse:
    """Update user review lifecycle status and notes on an existing gap."""
    if not persistence_service.is_configured:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable or unconfigured.",
        )

    try:
        return await persistence_service.update_gap_review(
            project_id=project_context.id,
            gap_id=gap_id,
            user_id=project_context.user_id,
            update_data=payload,
        )
    except GapNotFoundError:
        # Uniform 404 masking
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Information gap '{gap_id}' was not found in research project '{project_id}'.",
        ) from None
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable while updating gap review: %s", type(exc).__name__)
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc
    except GapTransactionError as exc:
        msg = getattr(exc, "message", str(exc))
        logger.error("Transaction failed updating review for gap %s: %s", gap_id, msg)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database transaction failed during gap review update.",
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error updating review for gap %s: %s", gap_id, type(exc).__name__)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update information gap review.",
        ) from exc
