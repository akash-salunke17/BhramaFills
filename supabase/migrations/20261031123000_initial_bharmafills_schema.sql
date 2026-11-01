-- =============================================================================
-- Bharmafills Initial Schema Migration
-- Version: 20261031123000
-- Name: initial_bharmafills_schema
-- Target: Supabase PostgreSQL 15+ (Session Pooler compatible)
-- Description: Core relational schema for projects, sources, extracted content,
--              topics, evidence, information gaps, conflicts, and verification.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Migration History Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    version VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    checksum VARCHAR(64) NOT NULL
);

-- -----------------------------------------------------------------------------
-- 2. Research Projects Table
-- -----------------------------------------------------------------------------
CREATE TABLE public.research_projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NULL,
    title VARCHAR(120) NOT NULL,
    research_question VARCHAR(1000) NOT NULL,
    description VARCHAR(2000) NULL,
    category VARCHAR(50) NOT NULL DEFAULT 'General Research',
    status VARCHAR(30) NOT NULL DEFAULT 'Draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL,
    CONSTRAINT chk_research_projects_title_len CHECK (length(trim(title)) >= 3),
    CONSTRAINT chk_research_projects_question_len CHECK (length(trim(research_question)) >= 10),
    CONSTRAINT chk_research_projects_status CHECK (status IN ('Draft', 'In Progress', 'Completed', 'Archived')),
    CONSTRAINT chk_research_projects_category CHECK (category IN (
        'Education', 'Technology', 'Scholarships', 'Healthcare',
        'Business', 'Government Schemes', 'General Research', 'Other'
    ))
);

CREATE INDEX idx_research_projects_status ON public.research_projects (status) WHERE deleted_at IS NULL;
CREATE INDEX idx_research_projects_category ON public.research_projects (category) WHERE deleted_at IS NULL;
CREATE INDEX idx_research_projects_created_at ON public.research_projects (created_at DESC);

-- -----------------------------------------------------------------------------
-- 3. Sources Table (Webpages and PDF Documents)
-- -----------------------------------------------------------------------------
CREATE TABLE public.sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES public.research_projects(id) ON DELETE CASCADE,
    source_type VARCHAR(10) NOT NULL,
    title VARCHAR(255) NOT NULL,
    original_url TEXT NULL,
    original_filename VARCHAR(255) NULL,
    file_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    ingestion_status VARCHAR(30) NOT NULL DEFAULT 'pending',
    error_message TEXT NULL,
    content_hash VARCHAR(64) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ NULL,
    CONSTRAINT chk_sources_source_type CHECK (source_type IN ('url', 'pdf')),
    CONSTRAINT chk_sources_ingestion_status CHECK (ingestion_status IN ('pending', 'processing', 'completed', 'failed')),
    CONSTRAINT chk_sources_url_required CHECK (
        (source_type = 'url' AND original_url IS NOT NULL AND length(trim(original_url)) > 0) OR
        (source_type = 'pdf')
    ),
    CONSTRAINT chk_sources_pdf_required CHECK (
        (source_type = 'pdf' AND original_filename IS NOT NULL AND length(trim(original_filename)) > 0) OR
        (source_type = 'url')
    )
);

