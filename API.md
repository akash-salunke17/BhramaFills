# Bharmafills — REST API Specification

> **Document Status**: Proposed Baseline / Target Specification
> **API Version**: `v1`
> **Target Framework**: Python FastAPI
> **Target Base URL**: `http://localhost:8000/api/v1`
> **Current Status**: `PLANNED` (Phase 3 for Extraction; Phase 4 for Core Endpoints)
> **Workspace Identifier**: `Shinchan`

---

## 1. API Conventions & Standards

### 1.1 Transport & Security
- **Protocol**: HTTPS (TLS 1.3 in production; HTTP for local development).
- **Authentication**: JWT Bearer token passed in the `Authorization` header (`Authorization: Bearer <SUPABASE_JWT_TOKEN>`).
  - **Signature Algorithm**: Asymmetric `ES256` (ECDSA with P-256 curve) validated against Supabase's public JWKS endpoint (`/.well-known/jwks.json`), or isolated `HS256` when configured.
  - **Enforcement Scope**: Mandatory on all project-scoped endpoints (`/api/v1/projects/*`). Unauthenticated access returns HTTP 401 with standard `WWW-Authenticate: Bearer` headers.
  - **Public Endpoints**: System health probes (`/api/v1/health`, `/api/v1/health/database`, `/api/v1/health/ai`), OpenAPI documentation (`/docs`, `/redoc`, `/openapi.json`), and general utility scrapers (`/api/v1/web/extract`) remain publicly accessible without credentials.
- **Media Type**: `application/json` (unless handling binary uploads where `multipart/form-data` is required).
- **CORS**: Restricted to explicitly configured frontend origins (`http://localhost:5173` in development).

### 1.2 Common Error Response Format (RFC 7807 Standard)
All 4xx and 5xx responses conform to a unified error schema. For authentication errors:
- **HTTP 401 Unauthorized (Missing Header)**:
  - Header: `WWW-Authenticate: Bearer`
  - Body: `{"detail": "Missing Authorization header. Provide a valid Bearer token."}`
- **HTTP 401 Unauthorized (Invalid or Expired Token)**:
  - Header: `WWW-Authenticate: Bearer error="invalid_token", error_description="Invalid or unauthorized authentication token"`
  - Body: `{"detail": "Invalid or unauthorized authentication token"}`

### 1.3 Project Ownership & IDOR Protection (Phase D Implementation)
- **Ownership Invariant**: All project resources require `research_projects.user_id == authenticated_user.id`.
- **Information Disclosure & IDOR Prevention**: When an authenticated caller accesses a project ID that either does not exist, has been soft-deleted, is unowned (`user_id IS NULL`), or belongs to another user (`user_id != caller.id`), the API responds with an identical generic HTTP 404:
  - **Status Code**: `HTTP 404 Not Found`
  - **Body**: `{"detail": "Research project '<project_id>' was not found."}`
- **Child Resource Masking**: If a child resource (e.g. source, extraction run, evidence) does not belong to the requested project, the API responds with generic HTTP 404 (`{"detail": "Source '<source_id>' was not found in research project '<project_id>'."}`) without disclosing foreign project UUIDs or cross-tenant resource existence.
- **Security Invariant**: Differentiating between 403 Forbidden (for existing foreign projects) and 404 Not Found (for nonexistent projects) would allow an attacker to enumerate valid project UUIDs across tenants. The unified 404 response completely closes this existence disclosure vector.
- **Implementation Status**: Reusable foundation module (`backend/app/core/ownership.py`) implemented in Phase D2, hardened in Phase D2.1, fully integrated into all 10 project API routes in Phase D3 (`OwnedProjectContext = Depends(get_owned_project)`), and rigorously audited via penetration testing in Phase D4 (42 dedicated ownership tests passing, 489 total backend tests). Side-effect isolation and query/body identity spoofing immunity verified.

For validation and domain exceptions:

```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "The research project payload contained invalid fields.",
    "status": 422,
    "timestamp": "2026-10-31T12:00:00Z",
    "details": [
      {
        "field": "title",
        "issue": "Title must be between 3 and 150 characters."
      }
    ]
  }
}
```

### 1.3 Pagination Format
List endpoints support `page` (1-indexed) and `page_size` query parameters:

```json
{
  "data": [],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_count": 45,
    "total_pages": 3,
    "has_next": true,
    "has_prev": false
  }
}
```

---

## 2. API Endpoint Directory

