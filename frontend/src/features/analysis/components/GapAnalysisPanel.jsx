import { useState } from "react";
import {
  Sparkles,
  RefreshCw,
  AlertTriangle,
  RotateCcw,
  CheckCircle2,
  HelpCircle,
  Database,
  ArrowRight,
} from "lucide-react";
import { useGapAnalysis } from "../hooks/useGapAnalysis";
import GapAnalysisSummary from "./GapAnalysisSummary";
import GapFilters from "./GapFilters";
import GapCard from "./GapCard";
import GapEvidenceViewer from "./GapEvidenceViewer";
import GapReviewDialog from "./GapReviewDialog";
import GapEmptyState from "./GapEmptyState";
import GapAnalysisSkeleton from "./GapAnalysisSkeleton";
import { authService } from "../../../services/authService";
import { projectService } from "../../../services/projectService";

export default function GapAnalysisPanel({ project, onSyncProject }) {
  const projectId = project?.backendId || project?.id;

  const {
    gaps,
    allGaps,
    summary,
    sources,
    evidenceList,
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
  } = useGapAnalysis(projectId);

  const [showRerunConfirm, setShowRerunConfirm] = useState(false);
  const [successToast, setSuccessToast] = useState("");

  const triggerToast = (msg) => {
    setSuccessToast(msg);
    setTimeout(() => setSuccessToast(""), 4000);
  };

  const handleRunClick = () => {
    if (allGaps.length > 0) {
      setShowRerunConfirm(true);
    } else {
      runDetection();
    }
  };

  const handleConfirmRerun = () => {
    setShowRerunConfirm(false);
    runDetection();
  };

  const handleSaveReview = async (gapId, updateData) => {
    await updateReview(gapId, updateData);
    triggerToast(`Gap review status updated to "${updateData.status}".`);
  };

  const handleSyncClick = async () => {
    if (onSyncProject) {
      onSyncProject();
    } else {
      if (!authService.isAuthenticated()) {
        authService.loginAsDemo();
      }
      await projectService.migrateLocalProjects();
      await refreshGaps();
    }
  };

  return (
    <div className="space-y-6">
      {/* Panel Action Header */}
      <div className="flex flex-col gap-4 rounded-2xl border bg-card p-5 shadow-sm sm:flex-row sm:items-center sm:justify-between sm:p-6">
        <div>
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Sparkles size={16} />
            </span>
            <h2 className="text-lg font-bold tracking-tight text-foreground sm:text-xl">
              Information Gap Analysis
            </h2>
          </div>
          <p className="mt-1 text-xs text-muted-foreground sm:text-sm">
            AI-assisted deficit detection, evidence grounding &amp; coverage verification
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          {/* Refresh persisted gaps button */}
          <button
            type="button"
            onClick={refreshGaps}
            disabled={loading || detecting}
            aria-label="Refresh gap findings"
            className="inline-flex items-center gap-1.5 rounded-xl border bg-background px-3 py-2 text-xs font-semibold text-foreground shadow-sm hover:bg-muted disabled:opacity-50"
          >
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
            <span className="hidden sm:inline">Refresh</span>
          </button>

          {/* Primary Action: Run / Rerun Detection */}
          {resolvedBackendId ? (
            <button
              type="button"
              onClick={handleRunClick}
              disabled={detecting}
              className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-xs font-bold text-primary-foreground shadow-sm hover:bg-primary/90 disabled:opacity-50"
            >
              {detecting ? (
                <>
                  <RefreshCw size={14} className="animate-spin" />
                  <span>Analyzing Gaps...</span>
                </>
              ) : allGaps.length > 0 ? (
                <>
                  <RotateCcw size={14} />
                  <span>Rerun Detection</span>
                </>
              ) : (
                <>
                  <Sparkles size={14} />
                  <span>Analyze Information Gaps</span>
                </>
              )}
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSyncClick}
              className="inline-flex items-center gap-2 rounded-xl bg-amber-600 px-4 py-2 text-xs font-bold text-white shadow-sm hover:bg-amber-700"
            >
              <Database size={14} />
              <span>Sync with Cloud to Analyze</span>
            </button>
          )}
        </div>
      </div>

      {/* Progress & Stage Banner during Detection */}
      {detecting && (
        <div className="rounded-xl border border-primary/30 bg-primary/5 p-4 text-xs">
          <div className="flex items-center gap-3">
            <RefreshCw size={16} className="animate-spin text-primary shrink-0" />
            <div className="space-y-0.5">
              <p className="font-bold text-foreground">Gap Detection Pipeline Active</p>
              <p className="text-muted-foreground">{detectionStage || "Processing..."}</p>
            </div>
          </div>
        </div>
      )}

      {/* Error Banner */}
      {error && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-xs text-destructive">
          <div className="flex items-start gap-3">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <div className="space-y-1">
              <p className="font-bold">Analysis Notice</p>
              <p className="leading-relaxed">{error}</p>
            </div>
          </div>
        </div>
      )}

      {/* Success Toast */}
      {successToast && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3.5 text-xs text-emerald-800 dark:text-emerald-200">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={16} className="text-emerald-500 shrink-0" />
            <span className="font-medium">{successToast}</span>
          </div>
        </div>
      )}

      {/* Main Content Area */}
      {!resolvedBackendId ? (
        <GapEmptyState type="no_backend_id" onSyncProject={handleSyncClick} />
      ) : loading && allGaps.length === 0 ? (
        <GapAnalysisSkeleton count={3} />
      ) : allGaps.length === 0 ? (
        <GapEmptyState
          type={detecting ? "initial" : "initial"}
          onRunDetection={handleRunClick}
          isDetecting={detecting}
        />
      ) : (
        <div className="space-y-6">
          {/* Summary Cards */}
          <GapAnalysisSummary
            summary={summary}
            onFilterPriority={(p) => setSelectedPriority(p)}
          />

          {/* Filters & Sorting Bar */}
          <GapFilters
            selectedPriority={selectedPriority}
            onSelectPriority={setSelectedPriority}
            selectedGapType={selectedGapType}
            onSelectGapType={setSelectedGapType}
            selectedStatus={selectedStatus}
            onSelectStatus={setSelectedStatus}
            sortBy={sortBy}
            onSelectSort={setSortBy}
            totalCount={allGaps.length}
            filteredCount={gaps.length}
          />

          {/* Gaps List or Empty Filter State */}
          {gaps.length === 0 ? (
            <GapEmptyState
              type="no_filter_matches"
              onClearFilters={() => {
                setSelectedPriority("all");
                setSelectedGapType("all");
                setSelectedStatus("all");
              }}
            />
          ) : (
            <div className="space-y-4">
              {gaps.map((gap) => (
                <GapCard
                  key={gap.id}
                  gap={gap}
                  onInspectEvidence={(g) => setActiveEvidenceGap(g)}
                  onOpenReview={(g) => setActiveReviewGap(g)}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Evidence Viewer Modal */}
      <GapEvidenceViewer
        gap={activeEvidenceGap}
        isOpen={Boolean(activeEvidenceGap)}
        onClose={() => setActiveEvidenceGap(null)}
        evidenceList={evidenceList}
        sources={sources}
      />

      {/* Review Dialog Modal */}
      <GapReviewDialog
        gap={activeReviewGap}
        isOpen={Boolean(activeReviewGap)}
        onClose={() => setActiveReviewGap(null)}
        onSave={handleSaveReview}
        isUpdating={reviewUpdating}
      />

      {/* Rerun Confirmation Modal */}
      {showRerunConfirm && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
        >
          <div className="w-full max-w-md rounded-2xl border bg-card p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-150">
            <h3 className="text-base font-bold text-foreground">
              Rerun Information Gap Detection?
            </h3>
            <p className="mt-2 text-xs text-muted-foreground leading-relaxed">
              Rerunning analysis will re-evaluate your current project sources and evidence against the core research question.
              <br /><br />
              <strong>Data Protection:</strong> Any custom review statuses (Investigating, Resolved, Dismissed) and user notes you have written will be automatically preserved.
            </p>
            <div className="mt-5 flex items-center justify-end gap-2.5">
              <button
                type="button"
                onClick={() => setShowRerunConfirm(false)}
                className="rounded-lg border bg-background px-4 py-2 text-xs font-semibold text-foreground hover:bg-muted"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmRerun}
                className="rounded-lg bg-primary px-4 py-2 text-xs font-bold text-primary-foreground shadow-sm hover:bg-primary/90"
              >
                Confirm &amp; Rerun
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
