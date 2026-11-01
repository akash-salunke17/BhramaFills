import {
  Sparkles,
  FileQuestion,
  SearchX,
  CheckCircle2,
  AlertCircle,
  Database,
  ArrowRight,
} from "lucide-react";

export default function GapEmptyState({
  type = "initial",
  onRunDetection,
  onClearFilters,
  onSyncProject,
  isDetecting,
}) {
  if (type === "no_backend_id") {
    return (
      <div className="rounded-2xl border border-dashed bg-card p-8 text-center sm:p-12">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-amber-500/10 text-amber-600 dark:text-amber-400">
          <Database size={28} />
        </div>
        <h3 className="mt-4 text-base font-bold text-foreground sm:text-lg">
          Cloud Synchronization Required
        </h3>
        <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground leading-relaxed">
          AI information gap analysis requires your research project and extracted evidence to be persisted in the Supabase PostgreSQL database.
        </p>
        {onSyncProject && (
          <button
            type="button"
            onClick={onSyncProject}
            className="mt-6 inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-xs font-bold text-primary-foreground shadow-sm hover:bg-primary/90"
          >
            <span>Synchronize Project with Database</span>
            <ArrowRight size={14} />
          </button>
        )}
      </div>
    );
  }

  if (type === "no_filter_matches") {
    return (
      <div className="rounded-2xl border border-dashed bg-card p-8 text-center sm:p-12">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
          <SearchX size={28} />
        </div>
        <h3 className="mt-4 text-base font-bold text-foreground sm:text-lg">
          No Gaps Match Your Active Filters
        </h3>
        <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
          Try adjusting your priority, gap type, or review status filters to see other findings.
        </p>
        {onClearFilters && (
          <button
            type="button"
            onClick={onClearFilters}
            className="mt-5 rounded-lg border bg-background px-4 py-2 text-xs font-semibold text-foreground hover:bg-muted"
          >
            Reset Filters
          </button>
        )}
      </div>
    );
  }

  if (type === "no_evidence") {
    return (
      <div className="rounded-2xl border border-dashed bg-card p-8 text-center sm:p-12">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
          <FileQuestion size={28} />
        </div>
        <h3 className="mt-4 text-base font-bold text-foreground sm:text-lg">
          No Extracted Evidence Available Yet
        </h3>
        <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground leading-relaxed">
          Before detecting information gaps, you must attach research sources (web URLs or PDF documents) and run evidence extraction.
        </p>
      </div>
    );
  }

  if (type === "no_gaps") {
    return (
      <div className="rounded-2xl border border-dashed border-emerald-500/30 bg-emerald-500/5 p-8 text-center sm:p-12">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
          <CheckCircle2 size={28} />
        </div>
        <h3 className="mt-4 text-base font-bold text-emerald-800 dark:text-emerald-200 sm:text-lg">
          No Information Gaps Detected
        </h3>
        <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground leading-relaxed">
          The evaluated corpus adequately addresses your core research question without notable missing topics or unsupported claims.
        </p>
      </div>
    );
  }

  // Default: Initial Ready State
  return (
    <div className="rounded-2xl border border-dashed bg-card p-8 text-center sm:p-12">
      <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
        <Sparkles size={28} />
      </div>
      <h3 className="mt-4 text-base font-bold text-foreground sm:text-lg">
        AI Information Gap Detection
      </h3>
      <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground leading-relaxed">
        Identify missing evidence, unanswered subquestions, single-source assertions, and coverage voids across your research sources.
      </p>
      {onRunDetection && (
        <button
          type="button"
          onClick={() => onRunDetection()}
          disabled={isDetecting}
          className="mt-6 inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-xs font-bold text-primary-foreground shadow-sm hover:bg-primary/90 disabled:opacity-50"
        >
          <Sparkles size={14} />
          <span>{isDetecting ? "Analyzing Gaps..." : "Analyze Information Gaps"}</span>
        </button>
      )}
    </div>
  );
}
