"""Secure prompt construction for Bharmafills AI tasks.

PromptBuilder assembles ChatMessage lists for AI processing, enforcing the
four-tier trust hierarchy:

  - Level 1 (TRUSTED_SYSTEM): Immutable security prompt (templates.SECURITY_SYSTEM_PROMPT).
    Programmatically injected into the system turn.
  - Level 2 (TRUSTED_TASK): Application-controlled task instruction in the user turn.
    Programmatically separated from external source material.
  - Level 3 (UNTRUSTED_SOURCE): External web and PDF documents enclosed in XML fences
    (<untrusted_source_document>) after sanitizing XML control sequences.
  - Level 4 (UNVERIFIED_OUTPUT): Raw model completions. Provisional text that
    must undergo downstream structural validation via SafeResponseParser.

Structured Truncation & Omission Metadata (Step 9B.1.2)
-------------------------------------------------------
In addition to assembling safe ChatMessage lists, PromptBuilder returns
structured metadata directly in `PromptBuildResult`:
  - `source_metadata`: Per-source character truncation details (was_truncated,
    original_char_count, retained_char_count, omitted_char_count).
  - `source_summary`: Overall source-count omission details (total_sources_provided,
    total_sources_included, total_sources_omitted, omitted_source_ids).

Callers do not need to parse XML prompt strings to discover whether source content
was truncated or whole sources were omitted.

Backwards Compatibility
-----------------------
PromptBuildResult implements `__iter__`, `__getitem__`, and `__len__` targeting
`self.messages`, enabling transparent unpacking (`sys, user = result`), indexing
(`result[0]`), and passing directly to AI clients.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.services.ai.prompts.constants import (
    MAX_SOURCE_CHARS,
    MAX_SOURCES_PER_PROMPT,
    SOURCE_TAG_CLOSE,
    SOURCE_TAG_OPEN,
    SOURCES_BLOCK_CLOSE_TAG,
    SOURCES_BLOCK_OPEN_TAG,
    SOURCES_TRUNCATION_TAG,
    SOURCE_TYPE_URL,
    SOURCE_TYPE_WEB,
    VALID_SOURCE_TYPES,
)
from app.services.ai.prompts.templates import SECURITY_SYSTEM_PROMPT
from app.services.ai.schemas import ChatMessage

logger = logging.getLogger(__name__)

# Comprehensive regex to match XML comments, CDATA, processing instructions,
# declarations, and HTML/XML tags in untrusted source text.
_XML_INJECTION_RE = re.compile(
    r"(?:"
    r"<!--[\s\S]*?-->|"                  # XML comments
    r"<!\[CDATA\[[\s\S]*?\]\]>|"        # CDATA blocks
    r"<!DOCTYPE[\s\S]*?>|"              # DOCTYPE declarations
    r"<\?[\s\S]*?\?>|"                  # Processing instructions (<?xml...?>)
    r"<(/?)(\w[\w\-]*)((?:\s+[^>]*)?)/?>"  # Standard XML/HTML opening/closing tags
    r")",
    re.IGNORECASE,
)

# Sentinel replacement used when source text is sanitised.
_SANITISED_TAG_PLACEHOLDER = "[TAG_REMOVED_BY_SANITISER]"


@dataclass(frozen=True)
class SourceDocument:
    """Immutable descriptor for a single untrusted source document.

    Attributes:
        id:      Stable identifier for this source (e.g. a UUID or index string).
                 Must not contain XML special characters (< > ").
        type:    Source medium — "web", "url" (normalized to "web"), or "pdf".
        content: Raw extracted text from the source. This is UNTRUSTED DATA.
        title:   Optional document or page title for attribution.
    """

    id: str | UUID
    type: str
    content: str
    title: str | None = None

    def __post_init__(self) -> None:
        # Normalize UUID to string
        if isinstance(self.id, UUID):
            object.__setattr__(self, "id", str(self.id))
        elif not isinstance(self.id, str):
            object.__setattr__(self, "id", str(self.id))

        id_str = self.id.strip() if isinstance(self.id, str) else ""
        if not id_str:
            raise ValueError("SourceDocument.id must be a non-empty string or UUID.")
        object.__setattr__(self, "id", id_str)

        if "<" in self.id or ">" in self.id or '"' in self.id:
            raise ValueError(
                "SourceDocument.id must not contain XML special characters (< > \")."
            )

        # Normalize "url" to "web"
        norm_type = self.type.strip().lower() if isinstance(self.type, str) else ""
        if norm_type == SOURCE_TYPE_URL:
            norm_type = SOURCE_TYPE_WEB
        if norm_type not in VALID_SOURCE_TYPES:
            raise ValueError(
                f"SourceDocument.type must be one of {sorted(VALID_SOURCE_TYPES)}, got {self.type!r}."
            )
        object.__setattr__(self, "type", norm_type)

        if not isinstance(self.content, str):
            object.__setattr__(self, "content", str(self.content or ""))


@dataclass(frozen=True)
class SourceTruncationMetadata:
    """Per-source character truncation metadata returned by PromptBuilder.

    Attributes:
        source_id:           Identifier of the source.
        source_type:         Type of the source ('web' or 'pdf').
        was_truncated:       Whether any characters were omitted from the prompt.
        original_char_count: Character count of the sanitised source content.
        retained_char_count: Character count retained within the fenced prompt.
        omitted_char_count:  Character count omitted (original - retained).
    """

    source_id: str
    source_type: str
    was_truncated: bool
    original_char_count: int
    retained_char_count: int
    omitted_char_count: int

    def __post_init__(self) -> None:
        if self.original_char_count < 0:
            raise ValueError("original_char_count cannot be negative.")
        if self.retained_char_count < 0:
            raise ValueError("retained_char_count cannot be negative.")
        if self.retained_char_count > self.original_char_count:
            raise ValueError("retained_char_count cannot exceed original_char_count.")
        if self.omitted_char_count < 0:
            raise ValueError("omitted_char_count cannot be negative.")
        if self.omitted_char_count != self.original_char_count - self.retained_char_count:
            raise ValueError(
                f"omitted_char_count ({self.omitted_char_count}) must equal "
                f"original_char_count ({self.original_char_count}) - retained_char_count ({self.retained_char_count})."
            )
        expected_truncated = self.omitted_char_count > 0
        if self.was_truncated != expected_truncated:
            raise ValueError(
                f"was_truncated ({self.was_truncated}) does not match "
                f"omitted_char_count ({self.omitted_char_count})."
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert metadata to standard dictionary representation."""
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "was_truncated": self.was_truncated,
            "original_char_count": self.original_char_count,
            "retained_char_count": self.retained_char_count,
            "omitted_char_count": self.omitted_char_count,
        }


