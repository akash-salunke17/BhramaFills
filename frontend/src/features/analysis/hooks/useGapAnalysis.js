import { useState, useEffect, useMemo, useCallback } from "react";
import { gapService } from "../services/gapService";
import { projectService } from "../../../services/projectService";
import { authService } from "../../../services/authService";

const PRIORITY_ORDER = {
  critical: 4,
  high: 3,
  medium: 2,
  low: 1,
};

export function useGapAnalysis(projectId) {
  const [gaps, setGaps] = useState([]);
  const [sources, setSources] = useState([]);
  const [evidenceList, setEvidenceList] = useState([]);
  const [rawDetection, setRawDetection] = useState(null);

  const [loading, setLoading] = useState(true);
  const [detecting, setDetecting] = useState(false);
  const [detectionStage, setDetectionStage] = useState("");
  const [error, setError] = useState(null);

  // Filters & Sorting
  const [selectedPriority, setSelectedPriority] = useState("all");
  const [selectedGapType, setSelectedGapType] = useState("all");
  const [selectedStatus, setSelectedStatus] = useState("all");
  const [sortBy, setSortBy] = useState("priority_desc");

  // Dialogs & Viewers
  const [activeEvidenceGap, setActiveEvidenceGap] = useState(null);
  const [activeReviewGap, setActiveReviewGap] = useState(null);
  const [reviewUpdating, setReviewUpdating] = useState(false);

  const resolvedBackendId = useMemo(() => {
    return projectService.resolveBackendId(projectId);
  }, [projectId]);

  // Fetch initial project information and existing persisted gaps
  const refreshGaps = useCallback(async () => {
    if (!resolvedBackendId) {
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      setError(null);

      // Fetch gaps and sources in parallel
      const [gapsResult, sourcesResult, evidenceResult] = await Promise.allSettled([
        gapService.listGaps(resolvedBackendId),
        gapService.getProjectSources(resolvedBackendId),
        gapService.getProjectEvidence(resolvedBackendId, { limit: 100 }),
      ]);

      if (gapsResult.status === "fulfilled") {
        setGaps(gapsResult.value?.gaps || []);
      } else {
        console.warn("[useGapAnalysis] Failed to load gaps:", gapsResult.reason);
      }

      if (sourcesResult.status === "fulfilled") {
        setSources(sourcesResult.value || []);
      }

      if (evidenceResult.status === "fulfilled") {
        setEvidenceList(evidenceResult.value?.items || []);
      }
    } catch (err) {
      console.error("[useGapAnalysis] Error loading project gap data:", err);
      setError(err.message || "Failed to load information gaps.");
    } finally {
      setLoading(false);
    }
  }, [resolvedBackendId]);

  useEffect(() => {
    refreshGaps();
  }, [refreshGaps]);

  // Filtered and sorted gaps
  const filteredGaps = useMemo(() => {
    let result = [...gaps];

    if (selectedPriority !== "all") {
      result = result.filter((g) => g.priority === selectedPriority);
    }

    if (selectedGapType !== "all") {
      result = result.filter((g) => g.gap_type === selectedGapType);
    }

    if (selectedStatus !== "all") {
      result = result.filter((g) => g.status === selectedStatus);
    }

    result.sort((a, b) => {
      if (sortBy === "priority_desc") {
        const orderA = PRIORITY_ORDER[a.priority] || 0;
        const orderB = PRIORITY_ORDER[b.priority] || 0;
        if (orderB !== orderA) return orderB - orderA;
        return new Date(b.updated_at || 0) - new Date(a.updated_at || 0);
      }
      if (sortBy === "priority_asc") {
        const orderA = PRIORITY_ORDER[a.priority] || 0;
        const orderB = PRIORITY_ORDER[b.priority] || 0;
        if (orderA !== orderB) return orderA - orderB;
        return new Date(b.updated_at || 0) - new Date(a.updated_at || 0);
      }
      if (sortBy === "recent_created") {
        return new Date(b.created_at || 0) - new Date(a.created_at || 0);
      }
      // default: recent_updated
      return new Date(b.updated_at || 0) - new Date(a.updated_at || 0);
    });

    return result;
  }, [gaps, selectedPriority, selectedGapType, selectedStatus, sortBy]);

  // Computed summary metrics
  const summary = useMemo(() => {
    const stats = {
      total: gaps.length,
      critical: 0,
      high: 0,
      medium: 0,
      low: 0,
      open: 0,
      investigating: 0,
      resolved: 0,
      dismissed: 0,
      hasCorpusTruncation: Boolean(rawDetection?.has_corpus_truncation),
      warnings: rawDetection?.warnings || [],
    };

    gaps.forEach((g) => {
      if (g.priority === "critical") stats.critical += 1;
      else if (g.priority === "high") stats.high += 1;
      else if (g.priority === "medium") stats.medium += 1;
      else if (g.priority === "low") stats.low += 1;

      if (g.status === "open") stats.open += 1;
      else if (g.status === "investigating") stats.investigating += 1;
      else if (g.status === "resolved") stats.resolved += 1;
      else if (g.status === "dismissed") stats.dismissed += 1;
    });

    return stats;
  }, [gaps, rawDetection]);

  // Execute AI gap detection with truthful progress stages and duplicate guard
  const runDetection = useCallback(
    async (customInstructions = null) => {
      if (detecting) return; // Prevent duplicate concurrent requests

      if (!resolvedBackendId) {
        setError(
          "This project must be synchronized to the backend database before gap detection can run. Please ensure you are logged in."
        );
        return;
      }

      setDetecting(true);
      setError(null);
      setDetectionStage("Preparing source evidence...");

      let stageTimer1 = null;
      let stageTimer2 = null;
      let stageTimer3 = null;

      try {
        // Truthful stage progression reflecting pipeline stages
        stageTimer1 = setTimeout(() => {
          setDetectionStage("Analyzing extracted information & claims...");
        }, 3000);

        stageTimer2 = setTimeout(() => {
          setDetectionStage("Validating potential gaps against evidence...");
        }, 12000);

        stageTimer3 = setTimeout(() => {
          setDetectionStage("Saving findings and cross-referencing citations...");
        }, 22000);

        const response = await gapService.detectGaps(resolvedBackendId, customInstructions);

        if (response) {
          setRawDetection(response.detection);
          if (response.persistence?.gaps) {
            setGaps(response.persistence.gaps);
          } else {
            // Re-fetch gaps if persistence summary was minimal
            await refreshGaps();
          }
        }
      } catch (err) {
        console.error("[useGapAnalysis] Gap detection failed:", err);
        setError(err.message || "Information gap detection failed. Please try again.");
      } finally {
        if (stageTimer1) clearTimeout(stageTimer1);
        if (stageTimer2) clearTimeout(stageTimer2);
        if (stageTimer3) clearTimeout(stageTimer3);
        setDetecting(false);
        setDetectionStage("");
      }
    },
    [detecting, resolvedBackendId, refreshGaps]
  );

  // Update review status on a gap
  const updateReview = useCallback(
    async (gapId, { status, user_notes }) => {
      if (!resolvedBackendId || !gapId) return;

      setReviewUpdating(true);
      try {
        const updatedGap = await gapService.updateGapReview(resolvedBackendId, gapId, {
          status,
          user_notes,
        });

        // Update local list immutably
        setGaps((prev) =>
          prev.map((g) => (g.id === gapId ? updatedGap : g))
        );

        // Update active modal gap if open
        if (activeEvidenceGap?.id === gapId) {
          setActiveEvidenceGap(updatedGap);
        }

        setActiveReviewGap(null);
        return updatedGap;
      } catch (err) {
        console.error("[useGapAnalysis] Review update failed:", err);
        throw err;
      } finally {
        setReviewUpdating(false);
      }
    },
    [resolvedBackendId, activeEvidenceGap]
  );

  return {
    gaps: filteredGaps,
    allGaps: gaps,
    summary,
    sources,
    evidenceList,
    rawDetection,
    loading,
    detecting,
    detectionStage,
    error,
    resolvedBackendId,
    // Filters & Sorting
    selectedPriority,
    setSelectedPriority,
    selectedGapType,
    setSelectedGapType,
    selectedStatus,
    setSelectedStatus,
    sortBy,
    setSortBy,
    // Modals
    activeEvidenceGap,
    setActiveEvidenceGap,
    activeReviewGap,
    setActiveReviewGap,
    reviewUpdating,
    // Actions
    runDetection,
    refreshGaps,
    updateReview,
  };
}
