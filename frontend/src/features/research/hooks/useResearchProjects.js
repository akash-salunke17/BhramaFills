import { useState, useEffect, useMemo, useCallback } from "react";
import { projectService } from "../../../services/projectService";
import { researchService } from "../services/researchService";
import { authService } from "../../../services/authService";

function computeStats(list) {
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
}

export function useResearchProjects() {
  const [allProjects, setAllProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [searchQuery, setSearchQuery] = useState("");
  const [selectedStatus, setSelectedStatus] = useState("All");
  const [selectedCategory, setSelectedCategory] = useState("All");
  const [sortBy, setSortBy] = useState("recent_updated");

  const [stats, setStats] = useState({
    total: 0,
    draft: 0,
    inProgress: 0,
    completed: 0,
    archived: 0,
    byCategory: {},
  });

  const fetchProjects = useCallback(async () => {
    try {
      const list = await projectService.getAllProjects();
      const computedStats = computeStats(list);
      setAllProjects(list);
      setStats(computedStats);
      setError(null);
    } catch (err) {
      console.error("[useResearchProjects] Failed to load projects:", err);
      setError(err.message || "Failed to load research projects.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let ignore = false;

    async function initialFetch() {
      try {
        const list = await projectService.getAllProjects();
        const computedStats = computeStats(list);
        if (!ignore) {
          setAllProjects(list);
          setStats(computedStats);
          setError(null);
          setLoading(false);
        }
      } catch (err) {
        if (!ignore) {
          console.error("[useResearchProjects] Failed to load projects:", err);
          setError(err.message || "Failed to load research projects.");
          setLoading(false);
        }
      }
    }

    initialFetch();

    const unsubStorage = researchService.subscribe(() => {
      initialFetch();
    });

    const unsubAuth = authService.subscribe(() => {
      initialFetch();
    });

    return () => {
      ignore = true;
      unsubStorage();
      unsubAuth();
    };
  }, []);

  // Filtering and Sorting logic
  const filteredProjects = useMemo(() => {
    let result = [...allProjects];

    // Status filter
    if (selectedStatus && selectedStatus !== "All") {
      result = result.filter((p) => p.status === selectedStatus);
    }

    // Category filter
    if (selectedCategory && selectedCategory !== "All") {
      result = result.filter((p) => p.category === selectedCategory);
    }

    // Search query filter (title, question, description)
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      result = result.filter((p) => {
        const titleMatch = (p.title || "").toLowerCase().includes(q);
        const questionMatch = (p.researchQuestion || "").toLowerCase().includes(q);
        const descMatch = (p.description || "").toLowerCase().includes(q);
        return titleMatch || questionMatch || descMatch;
      });
    }

    // Sorting with safe timestamp fallback and stable tie-breaking
    result.sort((a, b) => {
      if (sortBy === "recent_created") {
        const timeB = new Date(b.createdAt || 0).getTime() || 0;
        const timeA = new Date(a.createdAt || 0).getTime() || 0;
        if (timeB !== timeA) return timeB - timeA;
        return (a.title || "").localeCompare(b.title || "");
      }
      if (sortBy === "alphabetical") {
        return (a.title || "").localeCompare(b.title || "", undefined, { sensitivity: "base" });
      }
      // default: recent_updated
      const timeB = new Date(b.updatedAt || b.createdAt || 0).getTime() || 0;
      const timeA = new Date(a.updatedAt || a.createdAt || 0).getTime() || 0;
      if (timeB !== timeA) return timeB - timeA;
      return (a.title || "").localeCompare(b.title || "");
    });

    return result;
  }, [allProjects, selectedStatus, selectedCategory, searchQuery, sortBy]);

  const createProject = useCallback(async (data) => {
    setError(null);
    try {
      const created = await projectService.createProject(data);
      await fetchProjects();
      return created;
    } catch (err) {
      setError(err.message);
      throw err;
    }
  }, [fetchProjects]);

  const updateProject = useCallback(async (id, data) => {
    setError(null);
    try {
      const updated = await projectService.updateProject(id, data);
      await fetchProjects();
      return updated;
    } catch (err) {
      setError(err.message);
      throw err;
    }
  }, [fetchProjects]);

  const deleteProject = useCallback(async (id) => {
    setError(null);
    try {
      const success = await projectService.deleteProject(id);
      await fetchProjects();
      return success;
    } catch (err) {
      setError(err.message);
      throw err;
    }
  }, [fetchProjects]);

  return {
    allProjects,
    projects: filteredProjects,
    totalCount: allProjects.length,
    filteredCount: filteredProjects.length,
    loading,
    error,
    stats,
    searchQuery,
    setSearchQuery,
    selectedStatus,
    setSelectedStatus,
    selectedCategory,
    setSelectedCategory,
    sortBy,
    setSortBy,
    createProject,
    updateProject,
    deleteProject,
    refresh: fetchProjects,
  };
}
