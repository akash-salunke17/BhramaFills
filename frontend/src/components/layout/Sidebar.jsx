import {
  LayoutDashboard,
  FolderKanban,
  Files,
  ScanSearch,
  ClipboardCheck,
  Settings,
  Scan,
  X,
} from "lucide-react";

const navigation = [
  { label: "Overview", icon: LayoutDashboard },
  { label: "Research", icon: FolderKanban },
  { label: "Sources", icon: Files },
  { label: "Analysis", icon: ScanSearch },
  { label: "Checklist", icon: ClipboardCheck },
];

export default function Sidebar({
  activePage,
  onNavigate,
  mobileOpen = false,
  onClose,
}) {
  const content = (
    <div className="flex h-full flex-col justify-between">
      <div>
        <div className="mb-8 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
              <Scan size={20} />
            </div>
            <div>
              <span className="block text-sm font-bold tracking-tight text-foreground">
                BHARMAFILLS
              </span>
              <span className="block text-xs font-medium text-muted-foreground">
                Research intelligence
              </span>
            </div>
          </div>
          {onClose && (
            <button
              onClick={onClose}
              aria-label="Close sidebar"
              className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground md:hidden"
            >
              <X size={18} />
            </button>
          )}
        </div>

        <p className="mb-3 px-3 text-xs font-bold uppercase tracking-wider text-muted-foreground">
          Workspace
        </p>

        <nav aria-label="Main Navigation" className="flex flex-col gap-1">
          {navigation.map(({ label, icon: Icon }) => {
            const isActive = activePage === label;
            return (
              <button
                key={label}
                onClick={() => {
                  onNavigate(label);
                  if (onClose) onClose();
                }}
                aria-current={isActive ? "page" : undefined}
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
              >
                <Icon size={18} />
                <span>{label}</span>
              </button>
            );
          })}
        </nav>
      </div>

      <div className="border-t pt-4">
        <button
          type="button"
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <Settings size={18} />
          <span>Settings</span>
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop Sidebar */}
      <aside className="hidden w-64 shrink-0 flex-col border-r bg-card p-5 md:flex">
        {content}
      </aside>

      {/* Mobile Drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden" role="dialog" aria-modal="true">
          <div
            className="fixed inset-0 bg-background/80 backdrop-blur-sm"
            onClick={onClose}
            aria-hidden="true"
          />
          <aside className="relative flex w-72 max-w-[80vw] flex-col border-r bg-card p-5 shadow-2xl">
            {content}
          </aside>
        </div>
      )}
    </>
  );
}
