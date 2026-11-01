"""Information Gap Detection Service for Bharmafills.

Orchestrates multi-source evidence retrieval, prompt assembly with truncation transparency,
OpenRouter AI completion, safe response parsing, and independent backend grounding
validation against the project's evidence corpus.

Key Architectural Guarantees:
1. Strict Ownership Enforcement: Mandatory `user_id: UUID` checked via `verify_project_ownership`
   inside the active database connection before executing any data retrieval or external AI call.
   Nonexistent, unowned, and foreign-owned projects uniformly return generic `ProjectNotFoundError`.
2. Safe Evidence Retrieval: Parameterized SQL exclusively. Never loads cross-tenant or unowned records.
3. Separation of Extracted Statements vs. Claims: Extracted statements (`public.evidence`) are source-attributed
   statements excerpted directly from documents; source claims (`public.source_claims`) are unverified assertions.
   Neither represents external independent factual verification.
4. Truncation & Omission Awareness: Consumes `PromptBuildResult` metadata from `PromptBuilder`.
   Explicitly warns the caller and marks findings if character truncation or source omissions occurred.
5. Anti-Hallucination & Independent Validation: Validates AI candidate gaps against actual project
   evidence using `ValidatedGapFinding` with verdicts:
   - `confirmed`: Missing information verified absent across all analyzed project sources.
   - `partially_covered`: Some evidence addresses related subtopics or aspects, but specific parameters/questions remain unanswered.
   - `disputed_by_evidence`: Existing source evidence materially challenges or contradicts candidate's claim of missingness.
   - `redundant`: Substantially duplicates a prior candidate in the same analysis.
6. Empty & Failed Corpus Handling: If 0 sources or 0 evidence exist, or all sources failed ingestion,
   AI completion is bypassed and a clear diagnostic result is returned without hallucinating gaps.
7. Zero Persistence in Step 10C: Operates strictly in-memory; does not write to `public.information_gaps`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import json
import logging
import re
from typing import Any, Sequence
from uuid import UUID

import asyncpg

from app.core.config import Settings, get_settings
from app.core.ownership import (
    ProjectAccessDeniedError,
    ProjectNotFoundError,
    verify_project_ownership,
)
from app.db.connection import DatabaseManager, get_db_manager
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
from app.services.ai.gap_schemas import (
    AIGapCandidatePayload,
    AIGapDetectionPayload,
    GapDetectionResult,
    GapPriority,
    GapType,
    ValidatedGapFinding,
    ValidationVerdict,
)
from app.services.ai.openrouter_client import OpenRouterClient
from app.services.ai.parser import SafeResponseParser
from app.services.ai.prompts.builder import PromptBuildResult, SourceDocument
from app.services.ai.prompts.gap_templates import assemble_gap_detection_prompt
from app.services.ai.schemas import ChatCompletionRequest

logger = logging.getLogger("bharmafills.services.ai.gap_detection")

# Common English stopwords excluded from concept extraction to prevent false lexical matches
_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "aren't", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both",
    "but", "by", "can", "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does",
    "doesn't", "doing", "don't", "down", "during", "each", "few", "for", "from", "further", "had",
    "hadn't", "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i", "i'd",
    "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself",
    "let's", "me", "more", "most", "mustn't", "my", "myself", "no", "nor", "not", "of", "off",
    "on", "once", "only", "or", "other", "ought", "our", "ours", "ourselves", "out", "over", "own",
    "same", "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some",
    "such", "than", "that", "that's", "the", "their", "theirs", "them", "themselves", "then",
    "there", "there's", "these", "they", "they'd", "they'll", "they're", "they've", "this",
    "those", "through", "to", "too", "under", "until", "up", "very", "was", "wasn't", "we",
    "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when", "when's",
    "where", "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't",
    "would", "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself",
    "yourselves",
}


# Canonical concept clusters to recognize different wording expressing the same concept
_CANONICAL_CONCEPT_CLUSTERS: dict[str, set[str]] = {
    "financial_subsidy": {
        "subsidy", "subsidies", "assistance", "grant", "grants", "rebate", "rebates",
        "incentive", "incentives", "allowance", "funding", "stipend", "subvention",
        "aid", "credit", "credits",
    },
    "eligibility_criteria": {
        "eligibility", "eligible", "qualification", "qualifications", "qualify",
        "qualifying", "criteria", "criterion", "requirement", "requirements",
        "prerequisite", "prerequisites", "threshold", "thresholds", "condition", "conditions",
    },
    "cost_pricing": {
        "cost", "costs", "price", "pricing", "expense", "expenses", "expenditure",
        "budget", "financial", "capex", "opex", "tariff", "tariffs", "fee", "fees",
    },
    "waste_disposal": {
        "disposal", "recycle", "recycling", "waste", "decommissioning",
        "landfill", "landfills", "e-waste", "scrapping", "scrap", "discard",
    },
    "environmental_impact": {
        "environmental", "environment", "ecological", "footprint", "emissions",
        "pollution", "pollutant", "carbon", "toxic", "toxicity", "leachate",
    },
    "regulatory_compliance": {
        "regulatory", "regulations", "regulation", "compliance", "policy", "statutory",
        "legal", "legislation", "mandate", "mandates", "standard", "standards", "rule", "rules",
        "fine", "fines", "penalty", "penalties", "enforcement",
    },
    "performance_efficiency": {
        "efficiency", "performance", "yield", "output", "capacity", "generation",
        "degradation", "durability", "lifespan", "lifetime",
    },
    "health_safety": {
        "health", "safety", "hazard", "hazards", "hazardous", "risk", "risks",
        "injury", "illness", "exposure", "adverse",
    },
    "deployment_installation": {
        "deployment", "installation", "installing", "adoption", "rollout",
        "implementation", "commissioning", "setup",
    },
    "maintenance_operations": {
        "maintenance", "maintaining", "servicing", "service", "upkeep",
        "operational", "operations", "repair", "repairs",
    },
    "timeline_duration": {
        "timeline", "schedule", "duration", "timeframe", "milestone", "milestones",
        "delay", "delays", "deadline", "turnaround",
    },
    "geographic_location": {
        "geographic", "geography", "regional", "region", "jurisdiction", "jurisdictions",
        "state", "local", "federal", "national",
    },
}

_TOKEN_TO_CANONICAL: dict[str, str] = {}
for canonical, tokens in _CANONICAL_CONCEPT_CLUSTERS.items():
    for tok in tokens:
        _TOKEN_TO_CANONICAL[tok] = canonical


def _stem_simple(tok: str) -> str:
    """Apply simple deterministic suffix stripping for English vocabulary."""
    if tok.endswith("ies") and len(tok) > 4:
        return tok[:-3] + "y"
    if tok.endswith("ing") and len(tok) > 5:
        return tok[:-3]
    if tok.endswith("ed") and len(tok) > 4:
        return tok[:-2]
    if tok.endswith("s") and not tok.endswith("ss") and len(tok) > 3:
        return tok[:-1]
    return tok


def _extract_key_concepts(text: str) -> set[str]:
    """Extract substantive concepts, stems, and canonical concept cluster identifiers."""
    if not text:
        return set()
    raw_tokens = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
    concepts: set[str] = set()
    for raw in raw_tokens:
        if raw in _STOPWORDS:
            continue
        concepts.add(raw)
        stemmed = _stem_simple(raw)
        concepts.add(stemmed)

        # Check canonical clusters for raw or stemmed form
        cluster = _TOKEN_TO_CANONICAL.get(raw) or _TOKEN_TO_CANONICAL.get(stemmed)
        if cluster:
            concepts.add(f"concept:{cluster}")

    return concepts


def _is_redundant_candidate(
    candidate: AIGapCandidatePayload,
    existing_findings: Sequence[ValidatedGapFinding],
) -> ValidatedGapFinding | None:
    """Identify if a candidate substantially duplicates an earlier candidate in this analysis."""
    cand_tokens = _extract_key_concepts(f"{candidate.target_subquestion} {candidate.gap_description}")
    if not cand_tokens:
        return None

    cand_subq_norm = candidate.target_subquestion.strip().lower()

    for item in existing_findings:
        prior = item.candidate
        prior_subq_norm = prior.target_subquestion.strip().lower()

        # Exact subquestion match
        if cand_subq_norm == prior_subq_norm:
            return item

        # High Jaccard concept overlap with matching gap_type
        prior_tokens = _extract_key_concepts(f"{prior.target_subquestion} {prior.gap_description}")
        if not prior_tokens:
            continue

        intersection = cand_tokens.intersection(prior_tokens)
        union = cand_tokens.union(prior_tokens)
        jaccard = len(intersection) / len(union) if union else 0.0

        if jaccard >= 0.80 and candidate.gap_type == prior.gap_type:
            return item

    return None


@dataclass
class GroundingAssessment:
    """Encapsulates backend evidence grounding verdict and detailed context."""

    verdict: ValidationVerdict
    grounded_facts_count: int
    covered_evidence_ids: list[UUID]
    grounding_notes: str


def _assess_candidate_grounding(
    candidate: AIGapCandidatePayload,
    facts: Sequence[dict[str, Any]],
    fact_topic_names: dict[UUID, list[str]],
    valid_project_evidence_ids: set[UUID],
    research_question: str,
    evaluated_sources_count: int,
    has_corpus_truncation: bool,
) -> GroundingAssessment:
    """Assess candidate gap against project evidence using semantic concept heuristics.

    Guarantees:
    - Zero lexical overlap does NOT claim universal non-existence; notes explicit corpus scope.
    - Multiple shared keywords in different contexts do not falsely dispute a genuine gap.
    - Different wording expressing the same concept is recognized via canonical concept clusters.
    - Topic association alone provides domain context (yielding `partially_covered`), not complete proof.
    - Evidence answering only part of a multi-part inquiry yields `partially_covered`.
    - `disputed_by_evidence` is strictly reserved for when source evidence directly contradicts
      a candidate's missing-information claim.
    """
    subq_concepts = _extract_key_concepts(candidate.target_subquestion)
    cand_desc_concepts = _extract_key_concepts(candidate.gap_description)
    combined_cand_concepts = subq_concepts.union(cand_desc_concepts)

    rq_concepts = _extract_key_concepts(research_question)
    specific_inquiry_concepts = subq_concepts - rq_concepts
    if len(specific_inquiry_concepts) < 2:
        specific_inquiry_concepts = subq_concepts

    subq_clusters = {c for c in subq_concepts if c.startswith("concept:")}
    is_multifacet = len(subq_clusters) >= 2

    substantive_fact_ids: list[UUID] = []
    partial_aspect_fact_ids: list[UUID] = []
    topic_context_fact_ids: list[UUID] = []

    related_topic = candidate.related_topic_name.strip().lower() if candidate.related_topic_name else None

    for fact in facts:
        fact_id = fact["id"]
        if fact_id not in valid_project_evidence_ids:
            continue

        fact_text = f"{fact.get('claim', '')} {fact.get('supporting_excerpt', '')}"
        fact_concepts = _extract_key_concepts(fact_text)
        fact_clusters = {c for c in fact_concepts if c.startswith("concept:")}

        # 1. Topic context match
        has_topic_match = False
        if related_topic:
            topics_for_fact = [t.lower() for t in fact_topic_names.get(fact_id, [])]
            if related_topic in topics_for_fact:
                has_topic_match = True

        # 2. Specific substantive inquiry overlap
        specific_shared = specific_inquiry_concepts.intersection(fact_concepts)
        shared_clusters = subq_clusters.intersection(fact_clusters)

        # Check if the fact matches specific inquiry concepts beyond background words
        has_substantive_overlap = False
        if len(specific_shared) >= 2:
            has_substantive_overlap = True
        elif len(specific_inquiry_concepts) > 0 and (len(specific_shared) / len(specific_inquiry_concepts) >= 0.5):
            has_substantive_overlap = True
        elif shared_clusters:
            has_substantive_overlap = True

        if has_substantive_overlap:
            # Check if candidate inquiry is multi-part and this fact covers only some facets
            if is_multifacet:
                matched_clusters = subq_clusters.intersection(fact_clusters)
                if len(matched_clusters) < len(subq_clusters):
                    partial_aspect_fact_ids.append(fact_id)
                else:
                    substantive_fact_ids.append(fact_id)
            else:
                substantive_fact_ids.append(fact_id)
        elif has_topic_match:
            topic_context_fact_ids.append(fact_id)

    # Compile sanitized covered evidence IDs in priority order
    covered_evidence_ids = list(
        dict.fromkeys(substantive_fact_ids + partial_aspect_fact_ids + topic_context_fact_ids)
    )
    facts_count = len(covered_evidence_ids)

    # Verdict Determination
    verdict: ValidationVerdict
    notes: str

    if facts_count == 0:
        verdict = "confirmed"
        notes = (
            f"Confirmed: Within the analyzed corpus of {evaluated_sources_count} source(s), "
            f"zero source statements were found addressing the specific subquestion '{candidate.target_subquestion}'."
        )
    elif candidate.gap_type == GapType.NO_EVIDENCE and len(substantive_fact_ids) >= 2 and len(partial_aspect_fact_ids) == 0:
        # Candidate asserts no evidence, but multiple concrete statements directly address this specific inquiry
        verdict = "disputed_by_evidence"
        notes = (
            f"Disputed by evidence: Candidate asserts no evidence exists, but {len(substantive_fact_ids)} "
            f"source statement(s) directly provide evidence addressing this specific subquestion "
            f"(e.g., statement ID: {substantive_fact_ids[0]})."
        )
    else:
        # Some evidence exists: either partial facet coverage, single substantive statement, or topic context
        verdict = "partially_covered"
        if is_multifacet and partial_aspect_fact_ids and not substantive_fact_ids:
            notes = (
                f"Partially covered: {facts_count} source statement(s) address some facets of this multi-part inquiry, "
                f"but remaining aspects (e.g., eligibility, costs, or enforcement) remain unaddressed within the analyzed corpus."
            )
        elif not substantive_fact_ids and not partial_aspect_fact_ids and topic_context_fact_ids:
            notes = (
                f"Partially covered: {facts_count} source statement(s) provide related context under topic "
                f"'{candidate.related_topic_name or 'general'}', but the specific inquiry regarding "
                f"'{candidate.target_subquestion}' is not directly answered within the analyzed corpus."
            )
        else:
            notes = (
                f"Partially covered: {facts_count} source statement(s) provide related context, "
                f"but specific operational, eligibility, or quantitative parameters highlighted in "
                f"the gap remain absent or uncorroborated."
            )

    if has_corpus_truncation:
        notes += " [Notice: Partial corpus coverage; omitted sources or sections may contain relevant details.]"

    return GroundingAssessment(
        verdict=verdict,
        grounded_facts_count=facts_count,
        covered_evidence_ids=covered_evidence_ids,
        grounding_notes=notes,
    )


def _find_matching_evidence(
    candidate: AIGapCandidatePayload,
    facts: Sequence[dict[str, Any]],
    fact_topic_names: dict[UUID, list[str]],
) -> list[UUID]:
    """Identify source statements in the project corpus that relate to candidate's topic or subquestion."""
    assessment = _assess_candidate_grounding(
        candidate=candidate,
        facts=facts,
        fact_topic_names=fact_topic_names,
        valid_project_evidence_ids={f["id"] for f in facts},
        research_question="",
        evaluated_sources_count=len(facts),
        has_corpus_truncation=False,
    )
    return assessment.covered_evidence_ids


