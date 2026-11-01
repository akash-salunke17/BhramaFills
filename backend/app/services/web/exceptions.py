"""Custom domain exceptions for secure web extraction and SSRF defense."""


class WebExtractionError(Exception):
    """Base exception for all web extraction and fetching errors."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class InvalidURLError(WebExtractionError):
    """Raised when a provided URL fails syntax, scheme, or formatting rules."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=400)


class SSRFBlockedError(WebExtractionError):
    """Raised when a destination resolves to a private, loopback, or prohibited network range."""

    def __init__(self, message: str = "Destination IP address is prohibited by SSRF security policy.") -> None:
        super().__init__(message, status_code=400)


class UnsafeRedirectError(WebExtractionError):
    """Raised when an HTTP redirect violates security policies (loop, SSRF target, downgrade)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=400)


class ContentTooLargeError(WebExtractionError):
    """Raised when fetched HTTP response body exceeds maximum allowed size."""

    def __init__(self, message: str = "Response body exceeds maximum allowed size of 2 MB.") -> None:
        super().__init__(message, status_code=413)


class UnsupportedContentTypeError(WebExtractionError):
    """Raised when HTTP response Content-Type is not supported HTML or XHTML."""

    def __init__(self, content_type: str) -> None:
        super().__init__(
            f"Unsupported Content-Type '{content_type}'. Expected 'text/html' or 'application/xhtml+xml'.",
            status_code=422,
        )


class FetchTimeoutError(WebExtractionError):
    """Raised when a network connection or read operation exceeds timeout limits."""

    def __init__(self, message: str = "Web request timed out.") -> None:
        super().__init__(message, status_code=504)


class FetchNetworkError(WebExtractionError):
    """Raised when a network, DNS, or socket failure prevents successful connection."""

    def __init__(self, message: str = "Failed to establish network connection to target host.") -> None:
        super().__init__(message, status_code=502)

