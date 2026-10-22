import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import ToolsNav from "./ToolsNav";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));

function renderNav(route = "/calculator") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <ToolsNav />
    </MemoryRouter>,
  );
}

describe("ToolsNav", () => {
  it("renders all tool links", () => {
    renderNav();

    expect(screen.getByText("GST Calculator")).toBeInTheDocument();
    expect(screen.getByText("GSTIN Lookup")).toBeInTheDocument();
    expect(screen.getByText("HSN Finder")).toBeInTheDocument();
    expect(screen.getByText("Due Dates")).toBeInTheDocument();
    expect(screen.getByText("All Tools")).toBeInTheDocument();
  });

  it("applies active class to the current route", () => {
    renderNav("/calculator");

    const calcLink = screen.getByText("GST Calculator");
    expect(calcLink.className).toContain("active");

    const lookupLink = screen.getByText("GSTIN Lookup");
    expect(lookupLink.className).not.toContain("active");
  });

  it("highlights lookup when on the lookup route", () => {
    renderNav("/lookup");

    const lookupLink = screen.getByText("GSTIN Lookup");
    expect(lookupLink.className).toContain("active");
  });

  it("renders the sign-up CTA pointing to /login", () => {
    renderNav();

    const cta = screen.getByText("Sign up free");
    expect(cta).toHaveAttribute("href", "/login");
  });

  it("renders the brand link pointing to gst.doaide.com", () => {
    renderNav();

    const brand = screen.getByText(/DoAide/).closest("a");
    expect(brand).toHaveAttribute("href", "https://gst.doaide.com");
  });
});
