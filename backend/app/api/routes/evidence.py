"""API route handlers for evidence persistence, extraction runs, and evidence retrieval."""

import logging
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import get_current_user
from app.core.auth_schemas import AuthenticatedUser
from app.core.ownership import OwnedProjectContext, get_owned_project
from app.db.connection import DatabaseNotConfiguredError, DatabaseUnavailableError
from app.services.evidence import (
    DuplicateExtractionRunError,
    EvidencePersistenceError,
    EvidencePersistenceService,
    EvidenceTransactionError,
    ExtractionRunListResponse,
    ExtractionRunNotFoundError,
    ExtractionRunResponse,
    InvalidEvidencePayloadError,
    PersistEvidenceRequest,
    PersistedEvidenceRunResponse,
    ProjectEvidenceResponse,
    SourceMismatchError,
    get_evidence_persistence_service,
)
from app.services.sources.exceptions import ProjectNotFoundError, SourceNotFoundError

logger = logging.getLogger("bharmafills.api.evidence")

router = APIRouter(prefix="/projects", tags=["evidence"])


@router.post(
    "/{project_id}/sources/{source_id}/persist",
    response_model=PersistedEvidenceRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Persist validated evidence extraction result into Supabase",
    description="Atomically persists extraction run metadata, discrete facts, and source claims into PostgreSQL.",
    responses={
        201: {"description": "Evidence extraction run successfully persisted"},
        401: {"description": "Missing or invalid Bearer authentication token"},
        404: {"description": "Research project or source not found"},
        409: {"description": "Duplicate extraction run detected"},
        422: {"description": "Invalid evidence payload or schema mismatch"},
        500: {"description": "Transaction failed and was rolled back"},
        503: {"description": "Database connection unavailable or unconfigured"},
    },
)
async def persist_source_evidence_endpoint(
    project_id: UUID,
    source_id: UUID,
    payload: PersistEvidenceRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    project_context: OwnedProjectContext = Depends(get_owned_project),
    service: EvidencePersistenceService = Depends(get_evidence_persistence_service),
) -> PersistedEvidenceRunResponse:
    """Atomically persist validated evidence results for a project source."""
    if not service.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable or unconfigured.",
        )

    try:
        return await service.persist_extraction_result(
            project_id=project_context.id,
            source_id=source_id,
            result=payload.result,
            user_id=project_context.user_id,
            batch_id=payload.batch_id,
            idempotency_key=payload.idempotency_key,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except SourceMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source '{source_id}' was not found in research project '{project_id}'.",
        ) from exc
    except DuplicateExtractionRunError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
    except InvalidEvidencePayloadError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message) from exc
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable during evidence persistence: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc
    except EvidenceTransactionError as exc:
        logger.error("Transaction failed during evidence persistence: %s", exc.message)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=exc.message) from exc
    except Exception as exc:
        logger.error("Unexpected error persisting evidence: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while persisting evidence.",
        ) from exc


@router.get(
    "/{project_id}/sources/{source_id}/evidence",
    response_model=ProjectEvidenceResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve extracted facts and claims for a specific source",
    description="Returns persisted facts and source claims for a given source document with optional filters and pagination.",
    responses={
        200: {"description": "Paginated collection of source evidence facts and claims"},
        401: {"description": "Missing or invalid Bearer authentication token"},
        404: {"description": "Research project or source not found"},
        503: {"description": "Database connection unavailable or unconfigured"},
    },
)
async def get_source_evidence_endpoint(
    project_id: UUID,
    source_id: UUID,
    run_id: UUID | None = Query(default=None, description="Optional extraction run UUID filter"),
    item_type: Literal["all", "facts", "claims"] = Query(default="all", description="Filter facts, claims, or both"),
    fact_type: str | None = Query(default=None, description="Optional FactType filter"),
    claim_type: str | None = Query(default=None, description="Optional ClaimType filter"),
    limit: int = Query(default=50, ge=1, le=200, description="Items limit per page"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    project_context: OwnedProjectContext = Depends(get_owned_project),
    service: EvidencePersistenceService = Depends(get_evidence_persistence_service),
) -> ProjectEvidenceResponse:
    """Retrieve persisted facts and claims for a specific source."""
    if not service.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable or unconfigured.",
        )

    try:
        return await service.get_source_evidence(
            project_id=project_context.id,
            source_id=source_id,
            user_id=project_context.user_id,
            extraction_run_id=run_id,
            item_type=item_type,
            fact_type=fact_type,
            claim_type=claim_type,
            limit=limit,
            offset=offset,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except SourceMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source '{source_id}' was not found in research project '{project_id}'.",
        ) from exc
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable while retrieving source evidence: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc


