import { useState, useEffect } from "react";
import {
  CATEGORIES,
  STATUSES,
  DEFAULT_CATEGORY,
  DEFAULT_STATUS,
  validateResearchProject,
} from "../schemas/researchValidation";
import { X, AlertCircle } from "lucide-react";

export default function ResearchForm({
  project = null,
  isOpen = false,
  onSave,
  onCancel,
}) {
  const isEditing = Boolean(project && project.id);

  const [formData, setFormData] = useState({
    title: project?.title || "",
    researchQuestion: project?.researchQuestion || "",
    description: project?.description || "",
    category: project?.category || DEFAULT_CATEGORY,
    status: project?.status || DEFAULT_STATUS,
  });

  const [errors, setErrors] = useState({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [generalError, setGeneralError] = useState("");

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e) => {
      if (e.key === "Escape" && !isSubmitting) {
        onCancel();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, isSubmitting, onCancel]);

  if (!isOpen) return null;

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
    // Clear field-specific error as user types
    if (errors[name]) {
      setErrors((prev) => {
        const next = { ...prev };
        delete next[name];
        return next;
      });
    }
    if (generalError) setGeneralError("");
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (isSubmitting) return;

    const validation = validateResearchProject(formData);
    if (!validation.isValid) {
      setErrors(validation.errors);
      return;
    }

    try {
      setIsSubmitting(true);
      setGeneralError("");
      await onSave(validation.cleanedData);
    } catch (err) {
      console.error("[ResearchForm] Save error:", err);
      setGeneralError(err.message || "Failed to save research project.");
      if (err.validationErrors) {
        setErrors(err.validationErrors);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="research-form-title"
    >
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-background/80 backdrop-blur-sm"
        onClick={!isSubmitting ? onCancel : undefined}
        aria-hidden="true"
      />

      {/* Modal Dialog Card */}
      <div className="relative max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-2xl border bg-card p-6 shadow-2xl sm:p-8">
        <div className="flex items-center justify-between border-b pb-4">
          <div>
            <h2
              id="research-form-title"
              className="text-xl font-bold tracking-tight text-foreground"
            >
              {isEditing ? "Edit Research Project" : "Create New Research Project"}
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              {isEditing
                ? "Update your project parameters and inquiry details."
                : "Define your core investigation question and metadata."}
            </p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            disabled={isSubmitting}
            aria-label="Close form"
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
          >
            <X size={20} />
          </button>
        </div>

        {generalError && (
          <div
            role="alert"
            className="mt-4 flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/10 p-3 text-sm text-destructive"
          >
            <AlertCircle size={16} className="shrink-0" />
            <span>{generalError}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-6 space-y-5" noValidate>
          {/* Research Title */}
          <div>
            <div className="flex items-center justify-between">
              <label
                htmlFor="research-title"
                className="block text-xs font-bold uppercase tracking-wider text-foreground"
              >
                Research Title <span className="text-destructive">*</span>
              </label>
              <span className="text-xs text-muted-foreground">
                {formData.title.length}/120
              </span>
            </div>
            <input
              id="research-title"
              name="title"
              type="text"
              required
              value={formData.title}
              onChange={handleChange}
              disabled={isSubmitting}
              placeholder="e.g. AI-Assisted Medical Diagnostic Accuracy"
              className={`mt-1.5 w-full rounded-lg border bg-background px-3.5 py-2.5 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:ring-2 ${
                errors.title
                  ? "border-destructive focus:border-destructive focus:ring-destructive/20"
                  : "border-border focus:border-ring focus:ring-ring/20"
              }`}
            />
            {errors.title && (
              <p className="mt-1 text-xs font-medium text-destructive">{errors.title}</p>
            )}
          </div>

          {/* Research Question */}
          <div>
            <div className="flex items-center justify-between">
              <label
                htmlFor="research-question"
                className="block text-xs font-bold uppercase tracking-wider text-foreground"
              >
                Research Question <span className="text-destructive">*</span>
              </label>
              <span className="text-xs text-muted-foreground">
                {formData.researchQuestion.length}/1000
              </span>
            </div>
            <textarea
              id="research-question"
              name="researchQuestion"
              required
              rows={4}
              value={formData.researchQuestion}
              onChange={handleChange}
              disabled={isSubmitting}
              placeholder="What specific claim, gap, or unanswered question are you investigating across sources?"
              className={`mt-1.5 w-full rounded-lg border bg-background px-3.5 py-2.5 text-sm leading-relaxed text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:ring-2 ${
                errors.researchQuestion
                  ? "border-destructive focus:border-destructive focus:ring-destructive/20"
                  : "border-border focus:border-ring focus:ring-ring/20"
              }`}
            />
            {errors.researchQuestion && (
              <p className="mt-1 text-xs font-medium text-destructive">
                {errors.researchQuestion}
              </p>
            )}
          </div>

          {/* Description (Optional) */}
          <div>
            <div className="flex items-center justify-between">
              <label
                htmlFor="research-description"
                className="block text-xs font-bold uppercase tracking-wider text-foreground"
              >
                Description <span className="text-xs font-normal text-muted-foreground">(Optional)</span>
              </label>
              <span className="text-xs text-muted-foreground">
                {formData.description.length}/2000
              </span>
            </div>
            <textarea
              id="research-description"
              name="description"
              rows={3}
              value={formData.description}
              onChange={handleChange}
              disabled={isSubmitting}
              placeholder="Additional background, context, target domains, or methodological scope..."
              className="mt-1.5 w-full rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm leading-relaxed text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-ring focus:ring-2 focus:ring-ring/20"
            />
            {errors.description && (
              <p className="mt-1 text-xs font-medium text-destructive">
                {errors.description}
              </p>
            )}
          </div>

          {/* Category & Status */}
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label
                htmlFor="research-category"
                className="block text-xs font-bold uppercase tracking-wider text-foreground"
              >
                Category <span className="text-destructive">*</span>
              </label>
              <select
                id="research-category"
                name="category"
                value={formData.category}
                onChange={handleChange}
                disabled={isSubmitting}
                className="mt-1.5 w-full rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm text-foreground outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/20"
              >
                {CATEGORIES.map((cat) => (
                  <option key={cat} value={cat}>
                    {cat}
                  </option>
                ))}
              </select>
              {errors.category && (
                <p className="mt-1 text-xs font-medium text-destructive">
                  {errors.category}
                </p>
              )}
            </div>

            <div>
              <label
                htmlFor="research-status"
                className="block text-xs font-bold uppercase tracking-wider text-foreground"
              >
                Status
              </label>
              <select
                id="research-status"
                name="status"
                value={formData.status}
                onChange={handleChange}
                disabled={isSubmitting}
                className="mt-1.5 w-full rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm text-foreground outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/20"
              >
                {STATUSES.map((st) => (
                  <option key={st} value={st}>
                    {st}
                  </option>
                ))}
              </select>
              {errors.status && (
                <p className="mt-1 text-xs font-medium text-destructive">
                  {errors.status}
                </p>
              )}
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex flex-col-reverse gap-3 border-t pt-5 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={onCancel}
              disabled={isSubmitting}
              className="inline-flex justify-center rounded-lg border bg-background px-5 py-2.5 text-sm font-semibold text-foreground shadow-sm hover:bg-muted disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90 active:scale-95 disabled:opacity-50"
            >
              {isSubmitting
                ? "Saving..."
                : isEditing
                ? "Save Changes"
                : "Create Project"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
