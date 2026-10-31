import ResearchCard from "./ResearchCard";
import { FolderKanban, Plus, SearchX } from "lucide-react";

export default function ResearchList({
  projects,
  allProjectsCount,
  loading,
  onView,
  onEdit,
  onDelete,
  onCreateNew,
  onClearFilters,
}) {
  if (loading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {[1, 2, 3].map((n) => (
          <div
            key={n}
            className="animate-pulse rounded-xl border bg-card p-6 shadow-sm space-y-4"
          >
            <div className="flex justify-between">
              <div className="h-5 w-20 rounded bg-muted" />
              <div className="h-5 w-16 rounded bg-muted" />
            </div>
            <div className="h-6 w-3/4 rounded bg-muted" />
            <div className="h-12 w-full rounded bg-muted" />
            <div className="h-8 w-full border-t pt-3 flex justify-between">
              <div className="h-4 w-24 rounded bg-muted" />
              <div className="h-4 w-12 rounded bg-muted" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  // State 1: Completely empty database
  if (allProjectsCount === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed bg-card p-8 text-center sm:p-14">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-muted text-muted-foreground shadow-inner">
          <FolderKanban size={32} aria-hidden="true" />
        </div>
        <h3 className="mt-4 text-lg font-bold tracking-tight text-foreground sm:text-xl">
          No research projects yet
        </h3>
        <p className="mt-2 max-w-md text-sm text-muted-foreground">
          Create your first research workspace to begin analyzing information gaps, conflicting claims, and verification checklists.
        </p>
        <button
          type="button"
          onClick={onCreateNew}
          className="mt-6 inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90 active:scale-95"
        >
          <Plus size={16} />
          <span>Create Research Project</span>
        </button>
      </div>
    );
  }

  // State 2: Filter yielded no results
  if (projects.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed bg-card p-8 text-center sm:p-12">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-muted text-muted-foreground">
          <SearchX size={26} aria-hidden="true" />
        </div>
        <h3 className="mt-3 text-base font-bold text-foreground">
          No matching research projects
        </h3>
        <p className="mt-1 max-w-sm text-xs text-muted-foreground sm:text-sm">
          No projects matched your active search query or filter criteria. Try adjusting or clearing your filters.
        </p>
        {onClearFilters && (
          <button
            type="button"
            onClick={onClearFilters}
            className="mt-4 inline-flex items-center gap-1.5 rounded-lg border bg-background px-4 py-2 text-xs font-semibold text-foreground hover:bg-muted"
          >
            Reset Filters
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {projects.map((project) => (
        <ResearchCard
          key={project.id}
          project={project}
          onView={onView}
          onEdit={onEdit}
          onDelete={onDelete}
        />
      ))}
    </div>
  );
}
