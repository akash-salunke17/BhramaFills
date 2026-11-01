export default function GapAnalysisSkeleton({ count = 3 }) {
  return (
    <div className="space-y-4 animate-pulse" aria-label="Loading gap findings">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-2xl border bg-card p-5 shadow-sm sm:p-6 space-y-3.5">
          {/* Top badges */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="h-5 w-20 rounded-md bg-muted" />
              <div className="h-5 w-28 rounded-md bg-muted" />
            </div>
            <div className="h-5 w-24 rounded-md bg-muted" />
          </div>

          {/* Title line */}
          <div className="h-6 w-3/4 rounded-lg bg-muted" />

          {/* Description line */}
          <div className="space-y-1.5">
            <div className="h-4 w-full rounded bg-muted/80" />
            <div className="h-4 w-5/6 rounded bg-muted/70" />
          </div>

          {/* Bottom actions */}
          <div className="flex items-center justify-between border-t pt-3">
            <div className="h-6 w-48 rounded bg-muted/60" />
            <div className="h-7 w-28 rounded-lg bg-muted" />
          </div>
        </div>
      ))}
    </div>
  );
}
