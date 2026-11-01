import { useState } from "react";
import { X, CheckCircle2, Clock, HelpCircle, Loader2 } from "lucide-react";

export default function GapReviewDialog({ gap, isOpen, onClose, onSave, isUpdating }) {
  const currentStatus = gap?.status === "open" ? "investigating" : gap?.status || "investigating";
  const existingNotes = gap?.confidence_metadata?.bharmafills?.user_review?.notes || "";

  const [selectedStatus, setSelectedStatus] = useState(currentStatus);
  const [userNotes, setUserNotes] = useState(existingNotes);
  const [error, setError] = useState(null);

  if (!isOpen || !gap) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);

    if (!["investigating", "resolved", "dismissed"].includes(selectedStatus)) {
      setError("Please select a valid review status.");
      return;
    }

    try {
      await onSave(gap.id, {
        status: selectedStatus,
        user_notes: userNotes.trim() || null,
      });
      onClose();
    } catch (err) {
      setError(err.message || "Failed to update review status.");
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="review-dialog-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
    >
      <div className="relative w-full max-w-lg rounded-2xl border bg-card p-6 shadow-2xl sm:p-7 animate-in fade-in zoom-in-95 duration-150">
        {/* Close Button */}
        <button
          type="button"
          onClick={onClose}
          aria-label="Close dialog"
          className="absolute right-4 top-4 rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <X size={18} />
        </button>

        <h2 id="review-dialog-title" className="text-lg font-bold text-foreground">
          Update Gap Review Status
        </h2>

        {/* Gap Description Excerpt */}
        <div className="mt-3 rounded-xl border bg-muted/30 p-3.5 text-xs text-muted-foreground">
          <span className="font-semibold text-foreground uppercase tracking-wider text-[10px] block mb-1">
            Information Gap:
          </span>
          <p className="line-clamp-2 text-foreground break-words">{gap.gap_description}</p>
        </div>

        {error && (
          <div className="mt-3 rounded-lg border border-destructive/20 bg-destructive/10 p-3 text-xs font-medium text-destructive">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-5 space-y-4">
          {/* Status Selection */}
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
              Review Status
            </label>
            <div className="grid grid-cols-3 gap-2">
              {/* Investigating */}
              <button
                type="button"
                onClick={() => setSelectedStatus("investigating")}
                className={`flex flex-col items-center gap-1.5 rounded-xl border p-3 text-xs font-semibold transition-all ${
                  selectedStatus === "investigating"
                    ? "border-sky-500 bg-sky-500/15 text-sky-700 dark:text-sky-300 ring-2 ring-sky-500/30"
                    : "border-muted bg-background text-muted-foreground hover:bg-muted"
                }`}
              >
                <Clock size={16} />
                <span>Investigating</span>
              </button>

              {/* Resolved */}
              <button
                type="button"
                onClick={() => setSelectedStatus("resolved")}
                className={`flex flex-col items-center gap-1.5 rounded-xl border p-3 text-xs font-semibold transition-all ${
                  selectedStatus === "resolved"
                    ? "border-emerald-500 bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 ring-2 ring-emerald-500/30"
                    : "border-muted bg-background text-muted-foreground hover:bg-muted"
                }`}
              >
                <CheckCircle2 size={16} />
                <span>Resolved</span>
              </button>

              {/* Dismissed */}
              <button
                type="button"
                onClick={() => setSelectedStatus("dismissed")}
                className={`flex flex-col items-center gap-1.5 rounded-xl border p-3 text-xs font-semibold transition-all ${
                  selectedStatus === "dismissed"
                    ? "border-muted-foreground bg-muted text-foreground ring-2 ring-muted-foreground/30"
                    : "border-muted bg-background text-muted-foreground hover:bg-muted"
                }`}
              >
                <HelpCircle size={16} />
                <span>Dismissed</span>
              </button>
            </div>
          </div>

          {/* User Review Notes */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label htmlFor="user-notes-input" className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                Review Notes &amp; Rationale
              </label>
              <span className="text-[11px] text-muted-foreground">
                {userNotes.length} / 2000
              </span>
            </div>
            <textarea
              id="user-notes-input"
              rows={4}
              maxLength={2000}
              value={userNotes}
              onChange={(e) => setUserNotes(e.target.value)}
              placeholder="Explain findings, follow-up citations discovered, or rationale for status resolution..."
              className="w-full rounded-xl border bg-background p-3 text-sm text-foreground shadow-sm placeholder:text-muted-foreground focus:border-primary focus:outline-none"
            />
          </div>

          {/* Action Buttons */}
          <div className="flex items-center justify-end gap-2.5 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={isUpdating}
              className="rounded-lg border bg-background px-4 py-2 text-xs font-semibold text-foreground hover:bg-muted disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isUpdating}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground shadow-sm hover:bg-primary/90 disabled:opacity-50"
            >
              {isUpdating && <Loader2 size={14} className="animate-spin" />}
              <span>Save Review</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
