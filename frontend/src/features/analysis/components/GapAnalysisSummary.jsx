import { AlertTriangle, AlertCircle, ShieldAlert, CheckCircle2, Search, Info } from "lucide-react";

export default function GapAnalysisSummary({ summary, onFilterPriority }) {
  if (!summary) return null;

  return (
    <div className="space-y-4">
      {/* Corpus Warnings Banner */}
      {summary.hasCorpusTruncation && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-xs text-amber-900 dark:text-amber-200">
          <div className="flex items-start gap-3">
            <AlertTriangle size={18} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
            <div>
              <p className="font-bold">Corpus Truncation / Source Omission Warning</p>
              <p className="mt-1 leading-relaxed">
                Some source documents exceeded model prompt capacity limits and were partially truncated or omitted. Findings reflect the inspected subset of evidence.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Model-Reported Warnings */}
      {summary.warnings && summary.warnings.length > 0 && (
        <div className="rounded-xl border border-muted bg-muted/40 p-3.5 text-xs text-muted-foreground">
          <div className="flex items-start gap-2.5">
            <Info size={16} className="mt-0.5 shrink-0 text-muted-foreground" />
            <div className="space-y-1">
              <span className="font-semibold text-foreground">Analysis Caveats &amp; Evidence Boundaries:</span>
              <ul className="list-disc pl-4 space-y-0.5">
                {summary.warnings.map((w, idx) => (
                  <li key={idx} className="break-words">{w}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Metrics Cards Grid */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 sm:gap-4">
        {/* Total Gaps */}
        <div className="rounded-xl border bg-card p-4 shadow-sm">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-xs font-semibold uppercase tracking-wider">Total Gaps</span>
            <Search size={16} />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold tracking-tight text-foreground">{summary.total}</span>
            <span className="text-xs text-muted-foreground">identified</span>
          </div>
        </div>

        {/* Critical Priority */}
        <button
          type="button"
          onClick={() => onFilterPriority && onFilterPriority("critical")}
          className="text-left rounded-xl border border-rose-500/20 bg-rose-500/5 p-4 shadow-sm transition-colors hover:bg-rose-500/10"
        >
          <div className="flex items-center justify-between text-rose-600 dark:text-rose-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Critical</span>
            <ShieldAlert size={16} />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold tracking-tight text-rose-700 dark:text-rose-300">
              {summary.critical}
            </span>
            <span className="text-xs text-rose-600/80 dark:text-rose-400/80">urgent</span>
          </div>
        </button>

        {/* High Priority */}
        <button
          type="button"
          onClick={() => onFilterPriority && onFilterPriority("high")}
          className="text-left rounded-xl border border-amber-500/20 bg-amber-500/5 p-4 shadow-sm transition-colors hover:bg-amber-500/10"
        >
          <div className="flex items-center justify-between text-amber-600 dark:text-amber-400">
            <span className="text-xs font-semibold uppercase tracking-wider">High Priority</span>
            <AlertCircle size={16} />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold tracking-tight text-amber-700 dark:text-amber-300">
              {summary.high}
            </span>
            <span className="text-xs text-amber-600/80 dark:text-amber-400/80">important</span>
          </div>
        </button>

        {/* Resolved / Investigating */}
        <div className="rounded-xl border bg-card p-4 shadow-sm">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-xs font-semibold uppercase tracking-wider">Review Status</span>
            <CheckCircle2 size={16} className="text-emerald-500" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold tracking-tight text-foreground">{summary.resolved}</span>
            <span className="text-xs text-muted-foreground">
              resolved ({summary.investigating} investigating)
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
