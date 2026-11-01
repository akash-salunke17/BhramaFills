import { useState } from "react";
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
  Database,
  CheckCircle2,
  ExternalLink,
  ChevronRight,
} from "lucide-react";
import { getStatusBadgeClass } from "../utils/researchStatus";
import { GapAnalysisPanel } from "@/features/analysis";
import { projectService } from "@/services/projectService";
import { authService } from "@/services/authService";

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
  initialTab = "overview",
}) {
  const [activeTab, setActiveTab] = useState(initialTab);
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncNotice, setSyncNotice] = useState("");

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

  const backendId = project.backendId || (projectService.resolveBackendId(project.id));
  const isCloudSynced = Boolean(backendId);

  const handleManualSync = async () => {
    setIsSyncing(true);
    setSyncNotice("");
    try {
      if (!authService.isAuthenticated()) {
        authService.loginAsDemo();
      }
      const res = await projectService.migrateLocalProjects();
      if (res.migratedCount > 0 || res.status === "completed") {
        setSyncNotice("Project successfully synchronized with database.");
      } else {
        setSyncNotice("Project is up to date.");
      }
    } catch (err) {
      setSyncNotice(`Sync failed: ${err.message}`);
    } finally {
      setIsSyncing(false);
    }
  };

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
          {/* Cloud Sync Status Indicator */}
          {isCloudSynced ? (
            <span
              title="Backed by Supabase PostgreSQL"
              className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1.5 text-xs font-semibold text-emerald-700 dark:text-emerald-300"
            >
              <CheckCircle2 size={13} />
              <span className="hidden sm:inline">Cloud Synced</span>
            </span>
          ) : (
            <button
              type="button"
              onClick={handleManualSync}
              disabled={isSyncing}
              className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-1.5 text-xs font-semibold text-amber-700 dark:text-amber-300 hover:bg-amber-500/20"
            >
              <Database size={13} className={isSyncing ? "animate-spin" : ""} />
              <span>{isSyncing ? "Syncing..." : "Sync with Cloud"}</span>
            </button>
          )}

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

      {syncNotice && (
        <div className="rounded-xl border border-primary/20 bg-primary/5 p-3 text-xs text-foreground flex items-center justify-between">
          <span>{syncNotice}</span>
          <button
            type="button"
            onClick={() => setSyncNotice("")}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Tabs Navigation */}
      <div className="flex items-center gap-1 border-b">
        <button
          type="button"
          onClick={() => setActiveTab("overview")}
          className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-bold transition-colors ${
            activeTab === "overview"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          <FileText size={15} />
          <span>Overview</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("gaps")}
          className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-bold transition-colors ${
            activeTab === "gaps"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          <Sparkles size={15} />
          <span>Information Gaps</span>
          <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] text-primary">
            Step 10E
          </span>
        </button>
      </div>

      {/* Tab: Overview */}
      {activeTab === "overview" && (
        <div className="space-y-6">
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
              {backendId && (
                <span className="font-mono text-[11px] text-muted-foreground ml-auto">
                  DB ID: {backendId.slice(0, 8)}...
                </span>
              )}
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

          {/* Quick Access Grid */}
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Module 1: Sources & Evidence Workspace */}
            <div className="rounded-2xl border bg-card p-6 shadow-sm">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-muted text-foreground">
                  <FileText size={20} />
                </div>
                <div>
                  <h3 className="text-base font-bold text-foreground">
                    Sources &amp; Extracted Evidence
                  </h3>
                  <p className="text-xs text-muted-foreground">
                    Webpages &amp; PDF research documents
                  </p>
                </div>
              </div>

              <div className="mt-4 rounded-xl border bg-muted/30 p-4 text-xs leading-relaxed text-muted-foreground">
                <div className="flex items-start gap-2">
                  <AlertCircle size={15} className="mt-0.5 shrink-0 text-muted-foreground" />
                  <span>
                    Attach website URLs or upload PDF research documents via backend APIs to extract facts, claims, and citation offsets.
                  </span>
                </div>
              </div>
            </div>

            {/* Module 2: AI Gap Analysis Action Card */}
            <div className="rounded-2xl border bg-card p-6 shadow-sm">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                    <Sparkles size={20} />
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-foreground">
                      Information Gap Detection
                    </h3>
                    <p className="text-xs text-muted-foreground">
                      AI-assisted missing evidence identification
                    </p>
                  </div>
                </div>
                <span className="rounded-md border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-bold text-emerald-700 dark:text-emerald-300">
                  Ready
                </span>
              </div>

              <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
                Examine your research corpus against the core question. Detect unsupported claims, unanswered subquestions, and track your review workflow.
              </p>

              <button
                type="button"
                onClick={() => setActiveTab("gaps")}
                className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-xs font-bold text-primary-foreground shadow-sm hover:bg-primary/90"
              >
                <span>Open Information Gaps Panel</span>
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Tab: Information Gaps (Step 10E) */}
      {activeTab === "gaps" && (
        <GapAnalysisPanel
          project={project}
          onSyncProject={handleManualSync}
        />
      )}
    </div>
  );
}