```
├── Health & System
│   ├── GET  /api/v1/health                     # Quick process liveness probe
│   ├── GET  /api/v1/health/database            # Supabase PostgreSQL connectivity probe
│   └── GET  /api/v1/health/ready               # Readiness probe (DB + Gemini ping)
├── Authentication
│   └── GET  /api/v1/auth/me                    # Current authenticated user details
├── Research Projects
│   ├── GET  /api/v1/projects                   # List research projects
│   ├── POST /api/v1/projects                   # Create a new research project
│   ├── GET  /api/v1/projects/{id}              # Get project details & statistics
│   ├── PATCH /api/v1/projects/{id}             # Update project metadata
│   └── DELETE /api/v1/projects/{id}            # Soft delete a project
├── Sources Management & Ingestion [PROTECTED - Phase D3: Ownership Enforced]
│   ├── POST /api/v1/projects/{project_id}/sources/web  # Ingest & persist web URL to Supabase (IMPLEMENTED - Step 7B, Phase D3 Ownership Enforced)
│   ├── POST /api/v1/projects/{project_id}/sources/pdf  # Upload & extract PDF source (IMPLEMENTED - Step 8, Phase D3 Ownership Enforced)
│   ├── GET  /api/v1/projects/{project_id}/sources      # List sources attached to a project (IMPLEMENTED - Step 7B, Phase D3 Ownership Enforced)
│   ├── GET  /api/v1/projects/{project_id}/sources/{source_id} # Detailed source & clean text (IMPLEMENTED - Step 7B, Phase D3 Ownership Enforced)
│   ├── POST /api/v1/projects/{project_id}/sources/{source_id}/extract # Extract structured facts & claims using AI (IMPLEMENTED - Step 9B.2.2B, Phase D3 Ownership Enforced)
│   └── DELETE /api/v1/sources/{source_id}              # Remove a source (PLANNED)
├── Extraction Pipeline
│   ├── POST /api/v1/web/extract                # SSRF-safe web fetching & BeautifulSoup content extraction (IMPLEMENTED - Step 7A, Public)
│   ├── POST /api/v1/extract/url                # Scrape & persist project web source (Planned Step 7B)
│   ├── POST /api/v1/extract/pdf                # Parse & clean uploaded PDF file (Planned Step 8)
│   └── GET  /api/v1/extract/status/{job_id}    # Check background extraction status
├── Evidence & Persistence [PROTECTED - Phase D3: Ownership Enforced]
│   ├── POST /api/v1/projects/{project_id}/sources/{source_id}/persist # Persist extracted evidence & claims to Supabase (IMPLEMENTED - Step 9B.3, Phase D3 Ownership Enforced)
│   ├── GET  /api/v1/projects/{project_id}/sources/{source_id}/evidence # Retrieve facts & claims for a specific source (IMPLEMENTED - Step 9B.3, Phase D3 Ownership Enforced)
│   ├── GET  /api/v1/projects/{project_id}/evidence                     # Retrieve all project facts & claims (IMPLEMENTED - Step 9B.3, Phase D3 Ownership Enforced)
│   ├── GET  /api/v1/projects/{project_id}/sources/{source_id}/extraction-runs # List extraction runs for a source (IMPLEMENTED - Step 9B.3, Phase D3 Ownership Enforced)
│   └── GET  /api/v1/projects/{project_id}/extraction-runs/{run_id}     # Detailed extraction run report (IMPLEMENTED - Step 9B.3, Phase D3 Ownership Enforced)
├── AI Information Gap Detection [PROTECTED - Step 10D.2: Implemented & Tested]
│   ├── POST /api/v1/projects/{project_id}/gaps/detect # Trigger AI gap analysis across project evidence & persist (IMPLEMENTED - Step 10D.2, Protected)
│   ├── GET  /api/v1/projects/{project_id}/gaps        # List detected information gaps with filters & pagination (IMPLEMENTED - Step 10D.2, Protected)
│   ├── GET  /api/v1/projects/{project_id}/gaps/{gap_id} # Detailed information gap report (IMPLEMENTED - Step 10D.2, Protected)
│   └── PATCH /api/v1/projects/{project_id}/gaps/{gap_id} # Update gap workflow review status & notes (IMPLEMENTED - Step 10D.2, Protected)
├── Cross-Source Conflict Detection [PLANNED - Step 11]
│   └── GET  /api/v1/projects/{project_id}/conflicts   # List detected conflicting claims (PLANNED - Step 11)
└── Verification Checklist
    ├── GET  /api/v1/projects/{id}/checklist    # Get generated verification checklist
    ├── POST /api/v1/projects/{id}/checklist    # Add manual checklist item
    └── PATCH /api/v1/checklist/{item_id}       # Update checklist item status
```

---

## 3. Endpoint Specifications

### 3.1 Health & Diagnostics

#### `GET /api/v1/health`
- **Description**: Lightweight health check verifying the running FastAPI process. Truthful probe that does not claim external services (DB, AI, scrapers) are operational.
- **Status**: `IMPLEMENTED & TESTED` (Step 5A)
- **Response `200 OK`**:
```json
{
  "status": "ok",
  "service": "Bharmafills API",
  "version": "0.1.0"
}
```

#### `GET /api/v1/health/database`
- **Description**: Dedicated connectivity probe verifying Supabase PostgreSQL database reachability via the Session Pooler. Truthful probe that does not leak hostnames, passwords, or stack traces.
- **Status**: `IMPLEMENTED & TESTED` (Step 6A)
- **Response `200 OK` (Configured & Connected)**:
```json
{
  "status": "ok",
  "database": "connected"
}
```
- **Response `200 OK` (Not Configured)**:
```json
{
  "status": "not_configured",
  "database": "not_configured"
}
```
- **Response `503 Service Unavailable` (Configured but Unreachable)**:
```json
{
  "status": "error",
  "database": "unavailable"
}
```