@dataclass(frozen=True)
class SourceOmissionSummary:
    """Overall source-count omission metadata returned by PromptBuilder.

    Attributes:
        total_sources_provided: Total number of sources passed to PromptBuilder.
        total_sources_included: Number of sources fenced within prompt capacity.
        total_sources_omitted:  Number of sources omitted due to MAX_SOURCES_PER_PROMPT.
        omitted_source_ids:     List of source IDs excluded by the limit.
    """

    total_sources_provided: int
    total_sources_included: int
    total_sources_omitted: int
    omitted_source_ids: list[str]

    def __post_init__(self) -> None:
        if self.total_sources_provided < 0:
            raise ValueError("total_sources_provided cannot be negative.")
        if self.total_sources_included < 0:
            raise ValueError("total_sources_included cannot be negative.")
        if self.total_sources_omitted < 0:
            raise ValueError("total_sources_omitted cannot be negative.")
        if self.total_sources_included + self.total_sources_omitted != self.total_sources_provided:
            raise ValueError(
                f"total_sources_included ({self.total_sources_included}) + "
                f"total_sources_omitted ({self.total_sources_omitted}) must equal "
                f"total_sources_provided ({self.total_sources_provided})."
            )
        if len(self.omitted_source_ids) != self.total_sources_omitted:
            raise ValueError(
                f"len(omitted_source_ids) ({len(self.omitted_source_ids)}) must equal "
                f"total_sources_omitted ({self.total_sources_omitted})."
            )

    @property
    def has_omissions(self) -> bool:
        """Return True if any sources were omitted from the prompt."""
        return self.total_sources_omitted > 0

    def to_dict(self) -> dict[str, Any]:
        """Convert summary to standard dictionary representation."""
        return {
            "total_sources_provided": self.total_sources_provided,
            "total_sources_included": self.total_sources_included,
            "total_sources_omitted": self.total_sources_omitted,
            "omitted_source_ids": list(self.omitted_source_ids),
        }


