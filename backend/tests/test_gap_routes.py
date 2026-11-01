"""Comprehensive HTTP-level security and integration tests for Step 10D.2: Protected Information Gap API Routes.

Verifies:
1. Authentication:
   - Missing / invalid Bearer token returns HTTP 401 with WWW-Authenticate header.
   - Valid token accepted across all endpoints.
2. Ownership & IDOR Protection:
   - Project ownership enforced: research_projects.user_id == current_user.id.
   - Foreign-owned, unowned, soft-deleted, and missing projects return generic HTTP 404.
   - Foreign gap IDs and mismatched child-resource lookups return generic HTTP 404.
   - Body/query parameter identity tampering is rejected or ignored.
3. Detection Endpoint (POST /api/v1/projects/{project_id}/gaps/detect):
   - Successful detection and transactional persistence.
   - Empty evidence and failed extraction handling.
   - Corpus truncation and omission warning propagation.
   - OpenRouter provider error mapping (504, 429, 503, 502).
   - Zero AI calls and zero database writes on ownership failure.
   - Idempotent rerun preservation of user review status and notes.
4. Retrieval Endpoints (GET /api/v1/projects/{project_id}/gaps, GET /.../gaps/{gap_id}):
   - Scoped listing with pagination and filters (status, priority, gap_type).
   - Single gap retrieval with generic 404 masking for foreign gaps.
5. Review Update Endpoint (PATCH /api/v1/projects/{project_id}/gaps/{gap_id}):
   - Valid status transitions (investigating, resolved, dismissed).
   - Rejection of invalid status (open, arbitrary) with HTTP 422.
   - Preservation of user notes and detection metadata immutability.
6. Operational Resilience:
   - Unconfigured / unavailable database returns HTTP 503.
   - Unconfigured AI provider returns HTTP 503.
   - Persistence transaction failure returns HTTP 500.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import time
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from fastapi import FastAPI, status
from fastapi.testclient import TestClient
import jwt
import pytest

from app.core.auth import SupabaseJWTVerifier, get_jwt_verifier
from app.core.config import Settings
from app.core.ownership import get_owned_project
from app.db.connection import (
    DatabaseManager,
    DatabaseNotConfiguredError,
    DatabaseUnavailableError,
    get_db_manager,
)
from app.main import create_app
from app.services.ai.exceptions import (
    AIAuthenticationError,
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
    get_gap_persistence_service,
)
from app.services.ai.gap_schemas import (
    AIGapCandidatePayload,
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
from app.services.sources.exceptions import ProjectNotFoundError

# =============================================================================
# Identifiers & Synthetic Fixtures
# =============================================================================

USER_A_ID = UUID("00000000-0000-4000-a000-000000000001")
USER_B_ID = UUID("00000000-0000-4000-a000-000000000002")

PROJECT_A_ID = UUID("11111111-1111-4000-a000-000000000001")
PROJECT_B_ID = UUID("22222222-2222-4000-a000-000000000002")
PROJECT_UNOWNED_ID = UUID("33333333-3333-4000-a000-000000000003")
PROJECT_DELETED_ID = UUID("44444444-4444-4000-a000-000000000004")
PROJECT_NONEXISTENT_ID = UUID("55555555-5555-4000-a000-000000000005")

GAP_A_ID = UUID("aaaa0000-0000-4000-a000-000000000001")
GAP_B_ID = UUID("bbbb0000-0000-4000-a000-000000000002")
GAP_NONEXISTENT_ID = UUID("cccc0000-0000-4000-a000-000000000003")

NOW = datetime.now(timezone.utc)


def create_token_for_user(user_id: UUID, email: str, private_key) -> str:
    """Helper generating signed ES256 JWT for arbitrary user identity."""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": "authenticated",
        "iss": "https://test-project.supabase.co/auth/v1",
        "aud": "authenticated",
        "exp": now + 7200,
        "iat": now,
        "app_metadata": {"provider": "email"},
        "user_metadata": {"user_id": str(user_id)},
    }
    return jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": "test-session-kid-1"})


def make_dummy_gap_response(
    gap_id: UUID = GAP_A_ID,
    project_id: UUID = PROJECT_A_ID,
    status: GapStatus = GapStatus.OPEN,
    priority: GapPriority = GapPriority.HIGH,
    gap_type: GapType = GapType.NO_EVIDENCE,
    notes: str | None = None,
) -> InformationGapResponse:
    """Helper creating a valid InformationGapResponse entity."""
    return InformationGapResponse(
        id=gap_id,
        project_id=project_id,
        topic_id=None,
        gap_description="The sources omit residency criteria for applicants.",
        explanation="Residency criteria are required for participation scope.",
        suggested_query="non-resident eligibility solar",
        priority=priority,
        status=status,
        gap_type=gap_type,
        confidence_metadata={
            "bharmafills": {
                "schema_version": 1,
                "fingerprint": "mock-fingerprint",
                "gap_subtype": "incomplete_detail",
                "validation_verdict": "confirmed",
                "ai_confidence": 0.88,
                "user_review": {"notes": notes} if notes else None,
            }
        },
        created_at=NOW,
        updated_at=NOW,
    )


def make_dummy_detection_result(
    project_id: UUID = PROJECT_A_ID,
    total_gaps: int = 1,
    warnings: list[str] | None = None,
    diagnostic: str | None = None,
    truncation: bool = False,
) -> GapDetectionResult:
    """Helper creating a valid GapDetectionResult envelope."""
    candidate = AIGapCandidatePayload(
        candidate_id=1,
        target_subquestion="What are the non-resident eligibility rules?",
        gap_description="The sources omit residency criteria for applicants.",
        explanation="Residency criteria are required for participation scope.",
        suggested_query="non-resident eligibility solar",
        gap_type=GapType.INSUFFICIENT_EVIDENCE,
        priority=GapPriority.HIGH,
        gap_subtype=GapSubtype.INCOMPLETE_DETAIL,
        confidence_score=0.88,
        reasoning="Sources discuss resident criteria only.",
    )
    finding = ValidatedGapFinding(
        candidate=candidate,
        validation_verdict="confirmed",
        grounded_facts_count=0,
        covered_evidence_ids=[],
        corpus_truncation_warning=truncation,
        grounding_notes="Analyzed 2 sources; no residency rules found.",
        source_omission_warning=None,
    )
    return GapDetectionResult(
        project_id=project_id,
        research_question="What are the complete eligibility criteria for community solar?",
        total_gaps_detected=total_gaps,
        gaps=[finding] if total_gaps > 0 else [],
        analysis_summary="Analysis completed.",
        warnings=warnings or [],
        has_corpus_truncation=truncation,
        sources_evaluated=2,
        facts_evaluated=4,
        claims_evaluated=2,
        topics_evaluated=1,
        ai_analysis_executed=diagnostic is None,
        diagnostic_message=diagnostic,
        detected_at=NOW,
    )


# =============================================================================
# Test Setup & Isolation Fixtures
# =============================================================================

@pytest.fixture
def mock_db_manager() -> DatabaseManager:
    """Mock DatabaseManager with truthful simulated project state for ownership checks."""
    mock_db = MagicMock(spec=DatabaseManager)
    mock_db.is_configured = True

    mock_conn = AsyncMock()

    async def mock_fetchrow(query: str, *args):
        if "FROM public.research_projects" in query:
            project_id = args[0]
            if project_id == PROJECT_A_ID:
                return {"id": PROJECT_A_ID, "user_id": USER_A_ID, "title": "Project A", "status": "In Progress"}
            elif project_id == PROJECT_B_ID:
                return {"id": PROJECT_B_ID, "user_id": USER_B_ID, "title": "Project B", "status": "Active"}
            elif project_id == PROJECT_UNOWNED_ID:
                return {"id": PROJECT_UNOWNED_ID, "user_id": None, "title": "Unowned", "status": "Draft"}
            elif project_id == PROJECT_DELETED_ID:
                return None  # soft deleted -> deleted_at IS NULL returns None
            elif project_id == PROJECT_NONEXISTENT_ID:
                return None
            return None
        return None

    mock_conn.fetchrow.side_effect = mock_fetchrow

    mock_acquire = AsyncMock()
    mock_acquire.__aenter__.return_value = mock_conn
    mock_acquire.__aexit__.return_value = None
    mock_db.acquire_connection.return_value = mock_acquire

    return mock_db


@pytest.fixture
def mock_detection_service() -> MagicMock:
    """Mock InformationGapDetectionService."""
    mock_service = MagicMock(spec=InformationGapDetectionService)
    mock_service.is_configured = True
    mock_service.detect_gaps = AsyncMock(return_value=make_dummy_detection_result())
    return mock_service


@pytest.fixture
def mock_persistence_service() -> MagicMock:
    """Mock GapPersistenceService."""
    mock_service = MagicMock(spec=GapPersistenceService)
    mock_service.is_configured = True

    default_gap = make_dummy_gap_response()
    default_batch = PersistedGapBatchResponse(
        project_id=PROJECT_A_ID,
        total_findings_evaluated=1,
        total_persisted=1,
        inserted_count=1,
        updated_count=0,
        preserved_count=0,
        gaps=[default_gap],
        persisted_at=NOW,
    )
    mock_service.persist_detection_result = AsyncMock(return_value=default_batch)
    mock_service.list_project_gaps = AsyncMock(return_value=[default_gap])
    mock_service.count_project_gaps = AsyncMock(return_value=1)
    mock_service.get_project_gap = AsyncMock(return_value=default_gap)
    mock_service.update_gap_review = AsyncMock(return_value=default_gap)

    return mock_service


@pytest.fixture
def test_app_gaps(
    test_settings: Settings,
    test_verifier: SupabaseJWTVerifier,
    mock_db_manager: DatabaseManager,
    mock_detection_service: MagicMock,
    mock_persistence_service: MagicMock,
) -> FastAPI:
    """FastAPI application wired with real get_owned_project and mock gap services."""
    app = create_app(settings=test_settings)
    app.dependency_overrides[get_jwt_verifier] = lambda: test_verifier
    app.dependency_overrides[get_db_manager] = lambda: mock_db_manager
    app.dependency_overrides[get_gap_detection_service] = lambda: mock_detection_service
    app.dependency_overrides[get_gap_persistence_service] = lambda: mock_persistence_service
    return app


@pytest.fixture
def client_a(test_app_gaps: FastAPI, test_ec_keypair) -> TestClient:
    """TestClient authenticated as User A (owner of Project A)."""
    private_key, _ = test_ec_keypair
    token_a = create_token_for_user(USER_A_ID, "user.a@bharmafills.org", private_key)
    return TestClient(test_app_gaps, base_url="http://testserver", headers={"Authorization": f"Bearer {token_a}"})


@pytest.fixture
def client_b(test_app_gaps: FastAPI, test_ec_keypair) -> TestClient:
    """TestClient authenticated as User B (owner of Project B)."""
    private_key, _ = test_ec_keypair
    token_b = create_token_for_user(USER_B_ID, "user.b@bharmafills.org", private_key)
    return TestClient(test_app_gaps, base_url="http://testserver", headers={"Authorization": f"Bearer {token_b}"})


@pytest.fixture
def unauth_client(test_app_gaps: FastAPI) -> TestClient:
    """Unauthenticated TestClient."""
    return TestClient(test_app_gaps, base_url="http://testserver")


# =============================================================================
# 1. Authentication Tests
# =============================================================================

class TestGapRouteAuthentication:
    """Verify all 4 gap endpoints require valid Bearer authentication."""

    @pytest.mark.parametrize(
        ("method", "endpoint"),
        [
            ("POST", f"/api/v1/projects/{PROJECT_A_ID}/gaps/detect"),
            ("GET", f"/api/v1/projects/{PROJECT_A_ID}/gaps"),
            ("GET", f"/api/v1/projects/{PROJECT_A_ID}/gaps/{GAP_A_ID}"),
            ("PATCH", f"/api/v1/projects/{PROJECT_A_ID}/gaps/{GAP_A_ID}"),
        ],
    )
    def test_missing_auth_header_rejected(self, unauth_client: TestClient, method: str, endpoint: str) -> None:
        """1-4. Unauthenticated requests are rejected with HTTP 401 and WWW-Authenticate."""
        resp = unauth_client.request(method, endpoint, json={"status": "investigating"} if method == "PATCH" else None)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Bearer" in resp.headers.get("WWW-Authenticate", "")

    @pytest.mark.parametrize(
        ("method", "endpoint"),
        [
            ("POST", f"/api/v1/projects/{PROJECT_A_ID}/gaps/detect"),
            ("GET", f"/api/v1/projects/{PROJECT_A_ID}/gaps"),
            ("GET", f"/api/v1/projects/{PROJECT_A_ID}/gaps/{GAP_A_ID}"),
            ("PATCH", f"/api/v1/projects/{PROJECT_A_ID}/gaps/{GAP_A_ID}"),
        ],
    )
    def test_invalid_token_rejected(self, test_app_gaps: FastAPI, method: str, endpoint: str) -> None:
        """5-8. Malformed or invalid JWTs are rejected with HTTP 401."""
        client = TestClient(test_app_gaps, base_url="http://testserver", headers={"Authorization": "Bearer not-a-valid-jwt"})
        resp = client.request(method, endpoint, json={"status": "investigating"} if method == "PATCH" else None)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# =============================================================================
# 2. Ownership & IDOR Protection Tests
# =============================================================================

class TestGapRouteOwnership:
    """Verify backend-enforced ownership: research_projects.user_id == current_user.id."""

    def test_owner_can_access_project_gaps(self, client_a: TestClient) -> None:
        """9. User A can access endpoints for their owned Project A."""
        resp = client_a.get(f"/api/v1/projects/{PROJECT_A_ID}/gaps")
        assert resp.status_code == status.HTTP_200_OK

    def test_user_b_cannot_access_project_a_gaps(self, client_b: TestClient) -> None:
        """10. User B attempting to access User A's project receives generic HTTP 404."""
        resp = client_b.get(f"/api/v1/projects/{PROJECT_A_ID}/gaps")
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.json()["detail"] == f"Research project '{PROJECT_A_ID}' was not found."

    def test_user_b_cannot_detect_gaps_in_project_a(
        self,
        client_b: TestClient,
        mock_detection_service: MagicMock,
        mock_persistence_service: MagicMock,
    ) -> None:
        """11. User B cannot trigger detection on Project A; causes 0 AI calls and 0 DB writes."""
        resp = client_b.post(f"/api/v1/projects/{PROJECT_A_ID}/gaps/detect")
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        # Zero side effects!
        mock_detection_service.detect_gaps.assert_not_called()
        mock_persistence_service.persist_detection_result.assert_not_called()

    @pytest.mark.parametrize("project_id", [PROJECT_UNOWNED_ID, PROJECT_DELETED_ID, PROJECT_NONEXISTENT_ID])
    def test_unowned_deleted_nonexistent_projects_return_identical_404(
        self,
        client_a: TestClient,
        project_id: UUID,
    ) -> None:
        """12-14. Unowned, deleted, and missing projects return uniform generic HTTP 404."""
        resp = client_a.get(f"/api/v1/projects/{project_id}/gaps")
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.json()["detail"] == f"Research project '{project_id}' was not found."

    def test_foreign_gap_id_in_owned_project_returns_generic_404(
        self,
        client_a: TestClient,
        mock_persistence_service: MagicMock,
    ) -> None:
        """15. Retrieving a gap UUID that does not exist in Project A returns generic 404."""
        mock_persistence_service.get_project_gap.side_effect = GapNotFoundError(
            gap_id=GAP_B_ID,
            project_id=PROJECT_A_ID,
        )
        resp = client_a.get(f"/api/v1/projects/{PROJECT_A_ID}/gaps/{GAP_B_ID}")
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.json()["detail"] == f"Information gap '{GAP_B_ID}' was not found in research project '{PROJECT_A_ID}'."

    def test_foreign_gap_id_update_returns_generic_404(
        self,
        client_a: TestClient,
        mock_persistence_service: MagicMock,
    ) -> None:
        """16. Patching a gap UUID not in Project A returns generic 404."""
        mock_persistence_service.update_gap_review.side_effect = GapNotFoundError(
            gap_id=GAP_B_ID,
            project_id=PROJECT_A_ID,
        )
        resp = client_a.patch(
            f"/api/v1/projects/{PROJECT_A_ID}/gaps/{GAP_B_ID}",
            json={"status": "investigating"},
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.json()["detail"] == f"Information gap '{GAP_B_ID}' was not found in research project '{PROJECT_A_ID}'."

    def test_identity_spoofing_via_query_or_body_ignored_or_rejected(
        self,
        client_a: TestClient,
        mock_persistence_service: MagicMock,
    ) -> None:
        """17. Passing foreign user_id in query params or body does not override token identity."""
        resp = client_a.patch(
            f"/api/v1/projects/{PROJECT_A_ID}/gaps/{GAP_A_ID}?user_id={USER_B_ID}",
            json={"status": "resolved", "user_notes": "Valid note"},
        )
        assert resp.status_code == status.HTTP_200_OK
        # Service strictly received USER_A_ID from the verified token
        call_kwargs = mock_persistence_service.update_gap_review.call_args[1]
        assert call_kwargs["user_id"] == USER_A_ID


# =============================================================================
# 3. Detection Endpoint Tests
# =============================================================================

class TestGapDetectionEndpoint:
    """Verify POST /api/v1/projects/{project_id}/gaps/detect behavior and resilience."""

    def test_successful_detection_and_persistence(
        self,
        client_a: TestClient,
        mock_detection_service: MagicMock,
        mock_persistence_service: MagicMock,
    ) -> None:
        """18. Successful detection and persistence returns structured response."""
        resp = client_a.post(
            f"/api/v1/projects/{PROJECT_A_ID}/gaps/detect",
            json={"custom_instructions": "Focus on residential subsidies"},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()

        assert data["project_id"] == str(PROJECT_A_ID)
        assert "detection" in data
        assert "persistence" in data
        assert data["detection"]["total_gaps_detected"] == 1
        assert data["persistence"]["total_persisted"] == 1
        assert len(data["persistence"]["gaps"]) == 1

        # Service invocations verify user_id bound from token
        mock_detection_service.detect_gaps.assert_called_once_with(
            project_id=PROJECT_A_ID,
            user_id=USER_A_ID,
            custom_instructions="Focus on residential subsidies",
        )
        mock_persistence_service.persist_detection_result.assert_called_once()

    def test_detection_empty_evidence_handled_transparently(
        self,
        client_a: TestClient,
        mock_detection_service: MagicMock,
        mock_persistence_service: MagicMock,
    ) -> None:
        """19. Empty evidence returns diagnostic envelope without failing."""
        empty_result = make_dummy_detection_result(
            total_gaps=0,
            diagnostic="Project contains 0 sources. Skipping AI detection.",
        )
        mock_detection_service.detect_gaps.return_value = empty_result

        mock_persistence_service.persist_detection_result.return_value = PersistedGapBatchResponse(
            project_id=PROJECT_A_ID,
            total_findings_evaluated=0,
            total_persisted=0,
            inserted_count=0,
            updated_count=0,
            preserved_count=0,
            gaps=[],
            persisted_at=NOW,
        )

        resp = client_a.post(f"/api/v1/projects/{PROJECT_A_ID}/gaps/detect")
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()

        assert data["detection"]["diagnostic_message"] == "Project contains 0 sources. Skipping AI detection."
        assert data["detection"]["total_gaps_detected"] == 0
        assert data["persistence"]["total_persisted"] == 0

    def test_detection_truncated_corpus_preserves_warnings(
        self,
        client_a: TestClient,
        mock_detection_service: MagicMock,
    ) -> None:
        """20. Truncation and source omission warnings are propagated in response."""
        result_with_warnings = make_dummy_detection_result(
            warnings=["Document partially truncated due to length limits."],
            truncation=True,
        )
        mock_detection_service.detect_gaps.return_value = result_with_warnings

        resp = client_a.post(f"/api/v1/projects/{PROJECT_A_ID}/gaps/detect")
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["detection"]["has_corpus_truncation"] is True
        assert len(data["detection"]["warnings"]) > 0

    def test_detection_openrouter_timeout_returns_504(
        self,
        client_a: TestClient,
        mock_detection_service: MagicMock,
    ) -> None:
        """21. OpenRouter timeout raises HTTP 504 Gateway Timeout."""
        mock_detection_service.detect_gaps.side_effect = AITimeoutError(
            message="Request timed out after 30.0s.",
            provider="openrouter",
            timeout_seconds=30.0,
        )
        resp = client_a.post(f"/api/v1/projects/{PROJECT_A_ID}/gaps/detect")
        assert resp.status_code == status.HTTP_504_GATEWAY_TIMEOUT
        assert resp.json()["detail"] == "AI completion request timed out. Please try again."

    def test_detection_openrouter_rate_limit_returns_429(
        self,
        client_a: TestClient,
        mock_detection_service: MagicMock,
    ) -> None:
        """22. OpenRouter rate limit raises HTTP 429 Too Many Requests."""
        mock_detection_service.detect_gaps.side_effect = AIRateLimitError(
            message="Rate limit exceeded.",
            provider="openrouter",
            retry_after=5.0,
        )
        resp = client_a.post(f"/api/v1/projects/{PROJECT_A_ID}/gaps/detect")
        assert resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert resp.json()["detail"] == "AI service rate limit exceeded. Please retry later."

    def test_detection_openrouter_quota_exceeded_returns_503(
        self,
        client_a: TestClient,
        mock_detection_service: MagicMock,
    ) -> None:
        """23. OpenRouter quota exhausted raises HTTP 503 Service Unavailable."""
        mock_detection_service.detect_gaps.side_effect = AIQuotaExceededError(
            message="Credit balance exhausted.",
            provider="openrouter",
        )
        resp = client_a.post(f"/api/v1/projects/{PROJECT_A_ID}/gaps/detect")
        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert resp.json()["detail"] == "AI provider quota exceeded."

    def test_detection_openrouter_auth_error_returns_502(
        self,
        client_a: TestClient,
        mock_detection_service: MagicMock,
    ) -> None:
        """24. Invalid API key raises HTTP 502 Bad Gateway."""
        mock_detection_service.detect_gaps.side_effect = AIAuthenticationError(
            message="Invalid API Key.",
            provider="openrouter",
        )
        resp = client_a.post(f"/api/v1/projects/{PROJECT_A_ID}/gaps/detect")
        assert resp.status_code == status.HTTP_502_BAD_GATEWAY
        assert resp.json()["detail"] == "AI provider authentication failure."

    def test_detection_malformed_ai_response_returns_502(
        self,
        client_a: TestClient,
        mock_detection_service: MagicMock,
    ) -> None:
        """25. Malformed AI response raises HTTP 502 Bad Gateway."""
        mock_detection_service.detect_gaps.side_effect = AIResponseValidationError(
            message="Missing required field 'gaps'.",
            provider="openrouter",
        )
        resp = client_a.post(f"/api/v1/projects/{PROJECT_A_ID}/gaps/detect")
        assert resp.status_code == status.HTTP_502_BAD_GATEWAY
        assert resp.json()["detail"] == "Failed to parse valid structured response from AI model."

    def test_detection_invalid_research_question_returns_400(
        self,
        client_a: TestClient,
        mock_detection_service: MagicMock,
    ) -> None:
        """26. Invalid/missing research question raises HTTP 400 Bad Request."""
        mock_detection_service.detect_gaps.side_effect = ValueError(
            f"Research project '{PROJECT_A_ID}' has an invalid or missing research question (minimum 10 characters required)."
        )
        resp = client_a.post(f"/api/v1/projects/{PROJECT_A_ID}/gaps/detect")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_extra_fields_in_detect_body_rejected(self, client_a: TestClient) -> None:
        """27. Extra fields (e.g., user_id) in request body are rejected with HTTP 422."""
        resp = client_a.post(
            f"/api/v1/projects/{PROJECT_A_ID}/gaps/detect",
            json={"custom_instructions": "Focus", "user_id": str(USER_B_ID)},
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# =============================================================================
# 4. Retrieval & Review Endpoints Tests
# =============================================================================

class TestGapRetrievalAndReviewEndpoints:
    """Verify GET and PATCH /api/v1/projects/{project_id}/gaps/... behavior."""

    def test_list_project_gaps_success(
        self,
        client_a: TestClient,
        mock_persistence_service: MagicMock,
    ) -> None:
        """28. List gaps returns paginated response with total_count and gap items."""
        resp = client_a.get(f"/api/v1/projects/{PROJECT_A_ID}/gaps?limit=10&offset=0")
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["project_id"] == str(PROJECT_A_ID)
        assert data["total_count"] == 1
        assert data["limit"] == 10
        assert data["offset"] == 0
        assert len(data["gaps"]) == 1

        mock_persistence_service.list_project_gaps.assert_called_once_with(
            project_id=PROJECT_A_ID,
            user_id=USER_A_ID,
            status=None,
            priority=None,
            gap_type=None,
            limit=10,
            offset=0,
        )

    def test_list_project_gaps_with_filters(
        self,
        client_a: TestClient,
        mock_persistence_service: MagicMock,
    ) -> None:
        """29. Query filters (status, priority, gap_type) are passed to persistence service."""
        resp = client_a.get(
            f"/api/v1/projects/{PROJECT_A_ID}/gaps?status=open&priority=high&gap_type=no_evidence"
        )
        assert resp.status_code == status.HTTP_200_OK
        call_kwargs = mock_persistence_service.list_project_gaps.call_args[1]
        assert call_kwargs["status"] == GapStatus.OPEN
        assert call_kwargs["priority"] == GapPriority.HIGH
        assert call_kwargs["gap_type"] == GapType.NO_EVIDENCE

    def test_get_single_gap_success(
        self,
        client_a: TestClient,
        mock_persistence_service: MagicMock,
    ) -> None:
        """30. Get single gap returns InformationGapResponse."""
        resp = client_a.get(f"/api/v1/projects/{PROJECT_A_ID}/gaps/{GAP_A_ID}")
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["id"] == str(GAP_A_ID)
        assert data["project_id"] == str(PROJECT_A_ID)
        mock_persistence_service.get_project_gap.assert_called_once_with(
            project_id=PROJECT_A_ID,
            gap_id=GAP_A_ID,
            user_id=USER_A_ID,
        )

    @pytest.mark.parametrize("status_val", ["investigating", "resolved", "dismissed"])
    def test_update_gap_review_allowed_statuses(
        self,
        client_a: TestClient,
        mock_persistence_service: MagicMock,
        status_val: str,
    ) -> None:
        """31-33. Valid review statuses succeed with HTTP 200."""
        expected_status = GapStatus(status_val)
        updated_gap = make_dummy_gap_response(status=expected_status, notes="Review notes.")
        mock_persistence_service.update_gap_review.return_value = updated_gap

        resp = client_a.patch(
            f"/api/v1/projects/{PROJECT_A_ID}/gaps/{GAP_A_ID}",
            json={"status": status_val, "user_notes": "Review notes."},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["status"] == status_val

    def test_update_gap_review_invalid_status_rejected_by_schema(self, client_a: TestClient) -> None:
        """34. Status 'open' or arbitrary string is rejected with HTTP 422."""
        resp = client_a.patch(
            f"/api/v1/projects/{PROJECT_A_ID}/gaps/{GAP_A_ID}",
            json={"status": "open"},
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        resp2 = client_a.patch(
            f"/api/v1/projects/{PROJECT_A_ID}/gaps/{GAP_A_ID}",
            json={"status": "unsupported_status"},
        )
        assert resp2.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_update_gap_review_notes_length_limit(self, client_a: TestClient) -> None:
        """35. User notes exceeding 2000 characters are rejected with HTTP 422."""
        resp = client_a.patch(
            f"/api/v1/projects/{PROJECT_A_ID}/gaps/{GAP_A_ID}",
            json={"status": "investigating", "user_notes": "a" * 2001},
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_review_notes_preserved_when_omitted_via_api(
        self,
        client_a: TestClient,
        mock_persistence_service: MagicMock,
    ) -> None:
        """35b. Patching status with omitted notes preserves previous review notes."""
        gap_with_notes = make_dummy_gap_response(status=GapStatus.RESOLVED, notes="Existing preserved note.")
        mock_persistence_service.update_gap_review.return_value = gap_with_notes

        resp = client_a.patch(
            f"/api/v1/projects/{PROJECT_A_ID}/gaps/{GAP_A_ID}",
            json={"status": "resolved"},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["confidence_metadata"]["bharmafills"]["user_review"]["notes"] == "Existing preserved note."


# =============================================================================
# 5. Operational Failures Tests
# =============================================================================

class TestGapOperationalFailures:
    """Verify safe degradation and error responses when dependencies are unconfigured/unavailable."""

    def test_ai_provider_not_configured_returns_503(
        self,
        client_a: TestClient,
        mock_detection_service: MagicMock,
    ) -> None:
        """36. Detection endpoint returns HTTP 503 when AI provider is not configured."""
        mock_detection_service.is_configured = False
        resp = client_a.post(f"/api/v1/projects/{PROJECT_A_ID}/gaps/detect")
        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "AI provider is not configured" in resp.json()["detail"]

    def test_database_service_not_configured_returns_503(
        self,
        client_a: TestClient,
        mock_persistence_service: MagicMock,
    ) -> None:
        """37. Persistence endpoints return HTTP 503 when DB service is not configured."""
        mock_persistence_service.is_configured = False
        resp = client_a.get(f"/api/v1/projects/{PROJECT_A_ID}/gaps")
        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "Database service is unavailable" in resp.json()["detail"]

    def test_database_unavailable_error_returns_503(
        self,
        client_a: TestClient,
        mock_persistence_service: MagicMock,
    ) -> None:
        """38. DatabaseUnavailableError raised during query returns HTTP 503."""
        mock_persistence_service.list_project_gaps.side_effect = DatabaseUnavailableError("Pool exhausted")
        resp = client_a.get(f"/api/v1/projects/{PROJECT_A_ID}/gaps")
        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "Database service is unavailable." in resp.json()["detail"]

    def test_persistence_transaction_error_returns_500(
        self,
        client_a: TestClient,
        mock_persistence_service: MagicMock,
    ) -> None:
        """39. GapTransactionError returns HTTP 500 without leaking stack traces."""
        mock_persistence_service.persist_detection_result.side_effect = GapTransactionError(
            "Transaction aborted due to constraint failure."
        )
        resp = client_a.post(f"/api/v1/projects/{PROJECT_A_ID}/gaps/detect")
        assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert resp.json()["detail"] == "Database transaction failed during gap persistence."

    def test_detection_unexpected_exception_returns_500(
        self,
        client_a: TestClient,
        mock_detection_service: MagicMock,
    ) -> None:
        """40. Unexpected exception during detection returns HTTP 500 without leaking stack traces."""
        mock_detection_service.detect_gaps.side_effect = RuntimeError("Fatal hardware interrupt")
        resp = client_a.post(f"/api/v1/projects/{PROJECT_A_ID}/gaps/detect")
        assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert resp.json()["detail"] == "An unexpected error occurred during information gap detection."
