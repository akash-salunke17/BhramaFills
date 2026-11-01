import { useState } from "react";
import {
  AlertTriangle,
  ShieldAlert,
  AlertCircle,
  HelpCircle,
  CheckCircle2,
  Clock,
  Sparkles,
  Search,
  Copy,
  Check,
  FileText,
  Edit2,
  ChevronRight,
} from "lucide-react";

export function getPriorityBadge(priority) {
  switch (priority) {
    case "critical":
      return {
        label: "Critical",
        icon: ShieldAlert,
        className: "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300",
      };
    case "high":
      return {
        label: "High Priority",
        icon: AlertCircle,
        className: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
      };
    case "medium":
      return {
        label: "Medium",
        icon: AlertTriangle,
        className: "border-yellow-500/30 bg-yellow-500/10 text-yellow-800 dark:text-yellow-300",
      };
    default:
      return {
        label: "Low",
        icon: HelpCircle,
        className: "border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-300",
      };
  }
}

export function getGapTypeLabel(type) {
  switch (type) {
    case "no_evidence":
      return "No Evidence Found";
    case "insufficient_evidence":
      return "Insufficient Evidence";
    case "conflicting_evidence":
      return "Conflicting Evidence";
    case "unverified":
      return "Unverified Claim";
    default:
      return type?.replace(/_/g, " ") || "Information Gap";
  }
}

export function getReviewStatusBadge(status) {
  switch (status) {
    case "investigating":
      return {
        label: "Investigating",
        icon: Clock,
        className: "border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300",
      };
    case "resolved":
      return {
        label: "Resolved",
        icon: CheckCircle2,
        className: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
      };
    case "dismissed":
      return {
        label: "Dismissed",
        icon: HelpCircle,
        className: "border-muted bg-muted/60 text-muted-foreground line-through",
      };
    default:
      return {
        label: "Open",
        icon: AlertCircle,
        className: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
      };
  }
}

