"""Evidence extraction coordinator service for Bharmafills.

Connects:
- Prompt templates (`assemble_evidence_extraction_prompt`)
- `PromptBuilder` & `PromptBuildResult` (structured truncation metadata)
- `BaseAIProvider` / `OpenRouterClient` (resilient async AI completions)
- `SafeResponseParser` (structured JSON decoding & schema validation)
- Pydantic evidence schemas (`EvidenceExtractionPayload`, `EvidenceExtractionResult`)

Enforces:
- Strict evidence integrity & attribution checks.
- Separation between model-generated payload and backend-owned envelope metadata.
- Accurate status determination (success, partial, failed, no_content).
- Failure isolation in multi-source batch extraction.
- Structured operational logging without credential, prompt, or source leaks.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import logging
import re
from typing import Any, Sequence
from uuid import UUID

from app.core.config import Settings, get_settings
from app.services.ai.base import BaseAIProvider
from app.services.ai.evidence_schemas import (
    BatchEvidenceExtractionResult,
    EvidenceExtractionPayload,
    EvidenceExtractionResult,
    EvidenceSourceType,
    ExtractedFact,
    ExtractionStatus,
    RepresentationType,
    SourceClaim,
)
from app.services.ai.exceptions import (
    AIAuthenticationError,
    AIProviderError,
    AIResponseValidationError,
)
from app.services.ai.openrouter_client import OpenRouterClient
from app.services.ai.parser import SafeResponseParser
from app.services.ai.prompts import (
    PromptBuildResult,
    SourceDocument,
    assemble_evidence_extraction_prompt,
)

logger = logging.getLogger("bharmafills.services.ai.evidence")

_WHITESPACE_COLLAPSE_RE = re.compile(r"\s+")


def _normalize_text_for_comparison(text: str) -> str:
    """Collapse all whitespace to single spaces for fuzzy quote verification."""
    return _WHITESPACE_COLLAPSE_RE.sub(" ", text.strip().lower())


class EvidenceExtractionService:
    """Orchestrates source-grounded evidence extraction using configured AI provider."""

    def __init__(
        self,
        ai_provider: BaseAIProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Initialize the extraction service.

        Args:
            ai_provider: AI provider instance. Defaults to default OpenRouter provider.
            settings: Settings instance. Defaults to get_settings().
        """
        self._settings = settings or get_settings()
        self._ai_provider = ai_provider or OpenRouterClient(settings=self._settings)

    @property
    def is_configured(self) -> bool:
        """Return True if the underlying AI provider has credentials configured."""
        return self._ai_provider.is_configured

    @property
    def active_model(self) -> str:
        """Return the active model identifier."""
        return self._ai_provider.active_model

    async def extract_source_evidence(
        self,
        source_id: str | UUID,
        source_type: str,
        content: str,
        title: str | None = None,
        source_url: str | None = None,
        research_question: str | None = None,
        custom_instructions: str | None = None,
        raise_on_error: bool = False,
    ) -> EvidenceExtractionResult:
        """Extract facts and claims from a single source document.

        Args:
            source_id:           Unique source identifier (UUID or non-empty string).
            source_type:         Source medium ('web', 'url', 'pdf').
            content:             Extracted textual content of the source.
            title:               Optional source title or filename.
            source_url:          Optional source URL for attribution verification.
            research_question:   Optional research inquiry guiding relevance.
            custom_instructions: Optional user-defined extraction directives.
            raise_on_error:      If True, raises AIProviderError on failure;
                                 if False, returns EvidenceExtractionResult with status='failed'.

        Returns:
            Authoritative EvidenceExtractionResult envelope.
        """
        clean_source_id = str(source_id).strip()
        if not clean_source_id:
            raise ValueError("source_id cannot be empty or pure whitespace.")
        if len(clean_source_id) > 100:
            raise ValueError(f"source_id length ({len(clean_source_id)}) exceeds 100 characters.")

        # Normalize source_type
        lowered_type = source_type.strip().lower()
        if lowered_type == "url":
            resolved_source_type = EvidenceSourceType.WEB
        elif lowered_type in ("web", "pdf"):
            resolved_source_type = EvidenceSourceType(lowered_type)
        else:
            raise ValueError(
                f"Unsupported source_type '{source_type}'. Must be 'web' (or 'url') or 'pdf'."
            )

        # 1. Content check: handle empty or whitespace-only content without calling AI provider
        if not content or not content.strip():
            logger.info(
                "Source '%s' (%s) contains no readable text content; returning no_content extraction.",
                clean_source_id,
                resolved_source_type.value,
            )
            return EvidenceExtractionResult(
                source_id=clean_source_id,
                source_type=resolved_source_type,
                facts=[],
                claims=[],
                extraction_status=ExtractionStatus.NO_CONTENT,
                warnings=["Source document contains no extractable readable text content."],
                errors=[],
                source_truncated=False,
                source_character_count=0,
                processed_character_count=0,
                extracted_at=datetime.now(timezone.utc),
            )

        # 2. Provider configuration check
        if not self._ai_provider.is_configured:
            logger.warning(
                "Cannot perform extraction for source '%s': AI provider is not configured.",
                clean_source_id,
            )
            err_msg = "AI provider is not configured. OPENROUTER_API_KEY is missing."
            if raise_on_error:
                raise AIAuthenticationError(message=err_msg)
            return EvidenceExtractionResult(
                source_id=clean_source_id,
                source_type=resolved_source_type,
                facts=[],
                claims=[],
                extraction_status=ExtractionStatus.FAILED,
                warnings=[],
                errors=[err_msg],
                source_truncated=False,
                source_character_count=len(content),
                processed_character_count=0,
                extracted_at=datetime.now(timezone.utc),
            )

        # 3. Build prompt with truncation awareness
        source_doc = SourceDocument(
            id=clean_source_id,
            type=resolved_source_type.value,
            content=content,
            title=title,
        )

        prompt_result: PromptBuildResult = assemble_evidence_extraction_prompt(
            sources=[source_doc],
            research_question=research_question,
            custom_instructions=custom_instructions,
        )

        # Extract structured truncation metadata
        was_truncated = prompt_result.has_character_truncation
        if prompt_result.source_metadata:
            meta = prompt_result.source_metadata[0]
            original_chars = meta.original_char_count
            processed_chars = meta.retained_char_count
            omitted_chars = meta.omitted_char_count
        else:
            original_chars = len(content)
            processed_chars = len(content)
            omitted_chars = 0

        truncation_warnings: list[str] = []
        if was_truncated:
            truncation_warnings.append(
                f"Source text was truncated before model evaluation: retained {processed_chars} "
                f"of {original_chars} characters ({omitted_chars} characters omitted)."
            )

        # 4. Invoke AI provider completion
        logger.info(
            "Initiating evidence extraction for source '%s' (type=%s, chars=%d, truncated=%s, model=%s)",
            clean_source_id,
            resolved_source_type.value,
            processed_chars,
            was_truncated,
            self._ai_provider.active_model,
        )

        try:
            response = await self._ai_provider.complete(
                messages=prompt_result.messages,
                temperature=0.1,  # Low temperature for strict factual grounding
            )
            raw_text = response.first_content
        except AIProviderError as exc:
            logger.warning(
                "AI provider error during extraction for source '%s': %s",
                clean_source_id,
                exc.message,
            )
            if raise_on_error:
                raise
            return EvidenceExtractionResult(
                source_id=clean_source_id,
                source_type=resolved_source_type,
                facts=[],
                claims=[],
                extraction_status=ExtractionStatus.FAILED,
                warnings=truncation_warnings,
                errors=[f"AI provider failure: {exc.message}"],
                source_truncated=was_truncated,
                source_character_count=original_chars,
                processed_character_count=processed_chars,
                extracted_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            logger.error(
                "Unexpected failure during AI completion for source '%s': %s",
                clean_source_id,
                type(exc).__name__,
            )
            if raise_on_error:
                raise
            return EvidenceExtractionResult(
                source_id=clean_source_id,
                source_type=resolved_source_type,
                facts=[],
                claims=[],
                extraction_status=ExtractionStatus.FAILED,
                warnings=truncation_warnings,
                errors=[f"Unexpected processing error: {type(exc).__name__}"],
                source_truncated=was_truncated,
                source_character_count=original_chars,
                processed_character_count=processed_chars,
                extracted_at=datetime.now(timezone.utc),
            )

        # 5. Parse and validate against EvidenceExtractionPayload
        parse_result = SafeResponseParser.parse_model_output(
            raw_text=raw_text,
            target_schema=EvidenceExtractionPayload,
        )

        if not parse_result.is_valid or parse_result.parsed_data is None:
            err_msg = parse_result.validation_error or "Model response could not be parsed into evidence payload."
            logger.warning(
                "Structured output validation failed for source '%s': %s",
                clean_source_id,
                err_msg,
            )
            if raise_on_error:
                raise AIResponseValidationError(message=err_msg)
            return EvidenceExtractionResult(
                source_id=clean_source_id,
                source_type=resolved_source_type,
                facts=[],
                claims=[],
                extraction_status=ExtractionStatus.FAILED,
                warnings=truncation_warnings,
                errors=[err_msg],
                source_truncated=was_truncated,
                source_character_count=original_chars,
                processed_character_count=processed_chars,
                extracted_at=datetime.now(timezone.utc),
            )

        payload: EvidenceExtractionPayload = parse_result.parsed_data

        # 6. Additional Evidence Integrity Checks
        valid_facts: list[ExtractedFact] = []
        valid_claims: list[SourceClaim] = []
        integrity_warnings: list[str] = []
        had_item_rejections = False

        normalized_source_content = _normalize_text_for_comparison(content)

        # A. Fact integrity verification
        for fact in payload.facts:
            # Attribution check
            if fact.location.source_id != clean_source_id:
                had_item_rejections = True
                integrity_warnings.append(
                    f"Rejected fact '{fact.fact_id}': location source_id '{fact.location.source_id}' "
                    f"does not match target source '{clean_source_id}'."
                )
                continue

            # Character offset verification
            if fact.location.start_char is not None and fact.location.end_char is not None:
                if fact.location.end_char > processed_chars or fact.location.start_char >= processed_chars:
                    integrity_warnings.append(
                        f"Fact '{fact.fact_id}' offsets [{fact.location.start_char}:{fact.location.end_char}] "
                        f"exceed processed text bounds ({processed_chars} chars)."
                    )

            # Direct quote verification against source text
            if fact.representation_type == RepresentationType.DIRECT_QUOTE:
                normalized_quote = _normalize_text_for_comparison(fact.evidence_text)
                if normalized_quote and normalized_quote not in normalized_source_content:
                    integrity_warnings.append(
                        f"Direct quote in fact '{fact.fact_id}' could not be verbatim-verified "
                        f"in source text (possible hallucination or modified phrasing)."
                    )

            valid_facts.append(fact)

        # B. Claim integrity verification
        for claim in payload.claims:
            # Attribution check
            if claim.source_id != clean_source_id:
                had_item_rejections = True
                integrity_warnings.append(
                    f"Rejected claim '{claim.claim_id}': claim source_id '{claim.source_id}' "
                    f"does not match target source '{clean_source_id}'."
                )
                continue

            # Character offset verification
            if claim.evidence_location.start_char is not None and claim.evidence_location.end_char is not None:
                if claim.evidence_location.end_char > processed_chars or claim.evidence_location.start_char >= processed_chars:
                    integrity_warnings.append(
                        f"Claim '{claim.claim_id}' offsets [{claim.evidence_location.start_char}:{claim.evidence_location.end_char}] "
                        f"exceed processed text bounds ({processed_chars} chars)."
                    )

            # URL consistency verification for web claims
            if source_url and claim.evidence_location.url:
                try:
                    expected_netloc = re.sub(r"^www\.", "", re.split(r"[:/]", source_url.split("//")[-1])[0].lower())
                    cited_netloc = re.sub(r"^www\.", "", re.split(r"[:/]", claim.evidence_location.url.split("//")[-1])[0].lower())
                    if expected_netloc and cited_netloc and expected_netloc != cited_netloc:
                        integrity_warnings.append(
                            f"Claim '{claim.claim_id}' cites URL '{claim.evidence_location.url}' "
                            f"with domain differing from source URL '{source_url}'."
                        )
                except Exception:
                    pass

            valid_claims.append(claim)

        # 7. Final status determination
        # If truncated or had item rejections, status is partial to reflect incomplete coverage
        if was_truncated or had_item_rejections:
            final_status = ExtractionStatus.PARTIAL
        else:
            final_status = ExtractionStatus.SUCCESS

        # Combine all warnings
        all_warnings: list[str] = (
            truncation_warnings + payload.extraction_warnings + integrity_warnings
        )

        logger.info(
            "Evidence extraction completed for source '%s': status=%s, facts=%d, claims=%d, warnings=%d",
            clean_source_id,
            final_status.value,
            len(valid_facts),
            len(valid_claims),
            len(all_warnings),
        )

        # 8. Assemble authoritative backend-owned EvidenceExtractionResult
        return EvidenceExtractionResult(
            source_id=clean_source_id,
            source_type=resolved_source_type,
            facts=valid_facts,
            claims=valid_claims,
            extraction_status=final_status,
            warnings=all_warnings,
            errors=[],
            source_truncated=was_truncated,
            source_character_count=original_chars,
            processed_character_count=processed_chars,
            extracted_at=datetime.now(timezone.utc),
        )

    async def extract_document_evidence(
        self,
        document: SourceDocument,
        research_question: str | None = None,
        custom_instructions: str | None = None,
        raise_on_error: bool = False,
    ) -> EvidenceExtractionResult:
        """Extract evidence from a SourceDocument instance.

        Args:
            document:            SourceDocument instance containing id, type, content, title.
            research_question:   Optional research inquiry guiding relevance.
            custom_instructions: Optional user-defined extraction directives.
            raise_on_error:      If True, raises AIProviderError on failure.

        Returns:
            EvidenceExtractionResult envelope.
        """
        return await self.extract_source_evidence(
            source_id=str(document.id),
            source_type=document.type,
            content=document.content,
            title=document.title,
            research_question=research_question,
            custom_instructions=custom_instructions,
            raise_on_error=raise_on_error,
        )

    async def extract_sources_batch(
        self,
        sources: Sequence[SourceDocument | dict[str, Any]],
        research_question: str | None = None,
        custom_instructions: str | None = None,
        raise_on_error: bool = False,
    ) -> BatchEvidenceExtractionResult:
        """Extract evidence from multiple sources with strict per-source failure isolation.

        Each source is processed independently. A failure on one source does not
        disrupt or invalidate successful extractions from other sources.

        Args:
            sources:             Sequence of SourceDocument or dict instances.
            research_question:   Optional research inquiry.
            custom_instructions: Optional user-defined extraction directives.
            raise_on_error:      If True, raises on the first encountered error.

        Returns:
            BatchEvidenceExtractionResult containing per-source results and summary metrics.
        """
        results: list[EvidenceExtractionResult] = []
        successful_count = 0
        partial_count = 0
        failed_count = 0
        empty_count = 0

        for item in sources:
            if isinstance(item, SourceDocument):
                doc = item
            elif isinstance(item, dict):
                doc = SourceDocument(
                    id=item.get("id", ""),
                    type=item.get("type", "web"),
                    content=item.get("content", ""),
                    title=item.get("title"),
                )
            else:
                raise TypeError(f"Expected SourceDocument or dict, got {type(item).__name__}")

            try:
                res = await self.extract_document_evidence(
                    document=doc,
                    research_question=research_question,
                    custom_instructions=custom_instructions,
                    raise_on_error=raise_on_error,
                )
            except Exception as exc:
                if raise_on_error:
                    raise
                logger.error(
                    "Batch extraction caught exception for source '%s': %s",
                    doc.id,
                    type(exc).__name__,
                )
                res = EvidenceExtractionResult(
                    source_id=str(doc.id),
                    source_type=EvidenceSourceType.WEB if doc.type in ("web", "url") else EvidenceSourceType.PDF,
                    facts=[],
                    claims=[],
                    extraction_status=ExtractionStatus.FAILED,
                    warnings=[],
                    errors=[f"Batch processing error: {type(exc).__name__}: {str(exc)}"],
                    source_truncated=False,
                    source_character_count=len(doc.content),
                    processed_character_count=0,
                    extracted_at=datetime.now(timezone.utc),
                )

            results.append(res)

            if res.extraction_status == ExtractionStatus.SUCCESS:
                successful_count += 1
            elif res.extraction_status == ExtractionStatus.PARTIAL:
                partial_count += 1
            elif res.extraction_status == ExtractionStatus.FAILED:
                failed_count += 1
            elif res.extraction_status == ExtractionStatus.NO_CONTENT:
                empty_count += 1

        return BatchEvidenceExtractionResult(
            results=results,
            total_sources=len(sources),
            successful_sources=successful_count,
            partial_sources=partial_count,
            failed_sources=failed_count,
            empty_sources=empty_count,
        )


@lru_cache
def get_evidence_extraction_service() -> EvidenceExtractionService:
    """Return a cached singleton instance of EvidenceExtractionService."""
    settings = get_settings()
    return EvidenceExtractionService(settings=settings)