#### `GET /api/v1/health/ai`
- **Description**: Inspects active AI integration configuration (OpenRouter + NVIDIA Nemotron 3 Ultra). Returns configuration state, active model, and model tier privacy warnings. Does not perform automatic network calls or consume API quota during probing.
- **Status**: `IMPLEMENTED & TESTED` (Step 9A)
- **Response `200 OK` (Configured)**:
```json
{
  "status": "configured",
  "provider": "openrouter",
  "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
  "base_url": "https://openrouter.ai/api/v1",
  "is_free_tier": true,
  "privacy_warning": "Free tier model endpoint active. NEVER transmit confidential, proprietary, or personally identifiable data (PII) to this model.",
  "masked_api_key": "sk-o...1234"
}
```
- **Response `200 OK` (Not Configured)**:
```json
{
  "status": "not_configured",
  "provider": "openrouter",
  "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
  "base_url": "https://openrouter.ai/api/v1",
  "is_free_tier": true,
  "privacy_warning": "Free tier model endpoint active. NEVER transmit confidential, proprietary, or personally identifiable data (PII) to this model.",
  "masked_api_key": null
}
```

#### `GET /api/v1/health/ready`
- **Description**: Deep readiness probe verifying database connectivity and external service availability.
- **Status**: `PLANNED` (Step 6+)
- **Response `200 OK`**:
```json
{
  "status": "ready",
  "database": "connected",
  "timestamp": "2026-10-31T12:00:00Z"
}
```

---

### 3.2 Research Projects

#### `GET /api/v1/projects`
- **Description**: Returns paginated list of projects belonging to the authenticated user.
- **Query Parameters**:
  - `page` (int, default: 1)
  - `page_size` (int, default: 20)
  - `search` (string, optional)
  - `status` (string, optional: `active`, `in_progress`, `completed`, `archived`)
- **Status**: `PLANNED`
- **Response `200 OK`**:
```json
{
  "data": [
    {
      "id": "e3a89047-9204-4b53-99b3-467812f8a421",
      "title": "National Scholarship Eligibility Audit 2026",
      "research_question": "What are the income thresholds and verification deadlines across state portals?",
      "description": "Comparative audit of NSP vs Maharashtra State DBT portals.",
      "status": "active",
      "tags": ["scholarship", "education", "compliance"],
      "source_count": 4,
      "gap_count": 2,
      "conflict_count": 1,
      "created_at": "2026-10-31T10:15:00Z",
      "updated_at": "2026-10-31T11:45:00Z"
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_count": 1,
    "total_pages": 1,
    "has_next": false,
    "has_prev": false
  }
}
```

#### `POST /api/v1/projects`
- **Description**: Creates a new research project.
- **Status**: `PLANNED`
- **Request Body**:
```json
{
  "title": "Clean Energy Grid Expansion",
  "research_question": "What transmission bottlenecks are identified in the 2026 energy roadmaps?",
  "description": "Cross-verifying CEA reports and state transmission whitepapers.",
  "tags": ["energy", "policy"]
}
```
- **Response `201 Created`**: Returns the newly created project record.

---

### 3.3 Extraction Pipeline

#### `POST /api/v1/web/extract`
- **Description**: Secure URL fetching and readable text extraction service. Implements strict SSRF protection, DNS pinning (eliminating rebinding TOCTOU gaps), manual redirect validation (max 5 hops, no downgrade, loop detection), streaming size caps (2 MB), content-type verification (`text/html`, `application/xhtml+xml`), and BeautifulSoup text extraction.
- **Status**: `IMPLEMENTED & TESTED` (Step 7A)
- **Request Body**:
```json
{
  "url": "https://example.org/articles/quantum-computing"
}
```
- **Response `200 OK`**:
```json
{
  "url": "https://example.org/articles/quantum-computing",
  "final_url": "https://example.org/articles/quantum-computing",
  "status_code": 200,
  "title": "Quantum Computing Breakthrough Announced in 2026",
  "meta_description": "Researchers announced a major advance in fault-tolerant quantum computing architectures.",
  "author": "Dr. Jane Doe",
  "language": "en",
  "canonical_url": "https://example.org/articles/quantum-computing",
  "clean_text": "A collaborative research group announced a major advance in quantum error correction...",
  "headings": [
    { "level": 1, "text": "Quantum Computing Breakthrough Announced in 2026" },
    { "level": 2, "text": "Hardware Architecture and Logical Qubits" }
  ],
  "paragraphs": [
    "A collaborative research group announced a major advance in quantum error correction...",
    "The team successfully demonstrated 100 logical qubits operating under fault-tolerant thresholds..."
  ],
  "word_count": 420,
  "character_count": 2850,
  "content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "redirect_count": 0,
  "extracted_at": "2026-10-31T12:40:00Z"
}
```
- **Error Responses**:
  - `400 Bad Request`: Prohibited SSRF address (loopback, private IPv4/IPv6, cloud metadata), invalid URL syntax, unsupported ports, or unsafe redirects.
  - `413 Payload Too Large`: Response body exceeded maximum allowed size of 2 MB.
  - `422 Unprocessable Entity`: Target Content-Type is not supported HTML/XHTML (e.g. PDF, image, audio).
  - `502 Bad Gateway`: Upstream remote host refused connection or network error occurred.
  - `504 Gateway Timeout`: Connection or read timeout exceeded.

#### `POST /api/v1/projects/{project_id}/sources/web`
- **Description**: Ingests, fetches, extracts, and persists a web source and its clean text into Supabase PostgreSQL for a specific research project. Enforces SSRF defense, streaming caps, BeautifulSoup content parsing, duplicate detection (by URL or content hash within project), and atomic transactions across `sources` and `extracted_content`.
- **Status**: `IMPLEMENTED & TESTED` (Step 7B)
- **Path Parameters**:
  - `project_id`: `UUID` (Required, identifier of target research project)
