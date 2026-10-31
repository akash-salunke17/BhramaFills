# Bharmafills — Product Requirements Document (PRD)

> **Document Status**: Active / Canonical Baseline
> **Product Version**: 0.2.0 (Phase 2 Completed)
> **Target Event**: Shinchan Online Hackathon 2026
> **Workspace Identifier**: `Shinchan`

---

## 1. Executive Summary & Product Description

**Bharmafills** is an AI-assisted Information Gap Detection Platform designed to expose what information sources omit, contradict, or leave unverified.

When users investigate a research topic across multiple sources—such as government schemes, educational policies, academic literature, or market intelligence—they face fragmented narratives. Traditional search engines and standard generative AI chatbots routinely hallucinate, summarize without source-grounding, or falsely assume an absence of evidence is proof of non-existence.

Bharmafills systematically parses research sources, organizes extracted claims by topic, detects conflicting statements, flags unanswered questions, and synthesizes an actionable, evidence-linked verification checklist.

---

## 2. Core Product Principles

All product behavior, prompt designs, and algorithms must adhere to six inviolable principles:

1. **Evidence Before Conclusions**: Conclusions must be directly traceable to extracted source excerpts. No assertions without citations.
2. **Source Traceability**: Every identified gap, conflicting claim, or checklist item must maintain a transparent link back to the originating URL or document page.
3. **Transparent Uncertainty**: The system must explicitly state when evidence is insufficient, inconclusive, or unavailable. Speculation must be labeled as hypothesis, never as fact.
4. **Zero Fabrication**: Under no circumstances may the system generate fictitious URLs, false quotations, fabricated research papers, or invented statistics.
5. **Missing vs. Conflicting Distinction**:
   - An **Information Gap** occurs when a critical question is completely unaddressed across sources.
   - A **Conflicting Claim** occurs when two or more sources make incompatible factual assertions on the same question.
6. **Absence of Evidence is Not Evidence of Absence**: If a source does not mention a requirement, the system must report that the requirement was not mentioned, never that it does not exist.
7. **External Content is Untrusted Data**: All scraped web text, user inputs, and uploaded documents are treated strictly as untrusted data. The AI must never follow instructions, commands, or prompt overrides embedded within external source texts.

---

## 3. Problem Statement & Target Audience

### 3.1 The Problem
- **Information Asymmetry**: Crucial eligibility criteria, hidden fees, or caveats are buried across dozens of disjointed documents.
- **Narrative Contradictions**: Different official portals or third-party summaries give conflicting deadlines, requirements, or definitions.
- **AI Hallucinations**: Standard LLMs invent answers when source documents lack coverage rather than admitting an information gap exists.
- **Lack of Verification Tools**: Users have no structured way to turn complex source findings into an actionable verification checklist.

### 3.2 Target Users
- **Students & Applicants**: Researching scholarship eligibility, university admissions, and government welfare programs.
- **Analysts & Researchers**: Investigating policy updates, scientific claims, market trends, and technological benchmarks.
- **Legal & Compliance Professionals**: Reviewing contractual terms, regulatory filings, and disclosure mandates across source drafts.

---

## 4. Product Goals & Non-Goals

### 4.1 Goals
- Provide structured **Research Project Workspaces** to organize distinct investigations.
- Ingest external research material via **web URLs** (HTML content extraction) and **uploaded PDF documents**.
- Systematically cross-reference sources to identify **unanswered questions**, **conflicting claims**, and **potential temporal inconsistencies**.
- Generate interactive, prioritized **Verification Checklists** categorized as *Pending*, *Verified*, or *Unresolved*.
- Maintain strict modularity, high accessibility, and instant data integrity verification.

### 4.2 Non-Goals
- Bharmafills is **not a generic web search engine** (it analyzes specific sources provided or curated by the user).
- Bharmafills is **not an automated decision-maker** (it surfaces gaps and contradictions for human verification; it does not replace legal, financial, or medical counsel).
- Bharmafills will **not scrape behind private paywalls or bypass access controls**.

---

## 5. Core User Journey

```text
+-----------------------+     +------------------------+     +------------------------+
| 1. Create Workspace   | --> | 2. Ingest Sources      | --> | 3. Automated Synthesis |
| Define title, inquiry |     | Attach URLs & upload   |     | Extract text, map      |
| question, & category  |     | PDF documents (Ph. 3)  |     | claims, & detect gaps  |
+-----------------------+     +------------------------+     +------------------------+
                                                                         |
                                                                         v
+-----------------------+     +------------------------+     +------------------------+
| 6. Complete Research  | <-- | 5. Track Checklist     | <-- | 4. Review Gaps & Claims|
| Export findings &     |     | Mark items Verified,   |     | Inspect contradictions |
| audit trails (Ph. 5)  |     | Pending, or Unresolved |     | with source citations  |
+-----------------------+     +------------------------+     +------------------------+
```

