import { describe, it, expect } from "vitest";
import {
  validateResearchProject,
  CATEGORIES,
  STATUSES,
  DEFAULT_STATUS,
} from "../features/research/schemas/researchValidation";

describe("Research Project Validation Schema", () => {
  const validPayload = {
    title: "AI in Climate Tech",
    researchQuestion: "How do transformer models optimize energy consumption in smart grids?",
    description: "An in-depth literature review across 2024-2026 publications.",
    category: "Technology",
    status: "Draft",
  };

  it("accepts a valid payload", () => {
    const result = validateResearchProject(validPayload);
    expect(result.isValid).toBe(true);
    expect(result.errors).toEqual({});
    expect(result.cleanedData.title).toBe("AI in Climate Tech");
    expect(result.cleanedData.status).toBe("Draft");
  });

  describe("Title field rules", () => {
    it("rejects missing or empty title", () => {
      const result = validateResearchProject({ ...validPayload, title: "" });
      expect(result.isValid).toBe(false);
      expect(result.errors.title).toMatch(/required/i);
    });

    it("rejects title with only whitespace", () => {
      const result = validateResearchProject({ ...validPayload, title: "   " });
      expect(result.isValid).toBe(false);
      expect(result.errors.title).toMatch(/required/i);
    });

    it("rejects title shorter than 3 characters", () => {
      const result = validateResearchProject({ ...validPayload, title: "AI" });
      expect(result.isValid).toBe(false);
      expect(result.errors.title).toMatch(/at least 3 characters/i);
    });

    it("rejects title longer than 120 characters", () => {
      const longTitle = "a".repeat(121);
      const result = validateResearchProject({ ...validPayload, title: longTitle });
      expect(result.isValid).toBe(false);
      expect(result.errors.title).toMatch(/cannot exceed 120 characters/i);
    });

    it("trims whitespace from title", () => {
      const result = validateResearchProject({ ...validPayload, title: "  Trimmed Title  " });
      expect(result.isValid).toBe(true);
      expect(result.cleanedData.title).toBe("Trimmed Title");
    });
  });

  describe("Research Question field rules", () => {
    it("rejects empty research question", () => {
      const result = validateResearchProject({ ...validPayload, researchQuestion: "" });
      expect(result.isValid).toBe(false);
      expect(result.errors.researchQuestion).toMatch(/required/i);
    });

    it("rejects research question shorter than 10 characters", () => {
      const result = validateResearchProject({ ...validPayload, researchQuestion: "What is?" });
      expect(result.isValid).toBe(false);
      expect(result.errors.researchQuestion).toMatch(/at least 10 characters/i);
    });

    it("rejects research question longer than 1000 characters", () => {
      const longQ = "q".repeat(1001);
      const result = validateResearchProject({ ...validPayload, researchQuestion: longQ });
      expect(result.isValid).toBe(false);
      expect(result.errors.researchQuestion).toMatch(/cannot exceed 1000 characters/i);
    });

    it("trims whitespace from research question", () => {
      const result = validateResearchProject({
        ...validPayload,
        researchQuestion: "   Does this question have valid trimmed content?   ",
      });
      expect(result.isValid).toBe(true);
      expect(result.cleanedData.researchQuestion).toBe(
        "Does this question have valid trimmed content?"
      );
    });
  });

  describe("Description field rules", () => {
    it("accepts empty optional description", () => {
      const result = validateResearchProject({ ...validPayload, description: "" });
      expect(result.isValid).toBe(true);
      expect(result.cleanedData.description).toBe("");
    });

    it("rejects description exceeding 2000 characters", () => {
      const longDesc = "d".repeat(2001);
      const result = validateResearchProject({ ...validPayload, description: longDesc });
      expect(result.isValid).toBe(false);
      expect(result.errors.description).toMatch(/cannot exceed 2000 characters/i);
    });
  });

  describe("Category and Status rules", () => {
    it("rejects invalid category not in permitted list", () => {
      const result = validateResearchProject({ ...validPayload, category: "Astrology" });
      expect(result.isValid).toBe(false);
      expect(result.errors.category).toMatch(/invalid category/i);
    });

    it("rejects invalid status", () => {
      const result = validateResearchProject({ ...validPayload, status: "UnknownStatus" });
      expect(result.isValid).toBe(false);
      expect(result.errors.status).toMatch(/invalid status/i);
    });

    it("defaults status to Draft when omitted", () => {
      const withoutStatus = { ...validPayload };
      delete withoutStatus.status;
      const result = validateResearchProject(withoutStatus);
      expect(result.isValid).toBe(true);
      expect(result.cleanedData.status).toBe(DEFAULT_STATUS);
    });

    it("allows all official categories", () => {
      CATEGORIES.forEach((cat) => {
        const result = validateResearchProject({ ...validPayload, category: cat });
        expect(result.isValid).toBe(true);
      });
    });

    it("allows all official statuses", () => {
      STATUSES.forEach((st) => {
        const result = validateResearchProject({ ...validPayload, status: st });
        expect(result.isValid).toBe(true);
      });
    });
  });

  describe("Hardening & Boundary tests", () => {
    it("safely handles null and non-object inputs without crashing", () => {
      const nullRes = validateResearchProject(null);
      expect(nullRes.isValid).toBe(false);
      expect(nullRes.errors.title).toBeDefined();

      const numRes = validateResearchProject(42);
      expect(numRes.isValid).toBe(false);

      const strRes = validateResearchProject("not an object");
      expect(strRes.isValid).toBe(false);
    });

    it("verifies exact boundary lengths for title (3 and 120 chars)", () => {
      const minTitle = validateResearchProject({ ...validPayload, title: "abc" });
      expect(minTitle.isValid).toBe(true);

      const maxTitle = validateResearchProject({ ...validPayload, title: "a".repeat(120) });
      expect(maxTitle.isValid).toBe(true);

      const overMaxTitle = validateResearchProject({ ...validPayload, title: "a".repeat(121) });
      expect(overMaxTitle.isValid).toBe(false);
      expect(overMaxTitle.errors.title).toMatch(/cannot exceed 120 characters/i);
    });

    it("verifies exact boundary lengths for research question (10 and 1000 chars)", () => {
      const belowMinQ = validateResearchProject({ ...validPayload, researchQuestion: "123456789" });
      expect(belowMinQ.isValid).toBe(false);

      const minQ = validateResearchProject({ ...validPayload, researchQuestion: "1234567890" });
      expect(minQ.isValid).toBe(true);

      const maxQ = validateResearchProject({ ...validPayload, researchQuestion: "q".repeat(1000) });
      expect(maxQ.isValid).toBe(true);

      const overMaxQ = validateResearchProject({ ...validPayload, researchQuestion: "q".repeat(1001) });
      expect(overMaxQ.isValid).toBe(false);
    });

    it("supports multiline content in research question", () => {
      const multiline = "Line 1: Problem statement.\nLine 2: Target methodology.\nLine 3: Key claim?";
      const res = validateResearchProject({ ...validPayload, researchQuestion: multiline });
      expect(res.isValid).toBe(true);
      expect(res.cleanedData.researchQuestion).toBe(multiline);
    });

    it("verifies exact boundary for description (2000 chars)", () => {
      const maxDesc = validateResearchProject({ ...validPayload, description: "d".repeat(2000) });
      expect(maxDesc.isValid).toBe(true);

      const overMaxDesc = validateResearchProject({ ...validPayload, description: "d".repeat(2001) });
      expect(overMaxDesc.isValid).toBe(false);
    });
  });
});
