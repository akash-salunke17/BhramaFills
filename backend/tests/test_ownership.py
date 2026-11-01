"""Comprehensive unit and integration tests for Bharmafills project ownership authorization foundation.

Phase D2 Test Suite covering:
- Group 1: Data model immutability & exception hierarchy
- Group 2: verify_project_ownership (happy path, foreign owner, unowned, soft-deleted, missing)
- Group 3: Child resource relationship verification (sources, evidence, runs, claims)
- Group 4: get_owned_project FastAPI dependency and HTTP 404 information-disclosure protection
- Group 5: Service-layer ownership enforcement (web, PDF, persistence services)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from fastapi import HTTPException, status
import pytest

from app.core.auth_schemas import AuthenticatedUser
from app.core.ownership import (
    OwnedProjectContext,
    ProjectAccessDeniedError,
    ResourceMismatchError,
    get_owned_project,
    verify_evidence_belongs_to_project,
    verify_extraction_run_belongs_to_project,
    verify_project_ownership,
    verify_source_belongs_to_project,
    verify_source_claim_belongs_to_project,
)
from app.db.connection import DatabaseManager
from app.services.evidence.persistence_service import EvidencePersistenceService
from app.services.pdf.service import PDFSourceIngestionService
from app.services.sources.exceptions import ProjectNotFoundError, SourceNotFoundError
from app.services.sources.web_source_service import WebSourceIngestionService

# Deterministic test UUIDs
USER_A_ID = UUID("00000000-0000-4000-a000-000000000001")
USER_B_ID = UUID("00000000-0000-4000-b000-000000000002")
PROJECT_A_ID = UUID("11111111-1111-4000-a000-000000000001")
PROJECT_B_ID = UUID("22222222-2222-4000-b000-000000000002")
SOURCE_A_ID = UUID("33333333-3333-4000-a000-000000000001")
EVIDENCE_A_ID = UUID("44444444-4444-4000-a000-000000000001")
RUN_A_ID = UUID("55555555-5555-4000-a000-000000000001")
CLAIM_A_ID = UUID("66666666-6666-4000-a000-000000000001")


# =============================================================================
# Group 1: Data Model & Domain Exception Tests
# =============================================================================

def test_owned_project_context_is_frozen_and_immutable():
    """Verify OwnedProjectContext is an immutable dataclass."""
    ctx = OwnedProjectContext(
        id=PROJECT_A_ID,
        user_id=USER_A_ID,
        title="Antarctic Ice Core Research",
        status="In Progress",
    )
    assert ctx.id == PROJECT_A_ID
    assert ctx.user_id == USER_A_ID
    assert ctx.title == "Antarctic Ice Core Research"
    assert ctx.status == "In Progress"

    with pytest.raises(Exception):  # FrozenInstanceError
        ctx.title = "Mutated Title"  # type: ignore[misc]


def test_project_access_denied_error_properties():
    """Verify ProjectAccessDeniedError retains target project and caller UUIDs."""
    err = ProjectAccessDeniedError(project_id=PROJECT_A_ID, user_id=USER_B_ID)
    assert err.project_id == PROJECT_A_ID
    assert err.user_id == USER_B_ID
    assert err.error_code == "ACCESS_DENIED"
    assert "Access denied" in str(err)


def test_resource_mismatch_error_properties():
    """Verify ResourceMismatchError retains resource classification and project mismatch."""
    err = ResourceMismatchError(
        resource_type="source",
        resource_id=SOURCE_A_ID,
        project_id=PROJECT_B_ID,
        actual_project_id=PROJECT_A_ID,
    )
    assert err.resource_type == "source"
    assert err.resource_id == str(SOURCE_A_ID)
    assert err.project_id == PROJECT_B_ID
    assert err.actual_project_id == PROJECT_A_ID
    assert err.error_code == "RESOURCE_MISMATCH"
    assert "does not belong" in str(err)


# =============================================================================
# Group 2: verify_project_ownership Core Function Tests
# =============================================================================

@pytest.mark.asyncio
async def test_verify_project_ownership_success_when_owner_matches():
    """Verify caller who owns the project receives valid OwnedProjectContext."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": PROJECT_A_ID,
        "user_id": USER_A_ID,
        "title": "Quantum Error Correction Survey",
        "status": "In Progress",
    }

    ctx = await verify_project_ownership(mock_conn, PROJECT_A_ID, USER_A_ID)

    assert isinstance(ctx, OwnedProjectContext)
    assert ctx.id == PROJECT_A_ID
    assert ctx.user_id == USER_A_ID
    assert ctx.title == "Quantum Error Correction Survey"
    assert ctx.status == "In Progress"
    mock_conn.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_verify_project_ownership_rejects_foreign_owner():
    """Verify user B attempting to access user A's project raises ProjectAccessDeniedError."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": PROJECT_A_ID,
        "user_id": USER_A_ID,  # Belongs to User A
        "title": "User A Private Research",
        "status": "Draft",
    }

    with pytest.raises(ProjectAccessDeniedError) as exc_info:
        await verify_project_ownership(mock_conn, PROJECT_A_ID, USER_B_ID)

    assert exc_info.value.project_id == PROJECT_A_ID
    assert exc_info.value.user_id == USER_B_ID


@pytest.mark.asyncio
async def test_verify_project_ownership_rejects_unowned_null_owner_project():
    """Verify ownerless project (user_id IS NULL) raises ProjectAccessDeniedError for any user."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": PROJECT_A_ID,
        "user_id": None,  # Ownerless project
        "title": "Legacy Project Without Owner",
        "status": "Draft",
    }

    with pytest.raises(ProjectAccessDeniedError) as exc_info:
        await verify_project_ownership(mock_conn, PROJECT_A_ID, USER_A_ID)

    assert exc_info.value.project_id == PROJECT_A_ID
    assert "unowned" in str(exc_info.value)


