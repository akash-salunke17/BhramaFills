"""Abstract base interface for AI providers in Bharmafills."""

from abc import ABC, abstractmethod

from app.services.ai.schemas import (
    AIConfigStatus,
    ChatCompletionResponse,
    ChatMessage,
)


class BaseAIProvider(ABC):
    """Abstract interface decoupling business services from vendor-specific AI SDKs/endpoints."""

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if the provider has necessary API credentials configured."""
        ...

    @property
    @abstractmethod
    def active_model(self) -> str:
        """Return the current active model identifier."""
        ...

    @abstractmethod
    async def complete(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs,
    ) -> ChatCompletionResponse:
        """Generate a chat completion from the AI provider.

        Args:
            messages: List of structured ChatMessage objects.
            model: Optional model override. Defaults to configured provider model.
            temperature: Optional sampling temperature override.
            max_tokens: Optional token generation cap.
            **kwargs: Extra vendor-specific parameters.

        Returns:
            ChatCompletionResponse envelope.

        Raises:
            AIAuthenticationError: If credentials are invalid.
            AIRateLimitError: If rate limits or throttling occur.
            AIQuotaExceededError: If account quota is exhausted.
            AIProviderUnavailableError: If provider service is down.
            AITimeoutError: If request times out.
            AIResponseValidationError: If response is malformed.
        """
        ...

    @abstractmethod
    async def check_health(self) -> AIConfigStatus:
        """Inspect provider configuration and return a safe status descriptor."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Safely release underlying HTTP clients or network resources."""
        ...

