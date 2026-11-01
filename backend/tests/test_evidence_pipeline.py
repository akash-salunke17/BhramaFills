"""Unit, integration, and endpoint tests for Bharmafills Evidence Extraction Pipeline.

Step 9B.2.2B Test Suite covering:
- Group A: EvidenceExtractionService unit tests (configuration, normalization, error handling)
- Group B: Structured parser and schema integration tests (JSON fencing, validation)
- Group C: Evidence integrity, attribution matching, quote and offset verification
- Group D: Truncation metadata preservation and batch failure isolation
- Group E: FastAPI route integration tests (POST /api/v1/projects/{project_id}/sources/{source_id}/extract)
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, status
from fastapi.testclient import TestClient
import pytest

from app.core.auth import get_current_user
from app.core.ownership import OwnedProjectContext, get_owned_project
from app.core.config import Settings
from app.db.connection import DatabaseNotConfiguredError, DatabaseUnavailableError
from app.services.ai.base import BaseAIProvider
from app.services.ai.evidence_schemas import (
    BatchEvidenceExtractionResult,
    ClaimType,
    EvidenceExtractionPayload,
    EvidenceExtractionResult,
    EvidenceLocation,
    EvidenceSourceType,
    ExtractEvidenceRequest,
    ExtractionStatus,
    ExtractedFact,
    FactType,
    RepresentationType,
    SourceClaim,
)
from app.services.ai.evidence_service import (
    EvidenceExtractionService,
    get_evidence_extraction_service,
)
from app.services.ai.exceptions import (
    AIAuthenticationError,
    AIProviderError,
    AIProviderUnavailableError,
    AIResponseValidationError,
    AITimeoutError,
)
from app.services.ai.prompts import SourceDocument
from app.services.ai.schemas import (
    ChatChoice,
    ChatCompletionResponse,
    ChatMessage,
    UsageInfo,
)
from app.services.sources.exceptions import ProjectNotFoundError, SourceNotFoundError
from app.services.sources.schemas import SourceDetailResponse
from app.services.sources.web_source_service import (
    WebSourceIngestionService,
    get_web_source_service,
)


# =============================================================================
# Test Fixtures & Sample Payloads
# =============================================================================

SAMPLE_SOURCE_ID = "src-climate-2026-001"
SAMPLE_PROJECT_ID = uuid4()
SAMPLE_SOURCE_UUID = uuid4()

SAMPLE_TEXT = (
    "The Antarctic ice sheet lost 252 billion metric tons of ice annually between 2009 and 2017. "
    "Scientists project that sea levels could rise by up to 1 meter by 2100 under high carbon emissions."
)

SAMPLE_MODEL_PAYLOAD_DICT: dict[str, Any] = {
    "facts": [
        {
            "fact_id": "fact-001",
            "statement": "The Antarctic ice sheet lost 252 billion metric tons of ice annually between 2009 and 2017.",
            "fact_type": "statistical",
            "location": {
                "source_id": SAMPLE_SOURCE_ID,
                "source_type": "web",
                "start_char": 0,
                "end_char": 92,
                "url": "https://example.com/antarctic-study",
                "heading_path": ["Introduction", "Ice Loss"],
                "paragraph_index": 0,
            },
            "evidence_text": "The Antarctic ice sheet lost 252 billion metric tons of ice annually between 2009 and 2017.",
            "representation_type": "direct_quote",
            "confidence": 0.96,
            "qualifiers": ["between 2009 and 2017"],
            "uncertainty_notes": None,
            "extraction_warnings": [],
        }
    ],
    "claims": [
        {
            "claim_id": "claim-001",
            "claim_text": "Sea levels could rise by up to 1 meter by 2100 under high carbon emissions.",
            "claim_type": "prediction",
            "source_id": SAMPLE_SOURCE_ID,
            "evidence_location": {
                "source_id": SAMPLE_SOURCE_ID,
                "source_type": "web",
                "start_char": 93,
                "end_char": 192,
                "url": "https://example.com/antarctic-study",
                "heading_path": ["Projections"],
                "paragraph_index": 0,
            },
            "representation_type": "paraphrase",
            "confidence": 0.89,
            "qualifiers": ["under high carbon emissions", "by 2100"],
            "uncertainty_notes": "Projected estimate based on carbon models",
            "extraction_warnings": [],
        }
    ],
    "extraction_warnings": [],
}


def build_mock_completion_response(content: str) -> ChatCompletionResponse:
    """Helper to create a ChatCompletionResponse mock envelope."""
    return ChatCompletionResponse(
        id="chatcmpl-test-001",
        model="nvidia/nemotron-3-ultra-550b-a55b:free",
        choices=[
            ChatChoice(
                index=0,
                message=ChatMessage(role="assistant", content=content),
                finish_reason="stop",
            )
        ],
        usage=UsageInfo(prompt_tokens=150, completion_tokens=85, total_tokens=235),
    )


# =============================================================================
# Group A: EvidenceExtractionService Unit Tests
# =============================================================================

@pytest.mark.asyncio
async def test_service_extract_source_evidence_happy_path():
    """Verify happy-path evidence extraction produces SUCCESS status with facts and claims."""
    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"
    mock_ai.complete.return_value = build_mock_completion_response(json.dumps(SAMPLE_MODEL_PAYLOAD_DICT))

    service = EvidenceExtractionService(ai_provider=mock_ai)
    result = await service.extract_source_evidence(
        source_id=SAMPLE_SOURCE_ID,
        source_type="web",
        content=SAMPLE_TEXT,
        title="Antarctic Study 2026",
        source_url="https://example.com/antarctic-study",
    )

    assert result.source_id == SAMPLE_SOURCE_ID
    assert result.source_type == EvidenceSourceType.WEB
    assert result.extraction_status == ExtractionStatus.SUCCESS
    assert len(result.facts) == 1
    assert len(result.claims) == 1
    assert result.facts[0].fact_id == "fact-001"
    assert result.claims[0].claim_id == "claim-001"
    assert result.source_truncated is False
    assert result.source_character_count == len(SAMPLE_TEXT)
    assert result.processed_character_count == len(SAMPLE_TEXT)
    assert len(result.errors) == 0
    assert isinstance(result.extracted_at, datetime)
    mock_ai.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_extract_source_evidence_pdf_source():
    """Verify PDF source_type is normalized to EvidenceSourceType.PDF."""
    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"

    pdf_payload = {
        "facts": [],
        "claims": [],
        "extraction_warnings": [],
    }
    mock_ai.complete.return_value = build_mock_completion_response(json.dumps(pdf_payload))

    service = EvidenceExtractionService(ai_provider=mock_ai)
    result = await service.extract_source_evidence(
        source_id="pdf-doc-123",
        source_type="pdf",
        content="Sample report text inside a PDF.",
        title="Report.pdf",
    )

    assert result.source_type == EvidenceSourceType.PDF
    assert result.source_id == "pdf-doc-123"
    assert result.extraction_status == ExtractionStatus.SUCCESS


@pytest.mark.asyncio
async def test_service_extract_source_evidence_url_alias():
    """Verify 'url' source_type alias is normalized to EvidenceSourceType.WEB."""
    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"
    mock_ai.complete.return_value = build_mock_completion_response(json.dumps({"facts": [], "claims": [], "extraction_warnings": []}))

    service = EvidenceExtractionService(ai_provider=mock_ai)
    result = await service.extract_source_evidence(
        source_id="src-url-001",
        source_type="url",
        content="Some web content.",
    )

    assert result.source_type == EvidenceSourceType.WEB


@pytest.mark.asyncio
async def test_service_extract_source_empty_content_returns_no_content():
    """Verify empty or pure whitespace content returns NO_CONTENT without calling AI."""
    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True

    service = EvidenceExtractionService(ai_provider=mock_ai)
    result = await service.extract_source_evidence(
        source_id=SAMPLE_SOURCE_ID,
        source_type="web",
        content="",
    )

    assert result.extraction_status == ExtractionStatus.NO_CONTENT
    assert len(result.facts) == 0
    assert len(result.claims) == 0
    assert len(result.warnings) == 1
    assert "no extractable readable text" in result.warnings[0]
    mock_ai.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_extract_source_whitespace_only_content_returns_no_content():
    """Verify whitespace-only content returns NO_CONTENT without calling AI."""
    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True

    service = EvidenceExtractionService(ai_provider=mock_ai)
    result = await service.extract_source_evidence(
        source_id=SAMPLE_SOURCE_ID,
        source_type="web",
        content="   \n\t   ",
    )

    assert result.extraction_status == ExtractionStatus.NO_CONTENT
    mock_ai.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_unconfigured_ai_returns_failed_when_no_raise():
    """Verify unconfigured AI returns FAILED status envelope when raise_on_error=False."""
    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = False

    service = EvidenceExtractionService(ai_provider=mock_ai)
    result = await service.extract_source_evidence(
        source_id=SAMPLE_SOURCE_ID,
        source_type="web",
        content=SAMPLE_TEXT,
        raise_on_error=False,
    )

    assert result.extraction_status == ExtractionStatus.FAILED
    assert len(result.errors) == 1
    assert "OPENROUTER_API_KEY is missing" in result.errors[0]
    mock_ai.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_unconfigured_ai_raises_when_raise_on_error():
    """Verify unconfigured AI raises AIAuthenticationError when raise_on_error=True."""
    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = False

    service = EvidenceExtractionService(ai_provider=mock_ai)
    with pytest.raises(AIAuthenticationError) as exc_info:
        await service.extract_source_evidence(
            source_id=SAMPLE_SOURCE_ID,
            source_type="web",
            content=SAMPLE_TEXT,
            raise_on_error=True,
        )
    assert "OPENROUTER_API_KEY is missing" in exc_info.value.message


@pytest.mark.asyncio
async def test_service_ai_provider_error_handling_no_raise():
    """Verify AIProviderError returns FAILED envelope with error message when raise_on_error=False."""
    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.complete.side_effect = AITimeoutError(message="Connection timed out after 30.0s")

    service = EvidenceExtractionService(ai_provider=mock_ai)
    result = await service.extract_source_evidence(
        source_id=SAMPLE_SOURCE_ID,
        source_type="web",
        content=SAMPLE_TEXT,
        raise_on_error=False,
    )

    assert result.extraction_status == ExtractionStatus.FAILED
    assert len(result.errors) == 1
    assert "timed out" in result.errors[0]


@pytest.mark.asyncio
async def test_service_ai_provider_error_handling_raise_on_error():
    """Verify AIProviderError is re-raised when raise_on_error=True."""
    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.complete.side_effect = AIProviderUnavailableError(message="Provider 503")

    service = EvidenceExtractionService(ai_provider=mock_ai)
    with pytest.raises(AIProviderUnavailableError):
        await service.extract_source_evidence(
            source_id=SAMPLE_SOURCE_ID,
            source_type="web",
            content=SAMPLE_TEXT,
            raise_on_error=True,
        )


@pytest.mark.asyncio
async def test_service_unexpected_exception_handling():
    """Verify unexpected exception is handled gracefully when raise_on_error=False."""
    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.complete.side_effect = RuntimeError("Fatal crash in driver")

    service = EvidenceExtractionService(ai_provider=mock_ai)
    result = await service.extract_source_evidence(
        source_id=SAMPLE_SOURCE_ID,
        source_type="web",
        content=SAMPLE_TEXT,
        raise_on_error=False,
    )

    assert result.extraction_status == ExtractionStatus.FAILED
    assert any("RuntimeError" in err for err in result.errors)


@pytest.mark.asyncio
async def test_service_invalid_source_id_raises_value_error():
    """Verify empty or overly long source_id raises ValueError immediately."""
    mock_ai = AsyncMock(spec=BaseAIProvider)
    service = EvidenceExtractionService(ai_provider=mock_ai)

    with pytest.raises(ValueError, match="empty or pure whitespace"):
        await service.extract_source_evidence(source_id="   ", source_type="web", content=SAMPLE_TEXT)

    with pytest.raises(ValueError, match="exceeds 100 characters"):
        await service.extract_source_evidence(source_id="x" * 101, source_type="web", content=SAMPLE_TEXT)


@pytest.mark.asyncio
async def test_service_unsupported_source_type_raises_value_error():
    """Verify unsupported source_type raises ValueError."""
    mock_ai = AsyncMock(spec=BaseAIProvider)
    service = EvidenceExtractionService(ai_provider=mock_ai)

    with pytest.raises(ValueError, match="Unsupported source_type"):
        await service.extract_source_evidence(source_id="src-1", source_type="audio", content=SAMPLE_TEXT)


@pytest.mark.asyncio
async def test_service_extract_document_evidence_convenience_method():
    """Verify extract_document_evidence delegates properly to extract_source_evidence."""
    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"
    mock_ai.complete.return_value = build_mock_completion_response(json.dumps({"facts": [], "claims": [], "extraction_warnings": []}))

    service = EvidenceExtractionService(ai_provider=mock_ai)
    doc = SourceDocument(id="doc-xyz", type="web", content="Some text content.", title="Test Title")

    result = await service.extract_document_evidence(document=doc)
    assert result.source_id == "doc-xyz"
    assert result.source_type == EvidenceSourceType.WEB
    assert result.extraction_status == ExtractionStatus.SUCCESS


# =============================================================================
# Group B: Structured Parser & Schema Tests
# =============================================================================

@pytest.mark.asyncio
async def test_parser_markdown_code_fenced_json():
    """Verify model output wrapped in markdown ```json ... ``` fences is extracted."""
    fenced_payload = f"```json\n{json.dumps(SAMPLE_MODEL_PAYLOAD_DICT)}\n```"

    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"
    mock_ai.complete.return_value = build_mock_completion_response(fenced_payload)

    service = EvidenceExtractionService(ai_provider=mock_ai)
    result = await service.extract_source_evidence(
        source_id=SAMPLE_SOURCE_ID,
        source_type="web",
        content=SAMPLE_TEXT,
    )

    assert result.extraction_status == ExtractionStatus.SUCCESS
    assert len(result.facts) == 1
    assert result.facts[0].fact_id == "fact-001"


@pytest.mark.asyncio
async def test_parser_malformed_json_returns_failed_result():
    """Verify non-JSON model response returns FAILED status when raise_on_error=False."""
    malformed_output = "I found the following facts: 1. Ice loss was huge in Antarctica."

    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"
    mock_ai.complete.return_value = build_mock_completion_response(malformed_output)

    service = EvidenceExtractionService(ai_provider=mock_ai)
    result = await service.extract_source_evidence(
        source_id=SAMPLE_SOURCE_ID,
        source_type="web",
        content=SAMPLE_TEXT,
        raise_on_error=False,
    )

    assert result.extraction_status == ExtractionStatus.FAILED
    assert len(result.errors) == 1
    assert "JSON" in result.errors[0] or "parse" in result.errors[0].lower()


@pytest.mark.asyncio
async def test_parser_malformed_json_raises_when_raise_on_error():
    """Verify malformed JSON raises AIResponseValidationError when raise_on_error=True."""
    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.complete.return_value = build_mock_completion_response("Not JSON at all")

    service = EvidenceExtractionService(ai_provider=mock_ai)
    with pytest.raises(AIResponseValidationError):
        await service.extract_source_evidence(
            source_id=SAMPLE_SOURCE_ID,
            source_type="web",
            content=SAMPLE_TEXT,
            raise_on_error=True,
        )


@pytest.mark.asyncio
async def test_parser_rejects_extra_fields_in_payload():
    """Verify strict extra='forbid' validation rejects hallucinated envelope keys."""
    invalid_dict = dict(SAMPLE_MODEL_PAYLOAD_DICT)
    invalid_dict["hallucinated_field"] = "not_allowed"

    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"
    mock_ai.complete.return_value = build_mock_completion_response(json.dumps(invalid_dict))

    service = EvidenceExtractionService(ai_provider=mock_ai)
    result = await service.extract_source_evidence(
        source_id=SAMPLE_SOURCE_ID,
        source_type="web",
        content=SAMPLE_TEXT,
        raise_on_error=False,
    )

    assert result.extraction_status == ExtractionStatus.FAILED
    assert any("Extra inputs are not permitted" in err or "extra" in err.lower() for err in result.errors)


# =============================================================================
# Group C: Evidence Integrity & Verification Tests
# =============================================================================

@pytest.mark.asyncio
async def test_integrity_fact_attribution_mismatch_rejected_and_status_partial():
    """Verify fact with location.source_id mismatch is rejected, and status becomes PARTIAL."""
    mismatched_payload = {
        "facts": [
            {
                "fact_id": "fact-alien",
                "statement": "Some fact from an unrelated document.",
                "fact_type": "general",
                "location": {
                    "source_id": "different-source-999",  # Does NOT match SAMPLE_SOURCE_ID
                    "source_type": "web",
                    "url": "https://example.com/other",
                },
                "evidence_text": "Some fact from an unrelated document.",
                "representation_type": "direct_quote",
                "confidence": 0.9,
                "qualifiers": [],
                "uncertainty_notes": None,
                "extraction_warnings": [],
            }
        ],
        "claims": [],
        "extraction_warnings": [],
    }

    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"
    mock_ai.complete.return_value = build_mock_completion_response(json.dumps(mismatched_payload))

    service = EvidenceExtractionService(ai_provider=mock_ai)
    result = await service.extract_source_evidence(
        source_id=SAMPLE_SOURCE_ID,
        source_type="web",
        content=SAMPLE_TEXT,
    )

    assert result.extraction_status == ExtractionStatus.PARTIAL
    assert len(result.facts) == 0  # Alien fact was rejected
    assert any("Rejected fact 'fact-alien'" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_integrity_claim_attribution_mismatch_rejected_and_status_partial():
    """Verify claim with source_id mismatch is rejected, and status becomes PARTIAL."""
    mismatched_payload = {
        "facts": [],
        "claims": [
            {
                "claim_id": "claim-alien",
                "claim_text": "Assertions from another article.",
                "claim_type": "opinion",
                "source_id": "different-source-999",  # Does NOT match SAMPLE_SOURCE_ID
                "evidence_location": {
                    "source_id": "different-source-999",
                    "source_type": "web",
                },
                "representation_type": "paraphrase",
                "confidence": 0.8,
                "qualifiers": [],
                "uncertainty_notes": None,
                "extraction_warnings": [],
            }
        ],
        "extraction_warnings": [],
    }

    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"
    mock_ai.complete.return_value = build_mock_completion_response(json.dumps(mismatched_payload))

    service = EvidenceExtractionService(ai_provider=mock_ai)
    result = await service.extract_source_evidence(
        source_id=SAMPLE_SOURCE_ID,
        source_type="web",
        content=SAMPLE_TEXT,
    )

    assert result.extraction_status == ExtractionStatus.PARTIAL
    assert len(result.claims) == 0  # Alien claim was rejected
    assert any("Rejected claim 'claim-alien'" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_integrity_direct_quote_verbatim_found_no_warning():
    """Verify exact quote found in source text produces no hallucination warning."""
    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"
    mock_ai.complete.return_value = build_mock_completion_response(json.dumps(SAMPLE_MODEL_PAYLOAD_DICT))

    service = EvidenceExtractionService(ai_provider=mock_ai)
    result = await service.extract_source_evidence(
        source_id=SAMPLE_SOURCE_ID,
        source_type="web",
        content=SAMPLE_TEXT,
    )

    # Verbatim quote is in SAMPLE_TEXT, so no quote warning
    assert not any("could not be verbatim-verified" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_integrity_direct_quote_not_found_adds_hallucination_warning():
    """Verify direct_quote not matching source text triggers a quote integrity warning."""
    hallucinated_quote_payload = {
        "facts": [
            {
                "fact_id": "fact-fake-quote",
                "statement": "Antarctica was tropical 10 million years ago.",
                "fact_type": "general",
                "location": {
                    "source_id": SAMPLE_SOURCE_ID,
                    "source_type": "web",
                },
                "evidence_text": "Antarctica was tropical 10 million years ago with lush palm trees.",
                "representation_type": "direct_quote",
                "confidence": 0.95,
                "qualifiers": [],
                "uncertainty_notes": None,
                "extraction_warnings": [],
            }
        ],
        "claims": [],
        "extraction_warnings": [],
    }

    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"
    mock_ai.complete.return_value = build_mock_completion_response(json.dumps(hallucinated_quote_payload))

    service = EvidenceExtractionService(ai_provider=mock_ai)
    result = await service.extract_source_evidence(
        source_id=SAMPLE_SOURCE_ID,
        source_type="web",
        content=SAMPLE_TEXT,
    )

    assert any("could not be verbatim-verified" in w for w in result.warnings)
    # The fact is still retained with the warning
    assert len(result.facts) == 1


@pytest.mark.asyncio
async def test_integrity_character_offsets_exceeding_bounds_adds_warning():
    """Verify character offsets exceeding source character length trigger an integrity warning."""
    out_of_bounds_payload = {
        "facts": [
            {
                "fact_id": "fact-oob",
                "statement": "A factual statement.",
                "fact_type": "general",
                "location": {
                    "source_id": SAMPLE_SOURCE_ID,
                    "source_type": "web",
                    "start_char": 500,
                    "end_char": 9999,  # Way past SAMPLE_TEXT length (~170 chars)
                },
                "evidence_text": "A factual statement.",
                "representation_type": "paraphrase",
                "confidence": 0.9,
                "qualifiers": [],
                "uncertainty_notes": None,
                "extraction_warnings": [],
            }
        ],
        "claims": [],
        "extraction_warnings": [],
    }

    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"
    mock_ai.complete.return_value = build_mock_completion_response(json.dumps(out_of_bounds_payload))

    service = EvidenceExtractionService(ai_provider=mock_ai)
    result = await service.extract_source_evidence(
        source_id=SAMPLE_SOURCE_ID,
        source_type="web",
        content=SAMPLE_TEXT,
    )

    assert any("exceed processed text bounds" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_integrity_claim_url_domain_mismatch_adds_warning():
    """Verify cited claim URL with a domain differing from source_url adds a warning."""
    domain_mismatch_payload = {
        "facts": [],
        "claims": [
            {
                "claim_id": "claim-domain-mismatch",
                "claim_text": "Sea levels will rise.",
                "claim_type": "prediction",
                "source_id": SAMPLE_SOURCE_ID,
                "evidence_location": {
                    "source_id": SAMPLE_SOURCE_ID,
                    "source_type": "web",
                    "url": "https://unrelated-domain.org/climate",
                },
                "representation_type": "paraphrase",
                "confidence": 0.85,
                "qualifiers": [],
                "uncertainty_notes": None,
                "extraction_warnings": [],
            }
        ],
        "extraction_warnings": [],
    }

    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"
    mock_ai.complete.return_value = build_mock_completion_response(json.dumps(domain_mismatch_payload))

    service = EvidenceExtractionService(ai_provider=mock_ai)
    result = await service.extract_source_evidence(
        source_id=SAMPLE_SOURCE_ID,
        source_type="web",
        content=SAMPLE_TEXT,
        source_url="https://example.com/antarctic-study",
    )

    assert any("with domain differing from source URL" in w for w in result.warnings)


# =============================================================================
# Group D: Truncation, Omission & Batch Tests
# =============================================================================

@pytest.mark.asyncio
async def test_truncation_large_source_sets_truncated_flag_and_partial_status():
    """Verify large content exceeding limits sets source_truncated=True and status=PARTIAL."""
    # Create content larger than max source char limit (e.g. 100_000 chars)
    giant_content = "Antarctic research data point. " * 3500  # ~108,500 chars

    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"
    mock_ai.complete.return_value = build_mock_completion_response(
        json.dumps({"facts": [], "claims": [], "extraction_warnings": []})
    )

    service = EvidenceExtractionService(ai_provider=mock_ai)
    result = await service.extract_source_evidence(
        source_id=SAMPLE_SOURCE_ID,
        source_type="web",
        content=giant_content,
    )

    assert result.source_truncated is True
    assert result.extraction_status == ExtractionStatus.PARTIAL
    assert result.source_character_count == len(giant_content)
    assert result.processed_character_count < len(giant_content)
    assert any("Source text was truncated" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_batch_extraction_multiple_sources_success():
    """Verify batch extraction processes multiple sources with accurate summary metrics."""
    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"
    mock_ai.complete.return_value = build_mock_completion_response(
        json.dumps({"facts": [], "claims": [], "extraction_warnings": []})
    )

    service = EvidenceExtractionService(ai_provider=mock_ai)
    sources = [
        SourceDocument(id="doc-1", type="web", content="Content for doc 1"),
        SourceDocument(id="doc-2", type="pdf", content="Content for doc 2"),
    ]

    batch_result: BatchEvidenceExtractionResult = await service.extract_sources_batch(sources=sources)

    assert batch_result.total_sources == 2
    assert batch_result.successful_sources == 2
    assert batch_result.failed_sources == 0
    assert batch_result.partial_sources == 0
    assert batch_result.empty_sources == 0
    assert len(batch_result.results) == 2


@pytest.mark.asyncio
async def test_batch_extraction_failure_isolation():
    """Verify failure in one source does not crash the batch and isolates errors."""
    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"

    # Doc 1 succeeds, Doc 2 fails with AIProviderUnavailableError, Doc 3 is empty
    mock_ai.complete.side_effect = [
        build_mock_completion_response(json.dumps({"facts": [], "claims": [], "extraction_warnings": []})),
        AIProviderUnavailableError("Temporary upstream outage"),
    ]

    service = EvidenceExtractionService(ai_provider=mock_ai)
    sources = [
        SourceDocument(id="doc-good", type="web", content="Valid content"),
        SourceDocument(id="doc-fail", type="web", content="Failing content"),
        SourceDocument(id="doc-empty", type="web", content=""),
    ]

    batch_result = await service.extract_sources_batch(sources=sources, raise_on_error=False)

    assert batch_result.total_sources == 3
    assert batch_result.successful_sources == 1
    assert batch_result.failed_sources == 1
    assert batch_result.empty_sources == 1
    assert batch_result.results[0].extraction_status == ExtractionStatus.SUCCESS
    assert batch_result.results[1].extraction_status == ExtractionStatus.FAILED
    assert batch_result.results[2].extraction_status == ExtractionStatus.NO_CONTENT


@pytest.mark.asyncio
async def test_batch_extraction_dict_inputs():
    """Verify batch extraction supports dict-based source declarations."""
    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"
    mock_ai.complete.return_value = build_mock_completion_response(
        json.dumps({"facts": [], "claims": [], "extraction_warnings": []})
    )

    service = EvidenceExtractionService(ai_provider=mock_ai)
    dict_sources = [
        {"id": "doc-dict-1", "type": "web", "content": "Text 1", "title": "Title 1"},
        {"id": "doc-dict-2", "type": "pdf", "content": "Text 2", "title": "Title 2"},
    ]

    batch_result = await service.extract_sources_batch(sources=dict_sources)
    assert batch_result.total_sources == 2
    assert batch_result.successful_sources == 2


@pytest.mark.asyncio
async def test_batch_extraction_raise_on_error():
    """Verify batch extraction raises immediately when raise_on_error=True."""
    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.complete.side_effect = AIProviderUnavailableError("Immediate failure")

    service = EvidenceExtractionService(ai_provider=mock_ai)
    sources = [
        SourceDocument(id="doc-1", type="web", content="Text 1"),
        SourceDocument(id="doc-2", type="web", content="Text 2"),
    ]

    with pytest.raises(AIProviderUnavailableError):
        await service.extract_sources_batch(sources=sources, raise_on_error=True)


# =============================================================================
# Group E: FastAPI Route Integration Tests
# =============================================================================

@pytest.fixture(autouse=True)
def override_project_ownership(app: FastAPI):
    """Allow pipeline domain unit tests to assume project ownership is validated."""
    app.dependency_overrides[get_owned_project] = (
        lambda project_id, current_user=Depends(get_current_user): OwnedProjectContext(
            id=project_id,
            user_id=current_user.id,
            title="Test Project",
        )
    )
    yield
    app.dependency_overrides.pop(get_owned_project, None)


def test_route_extract_evidence_success(app: FastAPI, client: TestClient):
    """Verify POST /{project_id}/sources/{source_id}/extract returns 200 with result."""
    mock_source_service = AsyncMock(spec=WebSourceIngestionService)
    mock_source_service.get_project_source_detail.return_value = SourceDetailResponse(
        id=SAMPLE_SOURCE_UUID,
        project_id=SAMPLE_PROJECT_ID,
        source_type="web",
        title="Sample Web Title",
        original_url="https://example.com/antarctic-study",
        ingestion_status="completed",
        extracted_text=SAMPLE_TEXT,
        character_count=len(SAMPLE_TEXT),
        word_count=len(SAMPLE_TEXT.split()),
        paragraph_count=1,
        content_hash="abc123hash",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    route_payload_dict = json.loads(json.dumps(SAMPLE_MODEL_PAYLOAD_DICT))
    route_payload_dict["facts"][0]["location"]["source_id"] = str(SAMPLE_SOURCE_UUID)
    route_payload_dict["claims"][0]["source_id"] = str(SAMPLE_SOURCE_UUID)
    route_payload_dict["claims"][0]["evidence_location"]["source_id"] = str(SAMPLE_SOURCE_UUID)

    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"
    mock_ai.complete.return_value = build_mock_completion_response(json.dumps(route_payload_dict))

    extraction_service = EvidenceExtractionService(ai_provider=mock_ai)

    app.dependency_overrides[get_web_source_service] = lambda: mock_source_service
    app.dependency_overrides[get_evidence_extraction_service] = lambda: extraction_service

    try:
        resp = client.post(
            f"/api/v1/projects/{SAMPLE_PROJECT_ID}/sources/{SAMPLE_SOURCE_UUID}/extract",
            json={"research_question": "What is the rate of ice loss in Antarctica?"},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["source_id"] == str(SAMPLE_SOURCE_UUID)
        assert data["extraction_status"] == "success"
        assert len(data["facts"]) == 1
        assert len(data["claims"]) == 1
        assert data["facts"][0]["fact_id"] == "fact-001"
    finally:
        app.dependency_overrides.pop(get_web_source_service, None)
        app.dependency_overrides.pop(get_evidence_extraction_service, None)


def test_route_extract_evidence_without_body(app: FastAPI, client: TestClient):
    """Verify POST extract endpoint succeeds even when body is not provided."""
    mock_source_service = AsyncMock(spec=WebSourceIngestionService)
    mock_source_service.get_project_source_detail.return_value = SourceDetailResponse(
        id=SAMPLE_SOURCE_UUID,
        project_id=SAMPLE_PROJECT_ID,
        source_type="web",
        title="Web Source",
        original_url="https://example.com/study",
        ingestion_status="completed",
        extracted_text=SAMPLE_TEXT,
        character_count=len(SAMPLE_TEXT),
        word_count=len(SAMPLE_TEXT.split()),
        paragraph_count=1,
        content_hash="abc123hash",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    mock_ai = AsyncMock(spec=BaseAIProvider)
    mock_ai.is_configured = True
    mock_ai.active_model = "nvidia/nemotron-3-ultra-550b-a55b:free"
    mock_ai.complete.return_value = build_mock_completion_response(json.dumps({"facts": [], "claims": [], "extraction_warnings": []}))

    extraction_service = EvidenceExtractionService(ai_provider=mock_ai)

    app.dependency_overrides[get_web_source_service] = lambda: mock_source_service
    app.dependency_overrides[get_evidence_extraction_service] = lambda: extraction_service

    try:
        resp = client.post(
            f"/api/v1/projects/{SAMPLE_PROJECT_ID}/sources/{SAMPLE_SOURCE_UUID}/extract"
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["extraction_status"] == "success"
    finally:
        app.dependency_overrides.pop(get_web_source_service, None)
        app.dependency_overrides.pop(get_evidence_extraction_service, None)


def test_route_extract_evidence_project_not_found(app: FastAPI, client: TestClient):
    """Verify 404 is returned when project does not exist."""
    mock_source_service = AsyncMock(spec=WebSourceIngestionService)
    mock_source_service.get_project_source_detail.side_effect = ProjectNotFoundError(
        f"Research project '{SAMPLE_PROJECT_ID}' was not found."
    )

    mock_extraction_service = MagicMock(spec=EvidenceExtractionService)
    mock_extraction_service.is_configured = True

    app.dependency_overrides[get_web_source_service] = lambda: mock_source_service
    app.dependency_overrides[get_evidence_extraction_service] = lambda: mock_extraction_service

    try:
        resp = client.post(
            f"/api/v1/projects/{SAMPLE_PROJECT_ID}/sources/{SAMPLE_SOURCE_UUID}/extract",
            json={},
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_web_source_service, None)
        app.dependency_overrides.pop(get_evidence_extraction_service, None)


def test_route_extract_evidence_source_not_found(app: FastAPI, client: TestClient):
    """Verify 404 is returned when source does not exist in the project."""
    mock_source_service = AsyncMock(spec=WebSourceIngestionService)
    mock_source_service.get_project_source_detail.side_effect = SourceNotFoundError(
        f"Source '{SAMPLE_SOURCE_UUID}' was not found in project '{SAMPLE_PROJECT_ID}'."
    )

    mock_extraction_service = MagicMock(spec=EvidenceExtractionService)
    mock_extraction_service.is_configured = True

    app.dependency_overrides[get_web_source_service] = lambda: mock_source_service
    app.dependency_overrides[get_evidence_extraction_service] = lambda: mock_extraction_service

    try:
        resp = client.post(
            f"/api/v1/projects/{SAMPLE_PROJECT_ID}/sources/{SAMPLE_SOURCE_UUID}/extract",
            json={},
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_web_source_service, None)
        app.dependency_overrides.pop(get_evidence_extraction_service, None)


def test_route_extract_evidence_ai_unconfigured_returns_503(app: FastAPI, client: TestClient):
    """Verify 503 is returned when AI provider is not configured."""
    mock_extraction_service = MagicMock(spec=EvidenceExtractionService)
    mock_extraction_service.is_configured = False

    app.dependency_overrides[get_evidence_extraction_service] = lambda: mock_extraction_service

    try:
        resp = client.post(
            f"/api/v1/projects/{SAMPLE_PROJECT_ID}/sources/{SAMPLE_SOURCE_UUID}/extract",
            json={},
        )
        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "OPENROUTER_API_KEY is missing" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_evidence_extraction_service, None)


def test_route_extract_evidence_db_unavailable_returns_503(app: FastAPI, client: TestClient):
    """Verify 503 is returned when database service is unavailable."""
    mock_source_service = AsyncMock(spec=WebSourceIngestionService)
    mock_source_service.get_project_source_detail.side_effect = DatabaseUnavailableError(
        "Could not connect to PostgreSQL."
    )

    mock_extraction_service = MagicMock(spec=EvidenceExtractionService)
    mock_extraction_service.is_configured = True

    app.dependency_overrides[get_web_source_service] = lambda: mock_source_service
    app.dependency_overrides[get_evidence_extraction_service] = lambda: mock_extraction_service

    try:
        resp = client.post(
            f"/api/v1/projects/{SAMPLE_PROJECT_ID}/sources/{SAMPLE_SOURCE_UUID}/extract",
            json={},
        )
        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "Database service is unavailable" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_web_source_service, None)
        app.dependency_overrides.pop(get_evidence_extraction_service, None)


def test_route_extract_evidence_invalid_uuid_returns_422(client: TestClient):
    """Verify 422 is returned for invalid UUID format in path parameters."""
    resp = client.post(
        "/api/v1/projects/not-a-uuid/sources/not-a-uuid/extract",
        json={},
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
