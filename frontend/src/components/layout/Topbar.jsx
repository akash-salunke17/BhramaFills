import { Bell, Search, Menu } from "lucide-react";

export default function Topbar({ activePage, onToggleSidebar }) {
  return (
    <header className="flex h-16 items-center justify-between border-b bg-card px-4 sm:px-6">
      <div className="flex items-center gap-3">
        {onToggleSidebar && (
          <button
            type="button"
            onClick={onToggleSidebar}
            aria-label="Open navigation menu"
            className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground md:hidden"
          >
            <Menu size={20} />
          </button>
        )}
        <div>
          <h2 className="text-lg font-bold tracking-tight text-foreground">
            {activePage}
          </h2>
          <p className="hidden text-xs font-medium text-muted-foreground sm:block">
            AI-assisted information gap detection
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3 sm:gap-4">
        <div className="hidden items-center gap-2 rounded-lg border bg-background/50 px-3 py-1.5 transition-colors focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/20 sm:flex">
          <Search size={16} className="text-muted-foreground" aria-hidden="true" />
          <input
            type="search"
            placeholder="Search workspaces..."
            aria-label="Search workspaces"
            className="w-36 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none lg:w-48"
          />
        </div>

        <button
          type="button"
          aria-label="Notifications"
          className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <Bell size={19} />
        </button>

        <div
          title="Bharmafills User"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-bold text-primary-foreground shadow-sm"
        >
          D
        </div>
      </div>
    </header>
  );
}
