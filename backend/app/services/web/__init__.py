"""Web content extraction and SSRF-safe fetching package for Bharmafills."""

from app.services.web.content_extractor import WebContentExtractor
from app.services.web.exceptions import (
    ContentTooLargeError,
    FetchNetworkError,
    FetchTimeoutError,
    InvalidURLError,
    SSRFBlockedError,
    UnsafeRedirectError,
    UnsupportedContentTypeError,
    WebExtractionError,
)
from app.services.web.safe_fetcher import FetchedWebContent, SafeWebFetcher, get_safe_fetcher
from app.services.web.schemas import HeadingItem, WebExtractRequest, WebExtractResponse
from app.services.web.url_validator import URLValidator

__all__ = [
    "URLValidator",
    "SafeWebFetcher",
    "get_safe_fetcher",
    "FetchedWebContent",
    "WebContentExtractor",
    "WebExtractRequest",
    "WebExtractResponse",
    "HeadingItem",
    "WebExtractionError",
    "InvalidURLError",
    "SSRFBlockedError",
    "UnsafeRedirectError",
    "ContentTooLargeError",
    "UnsupportedContentTypeError",
    "FetchTimeoutError",
    "FetchNetworkError",
]

