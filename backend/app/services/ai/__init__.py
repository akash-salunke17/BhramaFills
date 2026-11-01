"""AI Provider integration package for Bharmafills."""

from functools import lru_cache

from app.core.config import get_settings
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
    AIContentPolicyError,
    AIProviderError,
    AIProviderUnavailableError,
    AIQuotaExceededError,
    AIRateLimitError,
    AIResponseValidationError,
    AITimeoutError,
)
from app.services.ai.gap_detection_service import (
    InformationGapDetectionService,
    get_gap_detection_service,
)
from app.services.ai.gap_persistence_service import (
    GapNotFoundError,
    GapPersistenceError,
    GapPersistenceService,
    GapTransactionError,
    compute_gap_fingerprint,
    get_gap_persistence_service,
)
from app.services.ai.gap_schemas import (
    AIGapCandidatePayload,
    AIGapDetectionPayload,
    DetectGapsRequest,
    GapDetectionAndPersistenceResponse,
    GapDetectionResult,
    GapPriority,
    GapReviewStatus,
    GapReviewUpdate,
    GapStatus,
    GapSubtype,
    GapType,
    InformationGapListResponse,
    InformationGapResponse,
    PersistedGapBatchResponse,
    ValidatedGapFinding,
)
from app.services.ai.openrouter_client import OpenRouterClient
from app.services.ai.parser import SafeResponseParser
from app.services.ai.prompts import (
    EVIDENCE_EXTRACTION_FULL_INSTRUCTION,
    GAP_DETECTION_FULL_INSTRUCTION,
    PromptBuilder,
    PromptBuildResult,
    SECURITY_SYSTEM_PROMPT,
    SourceDocument,
    SourceOmissionSummary,
    SourceTruncationMetadata,
    assemble_evidence_extraction_prompt,
    assemble_gap_detection_prompt,
    build_evidence_extraction_prompt,
    build_gap_detection_prompt,
)
from app.services.ai.schemas import (
    AIConfigStatus,
    ChatChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    StructuredExtractionResult,
    UsageInfo,
)


@lru_cache
def get_ai_provider() -> BaseAIProvider:
    """Return a cached singleton instance of the default AI provider (OpenRouter)."""
    settings = get_settings()
    return OpenRouterClient(settings=settings)


__all__ = [
    "BaseAIProvider",
    "OpenRouterClient",
    "SafeResponseParser",
    "PromptBuilder",
    "PromptBuildResult",
    "SourceDocument",
    "SourceTruncationMetadata",
    "SourceOmissionSummary",
    "SECURITY_SYSTEM_PROMPT",
    "EVIDENCE_EXTRACTION_FULL_INSTRUCTION",
    "GAP_DETECTION_FULL_INSTRUCTION",
    "build_evidence_extraction_prompt",
    "assemble_evidence_extraction_prompt",
    "build_gap_detection_prompt",
    "assemble_gap_detection_prompt",
    "GapType",
    "GapPriority",
    "GapStatus",
    "GapSubtype",
    "GapReviewStatus",
    "AIGapCandidatePayload",
    "AIGapDetectionPayload",
    "ValidatedGapFinding",
    "InformationGapResponse",
    "GapReviewUpdate",
    "GapDetectionResult",
    "PersistedGapBatchResponse",
    "InformationGapListResponse",
    "DetectGapsRequest",
    "GapDetectionAndPersistenceResponse",
    "InformationGapDetectionService",
    "get_gap_detection_service",
    "GapPersistenceService",
    "get_gap_persistence_service",
    "compute_gap_fingerprint",
    "GapPersistenceError",
    "GapNotFoundError",
    "GapTransactionError",
    "RepresentationType",
    "EvidenceSourceType",
    "FactType",
    "ClaimType",
    "ExtractionStatus",
    "EvidenceLocation",
    "ExtractedFact",
    "SourceClaim",
    "EvidenceExtractionPayload",
    "EvidenceExtractionResult",
    "BatchEvidenceExtractionResult",
    "ExtractEvidenceRequest",
    "EvidenceExtractionService",
    "get_evidence_extraction_service",
    "ChatMessage",
    "ChatChoice",
    "UsageInfo",
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "AIConfigStatus",
    "StructuredExtractionResult",
    "AIProviderError",
    "AIAuthenticationError",
    "AIRateLimitError",
    "AIQuotaExceededError",
    "AIProviderUnavailableError",
    "AITimeoutError",
    "AIResponseValidationError",
    "AIContentPolicyError",
    "get_ai_provider",
]

