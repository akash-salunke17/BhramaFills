"""Health check endpoint verifying the FastAPI application process is running."""

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings

router = APIRouter()


class HealthResponse(BaseModel):
    """Schema for API health status response.

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
