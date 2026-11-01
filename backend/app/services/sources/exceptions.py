"""Exceptions for source ingestion and management service layer."""

from app.core.ownership import ProjectNotFoundError


class SourceServiceError(Exception):
    """Base exception for all source-related business logic errors."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class SourceNotFoundError(SourceServiceError):
    """Raised when a specific source record is not found."""

    def __init__(self, message: str = "Source not found.") -> None:
        super().__init__(message=message, status_code=404)


class EmptyExtractedContentError(SourceServiceError):
    """Raised when web page extraction yields empty readable text."""

    def __init__(self, message: str = "Extracted page content is empty or contains no readable text.") -> None:
        super().__init__(message=message, status_code=422)

