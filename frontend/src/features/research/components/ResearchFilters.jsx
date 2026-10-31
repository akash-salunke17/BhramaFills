import { Search, Filter, ArrowUpDown, X } from "lucide-react";
import { STATUSES, CATEGORIES } from "../schemas/researchValidation";

export default function ResearchFilters({
  searchQuery,
  onSearchChange,
  selectedStatus,
  onStatusChange,
  selectedCategory,
  onCategoryChange,
  sortBy,
  onSortChange,
  totalResults,
}) {
  const hasActiveFilters =
    Boolean(searchQuery) ||
    selectedStatus !== "All" ||
    selectedCategory !== "All" ||
    sortBy !== "recent_updated";

  const handleClear = () => {
    onSearchChange("");
    onStatusChange("All");
    onCategoryChange("All");
    onSortChange("recent_updated");
  };

  return (
    <div className="space-y-4 rounded-xl border bg-card p-4 shadow-sm sm:p-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        {/* Search input */}
        <div className="relative flex-1">
          <Search
            size={16}
            className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <input
            type="search"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search projects by title, question, or description..."
            aria-label="Search projects"
            className="w-full rounded-lg border border-border bg-background py-2 pl-9 pr-8 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-ring focus:ring-2 focus:ring-ring/20"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => onSearchChange("")}
              aria-label="Clear search query"
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X size={14} />
            </button>
          )}
        </div>

        {/* Dropdowns row */}
        <div className="flex flex-wrap items-center gap-2.5 sm:gap-3">
          {/* Status selector */}
          <div className="flex items-center gap-1.5">
            <Filter size={14} className="text-muted-foreground" aria-hidden="true" />
            <select
              value={selectedStatus}
              onChange={(e) => onStatusChange(e.target.value)}
              aria-label="Filter by status"
              className="rounded-lg border border-border bg-background px-3 py-2 text-xs font-semibold text-foreground outline-none focus:border-ring sm:text-sm"
            >
              <option value="All">All Statuses</option>
              {STATUSES.map((st) => (
                <option key={st} value={st}>
                  {st}
                </option>
              ))}
            </select>
          </div>

          {/* Category selector */}
          <select
            value={selectedCategory}
            onChange={(e) => onCategoryChange(e.target.value)}
            aria-label="Filter by category"
            className="rounded-lg border border-border bg-background px-3 py-2 text-xs font-semibold text-foreground outline-none focus:border-ring sm:text-sm"
          >
            <option value="All">All Categories</option>
            {CATEGORIES.map((cat) => (
              <option key={cat} value={cat}>
                {cat}
              </option>
            ))}
          </select>

          {/* Sort selector */}
          <div className="flex items-center gap-1.5">
            <ArrowUpDown size={14} className="text-muted-foreground" aria-hidden="true" />
            <select
              value={sortBy}
              onChange={(e) => onSortChange(e.target.value)}
              aria-label="Sort projects"
              className="rounded-lg border border-border bg-background px-3 py-2 text-xs font-semibold text-foreground outline-none focus:border-ring sm:text-sm"
            >
              <option value="recent_updated">Recently Updated</option>
              <option value="recent_created">Recently Created</option>
              <option value="alphabetical">Alphabetical (A-Z)</option>
            </select>
          </div>

          {/* Clear filters button */}
          {hasActiveFilters && (
            <button
              type="button"
              onClick={handleClear}
              className="inline-flex items-center gap-1 rounded-lg border bg-muted px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-muted/80"
            >
              <X size={12} />
              <span>Reset</span>
            </button>
          )}
        </div>
      </div>

      {/* Result counter indicator */}
      <div className="flex items-center justify-between text-xs text-muted-foreground border-t pt-2.5">
        <span>
          Showing <strong className="text-foreground">{totalResults}</strong>{" "}
          {totalResults === 1 ? "project" : "projects"}
        </span>
        {hasActiveFilters && (
          <span className="italic">Filters applied</span>
        )}
      </div>
    </div>
  );
}