@pytest.mark.asyncio
async def test_verify_project_ownership_rejects_nonexistent_project():
    """Verify query returning None raises ProjectNotFoundError."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None

    with pytest.raises(ProjectNotFoundError) as exc_info:
        await verify_project_ownership(mock_conn, PROJECT_A_ID, USER_A_ID)

    assert str(PROJECT_A_ID) in str(exc_info.value)


@pytest.mark.asyncio
async def test_verify_project_ownership_excludes_soft_deleted_project():
    """Verify query filters out deleted_at IS NOT NULL at SQL level."""
    mock_conn = AsyncMock()
    # SQL query includes `WHERE id = $1 AND deleted_at IS NULL`
    mock_conn.fetchrow.return_value = None

    with pytest.raises(ProjectNotFoundError):
        await verify_project_ownership(mock_conn, PROJECT_A_ID, USER_A_ID)


@pytest.mark.asyncio
async def test_verify_project_ownership_rejects_non_uuid_identities():
    """Verify runtime validation rejects non-UUID user_id or project_id with TypeError."""
    mock_conn = AsyncMock()

    with pytest.raises(TypeError) as exc_user:
        await verify_project_ownership(mock_conn, PROJECT_A_ID, "not-a-uuid")  # type: ignore[arg-type]
    assert "user_id must be a UUID instance" in str(exc_user.value)

    with pytest.raises(TypeError) as exc_proj:
        await verify_project_ownership(mock_conn, "not-a-uuid", USER_A_ID)  # type: ignore[arg-type]
    assert "project_id must be a UUID instance" in str(exc_proj.value)


# =============================================================================
# Group 3: Child Resource Relationship Validation Tests
# =============================================================================

@pytest.mark.asyncio
async def test_verify_source_belongs_to_project_success():
    """Verify source linked to matching project_id returns record when caller is verified owner."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = [
        # 1. Project ownership check
        {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "Project A", "status": "In Progress"},
        # 2. Source check
        {
            "id": SOURCE_A_ID,
            "project_id": PROJECT_A_ID,
            "title": "Study on Greenland Ice Cap",
            "source_type": "url",
            "original_url": "https://example.com/greenland",
            "original_filename": None,
            "ingestion_status": "completed",
        },
    ]

    res = await verify_source_belongs_to_project(mock_conn, PROJECT_A_ID, SOURCE_A_ID, user_id=USER_A_ID)
    assert res["id"] == SOURCE_A_ID
    assert res["project_id"] == PROJECT_A_ID


