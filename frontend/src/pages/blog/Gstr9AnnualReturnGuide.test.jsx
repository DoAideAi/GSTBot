import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import Gstr9AnnualReturnGuide from "./Gstr9AnnualReturnGuide";

vi.mock("../../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));

function renderArticle() {
  return render(
    <MemoryRouter>
      <Gstr9AnnualReturnGuide />
    </MemoryRouter>,
  );
}

describe("Gstr9AnnualReturnGuide", () => {
  it("renders the article title", () => {
    renderArticle();
    expect(
      screen.getByText("GSTR-9 Annual Return FY 2025-26: Due Date, Applicability, Late Fees"),
    ).toBeInTheDocument();
  });

  it("renders key sections", () => {
    renderArticle();
    expect(screen.getByText("Who Must File GSTR-9 for FY 2025-26")).toBeInTheDocument();
    expect(screen.getByText("GSTR-9C: The Reconciliation Statement")).toBeInTheDocument();
    expect(screen.getByText("Due Date and Late Fees")).toBeInTheDocument();
    expect(screen.getByText("Reconciliations to Finish Before Filing")).toBeInTheDocument();
  });

  it("states the 31 December 2026 due date", () => {
    renderArticle();
    expect(screen.getAllByText(/31 December 2026/).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the late fee table", () => {
    renderArticle();
    expect(screen.getByText("₹50 (₹25 CGST + ₹25 SGST)")).toBeInTheDocument();
    expect(screen.getByText("0.5% of turnover in the state/UT")).toBeInTheDocument();
  });

  it("has internal links to GST tools", () => {
    renderArticle();
    const hrefs = screen.getAllByRole("link").map((l) => l.getAttribute("href"));
    expect(hrefs).toContain("/gstr9-checklist");
    expect(hrefs).toContain("/late-fee-calculator");
    expect(hrefs).toContain("/gstr2b-reconciliation");
  });

  it("renders FAQs", () => {
    renderArticle();
    expect(screen.getByText("Can GSTR-9 be revised?")).toBeInTheDocument();
  });
});