@dataclass(frozen=True)
class PromptBuildResult:
    """Structured result returned by PromptBuilder.build().

    Contains the assembled ChatMessage objects alongside transparent per-source
    truncation metadata and overall source-count omission summaries.

    Callers do not need to parse prompt XML strings to inspect whether source
    content was truncated or whole sources were omitted.

    Backwards compatibility:
      Implements __iter__, __getitem__, and __len__ so existing code expecting
      a list of ChatMessage objects (e.g. `messages[0]`, `sys, user = messages`,
      or `for msg in messages:`) continues to work seamlessly without modification.
    """

    messages: list[ChatMessage]
    source_metadata: list[SourceTruncationMetadata]
    source_summary: SourceOmissionSummary

    @property
    def has_character_truncation(self) -> bool:
        """Return True if any included source document was character-truncated."""
        return any(m.was_truncated for m in self.source_metadata)

    @property
    def has_source_omissions(self) -> bool:
        """Return True if any sources were omitted due to MAX_SOURCES_PER_PROMPT."""
        return self.source_summary.has_omissions

    def to_dict(self) -> dict[str, Any]:
        """Convert result to standard dictionary representation."""
        return {
            "messages": [m.model_dump() for m in self.messages],
            "source_metadata": [m.to_dict() for m in self.source_metadata],
            "source_summary": self.source_summary.to_dict(),
        }

    def __iter__(self):
        """Enable iteration and sequence unpacking over ChatMessage objects."""
        return iter(self.messages)

    def __getitem__(self, index: int | slice):
        """Enable indexing into ChatMessage objects (e.g. result[0], result[1])."""
        return self.messages[index]

    def __len__(self) -> int:
        """Return the number of ChatMessage objects."""
        return len(self.messages)


