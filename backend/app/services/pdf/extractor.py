"""Page-by-page text extraction and metadata parser utilizing PyMuPDF."""

from datetime import datetime, timezone
import hashlib
import logging
import re

import pymupdf

from app.services.pdf.schemas import PDFExtractResult, PDFPageItem
from app.services.pdf.validator import PDFValidator

logger = logging.getLogger("bharmafills.services.pdf.extractor")


def _clean_meta_string(val: str | None) -> str | None:
    """Strip whitespace and return None if string is empty or absent."""
    if not val or not isinstance(val, str):
        return None
    cleaned = val.strip()
    return cleaned if cleaned else None


class PDFExtractor:
    """Extracts page-by-page clean text, metrics, document metadata, and hashes from PDF binaries."""

    @classmethod
    def extract(
        cls,
        pdf_bytes: bytes,
        max_pages: int = 200,
    ) -> PDFExtractResult:
        """Parse PDF document and produce a structured PDFExtractResult.

        Guarantees:
        - Page numbering starts at 1.
        - Identifies empty / scanned pages.
        - Whitespace is normalized conservatively.
        - PyMuPDF Document resources are closed in a finally block.
        """
        binary_hash = hashlib.sha256(pdf_bytes).hexdigest()
        doc = PDFValidator.open_and_validate_structure(pdf_bytes, max_pages=max_pages)

        try:
            # 1. Parse document metadata
            meta = doc.metadata or {}
            title = _clean_meta_string(meta.get("title"))
            author = _clean_meta_string(meta.get("author"))
            subject = _clean_meta_string(meta.get("subject"))
            creator = _clean_meta_string(meta.get("creator"))
            producer = _clean_meta_string(meta.get("producer"))
            creation_date = _clean_meta_string(meta.get("creationDate"))
            modification_date = _clean_meta_string(meta.get("modDate"))
            pdf_version = _clean_meta_string(meta.get("format"))

            # 2. Extract page-by-page content
            pages: list[PDFPageItem] = []
            empty_pages: list[int] = []
            extracted_pages_count = 0

            for page_idx in range(len(doc)):
                page = doc[page_idx]
                page_number = page_idx + 1  # 1-based page numbering

                raw_text = page.get_text("text")

                # Normalize lines and whitespace
                lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw_text.splitlines()]
                clean_text = "\n".join(lines).strip()
                clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)

                char_count = len(clean_text)
                word_count = len(clean_text.split()) if clean_text else 0
                has_text = bool(clean_text)

                if has_text:
                    extracted_pages_count += 1
                else:
                    empty_pages.append(page_number)

                pages.append(
                    PDFPageItem(
                        page_number=page_number,
                        text=clean_text,
                        character_count=char_count,
                        word_count=word_count,
                        has_text=has_text,
                    )
                )

            # 3. Combine readable text across readable pages
            readable_segments = [p.text for p in pages if p.has_text]
            combined_text = "\n\n".join(readable_segments).strip()
            total_word_count = sum(p.word_count for p in pages)
            total_char_count = sum(p.character_count for p in pages)
            text_hash = hashlib.sha256(combined_text.encode("utf-8")).hexdigest() if combined_text else None

            # 4. Classify document readability status
            total_pages = len(pages)
            if total_pages == 0:
                readability_status = "empty"
            elif len(empty_pages) == total_pages:
                readability_status = "no_extractable_text"
            elif len(empty_pages) == 0:
                readability_status = "fully_readable"
            else:
                readability_status = "partially_readable"

            logger.info(
                "Extracted PDF (%s): %d pages, %d with text (%s), %d words",
                binary_hash[:8],
                total_pages,
                extracted_pages_count,
                readability_status,
                total_word_count,
            )

            return PDFExtractResult(
                title=title,
                author=author,
                subject=subject,
                creator=creator,
                producer=producer,
                creation_date=creation_date,
                modification_date=modification_date,
                page_count=total_pages,
                extracted_pages_count=extracted_pages_count,
                empty_pages=empty_pages,
                pages=pages,
                combined_text=combined_text,
                word_count=total_word_count,
                character_count=total_char_count,
                binary_hash=binary_hash,
                text_hash=text_hash,
                pdf_version=pdf_version,
                readability_status=readability_status,
                extracted_at=datetime.now(timezone.utc),
            )
        finally:
            doc.close()

