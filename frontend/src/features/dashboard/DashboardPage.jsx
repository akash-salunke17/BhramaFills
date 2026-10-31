import {
  FolderKanban,
  Files,
  AlertTriangle,
  ClipboardCheck,
  Plus,
  ArrowRight,
  Clock,
  Tag,
} from "lucide-react";
import { useResearchProjects } from "../research/hooks/useResearchProjects";
import { getStatusBadgeClass } from "../research/utils/researchStatus";

export default function DashboardPage({ onNavigate }) {
  const { allProjects, stats } = useResearchProjects();

  const dynamicStats = [
    {
      title: "Research Projects",
      value: stats.total.toString(),
      description:
        stats.total > 0
          ? `${stats.inProgress} in progress, ${stats.draft} draft${stats.draft === 1 ? "" : "s"}`
          : "Total research workspaces",
      icon: FolderKanban,
    },
    {
      title: "Sources Collected",
      value: "0",
      description: "Web pages and PDF files",
      icon: Files,
    },
    {
      title: "Information Gaps",
      value: "0",
      description: "Issues identified",
      icon: AlertTriangle,
    },
    {
      title: "Pending Checks",
      value: "0",
      description: "Items to verify",
      icon: ClipboardCheck,
    },
  ];

  const steps = [
    ["01", "Create research", "Enter your research question."],
    ["02", "Add sources", "Provide URLs and upload PDFs."],
    ["03", "Analyze gaps", "Find missing or conflicting information."],
    ["04", "Verify findings", "Review evidence and checklist items."],
  ];

  // Up to 3 most recently updated projects
  const recentProjects = allProjects.slice(0, 3);

  return (
    <div className="space-y-8 p-4 sm:p-6 lg:p-8">
      {/* Workspace Overview & Welcome Heading */}
      <section>
        <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
          Workspace Overview
        </p>
        <h1 className="mt-2 text-2xl font-bold tracking-tight text-foreground sm:text-3xl lg:text-4xl">
          Welcome to Bharmafills
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
          Discover missing information, conflicting claims, and unanswered
          questions across your research sources.
        </p>
      </section>

      {/* 4 Key Statistics Cards */}
      <section aria-label="Key Statistics" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {dynamicStats.map((stat) => {
          const Icon = stat.icon;

          return (
            <div
              key={stat.title}
              className="rounded-xl border bg-card p-5 shadow-sm transition-shadow hover:shadow-md"
            >
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium text-muted-foreground">
                  {stat.title}
                </p>
                <Icon className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
              </div>

              <p className="mt-4 text-3xl font-bold tracking-tight text-foreground">
                {stat.value}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {stat.description}
              </p>
            </div>
          );
        })}
      </section>

      {/* Main Content Sections: Recent Research & How it Works */}
      <section className="grid gap-6 lg:grid-cols-3">
        {/* Recent Research Card */}
        <div className="rounded-xl border bg-card p-6 shadow-sm lg:col-span-2">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-lg font-bold tracking-tight text-foreground">
                Recent Research
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {allProjects.length > 0
                  ? `Showing latest ${recentProjects.length} of ${allProjects.length} workspaces`
                  : "Your latest research workspaces will appear here."}
              </p>
            </div>

            <button
              type="button"
              onClick={() => onNavigate("Research", "new")}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm transition-opacity hover:opacity-90 active:scale-95"
            >
              <Plus className="h-4 w-4" />
              <span>New Research</span>
            </button>
          </div>

          {allProjects.length === 0 ? (
            <div className="mt-8 rounded-lg border border-dashed p-8 text-center sm:p-12">
              <FolderKanban className="mx-auto h-10 w-10 text-muted-foreground" aria-hidden="true" />
              <h3 className="mt-4 text-base font-semibold text-foreground">
                No research projects yet
              </h3>
              <p className="mt-2 text-sm text-muted-foreground">
                Create your first research project to start finding information gaps.
              </p>
              <button
                type="button"
                onClick={() => onNavigate("Research", "new")}
                className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-primary transition-colors hover:underline"
              >
                <span>Create your first project</span>
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          ) : (
            <div className="mt-6 divide-y rounded-xl border">
              {recentProjects.map((p) => (
                <div
                  key={p.id}
                  onClick={() => onNavigate("Research")}
                  className="flex cursor-pointer items-center justify-between p-4 transition-colors hover:bg-muted/40 sm:p-5"
                >
                  <div className="min-w-0 flex-1 pr-4">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex items-center gap-1 rounded bg-muted px-2 py-0.5 text-[11px] font-semibold text-foreground">
                        <Tag size={10} className="text-muted-foreground" />
                        {p.category}
                      </span>
                      <span
                        className={`rounded border px-2 py-0.5 text-[11px] font-bold ${getStatusBadgeClass(
                          p.status
                        )}`}
                      >
                        {p.status}
                      </span>
                    </div>
                    <h4 className="mt-1.5 truncate text-sm font-bold text-foreground sm:text-base">
                      {p.title}
                    </h4>
                    <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">
                      {p.researchQuestion}
                    </p>
                  </div>

                  <div className="flex shrink-0 items-center gap-3">
                    <span className="hidden items-center gap-1 text-xs text-muted-foreground sm:inline-flex">
                      <Clock size={12} />
                      {new Date(p.updatedAt).toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                      })}
                    </span>
                    <ArrowRight size={16} className="text-muted-foreground" />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* How It Works Card */}
        <div className="rounded-xl border bg-card p-6 shadow-sm">
          <h2 className="text-lg font-bold tracking-tight text-foreground">
            How it works
          </h2>

          <div className="mt-6 space-y-6">
            {steps.map(([number, title, description]) => (
              <div key={number} className="flex gap-3">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-xs font-bold text-foreground">
                  {number}
                </span>
                <div>
                  <p className="text-sm font-semibold text-foreground">{title}</p>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                    {description}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
