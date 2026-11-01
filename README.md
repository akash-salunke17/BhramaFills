# Bharmafills

> **AI-Assisted Information Gap Detection Platform**
> Developed for **Shinchan Online Hackathon 2026**
> Workspace Identifier: `Shinchan`

---

## 1. Product Overview

**Bharmafills** is an intelligence platform engineered to help researchers, policy analysts, students, and compliance teams uncover what information sources leave unanswered. When investigating a topic across web articles, academic papers, reports, or government scheme portals, sources frequently present conflicting claims, omit crucial context, or rely on outdated assumptions.

Bharmafills systematically detects these **information gaps**, flags contradictions, and compiles evidence-based verification checklists.

---

## 2. Documentation Index

The repository maintains an authoritative, synchronized documentation suite:

| Specification | Description | Status |
| :--- | :--- | :--- |
| [PRD.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/PRD.md) | Product Requirements Document: principles, features, user personas, non-goals | `ACTIVE` |
| [ARCHITECTURE.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/ARCHITECTURE.md) | System architecture, frontend/backend topology, data flows, and security boundaries | `ACTIVE` |
| [DESIGN.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/DESIGN.md) | UI/UX design tokens, Nova preset, Geist typography, accessibility rules | `ACTIVE` |
| [DATABASE.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/DATABASE.md) | Conceptual ERD, 10-table Supabase PostgreSQL schema, RLS policies | `PLANNED` |
| [API.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/API.md) | REST API endpoints (FastAPI), request/response schemas, error envelope | `PLANNED` |
| [AGENTS.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/AGENTS.md) | Operating rules and mandatory engineering standards for AI agents | `ACTIVE` |
| [docs/SETUP.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/docs/SETUP.md) | Complete local development setup instructions for Windows and PowerShell | `ACTIVE` |
| [docs/IMPLEMENTATION.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/docs/IMPLEMENTATION.md) | Codebase inventory, component maps, and architectural breakdown | `ACTIVE` |
| [docs/SECURITY.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/docs/SECURITY.md) | Threat modeling, SSRF prevention, prompt injection, and RLS policies | `ACTIVE` |
| [docs/INTEGRATIONS.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/docs/INTEGRATIONS.md) | Specifications for Google Gemini, Supabase, BeautifulSoup, and PyMuPDF | `PLANNED` |
| [docs/TESTING.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/docs/TESTING.md) | Comprehensive testing guide (Vitest, RTL, Pytest, Playwright strategy) | `ACTIVE` |
| [docs/DEBUGGING.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/docs/DEBUGGING.md) | Troubleshooting runbooks for common Windows/Node/Python errors | `ACTIVE` |
| [docs/MCP.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/docs/MCP.md) | Model Context Protocol strategy, boundaries, and optional integrations | `PLANNED` |
| [docs/DEVELOPMENT_ROADMAP.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/docs/DEVELOPMENT_ROADMAP.md) | Canonical 13-stage development sequence and milestone dependencies | `ACTIVE` |

---

## 3. Implementation Status

| Stage | Module | Status | Verification Metrics |
| :--- | :--- | :---: | :--- |
| **Step 1 & 2** | **Tailwind, shadcn & UI Shell** | `COMPLETED` | Fully responsive shell, Nova preset, light mode, mobile drawer |
| **Step 3** | **Research Project Management** | `COMPLETED` | 52 passing Vitest unit tests, clean ESLint, zero build errors |
| **Step 4** | **Documentation Foundation** | `COMPLETED` | 16 canonical specifications, threat models, API and database contracts |
| **Step 5** | **FastAPI Foundation** | `COMPLETED` (5A) | 23 passing Pytest tests, modular app scaffold, CORS, truthful health probe |
| **Step 6A** | **Supabase Connection Foundation** | `COMPLETED` (6A) | 42 passing Pytest tests, asyncpg Session Pooler connection manager, `/health/database` probe |
| **Step 6B** | **Supabase Schema & RLS** | `PLANNED` *(Next)* | PostgreSQL schema migrations, RLS policies, client sync adapter |
| **Step 7** | **URL Extraction** | `PLANNED` | BeautifulSoup4 scraping, SSRF & DNS rebinding defense |
| **Step 8** | **PDF Extraction** | `PLANNED` | PyMuPDF parsing, page citation indexing, 20MB file cap |
| **Step 9** | **AI Extraction & Prompt Fencing** | `PLANNED` | Configurable Gemini model, XML untrusted prompt fencing |
| **Step 10 & 11** | **Gap & Conflict Detection** | `PLANNED` | Omission detection, pairwise claim contradiction analysis |
| **Step 12 & 13** | **Checklist & E2E Workflow** | `PLANNED` | Interactive verification checklist, Playwright E2E, audit export |

> **Persistence Notice**: Currently, research projects are persisted locally in the user's browser via a resilient storage service (`frontend/src/services/researchService.js`). Cloud PostgreSQL sync and multi-user authentication via Supabase are scheduled for Step 6.

---

## 4. Quickstart Guide (Frontend)

### Prerequisites
- Node.js v20+ recommended
- Windows PowerShell

### Setup Instructions
```powershell
# 1. Navigate to frontend directory
cd frontend

# 2. Install dependencies
npm.cmd install

# 3. Start local development server
npm.cmd run dev
```

### Verification Scripts
```powershell
# Run automated test suite (52 tests across 4 suites)
npm.cmd test

# Run ESLint code quality checks
npm.cmd run lint

# Compile production build
npm.cmd run build

# Preview production build locally
npm.cmd run preview
```

### Backend Quickstart (Step 5A Active)
```powershell
# 1. Navigate to backend directory
cd backend

# 2. Activate virtual environment
.\venv\Scripts\Activate.ps1

# 3. Start development server
python -m uvicorn app.main:app --reload --port 8000

# 4. Run automated test suite (171 tests)
python -m pytest
```

---

## 5. Technology Stack Summary

- **Frontend**: React 19, Vite 8, Tailwind CSS v4, Base UI, Nova design tokens, `@fontsource-variable/geist`, `lucide-react`.
- **Frontend Testing**: Vitest 5, React Testing Library, `@testing-library/jest-dom`, JSDOM (52 tests passing).
- **Backend**: Python 3.15, FastAPI, Uvicorn, HTTPX, asyncpg, Pydantic v2 & Pydantic Settings (171 tests passing across 15 suites).
- **Web Extraction Engine**: BeautifulSoup4, lxml, socket-level DNS pinning, strict SSRF defense (Step 7A/7B implemented & verified).
- **PDF Extraction Engine**: PyMuPDF (`fitz`), memory stream processing, page chunking, metadata extraction (Step 8 implemented & verified).
- **Database & Auth**: Supabase PostgreSQL 17 via Session Pooler, Row Level Security (RLS) on all domain tables (Step 6A/6B implemented & live-verified).
- **AI Synthesis Engine**: OpenRouter API (`nvidia/nemotron-3-ultra-550b-a55b:free`), HTTPX async client, SafeResponseParser (Step 9A implemented & verified).