@router.get(
    "/{project_id}/evidence",
    response_model=ProjectEvidenceResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve extracted facts and claims across an entire research project",
    description="Returns all persisted facts and source claims for a research project with optional filters and pagination.",
    responses={
        200: {"description": "Paginated collection of project evidence facts and claims"},
        401: {"description": "Missing or invalid Bearer authentication token"},
        404: {"description": "Research project not found"},
        503: {"description": "Database connection unavailable or unconfigured"},
    },
)
async def get_project_evidence_endpoint(
    project_id: UUID,
    source_id: UUID | None = Query(default=None, description="Optional source UUID filter"),
    run_id: UUID | None = Query(default=None, description="Optional extraction run UUID filter"),
    item_type: Literal["all", "facts", "claims"] = Query(default="all", description="Filter facts, claims, or both"),
    fact_type: str | None = Query(default=None, description="Optional FactType filter"),
    claim_type: str | None = Query(default=None, description="Optional ClaimType filter"),
    limit: int = Query(default=50, ge=1, le=200, description="Items limit per page"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    project_context: OwnedProjectContext = Depends(get_owned_project),
    service: EvidencePersistenceService = Depends(get_evidence_persistence_service),
) -> ProjectEvidenceResponse:
    """Retrieve persisted facts and claims across an entire research project."""
    if not service.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable or unconfigured.",
        )

    try:
        return await service.get_project_evidence(
            project_id=project_context.id,
            user_id=project_context.user_id,
            source_id=source_id,
            extraction_run_id=run_id,
            item_type=item_type,
            fact_type=fact_type,
            claim_type=claim_type,
            limit=limit,
            offset=offset,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except SourceMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source '{source_id}' was not found in research project '{project_id}'.",
        ) from exc
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable while retrieving project evidence: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc


@router.get(
    "/{project_id}/sources/{source_id}/extraction-runs",
    response_model=ExtractionRunListResponse,
    status_code=status.HTTP_200_OK,
    summary="List extraction runs for a specific source document",
    description="Returns chronologically ordered extraction run records for auditing and provenance.",
    responses={
        200: {"description": "Paginated list of extraction runs"},
        401: {"description": "Missing or invalid Bearer authentication token"},
        404: {"description": "Research project or source not found"},
        503: {"description": "Database connection unavailable or unconfigured"},
    },
)
async def list_source_extraction_runs_endpoint(
    project_id: UUID,
    source_id: UUID,
    limit: int = Query(default=20, ge=1, le=100, description="Items limit per page"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    project_context: OwnedProjectContext = Depends(get_owned_project),
    service: EvidencePersistenceService = Depends(get_evidence_persistence_service),
) -> ExtractionRunListResponse:
    """List extraction runs for a specific source document."""
    if not service.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable or unconfigured.",
        )

    try:
        return await service.list_extraction_runs(
            project_id=project_context.id,
            user_id=project_context.user_id,
            source_id=source_id,
            limit=limit,
            offset=offset,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except SourceMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source '{source_id}' was not found in research project '{project_id}'.",
        ) from exc
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable while listing extraction runs: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc


@router.get(
    "/{project_id}/extraction-runs/{run_id}",
    response_model=PersistedEvidenceRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Get details of a specific extraction run and its extracted evidence",
    description="Retrieves extraction run metadata, warnings, errors, and all linked facts and claims.",
    responses={
        200: {"description": "Detailed extraction run record with facts and claims"},
        401: {"description": "Missing or invalid Bearer authentication token"},
        404: {"description": "Research project or extraction run not found"},
        503: {"description": "Database connection unavailable or unconfigured"},
    },
)
async def get_extraction_run_detail_endpoint(
    project_id: UUID,
    run_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    project_context: OwnedProjectContext = Depends(get_owned_project),
    service: EvidencePersistenceService = Depends(get_evidence_persistence_service),
) -> PersistedEvidenceRunResponse:
    """Retrieve details of a specific extraction run and its extracted evidence."""
    if not service.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable or unconfigured.",
        )

    try:
        return await service.get_extraction_run_detail(
            project_id=project_context.id,
            run_id=run_id,
            user_id=project_context.user_id,
        )
    except (ProjectNotFoundError, ExtractionRunNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable while retrieving extraction run detail: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc

