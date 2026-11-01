"""OpenRouter AI provider implementation using HTTPX async client."""

import asyncio
import logging
from typing import Any
import httpx
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.services.ai.base import BaseAIProvider
from app.services.ai.exceptions import (
    AIAuthenticationError,
    AIContentPolicyError,
    AIProviderError,
    AIProviderUnavailableError,
    AIQuotaExceededError,
    AIRateLimitError,
    AIResponseValidationError,
    AITimeoutError,
)
from app.services.ai.schemas import (
    AIConfigStatus,
    ChatChoice,
    ChatCompletionResponse,
    ChatMessage,
    UsageInfo,
)

logger = logging.getLogger(__name__)

# Constants for bounded retry strategy
MAX_TRANSIENT_RETRIES = 2
INITIAL_BACKOFF_SECONDS = 1.0


class OpenRouterClient(BaseAIProvider):
    """Asynchronous client for OpenRouter API completions with connection pooling and resilience."""

    def __init__(
        self,
        settings: Settings | None = None,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the OpenRouter client.

        Args:
            settings: Settings instance. Defaults to get_settings().
            api_key: Optional explicit API key override.
            model: Optional model identifier override.
            base_url: Optional base URL override.
            timeout_seconds: Optional timeout override.
            http_client: Optional pre-configured httpx.AsyncClient (useful for testing/mocking).
        """
        self._settings = settings or get_settings()
        self._api_key = api_key if api_key is not None else self._settings.OPENROUTER_API_KEY
        self._model = model or self._settings.OPENROUTER_MODEL
        self._base_url = (base_url or self._settings.OPENROUTER_BASE_URL).rstrip("/")
        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else self._settings.OPENROUTER_TIMEOUT_SECONDS
        )

        self._injected_client = http_client
        self._owned_client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        """Return True if an API key is configured."""
        return bool(self._api_key and self._api_key.strip())

    @property
    def active_model(self) -> str:
        """Return the current active model identifier."""
        return self._model

    @property
    def base_url(self) -> str:
        """Return the configured OpenRouter base URL."""
        return self._base_url

    def _get_client(self) -> httpx.AsyncClient:
        """Retrieve the active reusable httpx.AsyncClient instance."""
        if self._injected_client is not None:
            return self._injected_client
        if self._owned_client is None or self._owned_client.is_closed:
            self._owned_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=min(5.0, self._timeout_seconds),
                    read=self._timeout_seconds,
                    write=self._timeout_seconds,
                    pool=self._timeout_seconds,
                ),
                headers={
                    "HTTP-Referer": "https://bharmafills.hackathon",
                    "X-Title": "Bharmafills",
                    "User-Agent": "Bharmafills-OpenRouter/1.0",
                },
            )
        return self._owned_client

    async def complete(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> ChatCompletionResponse:
        """Generate a chat completion from OpenRouter.

        Args:
            messages: List of structured ChatMessage instances.
            model: Model identifier override (defaults to configured model).
            temperature: Sampling temperature override.
            max_tokens: Max tokens to generate override.
            **kwargs: Extra parameters passed to the request body.

        Returns:
            ChatCompletionResponse envelope.

        Raises:
            AIAuthenticationError: Missing or invalid API key.
            AIRateLimitError: Rate limit exceeded.
            AIQuotaExceededError: Out of credits.
            AIProviderUnavailableError: Upstream server error.
            AITimeoutError: Request timed out.
            AIResponseValidationError: Malformed or unexpected response payload.
        """
        if not self.is_configured:
            raise AIAuthenticationError(
                message="OpenRouter API key is not configured. Add OPENROUTER_API_KEY to backend/.env."
            )

        target_model = model or self._model
        endpoint = f"{self._base_url}/chat/completions"

        payload: dict[str, Any] = {
            "model": target_model,
            "messages": [msg.model_dump() for msg in messages],
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        payload.update(kwargs)

        headers = {
            "Authorization": f"Bearer {self._api_key.strip()}",
            "Content-Type": "application/json",
        }

        client = self._get_client()
        attempts = 0
        backoff = INITIAL_BACKOFF_SECONDS

        while True:
            attempts += 1
            try:
                response = await client.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                )
            except httpx.TimeoutException as exc:
                if attempts <= MAX_TRANSIENT_RETRIES:
                    logger.warning(
                        "OpenRouter timeout on attempt %d/%d; retrying in %.1fs...",
                        attempts,
                        MAX_TRANSIENT_RETRIES + 1,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                raise AITimeoutError(
                    message=f"OpenRouter request timed out after {self._timeout_seconds}s.",
                    timeout_seconds=self._timeout_seconds,
                ) from exc
            except (httpx.NetworkError, httpx.ConnectError) as exc:
                if attempts <= MAX_TRANSIENT_RETRIES:
                    logger.warning(
                        "OpenRouter network error on attempt %d/%d; retrying in %.1fs...",
                        attempts,
                        MAX_TRANSIENT_RETRIES + 1,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                raise AIProviderUnavailableError(
                    message="Failed to connect to OpenRouter API (network or DNS failure)."
                ) from exc

            # Status Code Evaluation
            status_code = response.status_code

            if status_code == 200:
                try:
                    data = response.json()
                except Exception as exc:
                    raise AIResponseValidationError(
                        message="OpenRouter returned non-JSON HTTP 200 response body."
                    ) from exc

                try:
                    return self._parse_completion_response(data)
                except (ValidationError, KeyError, TypeError) as exc:
                    raise AIResponseValidationError(
                        message=f"Failed to parse OpenRouter response schema: {exc}"
                    ) from exc

            if status_code in (401, 403):
                # Non-retryable authentication failure
                raise AIAuthenticationError(
                    message="OpenRouter rejected API key (HTTP 401/403 Unauthorized)."
                )

            if status_code == 402:
                # Non-retryable quota/credit error
                raise AIQuotaExceededError(
                    message="OpenRouter account has insufficient credits or quota is exhausted."
                )

            if status_code == 429:
                retry_after_header = response.headers.get("Retry-After")
                retry_after = float(retry_after_header) if retry_after_header else None
                if attempts <= MAX_TRANSIENT_RETRIES:
                    sleep_time = retry_after if retry_after is not None else backoff
                    logger.warning(
                        "OpenRouter rate limited (429) on attempt %d/%d; waiting %.1fs...",
                        attempts,
                        MAX_TRANSIENT_RETRIES + 1,
                        sleep_time,
                    )
                    await asyncio.sleep(sleep_time)
                    backoff *= 2
                    continue
                raise AIRateLimitError(
                    message="OpenRouter rate limit exceeded. Retry after backoff.",
                    retry_after=retry_after,
                )

            if status_code in (500, 502, 503, 504):
                if attempts <= MAX_TRANSIENT_RETRIES:
                    logger.warning(
                        "OpenRouter server error (%d) on attempt %d/%d; retrying in %.1fs...",
                        status_code,
                        attempts,
                        MAX_TRANSIENT_RETRIES + 1,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                raise AIProviderUnavailableError(
                    message=f"OpenRouter service returned upstream error HTTP {status_code}.",
                    status_code=status_code,
                )

            # Unhandled status codes
            error_preview = response.text[:200] if response.text else "No details"
            raise AIProviderError(
                message=f"OpenRouter unexpected HTTP status {status_code}: {error_preview}",
                status_code=status_code,
            )

    def _parse_completion_response(self, data: dict[str, Any]) -> ChatCompletionResponse:
        """Translate raw OpenRouter completion JSON into ChatCompletionResponse."""
        choices_raw = data.get("choices")
        if not isinstance(choices_raw, list) or len(choices_raw) == 0:
            raise AIResponseValidationError(
                message="OpenRouter response missing valid 'choices' array."
            )

        choices: list[ChatChoice] = []
        for item in choices_raw:
            msg_raw = item.get("message", {})
            role = msg_raw.get("role", "assistant")
            content = msg_raw.get("content", "")
            choices.append(
                ChatChoice(
                    index=item.get("index", 0),
                    message=ChatMessage(role=role, content=content),
                    finish_reason=item.get("finish_reason"),
                )
            )

        usage: UsageInfo | None = None
        if "usage" in data and isinstance(data["usage"], dict):
            u = data["usage"]
            usage = UsageInfo(
                prompt_tokens=u.get("prompt_tokens", 0),
                completion_tokens=u.get("completion_tokens", 0),
                total_tokens=u.get("total_tokens", 0),
            )

        return ChatCompletionResponse(
            id=str(data.get("id", "completion-unknown")),
            model=str(data.get("model", self._model)),
            choices=choices,
            usage=usage,
        )

    async def check_health(self) -> AIConfigStatus:
        """Return safe configuration status without consuming API quota.

        Never includes any credential-derived information in the response.
        """
        if not self.is_configured:
            return AIConfigStatus(
                status="not_configured",
                provider="openrouter",
                model=self._model,
                base_url=self._base_url,
                is_free_tier=True,
            )

        return AIConfigStatus(
            status="configured",
            provider="openrouter",
            model=self._model,
            base_url=self._base_url,
            is_free_tier=True,
        )

    async def close(self) -> None:
        """Safely close underlying HTTP client connection pool."""
        if self._owned_client is not None and not self._owned_client.is_closed:
            await self._owned_client.aclose()
            self._owned_client = None

