"""API route handlers for secure web fetching and content extraction."""

import logging
from fastapi import APIRouter, Depends, HTTPException, status

from app.services.web import (
    SafeWebFetcher,
    WebContentExtractor,
    WebExtractRequest,
    WebExtractResponse,
    WebExtractionError,
    get_safe_fetcher,
)

logger = logging.getLogger("bharmafills.api.web")

router = APIRouter(prefix="/web", tags=["web"])


@router.post(
    "/extract",
    response_model=WebExtractResponse,
    status_code=status.HTTP_200_OK,
    summary="Safely fetch and extract clean content from a public web URL",
    description="Validates target URL against SSRF policy, fetches HTML safely with streaming limits, and extracts readable text.",
    responses={
        400: {"description": "Invalid URL syntax or SSRF policy violation"},
        413: {"description": "HTML response exceeded maximum allowed size of 2 MB"},
        422: {"description": "Unsupported Content-Type (non-HTML)"},
        502: {"description": "Upstream network connection error"},
        504: {"description": "Upstream connection or read timeout"},
    },
)
async def extract_web_content(
    payload: WebExtractRequest,
    fetcher: SafeWebFetcher = Depends(get_safe_fetcher),
) -> WebExtractResponse:
    """Fetch URL with SSRF defenses, follow safe redirects, and parse structured text."""
    try:
        fetched = await fetcher.fetch(payload.url)
    except WebExtractionError as exc:
        logger.warning("Web extraction failed for URL '%s': %s", payload.url, exc.message)
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error fetching URL '%s': %s", payload.url, type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing web extraction.",
        ) from exc

    # Parse and extract clean structured text and metadata
    try:
        extracted = WebContentExtractor.extract(
            html=fetched.html_content,
            original_url=fetched.url,
            final_url=fetched.final_url,
            status_code=fetched.status_code,
            redirect_count=fetched.redirect_count,
        )
        return extracted
    except Exception as exc:
        logger.error("Error extracting HTML for URL '%s': %s", payload.url, type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to parse content from fetched web page.",
        ) from exc