@pytest.mark.asyncio
async def test_verify_source_belongs_to_project_accepts_verified_context():
    """Verify source check accepts pre-verified OwnedProjectContext without extra DB query."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": SOURCE_A_ID,
        "project_id": PROJECT_A_ID,
        "title": "Study on Greenland Ice Cap",
        "source_type": "url",
        "original_url": "https://example.com/greenland",
        "original_filename": None,
        "ingestion_status": "completed",
    }

    ctx = OwnedProjectContext(id=PROJECT_A_ID, user_id=USER_A_ID, title="Project A")
    res = await verify_source_belongs_to_project(mock_conn, PROJECT_A_ID, SOURCE_A_ID, user_id=ctx)
    assert res["id"] == SOURCE_A_ID
    assert res["project_id"] == PROJECT_A_ID
    # Only 1 query executed (source check), no redundant project query
    mock_conn.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_verify_source_belongs_to_project_rejects_mismatched_context():
    """Verify source check rejects OwnedProjectContext representing a different project."""
    mock_conn = AsyncMock()
    ctx = OwnedProjectContext(id=PROJECT_B_ID, user_id=USER_A_ID, title="Project B")

    with pytest.raises(ResourceMismatchError) as exc_info:
        await verify_source_belongs_to_project(mock_conn, PROJECT_A_ID, SOURCE_A_ID, user_id=ctx)

    assert "does not match target project" in str(exc_info.value)
    mock_conn.fetchrow.assert_not_called()


@pytest.mark.asyncio
async def test_verify_source_belongs_to_project_rejects_missing_identity():
    """Verify child helper rejects None or invalid identity with TypeError."""
    mock_conn = AsyncMock()

    with pytest.raises(TypeError) as exc_info:
        await verify_source_belongs_to_project(mock_conn, PROJECT_A_ID, SOURCE_A_ID, user_id=None)  # type: ignore[arg-type]

    assert "user_id must be a valid UUID or OwnedProjectContext" in str(exc_info.value)
    mock_conn.fetchrow.assert_not_called()


@pytest.mark.asyncio
async def test_verify_source_belongs_to_project_rejects_mismatched_project():
    """Verify source belonging to project A is rejected when project B is supplied."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = [
        # 1. Project B ownership check
        {"id": PROJECT_B_ID, "user_id": USER_A_ID, "title": "Project B", "status": "In Progress"},
        # 2. Source check (source belongs to Project A)
        {
            "id": SOURCE_A_ID,
            "project_id": PROJECT_A_ID,
            "title": "Study on Greenland Ice Cap",
            "source_type": "url",
            "original_url": "https://example.com/greenland",
            "original_filename": None,
            "ingestion_status": "completed",
        },
    ]

    with pytest.raises(ResourceMismatchError) as exc_info:
        await verify_source_belongs_to_project(mock_conn, PROJECT_B_ID, SOURCE_A_ID, user_id=USER_A_ID)

    assert exc_info.value.resource_type == "source"
    assert exc_info.value.project_id == PROJECT_B_ID
    assert exc_info.value.actual_project_id == PROJECT_A_ID


@pytest.mark.asyncio
async def test_verify_source_belongs_to_project_rejects_missing_source():
    """Verify nonexistent source raises ResourceMismatchError."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = [
        # 1. Project ownership check
        {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "Project A", "status": "In Progress"},
        # 2. Source check (not found)
        None,
    ]

    with pytest.raises(ResourceMismatchError) as exc_info:
        await verify_source_belongs_to_project(mock_conn, PROJECT_A_ID, SOURCE_A_ID, user_id=USER_A_ID)

    assert "was not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_verify_evidence_belongs_to_project_success():
    """Verify evidence linked to matching project_id returns record."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = [
        # 1. Project ownership check
        {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "Project A", "status": "In Progress"},
        # 2. Evidence check
        {
            "id": EVIDENCE_A_ID,
            "project_id": PROJECT_A_ID,
            "source_id": SOURCE_A_ID,
            "extraction_run_id": RUN_A_ID,
            "claim": "Ice loss accelerated by 15% between 2020 and 2025.",
            "fact_type": "statistical",
            "representation_type": "direct_quote",
        },
    ]

    res = await verify_evidence_belongs_to_project(mock_conn, PROJECT_A_ID, EVIDENCE_A_ID, user_id=USER_A_ID)
    assert res["id"] == EVIDENCE_A_ID
    assert res["project_id"] == PROJECT_A_ID


