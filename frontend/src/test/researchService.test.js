import { describe, it, expect, beforeEach } from "vitest";
import { researchService } from "../features/research/services/researchService";

describe("Research Service Layer", () => {
  beforeEach(async () => {
    localStorage.clear();
    await researchService.clearAll();
  });

  const validData = {
    title: "Quantum Error Mitigation",
    researchQuestion: "What methods currently yield lowest overhead in NISQ devices?",
    description: "Systematic review of zero-noise extrapolation and probabilistic error cancellation.",
    category: "Technology",
    status: "Draft",
  };

  it("returns an empty list when no projects are stored", async () => {
    const list = await researchService.getAllProjects();
    expect(list).toEqual([]);
  });

  it("creates a project with unique ID, ISO timestamps, and preserves data", async () => {
    const created = await researchService.createProject(validData);

    expect(created.id).toBeDefined();
    expect(typeof created.id).toBe("string");
    expect(created.title).toBe(validData.title);
    expect(created.researchQuestion).toBe(validData.researchQuestion);
    expect(created.category).toBe("Technology");
    expect(created.status).toBe("Draft");
    expect(created.createdAt).toBeDefined();
    expect(created.updatedAt).toBe(created.createdAt);

    // Verify stored
    const list = await researchService.getAllProjects();
    expect(list.length).toBe(1);
    expect(list[0].id).toBe(created.id);
  });

  it("retrieves a project by ID", async () => {
    const created = await researchService.createProject(validData);
    const fetched = await researchService.getProjectById(created.id);

    expect(fetched).not.toBeNull();
    expect(fetched.id).toBe(created.id);
    expect(fetched.title).toBe(created.title);
  });

  it("returns null for non-existent ID", async () => {
    const fetched = await researchService.getProjectById("non-existent-id");
    expect(fetched).toBeNull();
  });

  it("updates an existing project, updates updatedAt, and preserves createdAt", async () => {
    const created = await researchService.createProject(validData);
    const originalCreatedAt = created.createdAt;

    // Small delay to ensure timestamp difference
    await new Promise((r) => setTimeout(r, 10));

    const updated = await researchService.updateProject(created.id, {
      title: "Updated Quantum Error Mitigation Title",
      status: "In Progress",
    });

    expect(updated.title).toBe("Updated Quantum Error Mitigation Title");
    expect(updated.status).toBe("In Progress");
    expect(updated.createdAt).toBe(originalCreatedAt);
    expect(new Date(updated.updatedAt).getTime()).toBeGreaterThanOrEqual(
      new Date(originalCreatedAt).getTime()
    );

    const reFetched = await researchService.getProjectById(created.id);
    expect(reFetched.title).toBe("Updated Quantum Error Mitigation Title");
    expect(reFetched.status).toBe("In Progress");
  });

  it("deletes a project by ID", async () => {
    const created = await researchService.createProject(validData);
    expect((await researchService.getAllProjects()).length).toBe(1);

    const result = await researchService.deleteProject(created.id);
    expect(result).toBe(true);

    const list = await researchService.getAllProjects();
    expect(list.length).toBe(0);

    const fetched = await researchService.getProjectById(created.id);
    expect(fetched).toBeNull();
  });

  it("throws an error when updating or deleting a non-existent ID", async () => {
    await expect(
      researchService.updateProject("missing-id", { title: "Valid Title" })
    ).rejects.toThrow(/not found/i);

    await expect(researchService.deleteProject("missing-id")).rejects.toThrow(
      /not found/i
    );
  });

  it("rejects invalid data when creating", async () => {
    await expect(
      researchService.createProject({ title: "No" })
    ).rejects.toThrow(/at least 3 characters/i);
  });

  it("gracefully recovers from corrupted JSON in localStorage", async () => {
    localStorage.setItem(researchService.STORAGE_KEY, "{ corrupted JSON text [[");
    const list = await researchService.getAllProjects();
    expect(list).toEqual([]);
  });

  it("correctly calculates project statistics", async () => {
    await researchService.createProject({
      title: "Project 1",
      researchQuestion: "Question for project one?",
      category: "Education",
      status: "Draft",
    });
    await researchService.createProject({
      title: "Project 2",
      researchQuestion: "Question for project two?",
      category: "Education",
      status: "In Progress",
    });
    await researchService.createProject({
      title: "Project 3",
      researchQuestion: "Question for project three?",
      category: "Technology",
      status: "Completed",
    });

    const stats = await researchService.getProjectStats();
    expect(stats.total).toBe(3);
    expect(stats.draft).toBe(1);
    expect(stats.inProgress).toBe(1);
    expect(stats.completed).toBe(1);
    expect(stats.archived).toBe(0);
    expect(stats.byCategory["Education"]).toBe(2);
    expect(stats.byCategory["Technology"]).toBe(1);
  });

  describe("Storage Reliability & Hardening Tests", () => {
    it("reports an honest error and does not silently swallow storage quota exceptions", async () => {
      // Mock setItem to throw QuotaExceededError
      const originalSetItem = Storage.prototype.setItem;
      Storage.prototype.setItem = () => {
        const quotaError = new Error("Quota exceeded");
        quotaError.name = "QuotaExceededError";
        throw quotaError;
      };

      try {
        await expect(
          researchService.createProject(validData)
        ).rejects.toThrow(/storage quota exceeded/i);
      } finally {
        Storage.prototype.setItem = originalSetItem;
      }
    });

    it("enforces strict data isolation preventing external state mutation", async () => {
      const created = await researchService.createProject(validData);

      // Attempt to mutate the returned object
      created.title = "Directly Mutated Title";

      // Verify that the record in storage remains untouched
      const fromDb = await researchService.getProjectById(created.id);
      expect(fromDb.title).toBe(validData.title);
    });

    it("sanitizes malformed records, recovers valid fields and drops invalid entries", async () => {
      const malformedData = [
        null,
        { id: "1" }, // missing title
        { id: "valid-1", title: "Project One", researchQuestion: "Valid Question Here?", category: "NonExistentCat", status: "InvalidStat", createdAt: "invalid-date" },
        { id: "valid-1", title: "Duplicate ID Entry", researchQuestion: "Duplicate Question?" }, // duplicate id
        { id: "valid-2", title: "Project Two", researchQuestion: "Second Question?" }
      ];

      localStorage.setItem(researchService.STORAGE_KEY, JSON.stringify(malformedData));

      const list = await researchService.getAllProjects();
      expect(list.length).toBe(2);
      expect(list[0].id).toBe("valid-1");
      expect(list[0].category).toBe("General Research"); // fallback
      expect(list[0].status).toBe("Draft"); // fallback
      expect(new Date(list[0].createdAt).getTime()).not.toBeNaN(); // valid normalized ISO
      expect(list[1].id).toBe("valid-2");
    });

    it("backs up corrupted raw JSON to a recovery key instead of silent destruction", async () => {
      const corruptedString = "corrupted-json-payload-###";
      localStorage.setItem(researchService.STORAGE_KEY, corruptedString);

      const list = await researchService.getAllProjects();
      expect(list).toEqual([]);

      // Verify backup key was created
      const allKeys = Object.keys(localStorage);
      const backupFound = allKeys.some((k) => k.startsWith(researchService.CORRUPTED_BACKUP_KEY));
      expect(backupFound).toBe(true);
    });
  });
});
