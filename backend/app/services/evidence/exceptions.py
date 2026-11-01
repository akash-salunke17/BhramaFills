"""Exceptions for evidence persistence and retrieval operations."""


class EvidencePersistenceError(Exception):
    """Base exception for evidence persistence and retrieval operations."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ExtractionRunNotFoundError(EvidencePersistenceError):
    """Raised when an extraction run record is not found."""

    def __init__(self, message: str = "Extraction run not found.") -> None:
        super().__init__(message=message, status_code=404)


class SourceMismatchError(EvidencePersistenceError):
    """Raised when source does not belong to the specified research project."""

    def __init__(self, message: str = "Source does not belong to specified project.") -> None:
        super().__init__(message=message, status_code=400)


class DuplicateExtractionRunError(EvidencePersistenceError):
    """Raised when an identical extraction run has already been recorded."""

    def __init__(self, message: str = "Duplicate extraction run detected.") -> None:
        super().__init__(message=message, status_code=409)


class InvalidEvidencePayloadError(EvidencePersistenceError):
    """Raised when the evidence payload violates data-integrity constraints."""

    def __init__(self, message: str = "Invalid evidence payload.") -> None:
        super().__init__(message=message, status_code=422)


class EvidenceTransactionError(EvidencePersistenceError):
    """Raised when a transactional database write fails and was rolled back."""

    def __init__(self, message: str = "Database transaction failed and was rolled back.") -> None:
        super().__init__(message=message, status_code=500)

