import {
  validateResearchProject,
  DEFAULT_CATEGORY,
  DEFAULT_STATUS,
  CATEGORIES,
  STATUSES,
} from "../schemas/researchValidation";

const STORAGE_KEY = "bharmafills_research_projects_v1";
const CORRUPTED_BACKUP_KEY = "bharmafills_research_corrupted_backup";

// In-memory fallback when localStorage is unavailable
let inMemoryFallback = null;

// Listeners for reactive updates
const listeners = new Set();

function notifyListeners() {
  listeners.forEach((listener) => {
    try {
      listener();
    } catch (err) {
      console.error("[researchService] Listener error:", err);
    }
  });
}

function generateId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "proj_" + Date.now() + "_" + Math.random().toString(36).slice(2, 9);
}

function getStorage() {
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      return window.localStorage;
    }
  } catch {
    // Storage access blocked or restricted (e.g. SecurityError in strict sandboxes)
  }
  return null;
}

function isValidIsoDate(str) {
  if (typeof str !== "string" || !str) return false;
  const d = new Date(str);
  return !Number.isNaN(d.getTime());
}

/**
 * Deep clones an item to enforce strict data isolation.
 */
function cloneProject(item) {
  if (!item || typeof item !== "object") return null;
  return {
    id: String(item.id),
    title: String(item.title),
    researchQuestion: String(item.researchQuestion || ""),
    description: String(item.description || ""),
    category: String(item.category || DEFAULT_CATEGORY),
    status: String(item.status || DEFAULT_STATUS),
    createdAt: String(item.createdAt),
    updatedAt: String(item.updatedAt),
  };
}

/**
 * Sanitizes an array of records loaded from storage:
 * - Drops completely invalid items (non-objects or missing id/title)
 * - Validates category and status
 * - Normalizes invalid timestamps
 * - Eliminates duplicate IDs
 */
function sanitizeRecords(records) {
  if (!Array.isArray(records)) return [];

  const seenIds = new Set();
  const valid = [];

  for (const item of records) {
    if (!item || typeof item !== "object") continue;

    const id = typeof item.id === "string" ? item.id.trim() : "";
    const title = typeof item.title === "string" ? item.title.trim() : "";
    if (!id || !title || seenIds.has(id)) continue;

    seenIds.add(id);

    const now = new Date().toISOString();
    const createdAt = isValidIsoDate(item.createdAt) ? item.createdAt : now;
    const updatedAt = isValidIsoDate(item.updatedAt) ? item.updatedAt : createdAt;

    const category = CATEGORIES.includes(item.category)
      ? item.category
      : DEFAULT_CATEGORY;
    const status = STATUSES.includes(item.status) ? item.status : DEFAULT_STATUS;

    valid.push({
      id,
      title,
      researchQuestion: typeof item.researchQuestion === "string" ? item.researchQuestion.trim() : "",
      description: typeof item.description === "string" ? item.description.trim() : "",
      category,
      status,
      createdAt,
      updatedAt,
    });
  }

  return valid;
}

function readFromStorage() {
  const storage = getStorage();
  if (!storage) {
    return inMemoryFallback ? sanitizeRecords(inMemoryFallback) : [];
  }

  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return [];

    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (parseErr) {
      console.error("[researchService] Corrupted JSON detected. Preserving backup key:", parseErr);
      // Preserve corrupted data to avoid silent loss
      try {
        storage.setItem(`${CORRUPTED_BACKUP_KEY}_${Date.now()}`, raw);
      } catch {
        // Ignore backup failure
      }
      return [];
    }

    if (!Array.isArray(parsed)) {
      console.warn("[researchService] Non-array storage item detected.");
      return [];
    }

    return sanitizeRecords(parsed);
  } catch (err) {
    console.error("[researchService] Read storage error:", err);
    return [];
  }
}

function writeToStorage(projects) {
  const sanitized = sanitizeRecords(projects);
  const storage = getStorage();

  if (!storage) {
    inMemoryFallback = [...sanitized];
    notifyListeners();
    return;
  }

  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(sanitized));
    notifyListeners();
  } catch (err) {
    console.error("[researchService] Failed writing to storage:", err);
    // If quota is exceeded, throw clear error and do NOT overwrite valid storage
    const error = new Error("Storage quota exceeded or storage write denied. Your changes could not be saved to disk.");
    error.name = "QuotaExceededError";
    error.originalError = err;
    throw error;
  }
}