- **Request Body**:
```json
{
  "url": "https://en.wikipedia.org/wiki/Information_gap_task"
}
```
- **Response `201 Created`** (New Source Ingested):
```json
{
  "source_id": "893c5d76-5749-417d-8b01-b664168cf892",
  "project_id": "e3a89047-9204-4b53-99b3-467812f8a421",
  "original_url": "https://en.wikipedia.org/wiki/Information_gap_task",
  "final_url": "https://en.wikipedia.org/wiki/Information_gap_task",
  "title": "Information gap task - Wikipedia",
  "ingestion_status": "completed",
  "extracted_content_id": "0f63a238-1632-4752-b1ee-6d0df09b5558",
  "word_count": 380,
  "character_count": 2650,
  "content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "is_duplicate": false,
  "extracted_at": "2026-10-31T13:00:00Z",
  "created_at": "2026-10-31T13:00:00Z"
}
```
- **Response `200 OK`** (Duplicate URL or Identical Content Hash Resolved Idempotently):
```json
{
  "source_id": "893c5d76-5749-417d-8b01-b664168cf892",
  "project_id": "e3a89047-9204-4b53-99b3-467812f8a421",
  "original_url": "https://en.wikipedia.org/wiki/Information_gap_task",
  "final_url": "https://en.wikipedia.org/wiki/Information_gap_task",
  "title": "Information gap task - Wikipedia",
  "ingestion_status": "completed",
  "extracted_content_id": "0f63a238-1632-4752-b1ee-6d0df09b5558",
  "word_count": 380,
  "character_count": 2650,
  "content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "is_duplicate": true,
  "extracted_at": "2026-10-31T13:00:00Z",
  "created_at": "2026-10-31T13:00:00Z"
}
```
- **Error Responses**:
  - `400 Bad Request`: SSRF violation, invalid URL syntax, or unsafe redirect.
  - `404 Not Found`: Target research project not found or soft-deleted.
  - `413 Payload Too Large`: Response body exceeded 2 MB.
  - `422 Unprocessable Entity`: Target Content-Type is non-HTML, malformed UUID, or extracted page content is empty.
  - `502 Bad Gateway`: Upstream remote host connection refused or DNS failure.
  - `503 Service Unavailable`: Supabase PostgreSQL connection unavailable or unconfigured.
  - `504 Gateway Timeout`: Upstream connection or read timeout.

#### `GET /api/v1/projects/{project_id}/sources`
- **Description**: Returns all non-deleted sources linked to the research project with extraction metadata and word counts.
- **Status**: `IMPLEMENTED & TESTED` (Step 7B)
- **Response `200 OK`**:
```json
[
  {
    "id": "893c5d76-5749-417d-8b01-b664168cf892",
    "project_id": "e3a89047-9204-4b53-99b3-467812f8a421",
    "source_type": "url",
    "title": "Information gap task - Wikipedia",
    "original_url": "https://en.wikipedia.org/wiki/Information_gap_task",
    "original_filename": null,
    "ingestion_status": "completed",
    "content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "word_count": 380,
    "character_count": 2650,
    "created_at": "2026-10-31T13:00:00Z",
    "updated_at": "2026-10-31T13:00:00Z"
  }
]
```

#### `GET /api/v1/projects/{project_id}/sources/{source_id}`
- **Description**: Returns complete details of a specific source including full extracted text content and parser metadata.
- **Status**: `IMPLEMENTED & TESTED` (Step 7B)
- **Response `200 OK`**: Returns full `SourceDetailResponse` with `extracted_text`, `extraction_metadata`, and `file_metadata`.

#### `POST /api/v1/projects/{project_id}/sources/pdf`
- **Description**: Secure PDF ingestion pipeline using PyMuPDF. Validates file header (`%PDF-`), MIME type (`application/pdf`), and `.pdf` extension. Reads in 64 KB chunks enforcing size limits (default 20 MB). Opens and parses purely in memory (zero disk writes). Rejects password-encrypted PDFs and documents exceeding page caps (default 200 pages). Extracts page-by-page text, extracts document metadata (title, author, subject, creation date), detects empty/scanned pages, and computes binary SHA-256 hash. Performs project isolation check, idempotently resolves duplicates via binary hash (`idx_sources_project_hash_unique`), and executes atomic PostgreSQL transactions inserting into `public.sources` and `public.extracted_content`. Scanned PDFs with zero extractable text are safely logged as `failed` in `public.sources` with 422 Unprocessable Entity.
- **Status**: `IMPLEMENTED & TESTED` (Step 8)
- **Path Parameters**:
  - `project_id`: `UUID` (Required, identifier of target research project)
- **Request Format**: `multipart/form-data`
  - `file`: Binary file upload (Required, must be valid PDF)
