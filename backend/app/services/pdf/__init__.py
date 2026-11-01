"""PDF extraction and ingestion service package using PyMuPDF."""

from app.services.pdf.exceptions import (
    EmptyPDFError,
    InvalidPDFError,
    OversizedPageCountError,
    OversizedPDFError,
    PasswordProtectedPDFError,
    PDFProcessingError,
    ScannedPDFError,
    UnsupportedMediaTypeError,
)
from app.services.pdf.extractor import PDFExtractor
from app.services.pdf.schemas import (
    PDFExtractResult,
    PDFPageItem,
    ProjectPDFSourceResponse,
)
from app.services.pdf.service import (
    PDFSourceIngestionService,
    get_pdf_source_service,
)
from app.services.pdf.validator import (
    ALLOWED_PDF_MIME_TYPES,
    PDF_MAGIC_MARKER,
    PDFValidator,
)

__all__ = [
    "PDFSourceIngestionService",
    "get_pdf_source_service",
    "PDFExtractor",
    "PDFValidator",
    "ALLOWED_PDF_MIME_TYPES",
    "PDF_MAGIC_MARKER",
    "PDFExtractResult",
    "PDFPageItem",
    "ProjectPDFSourceResponse",
    "PDFProcessingError",
    "InvalidPDFError",
    "UnsupportedMediaTypeError",
    "OversizedPDFError",
    "OversizedPageCountError",
    "EmptyPDFError",
    "PasswordProtectedPDFError",
    "ScannedPDFError",
]

