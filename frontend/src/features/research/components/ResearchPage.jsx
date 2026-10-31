import { useState, useEffect } from "react";
import { useResearchProjects } from "../hooks/useResearchProjects";
import { researchService } from "../services/researchService";
import ResearchFilters from "./ResearchFilters";
import ResearchList from "./ResearchList";
import ResearchForm from "./ResearchForm";
import ResearchDetails from "./ResearchDetails";
import DeleteResearchDialog from "./DeleteResearchDialog";
import { Plus, CheckCircle, AlertCircle } from "lucide-react";

export default function ResearchPage({ initialAction = null }) {
  const {
    projects,
    totalCount,
    filteredCount,
    loading,
    error,
    searchQuery,
    setSearchQuery,
    selectedStatus,
    setSelectedStatus,
    selectedCategory,
    setSelectedCategory,
    sortBy,
    setSortBy,
    createProject,
    updateProject,
    deleteProject,
  } = useResearchProjects();

  // Navigation within Research module: "list" | "details"
  const [viewMode, setViewMode] = useState("list");
  const [selectedProject, setSelectedProject] = useState(null);

  // Modal states
  const [isFormOpen, setIsFormOpen] = useState(initialAction === "new");
  const [editingProject, setEditingProject] = useState(null);

  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [projectToDelete, setProjectToDelete] = useState(null);
  const [isDeleting, setIsDeleting] = useState(false);

  // Transient success notification
  const [successMessage, setSuccessMessage] = useState("");
  const [storageWarning] = useState(() => {
    const health = researchService.getStorageHealth();
    return health.persistent
      ? ""
      : health.warning ||
          "Session memory only — changes will not persist after page refresh.";
  });

  const showSuccess = (msg) => {
    setSuccessMessage(msg);
    setTimeout(() => setSuccessMessage(""), 4000);
  };

  // Open create form if initialAction is "new"
  useEffect(() => {
    if (initialAction === "new") {
      const timer = setTimeout(() => {
        setEditingProject(null);
        setIsFormOpen(true);
      }, 0);
      return () => clearTimeout(timer);
    }
  }, [initialAction]);

  // Handlers
  const handleOpenCreate = () => {
    setEditingProject(null);
    setIsFormOpen(true);
  };

  const handleOpenEdit = (project) => {
    setEditingProject(project);
    setIsFormOpen(true);
  };

  const handleOpenView = (project) => {
    setSelectedProject(project);
    setViewMode("details");
  };

  const handleOpenDelete = (project) => {
    setProjectToDelete(project);
    setIsDeleteDialogOpen(true);
  };

  const handleConfirmDelete = async (id) => {
    try {
      setIsDeleting(true);
      await deleteProject(id);
      setIsDeleteDialogOpen(false);
      setProjectToDelete(null);
      if (viewMode === "details" && selectedProject?.id === id) {
        setViewMode("list");
        setSelectedProject(null);
      }
      showSuccess("Research project deleted successfully.");
    } catch (err) {
      console.error("[ResearchPage] Delete error:", err);
    } finally {
      setIsDeleting(false);
    }
  };

  const handleSaveProject = async (cleanedData) => {
    if (editingProject) {
      const updated = await updateProject(editingProject.id, cleanedData);
      setIsFormOpen(false);
      setEditingProject(null);
      if (selectedProject?.id === updated.id) {
        setSelectedProject(updated);
      }
      showSuccess("Research project updated successfully.");
    } else {
      await createProject(cleanedData);
      setIsFormOpen(false);
      showSuccess("New research project created successfully.");
    }
  };

  return (
    <div className="space-y-6 p-4 sm:p-6 lg:p-8">
      {/* Success Notification Banner */}
      {successMessage && (
        <div
          role="status"
          aria-live="polite"
          className="flex items-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/10 p-3.5 text-sm font-medium text-emerald-800"
        >
          <CheckCircle size={18} className="text-emerald-600 shrink-0" />
          <span>{successMessage}</span>
        </div>
      )}

      {/* Storage Warning Banner (when running in session memory fallback) */}
      {storageWarning && (
        <div
          role="status"
          aria-live="polite"
          className="flex items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-500/10 p-3.5 text-sm font-medium text-amber-800"
        >
          <AlertCircle size={18} className="shrink-0 text-amber-600" />
          <span>{storageWarning}</span>
        </div>
      )}

      {/* Global Error Banner */}
      {error && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-xl border border-destructive/20 bg-destructive/10 p-3.5 text-sm font-medium text-destructive"
        >
          <AlertCircle size={18} className="shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* View Mode Switching */}
      {viewMode === "details" ? (
        <ResearchDetails
          project={selectedProject}
          onBack={() => {
            setViewMode("list");
            setSelectedProject(null);
          }}
          onEdit={handleOpenEdit}
          onDelete={handleOpenDelete}
        />
      ) : (
        <>
          {/* Header Bar */}
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                Research Workspaces
              </p>
              <h1 className="mt-1 text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
                Research Projects
              </h1>
              <p className="mt-1 text-xs text-muted-foreground sm:text-sm">
                Manage your ongoing inquiries, define gap detection questions, and track investigation progress.
              </p>
            </div>

            <button
              type="button"
              onClick={handleOpenCreate}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90 active:scale-95"
            >
              <Plus size={16} />
              <span>New Research</span>
            </button>
          </div>

          {/* Filters & Search (only shown when there are projects or active filters) */}
          {(totalCount > 0 || searchQuery || selectedStatus !== "All") && (
            <ResearchFilters
              searchQuery={searchQuery}
              onSearchChange={setSearchQuery}
              selectedStatus={selectedStatus}
              onStatusChange={setSelectedStatus}
              selectedCategory={selectedCategory}
              onCategoryChange={setSelectedCategory}
              sortBy={sortBy}
              onSortChange={setSortBy}
              totalResults={filteredCount}
            />
          )}

          {/* Project List */}
          <ResearchList
            projects={projects}
            allProjectsCount={totalCount}
            loading={loading}
            onView={handleOpenView}
            onEdit={handleOpenEdit}
            onDelete={handleOpenDelete}
            onCreateNew={handleOpenCreate}
            onClearFilters={() => {
              setSearchQuery("");
              setSelectedStatus("All");
              setSelectedCategory("All");
              setSortBy("recent_updated");
            }}
          />
        </>
      )}

      {/* Create / Edit Form Modal */}
      <ResearchForm
        key={editingProject ? editingProject.id : "new-project"}
        isOpen={isFormOpen}
        project={editingProject}
        onSave={handleSaveProject}
        onCancel={() => {
          setIsFormOpen(false);
          setEditingProject(null);
        }}
      />

      {/* Delete Confirmation Modal */}
      <DeleteResearchDialog
        isOpen={isDeleteDialogOpen}
        project={projectToDelete}
        onConfirm={handleConfirmDelete}
        onCancel={() => {
          setIsDeleteDialogOpen(false);
          setProjectToDelete(null);
        }}
        isDeleting={isDeleting}
      />
    </div>
  );
}