class PromptBuilder:
    """Assembles structured, XML-fenced ChatMessage lists for Bharmafills AI tasks.

    All methods are pure class-level utilities — no instance state is required.

    Design Safeguards & Trust Boundaries
    ------------------------------------
    1. The system message is always SECURITY_SYSTEM_PROMPT from templates.py.
       It is application-controlled and never derived from external content.
    2. Source documents are sanitised to strip XML control sequences, comments,
       CDATA, and tags before fencing, mitigating delimiter collision.
    3. Content truncation is transparent: XML tags include explicit truncated="true/false"
       attributes, and content includes visible omission notices.
    4. Source list truncation is transparent: exceeding MAX_SOURCES_PER_PROMPT
       injects an explicit <sources_truncation_notice> tag into the prompt.
    5. The system message is always the first element in the returned list.
    6. Task instructions are application-controlled; they are never derived from
       or modified by external source content.
    7. Limitation: Prompt demarcation mitigates delimiter-based injection but does
       not guarantee immunity against all model-level or semantic attacks.
       Downstream validation via SafeResponseParser is required.
    """

    @classmethod
    def sanitise_source_text(cls, text: str) -> str:
        """Strip XML tags, comments, CDATA, and control patterns from untrusted source text.

        Replaces XML markup with safe placeholders to reduce delimiter collision
        and injection risks. Preserves mathematical expressions such as 'x < 10'
        or 'price < $50'.

        Args:
            text: Raw extracted text from a website or PDF document.

        Returns:
            Sanitised text safe to embed inside XML fences.
        """
        if not text:
            return ""
        return _XML_INJECTION_RE.sub(_SANITISED_TAG_PLACEHOLDER, text)

    @classmethod
    def _normalize_source(cls, source: SourceDocument | dict[str, Any]) -> SourceDocument:
        """Convert a dict or SourceDocument instance into a valid SourceDocument."""
        if isinstance(source, SourceDocument):
            return source
        if isinstance(source, dict):
            return SourceDocument(
                id=str(source.get("id", "")),
                type=str(source.get("type", SOURCE_TYPE_WEB)),
                content=str(source.get("content", "")),
                title=source.get("title"),
            )
        raise TypeError(f"Expected SourceDocument or dict, got {type(source).__name__}")

    @classmethod
    def fence_source_with_metadata(
        cls,
        source: SourceDocument | dict[str, Any],
        index: int,
        *,
        truncate: bool = True,
    ) -> tuple[str, SourceTruncationMetadata]:
        """Wrap a single source document in XML isolation tags and return structured metadata.

        Args:
            source:   SourceDocument instance or dict to fence.
            index:    1-based ordinal position of this source in the prompt.
            truncate: If True, truncate source text exceeding MAX_SOURCE_CHARS.

        Returns:
            Tuple of (fenced_xml_string, SourceTruncationMetadata).
        """
        norm_source = cls._normalize_source(source)
        content = cls.sanitise_source_text(norm_source.content)

        is_truncated = False
        omitted_chars = 0
        original_chars = len(content)
        retained_chars = original_chars

        if truncate and original_chars > MAX_SOURCE_CHARS:
            is_truncated = True
            retained_chars = MAX_SOURCE_CHARS
            omitted_chars = original_chars - MAX_SOURCE_CHARS
            content = content[:MAX_SOURCE_CHARS]
            content += (
                f"\n[TRUNCATION NOTICE: Content exceeded limit of {MAX_SOURCE_CHARS:,} characters. "
                f"{omitted_chars:,} characters omitted to keep prompt within safe context bounds.]"
            )

        metadata = SourceTruncationMetadata(
            source_id=norm_source.id,
            source_type=norm_source.type,
            was_truncated=is_truncated,
            original_char_count=original_chars,
            retained_char_count=retained_chars,
            omitted_char_count=omitted_chars,
        )

        title_attr = ""
        if norm_source.title:
            sanitized_title = re.sub(r'["<>\n\r]', ' ', norm_source.title).strip()
            title_attr = f' title="{sanitized_title}"'

        trunc_attr = (
            f' truncated="true" omitted_chars="{omitted_chars}"'
            if is_truncated
            else ' truncated="false"'
        )

        open_tag = (
            f'{SOURCE_TAG_OPEN} id="{norm_source.id}" type="{norm_source.type}" '
            f'index="{index}"{title_attr}{trunc_attr}>'
        )
        fenced_str = f"{open_tag}\n{content}\n{SOURCE_TAG_CLOSE}"
        return fenced_str, metadata

    @classmethod
    def fence_source(
        cls,
        source: SourceDocument | dict[str, Any],
        index: int,
        *,
        truncate: bool = True,
    ) -> str:
        """Wrap a single source document in XML isolation tags with transparent truncation metadata.

        Preserves backwards compatibility for callers expecting a fenced string.

        Args:
            source:   SourceDocument instance or dict to fence.
            index:    1-based ordinal position of this source in the prompt.
            truncate: If True, truncate source text exceeding MAX_SOURCE_CHARS.

        Returns:
            Fenced XML string.
        """
        fenced_str, _ = cls.fence_source_with_metadata(source, index, truncate=truncate)
        return fenced_str

    @classmethod
    def build_sources_block_with_metadata(
        cls,
        sources: list[SourceDocument | dict[str, Any]],
    ) -> tuple[str, list[SourceTruncationMetadata], SourceOmissionSummary]:
        """Assemble the complete XML sources block and return structured metadata.

        Args:
            sources: Ordered list of SourceDocument or dict instances.

        Returns:
            Tuple of (sources_block_str, list[SourceTruncationMetadata], SourceOmissionSummary).
        """
        if not sources:
            summary = SourceOmissionSummary(
                total_sources_provided=0,
                total_sources_included=0,
                total_sources_omitted=0,
                omitted_source_ids=[],
            )
            return "", [], summary

        normalized = [cls._normalize_source(s) for s in sources]
        total_sources = len(normalized)

        if total_sources > MAX_SOURCES_PER_PROMPT:
            included_sources = normalized[:MAX_SOURCES_PER_PROMPT]
            omitted_sources = normalized[MAX_SOURCES_PER_PROMPT:]
            omitted_ids = [s.id for s in omitted_sources]
            logger.warning(
                "PromptBuilder received %d sources but MAX_SOURCES_PER_PROMPT=%d. "
                "Truncating %d excess source(s) from prompt.",
                total_sources,
                MAX_SOURCES_PER_PROMPT,
                len(omitted_sources),
            )
            truncation_tag = (
                f'\n<{SOURCES_TRUNCATION_TAG} total_provided="{total_sources}" '
                f'included="{MAX_SOURCES_PER_PROMPT}" omitted="{len(omitted_sources)}" '
                f'message="Source list exceeded prompt capacity; {len(omitted_sources)} source(s) omitted." />'
            )
        else:
            included_sources = normalized
            omitted_ids = []
            truncation_tag = ""

        summary = SourceOmissionSummary(
            total_sources_provided=total_sources,
            total_sources_included=len(included_sources),
            total_sources_omitted=len(omitted_ids),
            omitted_source_ids=omitted_ids,
        )

        fenced_items: list[str] = []
        metadata_list: list[SourceTruncationMetadata] = []

        for i, s in enumerate(included_sources):
            fenced_str, meta = cls.fence_source_with_metadata(s, i + 1)
            fenced_items.append(fenced_str)
            metadata_list.append(meta)

        inner = "\n\n".join(fenced_items)
        if truncation_tag:
            inner = f"{inner}{truncation_tag}"

        block_str = f"{SOURCES_BLOCK_OPEN_TAG}\n{inner}\n{SOURCES_BLOCK_CLOSE_TAG}"
        return block_str, metadata_list, summary

    @classmethod
    def build_sources_block(
        cls,
        sources: list[SourceDocument | dict[str, Any]],
    ) -> str:
        """Assemble the complete XML sources block for backwards compatibility.

        Args:
            sources: Ordered list of SourceDocument or dict instances.

        Returns:
            Multi-line XML string enclosed in <untrusted_sources> wrapper tags.
        """
        block_str, _, _ = cls.build_sources_block_with_metadata(sources)
        return block_str

    @classmethod
    def build(
        cls,
        task_instruction: str,
        sources: list[SourceDocument | dict[str, Any]] | None = None,
    ) -> PromptBuildResult:
        """Assemble a complete, security-hardened ChatMessage list with structured metadata.

        The returned PromptBuildResult contains:
          - `messages`: list of ChatMessage objects (system role then user role).
          - `source_metadata`: list of SourceTruncationMetadata for included sources.
          - `source_summary`: SourceOmissionSummary describing source counts and omitted IDs.

        Args:
            task_instruction: Application-controlled trusted task description.
                              Must not be empty. Must not be derived from or
                              modified by any external source content.
            sources:          Optional list of SourceDocument or dict instances to
                              include as XML-fenced untrusted source material.

        Returns:
            PromptBuildResult envelope with messages and structured metadata.

        Raises:
            ValueError: If task_instruction is empty or whitespace-only.
        """
        if not task_instruction or not task_instruction.strip():
            raise ValueError(
                "task_instruction must be a non-empty application-controlled string. "
                "Do not pass source content as a task instruction."
            )

        user_parts: list[str] = [task_instruction.strip()]

        if sources:
            sources_block, metadata_list, summary = cls.build_sources_block_with_metadata(sources)
            if sources_block:
                user_parts.append(sources_block)
        else:
            metadata_list = []
            summary = SourceOmissionSummary(
                total_sources_provided=0,
                total_sources_included=0,
                total_sources_omitted=0,
                omitted_source_ids=[],
            )

        user_content = "\n\n".join(user_parts)

        messages = [
            ChatMessage(role="system", content=SECURITY_SYSTEM_PROMPT),
            ChatMessage(role="user", content=user_content),
        ]

        return PromptBuildResult(
            messages=messages,
            source_metadata=metadata_list,
            source_summary=summary,
        )

    @classmethod
    def build_system_only(cls) -> PromptBuildResult:
        """Return a PromptBuildResult containing only the security system prompt.

        Useful for health checks or capability probes that do not require
        source material.

        Returns:
            PromptBuildResult containing a single system ChatMessage.
        """
        messages = [ChatMessage(role="system", content=SECURITY_SYSTEM_PROMPT)]
        summary = SourceOmissionSummary(
            total_sources_provided=0,
            total_sources_included=0,
            total_sources_omitted=0,
            omitted_source_ids=[],
        )
        return PromptBuildResult(
            messages=messages,
            source_metadata=[],
            source_summary=summary,
        )
