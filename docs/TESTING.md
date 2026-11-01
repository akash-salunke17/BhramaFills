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
| **Backend Unit & Configuration** | Settings, Pydantic validation, app metadata, CORS, DB config | Pytest | `COMPLETED` (26 tests) |
| **Backend Database Lifecycle & API** | Process & DB health probes, connection manager, migrations, HTTPX ASGI | Pytest + HTTPX + asyncpg | `COMPLETED` (27 tests) |
| **Backend Web Extraction & Persistence** | SSRF defenses, DNS pinning, BeautifulSoup parser, Supabase persistence | Pytest + HTTPX + asyncpg | `COMPLETED` (61 tests) |
| **Backend AI & Gap Detection** | Text extraction, sanitization, prompt builders | Pytest + pytest-mock | `PLANNED` (Step 9+) |
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

## 4. Backend Testing Suite (Step 5, 6, 7, 8 & 9A Active Baseline)

### 4.1 Pytest Suite Breakdown
Total: **171 Passing Automated Tests** across 15 test suites in `backend/tests/`:

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
5. **`test_db_config.py` (7 tests)**:
   - Verifies `SUPABASE_DB_URL` default parsing, `postgresql://` and `postgres://` scheme validation.
   - Verifies whitespace normalization, invalid scheme rejection, environment loading, and timeout bounds.
6. **`test_db_connection.py` (7 tests)**:
   - Verifies `DatabaseManager` not-configured behavior, lazy initialization, connection timeout handling.
   - Verifies query result validation, connection pool drainage, and error logging without secret leakage.
7. **`test_db_health.py` (5 tests)**:
   - Verifies process health remains independent of database.
   - Verifies `/api/v1/health/database` returns 200 connected, 200 not_configured, or 503 unavailable.
   - Verifies database health response never leaks passwords, credentials, or internal connection parameters.
8. **`test_db_migration.py` (11 tests)**:
   - Verifies migration file naming, version format, and deterministic checksum generation.
   - Verifies migration SQL contains zero destructive statements (no DROP or TRUNCATE).
   - Verifies creation of all 10 Bharmafills domain tables and `schema_migrations` table.
   - Verifies UUID primary keys, TIMESTAMPTZ defaults, and domain check constraints.
   - Verifies Row Level Security (RLS) is enabled across all tables.
   - Verifies `DatabaseMigrator` drift detection, idempotent re-run skipping, and schema integrity reporting.
9. **`test_web_url_validator.py` (11 tests)**:
   - Verifies accepted HTTP/HTTPS schemes, rejects non-HTTP schemes (`file://`, `ftp://`, `data:`, `javascript:`).
   - Verifies control character rejection, embedded credential blocking, and port bounds (standard web ports only).
   - Verifies immediate blocking of localhost, local network names, and direct private/loopback/metadata IP literals.
   - Verifies Punycode IDN domain normalization and IPv6 zone identifier rejection.
10. **`test_web_ssrf.py` (7 tests)**:
    - Verifies public IPs pass SSRF checks.
    - Verifies DNS resolution to private IPv4 (RFC 1918), loopback (`127.0.0.0/8`), and cloud metadata (`169.254.169.254`).
    - Verifies CGNAT (`100.64.0.0/10`), TEST-NET, and IPv4-mapped IPv6 ranges are blocked.
    - Verifies DNS rebinding defense: if ANY returned A/AAAA record is private, the entire request is blocked.
11. **`test_web_extractor.py` (5 tests)**:
    - Verifies title, meta description, author, language, and canonical URL extraction.
    - Verifies complete stripping of scripts, styles, nav, footer, header, and aside tags.
    - Verifies structured heading parsing (`level`, `text`) and clean paragraph blocks.
    - Verifies word/character counting and deterministic SHA-256 content hash calculation.
    - Verifies OpenGraph fallback parsing.
12. **`test_web_route.py` (9 tests)**:
    - Verifies `POST /api/v1/web/extract` returns HTTP 200 and structured payload on valid web page.
    - Verifies HTTP 400 Bad Request on SSRF loopback, metadata, and invalid URL syntax.
    - Verifies HTTP 413 on payload > 2 MB, HTTP 422 on non-HTML content type, HTTP 504 on timeout, and HTTP 502 on network failure.
    - Verifies redirect security: HTTP 400 on redirect loops and insecure HTTPS to HTTP downgrades.
    - Verifies OpenAPI schema documents `/api/v1/web/extract`.
13. **`test_source_ingestion.py` (29 tests)**:
    - Verifies `ProjectWebSourceRequest` validation and rejection of empty/oversized URLs.
    - Verifies `ProjectWebSourceResponse` schema serialization and field completeness.
    - Verifies `DatabaseManager.acquire_connection()` lifecycle, pool checks, timeouts, and error translations.
    - Verifies `WebSourceIngestionService`:
      - Project existence validation and 404 on missing/soft-deleted projects.
      - Duplicate URL detection returning existing source with `is_duplicate=True` without re-fetching.
      - Duplicate content hash detection returning existing source with `is_duplicate=True` without re-inserting.
      - Atomic transaction execution inserting into `public.sources` and `public.extracted_content`.
      - Empty content rejection raising `EmptyExtractedContentError` (422).
      - Title fallback derivation and truncation to VARCHAR(255).
      - Project sources listing and single source detail retrieval.
    - Verifies Route Integration:
      - `POST /api/v1/projects/{project_id}/sources/web` returning 201 Created on fresh ingestion.
      - `POST /api/v1/projects/{project_id}/sources/web` returning 200 OK on duplicate resolution.
      - Proper status codes: 400 (SSRF/invalid URL), 404 (project missing), 413 (oversized payload), 422 (unsupported type/empty text/invalid UUID), 502 (network), 503 (database unavailable), 504 (timeout).
      - `GET /api/v1/projects/{project_id}/sources` returning 200 with source summaries.
      - `GET /api/v1/projects/{project_id}/sources/{source_id}` returning 200 with full extracted text.
      - OpenAPI schema documents all source ingestion and listing endpoints.

14. **`test_pdf_ingestion.py` (34 tests)**:
    - Verifies `PDFValidator`: MIME validation (`application/pdf`), `%PDF-` header magic bytes check, file size limit rejection (`PDF_MAX_UPLOAD_BYTES`), filename sanitization (directory traversal removal, stem truncation to 251 chars preserving `.pdf`), in-memory opening, password-protected PDF rejection, and page count limit rejection (`PDF_MAX_PAGES`).
    - Verifies `PDFExtractor`: multi-page text extraction, page-level word/character counts, 1-based page indexing, whitespace normalization, PDF document metadata extraction (title, author, subject, creation date), scanned/empty document detection, readability classification (`fully_readable`, `partially_readable`, `no_extractable_text`, `empty`), and SHA-256 binary and text hash generation.
    - Verifies `PDFSourceIngestionService`:
      - Active project validation and 404 on missing/soft-deleted projects.
      - Binary SHA-256 hash deduplication returning existing source with `is_duplicate=True` without re-inserting.
      - Scanned document isolation: PDFs with 0 extractable characters safely recorded in `public.sources` with `ingestion_status='failed'` without violating non-empty text database check constraints.
      - Atomic transaction execution writing to `public.sources` and `public.extracted_content`.
      - Fallback title derivation from PDF metadata title or sanitized filename.
    - Verifies Route Integration (`POST /api/v1/projects/{project_id}/sources/pdf`):
      - 201 Created on fresh PDF upload with structured page items and metadata.
      - 200 OK on duplicate upload resolved idempotently via binary hash.
      - Proper status codes: 400 Bad Request (invalid header, corrupted, password protected), 404 Not Found (project missing), 413 Payload Too Large (oversized file or page limit exceeded), 415 Unsupported Media Type (non-pdf MIME or non-.pdf extension), 422 Unprocessable Entity (scanned image-only PDF), 503 Service Unavailable (database unconfigured/unavailable).
      - OpenAPI schema documents PDF ingestion endpoint and multipart schema.
