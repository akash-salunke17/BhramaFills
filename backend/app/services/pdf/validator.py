"""Defensive PDF validation engine checking signatures, sizes, MIME types, and document structures."""

import logging
from pathlib import Path
import re
from typing import BinaryIO

import pymupdf

from app.services.pdf.exceptions import (
    EmptyPDFError,
    InvalidPDFError,
    OversizedPageCountError,
    OversizedPDFError,
    PasswordProtectedPDFError,
    UnsupportedMediaTypeError,
)

logger = logging.getLogger("bharmafills.services.pdf.validator")

# Supported PDF MIME types
ALLOWED_PDF_MIME_TYPES = frozenset([
    "application/pdf",
    "application/x-pdf",
    "application/acrobat",
    "applications/vnd.pdf",
    "text/pdf",
    "text/x-pdf",
    "application/octet-stream",
])

# Magic byte marker for PDF format
PDF_MAGIC_MARKER = b"%PDF-"


class PDFValidator:
    """Validates uploaded PDF binary data, headers, structure, and resource bounds."""

    @classmethod
    def validate_mime_type(cls, content_type: str | None) -> None:
        """Verify that the HTTP Content-Type header corresponds to a PDF document."""
        if not content_type:
            return

        normalized = content_type.split(";")[0].strip().lower()
        if normalized not in ALLOWED_PDF_MIME_TYPES:
            logger.warning("Rejected unsupported upload Content-Type: '%s'", content_type)
            raise UnsupportedMediaTypeError(
                f"Unsupported media type '{content_type}'. Only PDF documents are accepted."
            )

    @classmethod
    def validate_signature_and_size(cls, pdf_bytes: bytes, max_bytes: int = 20 * 1024 * 1024) -> None:
        """Verify byte bounds and PDF header magic signature (%PDF-)."""
        if not pdf_bytes or len(pdf_bytes) == 0:
            raise EmptyPDFError("Uploaded PDF file is empty (0 bytes).")

        if len(pdf_bytes) > max_bytes:
            raise OversizedPDFError(
                f"Uploaded PDF exceeds maximum allowed size of {max_bytes} bytes ({len(pdf_bytes)} bytes uploaded)."
            )

        # PDF standard allows the %PDF- header to appear anywhere within the first 1024 bytes
        header_sample = pdf_bytes[:1024]
        if PDF_MAGIC_MARKER not in header_sample:
            logger.warning("Uploaded file lacks '%PDF-' signature in first 1024 bytes")
            raise InvalidPDFError("File does not contain a valid PDF header signature (%PDF-).")

    @classmethod
    def sanitize_filename(cls, filename: str | None) -> str:
        """Sanitize client-provided filename to prevent path traversal or filesystem escapes."""
        if not filename or not isinstance(filename, str):
            return "uploaded_document.pdf"

        # Strip path traversal elements and control characters
        cleaned = re.sub(r"[\r\n\t\0]", "", filename.strip())
        # Extract purely the basename
        basename = Path(cleaned).name

        # Remove any leading dots or slashes
        basename = re.sub(r"^[./\\]+", "", basename)
        if not basename:
            basename = "uploaded_document.pdf"

        # Guarantee .pdf extension
        if not basename.lower().endswith(".pdf"):
            basename = f"{basename}.pdf"

        # Truncate to 255 chars preserving .pdf extension
        if len(basename) > 255:
            stem = basename[:-4]
            basename = f"{stem[:251]}.pdf"

        return basename

    @classmethod
    def open_and_validate_structure(
        cls,
        pdf_bytes: bytes,
        max_pages: int = 200,
    ) -> pymupdf.Document:
        """Open PDF in-memory and verify document integrity, encryption, and page bounds.

        Returns:
            pymupdf.Document: Opened document instance. Caller MUST close it.
        """
        try:
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        except Exception as exc:
            logger.warning("PyMuPDF failed to parse document structure: %s", type(exc).__name__)
            raise InvalidPDFError("Corrupted or malformed PDF document structure.") from exc

        # 1. Check encryption / password protection
        if doc.is_encrypted or doc.needs_pass:
            doc.close()
            logger.warning("Rejected password-protected / encrypted PDF")
            raise PasswordProtectedPDFError("Password-protected or encrypted PDFs are not supported.")

        # 2. Check page count
        page_count = len(doc)
        if page_count == 0:
            doc.close()
            raise EmptyPDFError("PDF document contains zero pages.")

        if page_count > max_pages:
            doc.close()
            logger.warning("Rejected PDF with %d pages (limit: %d)", page_count, max_pages)
            raise OversizedPageCountError(
                f"PDF page count ({page_count}) exceeds maximum allowed limit of {max_pages} pages."
            )

        return doc