export default function GapCard({ gap, onInspectEvidence, onOpenReview }) {
  const [copiedQuery, setCopiedQuery] = useState(false);

  if (!gap) return null;

  const priorityBadge = getPriorityBadge(gap.priority);
  const statusBadge = getReviewStatusBadge(gap.status);
  const PriorityIcon = priorityBadge.icon;
  const StatusIcon = statusBadge.icon;

  // Extract nested bharmafills metadata safely
  const meta = gap.confidence_metadata || {};
  const bharmafills = meta.bharmafills || {};
  const aiConfidence = bharmafills.ai_confidence ?? meta.ai_confidence;
  const gapSubtype = bharmafills.gap_subtype || meta.gap_subtype;
  const verdict = bharmafills.validation_verdict;
  const truncationWarning = bharmafills.corpus_truncation_warning;
  const omissionWarning = bharmafills.source_omission_warning;
  const coveredEvidenceIds = bharmafills.covered_evidence_ids || [];
  const userReview = bharmafills.user_review;

  const handleCopyQuery = (e) => {
    e.stopPropagation();
    if (!gap.suggested_query) return;
    navigator.clipboard?.writeText(gap.suggested_query);
    setCopiedQuery(true);
    setTimeout(() => setCopiedQuery(false), 2000);
  };

  return (
    <div className="group relative rounded-2xl border bg-card p-5 shadow-sm transition-all hover:border-primary/40 hover:shadow-md sm:p-6">
      {/* Top Badges Row */}
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        <div className="flex flex-wrap items-center gap-2">
          {/* Priority */}
          <span
            className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-0.5 text-xs font-bold ${priorityBadge.className}`}
          >
            <PriorityIcon size={13} aria-hidden="true" />
            <span>{priorityBadge.label}</span>
          </span>

          {/* Gap Type */}
          <span className="inline-flex items-center rounded-md border bg-muted/40 px-2.5 py-0.5 text-xs font-semibold text-foreground">
            {getGapTypeLabel(gap.gap_type)}
          </span>

          {/* Subtype if present */}
          {gapSubtype && (
            <span className="inline-flex items-center rounded-md bg-secondary/80 px-2 py-0.5 text-[11px] font-medium text-secondary-foreground">
              {gapSubtype.replace(/_/g, " ")}
            </span>
          )}

          {/* Grounding Verdict */}
          {verdict && (
            <span
              className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium ${
                verdict === "confirmed"
                  ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                  : "border-blue-500/20 bg-blue-500/10 text-blue-700 dark:text-blue-300"
              }`}
            >
              {verdict.replace(/_/g, " ")}
            </span>
          )}
        </div>

        {/* Review Status & AI Confidence */}
        <div className="flex items-center gap-2">
          {typeof aiConfidence === "number" && (
            <span
              title="Calculated AI model confidence for candidate identification (not verified truth)"
              className="inline-flex items-center gap-1 rounded-md border border-purple-500/20 bg-purple-500/10 px-2 py-0.5 text-[11px] font-semibold text-purple-700 dark:text-purple-300"
            >
              <Sparkles size={11} aria-hidden="true" />
              <span>AI Confidence: {Math.round(aiConfidence * 100)}%</span>
            </span>
          )}

          <button
            type="button"
            onClick={() => onOpenReview && onOpenReview(gap)}
            className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-0.5 text-xs font-bold transition-transform hover:scale-105 ${statusBadge.className}`}
            title="Click to change review status or update notes"
          >
            <StatusIcon size={12} aria-hidden="true" />
            <span>{statusBadge.label}</span>
            <Edit2 size={10} className="ml-0.5 opacity-60" />
          </button>
        </div>
      </div>

      {/* Gap Description */}
      <h3 className="mt-3.5 text-base font-bold leading-snug text-foreground sm:text-lg break-words">
        {gap.gap_description}
      </h3>

      {/* Explanation */}
      {gap.explanation && (
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground break-words">
          {gap.explanation}
        </p>
      )}

      {/* Truncation / Omission Warning */}
      {(truncationWarning || omissionWarning) && (
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 p-2.5 text-xs text-amber-800 dark:text-amber-300">
          <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
          <span>
            <strong>Warning:</strong> {omissionWarning || "This gap was evaluated with partial corpus coverage."}
          </span>
        </div>
      )}

      {/* User Review Notes if present */}
      {userReview?.notes && (
        <div className="mt-3 rounded-lg border bg-muted/40 p-3 text-xs text-foreground">
          <span className="font-semibold text-muted-foreground uppercase text-[10px] tracking-wider block mb-1">
            Reviewer Notes ({userReview.status || gap.status}):
          </span>
          <p className="italic break-words">&ldquo;{userReview.notes}&rdquo;</p>
        </div>
      )}

      {/* Bottom Row: Suggested Query & Actions */}
      <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-t pt-3">
        {/* Suggested Query Pill */}
        {gap.suggested_query ? (
          <div className="flex max-w-full items-center gap-2 overflow-hidden rounded-lg bg-muted/50 px-2.5 py-1.5 text-xs">
            <Search size={13} className="shrink-0 text-muted-foreground" />
            <span className="truncate font-mono text-[11px] text-foreground" title={gap.suggested_query}>
              {gap.suggested_query}
            </span>
            <button
              type="button"
              onClick={handleCopyQuery}
              className="ml-auto inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold text-muted-foreground hover:bg-muted hover:text-foreground"
              title="Copy query"
            >
              {copiedQuery ? <Check size={12} className="text-emerald-500" /> : <Copy size={12} />}
              <span>{copiedQuery ? "Copied" : "Copy"}</span>
            </button>
          </div>
        ) : (
          <div />
        )}

        {/* Action Button: Evidence Viewer */}
        <div className="flex items-center gap-2 sm:ml-auto">
          {coveredEvidenceIds.length > 0 && (
            <span className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-[11px] font-medium text-muted-foreground">
              <FileText size={12} />
              <span>{coveredEvidenceIds.length} related evidence</span>
            </span>
          )}

          <button
            type="button"
            onClick={() => onInspectEvidence && onInspectEvidence(gap)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary transition-colors hover:bg-primary hover:text-primary-foreground"
          >
            <span>Inspect Evidence</span>
            <ChevronRight size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