- **Response `201 Created`** (Fresh PDF Upload):
```json
{
  "source_id": "893c5d76-5749-417d-8b01-b664168cf892",
  "project_id": "e3a89047-9204-4b53-99b3-467812f8a421",
  "original_filename": "climate_report_2026.pdf",
  "title": "National Climate Assessment 2026",
  "ingestion_status": "completed",
  "page_count": 14,
  "readable_page_count": 14,
  "readability_status": "fully_readable",
  "word_count": 4820,
  "character_count": 31200,
  "content_hash": "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9",
  "is_duplicate": false,
  "pages": [
    {
      "page_number": 1,
      "text": "Executive Summary: National Climate Assessment 2026...",
      "word_count": 350,
      "character_count": 2240,
      "is_empty": false
    }
  ],
  "created_at": "2026-10-31T14:00:00Z"
}
```
- **Response `200 OK`** (Duplicate PDF Resolved Idempotently by Binary SHA-256 Hash):
```json
{
  "source_id": "893c5d76-5749-417d-8b01-b664168cf892",
  "project_id": "e3a89047-9204-4b53-99b3-467812f8a421",
  "original_filename": "climate_report_2026.pdf",
  "title": "National Climate Assessment 2026",
  "ingestion_status": "completed",
  "page_count": 14,
  "readable_page_count": 14,
  "readability_status": "fully_readable",
  "word_count": 4820,
  "character_count": 31200,
  "content_hash": "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9",
  "is_duplicate": true,
  "pages": [],
  "created_at": "2026-10-31T14:00:00Z"
}
```
- **Error Responses**:
  - `400 Bad Request`: Corrupted PDF, invalid magic header (`%PDF-`), empty file body, or password-protected PDF.
  - `404 Not Found`: Target research project not found or soft-deleted.
  - `413 Payload Too Large`: Upload file exceeds maximum size limit (default 20 MB) or exceeds maximum page count limit (default 200 pages).
  - `415 Unsupported Media Type`: Uploaded file does not have `.pdf` extension or Content-Type is not `application/pdf`.
  - `422 Unprocessable Entity`: Scanned document containing zero extractable text (OCR not supported), or malformed project UUID.
  - `503 Service Unavailable`: Supabase PostgreSQL connection unavailable or unconfigured.

#### `POST /api/v1/projects/{project_id}/sources/{source_id}/extract`
- **Description**: Secure, source-grounded evidence extraction pipeline using the configured AI provider (OpenRouter NVIDIA Nemotron 3 Ultra). Validates project and source existence, checks AI configuration, isolates source text in XML fencing, invokes the model with low temperature (0.1), verifies output via `SafeResponseParser`, performs post-extraction evidence integrity checks (attribution matching, verbatim quote verification, offset bounds check, domain consistency), and returns an authoritative `EvidenceExtractionResult` envelope.
- **Status**: `IMPLEMENTED & TESTED` (Step 9B.2.2B)
- **Path Parameters**:
  - `project_id`: `UUID` (Required, identifier of target research project)
  - `source_id`: `UUID` (Required, identifier of target source document)
- **Request Body** (`application/json`, optional):
```json
{
  "research_question": "What are the specific eligibility thresholds and deadlines?",
  "custom_instructions": "Focus on numerical values and policy statements."
}
```
- **Response `200 OK`**:
```json
{
  "source_id": "893c5d76-5749-417d-8b01-b664168cf892",
  "source_type": "web",
  "facts": [
    {
      "fact_id": "fact-001",
      "statement": "Annual family income must not exceed INR 2,50,000 for eligibility.",
      "fact_type": "eligibility",
      "location": {
        "source_id": "893c5d76-5749-417d-8b01-b664168cf892",
        "source_type": "web",
        "start_char": 120,
        "end_char": 185,
        "url": "https://example.gov.in/scheme",
        "heading_path": ["Eligibility Criteria"]
      },
      "evidence_text": "Annual family income must not exceed INR 2,50,000 for eligibility.",
      "representation_type": "direct_quote",
      "confidence": 0.95,
      "qualifiers": ["for academic year 2026-27"],
      "uncertainty_notes": null,
      "extraction_warnings": []
    }
  ],
  "claims": [
    {
      "claim_id": "claim-001",
      "claim_text": "The portal will extend application deadlines if regional server outages occur.",
      "claim_type": "policy_statement",
      "source_id": "893c5d76-5749-417d-8b01-b664168cf892",
      "evidence_location": {
        "source_id": "893c5d76-5749-417d-8b01-b664168cf892",
        "source_type": "web",
        "start_char": 250,
        "end_char": 328,
        "url": "https://example.gov.in/scheme"
      },
      "representation_type": "paraphrase",
      "confidence": 0.88,
      "qualifiers": ["if regional server outages occur"],
      "uncertainty_notes": null,
      "extraction_warnings": []
    }
  ],
  "extraction_status": "success",
  "warnings": [],
  "errors": [],
  "source_truncated": false,
  "source_character_count": 4500,
  "processed_character_count": 4500,
  "extracted_at": "2026-11-01T06:50:00Z"
}
```
- **Error Responses**:
  - `404 Not Found`: Target research project or source document not found or soft-deleted.
  - `422 Unprocessable Entity`: Malformed UUID format in path parameters or extra fields in request body.
  - `503 Service Unavailable`: Database service is unavailable, or AI provider is unconfigured (`OPENROUTER_API_KEY` missing).
  - `500 Internal Server Error`: Unexpected unhandled error during extraction execution.

