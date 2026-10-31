export const CATEGORIES = [
  "Education",
  "Technology",
  "Scholarships",
  "Healthcare",
  "Business",
  "Government Schemes",
  "General Research",
  "Other",
];

export const STATUSES = [
  "Draft",
  "In Progress",
  "Completed",
  "Archived",
];

export const DEFAULT_CATEGORY = "General Research";
export const DEFAULT_STATUS = "Draft";

/**
 * Validates research project input fields according to Phase 2 standards.
 *
 * @param {Object} data Input values
 * @param {string} [data.title] Project title (3-120 chars)
 * @param {string} [data.researchQuestion] Main research question (10-1000 chars)
 * @param {string} [data.description] Optional project description (max 2000 chars)
 * @param {string} [data.category] Project domain category
 * @param {string} [data.status] Lifecycle status
 * @returns {{ isValid: boolean, errors: Record<string, string>, cleanedData: Object }}
 */
export function validateResearchProject(inputData = {}) {
  const errors = {};
  const data = inputData && typeof inputData === "object" ? inputData : {};

  const toSafeString = (val) => {
    if (typeof val === "string") return val.trim();
    if (typeof val === "number" && !Number.isNaN(val)) return String(val).trim();
    return "";
  };

  const title = toSafeString(data.title);
  const researchQuestion = toSafeString(data.researchQuestion);
  const description = toSafeString(data.description);
  const category = toSafeString(data.category);
  const status = toSafeString(data.status);

  // 1. Title validation
  if (!title) {
    errors.title = "Research title is required.";
  } else if (title.length < 3) {
    errors.title = "Research title must be at least 3 characters long.";
  } else if (title.length > 120) {
    errors.title = "Research title cannot exceed 120 characters.";
  }

  // 2. Research question validation
  if (!researchQuestion) {
    errors.researchQuestion = "Research question is required.";
  } else if (researchQuestion.length < 10) {
    errors.researchQuestion = "Research question must be at least 10 characters long.";
  } else if (researchQuestion.length > 1000) {
    errors.researchQuestion = "Research question cannot exceed 1000 characters.";
  }

  // 3. Description validation (optional)
  if (description.length > 2000) {
    errors.description = "Description cannot exceed 2000 characters.";
  }

  // 4. Category validation
  if (!category) {
    errors.category = "Please select a category.";
  } else if (!CATEGORIES.includes(category)) {
    errors.category = `Invalid category. Must be one of: ${CATEGORIES.join(", ")}`;
  }

  // 5. Status validation
  if (status && !STATUSES.includes(status)) {
    errors.status = `Invalid status. Must be one of: ${STATUSES.join(", ")}`;
  }

  const isValid = Object.keys(errors).length === 0;

  return {
    isValid,
    errors,
    cleanedData: {
      title,
      researchQuestion,
      description,
      category: category || DEFAULT_CATEGORY,
      status: status || DEFAULT_STATUS,
    },
  };
}
