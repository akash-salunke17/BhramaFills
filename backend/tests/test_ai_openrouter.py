"""Automated tests for OpenRouter AI provider integration, Nemotron model, and response parser."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.services.ai.base import BaseAIProvider
from app.services.ai.exceptions import (
    AIAuthenticationError,
    AIProviderError,
    AIProviderUnavailableError,
    AIQuotaExceededError,
    AIRateLimitError,
    AIResponseValidationError,
    AITimeoutError,
)
from app.services.ai.openrouter_client import OpenRouterClient
from app.services.ai.parser import SafeResponseParser
from app.services.ai.schemas import (
    AIConfigStatus,
    ChatChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    UsageInfo,
)


# =============================================================================
# 1. Configuration & Settings Tests
# =============================================================================

def test_openrouter_default_settings():
    """Verify default OpenRouter configuration values when unconfigured."""
    settings = Settings(
        OPENROUTER_API_KEY=None,
        _env_file=None,
    )
    assert settings.OPENROUTER_MODEL == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert settings.OPENROUTER_BASE_URL == "https://openrouter.ai/api/v1"
    assert settings.OPENROUTER_TIMEOUT_SECONDS == 30.0
    assert settings.OPENROUTER_API_KEY is None
    assert settings.is_ai_configured is False


def test_openrouter_configured_settings_and_masking():
    """Verify settings with valid API key report is_ai_configured correctly."""
    settings = Settings(
        OPENROUTER_API_KEY="sk-or-v1-abcdef1234567890abcdef",
        OPENROUTER_MODEL="custom/model-identifier",
        OPENROUTER_BASE_URL="https://custom.openrouter.ai/api/v1/",
        OPENROUTER_TIMEOUT_SECONDS=45.0,
        _env_file=None,
    )
    assert settings.is_ai_configured is True
    assert settings.OPENROUTER_MODEL == "custom/model-identifier"
    assert settings.OPENROUTER_BASE_URL == "https://custom.openrouter.ai/api/v1"
    assert settings.OPENROUTER_TIMEOUT_SECONDS == 45.0


def test_openrouter_api_key_whitespace_trimmed():
    """Verify empty or whitespace-only keys evaluate to None."""
    settings = Settings(OPENROUTER_API_KEY="   ", _env_file=None)
    assert settings.OPENROUTER_API_KEY is None
    assert settings.is_ai_configured is False


def test_openrouter_invalid_base_url_scheme_raises():
    """Verify non-HTTP schemes are rejected."""
    with pytest.raises(ValueError, match="OPENROUTER_BASE_URL must start with https:// or http://"):
        Settings(OPENROUTER_BASE_URL="ftp://openrouter.ai/api", _env_file=None)


# =============================================================================
# 2. Schema Envelope & Model Tests
# =============================================================================

def test_chat_message_validation():
    """Verify ChatMessage accepts valid roles and rejects invalid roles."""
    msg = ChatMessage(role="user", content="Hello test")
    assert msg.role == "user"
    assert msg.content == "Hello test"

    with pytest.raises(Exception):
        ChatMessage(role="unsupported_role", content="Fail")


def test_chat_completion_response_properties():
    """Verify ChatCompletionResponse helper properties."""
    resp = ChatCompletionResponse(
        id="gen-123",
        model="nvidia/nemotron-3-ultra-550b-a55b:free",
        choices=[
            ChatChoice(
                index=0,
                message=ChatMessage(role="assistant", content="Response content text"),
                finish_reason="stop",
            )
        ],
        usage=UsageInfo(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    assert resp.first_content == "Response content text"
    assert resp.usage.total_tokens == 15


# =============================================================================
# 3. OpenRouterClient Complete (Mocked HTTP Responses)
# =============================================================================

@pytest.mark.asyncio
async def test_client_unconfigured_raises_auth_error():
    """Verify complete() immediately raises AIAuthenticationError without making network call."""
    settings = Settings(OPENROUTER_API_KEY=None, _env_file=None)
    client = OpenRouterClient(settings=settings)

    with pytest.raises(AIAuthenticationError) as exc_info:
        await client.complete([ChatMessage(role="user", content="ping")])

    assert "OPENROUTER_API_KEY" in exc_info.value.message
    await client.close()


@pytest.mark.asyncio
async def test_client_successful_completion():
    """Verify complete() returns ChatCompletionResponse on HTTP 200."""
    settings = Settings(OPENROUTER_API_KEY="sk-or-v1-mock-key-123456", _env_file=None)

    mock_response = {
        "id": "chatcmpl-999",
        "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Evidence analysis result."},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 25, "completion_tokens": 10, "total_tokens": 35},
    }

    mock_http_client = AsyncMock(spec=httpx.AsyncClient)
    mock_http_resp = MagicMock(spec=httpx.Response)
    mock_http_resp.status_code = 200
    mock_http_resp.json.return_value = mock_response
    mock_http_client.post.return_value = mock_http_resp

    client = OpenRouterClient(settings=settings, http_client=mock_http_client)
    res = await client.complete([ChatMessage(role="user", content="Analyze topic")])

    assert res.id == "chatcmpl-999"
    assert res.model == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert res.first_content == "Evidence analysis result."
    assert res.usage.total_tokens == 35

    # Verify authorization header had bearer token without logging key
    call_kwargs = mock_http_client.post.call_args[1]
    assert call_kwargs["headers"]["Authorization"] == "Bearer sk-or-v1-mock-key-123456"
    assert call_kwargs["json"]["model"] == "nvidia/nemotron-3-ultra-550b-a55b:free"


@pytest.mark.asyncio
async def test_client_authentication_failure_401():
    """Verify HTTP 401 raises AIAuthenticationError without retrying."""
    settings = Settings(OPENROUTER_API_KEY="sk-or-v1-invalid", _env_file=None)

    mock_http_client = AsyncMock(spec=httpx.AsyncClient)
    mock_http_resp = MagicMock(spec=httpx.Response)
    mock_http_resp.status_code = 401
    mock_http_resp.text = "Unauthorized"
    mock_http_client.post.return_value = mock_http_resp

    client = OpenRouterClient(settings=settings, http_client=mock_http_client)
    with pytest.raises(AIAuthenticationError) as exc_info:
        await client.complete([ChatMessage(role="user", content="Hi")])

    assert exc_info.value.status_code == 401
    assert "sk-or-v1-invalid" not in str(exc_info.value)
    # Should fail immediately without retry
    assert mock_http_client.post.call_count == 1


@pytest.mark.asyncio
async def test_client_quota_exceeded_402():
    """Verify HTTP 402 raises AIQuotaExceededError."""
    settings = Settings(OPENROUTER_API_KEY="sk-or-v1-valid", _env_file=None)

    mock_http_client = AsyncMock(spec=httpx.AsyncClient)
    mock_http_resp = MagicMock(spec=httpx.Response)
    mock_http_resp.status_code = 402
    mock_http_resp.text = "Payment Required / Insufficient credits"
    mock_http_client.post.return_value = mock_http_resp

    client = OpenRouterClient(settings=settings, http_client=mock_http_client)
    with pytest.raises(AIQuotaExceededError) as exc_info:
        await client.complete([ChatMessage(role="user", content="Hi")])

    assert exc_info.value.status_code == 402
    assert mock_http_client.post.call_count == 1


@pytest.mark.asyncio
async def test_client_rate_limit_429():
    """Verify HTTP 429 retries bounded times and raises AIRateLimitError."""
    settings = Settings(OPENROUTER_API_KEY="sk-or-v1-valid", _env_file=None)

    mock_http_client = AsyncMock(spec=httpx.AsyncClient)
    mock_http_resp = MagicMock(spec=httpx.Response)
    mock_http_resp.status_code = 429
    mock_http_resp.headers = {"Retry-After": "0.01"}
    mock_http_client.post.return_value = mock_http_resp

    client = OpenRouterClient(settings=settings, http_client=mock_http_client)
    with pytest.raises(AIRateLimitError) as exc_info:
        await client.complete([ChatMessage(role="user", content="Hi")])

    assert exc_info.value.status_code == 429
    # Initial attempt + 2 retries = 3 attempts total
    assert mock_http_client.post.call_count == 3


@pytest.mark.asyncio
async def test_client_upstream_server_error_503():
    """Verify HTTP 503 retries bounded times and raises AIProviderUnavailableError."""
    settings = Settings(OPENROUTER_API_KEY="sk-or-v1-valid", _env_file=None)

    mock_http_client = AsyncMock(spec=httpx.AsyncClient)
    mock_http_resp = MagicMock(spec=httpx.Response)
    mock_http_resp.status_code = 503
    mock_http_resp.text = "Service Unavailable"
    mock_http_client.post.return_value = mock_http_resp

    client = OpenRouterClient(settings=settings, http_client=mock_http_client)
    with pytest.raises(AIProviderUnavailableError) as exc_info:
        await client.complete([ChatMessage(role="user", content="Hi")])

    assert exc_info.value.status_code == 503
    assert mock_http_client.post.call_count == 3


@pytest.mark.asyncio
async def test_client_timeout_raises_ai_timeout_error():
    """Verify httpx.TimeoutException retries and raises AITimeoutError."""
    settings = Settings(OPENROUTER_API_KEY="sk-or-v1-valid", OPENROUTER_TIMEOUT_SECONDS=10.0, _env_file=None)

    mock_http_client = AsyncMock(spec=httpx.AsyncClient)
    mock_http_client.post.side_effect = httpx.ReadTimeout("Timeout reading stream")

    client = OpenRouterClient(settings=settings, http_client=mock_http_client)
    with pytest.raises(AITimeoutError) as exc_info:
        await client.complete([ChatMessage(role="user", content="Hi")])

    assert exc_info.value.status_code == 504
    assert mock_http_client.post.call_count == 3


@pytest.mark.asyncio
async def test_client_malformed_response_raises_validation_error():
    """Verify response missing 'choices' raises AIResponseValidationError."""
    settings = Settings(OPENROUTER_API_KEY="sk-or-v1-valid", _env_file=None)

    mock_http_client = AsyncMock(spec=httpx.AsyncClient)
    mock_http_resp = MagicMock(spec=httpx.Response)
    mock_http_resp.status_code = 200
    mock_http_resp.json.return_value = {"id": "bad-resp", "choices": []}
    mock_http_client.post.return_value = mock_http_resp

    client = OpenRouterClient(settings=settings, http_client=mock_http_client)
    with pytest.raises(AIResponseValidationError):
        await client.complete([ChatMessage(role="user", content="Hi")])


# =============================================================================
# 4. SafeResponseParser Tests (Structured Output Verification)
# =============================================================================

class MockAuditSchema(BaseModel):
    summary: str
    detected_gaps_count: int
    confidence: float


def test_parser_extracts_clean_json_object():
    """Verify SafeResponseParser decodes direct JSON strings."""
    raw = '{"summary": "No gaps found in source.", "detected_gaps_count": 0, "confidence": 0.95}'
    result = SafeResponseParser.parse_model_output(raw, MockAuditSchema)

    assert result.is_valid is True
    assert result.parsed_data is not None
    assert result.parsed_data.summary == "No gaps found in source."
    assert result.parsed_data.detected_gaps_count == 0
    assert result.parsed_data.confidence == 0.95
    assert result.validation_error is None


def test_parser_extracts_markdown_fenced_json():
    """Verify SafeResponseParser strips markdown ```json code blocks."""
    raw = """
    Here is your audit analysis:
    ```json
    {
      "summary": "Identified 2 unaddressed eligibility criteria.",
      "detected_gaps_count": 2,
      "confidence": 0.88
    }
    ```
    Hope this helps!
    """
    result = SafeResponseParser.parse_model_output(raw, MockAuditSchema)

    assert result.is_valid is True
    assert result.parsed_data.detected_gaps_count == 2
    assert result.validation_error is None


def test_parser_extracts_embedded_json_substring():
    """Verify SafeResponseParser extracts balanced braces from prose text."""
    raw = 'Analysis output: {"summary": "Embedded JSON", "detected_gaps_count": 1, "confidence": 0.75} End of output.'
    result = SafeResponseParser.parse_model_output(raw, MockAuditSchema)

    assert result.is_valid is True
    assert result.parsed_data.summary == "Embedded JSON"


def test_parser_handles_malformed_json_gracefully():
    """Verify SafeResponseParser rejects invalid JSON syntax without raising exception."""
    raw = '{"summary": "Broken JSON", "detected_gaps_count": '
    result = SafeResponseParser.parse_model_output(raw, MockAuditSchema)

    assert result.is_valid is False
    assert result.parsed_data is None
    assert "JSON decoding error" in result.validation_error


def test_parser_handles_schema_mismatch_without_inventing_fields():
    """Verify SafeResponseParser rejects schema violations without fabricating missing data."""
    # Missing required field 'confidence'
    raw = '{"summary": "Missing confidence field", "detected_gaps_count": 1}'
    result = SafeResponseParser.parse_model_output(raw, MockAuditSchema)

    assert result.is_valid is False
    assert result.parsed_data is None
    assert "Schema validation failed" in result.validation_error
    assert "confidence" in result.validation_error


def test_parser_handles_empty_or_non_json_text():
    """Verify SafeResponseParser rejects pure conversational text."""
    raw = "I am an AI and I cannot find any structured information."
    result = SafeResponseParser.parse_model_output(raw, MockAuditSchema)

    assert result.is_valid is False
    assert "No JSON structure detected" in result.validation_error


# =============================================================================
# 5. Health Probe & Status Inspection Tests (GET /api/v1/health/ai)
# =============================================================================

def test_api_health_ai_not_configured(client: TestClient, app: FastAPI):
    """Verify GET /api/v1/health/ai returns not_configured when no API key is set."""
    mock_ai = MagicMock(spec=BaseAIProvider)
    mock_ai.check_health = AsyncMock(
        return_value=AIConfigStatus(
            status="not_configured",
            provider="openrouter",
            model="nvidia/nemotron-3-ultra-550b-a55b:free",
            base_url="https://openrouter.ai/api/v1",
            is_free_tier=True,
        )
    )

    from app.services.ai import get_ai_provider
    app.dependency_overrides[get_ai_provider] = lambda: mock_ai

    resp = client.get("/api/v1/health/ai")
    assert resp.status_code == 200

    data = resp.json()
    assert data["status"] == "not_configured"
    assert data["provider"] == "openrouter"
    assert data["model"] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert data["is_free_tier"] is True
    # Ensure no key-derived material is exposed in the response
    assert "masked_api_key" not in data
    assert "NEVER transmit confidential" in data["privacy_warning"]


def test_api_health_ai_configured(client: TestClient, app: FastAPI):
    """Verify GET /api/v1/health/ai returns configured status when API key is set."""
    mock_ai = MagicMock(spec=BaseAIProvider)
    mock_ai.check_health = AsyncMock(
        return_value=AIConfigStatus(
            status="configured",
            provider="openrouter",
            model="nvidia/nemotron-3-ultra-550b-a55b:free",
            base_url="https://openrouter.ai/api/v1",
            is_free_tier=True,
        )
    )

    from app.services.ai import get_ai_provider
    app.dependency_overrides[get_ai_provider] = lambda: mock_ai

    resp = client.get("/api/v1/health/ai")
    assert resp.status_code == 200

    data = resp.json()
    assert data["status"] == "configured"
    # Ensure no key-derived material is ever exposed in the response
    assert "masked_api_key" not in data
    assert "sk-" not in str(data)


def test_api_health_ai_response_never_contains_key_material(client: TestClient, app: FastAPI):
    """Verify health AI response never contains API key prefix, suffix, or any credential fragment."""
    mock_ai = MagicMock(spec=BaseAIProvider)
    mock_ai.check_health = AsyncMock(
        return_value=AIConfigStatus(
            status="configured",
            provider="openrouter",
            model="nvidia/nemotron-3-ultra-550b-a55b:free",
            base_url="https://openrouter.ai/api/v1",
            is_free_tier=True,
        )
    )

    from app.services.ai import get_ai_provider
    app.dependency_overrides[get_ai_provider] = lambda: mock_ai

    resp = client.get("/api/v1/health/ai")
    assert resp.status_code == 200
    response_text = resp.text

    # No key material in any form
    assert "masked_api_key" not in response_text
    assert "sk-or" not in response_text
    assert "sk-o..." not in response_text
    assert "Authorization" not in response_text


@pytest.mark.asyncio
async def test_api_health_ai_makes_no_external_http_requests():
    """Verify check_health() makes zero external HTTP requests (no quota consumption)."""
    settings = Settings(OPENROUTER_API_KEY="sk-or-v1-test-key", _env_file=None)
    mock_http_client = AsyncMock(spec=httpx.AsyncClient)

    client = OpenRouterClient(settings=settings, http_client=mock_http_client)
    result = await client.check_health()

    # check_health must NOT call the HTTP client
    mock_http_client.post.assert_not_called()
    mock_http_client.get.assert_not_called()
    assert result.status == "configured"
    assert result.provider == "openrouter"


def test_health_ai_documented_in_openapi(client: TestClient):
    """Verify GET /api/v1/health/ai is documented in the OpenAPI specification."""
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()

    assert "/api/v1/health/ai" in schema["paths"]
    assert "get" in schema["paths"]["/api/v1/health/ai"]