#### `POST /api/v1/extract/url`
- **Description**: Scrapes, sanitizes, and extracts textual excerpts from an external web page.
- **Status**: `PLANNED` (Phase 3)
- **Request Body**:
```json
{
  "project_id": "e3a89047-9204-4b53-99b3-467812f8a421",
  "url": "https://example.gov.in/schemes/scholarship-guidelines-2026.html",
  "title": "Official Guidelines 2026"
}
```
- **Response `200 OK`**:
```json
{
  "source_id": "893c5d76-5749-417d-8b01-b664168cf892",
  "title": "Official Guidelines 2026",
  "url": "https://example.gov.in/schemes/scholarship-guidelines-2026.html",
  "character_count": 14250,
  "cleaned_text_sample": "Section 1: Eligibility criteria mandate an annual household income below INR 2,50,000...",
  "extraction_status": "completed",
  "warnings": []
}
```

#### `POST /api/v1/extract/pdf`
- **Description**: Accepts a PDF binary upload (`multipart/form-data`) and returns structured page-level text.
- **Status**: `PLANNED` (Phase 3)
- **Form Data**:
  - `project_id`: `UUID`
  - `file`: `file.pdf` (max 20MB)
- **Response `200 OK`**:
```json
{
  "source_id": "119f87c2-3e33-4f90-bd9a-0e9e4f5a342b",
  "title": "State_DBT_Circular_2026.pdf",
  "page_count": 12,
  "character_count": 28400,
  "extraction_status": "completed"
}
```

---

### 3.4 Evidence Persistence & Retrieval (Step 9B.3)

#### `POST /api/v1/projects/{project_id}/sources/{source_id}/persist`
- **Description**: Explicitly persists an AI-extracted evidence result (`EvidenceExtractionResult`) into `public.extraction_runs`, `public.evidence` (facts), and `public.source_claims` (unverified assertions) within an atomic PostgreSQL transaction.
- **Status**: `IMPLEMENTED & TESTED` (Step 9B.3)
- **Request Body**:
```json
{
  "extraction_result": {
    "source_id": "893c5d76-5749-417d-8b01-b664168cf892",
    "source_type": "web",
    "facts": [
      {
        "fact_id": "fact-101",
        "statement": "Annual household income must be strictly below INR 2,50,000.",
        "fact_type": "eligibility",
        "location": {
          "source_id": "893c5d76-5749-417d-8b01-b664168cf892",
          "source_type": "web",
          "url": "https://example.gov.in/guidelines",
          "heading_path": ["Eligibility", "Income Threshold"]
        },
        "evidence_text": "Section 1.2: Eligibility criteria mandate an annual household income below INR 2,50,000.",
        "representation_type": "direct_quote",
        "confidence": 0.98
      }
    ],
    "claims": [
      {
        "claim_id": "claim-201",
        "claim_text": "The portal will extend application deadlines by two weeks if server loads spike.",
        "claim_type": "prediction",
        "source_id": "893c5d76-5749-417d-8b01-b664168cf892",
        "evidence_location": {
          "source_id": "893c5d76-5749-417d-8b01-b664168cf892",
          "source_type": "web"
        },
        "representation_type": "paraphrase",
        "confidence": 0.85
      }
    ],
    "extraction_status": "success",
    "source_truncated": false,
    "source_character_count": 14250,
    "processed_character_count": 14250,
    "extracted_at": "2026-11-01T12:00:00Z"
  },
  "idempotency_key": "custom-idempotency-key-optional"
}
```
- **Response `201 Created`**:
```json
{
  "success": true,
  "run": {
    "id": "e4414df6-2c93-4a0b-85d8-c7e522960f22",
    "project_id": "e3a89047-9204-4b53-99b3-467812f8a421",
    "source_id": "893c5d76-5749-417d-8b01-b664168cf892",
    "ai_provider": "openrouter",
    "ai_model": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "extraction_status": "success",
    "source_truncated": false,
    "source_character_count": 14250,
    "processed_character_count": 14250,
    "extracted_facts_count": 1,
    "extracted_claims_count": 1,
    "warnings": [],
    "errors": [],
    "created_at": "2026-11-01T12:00:01Z"
  },
  "persisted_facts_count": 1,
  "persisted_claims_count": 1,
  "warnings": []
}
```

#### `GET /api/v1/projects/{project_id}/sources/{source_id}/evidence`
- **Description**: Retrieves persisted facts and claims extracted from a specific source, with optional filtering by `item_type` (`all`, `facts`, `claims`), `fact_type`, `claim_type`, and `extraction_run_id`.
- **Status**: `IMPLEMENTED & TESTED` (Step 9B.3)
- **Query Parameters**:
  - `extraction_run_id` (UUID, optional)
  - `item_type` (`all`, `facts`, `claims` - default `all`)
  - `fact_type` (optional)
  - `claim_type` (optional)
  - `limit` (int, default 50, max 200)
  - `offset` (int, default 0)
