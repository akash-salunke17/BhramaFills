import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  projectService,
  normalizeBackendProject,
  isUuid,
} from "../services/projectService";
import { authService } from "../services/authService";
import { researchService } from "../features/research/services/researchService";
import { apiClient } from "../lib/apiClient";

describe("Project Service & LocalStorage Migration (projectService)", () => {
  beforeEach(async () => {
    authService.clearSession();
    await researchService.clearAll();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("identifies UUID strings accurately", () => {
    expect(isUuid("11111111-1111-4000-a000-000000000001")).toBe(true);
    expect(isUuid("not-a-uuid")).toBe(false);
    expect(isUuid("proj_123456789_abc")).toBe(false);
    expect(isUuid(null)).toBe(false);
  });

  it("normalizes backend project record to frontend camelCase model", () => {
    const rawBackend = {
      id: "11111111-1111-4000-a000-000000000001",
      user_id: "00000000-0000-4000-a000-000000000001",
      title: "Solar Energy Microgrids",
      research_question: "How do microgrids maintain frequency stability under cloud cover?",
      description: "Decentralized PV study.",
      category: "Technology",
      status: "In Progress",
      created_at: "2026-11-01T12:00:00Z",
      updated_at: "2026-11-01T12:30:00Z",
    };

    const normalized = normalizeBackendProject(rawBackend, "local-id-1");
    expect(normalized.id).toBe("11111111-1111-4000-a000-000000000001");
    expect(normalized.backendId).toBe("11111111-1111-4000-a000-000000000001");
    expect(normalized.localId).toBe("local-id-1");
    expect(normalized.researchQuestion).toBe(rawBackend.research_question);
    expect(normalized.isSynced).toBe(true);
  });

  it("records and resolves local-to-backend ID mapping", () => {
    projectService.recordIdMapping("local-proj-99", "22222222-2222-4000-a000-000000000002");
    expect(projectService.resolveBackendId("local-proj-99")).toBe("22222222-2222-4000-a000-000000000002");

    // Resolving an actual UUID directly returns itself
    expect(projectService.resolveBackendId("33333333-3333-4000-a000-000000000003")).toBe(
      "33333333-3333-4000-a000-000000000003"
    );
  });

  it("safely migrates eligible local projects to backend when authenticated", async () => {
    // 1. Create local project
    const local = await researchService.createProject({
      title: "Local Quantum Security",
      researchQuestion: "What post-quantum crypto standards exist for IoT?",
      description: "NIST standards review.",
      category: "Technology",
      status: "Draft",
    });

    // 2. Authenticate
    authService.loginAsDemo();

    // 3. Mock backend GET /projects (currently empty) and POST /projects
    const backendCreated = {
      id: "99999999-9999-4000-a000-000000000099",
      user_id: "00000000-0000-4000-a000-000000000001",
      title: local.title,
      research_question: local.researchQuestion,
      description: local.description,
      category: local.category,
      status: local.status,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    vi.spyOn(apiClient, "get").mockResolvedValue({ projects: [], total_count: 0 });
    const postSpy = vi.spyOn(apiClient, "post").mockResolvedValue(backendCreated);

    // 4. Run migration
    const result = await projectService.migrateLocalProjects();
    expect(result.status).toBe("completed");
    expect(result.migratedCount).toBe(1);
    expect(postSpy).toHaveBeenCalledTimes(1);

    // 5. Verify ID mapping was stored
    expect(projectService.resolveBackendId(local.id)).toBe("99999999-9999-4000-a000-000000000099");
  });

  it("avoids duplicate backend project creation on repeated sync (deduplication)", async () => {
    const local = await researchService.createProject({
      title: "Existing Title",
      researchQuestion: "Existing Question Long Enough Here?",
    });

    authService.loginAsDemo();

    // Mock backend already having a project with matching title and question
    const existingBackend = {
      id: "88888888-8888-4000-a000-000000000088",
      user_id: "00000000-0000-4000-a000-000000000001",
      title: "Existing Title",
      research_question: "Existing Question Long Enough Here?",
      description: null,
      category: "General Research",
      status: "Draft",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    vi.spyOn(apiClient, "get").mockResolvedValue({ projects: [existingBackend], total_count: 1 });
    const postSpy = vi.spyOn(apiClient, "post");

    const result = await projectService.migrateLocalProjects();
    expect(result.status).toBe("completed");
    expect(result.migratedCount).toBe(0); // Zero duplicate calls made
    expect(postSpy).not.toHaveBeenCalled();

    // Mapping linked to existing backend ID
    expect(projectService.resolveBackendId(local.id)).toBe("88888888-8888-4000-a000-000000000088");
  });
});
