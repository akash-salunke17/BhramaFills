import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import GapAnalysisSummary from "../features/analysis/components/GapAnalysisSummary";
import GapCard from "../features/analysis/components/GapCard";
import GapFilters from "../features/analysis/components/GapFilters";
import GapReviewDialog from "../features/analysis/components/GapReviewDialog";
import GapEvidenceViewer from "../features/analysis/components/GapEvidenceViewer";
import GapEmptyState from "../features/analysis/components/GapEmptyState";
import GapAnalysisSkeleton from "../features/analysis/components/GapAnalysisSkeleton";
import GapAnalysisPanel from "../features/analysis/components/GapAnalysisPanel";
import { projectService } from "../services/projectService";
import { gapService } from "../features/analysis/services/gapService";

const SAMPLE_GAP = {
  id: "gap-101",
  project_id: "11111111-1111-4000-a000-000000000001",
  gap_description: "Missing solar panel degradation rates over 20 years",
  explanation: "Long-term efficiency degradation is not stated in technical specs.",
  priority: "critical",
  status: "open",
  gap_type: "no_evidence",
  suggested_query: "monocrystalline degradation rate per annum 20 years",
  confidence_metadata: {
    bharmafills: {
      ai_confidence: 0.92,
      target_subquestion: "What is the expected power output degradation after 20 years?",
      gap_subtype: "incomplete_detail",
      validation_verdict: "confirmed",
      grounding_notes: "None of the 4 indexed datasheets mention 20-year degradation curves.",
      covered_evidence_ids: ["ev-99"],
      corpus_truncation_warning: false,
    },
  },
  created_at: "2026-11-01T12:00:00Z",
  updated_at: "2026-11-01T12:00:00Z",
};

const SAMPLE_EVIDENCE = [
  {
    id: "ev-99",
    source_id: "src-1",
    claim: "Warranty covers initial 5 years of operation.",
    supporting_excerpt: "Standard warranty covers factory defects for 5 years.",
    page_number: 14,
    fact_type: "temporal",
    confidence_score: 0.95,
  },
];

const SAMPLE_SOURCES = [
  {
    id: "src-1",
    title: "Solar Module Datasheet Rev 4",
    original_url: "https://example.com/datasheet.pdf",
  },
];

