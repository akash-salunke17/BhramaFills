"""API route handlers for research project sources and web content ingestion."""

import logging
from uuid import UUID
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status

from app.core.auth import get_current_user
from app.core.auth_schemas import AuthenticatedUser
from app.core.ownership import OwnedProjectContext, get_owned_project
from app.core.config import Settings, get_settings
from app.db.connection import DatabaseNotConfiguredError, DatabaseUnavailableError
from app.services.ai import (
    EvidenceExtractionResult,
    EvidenceExtractionService,
    ExtractEvidenceRequest,
    ExtractionStatus,
    get_evidence_extraction_service,
)
from app.services.evidence import (
    EvidencePersistenceService,
    get_evidence_persistence_service,
)
from app.services.pdf.exceptions import OversizedPDFError, PDFProcessingError
from app.services.pdf.schemas import ProjectPDFSourceResponse
from app.services.pdf.service import PDFSourceIngestionService, get_pdf_source_service
from app.services.sources.exceptions import (
    EmptyExtractedContentError,
    ProjectNotFoundError,
    SourceNotFoundError,
)
from app.services.sources.schemas import (
    ProjectWebSourceRequest,
    ProjectWebSourceResponse,
    SourceDetailResponse,
    SourceSummaryResponse,
)
from app.services.sources.web_source_service import (
    WebSourceIngestionService,
    get_web_source_service,
)
from app.services.web.exceptions import WebExtractionError

logger = logging.getLogger("bharmafills.api.sources")

router = APIRouter(prefix="/projects", tags=["sources"])


@router.post(
    "/{project_id}/sources/web",
    response_model=ProjectWebSourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest and persist web source for a research project",
    description="Validates target project, fetches URL with SSRF protection, extracts readable text, and saves source and content in Supabase.",
    responses={
        200: {"description": "Source or identical content already exists in this project (duplicate resolved)"},
        201: {"description": "Source and extracted text successfully stored"},
        400: {"description": "Invalid URL syntax, unsafe redirect, or SSRF policy violation"},
        401: {"description": "Missing or invalid Bearer authentication token"},
        404: {"description": "Research project not found or soft-deleted"},
        413: {"description": "HTML response exceeded maximum allowed size of 2 MB"},
        422: {"description": "Unsupported Content-Type or empty extracted text content"},
        502: {"description": "Upstream network connection error"},
        503: {"description": "Database connection unavailable or unconfigured"},
        504: {"description": "Upstream connection or read timeout"},
    },
)
async def ingest_web_source_endpoint(
    project_id: UUID,
    payload: ProjectWebSourceRequest,
    response: Response,
    current_user: AuthenticatedUser = Depends(get_current_user),
    project_context: OwnedProjectContext = Depends(get_owned_project),
    service: WebSourceIngestionService = Depends(get_web_source_service),
) -> ProjectWebSourceResponse:
    """Ingest a web URL into the specified research project, persisting source and extracted text."""
    try:
        result = await service.ingest_web_source(
            project_id=project_context.id,
            url=payload.url,
            user_id=project_context.user_id,
        )
        if result.is_duplicate:
            response.status_code = status.HTTP_200_OK
        return result
    except ProjectNotFoundError as exc:
        logger.warning("Project not found: %s", exc.message)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        ) from exc
    except EmptyExtractedContentError as exc:
        logger.warning("Empty content rejected: %s", exc.message)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.message,
        ) from exc
    except WebExtractionError as exc:
        logger.warning("Extraction error for URL '%s': %s", payload.url, exc.message)
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
        ) from exc
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable during web source ingestion: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error ingesting source for project %s: %s", project_id, type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing web source ingestion.",
        ) from exc


@router.post(
    "/{project_id}/sources/pdf",
    response_model=ProjectPDFSourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and ingest a PDF document for a research project",
    description="Validates PDF format and signature, extracts page-by-page readable text with PyMuPDF, and persists source metadata and extracted content in Supabase.",
    responses={
        200: {"description": "Identical PDF binary already exists in this project (duplicate resolved)"},
        201: {"description": "PDF source and extracted page text successfully stored"},
        400: {"description": "Invalid PDF signature, empty upload, malformed structure, or password-protected PDF"},
        401: {"description": "Missing or invalid Bearer authentication token"},
        404: {"description": "Research project not found or soft-deleted"},
        413: {"description": "Uploaded PDF exceeds maximum allowed file size or page count limit"},
        415: {"description": "Unsupported media type or non-PDF Content-Type"},
        422: {"description": "Invalid UUID format in path"},
        500: {"description": "Unexpected server error during PDF processing"},
        503: {"description": "Database connection unavailable or unconfigured"},
    },
)
async def ingest_pdf_source_endpoint(
    project_id: UUID,
    file: UploadFile = File(..., description="PDF document binary upload"),
    response: Response = Response(),
    current_user: AuthenticatedUser = Depends(get_current_user),
    project_context: OwnedProjectContext = Depends(get_owned_project),
    service: PDFSourceIngestionService = Depends(get_pdf_source_service),
    settings: Settings = Depends(get_settings),
) -> ProjectPDFSourceResponse:
    """Validate, extract, and persist an uploaded PDF document into a research project."""
    try:
        # Stream-read bytes with strict size bound to prevent memory exhaustion
        pdf_bytes = bytearray()
        max_bytes = settings.PDF_MAX_UPLOAD_BYTES
        chunk_size = 64 * 1024  # 64 KB

        while chunk := await file.read(chunk_size):
            pdf_bytes.extend(chunk)
            if len(pdf_bytes) > max_bytes:
                raise OversizedPDFError(
                    f"Uploaded PDF exceeds maximum allowed size of {max_bytes} bytes."
                )

        result = await service.ingest_pdf(
            project_id=project_context.id,
            filename=file.filename,
            content_type=file.content_type,
            pdf_bytes=bytes(pdf_bytes),
            user_id=project_context.user_id,
        )

        if result.is_duplicate:
            response.status_code = status.HTTP_200_OK

        return result
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        ) from exc
    except PDFProcessingError as exc:
        logger.warning("PDF processing rejected for project %s: %s", project_id, exc.message)
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
        ) from exc
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable during PDF source ingestion: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error ingesting PDF for project %s: %s", project_id, type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing PDF source ingestion.",
        ) from exc
    finally:
        await file.close()


