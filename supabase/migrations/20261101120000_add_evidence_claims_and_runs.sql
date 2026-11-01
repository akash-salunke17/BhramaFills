-- =============================================================================
-- Bharmafills Schema Migration: Evidence Persistence, Source Claims & Runs
-- Version: 20261101120000
-- Name: add_evidence_claims_and_runs
-- Target: Supabase PostgreSQL 15+ (Session Pooler compatible)
-- Description: Creates extraction_runs table, source_claims table, and enhances
--              evidence table with fact metadata, location offsets, and run linkage.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Extraction Runs Table (Auditability, Provenance, Truncation & Diagnostic Tracking)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.extraction_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES public.research_projects(id) ON DELETE CASCADE,
    source_id UUID NULL REFERENCES public.sources(id) ON DELETE CASCADE,
    batch_id UUID NULL,
    provider VARCHAR(50) NOT NULL DEFAULT 'openrouter',
    model_name VARCHAR(150) NOT NULL,
    extraction_status VARCHAR(30) NOT NULL,
    source_truncated BOOLEAN NOT NULL DEFAULT false,
    source_character_count INT NOT NULL DEFAULT 0,
    processed_character_count INT NOT NULL DEFAULT 0,
    facts_count INT NOT NULL DEFAULT 0,
    claims_count INT NOT NULL DEFAULT 0,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    run_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_extraction_runs_status CHECK (
        extraction_status IN ('success', 'partial', 'failed', 'no_content')
    ),
    CONSTRAINT chk_extraction_runs_counts CHECK (
        source_character_count >= 0 AND
        processed_character_count >= 0 AND
        facts_count >= 0 AND
        claims_count >= 0
    )
);

CREATE INDEX IF NOT EXISTS idx_extraction_runs_project_id ON public.extraction_runs (project_id);
CREATE INDEX IF NOT EXISTS idx_extraction_runs_source_id ON public.extraction_runs (source_id);
CREATE INDEX IF NOT EXISTS idx_extraction_runs_batch_id ON public.extraction_runs (batch_id) WHERE batch_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_extraction_runs_status ON public.extraction_runs (extraction_status);
CREATE INDEX IF NOT EXISTS idx_extraction_runs_extracted_at ON public.extraction_runs (extracted_at DESC);

-- -----------------------------------------------------------------------------
-- 2. Evidence Table Enhancements (Extracted Facts, Offsets & Run Linkage)
-- -----------------------------------------------------------------------------
ALTER TABLE public.evidence
    ADD COLUMN IF NOT EXISTS extraction_run_id UUID NULL REFERENCES public.extraction_runs(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS fact_id VARCHAR(100) NULL,
    ADD COLUMN IF NOT EXISTS fact_type VARCHAR(50) NOT NULL DEFAULT 'general',
    ADD COLUMN IF NOT EXISTS representation_type VARCHAR(30) NOT NULL DEFAULT 'direct_quote',
    ADD COLUMN IF NOT EXISTS qualifiers JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS uncertainty_notes TEXT NULL,
    ADD COLUMN IF NOT EXISTS extraction_warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS start_char INT NULL,
    ADD COLUMN IF NOT EXISTS end_char INT NULL,
    ADD COLUMN IF NOT EXISTS page_number INT NULL,
    ADD COLUMN IF NOT EXISTS url TEXT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_evidence_fact_type'
    ) THEN
        ALTER TABLE public.evidence ADD CONSTRAINT chk_evidence_fact_type CHECK (
            fact_type IN ('general', 'statistical', 'procedural', 'eligibility', 'definitional', 'temporal')
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_evidence_rep_type'
    ) THEN
        ALTER TABLE public.evidence ADD CONSTRAINT chk_evidence_rep_type CHECK (
            representation_type IN ('direct_quote', 'paraphrase')
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_evidence_offsets'
    ) THEN
        ALTER TABLE public.evidence ADD CONSTRAINT chk_evidence_offsets CHECK (
            (start_char IS NULL AND end_char IS NULL) OR
            (start_char IS NOT NULL AND end_char IS NOT NULL AND end_char > start_char AND start_char >= 0)
        );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_evidence_extraction_run_id ON public.evidence (extraction_run_id);
CREATE INDEX IF NOT EXISTS idx_evidence_fact_type ON public.evidence (fact_type);
CREATE INDEX IF NOT EXISTS idx_evidence_representation_type ON public.evidence (representation_type);
CREATE INDEX IF NOT EXISTS idx_evidence_source_offsets ON public.evidence (source_id, start_char, end_char);
CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_run_fact_id_unique
    ON public.evidence (extraction_run_id, fact_id)
    WHERE extraction_run_id IS NOT NULL AND fact_id IS NOT NULL;

-- -----------------------------------------------------------------------------
-- 3. Source Claims Table (Dedicated Claim Persistence with Provenance)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.source_claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES public.research_projects(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES public.sources(id) ON DELETE CASCADE,
    extraction_run_id UUID NULL REFERENCES public.extraction_runs(id) ON DELETE SET NULL,
    claim_id VARCHAR(100) NOT NULL,
    claim_text TEXT NOT NULL,
    claim_type VARCHAR(50) NOT NULL,
    representation_type VARCHAR(30) NOT NULL DEFAULT 'paraphrase',
    confidence_score NUMERIC(4, 3) NOT NULL DEFAULT 0.800,
    location_reference JSONB NOT NULL DEFAULT '{}'::jsonb,
    start_char INT NULL,
    end_char INT NULL,
    page_number INT NULL,
    url TEXT NULL,
    qualifiers JSONB NOT NULL DEFAULT '[]'::jsonb,
    uncertainty_notes TEXT NULL,
    extraction_warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_source_claims_text_len CHECK (length(trim(claim_text)) >= 3),
    CONSTRAINT chk_source_claims_confidence_bounds CHECK (confidence_score >= 0.000 AND confidence_score <= 1.000),
    CONSTRAINT chk_source_claims_type CHECK (
        claim_type IN (
            'factual_assertion', 'recommendation', 'policy_statement',
            'prediction', 'opinion', 'eligibility_condition', 'numerical_or_statistical'
        )
    ),
    CONSTRAINT chk_source_claims_rep_type CHECK (
        representation_type IN ('direct_quote', 'paraphrase')
    ),
    CONSTRAINT chk_source_claims_offsets CHECK (
        (start_char IS NULL AND end_char IS NULL) OR
        (start_char IS NOT NULL AND end_char IS NOT NULL AND end_char > start_char AND start_char >= 0)
    )
);

CREATE INDEX IF NOT EXISTS idx_source_claims_project_id ON public.source_claims (project_id);
CREATE INDEX IF NOT EXISTS idx_source_claims_source_id ON public.source_claims (source_id);
CREATE INDEX IF NOT EXISTS idx_source_claims_extraction_run_id ON public.source_claims (extraction_run_id);
CREATE INDEX IF NOT EXISTS idx_source_claims_claim_type ON public.source_claims (claim_type);
CREATE INDEX IF NOT EXISTS idx_source_claims_confidence_score ON public.source_claims (confidence_score);
CREATE UNIQUE INDEX IF NOT EXISTS idx_source_claims_run_claim_id_unique
    ON public.source_claims (extraction_run_id, claim_id)
    WHERE extraction_run_id IS NOT NULL;

-- -----------------------------------------------------------------------------
-- 4. Row Level Security (RLS) Configuration
-- -----------------------------------------------------------------------------
ALTER TABLE public.extraction_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.source_claims ENABLE ROW LEVEL SECURITY;
