/**
 * Project service bridging client-side LocalStorage and Supabase PostgreSQL backend CRUD.
 * Handles safe data migration, ID mapping, and offline/online reconciliation.
 */

import { apiClient, ApiClientError } from "../lib/apiClient";
import { authService } from "./authService";
import { researchService } from "../features/research/services/researchService";
import { validateResearchProject } from "../features/research/schemas/researchValidation";

const MAPPING_STORAGE_KEY = "bharmafills_project_id_mapping";

function getStorage() {
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      return window.localStorage;
    }
  } catch {
    // Restricted environment
  }
  return null;
}

/**
 * Normalizes backend project snake_case record to frontend camelCase model.
 */
export function normalizeBackendProject(bp, localId = null) {
  if (!bp || typeof bp !== "object") return null;
  return {
    id: String(bp.id),
    backendId: String(bp.id),
    localId: localId || String(bp.id),
    userId: bp.user_id ? String(bp.user_id) : null,
    title: String(bp.title || ""),
    researchQuestion: String(bp.research_question || ""),
    description: bp.description ? String(bp.description) : "",
    category: String(bp.category || "General Research"),
    status: String(bp.status || "Draft"),
    createdAt: String(bp.created_at || new Date().toISOString()),
    updatedAt: String(bp.updated_at || bp.created_at || new Date().toISOString()),
    isSynced: true,
  };
}

/**
 * Checks if a string is a standard UUID v4 format.
 */
export function isUuid(str) {
  if (typeof str !== "string") return false;
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(str.trim());
}