describe("Gap Analysis UI Components", () => {
  describe("GapAnalysisSummary", () => {
    it("renders metrics cards with exact numbers from backend response", () => {
      const summary = {
        total: 12,
        critical: 3,
        high: 4,
        medium: 3,
        low: 2,
        open: 7,
        investigating: 3,
        resolved: 2,
        dismissed: 0,
        hasCorpusTruncation: true,
        warnings: ["PDF document partially truncated due to length."],
      };

      const handlePriority = vi.fn();
      render(<GapAnalysisSummary summary={summary} onFilterPriority={handlePriority} />);

      expect(screen.getByText("12")).toBeInTheDocument();
      expect(screen.getByText("3")).toBeInTheDocument();
      expect(screen.getByText("4")).toBeInTheDocument();
      expect(screen.getByText(/Corpus Truncation/i)).toBeInTheDocument();
      expect(screen.getByText(/PDF document partially truncated/i)).toBeInTheDocument();

      // Click critical priority filter
      fireEvent.click(screen.getByText("Critical"));
      expect(handlePriority).toHaveBeenCalledWith("critical");
    });
  });

  describe("GapCard", () => {
    it("renders gap description, priority, confidence, and suggested query", () => {
      const inspectSpy = vi.fn();
      const reviewSpy = vi.fn();

      render(
        <GapCard
          gap={SAMPLE_GAP}
          onInspectEvidence={inspectSpy}
          onOpenReview={reviewSpy}
        />
      );

      expect(screen.getByText(/Missing solar panel degradation rates/i)).toBeInTheDocument();
      expect(screen.getByText("Critical")).toBeInTheDocument();
      expect(screen.getByText(/No Evidence Found/i)).toBeInTheDocument();
      expect(screen.getByText(/AI Confidence: 92%/i)).toBeInTheDocument();
      expect(screen.getByText(SAMPLE_GAP.suggested_query)).toBeInTheDocument();

      // Inspect Evidence button click
      const inspectBtn = screen.getByRole("button", { name: /inspect evidence/i });
      fireEvent.click(inspectBtn);
      expect(inspectSpy).toHaveBeenCalledWith(SAMPLE_GAP);

      // Review Status button click
      const reviewBtn = screen.getByRole("button", { name: /open/i });
      fireEvent.click(reviewBtn);
      expect(reviewSpy).toHaveBeenCalledWith(SAMPLE_GAP);
    });
  });

  describe("GapFilters", () => {
    it("allows user to select priority, type, status, and reset filters", () => {
      const setPriority = vi.fn();
      const setType = vi.fn();
      const setStatus = vi.fn();
      const setSort = vi.fn();

      render(
        <GapFilters
          selectedPriority="critical"
          onSelectPriority={setPriority}
          selectedGapType="all"
          onSelectGapType={setType}
          selectedStatus="all"
          onSelectStatus={setStatus}
          sortBy="priority_desc"
          onSelectSort={setSort}
          totalCount={10}
          filteredCount={3}
        />
      );

      expect(screen.getByText(/Showing/i)).toHaveTextContent("Showing 3 of 10 gaps");

      // Change priority select
      const prioritySelect = screen.getByLabelText(/filter by priority/i);
      fireEvent.change(prioritySelect, { target: { value: "high" } });
      expect(setPriority).toHaveBeenCalledWith("high");

      // Reset button click
      const resetBtn = screen.getByRole("button", { name: /reset/i });
      fireEvent.click(resetBtn);
      expect(setPriority).toHaveBeenCalledWith("all");
    });
  });

  describe("GapReviewDialog", () => {
    it("allows user to select review status, enter notes, and save review", async () => {
      const handleSave = vi.fn().mockResolvedValue({});
      const handleClose = vi.fn();

      render(
        <GapReviewDialog
          gap={SAMPLE_GAP}
          isOpen={true}
          onClose={handleClose}
          onSave={handleSave}
          isUpdating={false}
        />
      );

      expect(screen.getByRole("heading", { name: /update gap review status/i })).toBeInTheDocument();

      // Select 'Resolved'
      const resolvedBtn = screen.getByRole("button", { name: /resolved/i });
      fireEvent.click(resolvedBtn);

      // Enter notes
      const textarea = screen.getByPlaceholderText(/explain findings/i);
      fireEvent.change(textarea, { target: { value: "Found answer in manufacturer appendix." } });

      // Save
      const saveBtn = screen.getByRole("button", { name: /save review/i });
      fireEvent.click(saveBtn);

      expect(handleSave).toHaveBeenCalledWith("gap-101", {
        status: "resolved",
        user_notes: "Found answer in manufacturer appendix.",
      });
    });
  });

  describe("GapEvidenceViewer", () => {
    it("renders modal with subquestion, citation quotes, source name, and page number", () => {
      const handleClose = vi.fn();

      render(
        <GapEvidenceViewer
          gap={SAMPLE_GAP}
          isOpen={true}
          onClose={handleClose}
          evidenceList={SAMPLE_EVIDENCE}
          sources={SAMPLE_SOURCES}
        />
      );

      expect(screen.getByRole("dialog")).toBeInTheDocument();
      expect(screen.getByText(/What is the expected power output degradation after 20 years/i)).toBeInTheDocument();
      expect(screen.getByText(/Solar Module Datasheet Rev 4/i)).toBeInTheDocument();
      expect(screen.getByText(/Standard warranty covers factory defects for 5 years/i)).toBeInTheDocument();
      expect(screen.getByText(/Page:/i)).toBeInTheDocument();
      expect(screen.getByText("14")).toBeInTheDocument();

      // Close viewer
      const closeBtn = screen.getByRole("button", { name: /close viewer/i });
      fireEvent.click(closeBtn);
      expect(handleClose).toHaveBeenCalled();
    });
  });

  describe("GapEmptyState", () => {
    it("renders initial call to action state with 'Analyze Information Gaps' button", () => {
      const handleRun = vi.fn();
      render(<GapEmptyState type="initial" onRunDetection={handleRun} isDetecting={false} />);

      expect(screen.getByText("AI Information Gap Detection")).toBeInTheDocument();
      const btn = screen.getByRole("button", { name: /analyze information gaps/i });
      fireEvent.click(btn);
      expect(handleRun).toHaveBeenCalled();
    });

    it("renders no filter matches state with reset button", () => {
      const handleReset = vi.fn();
      render(<GapEmptyState type="no_filter_matches" onClearFilters={handleReset} />);

      expect(screen.getByText(/No Gaps Match Your Active Filters/i)).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /reset filters/i }));
      expect(handleReset).toHaveBeenCalled();
    });
  });

  describe("GapAnalysisSkeleton", () => {
    it("renders loading pulse placeholders", () => {
      render(<GapAnalysisSkeleton count={3} />);
      expect(screen.getByLabelText(/loading gap findings/i)).toBeInTheDocument();
    });
  });

  describe("GapAnalysisPanel (Master Panel Integration)", () => {
    beforeEach(() => {
      vi.spyOn(projectService, "resolveBackendId").mockReturnValue("11111111-1111-4000-a000-000000000001");
      vi.spyOn(gapService, "listGaps").mockResolvedValue({
        project_id: "11111111-1111-4000-a000-000000000001",
        total_count: 1,
        gaps: [SAMPLE_GAP],
      });
      vi.spyOn(gapService, "getProjectSources").mockResolvedValue(SAMPLE_SOURCES);
      vi.spyOn(gapService, "getProjectEvidence").mockResolvedValue({ items: SAMPLE_EVIDENCE });
    });

    it("renders the master panel with actions, summary, filters, and cards", async () => {
      const project = {
        id: "11111111-1111-4000-a000-000000000001",
        backendId: "11111111-1111-4000-a000-000000000001",
        title: "Solar Project",
      };

      render(<GapAnalysisPanel project={project} />);

      expect(screen.getByRole("heading", { name: /information gap analysis/i })).toBeInTheDocument();

      // Rerun detection button should be visible since gaps exist
      expect(screen.getByRole("button", { name: /rerun detection/i })).toBeInTheDocument();
    });
  });
});
