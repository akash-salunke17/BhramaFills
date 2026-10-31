import {
  ArrowLeft,
  Calendar,
  Tag,
  Edit3,
  Trash2,
  Clock,
  Layers,
  Sparkles,
  FileText,
  AlertCircle,
} from "lucide-react";
import { getStatusBadgeClass } from "../utils/researchStatus";

function formatFullDate(isoString) {
  if (!isoString) return "N/A";
  try {
    const d = new Date(isoString);
    return d.toLocaleString(undefined, {
      month: "long",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return isoString;
  }
}

export default function ResearchDetails({
  project,
  onBack,
  onEdit,
  onDelete,
}) {
  if (!project) {
    return (
      <div className="rounded-2xl border border-dashed bg-card p-8 text-center sm:p-12">
        <h3 className="text-base font-bold text-foreground">Project not found</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          The requested research workspace does not exist or has been removed.
        </p>
        <button
          type="button"
          onClick={onBack}
          className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
        >
          <ArrowLeft size={16} />
          <span>Back to Projects</span>
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Top Navigation Bar */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between border-b pb-4">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-2 rounded-lg border bg-background px-3.5 py-2 text-xs font-semibold text-foreground shadow-sm hover:bg-muted sm:text-sm"
        >
          <ArrowLeft size={16} />
          <span>Back to Projects</span>
        </button>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onEdit(project)}
            className="inline-flex items-center gap-1.5 rounded-lg border bg-background px-3.5 py-2 text-xs font-semibold text-foreground shadow-sm hover:bg-muted sm:text-sm"
          >
            <Edit3 size={15} />
            <span>Edit Project</span>
          </button>
          <button
            type="button"
            onClick={() => onDelete(project)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-destructive/20 bg-destructive/10 px-3.5 py-2 text-xs font-semibold text-destructive shadow-sm hover:bg-destructive/20 sm:text-sm"
          >
            <Trash2 size={15} />
            <span>Delete</span>
          </button>
        </div>
      </div>

      {/* Main Project Overview Card */}
      <div className="rounded-2xl border bg-card p-6 shadow-sm sm:p-8">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="inline-flex items-center gap-1.5 rounded-md bg-muted px-3 py-1 text-xs font-semibold text-foreground">
            <Tag size={13} className="text-muted-foreground" aria-hidden="true" />
            <span>{project.category}</span>
          </span>
          <span
            className={`inline-flex items-center rounded-md border px-3 py-1 text-xs font-bold ${getStatusBadgeClass(
              project.status
            )}`}
          >
            {project.status}
          </span>
        </div>

        <h1 className="mt-4 text-2xl font-bold tracking-tight text-foreground sm:text-3xl break-words">
          {project.title}
        </h1>

        {/* Timestamps */}
        <div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-muted-foreground border-y py-3">
          <span className="inline-flex items-center gap-1.5">
            <Calendar size={14} aria-hidden="true" />
            <span>Created: {formatFullDate(project.createdAt)}</span>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Clock size={14} aria-hidden="true" />
            <span>Last Modified: {formatFullDate(project.updatedAt)}</span>
          </span>
        </div>

        {/* Research Question */}
        <div className="mt-6 rounded-xl border bg-muted/40 p-5">
          <h2 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
            Core Research Question
          </h2>
          <p className="mt-2 text-base font-semibold leading-relaxed text-foreground sm:text-lg break-words">
            &ldquo;{project.researchQuestion}&rdquo;
          </p>
        </div>

        {/* Project Description (if provided) */}
        {project.description && (
          <div className="mt-6">
            <h2 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Project Description &amp; Scope
            </h2>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-foreground/90 break-words">
              {project.description}
            </p>
          </div>
        )}
      </div>

      {/* Future Workspace Modules Area */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Module 1: Sources Workspace (Phase 3) */}
        <div className="rounded-2xl border border-dashed bg-card p-6 shadow-sm">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-muted text-muted-foreground">
              <FileText size={20} />
            </div>
            <div>
              <h3 className="text-base font-bold text-foreground">
                Sources Workspace
              </h3>
              <p className="text-xs text-muted-foreground">
                Document ingestion &amp; web extraction
              </p>
            </div>
          </div>

          <div className="mt-5 rounded-lg bg-muted/40 p-4 text-xs leading-relaxed text-muted-foreground">
            <div className="flex items-start gap-2">
              <AlertCircle size={15} className="mt-0.5 shrink-0 text-muted-foreground" />
              <span>
                <strong>Upcoming in Phase 3:</strong> You will be able to attach web source URLs and upload PDF research documents for automated text extraction and reference mapping.
              </span>
            </div>
          </div>
        </div>

        {/* Module 2: AI Analysis & Verification Checklist (Phase 4) */}
        <div className="rounded-2xl border border-dashed bg-card p-6 shadow-sm">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-muted text-muted-foreground">
              <Sparkles size={20} />
            </div>
            <div>
              <h3 className="text-base font-bold text-foreground">
                AI Gap Analysis &amp; Checklist
              </h3>
              <p className="text-xs text-muted-foreground">
                Information gap detection &amp; claim conflict check
              </p>
            </div>
          </div>

          <div className="mt-5 rounded-lg bg-muted/40 p-4 text-xs leading-relaxed text-muted-foreground">
            <div className="flex items-start gap-2">
              <Layers size={15} className="mt-0.5 shrink-0 text-muted-foreground" />
              <span>
                <strong>Upcoming in Phase 4:</strong> Gemini AI synthesis will automatically identify missing evidence, contradictions between sources, and compile actionable verification checklists.
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