- **Response `200 OK`**:
```json
{
  "project_id": "e3a89047-9204-4b53-99b3-467812f8a421",
  "source_id": "893c5d76-5749-417d-8b01-b664168cf892",
  "facts": [
    {
      "id": "764b8559-0023-455b-b997-8c3ba5019de1",
      "fact_id": "fact-101",
      "statement": "Annual household income must be strictly below INR 2,50,000.",
      "fact_type": "eligibility",
      "evidence_text": "Section 1.2: Eligibility criteria mandate an annual household income below INR 2,50,000.",
      "representation_type": "direct_quote",
      "confidence": 0.98,
      "page_number": null,
      "url": "https://example.gov.in/guidelines",
      "location": { "url": "https://example.gov.in/guidelines" },
      "extraction_run_id": "e4414df6-2c93-4a0b-85d8-c7e522960f22",
      "created_at": "2026-11-01T12:00:01Z"
    }
  ],
  "claims": [
    {
      "id": "875c966a-1134-466c-ca08-9d4cb6120ef2",
      "claim_id": "claim-201",
      "claim_text": "The portal will extend application deadlines by two weeks if server loads spike.",
      "claim_type": "prediction",
      "representation_type": "paraphrase",
      "confidence": 0.85,
      "extraction_run_id": "e4414df6-2c93-4a0b-85d8-c7e522960f22",
      "created_at": "2026-11-01T12:00:01Z"
    }
  ],
  "total_facts": 1,
  "total_claims": 1,
  "limit": 50,
  "offset": 0
}
```

#### `GET /api/v1/projects/{project_id}/evidence`
- **Description**: Returns all extracted facts and claims across all sources in a project, with filtering and pagination.
- **Status**: `IMPLEMENTED & TESTED` (Step 9B.3)
- **Response `200 OK`**: Matches structure of source evidence with cross-source coverage.

