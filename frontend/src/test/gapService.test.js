import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { gapService } from "../features/analysis/services/gapService";
import { projectService } from "../services/projectService";
import { apiClient } from "../lib/apiClient";

describe("Information Gap API Service (gapService)", () => {
  const TEST_BACKEND_ID = "11111111-1111-4000-a000-000000000001";

  beforeEach(() => {
    vi.restoreAllMocks();
    projectService.recordIdMapping("local-proj-1", TEST_BACKEND_ID);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("throws honest error if project is not mapped to backend ID", () => {
    expect(() => gapService.resolveProjectId("unmapped-local-id")).toThrow(
      /Project has not been synchronized/i
    );
  });

  it("calls detectGaps endpoint with resolved UUID and payload", async () => {
    const postSpy = vi.spyOn(apiClient, "post").mockResolvedValue({
      project_id: TEST_BACKEND_ID,
      detection: { gaps: [] },
    });

    await gapService.detectGaps("local-proj-1", "Focus on technical criteria");

    expect(postSpy).toHaveBeenCalledTimes(1);
    const [endpoint, body, opts] = postSpy.mock.calls[0];
    expect(endpoint).toBe(`/projects/${TEST_BACKEND_ID}/gaps/detect`);
    expect(body).toEqual({ custom_instructions: "Focus on technical criteria" });
    expect(opts.timeoutMs).toBe(90000);
  });

  it("calls listGaps with query parameter filters", async () => {
    const getSpy = vi.spyOn(apiClient, "get").mockResolvedValue({
      project_id: TEST_BACKEND_ID,
      total_count: 0,
      gaps: [],
    });

    await gapService.listGaps(TEST_BACKEND_ID, {
      status: "investigating",
      priority: "critical",
      gapType: "no_evidence",
    });

    expect(getSpy).toHaveBeenCalledTimes(1);
    const [endpoint, opts] = getSpy.mock.calls[0];
    expect(endpoint).toBe(`/projects/${TEST_BACKEND_ID}/gaps`);
    expect(opts.params).toEqual({
      limit: 100,
      offset: 0,
      status: "investigating",
      priority: "critical",
      gap_type: "no_evidence",
    });
  });

  it("calls getGap for a single gap", async () => {
    const GAP_ID = "aaaa0000-0000-4000-a000-000000000001";
    const getSpy = vi.spyOn(apiClient, "get").mockResolvedValue({ id: GAP_ID });

    await gapService.getGap(TEST_BACKEND_ID, GAP_ID);

    expect(getSpy).toHaveBeenCalledWith(`/projects/${TEST_BACKEND_ID}/gaps/${GAP_ID}`);
  });

  it("validates status and calls updateGapReview with PATCH payload", async () => {
    const GAP_ID = "aaaa0000-0000-4000-a000-000000000001";
    const patchSpy = vi.spyOn(apiClient, "patch").mockResolvedValue({
      id: GAP_ID,
      status: "resolved",
    });

    // Valid update
    await gapService.updateGapReview(TEST_BACKEND_ID, GAP_ID, {
      status: "resolved",
      user_notes: "Verified through government gazette source.",
    });

    expect(patchSpy).toHaveBeenCalledWith(
      `/projects/${TEST_BACKEND_ID}/gaps/${GAP_ID}`,
      {
        status: "resolved",
        user_notes: "Verified through government gazette source.",
      }
    );

    // Invalid status rejected
    await expect(
      gapService.updateGapReview(TEST_BACKEND_ID, GAP_ID, { status: "open" })
    ).rejects.toThrow(/Review status must be/i);

    await expect(
      gapService.updateGapReview(TEST_BACKEND_ID, GAP_ID, { status: "arbitrary" })
    ).rejects.toThrow(/Review status must be/i);
  });
});