@router.get(
    "/{project_id}/sources",
    response_model=list[SourceSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List all sources linked to a research project",
    description="Retrieves active sources and metadata summaries for the given research project.",
    responses={
        200: {"description": "List of project sources"},
        401: {"description": "Missing or invalid Bearer authentication token"},
        404: {"description": "Research project not found"},
        503: {"description": "Database connection unavailable or unconfigured"},
    },
)
async def list_project_sources_endpoint(
    project_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    project_context: OwnedProjectContext = Depends(get_owned_project),
    service: WebSourceIngestionService = Depends(get_web_source_service),
) -> list[SourceSummaryResponse]:
    """Retrieve all non-deleted sources for a research project."""
    try:
        return await service.list_project_sources(
            project_id=project_context.id,
            user_id=project_context.user_id,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        ) from exc
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable while listing sources: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc


@router.get(
    "/{project_id}/sources/{source_id}",
    response_model=SourceDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get source details and extracted text",
    description="Retrieves a single source record and its full extracted content for a research project.",
    responses={
        200: {"description": "Detailed source record with extracted text"},
        401: {"description": "Missing or invalid Bearer authentication token"},
        404: {"description": "Research project or source not found"},
        503: {"description": "Database connection unavailable or unconfigured"},
    },
)
async def get_project_source_detail_endpoint(
    project_id: UUID,
    source_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    project_context: OwnedProjectContext = Depends(get_owned_project),
    service: WebSourceIngestionService = Depends(get_web_source_service),
) -> SourceDetailResponse:
    """Retrieve full detail and extracted content for a specific source."""
    try:
        return await service.get_project_source_detail(
            project_id=project_context.id,
            source_id=source_id,
            user_id=project_context.user_id,
        )
    except (ProjectNotFoundError, SourceNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        ) from exc
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable while retrieving source detail: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc


@router.post(
    "/{project_id}/sources/{source_id}/extract",
    response_model=EvidenceExtractionResult,
    status_code=status.HTTP_200_OK,
    summary="Extract structured evidence facts and claims from a project source",
    description=(
        "Validates research project and source existence, checks AI configuration, "
        "and coordinates source-grounded evidence extraction using the configured AI provider."
    ),
    responses={
        200: {"description": "Evidence extraction result envelope"},
        401: {"description": "Missing or invalid Bearer authentication token"},
        404: {"description": "Research project or source not found"},
        503: {"description": "Database unavailable or AI provider not configured"},
        500: {"description": "Unexpected server error during evidence extraction"},
    },
)
async def extract_project_source_evidence_endpoint(
    project_id: UUID,
    source_id: UUID,
    payload: ExtractEvidenceRequest | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
    project_context: OwnedProjectContext = Depends(get_owned_project),
    source_service: WebSourceIngestionService = Depends(get_web_source_service),
    extraction_service: EvidenceExtractionService = Depends(get_evidence_extraction_service),
    persistence_service: EvidencePersistenceService = Depends(get_evidence_persistence_service),
) -> EvidenceExtractionResult:
    """Extract evidence facts and claims for a specific source document."""
    if not extraction_service.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI provider is not configured. OPENROUTER_API_KEY is missing.",
        )

    try:
        source_detail = await source_service.get_project_source_detail(
            project_id=project_context.id,
            source_id=source_id,
            user_id=project_context.user_id,
        )
    except (ProjectNotFoundError, SourceNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        ) from exc
    except (DatabaseNotConfiguredError, DatabaseUnavailableError) as exc:
        logger.error("Database unavailable while retrieving source detail: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable.",
        ) from exc

    research_question = payload.research_question if payload else None
    custom_instructions = payload.custom_instructions if payload else None

    try:
        extraction_result = await extraction_service.extract_source_evidence(
            source_id=str(source_id),
            source_type=source_detail.source_type,
            content=source_detail.extracted_text or "",
            title=source_detail.title,
            source_url=source_detail.original_url,
            research_question=research_question,
            custom_instructions=custom_instructions,
            raise_on_error=False,
        )

        # Attempt automatic persistence if configured and extraction was not completely failed
        if persistence_service.is_configured and extraction_result.extraction_status != ExtractionStatus.FAILED:
            try:
                persisted = await persistence_service.persist_extraction_result(
                    project_id=project_context.id,
                    source_id=source_id,
                    result=extraction_result,
                    user_id=project_context.user_id,
                )
                return extraction_result.model_copy(
                    update={
                        "run_id": persisted.run.id,
                        "is_persisted": True,
                    }
                )
            except Exception as exc:
                logger.warning("Automatic persistence for source %s failed: %s", source_id, type(exc).__name__)
                updated_warnings = list(extraction_result.warnings) + [
                    f"Automatic database persistence was not completed: {type(exc).__name__}"
                ]
                return extraction_result.model_copy(
                    update={
                        "is_persisted": False,
                        "warnings": updated_warnings,
                    }
                )

        return extraction_result
    except Exception as exc:
        logger.error(
            "Unexpected error extracting evidence for source %s: %s",
            source_id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while executing evidence extraction.",
        ) from exc


