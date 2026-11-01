"""Sources service package exposing ingestion, management, and schemas."""

from app.services.pdf.schemas import ProjectPDFSourceResponse
from app.services.sources.exceptions import (
    EmptyExtractedContentError,
    ProjectNotFoundError,
    SourceNotFoundError,
    SourceServiceError,
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

__all__ = [
    "WebSourceIngestionService",
    "get_web_source_service",
    "ProjectWebSourceRequest",
    "ProjectWebSourceResponse",
    "ProjectPDFSourceResponse",
    "SourceSummaryResponse",
    "SourceDetailResponse",
    "SourceServiceError",
    "ProjectNotFoundError",
    "SourceNotFoundError",
    "EmptyExtractedContentError",
]