@pytest.mark.asyncio
async def test_verify_evidence_belongs_to_project_rejects_mismatch():
    """Verify evidence belonging to Project A is rejected when Project B is queried."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = [
        # 1. Project B ownership check
        {"id": PROJECT_B_ID, "user_id": USER_A_ID, "title": "Project B", "status": "In Progress"},
        # 2. Evidence check
        {
            "id": EVIDENCE_A_ID,
            "project_id": PROJECT_A_ID,
            "source_id": SOURCE_A_ID,
            "extraction_run_id": RUN_A_ID,
            "claim": "Mismatched claim",
            "fact_type": "general",
            "representation_type": "paraphrase",
        },
    ]

    with pytest.raises(ResourceMismatchError) as exc_info:
        await verify_evidence_belongs_to_project(mock_conn, PROJECT_B_ID, EVIDENCE_A_ID, user_id=USER_A_ID)

    assert exc_info.value.resource_type == "evidence"


@pytest.mark.asyncio
async def test_verify_extraction_run_belongs_to_project_success_and_mismatch():
    """Verify extraction run validation for matching and mismatched projects."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = [
        # 1. Project A ownership check
        {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "Project A", "status": "In Progress"},
        # 2. Extraction run check
        {
            "id": RUN_A_ID,
            "project_id": PROJECT_A_ID,
            "source_id": SOURCE_A_ID,
            "provider": "openrouter",
            "model_name": "nvidia/nemotron-3-ultra-550b-a55b:free",
            "extraction_status": "success",
        },
    ]

    # Match succeeds
    res = await verify_extraction_run_belongs_to_project(mock_conn, PROJECT_A_ID, RUN_A_ID, user_id=USER_A_ID)
    assert res["id"] == RUN_A_ID

    # Mismatch raises ResourceMismatchError
    mock_conn.fetchrow.side_effect = [
        {"id": PROJECT_B_ID, "user_id": USER_A_ID, "title": "Project B", "status": "In Progress"},
        {
            "id": RUN_A_ID,
            "project_id": PROJECT_A_ID,
            "source_id": SOURCE_A_ID,
            "provider": "openrouter",
            "model_name": "nvidia/nemotron-3-ultra-550b-a55b:free",
            "extraction_status": "success",
        },
    ]
    with pytest.raises(ResourceMismatchError):
        await verify_extraction_run_belongs_to_project(mock_conn, PROJECT_B_ID, RUN_A_ID, user_id=USER_A_ID)


