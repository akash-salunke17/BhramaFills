import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useGapAnalysis } from "../features/analysis/hooks/useGapAnalysis";
import { gapService } from "../features/analysis/services/gapService";
import { projectService } from "../services/projectService";

const TEST_PROJECT_ID = "11111111-1111-4000-a000-000000000001";

const DUMMY_GAPS = [
  {
    id: "gap-1",
    project_id: TEST_PROJECT_ID,
    gap_description: "Missing eligibility criteria",
    explanation: "Applicants cannot determine if they qualify.",
    priority: "critical",
    status: "open",
    gap_type: "no_evidence",
    created_at: "2026-11-01T10:00:00Z",
    updated_at: "2026-11-01T10:00:00Z",
    confidence_metadata: {
      bharmafills: {
        ai_confidence: 0.88,
        validation_verdict: "confirmed",
        covered_evidence_ids: ["ev-1"],
      },
    },
  },
  {
    id: "gap-2",
    project_id: TEST_PROJECT_ID,
    gap_description: "Application deadlines not mentioned",
    explanation: "Timeline is unknown.",
    priority: "medium",
    status: "investigating",
    gap_type: "insufficient_evidence",
    created_at: "2026-11-01T11:00:00Z",
    updated_at: "2026-11-01T11:00:00Z",
    confidence_metadata: {
      bharmafills: {
        ai_confidence: 0.65,
        validation_verdict: "partially_covered",
      },
    },
  },
];

describe("useGapAnalysis Hook", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(projectService, "resolveBackendId").mockReturnValue(TEST_PROJECT_ID);
    vi.spyOn(gapService, "listGaps").mockResolvedValue({
      project_id: TEST_PROJECT_ID,
      total_count: 2,
      gaps: DUMMY_GAPS,
    });
    vi.spyOn(gapService, "getProjectSources").mockResolvedValue([
      { id: "src-1", title: "Guidelines PDF" },
    ]);
    vi.spyOn(gapService, "getProjectEvidence").mockResolvedValue({
      items: [{ id: "ev-1", claim: "Partial mention" }],
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches gaps, sources, and computes summary statistics upon initialization", async () => {
    const { result } = renderHook(() => useGapAnalysis(TEST_PROJECT_ID));

    // Wait for async load
    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.loading).toBe(false);
    expect(result.current.allGaps.length).toBe(2);
    expect(result.current.sources.length).toBe(1);
    expect(result.current.summary.total).toBe(2);
    expect(result.current.summary.critical).toBe(1);
    expect(result.current.summary.medium).toBe(1);
    expect(result.current.summary.open).toBe(1);
    expect(result.current.summary.investigating).toBe(1);
  });

  it("filters gaps by priority correctly", async () => {
    const { result } = renderHook(() => useGapAnalysis(TEST_PROJECT_ID));

    await act(async () => {
      await Promise.resolve();
    });

    // Filter to critical
    act(() => {
      result.current.setSelectedPriority("critical");
    });
    expect(result.current.gaps.length).toBe(1);
    expect(result.current.gaps[0].id).toBe("gap-1");

    // Filter to low (none)
    act(() => {
      result.current.setSelectedPriority("low");
    });
    expect(result.current.gaps.length).toBe(0);
  });

  it("filters gaps by status and gap type", async () => {
    const { result } = renderHook(() => useGapAnalysis(TEST_PROJECT_ID));

    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      result.current.setSelectedStatus("investigating");
    });
    expect(result.current.gaps.length).toBe(1);
    expect(result.current.gaps[0].id).toBe("gap-2");

    act(() => {
      result.current.setSelectedStatus("all");
      result.current.setSelectedGapType("no_evidence");
    });
    expect(result.current.gaps.length).toBe(1);
    expect(result.current.gaps[0].id).toBe("gap-1");
  });

  it("sorts gaps by priority descending and ascending", async () => {
    const { result } = renderHook(() => useGapAnalysis(TEST_PROJECT_ID));

    await act(async () => {
      await Promise.resolve();
    });

    // Default priority desc: critical first, then medium
    expect(result.current.gaps[0].priority).toBe("critical");
    expect(result.current.gaps[1].priority).toBe("medium");

    // Priority asc: medium first, then critical
    act(() => {
      result.current.setSortBy("priority_asc");
    });
    expect(result.current.gaps[0].priority).toBe("medium");
    expect(result.current.gaps[1].priority).toBe("critical");
  });

  it("runs gap detection and prevents duplicate concurrent execution", async () => {
    let resolveDetect;
    const detectPromise = new Promise((res) => {
      resolveDetect = res;
    });

    const detectSpy = vi.spyOn(gapService, "detectGaps").mockImplementation(() => detectPromise);

    const { result } = renderHook(() => useGapAnalysis(TEST_PROJECT_ID));
    await act(async () => {
      await Promise.resolve();
    });

    // Trigger detection
    let p1;
    act(() => {
      p1 = result.current.runDetection("Check all sections");
    });

    expect(result.current.detecting).toBe(true);

    // Attempt second trigger while detecting is true
    let p2;
    act(() => {
      p2 = result.current.runDetection("Duplicate call");
    });

    // Should only have been called once
    expect(detectSpy).toHaveBeenCalledTimes(1);

    // Resolve detection
    await act(async () => {
      resolveDetect({
        project_id: TEST_PROJECT_ID,
        detection: {
          total_gaps_detected: 1,
          warnings: ["1 source truncated"],
          has_corpus_truncation: true,
        },
        persistence: {
          gaps: [DUMMY_GAPS[0]],
        },
      });
      await p1;
    });

    expect(result.current.detecting).toBe(false);
  });

  it("updates gap review status and notes immutably", async () => {
    const updatedGap = {
      ...DUMMY_GAPS[0],
      status: "resolved",
      confidence_metadata: {
        bharmafills: {
          user_review: { status: "resolved", notes: "Found citation" },
        },
      },
    };

    vi.spyOn(gapService, "updateGapReview").mockResolvedValue(updatedGap);

    const { result } = renderHook(() => useGapAnalysis(TEST_PROJECT_ID));
    await act(async () => {
      await Promise.resolve();
    });

    await act(async () => {
      await result.current.updateReview("gap-1", {
        status: "resolved",
        user_notes: "Found citation",
      });
    });

    const modified = result.current.allGaps.find((g) => g.id === "gap-1");
    expect(modified?.status).toBe("resolved");
    expect(result.current.summary.resolved).toBe(1);
    expect(result.current.summary.open).toBe(0);
  });
});
