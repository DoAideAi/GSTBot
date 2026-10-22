import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import GstImsGuide from "./GstImsGuide";

vi.mock("../../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));

function renderArticle() {
  return render(
    <MemoryRouter>
      <GstImsGuide />
    </MemoryRouter>,
  );
}

describe("GstImsGuide", () => {
  it("renders the article title", () => {
    renderArticle();
    expect(
      screen.getByText("GST Invoice Management System (IMS) Explained: Accept, Reject, Pending"),
    ).toBeInTheDocument();
  });

  it("renders key sections", () => {
    renderArticle();
    expect(screen.getByText("What IMS Is and Where It Sits")).toBeInTheDocument();
    expect(screen.getByText("How Each Action Affects Your ITC")).toBeInTheDocument();
    expect(screen.getByText("Credit Notes Are Special")).toBeInTheDocument();
    expect(screen.getByText("A Practical Month-End IMS Workflow")).toBeInTheDocument();
  });

  it("renders the IMS action table", () => {
    renderArticle();
    expect(screen.getByText("Accept / no action")).toBeInTheDocument();
    expect(screen.getByText("ITC auto-populates GSTR-3B Table 4")).toBeInTheDocument();
  });

  it("has internal links to GST tools", () => {
    renderArticle();
    const hrefs = screen.getAllByRole("link").map((l) => l.getAttribute("href"));
    expect(hrefs).toContain("/gstr2b-reconciliation");
    expect(hrefs).toContain("/itc-calculator");
    expect(hrefs).toContain("/input-tax-credit");
  });

  it("renders FAQs", () => {
    renderArticle();
    expect(screen.getByText("Is IMS mandatory for every taxpayer?")).toBeInTheDocument();
    expect(screen.getByText("Does IMS replace GSTR-2B reconciliation?")).toBeInTheDocument();
  });
});