CREATE INDEX idx_sources_project_id ON public.sources (project_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_sources_ingestion_status ON public.sources (ingestion_status) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX idx_sources_project_url_unique ON public.sources (project_id, original_url)
    WHERE deleted_at IS NULL AND original_url IS NOT NULL;
CREATE UNIQUE INDEX idx_sources_project_hash_unique ON public.sources (project_id, content_hash)
    WHERE deleted_at IS NULL AND content_hash IS NOT NULL;

-- -----------------------------------------------------------------------------
-- 4. Extracted Content Table
-- -----------------------------------------------------------------------------
CREATE TABLE public.extracted_content (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES public.sources(id) ON DELETE CASCADE,
    extracted_text TEXT NOT NULL,
    extraction_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    extraction_method VARCHAR(50) NOT NULL DEFAULT 'unspecified',
    extraction_version VARCHAR(20) NOT NULL DEFAULT '1.0',
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_extracted_content_text_not_empty CHECK (length(trim(extracted_text)) > 0)
);

CREATE INDEX idx_extracted_content_source_id ON public.extracted_content (source_id);
CREATE INDEX idx_extracted_content_extracted_at ON public.extracted_content (extracted_at DESC);

-- -----------------------------------------------------------------------------
-- 5. Topics Table
-- -----------------------------------------------------------------------------
CREATE TABLE public.topics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES public.research_projects(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    description TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_topics_name_len CHECK (length(trim(name)) >= 2),
    CONSTRAINT uq_topics_project_name UNIQUE (project_id, name)
);

CREATE INDEX idx_topics_project_id ON public.topics (project_id);

-- -----------------------------------------------------------------------------
-- 6. Evidence Table (Claims, Excerpts, Confidence, Provenance)
-- -----------------------------------------------------------------------------
CREATE TABLE public.evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES public.research_projects(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES public.sources(id) ON DELETE CASCADE,
    extracted_content_id UUID NULL REFERENCES public.extracted_content(id) ON DELETE SET NULL,
    claim TEXT NOT NULL,
    supporting_excerpt TEXT NOT NULL,
    location_reference JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence_score NUMERIC(4, 3) NOT NULL DEFAULT 0.500,
    confidence_explanation TEXT NULL,
    ai_model VARCHAR(100) NULL,
    analysis_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_evidence_claim_len CHECK (length(trim(claim)) >= 5),
    CONSTRAINT chk_evidence_excerpt_len CHECK (length(trim(supporting_excerpt)) >= 5),
    CONSTRAINT chk_evidence_confidence_bounds CHECK (confidence_score >= 0.000 AND confidence_score <= 1.000)
);

CREATE INDEX idx_evidence_project_id ON public.evidence (project_id);
CREATE INDEX idx_evidence_source_id ON public.evidence (source_id);
CREATE INDEX idx_evidence_extracted_content_id ON public.evidence (extracted_content_id);
CREATE INDEX idx_evidence_confidence_score ON public.evidence (confidence_score);

-- -----------------------------------------------------------------------------
-- 7. Evidence-Topics Junction Table (Many-to-Many)
-- -----------------------------------------------------------------------------
CREATE TABLE public.evidence_topics (
    evidence_id UUID NOT NULL REFERENCES public.evidence(id) ON DELETE CASCADE,
    topic_id UUID NOT NULL REFERENCES public.topics(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (evidence_id, topic_id)
);

CREATE INDEX idx_evidence_topics_topic_id ON public.evidence_topics (topic_id);

-- -----------------------------------------------------------------------------
-- 8. Information Gaps Table
-- -----------------------------------------------------------------------------
CREATE TABLE public.information_gaps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES public.research_projects(id) ON DELETE CASCADE,
    topic_id UUID NULL REFERENCES public.topics(id) ON DELETE SET NULL,
    gap_description TEXT NOT NULL,
    explanation TEXT NOT NULL,
    suggested_query TEXT NULL,
    priority VARCHAR(20) NOT NULL DEFAULT 'medium',
    status VARCHAR(30) NOT NULL DEFAULT 'open',
    gap_type VARCHAR(30) NOT NULL DEFAULT 'no_evidence',
    confidence_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_information_gaps_desc_len CHECK (length(trim(gap_description)) >= 5),
    CONSTRAINT chk_information_gaps_priority CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT chk_information_gaps_status CHECK (status IN ('open', 'investigating', 'resolved', 'dismissed')),
    CONSTRAINT chk_information_gaps_type CHECK (gap_type IN (
        'no_evidence', 'insufficient_evidence', 'conflicting_evidence', 'unverified'
    ))
);

CREATE INDEX idx_information_gaps_project_id ON public.information_gaps (project_id);
CREATE INDEX idx_information_gaps_topic_id ON public.information_gaps (topic_id);
CREATE INDEX idx_information_gaps_priority ON public.information_gaps (priority);
CREATE INDEX idx_information_gaps_status ON public.information_gaps (status);
CREATE INDEX idx_information_gaps_type ON public.information_gaps (gap_type);

-- -----------------------------------------------------------------------------
-- 9. Conflicts Table (Contradictory Claims Across Sources)
-- -----------------------------------------------------------------------------
CREATE TABLE public.conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES public.research_projects(id) ON DELETE CASCADE,
    topic_id UUID NULL REFERENCES public.topics(id) ON DELETE SET NULL,
    description TEXT NOT NULL,
    explanation TEXT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'detected',
    severity VARCHAR(20) NOT NULL DEFAULT 'medium',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_conflicts_desc_len CHECK (length(trim(description)) >= 5),
    CONSTRAINT chk_conflicts_status CHECK (status IN ('detected', 'under_review', 'resolved', 'dismissed')),
    CONSTRAINT chk_conflicts_severity CHECK (severity IN ('low', 'medium', 'high', 'critical'))
);