#### `GET /api/v1/projects/{project_id}/sources/{source_id}/extraction-runs`
- **Description**: Lists historical AI extraction runs for a given source, tracking model provenance, status, and item counts.
- **Status**: `IMPLEMENTED & TESTED` (Step 9B.3)
- **Response `200 OK`**:
```json
{
  "project_id": "e3a89047-9204-4b53-99b3-467812f8a421",
  "source_id": "893c5d76-5749-417d-8b01-b664168cf892",
  "runs": [
    {
      "id": "e4414df6-2c93-4a0b-85d8-c7e522960f22",
      "ai_provider": "openrouter",
      "ai_model": "nvidia/nemotron-3-ultra-550b-a55b:free",
      "extraction_status": "success",
      "source_truncated": false,
      "extracted_facts_count": 1,
      "extracted_claims_count": 1,
      "created_at": "2026-11-01T12:00:01Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

#### `GET /api/v1/projects/{project_id}/extraction-runs/{run_id}`
- **Description**: Retrieves complete telemetry and error details for a specific extraction execution.
- **Status**: `IMPLEMENTED & TESTED` (Step 9B.3)
- **Response `200 OK`**: Returns typed `ExtractionRunResponse`.

---

### 3.5 AI Information Gap Detection & Persistence (Step 10D.2 — Implemented & Tested)

#### `POST /api/v1/projects/{project_id}/gaps/detect`
- **Description**: Triggers source-grounded information gap detection across project sources and evidence. Deconstructs the research question, cross-references persisted evidence, generates candidates via OpenRouter AI, validates candidates against evidence with semantic concept clustering, and transactionally persists findings to `public.information_gaps` with deterministic SHA-256 rerun deduplication.
- **Status**: `IMPLEMENTED & TESTED` (Step 10D.2)
- **Security**: Requires Bearer JWT authentication and verified project ownership (`Depends(get_owned_project)`).
- **Request Body** (optional `DetectGapsRequest`):
```json
{
  "custom_instructions": "Focus on residential solar battery storage incentives."
}
```
- **Response `200 OK` (`GapDetectionAndPersistenceResponse`)**:
```json
{
  "project_id": "11111111-1111-4000-a000-000000000001",
  "detection": {
    "project_id": "11111111-1111-4000-a000-000000000001",
    "research_question": "What are the complete eligibility criteria for community solar?",
    "total_gaps_detected": 1,
    "gaps": [
      {
        "candidate": {
          "candidate_id": 1,
          "target_subquestion": "What are the non-resident eligibility rules?",
          "gap_description": "The sources omit residency criteria for applicants.",
          "explanation": "Residency criteria are required for participation scope.",
          "suggested_query": "non-resident eligibility solar",
          "gap_type": "insufficient_evidence",
          "priority": "high",
          "gap_subtype": "incomplete_detail",
          "confidence_score": 0.88,
          "reasoning": "Sources discuss resident criteria only."
        },
        "validation_verdict": "confirmed",
        "grounded_facts_count": 0,
        "covered_evidence_ids": [],
        "corpus_truncation_warning": false,
        "grounding_notes": "Analyzed 2 sources; no residency rules found.",
        "source_omission_warning": null
      }
    ],
    "analysis_summary": "Analysis completed.",
    "warnings": [],
    "has_corpus_truncation": false,
    "sources_evaluated": 2,
    "facts_evaluated": 4,
    "claims_evaluated": 2,
    "topics_evaluated": 1,
    "ai_analysis_executed": true,
    "diagnostic_message": null,
    "detected_at": "2026-11-01T12:00:00Z"
  },
  "persistence": {
    "project_id": "11111111-1111-4000-a000-000000000001",
    "total_findings_evaluated": 1,
    "total_persisted": 1,
    "inserted_count": 1,
    "updated_count": 0,
    "preserved_count": 0,
    "gaps": [
      {
        "id": "aaaa0000-0000-4000-a000-000000000001",
        "project_id": "11111111-1111-4000-a000-000000000001",
        "topic_id": null,
        "gap_description": "The sources omit residency criteria for applicants.",
        "explanation": "Residency criteria are required for participation scope.",
        "suggested_query": "non-resident eligibility solar",
        "priority": "high",
        "status": "open",
        "gap_type": "insufficient_evidence",
        "confidence_metadata": {
          "bharmafills": {
            "schema_version": 1,
            "fingerprint": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "gap_subtype": "incomplete_detail",
            "validation_verdict": "confirmed",
            "ai_confidence": 0.88,
            "user_review": null
          }
        },
        "created_at": "2026-11-01T12:00:00Z",
        "updated_at": "2026-11-01T12:00:00Z"
      }
    ],
    "persisted_at": "2026-11-01T12:00:00Z"
  }
}
```

#### `GET /api/v1/projects/{project_id}/gaps`
- **Description**: Returns paginated list of persisted information gaps for an owned project with multi-dimensional filtering.
- **Status**: `IMPLEMENTED & TESTED` (Step 10D.2)
- **Security**: Requires Bearer JWT authentication and verified project ownership (`Depends(get_owned_project)`).
- **Query Parameters**:
  - `status`: Optional filter (`open`, `investigating`, `resolved`, `dismissed`).
  - `priority`: Optional filter (`low`, `medium`, `high`, `critical`).
  - `gap_type`: Optional filter (`no_evidence`, `insufficient_evidence`, `conflicting_evidence`, `unverified`).
  - `limit`: Default `50`, range `1-200`.
  - `offset`: Default `0`, ge `0`.
- **Response `200 OK` (`InformationGapListResponse`)**:
```json
{
  "project_id": "11111111-1111-4000-a000-000000000001",
  "total_count": 1,
  "limit": 50,
  "offset": 0,
  "gaps": [
    {
      "id": "aaaa0000-0000-4000-a000-000000000001",
      "project_id": "11111111-1111-4000-a000-000000000001",
      "topic_id": null,
      "gap_description": "The sources omit residency criteria for applicants.",
      "explanation": "Residency criteria are required for participation scope.",
      "suggested_query": "non-resident eligibility solar",
      "priority": "high",
      "status": "open",
      "gap_type": "insufficient_evidence",
      "confidence_metadata": {
        "bharmafills": {
          "schema_version": 1,
          "fingerprint": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
          "gap_subtype": "incomplete_detail",
          "validation_verdict": "confirmed",
          "ai_confidence": 0.88,
          "user_review": null
        }
      },
      "created_at": "2026-11-01T12:00:00Z",
      "updated_at": "2026-11-01T12:00:00Z"
    }
  ]
}
```

#### `GET /api/v1/projects/{project_id}/gaps/{gap_id}`
- **Description**: Retrieves full detail of a specific information gap. Returns generic 404 if the gap does not belong to the requested project.
- **Status**: `IMPLEMENTED & TESTED` (Step 10D.2)
- **Security**: Requires Bearer JWT authentication and verified project ownership (`Depends(get_owned_project)`).
- **Response `200 OK`**: Returns typed `InformationGapResponse`.

#### `PATCH /api/v1/projects/{project_id}/gaps/{gap_id}`
- **Description**: Updates the lifecycle status of an information gap (`investigating`, `resolved`, `dismissed`) and user review notes. Preserves existing detection metadata and rejects rollback to `open`.
- **Status**: `IMPLEMENTED & TESTED` (Step 10D.2)
- **Security**: Requires Bearer JWT authentication and verified project ownership (`Depends(get_owned_project)`).
- **Request Body** (`GapReviewUpdate`):
```json
{
  "status": "resolved",
  "user_notes": "Verified via supplementary government gazette notification dated Oct 28, 2026."
}
```
- **Response `200 OK`**: Returns updated `InformationGapResponse`.

---

### 3.6 Cross-Source Conflict Detection (Step 11 — Planned)

#### `GET /api/v1/projects/{id}/conflicts`
- **Description**: Returns direct contradictions identified across sources.
- **Status**: `PLANNED` (Phase 4)
- **Response `200 OK`**:
```json
{
  "project_id": "e3a89047-9204-4b53-99b3-467812f8a421",
  "conflicts": [
    {
      "id": "conf-301",
      "topic": "Application Deadline",
      "source_a": {
        "source_id": "893c5d76-5749-417d-8b01-b664168cf892",
        "title": "Central Portal Guidelines",
        "claim": "Deadline for academic year 2026 is November 30, 2026."
      },
      "source_b": {
        "source_id": "119f87c2-3e33-4f90-bd9a-0e9e4f5a342b",
        "title": "State DBT Circular",
        "claim": "Deadline for academic year 2026 is October 15, 2026."
      },
      "contradiction_analysis": "The central portal grants a 45-day extension that is not reflected in the state-level circular.",
      "status": "unresolved"
    }
  ]
}
```

---

### 3.6 Verification Checklist

#### `GET /api/v1/projects/{id}/checklist`
- **Description**: Returns the evidence-backed verification checklist.
- **Status**: `PLANNED` (Phase 5)
- **Response `200 OK`**:
```json
{
  "project_id": "e3a89047-9204-4b53-99b3-467812f8a421",
  "items": [
    {
      "id": "chk-001",
      "priority": "urgent",
      "verification_question": "Confirm with district officer whether state portal accepts central extension to Nov 30.",
      "item_text": "Verify final submission deadline discrepancy.",
      "status": "pending",
      "evidence_references": ["conf-301"]
    }
  ]
}
```
