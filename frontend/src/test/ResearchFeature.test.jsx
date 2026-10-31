import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach } from "vitest";
import App from "../App";
import { ResearchPage } from "../features/research";
import { researchService } from "../features/research/services/researchService";

describe("Phase 2 — Research Project Management Feature Tests", () => {
  beforeEach(async () => {
    localStorage.clear();
    await researchService.clearAll();
  });

  describe("ResearchPage Component - Empty & Form States", () => {
    it("renders empty state illustration and 'Create Research Project' button", async () => {
      render(<ResearchPage />);

      await waitFor(() => {
        expect(screen.getByRole("heading", { level: 3, name: /no research projects yet/i })).toBeInTheDocument();
      });

      expect(screen.getByRole("button", { name: /create research project/i })).toBeInTheDocument();
    });

    it("opens the create modal when 'New Research' button is clicked", async () => {
      render(<ResearchPage />);

      const newResearchBtn = screen.getByRole("button", { name: /new research/i });
      fireEvent.click(newResearchBtn);

      expect(
        screen.getByRole("heading", { level: 2, name: /create new research project/i })
      ).toBeInTheDocument();
      expect(screen.getByLabelText(/research title/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/research question/i)).toBeInTheDocument();
    });

    it("displays inline validation errors when submitting an empty form", async () => {
      render(<ResearchPage />);

      fireEvent.click(screen.getByRole("button", { name: /new research/i }));

      const submitBtn = screen.getByRole("button", { name: /create project/i });
      fireEvent.click(submitBtn);

      expect(await screen.findByText(/research title is required/i)).toBeInTheDocument();
      expect(screen.getByText(/research question is required/i)).toBeInTheDocument();
    });

    it("closes form when 'Cancel' button is clicked without saving", async () => {
      render(<ResearchPage />);

      fireEvent.click(screen.getByRole("button", { name: /new research/i }));
      expect(screen.getByRole("heading", { level: 2, name: /create new research project/i })).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

      await waitFor(() => {
        expect(
          screen.queryByRole("heading", { level: 2, name: /create new research project/i })
        ).not.toBeInTheDocument();
      });
    });
  });

  describe("Complete End-to-End User Flow (Integration)", () => {
    it("creates a project, opens details, edits it, searches/filters, and deletes it", async () => {
      render(<App />);

      // 1. Navigate from Overview to Research page via Sidebar
      const researchNavBtns = screen.getAllByRole("button", { name: /research/i });
      fireEvent.click(researchNavBtns[0]);

      await waitFor(() => {
        expect(
          screen.getByRole("heading", { level: 1, name: /research projects/i })
        ).toBeInTheDocument();
      });

      // 2. Open Create Form & Fill fields
      fireEvent.click(screen.getByRole("button", { name: /new research/i }));

      const titleInput = screen.getByLabelText(/research title/i);
      const questionInput = screen.getByLabelText(/research question/i);
      const descInput = screen.getByLabelText(/description/i);
      const categorySelect = screen.getByLabelText(/category/i);

      fireEvent.change(titleInput, { target: { value: "Quantum Algorithms for Climate Simulation" } });
      fireEvent.change(questionInput, {
        target: {
          value: "How do variational quantum eigensolvers compare against classical DFT in carbon capture modeling?",
        },
      });
      fireEvent.change(descInput, {
        target: { value: "Investigating benchmark accuracy and hardware noise overhead." },
      });
      fireEvent.change(categorySelect, { target: { value: "Technology" } });

      // 3. Submit Project
      const createBtn = screen.getByRole("button", { name: /create project/i });
      fireEvent.click(createBtn);

      // Verify success notification and project appears in list
      expect(
        await screen.findByText(/new research project created successfully/i)
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { level: 3, name: /quantum algorithms for climate simulation/i })
      ).toBeInTheDocument();
      expect(screen.getAllByText("Technology").length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText("Draft").length).toBeGreaterThanOrEqual(1);

      // 4. Open Project Details Workspace
      const openBtn = screen.getByRole("button", { name: /open workspace/i });
      fireEvent.click(openBtn);

      expect(
        await screen.findByRole("heading", {
          level: 1,
          name: /quantum algorithms for climate simulation/i,
        })
      ).toBeInTheDocument();
      expect(
        screen.getByText(/sources workspace/i)
      ).toBeInTheDocument();
      expect(
        screen.getByText(/upcoming in phase 3/i)
      ).toBeInTheDocument();

      // 5. Edit the Project Title & Status
      const editBtn = screen.getByRole("button", { name: /edit project/i });
      fireEvent.click(editBtn);

      expect(
        await screen.findByRole("heading", { level: 2, name: /edit research project/i })
      ).toBeInTheDocument();

      const editTitleInput = screen.getByLabelText(/research title/i);
      const editStatusSelect = screen.getByLabelText(/status/i);

      fireEvent.change(editTitleInput, { target: { value: "Updated Quantum Climate Benchmark" } });
      fireEvent.change(editStatusSelect, { target: { value: "In Progress" } });

      const saveChangesBtn = screen.getByRole("button", { name: /save changes/i });
      fireEvent.click(saveChangesBtn);

      expect(
        await screen.findByText(/research project updated successfully/i)
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { level: 1, name: /updated quantum climate benchmark/i })
      ).toBeInTheDocument();
      expect(screen.getAllByText("In Progress").length).toBeGreaterThanOrEqual(1);

      // 6. Go back to Project List
      const backBtn = screen.getByRole("button", { name: /back to projects/i });
      fireEvent.click(backBtn);

      // 7. Search & Filter Testing
      const searchInput = screen.getByLabelText(/search projects/i);
      fireEvent.change(searchInput, { target: { value: "Updated Quantum" } });

      expect(
        screen.getByRole("heading", { level: 3, name: /updated quantum climate benchmark/i })
      ).toBeInTheDocument();

      // Search for something that doesn't exist
      fireEvent.change(searchInput, { target: { value: "NonExistentKeywordXYZ" } });

      expect(await screen.findByText(/no matching research projects/i)).toBeInTheDocument();

      // Clear search
      fireEvent.change(searchInput, { target: { value: "" } });
      expect(
        await screen.findByRole("heading", { level: 3, name: /updated quantum climate benchmark/i })
      ).toBeInTheDocument();

      // Filter by Status
      const statusFilter = screen.getByLabelText(/filter by status/i);
      fireEvent.change(statusFilter, { target: { value: "Completed" } });
      expect(screen.getByText(/no matching research projects/i)).toBeInTheDocument();

      fireEvent.change(statusFilter, { target: { value: "In Progress" } });
      expect(
        screen.getByRole("heading", { level: 3, name: /updated quantum climate benchmark/i })
      ).toBeInTheDocument();

      // Reset to All
      fireEvent.change(statusFilter, { target: { value: "All" } });

      // 8. Delete the Project with confirmation
      const deleteIconBtn = screen.getByTitle(/delete project/i);
      fireEvent.click(deleteIconBtn);

      expect(
        await screen.findByRole("heading", { level: 3, name: /delete research project\?/i })
      ).toBeInTheDocument();

      // Test Cancel deletion first
      const cancelDeleteBtn = screen.getByRole("button", { name: /cancel/i });
      fireEvent.click(cancelDeleteBtn);

      expect(
        screen.getByRole("heading", { level: 3, name: /updated quantum climate benchmark/i })
      ).toBeInTheDocument();

      // Re-open Delete modal and confirm
      fireEvent.click(screen.getByTitle(/delete project/i));
      const confirmDeleteBtn = screen.getByRole("button", { name: /delete project/i });
      fireEvent.click(confirmDeleteBtn);

      // 9. Verify project no longer exists and empty state returns
      expect(
        await screen.findByText(/research project deleted successfully/i)
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { level: 3, name: /no research projects yet/i })
      ).toBeInTheDocument();
    }, 15000);

    it("persists created projects across reloads and synchronizes with Dashboard metrics", async () => {
      // Create project directly via service to simulate preexisting data
      await researchService.createProject({
        title: "Autonomous Drone Mapping",
        researchQuestion: "Can stereo camera SLAM outperform LiDAR in GPS-denied tunnels?",
        description: "Benchmark testing on PX4 drones.",
        category: "Technology",
        status: "In Progress",
      });

      // Render App on Overview
      render(<App />);

      // Verify dashboard statistics reflect the persisted project
      await waitFor(() => {
        expect(screen.getByText("1 in progress, 0 drafts")).toBeInTheDocument();
      });

      // Navigate to Research and verify the project card is visible
      const researchNavBtns = screen.getAllByRole("button", { name: /research/i });
      fireEvent.click(researchNavBtns[0]);

      expect(
        await screen.findByRole("heading", { level: 3, name: /autonomous drone mapping/i })
      ).toBeInTheDocument();
      expect(screen.getAllByText("In Progress").length).toBeGreaterThanOrEqual(1);
    });
  });
});