export const projectService = {
  /**
   * Retrieve the local-to-backend ID mapping dictionary.
   */
  getIdMapping() {
    const storage = getStorage();
    if (storage) {
      try {
        const raw = storage.getItem(MAPPING_STORAGE_KEY);
        if (raw) {
          const parsed = JSON.parse(raw);
          if (parsed && typeof parsed === "object") return parsed;
        }
      } catch (err) {
        console.warn("[projectService] Failed reading ID mapping:", err);
      }
    }
    return {};
  },

  /**
   * Record a mapping from local project ID to backend PostgreSQL UUID.
   */
  recordIdMapping(localId, backendId) {
    if (!localId || !backendId) return;
    const mapping = this.getIdMapping();
    mapping[String(localId)] = String(backendId);
    const storage = getStorage();
    if (storage) {
      try {
        storage.setItem(MAPPING_STORAGE_KEY, JSON.stringify(mapping));
      } catch (err) {
        console.warn("[projectService] Failed storing ID mapping:", err);
      }
    }
  },

  /**
   * Resolve the active backend ID for a project.
   */
  resolveBackendId(id) {
    if (!id) return null;
    if (isUuid(id)) return id;
    const mapping = this.getIdMapping();
    return mapping[id] || null;
  },

  /**
   * Synchronize / migrate eligible LocalStorage projects to backend PostgreSQL.
   */
  async migrateLocalProjects() {
    if (!authService.isAuthenticated()) {
      return { status: "unauthenticated", migratedCount: 0, errors: [] };
    }

    const localProjects = await researchService.getAllProjects();
    if (!localProjects || localProjects.length === 0) {
      return { status: "no_data", migratedCount: 0, errors: [] };
    }

    const mapping = this.getIdMapping();
    let backendProjects = [];
    try {
      const resp = await apiClient.get("/projects?limit=200");
      backendProjects = resp?.projects || [];
    } catch (err) {
      console.warn("[projectService] Failed fetching existing backend projects for reconciliation:", err);
      return { status: "backend_unavailable", error: err.message, migratedCount: 0 };
    }

    let migratedCount = 0;
    const errors = [];

    for (const lp of localProjects) {
      const existingMappedBackendId = mapping[lp.id];

      // If already mapped and exists in backend, skip
      if (existingMappedBackendId && backendProjects.some((bp) => bp.id === existingMappedBackendId)) {
        continue;
      }

      // Check for deduplication by exact title & question match
      const matchingBackend = backendProjects.find(
        (bp) =>
          bp.title.trim().toLowerCase() === lp.title.trim().toLowerCase() &&
          bp.research_question.trim().toLowerCase() === lp.researchQuestion.trim().toLowerCase()
      );

      if (matchingBackend) {
        // Link existing backend record without duplicate insertion
        this.recordIdMapping(lp.id, matchingBackend.id);
        continue;
      }

      // Project needs migration to backend
      try {
        // Ensure minimum length constraints before inserting into DB
        const title = lp.title.trim().length >= 3 ? lp.title.trim() : lp.title.trim().padEnd(3, ".");
        const question =
          lp.researchQuestion.trim().length >= 10
            ? lp.researchQuestion.trim()
            : lp.researchQuestion.trim().padEnd(10, ".");

        const createdBackend = await apiClient.post("/projects", {
          title,
          research_question: question,
          description: lp.description ? lp.description.trim() : null,
          category: lp.category || "General Research",
          status: lp.status || "Draft",
        });

        if (createdBackend && createdBackend.id) {
          this.recordIdMapping(lp.id, createdBackend.id);
          backendProjects.push(createdBackend);
          migratedCount += 1;
        }
      } catch (err) {
        console.error(`[projectService] Failed to migrate project "${lp.title}":`, err);
        errors.push({ projectId: lp.id, title: lp.title, error: err.message });
      }
    }

    return {
      status: errors.length === 0 ? "completed" : "partial",
      migratedCount,
      totalCount: localProjects.length,
      errors,
    };
  },

  /**
   * Retrieve all projects.
   * If authenticated, loads backend projects and merges with any unsynced local projects.
   * If unauthenticated, loads local projects.
   */
  async getAllProjects() {
    if (authService.isAuthenticated()) {
      try {
        // Auto-run migration reconciliation in background
        this.migrateLocalProjects().catch((err) => {
          console.warn("[projectService] Background migration sync notice:", err);
        });

        const resp = await apiClient.get("/projects?limit=200");
        const backendList = (resp?.projects || []).map((bp) => normalizeBackendProject(bp));

        // Also check if any local projects are not yet in backendList
        const localList = await researchService.getAllProjects();
        const mapping = this.getIdMapping();
        const backendIdSet = new Set(backendList.map((p) => p.id));

        const unsyncedLocal = localList
          .filter((lp) => {
            const mappedId = mapping[lp.id];
            return !mappedId || !backendIdSet.has(mappedId);
          })
          .map((lp) => ({ ...lp, isSynced: false, backendId: mapping[lp.id] || null }));

        return [...backendList, ...unsyncedLocal];
      } catch (err) {
        console.warn("[projectService] Backend unavailable, falling back to LocalStorage:", err);
      }
    }

    // Unauthenticated or fallback
    const localList = await researchService.getAllProjects();
    const mapping = this.getIdMapping();
    return localList.map((lp) => ({
      ...lp,
      backendId: mapping[lp.id] || (isUuid(lp.id) ? lp.id : null),
      isSynced: Boolean(mapping[lp.id] || isUuid(lp.id)),
    }));
  },

  /**
   * Retrieve a single project by ID.
   */
  async getProjectById(id) {
    if (!id) return null;

    const backendId = this.resolveBackendId(id);

    if (authService.isAuthenticated() && backendId) {
      try {
        const bp = await apiClient.get(`/projects/${backendId}`);
        if (bp) {
          return normalizeBackendProject(bp, id !== backendId ? id : null);
        }
      } catch (err) {
        if (!(err instanceof ApiClientError && err.status === 404)) {
          console.warn(`[projectService] Error fetching project ${backendId} from backend:`, err);
        }
      }
    }

    // Local fallback
    const local = await researchService.getProjectById(id);
    if (local) {
      return {
        ...local,
        backendId: backendId || null,
        isSynced: Boolean(backendId),
      };
    }
    return null;
  },

  /**
   * Create a new research project.
   */
  async createProject(projectData) {
    const validation = validateResearchProject(projectData);
    if (!validation.isValid) {
      const firstError = Object.values(validation.errors)[0] || "Validation failed";
      const err = new Error(firstError);
      err.validationErrors = validation.errors;
      throw err;
    }

    // Always create locally first so user never loses data
    const localProject = await researchService.createProject(projectData);

    // If authenticated, also create in Supabase PostgreSQL
    if (authService.isAuthenticated()) {
      try {
        const bp = await apiClient.post("/projects", {
          title: validation.cleanedData.title,
          research_question: validation.cleanedData.researchQuestion,
          description: validation.cleanedData.description,
          category: validation.cleanedData.category,
          status: validation.cleanedData.status,
        });

        if (bp && bp.id) {
          this.recordIdMapping(localProject.id, bp.id);
          return normalizeBackendProject(bp, localProject.id);
        }
      } catch (err) {
        console.warn("[projectService] Backend project creation deferred to next sync:", err);
      }
    }

    return {
      ...localProject,
      backendId: null,
      isSynced: false,
    };
  },

  /**
   * Update an existing research project.
   */
  async updateProject(id, updates) {
    const backendId = this.resolveBackendId(id);

    // Update in backend if authenticated and backendId exists
    let updatedBackend = null;
    if (authService.isAuthenticated() && backendId) {
      try {
        const payload = {};
        if (updates.title !== undefined) payload.title = updates.title;
        if (updates.researchQuestion !== undefined) payload.research_question = updates.researchQuestion;
        if (updates.description !== undefined) payload.description = updates.description;
        if (updates.category !== undefined) payload.category = updates.category;
        if (updates.status !== undefined) payload.status = updates.status;

        updatedBackend = await apiClient.patch(`/projects/${backendId}`, payload);
      } catch (err) {
        console.warn(`[projectService] Failed updating backend project ${backendId}:`, err);
      }
    }

    // Also update locally
    const updatedLocal = await researchService.updateProject(id, updates).catch(() => null);

    if (updatedBackend) {
      return normalizeBackendProject(updatedBackend, id !== backendId ? id : null);
    }
    return updatedLocal;
  },

  /**
   * Delete a research project.
   */
  async deleteProject(id) {
    const backendId = this.resolveBackendId(id);

    if (authService.isAuthenticated() && backendId) {
      try {
        await apiClient.delete(`/projects/${backendId}`);
      } catch (err) {
        console.warn(`[projectService] Failed deleting project ${backendId} on backend:`, err);
      }
    }

    // Also remove locally
    try {
      await researchService.deleteProject(id);
    } catch {
      // Ignore if was only on backend
    }

    return true;
  },
};