15. **`test_ai_openrouter.py` (23 tests)**:
    - Verifies Configuration: default model (`nvidia/nemotron-3-ultra-550b-a55b:free`), base URL normalization, timeout constraints, API key whitespace stripping, and masked key helper (`sk-o...1234`).
    - Verifies Chat Schemas: `ChatMessage` validation for system/user/assistant, `ChatCompletionRequest`, and `ChatCompletionResponse` properties with `first_content` helper.
    - Verifies `OpenRouterClient` (Mocked HTTP responses):
      - Rejection of unconfigured client with `AIAuthenticationError` without network traffic.
      - Successful completion on HTTP 200 parsing into `ChatCompletionResponse`.
      - Non-retryable immediate failure on HTTP 401/403 (`AIAuthenticationError`) and HTTP 402 (`AIQuotaExceededError`) without leaking keys in exceptions.
      - Bounded retry with exponential backoff on HTTP 429 (`AIRateLimitError`, respecting Retry-After header) and HTTP 503 (`AIProviderUnavailableError`).
      - Bounded retry on `httpx.TimeoutException` raising `AITimeoutError`.
      - Malformed response structure handling raising `AIResponseValidationError`.
    - Verifies `SafeResponseParser`:
      - Direct JSON string parsing and validation into Pydantic model.
      - Markdown code block stripping (` ```json ` and ` ``` `).
      - Embedded bracketed JSON substring extraction from conversational text.
      - Malformed JSON handling producing structured validation errors without unhandled exceptions.
      - Schema mismatch rejection without silently fabricating missing fields or citations.
      - Non-JSON / conversational output rejection.
    - Verifies AI Diagnostics Route (`GET /api/v1/health/ai`):
      - Returns 200 with `status='not_configured'` when unconfigured; response contains no credential-derived information.
      - Returns 200 with `status='configured'` when API key is present; response never exposes any key material.
      - Preserves model identifier, free-tier flag, and privacy warning without triggering paid API calls.
      - OpenAPI specification documents `/api/v1/health/ai`.
  16. **Prompt Security Architecture, Truncation Transparency & Structured Metadata Test Suite** (`backend/tests/test_prompt_security.py` — 54 tests):
    - Verifies Foundational Security System Prompt:
      - Explicit declaration of 4-tier trust hierarchy (TRUSTED System, TRUSTED Task, UNTRUSTED Sources, UNVERIFIED Output).
      - Explicit declaration of probabilistic boundary limitations in unified model attention.
      - Prohibitions against instruction-following inside source tags, jailbreaks (DAN), and system override.
      - Secrets protection (system prompts, API keys, database credentials).
      - Strict prohibition against fact or citation fabrication and hallucination.
      - Mandatory distinction between direct quotations, paraphrases, inferences, and missing information.
    - Verifies `SourceDocument` Domain Model:
      - Validation of `web`, `pdf`, and normalization of `url` to `web`.
      - Automatic conversion of UUID instances to string IDs.
      - Rejection of empty/whitespace IDs, unsupported types, and XML special characters (`<`, `>`, `"`).
      - Frozen immutability.
    - Verifies XML Sanitization & Delimiter Safety:
      - Stripping of breakout closing tags (`</untrusted_source_document>`), fake `<system>` tags, comments (`<!-- ... -->`), CDATA (`<![CDATA[ ... ]]>`), and processing instructions.
      - Preservation of mathematical comparisons (e.g., `x < 10`, `price < $50`).
    - Verifies XML Fencing, Truncation Transparency & Prompt Assembly:
      - Correct XML wrapper syntax, 1-based source indexing, and sanitized title attribute formatting.
      - Explicit machine-readable `truncated="true/false"` and `omitted_chars="N"` attributes on fenced tags.
      - Explicit content truncation notices when source text exceeds `MAX_SOURCE_CHARS` (40,000 characters).
      - Explicit `<sources_truncation_notice>` tags when source count exceeds `MAX_SOURCES_PER_PROMPT` (20 sources).
      - Assembly into `[ChatMessage(role='system'), ChatMessage(role='user')]` envelopes.
      - Seamless support for both `SourceDocument` instances and dictionaries.
      - Adversarial jailbreak and fence-breakout containment testing.
    - Verifies Structured Truncation & Omission Metadata Contracts (Step 9B.1.2 — 21 test scenarios):
      - `SourceTruncationMetadata` tracking for sources below limit, at limit, and over limit.
      - Invariant enforcement: `omitted_char_count == original_char_count - retained_char_count`, `was_truncated == (omitted_char_count > 0)`, `retained <= original`.
      - `SourceOmissionSummary` tracking when sources <= 20 and > 20.
      - Invariant enforcement: `included + omitted == provided`, `len(omitted_ids) == omitted`.
      - `PromptBuildResult` structure and properties: `has_character_truncation`, `has_source_omissions`, `.to_dict()`.
      - Zero sources provided behavior (empty list metadata, 0 provided/included/omitted summary).
      - `build_system_only()` return shape and metadata.
      - Caller backwards compatibility: sequence unpacking (`sys_msg, user_msg = result`), indexing (`result[0]`), and length (`len(result)`).
      - Factual grounding and data-integrity guarantees: callers have programmatic certainty of whether sources were truncated or omitted without parsing XML strings.
  17. **Evidence Extraction Schemas & Data Model Test Suite** (`backend/tests/test_evidence_schemas.py` — 33 tests):
    - Verifies `EvidenceLocation`:
      - Web source locations (URLs, heading hierarchies, paragraph index, human-readable descriptions).
      - PDF source locations (1-based page numbers, start/end character offsets).
      - Source type normalization (`url` -> `web`).
      - Positive page bounds enforcement (`page_number >= 1`; rejects 0 and negative).
      - Safe URL validation (accepts http/https; rejects non-http schemes, control characters, missing netloc).
      - Character offset ordering (`end_char > start_char`; rejects `end_char <= start_char` and negative offsets).
      - Minimal location construction with optional field handling.
      - Source ID validation (rejects empty/whitespace and length > 100).
      - Immutability check (`frozen=True`).
    - Verifies `ExtractedFact`:
      - Direct quote representation (`RepresentationType.DIRECT_QUOTE`).
      - Faithful paraphrase representation (`RepresentationType.PARAPHRASE`).
      - Non-empty statement and non-empty evidence text enforcement.
      - Confidence score bounds (accepts 0.0 and 1.0; rejects < 0.0 and > 1.0).
      - Qualifier and extraction warning preservation and whitespace trimming.
      - Immutability check.
    - Verifies `SourceClaim`:
      - All 7 claim types accepted (`factual_assertion`, `recommendation`, `policy_statement`, `prediction`, `opinion`, `eligibility_condition`, `numerical_or_statistical`).
      - Rejection of invalid/unsupported claim types.
      - Source ID cross-field consistency (`claim.source_id == claim.evidence_location.source_id`).
      - Absence of implicit verification or truth-assertion fields (`verified`, `is_true` forbidden).
    - Verifies `EvidenceExtractionResult`:
      - Successful extraction envelope containing facts and claims.
      - Partial extraction envelope for truncated source corpora.
      - Truncation integrity invariant: rejects `extraction_status='success'` when `source_truncated=True`.
      - Failure integrity invariant: `extraction_status='failed'` requires non-empty error list.
      - No-content integrity invariant: `extraction_status='no_content'` forbids facts and claims.
      - Source ID consistency: rejects facts or claims referencing mismatched `source_id`.
      - Character count bounds: rejects `processed_character_count > source_character_count`.
      - Full JSON serialization and deserialization roundtrip.
    - Verifies Security & Integration:
      - Extra/unexpected field rejection (`extra='forbid'` across all models).
      - Excessive string length bounds.
      - Unicode and multilingual text preservation (Devanagari, Chinese, emojis).
      - Adversarial prompt injection payloads in evidence text remain inert data.
      - Integration with `SafeResponseParser.parse_model_output()`.
  18. **Evidence Extraction Prompt Templates Test Suite** (`backend/tests/test_evidence_templates.py` — 18 tests):
    - Verifies Importability and Public API:
      - Public template exports available from `app.services.ai.prompts.evidence_templates`, `app.services.ai.prompts`, and `app.services.ai`.
    - Verifies Extraction Instructions & Domain Alignment:
      - Instructions for extracting `ExtractedFact` and `SourceClaim`.
      - Inclusion of all required fields (`fact_id`, `statement`, `fact_type`, `location`, `evidence_text`, `representation_type`, `confidence`, `qualifiers`, `uncertainty_notes`, `extraction_warnings`, `claim_id`, `claim_text`, `claim_type`, `source_id`, `evidence_location`).
      - All controlled enum values referenced (`FactType`, `ClaimType`, `RepresentationType`).
    - Verifies Direct Quote vs. Paraphrase Separation:
      - Explicit rules mandating verbatim text for `direct_quote` and faithful restatement for `paraphrase`.
      - Strict prohibition against presenting a paraphrase as a quotation.
    - Verifies Confidence Semantics:
      - Defined as extraction fidelity/accuracy, explicitly noting it does not represent objective truth, source trustworthiness, or external verification.
    - Verifies Anti-Fabrication & Strict Grounding Rules:
      - All 10 anti-fabrication rules confirmed present in instruction text.
      - Empty source handling: returns empty arrays without inventing facts.
    - Verifies Prompt-Injection Defense:
      - Source content treated as untrusted data; instruction overrides ignored; secrets protected; probabilistic boundary explicitly noted.
    - Verifies Truncation and Omission Awareness:
      - `build_truncation_notice()` emits empty string when corpus is complete.
      - Emits prominent warning with character counts when source content is truncated.
      - Emits source list omission notice when sources exceed prompt bounds.
      - `build_evidence_extraction_prompt()` injects truncation notices into the user turn.
    - Verifies Output Contract & Backend Boundary:
      - Strict raw JSON contract; forbids Markdown fences (` ```json `); forbids introductory prose.
      - Explicitly prohibits requesting backend-owned envelope metadata (`extracted_at`, `extraction_status`, `source_truncated`, character processing counts, errors).
    - Verifies PromptBuilder and Parser Integration:
      - `assemble_evidence_extraction_prompt()` returns a valid `PromptBuildResult` with sequence unpacking, metadata, and XML fences.
      - Incorporates character truncation notices directly into the user message when source text exceeds `MAX_SOURCE_CHARS`.
      - `SafeResponseParser` parses model output into `EvidenceExtractionPayload`.
  19. **Evidence Extraction Pipeline & Structured Parser Test Suite** (`backend/tests/test_evidence_pipeline.py` — 35 tests):
    - Verifies Service Unit Functionality (`EvidenceExtractionService`):
      - Happy-path extraction producing `SUCCESS` status with discrete facts and claims.
      - Normalization of source types (`pdf`, `url` -> `web`).
      - Empty and whitespace-only content returning `NO_CONTENT` immediately without invoking upstream AI completions.
      - Unconfigured AI provider error handling (`FAILED` status envelope or `AIAuthenticationError` when `raise_on_error=True`).
      - AI provider exceptions (`AITimeoutError`, `AIProviderUnavailableError`, unexpected runtime errors).
      - Parameter validation for `source_id` bounds and invalid source types.
      - `extract_document_evidence` convenience wrapper.
    - Verifies Structured Parser & Schema Integration:
      - Markdown-fenced JSON (```json ... ```) parsing.
      - Malformed or non-JSON model response handling (`FAILED` status or `AIResponseValidationError`).
      - Strict extra field rejection (`extra='forbid'`) preventing hallucinated envelope properties.
    - Verifies Evidence Integrity Checks:
      - Rejection of facts or claims with mismatched `source_id`, triggering status downgrade to `PARTIAL` and explicit integrity warnings.
      - Verbatim direct quote checking against source text with whitespace normalization; flags non-matching quotes as potential hallucinations while retaining data.
      - Character offset bounds verification against processed text limits.
      - Web claim URL domain consistency checks against source URLs.
    - Verifies Truncation Metadata & Batch Isolation:
      - Truncated source corpora correctly setting `source_truncated=True`, status `PARTIAL`, and tracking character counts.
      - `extract_sources_batch` processing multiple sources with per-source try-except failure isolation.
      - Accurate summary metrics (`total_sources`, `successful_sources`, `partial_sources`, `failed_sources`, `empty_sources`).
      - Dict-based and `SourceDocument` batch inputs.
    - Verifies FastAPI Endpoint Integration (`POST /api/v1/projects/{project_id}/sources/{source_id}/extract`):
      - HTTP 200 OK returning authoritative `EvidenceExtractionResult`.
      - Optional `ExtractEvidenceRequest` pass-through or execution without body.
      - HTTP 404 for missing project or missing source.
      - HTTP 503 when AI provider is unconfigured or database is unavailable.
      - HTTP 422 for malformed UUID path parameters.
  20. **Evidence Database Persistence & Retrieval Test Suite** (`backend/tests/test_evidence_persistence.py` — 26 tests):
    - Verifies Migration Integrity:
      - Validates SQL syntax and constraints in `20261101120000_add_evidence_claims_and_runs.sql`.
      - Verifies `extraction_runs`, `source_claims`, and additive columns on `evidence`.
      - Guarantees zero destructive statements (`DROP TABLE`, `TRUNCATE TABLE`).
    - Verifies Service Unit Persistence:
      - Happy-path insertion of extraction result into `extraction_runs`, `evidence`, and `source_claims`.
      - Correct generation of IDs, timestamps, and cross-linking to `run_id`.
      - Rejection of invalid payloads and mismatched project/source identifiers.
      - Persistence with empty facts/claims (`no_content` or `failed` run tracking).
    - Verifies Transactional Integrity & Rollback:
      - Simulates database exceptions during fact insertion; verifies `conn.transaction` abort and rollback.
      - Simulates database exceptions during claim insertion; verifies complete rollback of the entire run.
      - Ensures zero orphan extraction runs or half-persisted states remain after errors.
    - Verifies Idempotency & Batch Isolation:
      - Re-persisting with existing idempotency key raises `DuplicateExtractionRunError`.
      - `persist_batch_extraction_results` handles multi-source results with per-source try-except isolation.
    - Verifies Multi-Dimensional Retrieval:
      - Filtering by source, extraction run, item type (`all`, `facts`, `claims`), fact type, and claim type.
      - Correct pagination offsets and limit caps.
      - Extraction run listing and detailed telemetry retrieval.
    - Verifies FastAPI Evidence Routes:
      - `POST /api/v1/projects/{project_id}/sources/{source_id}/persist` returning HTTP 201 Created.
      - `GET /api/v1/projects/{project_id}/sources/{source_id}/evidence` returning HTTP 200 OK.
      - `GET /api/v1/projects/{project_id}/evidence` returning HTTP 200 OK.
      - `GET /api/v1/projects/{project_id}/sources/{source_id}/extraction-runs` returning HTTP 200 OK.
      - `GET /api/v1/projects/{project_id}/extraction-runs/{run_id}` returning HTTP 200 OK.
      - Error mapping: HTTP 404 for missing project/source/run, HTTP 503 when database is unconfigured.

### 4.2 Running Backend Tests in PowerShell
```powershell
# Navigate to backend directory
cd "D:\Users\Vikas Salunke\Downloads\Shinchan\backend"

# Execute test suite (Windows asyncio Proactor loopback socket requires standard network permissions)
.\venv\Scripts\python.exe -m pytest
```

### 4.3 Step 9B.3.2 Live Database Migration & Catalog Audit Results
- **Migration Application**:
  - `20261101120000_add_evidence_claims_and_runs.sql` applied via `DatabaseMigrator.apply_all_pending()` against Supabase PostgreSQL 17.11.
  - Checksum verified: `895361b72cabcad4d5de857ec3235a73717c62e7ee70401c2031910461871567` (exact match with migration file).
- **Direct Live Database Inspection**:
  - `public.extraction_runs`: Verified exists with 17 columns, 5 indexes, and RLS enabled.
  - `public.source_claims`: Verified exists with 19 columns, 5 indexes, unique index `idx_source_claims_run_claim_id_unique`, and RLS enabled.
  - `public.evidence`: Verified 11 additive columns present, unique index `idx_evidence_run_fact_id_unique`, and RLS enabled.
  - Table counts: 7 verified tables, 0 records lost, 0 orphan records.
- **Full Stack Quality Gate Execution**:
  - Backend tests: 339 passed in 47.48s (0 failures, 0 errors).
  - Frontend tests: 52 passed in 25.00s across 4 test suites (0 failures).
  - ESLint: 0 errors, 0 warnings.
  - Production build: Vite built in 4.11s with exit code 0.

### 4.4 Phase C2 Supabase JWT Authentication Test Suite (`backend/tests/test_auth.py` — 35 tests)
- **Valid Tokens (4 tests)**:
  - Valid ES256 token verification returning typed `AuthenticatedUser`.
  - Immutability of `AuthenticatedUser` model.
  - Safe handling of missing optional claims (email, app_metadata).
  - Valid HS256 token verification when `SUPABASE_JWT_SECRET` is explicitly configured.
- **Cryptographic & Anti-Tampering (5 tests)**:
  - Tampered payload segment rejected with `InvalidSignatureError`.
  - Token signed with untrusted EC private key rejected with `InvalidSignatureError`.
  - Prohibited `alg: none` rejected with `InvalidAlgorithmError`.
  - Unsupported algorithms (e.g. HS512, RS512) rejected with `InvalidAlgorithmError`.
  - HS256 rejected when secret is unconfigured.
- **Claims Verification (8 tests)**:
  - Expired tokens rejected with `ExpiredTokenError`.
  - Future `nbf` tokens rejected with `InvalidTokenError`.
  - Audience mismatch rejected with `InvalidTokenError`.
  - Issuer mismatch rejected with `InvalidTokenError`.
  - Missing subject (`sub`) claim rejected with `InvalidTokenError`.
  - Non-UUID subject claim rejected with `InvalidTokenError`.
  - Empty, whitespace, or malformed JWT strings rejected with `InvalidTokenError`.
- **JWKS Resilience & Cooldown (3 tests)**:
  - `ResilientJWKClient` refresh cooldown throttles rapid consecutive lookups for unknown `kid` to prevent DoS request amplification.
  - Unreachable JWKS endpoint fails closed with `JWKSUnavailableError`.
  - Missing authentication configuration fails closed with `AuthenticationConfigurationError`.
- **FastAPI Dependencies (9 tests)**:
  - Missing `Authorization` header returns HTTP 401 with `WWW-Authenticate: Bearer`.
  - Non-Bearer schemes return HTTP 401 with `error="invalid_request"`.
  - Empty Bearer token returns HTTP 401.
  - Valid token grants access to protected dependency and injects `AuthenticatedUser`.
  - Expired token returns HTTP 401 with explicit RFC 6750 `error="invalid_token"`.
  - Tampered token returns generic 401 without leaking internal crypto tracebacks.
  - `get_optional_user` returns `None` without header, `AuthenticatedUser` with valid token, and HTTP 401 with invalid token.
- **Advanced Security & Settings (6 tests)**:
  - Prohibited symmetric algorithms rejected.
  - Key rotation dynamically resolves signing keys matching token `kid`.
  - Zero token or credential leakage into logging records.
  - Dynamic derivation of `effective_supabase_url`, JWKS endpoint, and issuer from `SUPABASE_DB_URL`.
  - Explicit `SUPABASE_URL` overrides derived values.
  - Comma-separated algorithm configuration parsing.

### 4.5 Phase C3 Route Integration & Protection Boundary Test Suite (`backend/tests/test_route_protection.py` — 46 tests)
- **Unauthenticated Request Rejection (10 tests)**:
  - All 10 project-scoped data endpoints reject requests missing an `Authorization` header with HTTP 401 Unauthorized.
  - Verifies presence of RFC 6750 `WWW-Authenticate: Bearer` challenge header.
  - Verifies clear, non-leaking error detail message.
- **Malformed Token Rejection (10 tests)**:
  - All 10 project endpoints reject malformed Bearer tokens with HTTP 401 Unauthorized.
  - Verifies RFC 6750 `WWW-Authenticate: Bearer error="invalid_token"` challenge header.
- **Expired Token Rejection (10 tests)**:
  - All 10 project endpoints reject expired Bearer tokens with HTTP 401 Unauthorized.
  - Verifies RFC 6750 `WWW-Authenticate: Bearer error="invalid_token"` challenge header.
- **Valid Token Authentication Boundary (10 tests)**:
  - Valid cryptographically signed ES256 Bearer token successfully passes the authentication boundary on all 10 endpoints.
  - Downstream services receive the authenticated request without HTTP 401 rejection.
- **Public Endpoint Accessibility (5 tests)**:
  - Verifies `/api/v1/health` is accessible without authentication (HTTP 200).
  - Verifies `/api/v1/health/database` is accessible without authentication (HTTP 200).
  - Verifies `/api/v1/health/ai` is accessible without authentication (HTTP 200).
  - Verifies `/docs` (Swagger UI) is accessible without authentication (HTTP 200).
  - Verifies `/openapi.json` is accessible without authentication (HTTP 200).
- **Public Health Secret Non-Leakage (1 test)**:
  - Verifies health probes never leak tokens, JWT secrets, database credentials, or signing keys.

### 4.6 Phase C4 Full Security, Regression & Living Documentation Audit Results
- **Full Backend Pytest Suite Run**:
  - Command: `python -m pytest backend/tests -v`
  - Collected: 420 tests
  - Passed: 420 tests (100%)
  - Failed: 0
  - Skipped: 0
  - Warnings: 0
  - Execution Duration: 16.23s
  - Breakdown by Domain:
    - Web Source Ingestion, Extractor & SSRF: 63 tests
    - PDF Ingestion & Validation: 34 tests
    - AI Provider & OpenRouter: 25 tests
    - Prompt Security, Templates & Schemas: 105 tests
    - Evidence Extraction Pipeline: 35 tests
    - Database Connection, Migrations & Health: 30 tests
    - Evidence Persistence & Transaction Rollback: 26 tests
    - App Foundation, Config & CORS: 21 tests
    - Core Supabase JWT Authentication: 35 tests
    - Route Protection & Boundary Enforcement: 46 tests
- **Frontend Vitest Suite Run**:
  - Command: `npm.cmd --prefix frontend test -- --run`
  - Collected: 52 tests across 4 test suites
  - Passed: 52 tests (100%)
  - Failed: 0
  - Execution Duration: 8.82s
- **Frontend Code Quality & Compilation**:
  - Linting (`npm.cmd --prefix frontend run lint`): 0 errors, 0 warnings.
  - Production Build (`npm.cmd --prefix frontend run build`): Exit code 0, 277.86 kB JS, 43.17 kB CSS.
- **Git & Workspace Integrity**:
  - `git diff --check`: 0 whitespace errors.
  - Tracked secrets / JWT tokens: 0 found in repository.

### 4.7 Phase D2 & D2.1 Reusable Backend Project Ownership Authorization Foundation & Mandatory Hardening Test Results
- **Ownership Test Suite (`backend/tests/test_ownership.py`)**:
  - Command: `python -m pytest backend/tests/test_ownership.py -v`
  - Collected: 27 tests
  - Passed: 27 tests (100%)
  - Failed: 0
  - Execution Duration: 0.17s
  - Coverage by Verification Group:
    - **Group 1: Data Model & Domain Exception Tests (3 tests)**:
      - `test_owned_project_context_is_frozen_and_immutable`: Verifies `OwnedProjectContext` is a frozen dataclass rejecting runtime mutation.
      - `test_project_access_denied_error_properties`: Verifies `ProjectAccessDeniedError` retains target project ID, caller ID, and error code `"ACCESS_DENIED"`.
      - `test_resource_mismatch_error_properties`: Verifies `ResourceMismatchError` retains resource classification, ID, target project ID, and actual project ID.
    - **Group 2: verify_project_ownership Core Function Tests (6 tests)**:
      - `test_verify_project_ownership_success_when_owner_matches`: Verifies valid owner receives populated `OwnedProjectContext`.
      - `test_verify_project_ownership_rejects_foreign_owner`: Verifies caller attempting to access another user's project raises `ProjectAccessDeniedError`.
      - `test_verify_project_ownership_rejects_unowned_null_owner_project`: Verifies ownerless legacy project (`user_id IS NULL`) raises `ProjectAccessDeniedError`.
      - `test_verify_project_ownership_rejects_nonexistent_project`: Verifies missing project raises `ProjectNotFoundError`.
      - `test_verify_project_ownership_excludes_soft_deleted_project`: Verifies soft-deleted project (`deleted_at IS NOT NULL`) is rejected as not found.
      - `test_verify_project_ownership_rejects_non_uuid_identities`: Verifies invalid identity types (strings, ints, None) raise `TypeError` failing closed.
    - **Group 3: Child Resource Relationship Integrity Tests (10 tests)**:
      - `test_verify_source_belongs_to_project_success`: Validates active source in target project.
      - `test_verify_source_belongs_to_project_rejects_mismatched_project`: Rejects source belonging to a different project with `ResourceMismatchError`.
      - `test_verify_source_belongs_to_project_rejects_missing_source`: Rejects missing source with `ResourceMismatchError`.
      - `test_verify_source_belongs_to_project_accepts_verified_context`: Verifies `OwnedProjectContext` reuse avoiding redundant project lookup.
      - `test_verify_source_belongs_to_project_rejects_mismatched_context`: Rejects pre-verified context belonging to a different project.
      - `test_verify_source_belongs_to_project_rejects_missing_identity`: Rejects missing or invalid identity (`user_id=None` or string) with `TypeError`.
      - `test_verify_evidence_belongs_to_project_success`: Validates evidence in target project.
      - `test_verify_evidence_belongs_to_project_rejects_mismatch`: Rejects mismatched evidence record with `ResourceMismatchError`.
      - `test_verify_extraction_run_belongs_to_project_success_and_mismatch`: Validates matching and mismatched extraction runs.
      - `test_verify_source_claim_belongs_to_project_success_and_mismatch`: Validates matching and mismatched source claims.
    - **Group 4: FastAPI get_owned_project Dependency & IDOR Protection Tests (4 tests)**:
      - `test_get_owned_project_dependency_authorized_user`: Verifies valid owner yields `OwnedProjectContext`.
      - `test_get_owned_project_dependency_masks_foreign_project_as_404`: Verifies foreign-owned project returns generic HTTP 404 (preventing existence leaks).
      - `test_get_owned_project_dependency_masks_ownerless_project_as_404`: Verifies unowned project returns generic HTTP 404.
      - `test_get_owned_project_dependency_nonexistent_returns_404`: Verifies nonexistent project returns generic HTTP 404 with identical error payload.
    - **Group 5: Service-Layer Ownership Enforcement & Fail-Closed Guards (4 tests)**:
      - `test_web_source_service_ownership_enforcement`: Verifies `WebSourceIngestionService` validates project ownership inside transactional workflow.
      - `test_pdf_source_service_ownership_enforcement`: Verifies `PDFSourceIngestionService` validates project ownership before parsing PDF content.
      - `test_evidence_persistence_service_ownership_enforcement`: Verifies `EvidencePersistenceService` validates project ownership inside transaction block.
      - `test_services_reject_missing_or_invalid_user_id`: Verifies all domain service methods reject missing or non-UUID `user_id` with `TypeError`.
- **Full Backend Regression Suite Run**:
  - Command: `python -m pytest backend/tests -q`
  - Collected: 447 tests
  - Passed: 447 tests (100%)
  - Failed: 0
  - Execution Duration: 15.22s
- **Frontend Regression Suite Run**:
  - Command: `npm.cmd --prefix frontend test -- --run`
  - Collected: 52 tests
  - Passed: 52 tests (100%)
  - Failed: 0
  - Execution Duration: 8.05s

### 4.8 Phase D3 Protected API Route Integration & Ownership Enforcement Test Results
- **Dedicated Route Ownership Test Suite (`backend/tests/test_route_ownership.py`)**:
  - Command: `python -m pytest backend/tests/test_route_ownership.py -v`
  - Collected: 25 tests
  - Passed: 25 tests (100%)
  - Failed: 0
  - Execution Duration: 1.12s
  - Coverage by Verification Group:
    - **Group 1: Project Ownership & Generic 404 Masking (5 tests)**:
      - `test_owner_accesses_own_project_successfully`: Owner (User A) accesses own project resources (HTTP 200).
      - `test_foreign_user_receives_generic_404_on_project_access`: Foreign user (User B) accessing Project A receives generic 404 without leaking existence.
      - `test_ownerless_project_receives_identical_generic_404`: Ownerless legacy project returns identical generic 404.
      - `test_soft_deleted_project_receives_identical_generic_404`: Soft-deleted project returns identical generic 404.
      - `test_nonexistent_project_receives_identical_generic_404`: Nonexistent project returns identical generic 404.
    - **Group 2: Source Endpoints Access Control (5 tests)**:
      - `test_owner_can_ingest_web_source_foreign_user_blocked`: POST web source (Owner 201; Foreign User 404).
      - `test_owner_can_ingest_pdf_foreign_user_blocked`: POST pdf source (Owner 201; Foreign User 404).
      - `test_owner_can_list_sources_foreign_user_blocked`: GET sources (Owner 200; Foreign User 404).
      - `test_owner_can_get_source_detail_foreign_user_blocked`: GET source detail (Owner 200; Foreign User 404).
      - `test_owner_can_extract_evidence_foreign_user_blocked`: POST extract (Owner 200; Foreign User 404).
    - **Group 3: Evidence & Extraction Run Endpoints Access Control (5 tests)**:
      - `test_owner_can_persist_evidence_foreign_user_blocked`: POST persist (Owner 201; Foreign User 404).
      - `test_owner_can_get_source_evidence_foreign_user_blocked`: GET source evidence (Owner 200; Foreign User 404).
      - `test_owner_can_get_project_evidence_foreign_user_blocked`: GET project evidence (Owner 200; Foreign User 404).
      - `test_owner_can_list_extraction_runs_foreign_user_blocked`: GET extraction runs (Owner 200; Foreign User 404).
      - `test_owner_can_get_extraction_run_detail_foreign_user_blocked`: GET extraction run detail (Owner 200; Foreign User 404).
    - **Group 4: Child-Resource Cross-Project IDOR Substitution (5 tests)**:
      - `test_cross_project_source_access_returns_404`: Accessing Source B under Project A returns generic 404.
      - `test_cross_project_source_evidence_returns_404`: Querying evidence for Source B under Project A returns generic 404.
      - `test_cross_project_extraction_runs_returns_404`: Querying runs for Source B under Project A returns generic 404.
      - `test_cross_project_extraction_run_detail_returns_404`: Querying Run B under Project A returns generic 404.
      - `test_cross_project_persist_attempt_returns_404`: Persisting evidence for Source B under Project A returns generic 404.
    - **Group 5: Background Task Identity Preservation (1 test)**:
      - `test_extract_endpoint_automatic_persistence_preserves_owner_identity`: Automatic persistence strictly binds `user_id` from cryptographically verified token.
    - **Group 6: Security Regressions & Public Routes (4 tests)**:
      - `test_unauthenticated_request_rejected_with_401`: Missing token returns 401.
      - `test_malformed_bearer_token_rejected_with_401`: Malformed token returns 401.
      - `test_public_health_remains_accessible`: GET `/api/v1/health` returns 200.
      - `test_public_web_extract_remains_accessible`: POST `/api/v1/web/extract` returns 200.
- **Full Backend Pytest Suite Run**:
  - Command: `python -m pytest backend/tests -q`
  - Collected: 472 tests
  - Passed: 472 tests (100%)
  - Failed: 0
  - Execution Duration: 17.12s
- **Frontend Vitest Suite Run**:
  - Command: `npm.cmd --prefix frontend test -- --run`
  - Collected: 52 tests across 4 suites
  - Passed: 52 tests (100%)
  - Failed: 0
  - Execution Duration: 9.18s
- **Total Stack Test Count**: 524 automated tests passing (52 frontend + 472 backend).

### 4.9 Phase D4 Ownership Regression & Penetration Audit Test Results
- **Penetration Test Suite (`backend/tests/test_ownership_penetration.py` — 17 tests)**:
  - Command: `python -m pytest backend/tests/test_ownership_penetration.py -v`
  - Collected: 17 tests
  - Passed: 17 tests (100%)
  - Failed: 0
  - Execution Duration: 0.56s
  - Coverage by Verification Group:
    - **Group 1: Side-Effect Isolation (4 tests)**:
      - `test_unauthorized_web_ingestion_has_zero_side_effects`: 0 web fetches, 0 DB writes.
      - `test_unauthorized_pdf_ingestion_has_zero_side_effects`: 0 PDF parses, 0 DB writes.
      - `test_unauthorized_extraction_has_zero_ai_or_persistence_side_effects`: 0 AI completion calls, 0 persistence calls.
      - `test_unauthorized_persistence_has_zero_database_side_effects`: 0 persistence calls.
    - **Group 2: Identity Spoofing & Parameter Tampering Immunity (3 tests)**:
      - `test_request_body_cannot_override_authenticated_identity`: JSON body `user_id` injection rejected with 404.
      - `test_query_parameter_cannot_override_authenticated_identity`: URL query `?user_id=...` parameter ignored.
      - `test_extract_endpoint_spoofed_body_identity_is_ignored`: Body identity injection on extract rejected with 404.
    - **Group 3: Cryptographic Token Regressions (5 tests)**:
      - `test_token_with_wrong_issuer_rejected_with_401`: Rejected with HTTP 401.
      - `test_token_with_wrong_audience_rejected_with_401`: Rejected with HTTP 401.
      - `test_token_with_expired_timestamp_rejected_with_401`: Rejected with HTTP 401 and invalid_token error.
      - `test_token_with_invalid_user_uuid_rejected_with_401`: Rejected with HTTP 401.
      - `test_token_with_untrusted_signature_rejected_with_401`: Rejected with HTTP 401.
    - **Group 4: Service-Layer Direct Bypass Audit (3 tests)**:
      - `test_direct_service_call_rejects_missing_identity`: Missing user_id raises TypeError across all domain services.
      - `test_direct_service_call_enforces_project_ownership_within_connection`: Service validation fails closed within connection.
      - `test_child_resource_helper_rejects_forged_project_context`: Mismatched OwnedProjectContext raises ResourceMismatchError.
    - **Group 5: Generic 404 Uniformity & IDOR Masking (2 tests)**:
      - `test_generic_404_response_exact_uniformity`: Identical response structure across foreign, unowned, deleted, and nonexistent projects.
      - `test_invalid_uuid_returns_422_without_leaking_data`: Non-UUID in path returns HTTP 422.
- **Full Backend Pytest Suite Run**:
  - Command: `python -m pytest backend/tests -q`
  - Collected: 489 tests
  - Passed: 489 tests (100%)
  - Failed: 0
  - Execution Duration: 18.82s
- **Frontend Vitest Suite Run**:
  - Command: `npm.cmd --prefix frontend test -- --run`
  - Collected: 52 tests across 4 suites
  - Passed: 52 tests (100%)
  - Failed: 0
  - Execution Duration: 9.87s
- **Total Stack Test Count**: 541 automated tests passing (52 frontend + 489 backend).

### 4.10 Step 10B Information Gap Detection Pydantic Schemas & Prompt Templates Test Results
- **Schema Test Suite (`backend/tests/test_gap_schemas.py` — 51 tests)**:
  - Command: `python -m pytest backend/tests/test_gap_schemas.py -v`
  - Collected: 51 tests
  - Passed: 51 tests (100%)
  - Failed: 0
  - Execution Duration: 0.12s
  - Coverage:
    - Controlled enums (`GapType`, `GapPriority`, `GapStatus`, `GapSubtype`, `GapReviewStatus`) matching database check constraints.
    - `AIGapCandidatePayload`: boundary tests for `candidate_id` (1-100), `confidence_score` (0.0-1.0), non-finite rejection (NaN, +inf, -inf), required string non-emptiness and whitespace stripping, optional field stripping, extra field rejection (`extra="forbid"`), and immutability (`frozen=True`).
    - `AIGapDetectionPayload`: unique `candidate_id` enforcement, empty gaps list handling, summary non-emptiness, max candidate limits (<= 50), and extra field rejection.
    - `ValidatedGapFinding`: allowed validation verdicts (`confirmed`, `partially_covered`, `disputed_by_evidence`, `redundant`), invalid verdict rejection, non-negative fact counts, covered evidence UUID tracking, and extra field rejection.
    - `InformationGapResponse`: persisted entity schema matching `public.information_gaps` with UUIDs and timestamp integrity.
    - `GapReviewUpdate`: review status restrictions (`investigating`, `resolved`, `dismissed`), strict rejection of illegal rollback to `open`, optional non-empty user notes, and extra field rejection.
    - `GapDetectionResult`: service execution envelope with UTC timestamps and non-negative counts.
- **Prompt Template Test Suite (`backend/tests/test_gap_templates.py` — 19 tests)**:
  - Command: `python -m pytest backend/tests/test_gap_templates.py -v`
  - Collected: 19 tests
  - Passed: 19 tests (100%)
  - Failed: 0
  - Execution Duration: 0.06s
  - Coverage:
    - Static templates: task header with product branding, epistemic grounding rules (absence $\ne$ falsehood), all taxonomy enum values, priority rubric, injection defenses, and JSON contract.
    - Dynamic truncation notices: `build_gap_truncation_notice` returns `None` when untruncated, injects character counts on truncation, and reports source omissions with partial-corpus warnings.
    - Task prompt assembly: `build_gap_detection_prompt` incorporates research question, existing topics, custom directives, and truncation notices. Rejects empty research questions.
    - High-level coordinator: `assemble_gap_detection_prompt` integrates with `PromptBuilder`, generating `SECURITY_SYSTEM_PROMPT` in system turn, fenced sources in user turn, and structured truncation metadata. Compatible with dictionary and `SourceDocument` inputs.
- **Combined Step 10B Test Execution**:
  - `python -m pytest backend/tests/test_gap_schemas.py backend/tests/test_gap_templates.py -v`: 70 / 70 passed in 0.18s.
- **Full Backend Pytest Suite Run**:
  - Command: `python -m pytest backend/tests -q`
  - Collected: 559 tests
  - Passed: 559 tests (100%)
  - Failed: 0
  - Execution Duration: 17.71s
- **Frontend Vitest Suite Run**:
  - Command: `npm.cmd --prefix frontend test -- --run`
  - Collected: 52 tests across 4 suites
  - Passed: 52 tests (100%)
  - Failed: 0
  - Execution Duration: 8.68s
- **Total Stack Test Count**: 611 automated tests passing (52 frontend + 559 backend).

### 4.11 Step 10C Information Gap Detection Service & Validation Pipeline Test Results
- **Gap Detection Service Test Suite (`backend/tests/test_gap_detection_service.py` — 36 tests)**:
  - Command: `python -m pytest backend/tests/test_gap_detection_service.py -v`
  - Collected: 36 tests
  - Passed: 36 tests (100%)
  - Failed: 0
  - Execution Duration: 0.32s
  - Coverage:
    - **Group 1: Ownership & Security (8 tests)**:
      - Valid owner initiates detection; missing user ID raises `TypeError`; invalid user ID / project ID raises `TypeError`.
      - Foreign project access returns generic `ProjectNotFoundError` (HTTP 404 IDOR masking).
      - Deleted/unowned projects return `ProjectNotFoundError`.
      - Zero AI completion calls occur prior to ownership validation (side-effect isolation).
      - AI completion output cannot spoof user or project identity.
    - **Group 2: Evidence Retrieval & Corpus Bounds (6 tests)**:
      - Research question loaded and validated (rejects < 10 characters with `ValueError`).
      - Distinguishes extracted source statements from unverified source claims in prompt text.
      - Preserves topic taxonomy associations.
      - Empty corpus (0 sources) returns diagnostic without AI call.
      - Failed extractions (all sources failed) return diagnostic distinguishing failure from genuine gaps.
      - Sources with 0 facts/claims return diagnostic without AI call.
    - **Group 3: Candidate Grounding & Anti-Hallucination (6 tests)**:
      - Unaddressed candidate with 0 matching statements produces verdict `confirmed`.
      - Candidate with matching topic produces `partially_covered`.
      - Candidate declaring `no_evidence` when multiple concrete statements exist produces `disputed_by_evidence`.
      - Duplicate candidate targeting the same subquestion produces verdict `redundant`.
      - Superficial single-keyword overlap does not falsely dispute a gap.
      - Unknown or foreign evidence IDs are filtered out from `covered_evidence_ids`.
    - **Group 4: Truncation & Omission Transparency (3 tests)**:
      - Character truncation produces `corpus_truncation_warning=True` on findings and top-level result.
      - Capping above 20 sources produces source omission warnings and partial corpus cautions.
    - **Group 5: Provider Resilience & Read-Only Safety (13 tests)**:
      - Provider errors (`AITimeoutError`, `AIRateLimitError`, `AIProviderUnavailableError`, `AIAuthenticationError`) propagate without conversion to false empty success.
      - Malformed or invalid JSON raises `AIResponseValidationError`.
      - Zero database mutations occur during detection (`mock_conn.execute.call_count == 0`).

### 4.12 Step 10C.1 Evidence Grounding Validation Remediation Test Results
- **Gap Detection Remediation Test Suite (`backend/tests/test_gap_detection_service.py` — 46 tests total)**:
  - Command: `python -m pytest backend/tests/test_gap_detection_service.py -v`
  - Collected: 46 tests
  - Passed: 46 tests (100%)
  - Failed: 0
  - Execution Duration: 0.49s
  - Coverage (10 Dedicated Remediation Tests in `TestEvidenceGroundingRemediation`):
    - `test_remediation_multiple_shared_keywords_not_automatic_coverage`: Packaging shipping costs in a solar project do not falsely dispute a solar panel recycling/disposal gap.
    - `test_remediation_different_wording_same_concept_recognized`: "Financial assistance" recognizes "subsidies" and "grants" via canonical concept clustering.
    - `test_remediation_zero_lexical_overlap_scope_transparency`: Grounding notes explicitly scope absence to analyzed corpus.
    - `test_remediation_topic_association_alone_does_not_prove_coverage`: Topic association alone yields `partially_covered`, never `disputed_by_evidence`.
    - `test_remediation_partial_question_coverage_yields_partially_covered`: Answering one facet of a multi-part question yields `partially_covered`.
    - `test_remediation_source_assertion_not_treated_as_verified_truth`: Prompt headers and notes accurately describe source statements.
    - `test_remediation_genuine_missing_information_confirmed`: Complete absence produces confirmed finding.
    - `test_remediation_uncertain_cases_retain_explanatory_notes`: Preserves candidates with transparent reasoning.
    - `test_remediation_cross_project_evidence_isolation_intact`: Parameterized queries and 404 IDOR masking prevent cross-tenant leakage.
    - `test_remediation_truncation_and_omission_warnings_intact`: Truncation and source omissions propagate transparent notices.
- **Full Backend Pytest Suite Run**:
  - Command: `python -m pytest backend/tests -q`
  - Collected: 605 tests
  - Passed: 605 tests (100%)
  - Failed: 0
  - Execution Duration: 18.37s
- **Frontend Vitest Suite Run**:
  - Command: `npm.cmd --prefix frontend test -- --run`
  - Collected: 52 tests across 4 suites
  - Passed: 52 tests (100%)
  - Failed: 0
  - Execution Duration: 9.46s
- **Total Stack Test Count**: 657 automated tests passing (52 frontend + 605 backend).

### 4.13 Step 10D.1 Information Gap Database Persistence & Idempotency Test Results
- **Gap Persistence Test Suite (`backend/tests/test_gap_persistence_service.py` — 44 tests total)**:
  - Command: `python -m pytest backend/tests/test_gap_persistence_service.py -v`
  - Collected: 44 tests
  - Passed: 44 tests (100%)
  - Failed: 0
  - Execution Duration: 0.27s
  - Coverage by Category:
    - **Ownership & Security (13 tests)**:
      - Valid project owner can persist findings; foreign-owned or soft-deleted projects rejected with generic 404 (`ProjectNotFoundError`).
      - Non-UUID `user_id` / `project_id` (None, strings, ints) raise `TypeError` failing closed.
      - Zero database writes occur before caller ownership is verified.
      - Foreign gap UUID cannot be retrieved or updated by a non-owner.
    - **Database Mapping & Topic/Evidence Verification (6 tests)**:
      - `ValidatedGapFinding` fields accurately mapped to `public.information_gaps` columns.
      - Namespaced `confidence_metadata->'bharmafills'` structure validated.
      - Unmatched topic names safely produce `topic_id = NULL`.
      - Scoped topic lookup queries `public.topics WHERE project_id = $1`, enforcing project isolation and safely setting `topic_id = NULL` for topics from foreign projects or unknown names.
      - Foreign or unmatched evidence UUIDs are stripped from `covered_evidence_ids`.
      - AI confidence explicitly labeled as model output without claiming empirical certainty.
    - **Idempotency & Concurrent Reruns (9 tests)**:
      - SHA-256 fingerprint generation is deterministic across whitespace/casing normalization.
      - Identical findings execute an in-place `UPDATE`, preserving row UUID and creation timestamps.
      - User review statuses (`investigating`, `resolved`, `dismissed`) are preserved across reruns.
      - User review notes and unknown external JSONB keys are preserved across reruns.
      - Unseen prior findings remain intact and are not automatically deleted.
      - PostgreSQL advisory locking (`pg_advisory_xact_lock`) serializes parallel runs on the same project.
    - **User Review Lifecycle Updates (6 tests)**:
      - Transitions to allowed statuses (`investigating`, `resolved`, `dismissed`) succeed.
      - Rollbacks to `open` or arbitrary statuses are rejected by schema validation.
      - User review notes are length-limited to 2,000 characters.
      - Review updates modify only `status`, `user_review`, and `updated_at`; AI detection fields remain immutable.
      - Nonexistent gap updates raise `GapNotFoundError`.
      - Omitted review notes preserve pre-existing notes.
    - **Retrieval, Pagination & Transaction Safety (10 tests)**:
      - Project gap listing strictly scoped to project boundary.
      - Filtering by status, priority, and gap type passes correct SQL parameters.
      - Single gap retrieval requires both `id` and `project_id`.
      - Nonexistent gap retrieval raises `GapNotFoundError`.
      - Pagination limits and offsets clamped safely (1 to 200).
      - Database failures during batch persistence trigger rollback and raise `GapTransactionError`.
      - Empty detection results handled gracefully (0 persisted, 0 inserted, 0 updated).
      - `verify_gap_belongs_to_project` helper validated for matching and mismatched gaps.
      - Singleton instance caching verified.
- **Full Backend Pytest Suite Run**:
  - Command: `python -m pytest backend/tests -q`
  - Collected: 649 tests
  - Passed: 649 tests (100%)
  - Failed: 0
  - Execution Duration: 19.85s
- **Frontend Vitest Suite Run**:
  - Command: `npm.cmd --prefix frontend test -- --run`
  - Collected: 52 tests across 4 suites
  - Passed: 52 tests (100%)
  - Failed: 0
  - Execution Duration: 9.39s
- **Total Stack Test Count**: 701 automated tests passing (52 frontend + 649 backend).

### 4.14 Step 10D.2 Protected Information Gap API Route Test Results
- **Gap API Routes Test Suite (`backend/tests/test_gap_routes.py` — 41 tests total)**:
  - Command: `python -m pytest backend/tests/test_gap_routes.py -v`
  - Collected: 41 tests
  - Passed: 41 tests (100%)
  - Failed: 0
  - Execution Duration: 2.77s
  - Coverage by Category:
    - **Authentication & Headers (2 tests)**:
      - Requests lacking `Authorization` header return HTTP 401 with `WWW-Authenticate: Bearer` challenge.
      - Requests with malformed or invalid Bearer tokens return HTTP 401 with proper challenge header.
    - **Ownership & IDOR Masking (9 tests)**:
      - Project owner successfully triggers `/detect` and `/gaps` endpoints.
      - Requesting another user's project returns generic HTTP 404 (`"Research project not found."`).
      - Requesting nonexistent or soft-deleted projects returns generic HTTP 404 with identical payload structure.
      - Identity spoofing via query parameters (`?user_id=...`) or body fields is ignored/rejected; caller context remains bound to authenticated token.
      - Requesting a gap ID belonging to a foreign project or nonexistent gap returns generic HTTP 404 (`"Information gap '{gap_id}' was not found in research project '{project_id}'."`).
      - Child-resource error catch order verifies `GapNotFoundError` precedes `ProjectNotFoundError`.
    - **Detection Endpoint Execution & Mapping (11 tests)**:
      - Successful gap detection persists findings and returns combined envelope (`GapDetectionAndPersistenceResponse`).
      - Diagnostic envelopes from empty/failed corpora are handled and persisted with 0 findings.
      - Truncation and source omission warnings propagate faithfully.
      - Custom instructions payload handled correctly; extra unexpected fields rejected with HTTP 422.
      - OpenRouter exception mappings verified: `AITimeoutError` (504 Gateway Timeout), `AIRateLimitError` (429 Too Many Requests with `Retry-After`), `AIQuotaExceededError` (503 Service Unavailable), `AIAuthenticationError` (502 Bad Gateway), `AIResponseValidationError` (502 Bad Gateway), `AIProviderError` (502 Bad Gateway), and `ValueError` (400 Bad Request).
    - **Retrieval & Review Endpoints (12 tests)**:
      - Scoped listing returns project gaps with total counts and pagination limits.
      - Filtering by status, priority, and gap type accurately passes query parameters.
      - Single gap retrieval returns verified gap belonging to project.
      - Review updates allow transitions to `investigating`, `resolved`, `dismissed`.
      - Reverting to `open` or arbitrary string statuses rejected by schema with HTTP 422.
      - Notes length limit (2,000 characters) enforced with HTTP 422.
      - Omitted review notes preserve pre-existing notes without clearing.
    - **Operational Failures & Unhandled Exception Containment (7 tests)**:
      - Unconfigured AI provider returns HTTP 503 (`"AI service is not configured."`).
      - Unconfigured persistence service returns HTTP 503 (`"Gap persistence service is not configured."`).
      - Database unavailable returns HTTP 503 (`"Database service is currently unavailable."`).
      - Persistence transaction failure returns HTTP 500 (`"Failed to persist information gap findings."`).
      - Unhandled exceptions log internal stack trace and return generic RFC 7807 HTTP 500 error without exposing stack traces.
- **Full Backend Pytest Suite Run**:
  - Command: `python -m pytest backend/tests -q`
  - Collected: 690 tests
  - Passed: 690 tests (100%)
  - Failed: 0
  - Execution Duration: 23.72s
- **Frontend Vitest Suite Run**:
  - Command: `npm.cmd --prefix frontend test -- --run`
  - Collected: 52 tests across 4 suites
  - Passed: 52 tests (100%)
  - Failed: 0
  - Execution Duration: 8.94s
- **Total Stack Test Count**: 742 automated tests passing (52 frontend + 690 backend).

---

## 5. Quality Gate & Continuous Integration Checklist

Before committing or releasing any phase:
1. **Frontend Unit Tests**: `npm.cmd test` passes with zero failures (52 tests passing).
2. **Frontend Linting**: `npm.cmd run lint` returns 0 errors and 0 warnings.
3. **Frontend Build**: `npm.cmd run build` completes with exit code 0.
4. **Backend Unit Tests**: `python -m pytest` passes with zero failures (690 tests passing: 339 core + 35 auth + 46 route protection + 27 ownership + 25 route ownership + 17 ownership penetration + 51 gap schemas + 19 gap templates + 46 gap detection service & remediation + 44 gap persistence service + 41 gap API routes).
5. **Live Database Verification**: Live Supabase catalog audit matches migrations `20261031123000` and `20261101120000`.
6. **Total Test Coverage**: 742 automated tests passing across the stack (52 frontend + 690 backend).
7. **Manual Sanity Check**: Verify desktop, tablet, and mobile views in the browser, and verify API health probes.
