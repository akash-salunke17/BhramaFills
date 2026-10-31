# Bharmafills — Comprehensive Quality Assurance & Testing Guide

> **Document Status**: Canonical Testing Baseline
> **Mandatory Policy**: Immediate Testing After Every Module Implementation
> **Current Status**: 52 Unit Tests Passing (Phase 2 Verified)
> **Workspace Identifier**: `Shinchan`

---

## 1. The Bharmafills Testing Mandate

**We never implement multiple features and test everything at the end.**

Every engineer and AI agent working on this codebase must adhere to the 4-step implementation cycle:
1. **Implement One Module**: Write the specific function, component, or endpoint.
2. **Write Automated Tests**: Cover standard inputs, invalid inputs, edge cases, and failure scenarios.
3. **Execute & Verify Immediately**: Run the test suite in the terminal; do not proceed until 100% passing.
4. **Hardening**: Fix any identified edge-case bugs, run the linter, and verify the production build.

---

## 2. Test Pyramid & Tooling Matrix

| Test Type | Target Scope | Framework / Tools | Current Status |
| :--- | :--- | :--- | :--- |
| **Frontend Unit Tests** | Validation schemas, utility functions, persistence logic | Vitest + JSDOM | `COMPLETED` (30 tests) |
| **Frontend Component Tests** | React hooks, forms, modal dialogs, project cards | Vitest + React Testing Library | `COMPLETED` (22 tests) |
| **Backend Unit & Configuration** | Settings, Pydantic validation, app metadata, CORS | Pytest | `COMPLETED` (19 tests) |
| **Backend API Integration** | FastAPI health endpoint, async HTTPX ASGI probe | Pytest + HTTPX | `COMPLETED` (4 tests) |
| **Backend Extraction & AI** | Text extraction, sanitization, prompt builders | Pytest + pytest-mock | `PLANNED` (Step 7+) |
| **End-to-End (E2E)** | Full user workflows (Create project -> Ingest -> Gaps -> Export) | Playwright | `PLANNED` (Step 13) |

---

## 3. Frontend Testing Suite (Active Baseline)

### 3.1 Test Suite Breakdown
Total: **52 Passing Automated Tests** across 4 test suites in `frontend/tests/`:

1. **`researchProjectSchema.test.js` (14 tests)**:
   - Validates minimum title length (3 characters) and maximum length (120 characters).
   - Validates minimum research question length (10 characters) and maximum length (1000 characters).
   - Enforces status whitelist (`active`, `in_progress`, `completed`, `archived`).
   - Enforces category whitelist (Education, Technology, Scholarships, Healthcare, etc.).
   - Verifies whitespace trimming and input sanitization.
2. **`researchService.test.js` (16 tests)**:
   - Verifies CRUD persistence: `getProjects`, `saveProject`, `deleteProject`, `getProjectById`.
   - Tests corrupted JSON recovery: guarantees invalid storage data is safely quarantined to `bharmafills_research_corrupted_backup_<timestamp>` without crashing.
   - Tests `QuotaExceededError`: simulates storage exhaustion and verifies graceful in-memory fallback.
   - Verifies schema version tagging (`SCHEMA_VERSION: 1`).
3. **`useResearchProjects.test.jsx` (10 tests)**:
   - Tests reactive state updates on project addition, edit, and deletion.
   - Tests live multi-parameter filtering (by status, by category, and by text search).
   - Tests sorting mechanisms (recently updated, recently created, alphabetical).
   - Tests multi-tab synchronization via `window.addEventListener('storage', ...)`.
4. **`ResearchPage.test.jsx` (12 tests)**:
   - Verifies modal dialog opening, focus trap, and form submission.
   - Verifies inline validation error rendering on invalid form submission.
   - Verifies empty state rendering when no projects match active filters.
   - Tests two-step project deletion modal and state cleanup.

### 3.2 Running Frontend Tests in PowerShell
```powershell
# Navigate to frontend
cd "D:\Users\Vikas Salunke\Downloads\Shinchan\frontend"

# Run tests in Vitest watch-free mode
npm.cmd test

# Run tests with coverage reporting
npm.cmd test -- --coverage

# Run specific test file
npx.cmd vitest run tests/researchService.test.js
```

### 3.3 Frontend Testing Best Practices
- **Act Warnings Prevention**: Avoid state updates outside React's event loop. When testing hooks, wrap mutations in `act(() => { ... })`.
- **Keyboard Event Performance**: In JSDOM, simulating 100+ keystrokes with `userEvent.type()` can cause 5000ms timeouts. For long research questions (100–500 chars), use `fireEvent.change(input, { target: { value: text } })`.
- **Local Storage Mocking**: Always restore `window.localStorage` in `beforeEach` and `afterEach` hooks to prevent state leakage between tests.

---

## 4. Backend Testing Suite (Step 5A Baseline Active)

### 4.1 Pytest Suite Breakdown
Total: **23 Passing Automated Tests** in `backend/tests/`:

1. **`test_health.py` (4 tests)**:
   - Verifies synchronous client returns HTTP 200 with `{ "status": "ok", "service": "...", "version": "..." }`.
   - Verifies asynchronous HTTPX client receives HTTP 200 via `ASGITransport`.
   - Verifies health endpoint does not leak environment keys, secrets, or internal paths.
   - Verifies unprefixed `/health` returns 404 (enforcing `/api/v1` prefix).
2. **`test_app.py` (4 tests)**:
   - Verifies application metadata matches configured settings.
   - Verifies OpenAPI schema generation includes `/api/v1/health` and schema components.
   - Verifies Swagger UI is accessible in development and test environments.
   - Verifies Swagger UI and OpenAPI docs are disabled in production mode.
3. **`test_cors.py` (6 tests)**:
   - Verifies allowed localhost origin (`http://localhost:5173`) receives `access-control-allow-origin` and credentials header.
   - Verifies allowed loopback IP origin (`http://127.0.0.1:5173`) receives allow headers.
   - Verifies unauthorized origin (`http://malicious-external-site.com`) does not receive allow headers.
   - Verifies preflight `OPTIONS` request returns 200 and allowed methods.
   - Verifies custom origin configuration via Settings.
   - Verifies default origins do not contain insecure wildcards (`*`).
4. **`test_config.py` (9 tests)**:
   - Verifies default settings validity.
   - Verifies environment variable overrides.
   - Verifies comma-separated string parsing for `CORS_ORIGINS`.
   - Verifies empty string handling for `CORS_ORIGINS`.
   - Verifies API prefix slash normalization.
   - Verifies invalid environment raises Pydantic `ValidationError`.
   - Verifies invalid port numbers raise Pydantic `ValidationError`.
   - Verifies boolean helper properties (`is_development`, `is_test`, `is_production`).
   - Verifies `get_settings()` singleton caching.

### 4.2 Running Backend Tests in PowerShell
```powershell
# Navigate to backend directory
cd "D:\Users\Vikas Salunke\Downloads\Shinchan\backend"

# Execute test suite
.\venv\Scripts\python.exe -m pytest
```

---

## 5. Quality Gate & Continuous Integration Checklist

Before committing or releasing any phase:
1. **Frontend Unit Tests**: `npm.cmd test` passes with zero failures (52 tests passing).
2. **Frontend Linting**: `npm.cmd run lint` returns 0 errors and 0 warnings.
3. **Frontend Build**: `npm.cmd run build` completes with exit code 0.
4. **Backend Unit Tests**: `python -m pytest` passes with zero failures (23 tests passing).
5. **Manual Sanity Check**: Verify desktop, tablet, and mobile views in the browser, and verify API health probe.
