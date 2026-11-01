/**
 * Gap analysis API service interacting with protected backend endpoints.
 */

import { apiClient } from "../../../lib/apiClient";
import { projectService } from "../../../services/projectService";

export const gapService = {
  /**
   * Resolve valid backend project UUID. Throws if project has no backend ID.
   */
  resolveProjectId(projectId) {
    const backendId = projectService.resolveBackendId(projectId);
    if (!backendId) {
      throw new Error(
        "Project has not been synchronized with the cloud database. Please sign in or ensure the project is saved."
      );
    }
    return backendId;
  },

  /**
   * Run AI gap detection and transactional persistence.
   * @param {string} projectId Project UUID
   * @param {string|null} customInstructions Optional guidance for the AI model
   */
  async detectGaps(projectId, customInstructions = null) {
    const resolvedId = this.resolveProjectId(projectId);
    const body = customInstructions && customInstructions.trim()
      ? { custom_instructions: customInstructions.trim() }
      : null;

    // AI completions can take up to 60-90s
    return await apiClient.post(`/projects/${resolvedId}/gaps/detect`, body, {
      timeoutMs: 90000,
    });
  },

  /**
   * List persisted information gaps for a project.
   */
  async listGaps(projectId, { status = null, priority = null, gapType = null, limit = 100, offset = 0 } = {}) {
    const resolvedId = this.resolveProjectId(projectId);
    const params = {
      limit,
      offset,
    };
    if (status && status !== "all") params.status = status;
    if (priority && priority !== "all") params.priority = priority;
    if (gapType && gapType !== "all") params.gap_type = gapType;

    return await apiClient.get(`/projects/${resolvedId}/gaps`, { params });
  },

  /**
   * Retrieve a single gap by ID.
   */
  async getGap(projectId, gapId) {
    const resolvedId = this.resolveProjectId(projectId);
    return await apiClient.get(`/projects/${resolvedId}/gaps/${gapId}`);
  },

  /**
   * Update review status ('investigating', 'resolved', 'dismissed') and user notes on a gap.
   */
  async updateGapReview(projectId, gapId, { status, user_notes = null }) {
    const resolvedId = this.resolveProjectId(projectId);
    if (!status || !["investigating", "resolved", "dismissed"].includes(status)) {
      throw new Error("Review status must be 'investigating', 'resolved', or 'dismissed'.");
    }

    const payload = {
      status,
      user_notes: user_notes && user_notes.trim() ? user_notes.trim() : null,
    };

    return await apiClient.patch(`/projects/${resolvedId}/gaps/${gapId}`, payload);
  },

  /**
   * Retrieve project sources to check extraction readiness.
   */
  async getProjectSources(projectId) {
    const resolvedId = this.resolveProjectId(projectId);
    return await apiClient.get(`/projects/${resolvedId}/sources`);
  },

  /**
   * Retrieve extracted evidence facts and claims for a project.
   */
  async getProjectEvidence(projectId, options = {}) {
    const resolvedId = this.resolveProjectId(projectId);
    return await apiClient.get(`/projects/${resolvedId}/evidence`, { params: options });
  },
};
