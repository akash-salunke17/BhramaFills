import { Filter, ArrowUpDown, X } from "lucide-react";

export default function GapFilters({
  selectedPriority,
  onSelectPriority,
  selectedGapType,
  onSelectGapType,
  selectedStatus,
  onSelectStatus,
  sortBy,
  onSelectSort,
  totalCount,
  filteredCount,
}) {
  const isFiltered =
    selectedPriority !== "all" || selectedGapType !== "all" || selectedStatus !== "all";

  const handleClearFilters = () => {
    onSelectPriority("all");
    onSelectGapType("all");
    onSelectStatus("all");
  };

  return (
    <div className="space-y-3 rounded-2xl border bg-card p-4 shadow-sm sm:p-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        {/* Left: Filter Selectors */}
        <div className="flex flex-wrap items-center gap-2.5">
          <div className="flex items-center gap-1.5 text-xs font-bold text-muted-foreground uppercase tracking-wider mr-1">
            <Filter size={14} />
            <span>Filters:</span>
          </div>

          {/* Priority Filter */}
          <select
            value={selectedPriority}
            onChange={(e) => onSelectPriority(e.target.value)}
            aria-label="Filter by priority"
            className="rounded-lg border bg-background px-3 py-1.5 text-xs font-semibold text-foreground shadow-sm focus:border-primary focus:outline-none"
          >
            <option value="all">All Priorities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>

          {/* Gap Type Filter */}
          <select
            value={selectedGapType}
            onChange={(e) => onSelectGapType(e.target.value)}
            aria-label="Filter by gap type"
            className="rounded-lg border bg-background px-3 py-1.5 text-xs font-semibold text-foreground shadow-sm focus:border-primary focus:outline-none"
          >
            <option value="all">All Gap Types</option>
            <option value="no_evidence">No Evidence</option>
            <option value="insufficient_evidence">Insufficient Evidence</option>
            <option value="conflicting_evidence">Conflicting Evidence</option>
            <option value="unverified">Unverified Claims</option>
          </select>

          {/* Status Filter */}
          <select
            value={selectedStatus}
            onChange={(e) => onSelectStatus(e.target.value)}
            aria-label="Filter by review status"
            className="rounded-lg border bg-background px-3 py-1.5 text-xs font-semibold text-foreground shadow-sm focus:border-primary focus:outline-none"
          >
            <option value="all">All Review States</option>
            <option value="open">Open</option>
            <option value="investigating">Investigating</option>
            <option value="resolved">Resolved</option>
            <option value="dismissed">Dismissed</option>
          </select>

          {/* Clear Filters Button */}
          {isFiltered && (
            <button
              type="button"
              onClick={handleClearFilters}
              className="inline-flex items-center gap-1 rounded-lg border border-dashed border-muted-foreground/30 px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X size={12} />
              <span>Reset</span>
            </button>
          )}
        </div>

        {/* Right: Sorting & Count */}
        <div className="flex items-center justify-between gap-3 border-t pt-3 lg:border-t-0 lg:pt-0">
          <span className="text-xs text-muted-foreground">
            Showing <strong className="text-foreground">{filteredCount}</strong> of{" "}
            <strong className="text-foreground">{totalCount}</strong> gaps
          </span>

          <div className="flex items-center gap-2">
            <ArrowUpDown size={14} className="text-muted-foreground shrink-0" />
            <select
              value={sortBy}
              onChange={(e) => onSelectSort(e.target.value)}
              aria-label="Sort gaps"
              className="rounded-lg border bg-background px-3 py-1.5 text-xs font-semibold text-foreground shadow-sm focus:border-primary focus:outline-none"
            >
              <option value="priority_desc">Highest Priority First</option>
              <option value="priority_asc">Lowest Priority First</option>
              <option value="recent_updated">Recently Updated</option>
              <option value="recent_created">Recently Created</option>
            </select>
          </div>
        </div>
      </div>
    </div>
  );
}