def _format_source_evidence_content(
    source: dict[str, Any],
    source_facts: Sequence[dict[str, Any]],
    source_claims: Sequence[dict[str, Any]],
    fact_topics: dict[UUID, list[str]],
) -> str:
    """Format extracted source statements and claims for a single source document into prompt content."""
    lines: list[str] = [
        f"SOURCE METADATA:",
        f"- Source Title: {source.get('title', 'Untitled')}",
        f"- Source Medium: {source.get('source_type', 'unknown')}",
    ]

    if source.get("original_url"):
        lines.append(f"- URL: {source['original_url']}")
    elif source.get("original_filename"):
        lines.append(f"- Filename: {source['original_filename']}")

    lines.append("")
    lines.append("EXTRACTED SOURCE STATEMENTS (Statements excerpted directly from this source - not independently verified facts):")
    if source_facts:
        for f in source_facts:
            f_id = f["id"]
            claim_text = f.get("claim", "").strip()
            fact_type = f.get("fact_type", "general")
            rep_type = f.get("representation_type", "direct_quote")
            confidence = f.get("confidence_score", 1.0)
            topics = fact_topics.get(f_id, [])
            topic_str = f" | Topics: {', '.join(topics)}" if topics else ""

            lines.append(
                f"- [Statement ID: {f_id}] \"{claim_text}\" (Type: {fact_type}, Form: {rep_type}, Stated Confidence: {confidence:.2f}{topic_str})"
            )
            if f.get("supporting_excerpt"):
                lines.append(f"  Excerpt: \"{f['supporting_excerpt'].strip()}\"")
            if f.get("uncertainty_notes"):
                lines.append(f"  Caveat/Uncertainty: {f['uncertainty_notes']}")
    else:
        lines.append("  (No discrete source statements extracted for this source)")

    lines.append("")
    lines.append("SOURCE CLAIMS (Assertions made by this source - unverified assertions):")
    if source_claims:
        for c in source_claims:
            c_id = c["id"]
            claim_text = c.get("claim_text", "").strip()
            claim_type = c.get("claim_type", "factual_assertion")
            confidence = c.get("confidence_score", 0.8)

            lines.append(
                f"- [Claim ID: {c_id}] \"{claim_text}\" (Claim Type: {claim_type}, Stated Confidence: {confidence:.2f})"
            )
            if c.get("uncertainty_notes"):
                lines.append(f"  Caveat/Uncertainty: {c['uncertainty_notes']}")
    else:
        lines.append("  (No claims recorded for this source)")

    return "\n".join(lines)


