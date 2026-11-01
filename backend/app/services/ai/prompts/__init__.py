"""Centralized prompt architecture for Bharmafills AI processing.

This package establishes and enforces the trust hierarchy for all LLM interactions:

  Level 1 — TRUSTED: Application system instructions (this package).
  Level 2 — TRUSTED: Application-controlled task instructions.
  Level 3 — UNTRUSTED: External source content (websites, PDFs) fenced in XML.
  Level 4 — UNVERIFIED: AI-generated output (validated downstream by SafeResponseParser).

External source content is ALWAYS wrapped in XML isolation tags before being
passed to the model.  The system prompt explicitly instructs the model to
treat fenced content as data, not as instructions.

Public API
----------
PromptBuilder          — Assembles safe ChatMessage lists for any AI task.
SourceDocument         — Immutable descriptor for an untrusted source document.
SECURITY_SYSTEM_PROMPT — Foundational system instruction template (read-only).
SOURCE_TAG_OPEN        — Opening XML fence tag constant.
SOURCE_TAG_CLOSE       — Closing XML fence tag constant.
SOURCES_BLOCK_OPEN_TAG — Opening multi-source wrapper tag.
SOURCES_BLOCK_CLOSE_TAG— Closing multi-source wrapper tag.
"""

from app.services.ai.prompts.builder import (
    PromptBuilder,
    PromptBuildResult,
    SourceDocument,
    SourceOmissionSummary,
    SourceTruncationMetadata,
)
from app.services.ai.prompts.constants import (
    MAX_SOURCE_CHARS,
    MAX_SOURCES_PER_PROMPT,
    SOURCE_CLOSE_TAG,
    SOURCE_OPEN_TAG,
    SOURCE_TAG_CLOSE,
    SOURCE_TAG_OPEN,
    SOURCE_TYPE_PDF,
    SOURCE_TYPE_URL,
    SOURCE_TYPE_WEB,
    SOURCES_BLOCK_CLOSE_TAG,
    SOURCES_BLOCK_OPEN_TAG,
    SOURCES_TRUNCATION_TAG,
    TRUST_LEVEL_OUTPUT,
    TRUST_LEVEL_SOURCE,
    TRUST_LEVEL_SYSTEM,
    TRUST_LEVEL_TASK,
    VALID_SOURCE_TYPES,
)
from app.services.ai.prompts.evidence_templates import (
    EVIDENCE_EXTRACTION_FULL_INSTRUCTION,
    EVIDENCE_EXTRACTION_INSTRUCTIONS,
    EVIDENCE_EXTRACTION_JSON_CONTRACT,
    EVIDENCE_EXTRACTION_TASK_HEADER,
    EVIDENCE_GROUNDING_RULES,
    EVIDENCE_PROMPT_INJECTION_DEFENSE,
    assemble_evidence_extraction_prompt,
    build_evidence_extraction_prompt,
    build_truncation_notice,
)
from app.services.ai.prompts.gap_templates import (
    GAP_CLASSIFICATION_INSTRUCTIONS,
    GAP_DETECTION_FULL_INSTRUCTION,
    GAP_DETECTION_JSON_CONTRACT,
    GAP_DETECTION_TASK_HEADER,
    GAP_GROUNDING_RULES,
    GAP_PRIORITY_INSTRUCTIONS,
    GAP_PROMPT_INJECTION_DEFENSE,
    assemble_gap_detection_prompt,
    build_gap_detection_prompt,
    build_gap_truncation_notice,
)
from app.services.ai.prompts.templates import SECURITY_SYSTEM_PROMPT

__all__ = [
    "PromptBuilder",
    "PromptBuildResult",
    "SourceDocument",
    "SourceTruncationMetadata",
    "SourceOmissionSummary",
    "SECURITY_SYSTEM_PROMPT",
    "EVIDENCE_EXTRACTION_TASK_HEADER",
    "EVIDENCE_GROUNDING_RULES",
    "EVIDENCE_EXTRACTION_INSTRUCTIONS",
    "EVIDENCE_PROMPT_INJECTION_DEFENSE",
    "EVIDENCE_EXTRACTION_JSON_CONTRACT",
    "EVIDENCE_EXTRACTION_FULL_INSTRUCTION",
    "build_truncation_notice",
    "build_evidence_extraction_prompt",
    "assemble_evidence_extraction_prompt",
    "GAP_DETECTION_TASK_HEADER",
    "GAP_GROUNDING_RULES",
    "GAP_CLASSIFICATION_INSTRUCTIONS",
    "GAP_PRIORITY_INSTRUCTIONS",
    "GAP_PROMPT_INJECTION_DEFENSE",
    "GAP_DETECTION_JSON_CONTRACT",
    "GAP_DETECTION_FULL_INSTRUCTION",
    "build_gap_truncation_notice",
    "build_gap_detection_prompt",
    "assemble_gap_detection_prompt",
    "SOURCE_OPEN_TAG",
    "SOURCE_CLOSE_TAG",
    "SOURCE_TAG_OPEN",
    "SOURCE_TAG_CLOSE",
    "SOURCES_BLOCK_OPEN_TAG",
    "SOURCES_BLOCK_CLOSE_TAG",
    "SOURCES_TRUNCATION_TAG",
    "TRUST_LEVEL_SYSTEM",
    "TRUST_LEVEL_TASK",
    "TRUST_LEVEL_SOURCE",
    "TRUST_LEVEL_OUTPUT",
    "SOURCE_TYPE_WEB",
    "SOURCE_TYPE_URL",
    "SOURCE_TYPE_PDF",
    "VALID_SOURCE_TYPES",
    "MAX_SOURCES_PER_PROMPT",
    "MAX_SOURCE_CHARS",
]
