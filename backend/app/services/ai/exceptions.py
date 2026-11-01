"""Domain exceptions for AI providers and LLM integration in Bharmafills."""


class AIProviderError(Exception):
    """Base exception for all AI provider integration failures.

    Guarantees that sensitive credentials or raw API keys are never leaked in error messages.
    """

    def __init__(
        self,
        message: str,
        provider: str = "openrouter",
        status_code: int = 500,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.status_code = status_code

    def __str__(self) -> str:
        return f"[{self.provider}] {self.message}"


class AIAuthenticationError(AIProviderError):
    """Raised when the AI provider rejects the API key or authentication fails (HTTP 401/403)."""

    def __init__(
        self,
        message: str = "Invalid or missing AI provider API key. Check OPENROUTER_API_KEY in backend/.env.",
        provider: str = "openrouter",
    ) -> None:
        super().__init__(message=message, provider=provider, status_code=401)


class AIRateLimitError(AIProviderError):
    """Raised when the AI provider throttles requests due to rate limits (HTTP 429)."""

    def __init__(
        self,
        message: str = "AI provider rate limit exceeded. Please retry after backoff.",
        provider: str = "openrouter",
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message=message, provider=provider, status_code=429)
        self.retry_after = retry_after


class AIQuotaExceededError(AIProviderError):
    """Raised when the account has insufficient credits or quota exhausted (HTTP 402)."""

    def __init__(
        self,
        message: str = "AI provider account quota or credits exhausted.",
        provider: str = "openrouter",
    ) -> None:
        super().__init__(message=message, provider=provider, status_code=402)


class AIProviderUnavailableError(AIProviderError):
    """Raised when the AI provider is down, unreachable, or returns 502/503."""

    def __init__(
        self,
        message: str = "AI provider service is currently unavailable.",
        provider: str = "openrouter",
        status_code: int = 503,
    ) -> None:
        super().__init__(message=message, provider=provider, status_code=status_code)


class AITimeoutError(AIProviderError):
    """Raised when a request to the AI provider times out."""

    def __init__(
        self,
        message: str = "Request to AI provider timed out.",
        provider: str = "openrouter",
        timeout_seconds: float = 30.0,
    ) -> None:
        super().__init__(message=message, provider=provider, status_code=504)
        self.timeout_seconds = timeout_seconds


class AIResponseValidationError(AIProviderError):
    """Raised when the AI provider returns an unparseable, malformed, or unexpected response."""

    def __init__(
        self,
        message: str = "Failed to parse or validate AI provider response.",
        provider: str = "openrouter",
    ) -> None:
        super().__init__(message=message, provider=provider, status_code=502)


class AIContentPolicyError(AIProviderError):
    """Raised when the AI provider flags prompt or completion content as violating policy."""

    def __init__(
        self,
        message: str = "AI provider flagged or blocked the request under content policy.",
        provider: str = "openrouter",
    ) -> None:
        super().__init__(message=message, provider=provider, status_code=422)

