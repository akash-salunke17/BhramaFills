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
- **Media Type**: `application/json` (unless handling binary uploads where `multipart/form-data` is required).
- **CORS**: Restricted to explicitly configured frontend origins (`http://localhost:5173` in development).

### 1.2 Common Error Response Format (RFC 7807 Standard)
All 4xx and 5xx responses conform to a unified error schema:

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
│   ├── GET  /api/v1/health                     # Quick liveness probe
│   └── GET  /api/v1/health/ready               # Readiness probe (DB + Gemini ping)
├── Authentication
│   └── GET  /api/v1/auth/me                    # Current authenticated user details
├── Research Projects
│   ├── GET  /api/v1/projects                   # List research projects
│   ├── POST /api/v1/projects                   # Create a new research project
│   ├── GET  /api/v1/projects/{id}              # Get project details & statistics
│   ├── PATCH /api/v1/projects/{id}             # Update project metadata
│   └── DELETE /api/v1/projects/{id}            # Soft delete a project
├── Sources Management
│   ├── GET  /api/v1/projects/{id}/sources      # List sources attached to a project
│   ├── POST /api/v1/projects/{id}/sources      # Register a source (URL or manual)
│   └── DELETE /api/v1/sources/{source_id}      # Remove a source
├── Extraction Pipeline
│   ├── POST /api/v1/extract/url                # Scrape & clean URL HTML
│   ├── POST /api/v1/extract/pdf                # Parse & clean uploaded PDF file
│   └── GET  /api/v1/extract/status/{job_id}    # Check background extraction status
├── Evidence & Source Inspection
│   ├── GET  /api/v1/projects/{id}/evidence     # Retrieve extracted facts & evidence records
│   └── GET  /api/v1/sources/{id}/document      # Retrieve extracted document text & page metadata
├── AI Analysis & Gap Detection
│   ├── POST /api/v1/projects/{id}/analyze      # Trigger AI gap & conflict analysis
│   ├── GET  /api/v1/projects/{id}/gaps         # List detected information gaps
│   └── GET  /api/v1/projects/{id}/conflicts    # List detected conflicting claims
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

### 3.4 Evidence & Source Inspection

#### `GET /api/v1/projects/{id}/evidence`
- **Description**: Returns all discrete extracted facts, page citations, and evidence records associated with sources in this project.
- **Status**: `PLANNED` (Step 7/8 Ingestion & Step 9 AI Baseline)
- **Response `200 OK`**:
```json
{
  "project_id": "e3a89047-9204-4b53-99b3-467812f8a421",
  "evidence": [
    {
      "id": "fact-101",
      "source_id": "893c5d76-5749-417d-8b01-b664168cf892",
      "source_title": "Official Guidelines 2026",
      "topic": "Income Threshold",
      "claim_text": "Annual household income must be strictly below INR 2,50,000.",
      "exact_citation": "Section 1.2: Eligibility criteria mandate an annual household income below INR 2,50,000 as attested by the competency authority.",
      "page_number": 2,
      "confidence_score": 0.98
    }
  ]
}
```

#### `GET /api/v1/sources/{id}/document`
- **Description**: Retrieves cleaned, normalized document text and page breakdown for a specific source.
- **Status**: `PLANNED` (Step 7/8 Ingestion)
- **Response `200 OK`**:
```json
{
  "source_id": "893c5d76-5749-417d-8b01-b664168cf892",
  "title": "Official Guidelines 2026",
  "character_count": 14250,
  "page_count": 4,
  "extraction_status": "completed",
  "cleaned_text": "Section 1: Eligibility criteria mandate...",
  "pages": [
    {
      "page_number": 1,
      "character_count": 3200,
      "text": "Government of India Notification..."
    }
  ]
}
```

---

### 3.5 AI Gap & Conflict Detection

#### `POST /api/v1/projects/{id}/analyze`
- **Description**: Triggers comparative analysis using Google Gemini across all extracted project sources.
- **Status**: `PLANNED` (Phase 4)
- **Response `202 Accepted`**:
```json
{
  "analysis_job_id": "771e194c-cfc2-48df-9f33-10d9fa2e022b",
  "status": "processing",
  "estimated_duration_seconds": 12
}
```

#### `GET /api/v1/projects/{id}/gaps`
- **Description**: Returns all identified information gaps for a project.
- **Status**: `PLANNED` (Phase 4)
- **Response `200 OK`**:
```json
{
  "project_id": "e3a89047-9204-4b53-99b3-467812f8a421",
  "gaps": [
    {
      "id": "gap-901",
      "topic": "Income Certificate Attestation",
      "severity": "critical",
      "title": "Missing Issuing Authority Requirement",
      "description": "None of the 4 sources specify whether the income certificate must be issued by a Tehsildar or Sub-Divisional Magistrate.",
      "why_it_matters": "Submitting an unauthorized certificate causes immediate application disqualification without appeal.",
      "suggested_query": "Maharashtra DBT income certificate issuing authority notification 2026",
      "status": "unresolved"
    }
  ]
}
```

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
