import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import App from "../App";
import DashboardPage from "../features/dashboard/DashboardPage";
import Topbar from "../components/layout/Topbar";
import Sidebar from "../components/layout/Sidebar";

describe("Phase 1 Regression Test Suite", () => {
  describe("DashboardPage Component", () => {
    it("renders the dashboard headings and introductory copy", () => {
      render(<DashboardPage onNavigate={() => {}} />);

      expect(screen.getByText(/workspace overview/i)).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { level: 1, name: /welcome to bharmafills/i })
      ).toBeInTheDocument();
      expect(
        screen.getByText(/discover missing information, conflicting claims/i)
      ).toBeInTheDocument();
    });

    it("renders all 4 statistics cards with expected metrics", () => {
      render(<DashboardPage onNavigate={() => {}} />);

      expect(screen.getByText("Research Projects")).toBeInTheDocument();
      expect(screen.getByText("Sources Collected")).toBeInTheDocument();
      expect(screen.getByText("Information Gaps")).toBeInTheDocument();
      expect(screen.getByText("Pending Checks")).toBeInTheDocument();

      const zeroes = screen.getAllByText("0");
      expect(zeroes.length).toBe(4);
    });

    it("renders Recent Research and How it Works sections", () => {
      render(<DashboardPage onNavigate={() => {}} />);

      expect(
        screen.getByRole("heading", { level: 2, name: /recent research/i })
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { level: 2, name: /how it works/i })
      ).toBeInTheDocument();
      expect(screen.getByText(/no research projects yet/i)).toBeInTheDocument();
    });

    it("calls onNavigate with 'Research' when 'New Research' button is clicked", () => {
      let navigatedTo = "";
      render(<DashboardPage onNavigate={(page) => { navigatedTo = page; }} />);

      const newResearchBtn = screen.getByRole("button", { name: /new research/i });
      fireEvent.click(newResearchBtn);

      expect(navigatedTo).toBe("Research");
    });

    it("calls onNavigate with 'Research' when 'Create your first project' is clicked", () => {
      let navigatedTo = "";
      render(<DashboardPage onNavigate={(page) => { navigatedTo = page; }} />);

      const createFirstBtn = screen.getByRole("button", {
        name: /create your first project/i,
      });
      fireEvent.click(createFirstBtn);

      expect(navigatedTo).toBe("Research");
    });
  });

  describe("Topbar Component", () => {
    it("renders current active page title and auxiliary actions", () => {
      render(<Topbar activePage="Overview" onToggleSidebar={() => {}} />);

      expect(
        screen.getByRole("heading", { level: 2, name: "Overview" })
      ).toBeInTheDocument();
      expect(
        screen.getByLabelText(/search workspaces/i)
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /notifications/i })
      ).toBeInTheDocument();
      expect(screen.getByText("D")).toBeInTheDocument();
    });
  });

  describe("Sidebar Component", () => {
    it("renders brand, navigation links, and highlights the active item", () => {
      render(<Sidebar activePage="Overview" onNavigate={() => {}} />);

      expect(screen.getByText("BHARMAFILLS")).toBeInTheDocument();

      const overviewBtn = screen.getByRole("button", { name: /overview/i });
      expect(overviewBtn).toHaveAttribute("aria-current", "page");

      const researchBtn = screen.getByRole("button", { name: /research/i });
      expect(researchBtn).not.toHaveAttribute("aria-current");
    });
  });

  describe("End-to-End Application Integration (App)", () => {
    it("renders initial Overview dashboard page", () => {
      render(<App />);

      expect(
        screen.getByRole("heading", { level: 1, name: /welcome to bharmafills/i })
      ).toBeInTheDocument();
      expect(screen.getAllByText("Overview").length).toBeGreaterThanOrEqual(1);
    });

    it("navigates via Sidebar to Research, Sources, and Analysis pages", () => {
      render(<App />);

      // Navigate to Research (implemented in Phase 2)
      const researchNavBtns = screen.getAllByRole("button", { name: /research/i });
      fireEvent.click(researchNavBtns[0]);
      expect(
        screen.getByRole("heading", { level: 1, name: /research projects/i })
      ).toBeInTheDocument();

      // Navigate to Sources (placeholder)
      const sourcesNavBtns = screen.getAllByRole("button", { name: /sources/i });
      fireEvent.click(sourcesNavBtns[0]);
      expect(
        screen.getByText(/this module will be implemented and tested separately/i)
      ).toBeInTheDocument();
      expect(screen.getAllByText("Sources").length).toBeGreaterThanOrEqual(1);

      // Navigate to Analysis (placeholder)
      const analysisNavBtns = screen.getAllByRole("button", { name: /analysis/i });
      fireEvent.click(analysisNavBtns[0]);
      expect(
        screen.getByText(/this module will be implemented and tested separately/i)
      ).toBeInTheDocument();
      expect(screen.getAllByText("Analysis").length).toBeGreaterThanOrEqual(1);

      // Navigate back to Overview
      const overviewNavBtns = screen.getAllByRole("button", { name: /overview/i });
      fireEvent.click(overviewNavBtns[0]);
      expect(
        screen.getByRole("heading", { level: 1, name: /welcome to bharmafills/i })
      ).toBeInTheDocument();
    });

    it("navigates to Research when 'New Research' button is clicked from Dashboard", () => {
      render(<App />);

      const newResearchBtn = screen.getByRole("button", { name: /new research/i });
      fireEvent.click(newResearchBtn);

      expect(
        screen.getByRole("heading", { level: 1, name: /research projects/i })
      ).toBeInTheDocument();
    });
  });
});