---

## 6. Functional Requirements & Implementation Status

| Feature ID | Functional Requirement | Development Stage | Status |
| :--- | :--- | :--- | :--- |
| **FR-01** | **Application Shell & Layout**: Responsive sidebar, topbar, mobile drawer, high-contrast theme. | Step 1 & 2 | **COMPLETED & VERIFIED** |
| **FR-02** | **Dashboard Metrics**: Live project counts (Total, Active) and dynamic recent activity list. | Step 2 & 3 | **COMPLETED & VERIFIED** |
| **FR-03** | **Project Creation**: Form validating title (3–120 chars), question (10–1000 chars), category, and status. | Step 3 | **COMPLETED & VERIFIED** |
| **FR-04** | **Project Management (CRUD)**: Listing, viewing details, editing parameters, and safe deletion with confirmation. | Step 3 | **COMPLETED & VERIFIED** |
| **FR-05** | **Exploration (Search/Filter/Sort)**: Multi-field text search, 4 lifecycle status filters, 8 category filters, and 3 sort options. | Step 3 | **COMPLETED & VERIFIED** |
| **FR-06** | **Local Storage Persistence**: Decoupled service layer (`researchService.js`) with quota handling and corrupted data recovery. | Step 3 | **COMPLETED & VERIFIED** |
| **FR-07** | **FastAPI Backend Core**: RESTful API service coordinating health checks, CORS, error handling, and extraction routes. | Step 5 | **PLANNED** |
| **FR-08** | **Supabase Cloud Persistence**: PostgreSQL relational database with Row Level Security (RLS) and client migration. | Step 6 | **PLANNED** |
| **FR-09** | **URL Source Ingestion**: Extract readable text from web pages via BeautifulSoup with SSRF/DNS rebinding defense. | Step 7 | **PLANNED** |
| **FR-10** | **PDF Document Extraction**: Ingest and extract text, sections, and metadata from uploaded PDFs via PyMuPDF. | Step 8 | **PLANNED** |
| **FR-11** | **AI Extraction & Prompt Fencing**: Configurable Gemini model (`GEMINI_MODEL`) with XML untrusted prompt fencing. | Step 9 | **PLANNED** |
| **FR-12** | **Information Gap Detection**: Synthesize extracted source passages to identify unaddressed inquiries and omissions. | Step 10 | **PLANNED** |
| **FR-13** | **Conflict Detection**: Surface contradictory claims between sources with side-by-side excerpt comparisons. | Step 11 | **PLANNED** |
| **FR-14** | **Evidence & Verification Checklist**: Interactive checklist allowing users to verify, debunk, and export identified gaps. | Step 12 & 13 | **PLANNED** |

---

## 7. Non-Functional Requirements

- **Accessibility**: WCAG 2.1 AA compliant text contrast (>16:1 for primary headings), explicit form labels, and complete keyboard navigation (`Escape` to dismiss modals).
- **Data Integrity**: Local browser storage must not silently swallow quota errors or destroy corrupted JSON without an automated quarantine backup.
- **Performance**: Instantaneous client-side filtering and sorting for up to 500 local workspaces; production frontend bundle < 300 kB (gzip: ~82 kB).
- **Security**: Zero `dangerouslySetInnerHTML`, strict input sanitization, and strict separation between frontend presentation and future backend secrets (Gemini API keys, Supabase Service Role).
- **Reliability**: 100% passing automated test suite required before any phase advancement.

---

## 8. Success Metrics

1. **Extraction Accuracy**: ≥ 90% of relevant main body text extracted from non-paywalled informational URLs.
2. **Gap Precision**: ≥ 85% of surfaced information gaps judged genuine and relevant by human evaluators.
3. **Traceability**: 100% of reported conflicting claims include exact source references (URL or PDF page).
4. **Code Quality**: Zero ESLint warnings, zero failing regression tests, and zero unhandled promise rejections.

---

## 9. Cross-References

- For UI layout and design tokens, see [DESIGN.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/DESIGN.md).
- For system boundaries and service architecture, see [ARCHITECTURE.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/ARCHITECTURE.md).
- For planned relational tables, see [DATABASE.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/DATABASE.md).
- For planned REST endpoints, see [API.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/API.md).
- For agent governance and development rules, see [AGENTS.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/AGENTS.md).
- For sequential milestone roadmap, see [docs/DEVELOPMENT_ROADMAP.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/docs/DEVELOPMENT_ROADMAP.md).
