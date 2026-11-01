import { useState } from "react";
import {
  X,
  FileText,
  ExternalLink,
  Sparkles,
  Search,
  Copy,
  Check,
  AlertTriangle,
  Info,
  CheckCircle2,
  Bookmark,
  Layers,
} from "lucide-react";
import { getPriorityBadge, getGapTypeLabel, getReviewStatusBadge } from "./GapCard";

export default function GapEvidenceViewer({ gap, isOpen, onClose, evidenceList = [], sources = [] }) {
  const [copiedQuery, setCopiedQuery] = useState(false);

  if (!isOpen || !gap) return null;

  const priorityBadge = getPriorityBadge(gap.priority);
  const statusBadge = getReviewStatusBadge(gap.status);
  const PriorityIcon = priorityBadge.icon;
  const StatusIcon = statusBadge.icon;

  const meta = gap.confidence_metadata || {};
  const bharmafills = meta.bharmafills || {};
  const aiConfidence = bharmafills.ai_confidence ?? meta.ai_confidence;
  const aiReasoning = bharmafills.ai_reasoning || meta.ai_reasoning;
  const targetSubquestion = bharmafills.target_subquestion;
  const gapSubtype = bharmafills.gap_subtype || meta.gap_subtype;
  const verdict = bharmafills.validation_verdict;
  const groundingNotes = bharmafills.grounding_notes;
  const coveredEvidenceIds = bharmafills.covered_evidence_ids || [];
  const userReview = bharmafills.user_review;

  // Map sources by ID for fast lookup
  const sourceById = new Map();
  (sources || []).forEach((s) => {
    sourceById.set(String(s.id), s);
  });

  // Map project evidence items by ID
  const evidenceById = new Map();
  (evidenceList || []).forEach((e) => {
    evidenceById.set(String(e.id), e);
  });

  const handleCopyQuery = () => {
    if (!gap.suggested_query) return;
    navigator.clipboard?.writeText(gap.suggested_query);
    setCopiedQuery(true);
    setTimeout(() => setCopiedQuery(false), 2000);
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="evidence-viewer-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
    >
      <div className="relative flex max-h-[90vh] w-full max-w-3xl flex-col rounded-2xl border bg-card shadow-2xl animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="flex items-start justify-between border-b p-5 sm:p-6">
          <div className="space-y-1 pr-6">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-0.5 text-xs font-bold ${priorityBadge.className}`}
              >
                <PriorityIcon size={13} aria-hidden="true" />
                <span>{priorityBadge.label}</span>
              </span>

              <span className="inline-flex items-center rounded-md border bg-muted/40 px-2.5 py-0.5 text-xs font-semibold text-foreground">
                {getGapTypeLabel(gap.gap_type)}
              </span>

              <span className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-0.5 text-xs font-bold ${statusBadge.className}`}>
                <StatusIcon size={12} aria-hidden="true" />
                <span>{statusBadge.label}</span>
              </span>
            </div>
            <h2 id="evidence-viewer-title" className="text-lg font-bold text-foreground sm:text-xl break-words pt-1">
              {gap.gap_description}
            </h2>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close evidence viewer"
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X size={20} />
          </button>
        </div>

        {/* Scrollable Content Body */}
        <div className="flex-1 overflow-y-auto p-5 sm:p-6 space-y-6">
          {/* Section 1: Detailed Explanation & Subquestion */}
          <div className="space-y-3">
            <div>
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                Detailed Explanation &amp; Deficit Significance
              </h3>
              <p className="mt-1 text-sm leading-relaxed text-foreground break-words">
                {gap.explanation}
              </p>
            </div>

            {targetSubquestion && (
              <div className="rounded-xl border bg-muted/30 p-3.5 text-xs">
                <span className="font-semibold text-muted-foreground uppercase text-[10px] tracking-wider block mb-1">
                  Specific Unanswered Question Investigated:
                </span>
                <p className="font-medium text-foreground break-words">&ldquo;{targetSubquestion}&rdquo;</p>
              </div>
            )}
          </div>

          {/* Section 2: AI Confidence & Uncertainty */}
          <div className="rounded-xl border border-purple-500/20 bg-purple-500/5 p-4 space-y-2">
            <div className="flex items-center justify-between text-xs font-bold text-purple-700 dark:text-purple-300">
              <span className="flex items-center gap-1.5">
                <Sparkles size={14} />
                <span>AI Confidence &amp; Evaluator Reasoning</span>
              </span>
              {typeof aiConfidence === "number" && (
                <span className="rounded bg-purple-500/20 px-2 py-0.5 font-mono">
                  {Math.round(aiConfidence * 100)}% Confidence
                </span>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              <em>Note:</em> AI confidence represents the model&apos;s evaluation certainty that this information is absent or insufficient in the supplied documents. It is not an assertion of absolute real-world fact.
            </p>
            {aiReasoning && (
              <p className="text-xs leading-relaxed text-foreground/90 break-words pt-1">
                <strong>Model Reasoning:</strong> {aiReasoning}
              </p>
            )}
          </div>

          {/* Section 3: Grounding Verification & Notes */}
          {groundingNotes && (
            <div className="rounded-xl border bg-card p-4 space-y-2 shadow-sm">
              <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground">
                <Info size={14} />
                <span>Backend Grounding &amp; Cross-Reference Verification</span>
              </div>
              <p className="text-xs leading-relaxed text-foreground/90 break-words">
                {groundingNotes}
              </p>
              {verdict && (
                <div className="text-[11px] text-muted-foreground pt-1">
                  Validation verdict: <strong className="text-foreground">{verdict}</strong>
                </div>
              )}
            </div>
          )}

          {/* Section 4: Related Extracted Evidence & Citations */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                <FileText size={14} />
                <span>Referenced Evidence Records ({coveredEvidenceIds.length})</span>
              </h3>
            </div>

            {coveredEvidenceIds.length === 0 ? (
              <div className="rounded-xl border border-dashed p-4 text-center text-xs text-muted-foreground">
                No specific evidence records were cited as partially covering this gap. This topic appears completely unrepresented in the indexed corpus.
              </div>
            ) : (
              <div className="space-y-3">
                {coveredEvidenceIds.map((eid, idx) => {
                  const evRecord = evidenceById.get(String(eid));
                  const sourceRecord = evRecord?.source_id ? sourceById.get(String(evRecord.source_id)) : null;

                  return (
                    <div
                      key={eid || idx}
                      className="rounded-xl border bg-card p-4 shadow-sm text-xs space-y-2"
                    >
                      <div className="flex items-center justify-between text-muted-foreground">
                        <span className="font-mono text-[10px]">Evidence ID: {eid}</span>
                        {sourceRecord && (
                          <span className="font-semibold text-foreground">
                            {sourceRecord.title || sourceRecord.original_filename || "Source Document"}
                          </span>
                        )}
                      </div>

                      {evRecord ? (
                        <>
                          {/* Claim */}
                          {evRecord.claim && (
                            <p className="font-semibold text-foreground break-words">
                              {evRecord.claim}
                            </p>
                          )}

                          {/* Citation quote (untrusted data rendered safely) */}
                          {evRecord.supporting_excerpt && (
                            <div className="rounded-lg bg-muted/50 p-2.5 font-mono text-[11px] text-foreground/90 break-words">
                              &ldquo;{evRecord.supporting_excerpt}&rdquo;
                            </div>
                          )}

                          {/* Metadata row: page, URL, representation */}
                          <div className="flex flex-wrap items-center gap-3 pt-1 text-[11px] text-muted-foreground">
                            {evRecord.page_number && (
                              <span>Page: <strong>{evRecord.page_number}</strong></span>
                            )}
                            {evRecord.fact_type && (
                              <span>Type: <strong>{evRecord.fact_type}</strong></span>
                            )}
                            {evRecord.confidence_score && (
                              <span>Confidence: <strong>{Math.round(evRecord.confidence_score * 100)}%</strong></span>
                            )}
                            {sourceRecord?.original_url && (
                              <a
                                href={sourceRecord.original_url}
                                target="_blank"
                                rel="noreferrer noopener"
                                className="inline-flex items-center gap-1 text-primary hover:underline ml-auto"
                              >
                                <span>Open Source</span>
                                <ExternalLink size={11} />
                              </a>
                            )}
                          </div>
                        </>
                      ) : (
                        <div className="rounded-lg bg-muted/30 p-2.5 text-muted-foreground italic">
                          Evidence record {eid} is referenced by this finding but was omitted from the active evidence page view.
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Section 5: Suggested Search Query */}
          {gap.suggested_query && (
            <div className="rounded-xl border bg-muted/40 p-4 space-y-2">
              <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground block">
                Suggested Follow-up Search Query
              </span>
              <div className="flex items-center justify-between gap-3 rounded-lg border bg-background p-2.5">
                <span className="font-mono text-xs text-foreground truncate">
                  {gap.suggested_query}
                </span>
                <button
                  type="button"
                  onClick={handleCopyQuery}
                  className="inline-flex shrink-0 items-center gap-1 rounded bg-muted px-2.5 py-1 text-xs font-semibold text-foreground hover:bg-muted/80"
                >
                  {copiedQuery ? <Check size={12} className="text-emerald-500" /> : <Copy size={12} />}
                  <span>{copiedQuery ? "Copied" : "Copy Query"}</span>
                </button>
              </div>
            </div>
          )}

          {/* Section 6: Reviewer Notes if present */}
          {userReview?.notes && (
            <div className="rounded-xl border bg-muted/30 p-4 space-y-1">
              <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground block">
                Review Status: {userReview.status || gap.status}
              </span>
              <p className="text-xs text-foreground italic break-words">
                &ldquo;{userReview.notes}&rdquo;
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end border-t p-4 sm:p-5">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground shadow-sm hover:bg-primary/90"
          >
            Close Viewer
          </button>
        </div>
      </div>
    </div>
  );
}
