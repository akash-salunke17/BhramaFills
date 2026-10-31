import { Calendar, Tag, ArrowRight, Edit3, Trash2 } from "lucide-react";
import { getStatusBadgeClass } from "../utils/researchStatus";

function formatDate(isoString) {
  if (!isoString) return "N/A";
  try {
    const d = new Date(isoString);
    return d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return isoString;
  }
}

export default function ResearchCard({
  project,
  onView,
  onEdit,
  onDelete,
}) {
  const { title, researchQuestion, category, status, createdAt, updatedAt } = project;

  return (
    <div className="flex flex-col justify-between rounded-xl border bg-card p-5 shadow-sm transition-all hover:border-foreground/20 hover:shadow-md">
      <div>
        {/* Top Badges: Category & Status */}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-md bg-muted px-2.5 py-1 text-xs font-semibold text-foreground">
            <Tag size={12} className="text-muted-foreground" aria-hidden="true" />
            <span>{category}</span>
          </span>

          <span
            className={`inline-flex items-center rounded-md border px-2.5 py-1 text-xs font-bold ${getStatusBadgeClass(
              status
            )}`}
          >
            {status}
          </span>
        </div>

        {/* Title */}
        <h3
          onClick={() => onView(project)}
          className="mt-3 cursor-pointer text-base font-bold tracking-tight text-foreground transition-colors hover:text-primary sm:text-lg break-words"
        >
          {title}
        </h3>

        {/* Question Preview */}
        <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-muted-foreground sm:text-sm break-words">
          {researchQuestion}
        </p>
      </div>

      {/* Footer: Dates & Actions */}
      <div className="mt-5 border-t pt-4">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <Calendar size={13} aria-hidden="true" />
            <span>Updated {formatDate(updatedAt || createdAt)}</span>
          </span>
        </div>

        <div className="mt-3 flex items-center justify-between gap-2 pt-1">
          <button
            type="button"
            onClick={() => onView(project)}
            className="inline-flex items-center gap-1.5 text-xs font-bold text-primary hover:underline"
          >
            <span>Open Workspace</span>
            <ArrowRight size={13} />
          </button>

          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => onEdit(project)}
              aria-label={`Edit ${title}`}
              title="Edit project"
              className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <Edit3 size={15} />
            </button>
            <button
              type="button"
              onClick={() => onDelete(project)}
              aria-label={`Delete ${title}`}
              title="Delete project"
              className="rounded-lg p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
            >
              <Trash2 size={15} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