export const researchService = {
  STORAGE_KEY,
  CORRUPTED_BACKUP_KEY,

  /**
   * Check whether persistent browser storage is available.
   * @returns {{ persistent: boolean, warning?: string }}
   */
  getStorageHealth() {
    const storage = getStorage();
    if (!storage) {
      return {
        persistent: false,
        warning: "Browser storage is unavailable. Projects are kept in temporary session memory only and will not persist after page refresh.",
      };
    }
    return { persistent: true };
  },

  /**
   * Subscribe to project updates.
   * @param {() => void} callback
   * @returns {() => void} Unsubscribe function
   */
  subscribe(callback) {
    listeners.add(callback);
    return () => listeners.delete(callback);
  },

  /**
   * Retrieve all research projects.
   * @returns {Promise<Array<Object>>}
   */
  async getAllProjects() {
    const list = readFromStorage();
    return list.map(cloneProject);
  },

  /**
   * Retrieve a single project by ID.
   * @param {string} id
   * @returns {Promise<Object|null>}
   */
  async getProjectById(id) {
    if (!id || typeof id !== "string") return null;
    const list = readFromStorage();
    const found = list.find((item) => item.id === id);
    return found ? cloneProject(found) : null;
  },

  /**
   * Create a new research project.
   * @param {Object} projectData
   * @returns {Promise<Object>} The created project
   */
  async createProject(projectData) {
    const validation = validateResearchProject(projectData);
    if (!validation.isValid) {
      const firstError = Object.values(validation.errors)[0] || "Validation failed";
      const error = new Error(firstError);
      error.validationErrors = validation.errors;
      throw error;
    }

    const now = new Date().toISOString();
    const newProject = {
      id: generateId(),
      title: validation.cleanedData.title,
      researchQuestion: validation.cleanedData.researchQuestion,
      description: validation.cleanedData.description,
      category: validation.cleanedData.category,
      status: validation.cleanedData.status || DEFAULT_STATUS,
      createdAt: now,
      updatedAt: now,
    };

    const current = readFromStorage();
    // Prevent duplicate ID collision
    if (current.some((item) => item.id === newProject.id)) {
      newProject.id = generateId() + "_alt";
    }

    current.unshift(newProject);
    writeToStorage(current);

    return cloneProject(newProject);
  },

  /**
   * Update an existing research project.
   * @param {string} id
   * @param {Object} updates
   * @returns {Promise<Object>} The updated project
   */
  async updateProject(id, updates) {
    if (!id || typeof id !== "string") {
      throw new Error("Valid project ID is required for updating.");
    }

    const current = readFromStorage();
    const index = current.findIndex((item) => item.id === id);
    if (index === -1) {
      throw new Error(`Project with id "${id}" was not found.`);
    }

    const existing = current[index];
    const merged = {
      title: updates?.title !== undefined ? updates.title : existing.title,
      researchQuestion:
        updates?.researchQuestion !== undefined
          ? updates.researchQuestion
          : existing.researchQuestion,
      description:
        updates?.description !== undefined ? updates.description : existing.description,
      category: updates?.category !== undefined ? updates.category : existing.category,
      status: updates?.status !== undefined ? updates.status : existing.status,
    };

    const validation = validateResearchProject(merged);
    if (!validation.isValid) {
      const firstError = Object.values(validation.errors)[0] || "Validation failed";
      const error = new Error(firstError);
      error.validationErrors = validation.errors;
      throw error;
    }

    const updated = {
      ...existing,
      ...validation.cleanedData,
      id: existing.id,
      createdAt: existing.createdAt, // Preserve original createdAt
      updatedAt: new Date().toISOString(),
    };

    current[index] = updated;
    writeToStorage(current);

    return cloneProject(updated);
  },

  /**
   * Delete a research project by ID.
   * @param {string} id
   * @returns {Promise<boolean>}
   */
  async deleteProject(id) {
    if (!id || typeof id !== "string") {
      throw new Error("Valid project ID is required for deletion.");
    }

    const current = readFromStorage();
    const index = current.findIndex((item) => item.id === id);
    if (index === -1) {
      throw new Error(`Project with id "${id}" was not found.`);
    }

    current.splice(index, 1);
    writeToStorage(current);

    return true;
  },

  /**
   * Compute aggregated statistics for projects.
   * @returns {Promise<{ total: number, draft: number, inProgress: number, completed: number, archived: number, byCategory: Record<string, number> }>}
   */
  async getProjectStats() {
    const list = readFromStorage();
    const stats = {
      total: list.length,
      draft: 0,
      inProgress: 0,
      completed: 0,
      archived: 0,
      byCategory: {},
    };

    list.forEach((item) => {
      if (item.status === "Draft") stats.draft += 1;
      else if (item.status === "In Progress") stats.inProgress += 1;
      else if (item.status === "Completed") stats.completed += 1;
      else if (item.status === "Archived") stats.archived += 1;

      if (item.category) {
        stats.byCategory[item.category] = (stats.byCategory[item.category] || 0) + 1;
      }
    });

    return stats;
  },

  /**
   * Clear all projects (test helper only).
   */
  async clearAll() {
    const storage = getStorage();
    if (storage) {
      try {
        storage.removeItem(STORAGE_KEY);
      } catch {
        // Ignore
      }
    }
    inMemoryFallback = [];
    notifyListeners();
  },
};
