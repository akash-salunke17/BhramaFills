import { useState } from "react";
import Sidebar from "@/components/layout/Sidebar";
import Topbar from "@/components/layout/Topbar";
import DashboardPage from "@/features/dashboard/DashboardPage";
import { ResearchPage } from "@/features/research";

function App() {
  const [activePage, setActivePage] = useState("Overview");
  const [researchAction, setResearchAction] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const handleNavigate = (page, action = null) => {
    setActivePage(page);
    setResearchAction(action);
    setSidebarOpen(false);
  };

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <Sidebar
        activePage={activePage}
        onNavigate={(page) => handleNavigate(page, null)}
        mobileOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar
          activePage={activePage}
          onToggleSidebar={() => setSidebarOpen((prev) => !prev)}
        />

        <main className="min-w-0 flex-1">
          {activePage === "Overview" ? (
            <DashboardPage onNavigate={handleNavigate} />
          ) : activePage === "Research" ? (
            <ResearchPage initialAction={researchAction} />
          ) : (
            <div className="p-4 sm:p-6 lg:p-8">
              <h1 className="text-2xl font-bold tracking-tight text-foreground">
                {activePage}
              </h1>
              <p className="mt-2 text-sm text-muted-foreground">
                This module will be implemented and tested separately.
              </p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
