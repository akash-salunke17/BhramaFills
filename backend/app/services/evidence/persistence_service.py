"""Evidence database persistence, transaction management, and retrieval service for Bharmafills."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import json
import logging
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from app.core.config import Settings, get_settings
from app.core.ownership import ProjectAccessDeniedError, verify_project_ownership
from app.db.connection import (
    DatabaseManager,
    DatabaseNotConfiguredError,
    DatabaseUnavailableError,
    get_db_manager,
)
from app.services.ai.evidence_schemas import (
    BatchEvidenceExtractionResult,
    ClaimType,
    EvidenceExtractionResult,
    EvidenceLocation,
    EvidenceSourceType,
    ExtractionStatus,
    FactType,
    RepresentationType,
)
from app.services.evidence.exceptions import (
    DuplicateExtractionRunError,
    EvidencePersistenceError,
    EvidenceTransactionError,
    ExtractionRunNotFoundError,
    InvalidEvidencePayloadError,
    SourceMismatchError,
)
from app.services.evidence.schemas import (
    BatchPersistenceResponse,
    ExtractionRunListResponse,
    ExtractionRunResponse,
    PersistedClaimResponse,
    PersistedEvidenceRunResponse,
    PersistedFactResponse,
    ProjectEvidenceResponse,
)
from app.services.sources.exceptions import ProjectNotFoundError, SourceNotFoundError

logger = logging.getLogger("bharmafills.services.evidence.persistence")


def _parse_json(val: Any, default: Any = None) -> Any:
    """Parse JSON field if returned as string from asyncpg, or return directly."""
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return default
    return default


def _pad_min_len(text: str, min_len: int = 5) -> str:
    """Ensure string satisfies database check constraint minimum length."""
    trimmed = text.strip()
    if len(trimmed) >= min_len:
        return trimmed
    return trimmed.ljust(min_len, ".")


class EvidencePersistenceService:
    """Manages transactional persistence and retrieval of extracted facts and claims."""

    def __init__(
        self,
        db_manager: DatabaseManager | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._db_manager = db_manager or get_db_manager()

    @property
    def is_configured(self) -> bool:
        """Return True if database connection is configured."""
        return self._db_manager.is_configured

    async def validate_project_and_source(
        self,
        conn: asyncpg.Connection,
        project_id: UUID,
        source_id: UUID | str,
        user_id: UUID,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Validate research project existence, caller ownership, source existence, and project-source relationship.

        Raises:
            TypeError: If user_id is not a UUID instance.
            ProjectNotFoundError: If research project does not exist, is soft-deleted, or unowned/unauthorized.
            SourceNotFoundError: If source does not exist.
            SourceMismatchError: If source belongs to a different research project.
        """
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")

        resolved_source_uuid = UUID(str(source_id))

        # Check project existence and ownership
        try:
            context = await verify_project_ownership(conn, project_id, user_id)
            project_data = {
                "id": context.id,
                "user_id": context.user_id,
                "title": context.title,
            }
        except ProjectAccessDeniedError as exc:
            raise ProjectNotFoundError(f"Research project '{project_id}' was not found.") from exc

        # Check source existence and verify project_id foreign key match
        source_row = await conn.fetchrow(
            """
            SELECT id, project_id, title, source_type, original_url
            FROM public.sources
            WHERE id = $1 AND deleted_at IS NULL;
            """,
            resolved_source_uuid,
        )
        if not source_row:
            raise SourceNotFoundError(
                f"Source '{resolved_source_uuid}' was not found in project '{project_id}'."
            )

        if source_row["project_id"] != project_id:
            raise SourceMismatchError(
                f"Source '{resolved_source_uuid}' belongs to project '{source_row['project_id']}', "
                f"not target project '{project_id}'."
            )

        return project_data, dict(source_row)

    async def persist_extraction_result(
        self,
        project_id: UUID,
        source_id: UUID | str,
        result: EvidenceExtractionResult,
        user_id: UUID,
        batch_id: UUID | None = None,
        idempotency_key: str | None = None,
    ) -> PersistedEvidenceRunResponse:
        """Atomically persist an EvidenceExtractionResult, its run metadata, facts, and claims.

        Guarantees:
        - Atomic all-or-nothing database transaction.
        - Idempotency when identical run or idempotency_key is submitted.
        - Re-extraction preserves historical runs without silent overwrites.
        - Strict cross-project, cross-user, and cross-source isolation.
        """
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")

        resolved_source_uuid = UUID(str(source_id))

        # Verify source_id attribution matches result.source_id
        if str(resolved_source_uuid) != str(result.source_id):
            raise InvalidEvidencePayloadError(
                f"Source UUID '{resolved_source_uuid}' does not match extraction result source_id '{result.source_id}'."
            )

        async with self._db_manager.acquire_connection() as conn:
            # 1. Validate project and source
            await self.validate_project_and_source(conn, project_id, resolved_source_uuid, user_id=user_id)

            # 2. Check for existing idempotent run if key provided
            if idempotency_key:
                existing_run_row = await conn.fetchrow(
                    """
                    SELECT id, project_id, source_id, batch_id, provider, model_name,
                           extraction_status, source_truncated, source_character_count,
                           processed_character_count, facts_count, claims_count,
                           warnings, errors, run_metadata, extracted_at, created_at
                    FROM public.extraction_runs
                    WHERE project_id = $1 AND run_metadata->>'idempotency_key' = $2
                    LIMIT 1;
                    """,
                    project_id,
                    idempotency_key,
                )
                if existing_run_row:
                    logger.info(
                        "Idempotent extraction run resolved for key '%s' (Run ID: %s)",
                        idempotency_key,
                        existing_run_row["id"],
                    )
                    return await self._build_persisted_run_response(conn, dict(existing_run_row))

            # 3. Transactional persistence
            async with conn.transaction():
                # A. Insert extraction_runs record
                run_id = uuid4()
                now_utc = datetime.now(timezone.utc)
                run_metadata = {
                    "source_type": result.source_type.value,
                    "warnings_count": len(result.warnings),
                    "errors_count": len(result.errors),
                }
                if idempotency_key:
                    run_metadata["idempotency_key"] = idempotency_key

                try:
                    run_row = await conn.fetchrow(
                        """
                        INSERT INTO public.extraction_runs (
                            id,
                            project_id,
                            source_id,
                            batch_id,
                            provider,
                            model_name,
                            extraction_status,
                            source_truncated,
                            source_character_count,
                            processed_character_count,
                            facts_count,
                            claims_count,
                            warnings,
                            errors,
                            run_metadata,
                            extracted_at,
                            created_at
                        )
                        VALUES (
                            $1, $2, $3, $4, 'openrouter', 'nvidia/nemotron-3-ultra-550b-a55b:free',
                            $5, $6, $7, $8, $9, $10,
                            $11::jsonb, $12::jsonb, $13::jsonb, $14, $15
                        )
                        RETURNING id, created_at;
                        """,
                        run_id,
                        project_id,
                        resolved_source_uuid,
                        batch_id,
                        result.extraction_status.value,
                        result.source_truncated,
                        result.source_character_count,
                        result.processed_character_count,
                        len(result.facts),
                        len(result.claims),
                        json.dumps(result.warnings),
                        json.dumps(result.errors),
                        json.dumps(run_metadata),
                        result.extracted_at,
                        now_utc,
                    )
                except Exception as exc:
                    logger.error("Failed to insert extraction_run record: %s", type(exc).__name__)
                    raise EvidenceTransactionError(
                        f"Failed to record extraction run: {type(exc).__name__}"
                    ) from exc

                # B. Insert Extracted Facts into public.evidence
                persisted_facts: list[PersistedFactResponse] = []
                for fact in result.facts:
                    fact_db_id = uuid4()
                    location_dict = fact.location.model_dump()
                    statement_text = _pad_min_len(fact.statement, min_len=5)
                    evidence_text = _pad_min_len(fact.evidence_text, min_len=5)

                    try:
                        fact_row = await conn.fetchrow(
                            """
                            INSERT INTO public.evidence (
                                id,
                                project_id,
                                source_id,
                                extraction_run_id,
                                fact_id,
                                claim,
                                fact_type,
                                supporting_excerpt,
                                representation_type,
                                confidence_score,
                                location_reference,
                                start_char,
                                end_char,
                                page_number,
                                url,
                                qualifiers,
                                uncertainty_notes,
                                extraction_warnings,
                                ai_model,
                                analysis_metadata,
                                created_at,
                                updated_at
                            )
                            VALUES (
                                $1, $2, $3, $4,
                                $5, $6, $7, $8,
                                $9, $10::jsonb, $11, $12,
                                $13, $14, $15::jsonb, $16, $17::jsonb,
                                'nvidia/nemotron-3-ultra-550b-a55b:free', '{}'::jsonb,
                                $18, $18
                            )
                            RETURNING id, created_at;
                            """,
                            fact_db_id,
                            project_id,
                            resolved_source_uuid,
                            run_id,
                            fact.fact_id,
                            statement_text,
                            fact.fact_type.value,
                            evidence_text,
                            fact.representation_type.value,
                            round(fact.confidence, 3),
                            json.dumps(location_dict),
                            fact.location.start_char,
                            fact.location.end_char,
                            fact.location.page_number,
                            fact.location.url,
                            json.dumps(fact.qualifiers),
                            fact.uncertainty_notes,
                            json.dumps(fact.extraction_warnings),
                            now_utc,
                        )
                    except Exception as exc:
                        logger.error(
                            "Failed to insert fact '%s' for run %s: %s",
                            fact.fact_id,
                            run_id,
                            type(exc).__name__,
                        )
                        raise EvidenceTransactionError(
                            f"Failed to persist fact '{fact.fact_id}': {type(exc).__name__}"
                        ) from exc

                    persisted_facts.append(
                        PersistedFactResponse(
                            id=fact_row["id"],
                            project_id=project_id,
                            source_id=resolved_source_uuid,
                            extraction_run_id=run_id,
                            fact_id=fact.fact_id,
                            statement=fact.statement,
                            fact_type=fact.fact_type,
                            evidence_text=fact.evidence_text,
                            representation_type=fact.representation_type,
                            confidence=fact.confidence,
                            location=fact.location,
                            qualifiers=fact.qualifiers,
                            uncertainty_notes=fact.uncertainty_notes,
                            extraction_warnings=fact.extraction_warnings,
                            created_at=fact_row["created_at"],
                        )
                    )

                # C. Insert Source Claims into public.source_claims
                persisted_claims: list[PersistedClaimResponse] = []
                for claim in result.claims:
                    claim_db_id = uuid4()
                    loc_dict = claim.evidence_location.model_dump()
                    claim_text = _pad_min_len(claim.claim_text, min_len=3)

                    try:
                        claim_row = await conn.fetchrow(
                            """
                            INSERT INTO public.source_claims (
                                id,
                                project_id,
                                source_id,
                                extraction_run_id,
                                claim_id,
                                claim_text,
                                claim_type,
                                representation_type,
                                confidence_score,
                                location_reference,
                                start_char,
                                end_char,
                                page_number,
                                url,
                                qualifiers,
                                uncertainty_notes,
                                extraction_warnings,
                                created_at,
                                updated_at
                            )
                            VALUES (
                                $1, $2, $3, $4,
                                $5, $6, $7, $8,
                                $9, $10::jsonb, $11, $12,
                                $13, $14, $15::jsonb, $16, $17::jsonb,
                                $18, $18
                            )
                            RETURNING id, created_at;
                            """,
                            claim_db_id,
                            project_id,
                            resolved_source_uuid,
                            run_id,
                            claim.claim_id,
                            claim_text,
                            claim.claim_type.value,
                            claim.representation_type.value,
                            round(claim.confidence, 3),
                            json.dumps(loc_dict),
                            claim.evidence_location.start_char,
                            claim.evidence_location.end_char,
                            claim.evidence_location.page_number,
                            claim.evidence_location.url,
                            json.dumps(claim.qualifiers),
                            claim.uncertainty_notes,
                            json.dumps(claim.extraction_warnings),
                            now_utc,
                        )
                    except Exception as exc:
                        logger.error(
                            "Failed to insert claim '%s' for run %s: %s",
                            claim.claim_id,
                            run_id,
                            type(exc).__name__,
                        )
                        raise EvidenceTransactionError(
                            f"Failed to persist claim '{claim.claim_id}': {type(exc).__name__}"
                        ) from exc

                    persisted_claims.append(
                        PersistedClaimResponse(
                            id=claim_row["id"],
                            project_id=project_id,
                            source_id=resolved_source_uuid,
                            extraction_run_id=run_id,
                            claim_id=claim.claim_id,
                            claim_text=claim.claim_text,
                            claim_type=claim.claim_type,
                            representation_type=claim.representation_type,
                            confidence=claim.confidence,
                            evidence_location=claim.evidence_location,
                            qualifiers=claim.qualifiers,
                            uncertainty_notes=claim.uncertainty_notes,
                            extraction_warnings=claim.extraction_warnings,
                            created_at=claim_row["created_at"],
                        )
                    )

            logger.info(
                "Successfully persisted extraction run %s for source %s (%d facts, %d claims)",
                run_id,
                resolved_source_uuid,
                len(persisted_facts),
                len(persisted_claims),
            )

            run_response = ExtractionRunResponse(
                id=run_id,
                project_id=project_id,
                source_id=resolved_source_uuid,
                batch_id=batch_id,
                provider="openrouter",
                model_name="nvidia/nemotron-3-ultra-550b-a55b:free",
                extraction_status=result.extraction_status,
                source_truncated=result.source_truncated,
                source_character_count=result.source_character_count,
                processed_character_count=result.processed_character_count,
                facts_count=len(persisted_facts),
                claims_count=len(persisted_claims),
                warnings=result.warnings,
                errors=result.errors,
                run_metadata=run_metadata,
                extracted_at=result.extracted_at,
                created_at=now_utc,
            )

            return PersistedEvidenceRunResponse(
                run=run_response,
                facts=persisted_facts,
                claims=persisted_claims,
            )

    async def persist_batch_extraction_results(
        self,
        project_id: UUID,
        batch_result: BatchEvidenceExtractionResult,
        user_id: UUID,
    ) -> BatchPersistenceResponse:
        """Persist a batch of extraction results with independent per-source failure isolation."""
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a valid UUID, got {type(user_id).__name__}")
        batch_id = uuid4()
        successful_runs: list[PersistedEvidenceRunResponse] = []
        errors: list[str] = []

        for item in batch_result.results:
            try:
                persisted = await self.persist_extraction_result(
                    project_id=project_id,
                    source_id=UUID(str(item.source_id)),
                    result=item,
                    user_id=user_id,
                    batch_id=batch_id,
                )
                successful_runs.append(persisted)
            except Exception as exc:
                err_msg = f"Failed to persist source '{item.source_id}': {type(exc).__name__}: {str(exc)}"
                logger.error(err_msg)
                errors.append(err_msg)

        return BatchPersistenceResponse(
            batch_id=batch_id,
            total_sources=len(batch_result.results),
            successful_runs=len(successful_runs),
            failed_runs=len(errors),
            runs=successful_runs,
            errors=errors,
        )

    async def _build_persisted_run_response(
        self,
        conn: asyncpg.Connection,
        run_dict: dict[str, Any],
    ) -> PersistedEvidenceRunResponse:
        """Fetch linked facts and claims to reconstruct a PersistedEvidenceRunResponse."""
        run_id = run_dict["id"]
        project_id = run_dict["project_id"]
        source_id = run_dict["source_id"]

        run_response = ExtractionRunResponse(
            id=run_id,
            project_id=project_id,
            source_id=source_id,
            batch_id=run_dict.get("batch_id"),
            provider=run_dict.get("provider", "openrouter"),
            model_name=run_dict.get("model_name", "nvidia/nemotron-3-ultra-550b-a55b:free"),
            extraction_status=ExtractionStatus(run_dict["extraction_status"]),
            source_truncated=run_dict.get("source_truncated", False),
            source_character_count=run_dict.get("source_character_count", 0),
            processed_character_count=run_dict.get("processed_character_count", 0),
            facts_count=run_dict.get("facts_count", 0),
            claims_count=run_dict.get("claims_count", 0),
            warnings=_parse_json(run_dict.get("warnings"), default=[]),
            errors=_parse_json(run_dict.get("errors"), default=[]),
            run_metadata=_parse_json(run_dict.get("run_metadata"), default={}),
            extracted_at=run_dict["extracted_at"],
            created_at=run_dict["created_at"],
        )

        # Fetch facts
        fact_rows = await conn.fetch(
            """
            SELECT id, project_id, source_id, extraction_run_id, fact_id,
                   claim, fact_type, supporting_excerpt, representation_type,
                   confidence_score, location_reference, qualifiers,
                   uncertainty_notes, extraction_warnings, created_at
            FROM public.evidence
            WHERE extraction_run_id = $1
            ORDER BY created_at ASC, id ASC;
            """,
            run_id,
        )
        facts = [
            PersistedFactResponse(
                id=r["id"],
                project_id=r["project_id"],
                source_id=r["source_id"],
                extraction_run_id=r["extraction_run_id"],
                fact_id=r["fact_id"],
                statement=r["claim"],
                fact_type=FactType(r["fact_type"]),
                evidence_text=r["supporting_excerpt"],
                representation_type=RepresentationType(r["representation_type"]),
                confidence=float(r["confidence_score"]),
                location=EvidenceLocation(**_parse_json(r["location_reference"], default={})),
                qualifiers=_parse_json(r["qualifiers"], default=[]),
                uncertainty_notes=r["uncertainty_notes"],
                extraction_warnings=_parse_json(r["extraction_warnings"], default=[]),
                created_at=r["created_at"],
            )
            for r in fact_rows
        ]

        # Fetch claims
        claim_rows = await conn.fetch(
            """
            SELECT id, project_id, source_id, extraction_run_id, claim_id,
                   claim_text, claim_type, representation_type, confidence_score,
                   location_reference, qualifiers, uncertainty_notes,
                   extraction_warnings, created_at
            FROM public.source_claims
            WHERE extraction_run_id = $1
            ORDER BY created_at ASC, id ASC;
            """,
            run_id,
        )
        claims = [
            PersistedClaimResponse(
                id=r["id"],
                project_id=r["project_id"],
                source_id=r["source_id"],
                extraction_run_id=r["extraction_run_id"],
                claim_id=r["claim_id"],
                claim_text=r["claim_text"],
                claim_type=ClaimType(r["claim_type"]),
                representation_type=RepresentationType(r["representation_type"]),
                confidence=float(r["confidence_score"]),
                evidence_location=EvidenceLocation(**_parse_json(r["location_reference"], default={})),
                qualifiers=_parse_json(r["qualifiers"], default=[]),
                uncertainty_notes=r["uncertainty_notes"],
                extraction_warnings=_parse_json(r["extraction_warnings"], default=[]),
                created_at=r["created_at"],
            )
            for r in claim_rows
        ]

        return PersistedEvidenceRunResponse(
            run=run_response,
            facts=facts,
            claims=claims,
        )

    async def get_source_evidence(
        self,
        project_id: UUID,
        source_id: UUID,
        user_id: UUID,
        extraction_run_id: UUID | None = None,
        item_type: str = "all",
        fact_type: str | None = None,
        claim_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ProjectEvidenceResponse:
        """Retrieve persisted facts and claims for a specific source document."""
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")

        async with self._db_manager.acquire_connection() as conn:
            await self.validate_project_and_source(conn, project_id, source_id, user_id=user_id)
            return await self._query_evidence(
                conn=conn,
                project_id=project_id,
                source_id=source_id,
                extraction_run_id=extraction_run_id,
                item_type=item_type,
                fact_type=fact_type,
                claim_type=claim_type,
                limit=limit,
                offset=offset,
            )

    async def get_project_evidence(
        self,
        project_id: UUID,
        user_id: UUID,
        source_id: UUID | None = None,
        extraction_run_id: UUID | None = None,
        item_type: str = "all",
        fact_type: str | None = None,
        claim_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ProjectEvidenceResponse:
        """Retrieve persisted facts and claims across an entire research project."""
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")

        async with self._db_manager.acquire_connection() as conn:
            try:
                await verify_project_ownership(conn, project_id, user_id)
            except ProjectAccessDeniedError as exc:
                raise ProjectNotFoundError(f"Research project '{project_id}' was not found.") from exc

            if source_id:
                await self.validate_project_and_source(conn, project_id, source_id, user_id=user_id)

            return await self._query_evidence(
                conn=conn,
                project_id=project_id,
                source_id=source_id,
                extraction_run_id=extraction_run_id,
                item_type=item_type,
                fact_type=fact_type,
                claim_type=claim_type,
                limit=limit,
                offset=offset,
            )

    async def _query_evidence(
        self,
        conn: asyncpg.Connection,
        project_id: UUID,
        source_id: UUID | None,
        extraction_run_id: UUID | None,
        item_type: str,
        fact_type: str | None,
        claim_type: str | None,
        limit: int,
        offset: int,
    ) -> ProjectEvidenceResponse:
        """Internal helper executing parameterized queries for facts and claims."""
        facts: list[PersistedFactResponse] = []
        claims: list[PersistedClaimResponse] = []
        total_facts = 0
        total_claims = 0

        include_facts = item_type.lower() in ("all", "facts", "fact")
        include_claims = item_type.lower() in ("all", "claims", "claim")

        # 1. Query Facts
        if include_facts:
            conditions = ["project_id = $1"]
            params: list[Any] = [project_id]

            if source_id:
                params.append(source_id)
                conditions.append(f"source_id = ${len(params)}")

            if extraction_run_id:
                params.append(extraction_run_id)
                conditions.append(f"extraction_run_id = ${len(params)}")

            if fact_type:
                params.append(fact_type.strip().lower())
                conditions.append(f"fact_type = ${len(params)}")

            where_clause = " AND ".join(conditions)

            count_row = await conn.fetchval(
                f"SELECT count(*) FROM public.evidence WHERE {where_clause};",
                *params,
            )
            total_facts = count_row or 0

            params.append(limit)
            limit_idx = len(params)
            params.append(offset)
            offset_idx = len(params)

            rows = await conn.fetch(
                f"""
                SELECT id, project_id, source_id, extraction_run_id, fact_id,
                       claim, fact_type, supporting_excerpt, representation_type,
                       confidence_score, location_reference, qualifiers,
                       uncertainty_notes, extraction_warnings, created_at
                FROM public.evidence
                WHERE {where_clause}
                ORDER BY created_at ASC, id ASC
                LIMIT ${limit_idx} OFFSET ${offset_idx};
                """,
                *params,
            )
            facts = [
                PersistedFactResponse(
                    id=r["id"],
                    project_id=r["project_id"],
                    source_id=r["source_id"],
                    extraction_run_id=r["extraction_run_id"],
                    fact_id=r["fact_id"],
                    statement=r["claim"],
                    fact_type=FactType(r["fact_type"]),
                    evidence_text=r["supporting_excerpt"],
                    representation_type=RepresentationType(r["representation_type"]),
                    confidence=float(r["confidence_score"]),
                    location=EvidenceLocation(**_parse_json(r["location_reference"], default={})),
                    qualifiers=_parse_json(r["qualifiers"], default=[]),
                    uncertainty_notes=r["uncertainty_notes"],
                    extraction_warnings=_parse_json(r["extraction_warnings"], default=[]),
                    created_at=r["created_at"],
                )
                for r in rows
            ]

        # 2. Query Claims
        if include_claims:
            claim_conditions = ["project_id = $1"]
            claim_params: list[Any] = [project_id]

            if source_id:
                claim_params.append(source_id)
                claim_conditions.append(f"source_id = ${len(claim_params)}")

            if extraction_run_id:
                claim_params.append(extraction_run_id)
                claim_conditions.append(f"extraction_run_id = ${len(claim_params)}")

            if claim_type:
                claim_params.append(claim_type.strip().lower())
                claim_conditions.append(f"claim_type = ${len(claim_params)}")

            claim_where = " AND ".join(claim_conditions)

            count_claims_val = await conn.fetchval(
                f"SELECT count(*) FROM public.source_claims WHERE {claim_where};",
                *claim_params,
            )
            total_claims = count_claims_val or 0

            claim_params.append(limit)
            c_limit_idx = len(claim_params)
            claim_params.append(offset)
            c_offset_idx = len(claim_params)

            c_rows = await conn.fetch(
                f"""
                SELECT id, project_id, source_id, extraction_run_id, claim_id,
                       claim_text, claim_type, representation_type, confidence_score,
                       location_reference, qualifiers, uncertainty_notes,
                       extraction_warnings, created_at
                FROM public.source_claims
                WHERE {claim_where}
                ORDER BY created_at ASC, id ASC
                LIMIT ${c_limit_idx} OFFSET ${c_offset_idx};
                """,
                *claim_params,
            )
            claims = [
                PersistedClaimResponse(
                    id=r["id"],
                    project_id=r["project_id"],
                    source_id=r["source_id"],
                    extraction_run_id=r["extraction_run_id"],
                    claim_id=r["claim_id"],
                    claim_text=r["claim_text"],
                    claim_type=ClaimType(r["claim_type"]),
                    representation_type=RepresentationType(r["representation_type"]),
                    confidence=float(r["confidence_score"]),
                    evidence_location=EvidenceLocation(**_parse_json(r["location_reference"], default={})),
                    qualifiers=_parse_json(r["qualifiers"], default=[]),
                    uncertainty_notes=r["uncertainty_notes"],
                    extraction_warnings=_parse_json(r["extraction_warnings"], default=[]),
                    created_at=r["created_at"],
                )
                for r in c_rows
            ]

        return ProjectEvidenceResponse(
            project_id=project_id,
            source_id=source_id,
            total_facts=total_facts,
            total_claims=total_claims,
            limit=limit,
            offset=offset,
            facts=facts,
            claims=claims,
        )

    async def list_extraction_runs(
        self,
        project_id: UUID,
        user_id: UUID,
        source_id: UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> ExtractionRunListResponse:
        """List extraction runs for a project or source with pagination."""
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")

        async with self._db_manager.acquire_connection() as conn:
            try:
                await verify_project_ownership(conn, project_id, user_id)
            except ProjectAccessDeniedError as exc:
                raise ProjectNotFoundError(f"Research project '{project_id}' was not found.") from exc

            conditions = ["project_id = $1"]
            params: list[Any] = [project_id]

            if source_id:
                await self.validate_project_and_source(conn, project_id, source_id, user_id=user_id)
                params.append(source_id)
                conditions.append(f"source_id = ${len(params)}")

            where_clause = " AND ".join(conditions)

            total_runs = await conn.fetchval(
                f"SELECT count(*) FROM public.extraction_runs WHERE {where_clause};",
                *params,
            )

            params.append(limit)
            limit_idx = len(params)
            params.append(offset)
            offset_idx = len(params)

            rows = await conn.fetch(
                f"""
                SELECT id, project_id, source_id, batch_id, provider, model_name,
                       extraction_status, source_truncated, source_character_count,
                       processed_character_count, facts_count, claims_count,
                       warnings, errors, run_metadata, extracted_at, created_at
                FROM public.extraction_runs
                WHERE {where_clause}
                ORDER BY extracted_at DESC, id DESC
                LIMIT ${limit_idx} OFFSET ${offset_idx};
                """,
                *params,
            )

            runs = [
                ExtractionRunResponse(
                    id=r["id"],
                    project_id=r["project_id"],
                    source_id=r["source_id"],
                    batch_id=r["batch_id"],
                    provider=r["provider"],
                    model_name=r["model_name"],
                    extraction_status=ExtractionStatus(r["extraction_status"]),
                    source_truncated=r["source_truncated"],
                    source_character_count=r["source_character_count"],
                    processed_character_count=r["processed_character_count"],
                    facts_count=r["facts_count"],
                    claims_count=r["claims_count"],
                    warnings=_parse_json(r["warnings"], default=[]),
                    errors=_parse_json(r["errors"], default=[]),
                    run_metadata=_parse_json(r["run_metadata"], default={}),
                    extracted_at=r["extracted_at"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

            return ExtractionRunListResponse(
                total_runs=total_runs or 0,
                limit=limit,
                offset=offset,
                runs=runs,
            )

    async def get_extraction_run_detail(
        self,
        project_id: UUID,
        run_id: UUID,
        user_id: UUID,
    ) -> PersistedEvidenceRunResponse:
        """Retrieve full details of an extraction run including its facts and claims."""
        if not isinstance(user_id, UUID):
            raise TypeError(f"user_id must be a UUID instance, got {type(user_id).__name__}")

        async with self._db_manager.acquire_connection() as conn:
            try:
                await verify_project_ownership(conn, project_id, user_id)
            except ProjectAccessDeniedError as exc:
                raise ProjectNotFoundError(f"Research project '{project_id}' was not found.") from exc

            run_row = await conn.fetchrow(
                """
                SELECT id, project_id, source_id, batch_id, provider, model_name,
                       extraction_status, source_truncated, source_character_count,
                       processed_character_count, facts_count, claims_count,
                       warnings, errors, run_metadata, extracted_at, created_at
                FROM public.extraction_runs
                WHERE id = $1 AND project_id = $2;
                """,
                run_id,
                project_id,
            )
            if not run_row:
                raise ExtractionRunNotFoundError(
                    f"Extraction run '{run_id}' was not found in project '{project_id}'."
                )

            return await self._build_persisted_run_response(conn, dict(run_row))


@lru_cache
def get_evidence_persistence_service() -> EvidencePersistenceService:
    """Return a cached singleton instance of EvidencePersistenceService."""
    settings = get_settings()
    db_manager = get_db_manager()
    return EvidencePersistenceService(db_manager=db_manager, settings=settings)

