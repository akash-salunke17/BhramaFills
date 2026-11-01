"""Immutable string constants for the Bharmafills prompt security architecture.

All XML tag names and trust-level identifiers are defined here so that
templates, builder logic, and tests all reference a single source of truth.
Changing a tag name here propagates automatically everywhere.
"""

# ---------------------------------------------------------------------------
# XML fence tags for untrusted source content isolation
# ---------------------------------------------------------------------------

# Root wrapper around a single external source document
SOURCE_OPEN_TAG = "untrusted_source_document"
SOURCE_CLOSE_TAG = "untrusted_source_document"

# Convenience formatted strings used by PromptBuilder
SOURCE_TAG_OPEN: str = f"<{SOURCE_OPEN_TAG}"   # caller appends attributes, e.g.  id="1" type="web">
SOURCE_TAG_CLOSE: str = f"</{SOURCE_CLOSE_TAG}>"

# Wrapper for the entire multi-source block handed to the model
SOURCES_BLOCK_OPEN_TAG: str = "<untrusted_sources>"
SOURCES_BLOCK_CLOSE_TAG: str = "</untrusted_sources>"
SOURCES_TRUNCATION_TAG: str = "sources_truncation_notice"

# ---------------------------------------------------------------------------
# Trust level labels (informational, used in log and audit messages only)
# ---------------------------------------------------------------------------

TRUST_LEVEL_SYSTEM: str = "TRUSTED_SYSTEM"       # Application system prompt
TRUST_LEVEL_TASK: str = "TRUSTED_TASK"            # Application task instructions
TRUST_LEVEL_SOURCE: str = "UNTRUSTED_SOURCE"      # External website / PDF text
TRUST_LEVEL_OUTPUT: str = "UNVERIFIED_OUTPUT"     # Raw AI completion text

# ---------------------------------------------------------------------------
# Valid source type identifiers for XML attributes
# ---------------------------------------------------------------------------

SOURCE_TYPE_WEB: str = "web"
SOURCE_TYPE_URL: str = "url"
SOURCE_TYPE_PDF: str = "pdf"
VALID_SOURCE_TYPES: frozenset[str] = frozenset({SOURCE_TYPE_WEB, SOURCE_TYPE_URL, SOURCE_TYPE_PDF})

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

# Maximum number of sources that may be included in a single prompt
MAX_SOURCES_PER_PROMPT: int = 20

# Maximum character length of a single fenced source block (before truncation)
MAX_SOURCE_CHARS: int = 40_000