CREATE INDEX idx_conflicts_project_id ON public.conflicts (project_id);
CREATE INDEX idx_conflicts_topic_id ON public.conflicts (topic_id);
CREATE INDEX idx_conflicts_status ON public.conflicts (status);
CREATE INDEX idx_conflicts_severity ON public.conflicts (severity);

-- -----------------------------------------------------------------------------
-- 10. Conflict-Evidence Junction Table (Many-to-Many with Stance)
-- -----------------------------------------------------------------------------
CREATE TABLE public.conflict_evidence (
    conflict_id UUID NOT NULL REFERENCES public.conflicts(id) ON DELETE CASCADE,
    evidence_id UUID NOT NULL REFERENCES public.evidence(id) ON DELETE CASCADE,
    stance VARCHAR(30) NOT NULL DEFAULT 'contradicts',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (conflict_id, evidence_id),
    CONSTRAINT chk_conflict_evidence_stance CHECK (stance IN (
        'supports_side_a', 'supports_side_b', 'contradicts', 'neutral'
    ))
);

CREATE INDEX idx_conflict_evidence_evidence_id ON public.conflict_evidence (evidence_id);

-- -----------------------------------------------------------------------------
-- 11. Verification Checklist Table
-- -----------------------------------------------------------------------------
CREATE TABLE public.verification_checklist (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES public.research_projects(id) ON DELETE CASCADE,
    information_gap_id UUID NULL REFERENCES public.information_gaps(id) ON DELETE SET NULL,
    conflict_id UUID NULL REFERENCES public.conflicts(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    priority VARCHAR(20) NOT NULL DEFAULT 'medium',
    verification_notes TEXT NULL,
    verified_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_verification_checklist_title_len CHECK (length(trim(title)) >= 3),
    CONSTRAINT chk_verification_checklist_status CHECK (status IN ('pending', 'verified', 'unresolved')),
    CONSTRAINT chk_verification_checklist_priority CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT chk_verification_checklist_mutual_target CHECK (
        information_gap_id IS NULL OR conflict_id IS NULL
    )
);

CREATE INDEX idx_verification_checklist_project_id ON public.verification_checklist (project_id);
CREATE INDEX idx_verification_checklist_gap_id ON public.verification_checklist (information_gap_id);
CREATE INDEX idx_verification_checklist_conflict_id ON public.verification_checklist (conflict_id);
CREATE INDEX idx_verification_checklist_status ON public.verification_checklist (status);

-- -----------------------------------------------------------------------------
-- 12. Row Level Security (RLS) Configuration
-- -----------------------------------------------------------------------------
-- Enable RLS on all Bharmafills tables to prevent unauthorized PostgREST browser access.
-- With zero permissive policies, public/anon/authenticated roles have deny-all access.
-- The backend connects directly through the Session Pooler as table owner/service role.
ALTER TABLE public.research_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.extracted_content ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.evidence_topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.information_gaps ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conflicts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conflict_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.verification_checklist ENABLE ROW LEVEL SECURITY;