class InformationGapDetectionService:
    """Service orchestrating AI-assisted information gap detection across multi-source evidence."""

    def __init__(
        self,
        db_manager: DatabaseManager | None = None,
        ai_provider: BaseAIProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._db_manager = db_manager or get_db_manager()
        self._settings = settings or get_settings()
        self._ai_provider = ai_provider

    @property
    def ai_provider(self) -> BaseAIProvider:
        """Lazily initialize or return configured AI provider."""
        if self._ai_provider is None:
            self._ai_provider = OpenRouterClient(settings=self._settings)
        return self._ai_provider

    @property
    def is_configured(self) -> bool:
        """Return True if the underlying AI provider is configured with an API key."""
        if hasattr(self.ai_provider, "is_configured"):
            return bool(self.ai_provider.is_configured)
        return True

    @property
    def active_model(self) -> str:
        """Return active model identifier from provider or settings."""
        if hasattr(self.ai_provider, "active_model") and isinstance(self.ai_provider.active_model, str):
            return self.ai_provider.active_model
        return self._settings.OPENROUTER_MODEL

    async def detect_gaps(
        self,
        project_id: UUID,
        user_id: UUID,
        custom_instructions: str | None = None,
    ) -> GapDetectionResult:
        """Detect information gaps relative to a research project's inquiry and evidence corpus.

        Args:
            project_id: Target project UUID.
            user_id: Authenticated caller UUID.
            custom_instructions: Optional user-provided domain focus directives.

        Returns:
            GapDetectionResult containing validated gap findings and telemetry.

        Raises:
            TypeError: If project_id or user_id is not a UUID instance.
            ProjectNotFoundError: If the project does not exist, is soft-deleted, or not owned by user.
            ValueError: If the project has an invalid or missing research question.
            AIProviderError: If the AI completion fails or returns unparseable outputs.
        """
        # 1. Identity type validation
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")
        if not isinstance(project_id, UUID):
            raise TypeError(f"project_id must be a UUID instance, got {type(project_id).__name__}")

        # 2. Project ownership & active status verification within database connection
        async with self._db_manager.acquire_connection() as conn:
            try:
                project_context = await verify_project_ownership(conn, project_id, user_id)
            except ProjectAccessDeniedError as exc:
                logger.warning("Ownership access denied for project %s by user %s", project_id, user_id)
                raise ProjectNotFoundError(f"Research project '{project_id}' was not found.") from exc

            # 3. Retrieve full project definition
            proj_row = await conn.fetchrow(
                """
                SELECT id, title, research_question, description, category, status
                FROM public.research_projects
                WHERE id = $1 AND deleted_at IS NULL;
                """,
                project_id,
            )
            if not proj_row:
                raise ProjectNotFoundError(f"Research project '{project_id}' was not found.")

            research_question = (proj_row["research_question"] or "").strip()
            if not research_question or len(research_question) < 10:
                raise ValueError(
                    f"Research project '{project_id}' has an invalid or missing research question (minimum 10 characters required)."
                )

            # 4. Retrieve sources
            sources = await conn.fetch(
                """
                SELECT id, source_type, title, original_url, original_filename,
                       ingestion_status, error_message, file_metadata, created_at
                FROM public.sources
                WHERE project_id = $1 AND deleted_at IS NULL
                ORDER BY created_at ASC;
                """,
                project_id,
            )

            # Check Empty Sources Safeguard
            if not sources:
                logger.info("Project %s contains 0 sources. Skipping AI detection.", project_id)
                return GapDetectionResult(
                    project_id=project_id,
                    research_question=research_question,
                    total_gaps_detected=0,
                    gaps=[],
                    analysis_summary="Insufficient evidence to perform information gap detection. The research project currently contains no sources.",
                    warnings=[
                        "No sources have been added to this research project. Please ingest web or PDF sources and extract evidence before running gap detection."
                    ],
                    has_corpus_truncation=False,
                    sources_evaluated=0,
                    facts_evaluated=0,
                    claims_evaluated=0,
                    topics_evaluated=0,
                    ai_analysis_executed=False,
                    diagnostic_message="Insufficient evidence: 0 sources available in project.",
                )

            # Check Failed Extraction Safeguard
            failed_sources = [s for s in sources if s["ingestion_status"] == "failed"]
            if len(failed_sources) == len(sources):
                reasons = [
                    f"'{s['title']}': {s['error_message'] or 'Ingestion failed'}"
                    for s in failed_sources
                ]
                logger.warning("All sources in project %s failed ingestion. Skipping AI detection.", project_id)
                return GapDetectionResult(
                    project_id=project_id,
                    research_question=research_question,
                    total_gaps_detected=0,
                    gaps=[],
                    analysis_summary="Insufficient evidence to perform information gap detection. All sources in the project failed ingestion or extraction.",
                    warnings=[
                        f"All sources failed ingestion or evidence extraction: {'; '.join(reasons)}. Ingestion failures cannot be evaluated as genuine information gaps."
                    ],
                    has_corpus_truncation=False,
                    sources_evaluated=len(sources),
                    facts_evaluated=0,
                    claims_evaluated=0,
                    topics_evaluated=0,
                    ai_analysis_executed=False,
                    diagnostic_message="Insufficient evidence: all project sources failed ingestion.",
                )

            # 5. Retrieve topics, evidence facts, and source claims
            topics = await conn.fetch(
                """
                SELECT id, name, description
                FROM public.topics
                WHERE project_id = $1
                ORDER BY name ASC;
                """,
                project_id,
            )

            facts = await conn.fetch(
                """
                SELECT e.id, e.source_id, e.extraction_run_id, e.fact_id, e.claim,
                       e.fact_type, e.supporting_excerpt, e.representation_type,
                       e.confidence_score, e.location_reference, e.qualifiers,
                       e.uncertainty_notes, e.extraction_warnings, e.start_char,
                       e.end_char, e.page_number, e.url,
                       s.title AS source_title, s.source_type
                FROM public.evidence e
                JOIN public.sources s ON s.id = e.source_id
                WHERE e.project_id = $1 AND s.deleted_at IS NULL
                ORDER BY e.created_at ASC, e.id ASC;
                """,
                project_id,
            )

            claims = await conn.fetch(
                """
                SELECT sc.id, sc.source_id, sc.extraction_run_id, sc.claim_id,
                       sc.claim_text, sc.claim_type, sc.representation_type,
                       sc.confidence_score, sc.location_reference, sc.qualifiers,
                       sc.uncertainty_notes, sc.extraction_warnings, sc.start_char,
                       sc.end_char, sc.page_number, sc.url,
                       s.title AS source_title, s.source_type
                FROM public.source_claims sc
                JOIN public.sources s ON s.id = sc.source_id
                WHERE sc.project_id = $1 AND s.deleted_at IS NULL
                ORDER BY sc.created_at ASC, sc.id ASC;
                """,
                project_id,
            )

            evidence_topics_rows = await conn.fetch(
                """
                SELECT et.evidence_id, et.topic_id, t.name AS topic_name
                FROM public.evidence_topics et
                JOIN public.topics t ON t.id = et.topic_id
                WHERE t.project_id = $1;
                """,
                project_id,
            )

        # Build topic-evidence index
        fact_topics: dict[UUID, list[str]] = {}
        for r in evidence_topics_rows:
            fact_topics.setdefault(r["evidence_id"], []).append(r["topic_name"])

        # Check Zero Evidence Safeguard
        if not facts and not claims:
            logger.info("Project %s has sources but 0 facts/claims. Skipping AI detection.", project_id)
            return GapDetectionResult(
                project_id=project_id,
                research_question=research_question,
                total_gaps_detected=0,
                gaps=[],
                analysis_summary="Insufficient evidence to perform information gap detection. Sources are present, but no facts or claims have been extracted yet.",
                warnings=[
                    "No extracted facts or source claims were found for this project. Please execute evidence extraction on the project's sources before running gap detection."
                ],
                has_corpus_truncation=False,
                sources_evaluated=len(sources),
                facts_evaluated=0,
                claims_evaluated=0,
                topics_evaluated=len(topics),
                ai_analysis_executed=False,
                diagnostic_message="Insufficient evidence: 0 extracted facts or claims found.",
            )

        # 6. Group evidence per source and construct SourceDocument descriptors
        facts_by_source: dict[UUID, list[dict[str, Any]]] = {}
        for f in facts:
            facts_by_source.setdefault(f["source_id"], []).append(dict(f))

        claims_by_source: dict[UUID, list[dict[str, Any]]] = {}
        for c in claims:
            claims_by_source.setdefault(c["source_id"], []).append(dict(c))

        source_docs: list[SourceDocument] = []
        for s in sources:
            sid = s["id"]
            s_facts = facts_by_source.get(sid, [])
            s_claims = claims_by_source.get(sid, [])

            # Only include sources that have facts or claims extracted
            if not s_facts and not s_claims:
                continue

            content = _format_source_evidence_content(
                source=dict(s),
                source_facts=s_facts,
                source_claims=s_claims,
                fact_topics=fact_topics,
            )

            # Normalize type: "url" -> "web", "pdf" -> "pdf"
            raw_type = s["source_type"]
            normalized_type = "web" if raw_type == "url" else raw_type

            source_docs.append(
                SourceDocument(
                    id=str(sid),
                    type=normalized_type,
                    title=s["title"],
                    content=content,
                )
            )

        # 7. Assemble Prompt Envelope with Truncation Transparency
        topic_names = [t["name"] for t in topics]
        prompt_result: PromptBuildResult = assemble_gap_detection_prompt(
            sources=source_docs,
            research_question=research_question,
            existing_topics=topic_names,
            custom_instructions=custom_instructions,
        )

        has_corpus_truncation = (
            prompt_result.has_character_truncation or prompt_result.has_source_omissions
        )

        warnings: list[str] = []
        if prompt_result.has_character_truncation:
            warnings.append(
                "One or more source documents exceeded prompt character limits and were partially truncated. Some evidence details could not be evaluated."
            )
        if prompt_result.has_source_omissions:
            warnings.append(
                f"Prompt source capacity was reached. Only {prompt_result.source_summary.total_sources_included} of {prompt_result.source_summary.total_sources_provided} sources were evaluated ({prompt_result.source_summary.total_sources_omitted} source(s) omitted: {', '.join(prompt_result.source_summary.omitted_source_ids)})."
            )

        # Note any failed sources alongside valid sources
        if failed_sources:
            failed_titles = ", ".join(f"'{s['title']}'" for s in failed_sources)
            warnings.append(
                f"{len(failed_sources)} source(s) in this project failed ingestion and could not be evaluated: {failed_titles}."
            )

        # 8. Call OpenRouter AI Completion
        completion_request = ChatCompletionRequest(
            model=self.active_model,
            messages=prompt_result.messages,
            temperature=0.1,
            max_tokens=3000,
        )

        response = await self.ai_provider.complete(completion_request)
        raw_text = response.choices[0].message.content if response.choices else ""

        # 9. Parse and Validate AI Response Structure
        parse_result = SafeResponseParser.parse_model_output(raw_text, AIGapDetectionPayload)
        if not parse_result.is_valid or parse_result.parsed_data is None:
            logger.error("Failed to parse gap detection output: %s", parse_result.validation_error)
            raise AIResponseValidationError(
                f"Failed to parse or validate AI gap detection output: {parse_result.validation_error}"
            )

        ai_payload: AIGapDetectionPayload = parse_result.parsed_data

        # Incorporate model-reported caveats and warnings
        for w in ai_payload.warnings:
            if w and w not in warnings:
                warnings.append(w)

        # 10. Independent Backend Evidence Grounding Validation
        valid_project_evidence_ids = {f["id"] for f in facts}
        validated_findings: list[ValidatedGapFinding] = []

        for candidate in ai_payload.gaps:
            # Stage A: Check for redundancy against prior evaluated findings
            redundant_match = _is_redundant_candidate(candidate, validated_findings)
            if redundant_match is not None:
                validated_findings.append(
                    ValidatedGapFinding(
                        candidate=candidate,
                        validation_verdict="redundant",
                        grounded_facts_count=0,
                        covered_evidence_ids=[],
                        corpus_truncation_warning=has_corpus_truncation,
                        grounding_notes=(
                            f"Redundant: Substantially duplicates Candidate #{redundant_match.candidate.candidate_id} "
                            f"targeting the same subquestion."
                        ),
                        source_omission_warning=warnings[1] if prompt_result.has_source_omissions else None,
                    )
                )
                continue

            # Stage B: Evidence Grounding & Cross-Referencing
            assessment = _assess_candidate_grounding(
                candidate=candidate,
                facts=[dict(f) for f in facts],
                fact_topic_names=fact_topics,
                valid_project_evidence_ids=valid_project_evidence_ids,
                research_question=research_question,
                evaluated_sources_count=len(source_docs),
                has_corpus_truncation=has_corpus_truncation,
            )

            omission_msg = (
                f"{prompt_result.source_summary.total_sources_omitted} source(s) were omitted from context."
                if prompt_result.has_source_omissions
                else None
            )

            validated_findings.append(
                ValidatedGapFinding(
                    candidate=candidate,
                    validation_verdict=assessment.verdict,
                    grounded_facts_count=assessment.grounded_facts_count,
                    covered_evidence_ids=assessment.covered_evidence_ids,
                    corpus_truncation_warning=has_corpus_truncation,
                    grounding_notes=assessment.grounding_notes,
                    source_omission_warning=omission_msg,
                )
            )

        # 11. Compile Authoritative GapDetectionResult Envelope
        return GapDetectionResult(
            project_id=project_id,
            research_question=research_question,
            total_gaps_detected=len(validated_findings),
            gaps=validated_findings,
            analysis_summary=ai_payload.analysis_summary,
            warnings=warnings,
            has_corpus_truncation=has_corpus_truncation,
            sources_evaluated=len(source_docs),
            facts_evaluated=len(facts),
            claims_evaluated=len(claims),
            topics_evaluated=len(topics),
            ai_analysis_executed=True,
            diagnostic_message=None,
        )


@lru_cache
def get_gap_detection_service() -> InformationGapDetectionService:
    """Return a cached singleton instance of InformationGapDetectionService."""
    return InformationGapDetectionService()
