"""Health check endpoints verifying API process and database connectivity."""

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.db.connection import DatabaseManager, get_db_manager
from app.services.ai import AIConfigStatus, BaseAIProvider, get_ai_provider

router = APIRouter()


class HealthResponse(BaseModel):
    """Schema for API process health status response.

    Truthful indicator that the FastAPI process is operational.
    Does not verify external dependencies (DB/AI/Scraper) until those stages.
    """

    status: str = Field(
        default="ok",
        description="Health indicator of the local API process",
    )
    service: str = Field(
        ...,
        description="Public service identity name",
    )
    version: str = Field(
        ...,
        description="Running semantic version of the API service",
    )


class DatabaseHealthResponse(BaseModel):
    """Schema for database health status response."""

    status: str = Field(
        ...,
        description="Overall health indicator: 'ok', 'not_configured', or 'error'",
    )
    database: str = Field(
        ...,
        description="Database connectivity status: 'connected', 'not_configured', or 'unavailable'",
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="API Process Health Probe",
    description=(
        "Returns HTTP 200 indicating the Bharmafills API process is operational. "
        "Does not claim external services (database, AI, scraper) are healthy."
    ),
    tags=["Health"],
)
def check_health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Return the health status of the running FastAPI process."""
    return HealthResponse(
        status="ok",
        service=settings.PROJECT_NAME,
        version=settings.VERSION,
    )


@router.get(
    "/health/database",
    response_model=DatabaseHealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Supabase PostgreSQL Database Connectivity Probe",
    description=(
        "Returns the connectivity status of the Supabase PostgreSQL database. "
        "Returns HTTP 200 with database='connected' when reachable, "
        "HTTP 200 with database='not_configured' when SUPABASE_DB_URL is missing, "
        "or HTTP 503 when configured but unavailable."
    ),
    tags=["Health"],
    responses={
        status.HTTP_200_OK: {
            "description": "Database is reachable or intentionally not configured",
            "model": DatabaseHealthResponse,
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Database is configured but unreachable or connection failed",
            "model": DatabaseHealthResponse,
        },
    },
)
async def check_database_health(
    response: Response,
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> DatabaseHealthResponse:
    """Check connectivity to Supabase PostgreSQL without exposing credentials."""
    result = await db_manager.check_connection()
    if result.status == "error":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return DatabaseHealthResponse(
        status=result.status,
        database=result.database,
    )


@router.get(
    "/health/ai",
    response_model=AIConfigStatus,
    status_code=status.HTTP_200_OK,
    summary="AI Provider Configuration & Status Probe",
    description=(
        "Returns the configuration status and active model for the AI integration (OpenRouter). "
        "Returns status='configured' if API credentials are present, or status='not_configured' "
        "if missing. Never exposes plain text credentials or triggers paid API invocations."
    ),
    tags=["Health"],
)
async def check_ai_health(
    ai_provider: BaseAIProvider = Depends(get_ai_provider),
) -> AIConfigStatus:
    """Return configuration status of the AI provider without leaking secrets."""
    return await ai_provider.check_health()