@pytest.mark.asyncio
async def test_verify_source_claim_belongs_to_project_success_and_mismatch():
    """Verify source claim validation for matching and mismatched projects."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = [
        # 1. Project A ownership check
        {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "Project A", "status": "In Progress"},
        # 2. Source claim check
        {
            "id": CLAIM_A_ID,
            "project_id": PROJECT_A_ID,
            "source_id": SOURCE_A_ID,
            "extraction_run_id": RUN_A_ID,
            "claim_id": "claim-001",
            "claim_type": "factual_assertion",
        },
    ]

    # Match succeeds
    res = await verify_source_claim_belongs_to_project(mock_conn, PROJECT_A_ID, CLAIM_A_ID, user_id=USER_A_ID)
    assert res["id"] == CLAIM_A_ID

    # Mismatch raises ResourceMismatchError
    mock_conn.fetchrow.side_effect = [
        {"id": PROJECT_B_ID, "user_id": USER_A_ID, "title": "Project B", "status": "In Progress"},
        {
            "id": CLAIM_A_ID,
            "project_id": PROJECT_A_ID,
            "source_id": SOURCE_A_ID,
            "extraction_run_id": RUN_A_ID,
            "claim_id": "claim-001",
            "claim_type": "factual_assertion",
        },
    ]
    with pytest.raises(ResourceMismatchError):
        await verify_source_claim_belongs_to_project(mock_conn, PROJECT_B_ID, CLAIM_A_ID, user_id=USER_A_ID)


# =============================================================================
# Group 4: get_owned_project FastAPI Dependency Tests
# =============================================================================

@pytest.mark.asyncio
async def test_get_owned_project_dependency_authorized_user():
    """Verify dependency returns OwnedProjectContext when caller owns project."""
    mock_db = MagicMock(spec=DatabaseManager)
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": PROJECT_A_ID,
        "user_id": USER_A_ID,
        "title": "Clean Energy Grid Roadmap",
        "status": "In Progress",
    }
    mock_db.acquire_connection.return_value.__aenter__.return_value = mock_conn

    current_user = AuthenticatedUser(id=USER_A_ID, role="authenticated")

    ctx = await get_owned_project(
        project_id=PROJECT_A_ID,
        current_user=current_user,
        db_manager=mock_db,
    )
    assert ctx.id == PROJECT_A_ID
    assert ctx.user_id == USER_A_ID


@pytest.mark.asyncio
async def test_get_owned_project_dependency_masks_foreign_project_as_404():
    """Verify unauthorized project access returns generic 404 (IDOR information disclosure protection)."""
    mock_db = MagicMock(spec=DatabaseManager)
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": PROJECT_A_ID,
        "user_id": USER_A_ID,  # Owned by User A
        "title": "User A Sensitive Project",
        "status": "Draft",
    }
    mock_db.acquire_connection.return_value.__aenter__.return_value = mock_conn

    # User B attempts to access User A's project
    user_b = AuthenticatedUser(id=USER_B_ID, role="authenticated")

    with pytest.raises(HTTPException) as exc_info:
        await get_owned_project(
            project_id=PROJECT_A_ID,
            current_user=user_b,
            db_manager=mock_db,
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert f"Research project '{PROJECT_A_ID}' was not found." == exc_info.value.detail


@pytest.mark.asyncio
async def test_get_owned_project_dependency_masks_ownerless_project_as_404():
    """Verify ownerless project (user_id IS NULL) returns generic 404 with identical detail."""
    mock_db = MagicMock(spec=DatabaseManager)
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": PROJECT_A_ID,
        "user_id": None,  # Ownerless
        "title": "Unowned Project",
        "status": "Draft",
    }
    mock_db.acquire_connection.return_value.__aenter__.return_value = mock_conn

    user_a = AuthenticatedUser(id=USER_A_ID, role="authenticated")

    with pytest.raises(HTTPException) as exc_info:
        await get_owned_project(
            project_id=PROJECT_A_ID,
            current_user=user_a,
            db_manager=mock_db,
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert f"Research project '{PROJECT_A_ID}' was not found." == exc_info.value.detail


@pytest.mark.asyncio
async def test_get_owned_project_dependency_nonexistent_returns_404():
    """Verify nonexistent project returns generic 404 identical to unauthorized project."""
    mock_db = MagicMock(spec=DatabaseManager)
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None
    mock_db.acquire_connection.return_value.__aenter__.return_value = mock_conn

    user_a = AuthenticatedUser(id=USER_A_ID, role="authenticated")

    with pytest.raises(HTTPException) as exc_info:
        await get_owned_project(
            project_id=PROJECT_A_ID,
            current_user=user_a,
            db_manager=mock_db,
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert f"Research project '{PROJECT_A_ID}' was not found." == exc_info.value.detail


# =============================================================================
# Group 5: Service-Layer Ownership Enforcement Tests
# =============================================================================

@pytest.mark.asyncio
async def test_web_source_service_ownership_enforcement():
    """Verify WebSourceIngestionService rejects foreign user_id with ProjectNotFoundError."""
    mock_db = MagicMock(spec=DatabaseManager)
    service = WebSourceIngestionService(db_manager=mock_db)

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": PROJECT_A_ID,
        "user_id": USER_A_ID,
        "title": "Project A",
        "status": "Draft",
    }

    # Caller User A succeeds
    res_a = await service.validate_project_exists(mock_conn, PROJECT_A_ID, user_id=USER_A_ID)
    assert res_a["id"] == PROJECT_A_ID

    # Caller User B rejected with ProjectNotFoundError
    with pytest.raises(ProjectNotFoundError) as exc_info:
        await service.validate_project_exists(mock_conn, PROJECT_A_ID, user_id=USER_B_ID)

    assert str(PROJECT_A_ID) in str(exc_info.value)


@pytest.mark.asyncio
async def test_pdf_source_service_ownership_enforcement():
    """Verify PDFSourceIngestionService rejects foreign user_id with ProjectNotFoundError."""
    mock_db = MagicMock(spec=DatabaseManager)
    service = PDFSourceIngestionService(db_manager=mock_db)

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": PROJECT_A_ID,
        "user_id": USER_A_ID,
        "title": "Project A",
        "status": "Draft",
    }

    # Caller User A succeeds
    res_a = await service.validate_project_exists(mock_conn, PROJECT_A_ID, user_id=USER_A_ID)
    assert res_a["id"] == PROJECT_A_ID

    # Caller User B rejected with ProjectNotFoundError
    with pytest.raises(ProjectNotFoundError):
        await service.validate_project_exists(mock_conn, PROJECT_A_ID, user_id=USER_B_ID)


@pytest.mark.asyncio
async def test_services_reject_missing_or_invalid_user_id():
    """Verify all service methods reject None or non-UUID user_id with TypeError."""
    mock_db = MagicMock(spec=DatabaseManager)
    web_service = WebSourceIngestionService(db_manager=mock_db)
    pdf_service = PDFSourceIngestionService(db_manager=mock_db)
    evidence_service = EvidencePersistenceService(db_manager=mock_db)

    mock_conn = AsyncMock()

    # Web service rejects None and invalid type
    with pytest.raises(TypeError) as exc:
        await web_service.validate_project_exists(mock_conn, PROJECT_A_ID, user_id=None)  # type: ignore[arg-type]
    assert "user_id must be a UUID instance" in str(exc.value)

    with pytest.raises(TypeError) as exc:
        await web_service.validate_project_exists(mock_conn, PROJECT_A_ID, user_id="bad-uuid")  # type: ignore[arg-type]
    assert "user_id must be a UUID instance" in str(exc.value)

    # PDF service rejects None and invalid type
    with pytest.raises(TypeError) as exc:
        await pdf_service.validate_project_exists(mock_conn, PROJECT_A_ID, user_id=None)  # type: ignore[arg-type]
    assert "user_id must be a UUID instance" in str(exc.value)

    # Evidence service rejects None and invalid type
    with pytest.raises(TypeError) as exc:
        await evidence_service.validate_project_and_source(
            mock_conn, PROJECT_A_ID, SOURCE_A_ID, user_id=None  # type: ignore[arg-type]
        )
    assert "user_id must be a UUID instance" in str(exc.value)

    with pytest.raises(TypeError) as exc:
        await evidence_service.get_project_evidence(PROJECT_A_ID, user_id=None)  # type: ignore[arg-type]
    assert "user_id must be a UUID instance" in str(exc.value)

    with pytest.raises(TypeError) as exc:
        await evidence_service.list_extraction_runs(PROJECT_A_ID, user_id="bad-id")  # type: ignore[arg-type]
    assert "user_id must be a UUID instance" in str(exc.value)

    with pytest.raises(TypeError) as exc:
        await evidence_service.get_extraction_run_detail(PROJECT_A_ID, RUN_A_ID, user_id=None)  # type: ignore[arg-type]
    assert "user_id must be a UUID instance" in str(exc.value)


@pytest.mark.asyncio
async def test_evidence_persistence_service_ownership_enforcement():
    """Verify EvidencePersistenceService validates ownership and source linkage."""
    mock_db = MagicMock(spec=DatabaseManager)
    service = EvidencePersistenceService(db_manager=mock_db)

    mock_conn = AsyncMock()
    # First call: project lookup; Second call: source lookup
    mock_conn.fetchrow.side_effect = [
        {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "Project A", "status": "Draft"},
        {"id": SOURCE_A_ID, "project_id": PROJECT_A_ID, "title": "Source A", "source_type": "url", "original_url": "https://example.com"},
    ]

    p_data, s_data = await service.validate_project_and_source(
        conn=mock_conn,
        project_id=PROJECT_A_ID,
        source_id=SOURCE_A_ID,
        user_id=USER_A_ID,
    )
    assert p_data["id"] == PROJECT_A_ID
    assert s_data["id"] == SOURCE_A_ID

    # When User B calls validate_project_and_source:
    mock_conn.fetchrow.side_effect = [
        {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "Project A", "status": "Draft"},
    ]
    with pytest.raises(ProjectNotFoundError):
        await service.validate_project_and_source(
            conn=mock_conn,
            project_id=PROJECT_A_ID,
            source_id=SOURCE_A_ID,
            user_id=USER_B_ID,
        )

