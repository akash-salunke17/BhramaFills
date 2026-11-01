"""Exceptions for PDF upload validation and PyMuPDF text extraction."""


class PDFProcessingError(Exception):
    """Base exception for all PDF-related processing and validation errors."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class InvalidPDFError(PDFProcessingError):
    """Raised when uploaded file is corrupted, malformed, or missing the PDF header signature."""

    def __init__(self, message: str = "Invalid or malformed PDF document.") -> None:
        super().__init__(message=message, status_code=400)


class UnsupportedMediaTypeError(PDFProcessingError):
    """Raised when uploaded file Content-Type or magic header is not a supported PDF."""

    def __init__(self, message: str = "Unsupported media type. Only PDF documents are accepted.") -> None:
        super().__init__(message=message, status_code=415)


class OversizedPDFError(PDFProcessingError):
    """Raised when uploaded PDF exceeds maximum allowed file size."""

    def __init__(self, message: str = "Uploaded PDF exceeds maximum allowed file size.") -> None:
        super().__init__(message=message, status_code=413)


class OversizedPageCountError(PDFProcessingError):
    """Raised when PDF document page count exceeds the configured maximum limit."""

    def __init__(self, message: str = "PDF page count exceeds maximum allowed limit.") -> None:
        super().__init__(message=message, status_code=413)


class EmptyPDFError(PDFProcessingError):
    """Raised when uploaded file is empty (0 bytes) or PDF has 0 pages."""

    def __init__(self, message: str = "Uploaded PDF file is empty.") -> None:
        super().__init__(message=message, status_code=400)


class PasswordProtectedPDFError(PDFProcessingError):
    """Raised when PDF is encrypted or requires a password to open."""

    def __init__(self, message: str = "Password-protected or encrypted PDFs are not supported.") -> None:
        super().__init__(message=message, status_code=400)


class ScannedPDFError(PDFProcessingError):
    """Raised when PDF contains no extractable embedded text (image-only/scanned document)."""

    def __init__(self, message: str = "Document contains no extractable text (scanned or image-only PDF). OCR is not supported.") -> None:
        super().__init__(message=message, status_code=422)

