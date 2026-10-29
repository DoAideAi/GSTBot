import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import LandingPage from "./LandingPage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));
vi.mock("../lib/track", () => ({ track: vi.fn() }));
vi.mock("../lib/usageStats", async () => {
  const actual = await vi.importActual("../lib/usageStats");
  return { ...actual, getUsageStats: vi.fn().mockResolvedValue(null) };
});

const { getUsageStats } = await import("../lib/usageStats");

function renderLanding() {
  return render(
    <MemoryRouter>
      <LandingPage />
    </MemoryRouter>,
  );
}

describe("LandingPage", () => {
  it("shows the hero headline", () => {
    renderLanding();

    expect(screen.getByText("Free GST Tools for Indian Businesses")).toBeInTheDocument();
  });

  it("shows the hero subtitle", () => {
    renderLanding();

    expect(
      screen.getByText(/25\+ free tools/),
    ).toBeInTheDocument();
  });

  it("renders the header brand linking to doaide.com", () => {
    renderLanding();

    const brand = screen.getByText("doaide.com").closest("a");
    expect(brand).toHaveAttribute("href", "https://doaide.com");
  });

  it("renders the footer with DoAide product links", () => {
    renderLanding();

    expect(screen.getByText("Desk")).toBeInTheDocument();
    expect(screen.getByText("Jobs")).toBeInTheDocument();
    expect(screen.getByText("Pulse")).toBeInTheDocument();
    expect(screen.getByText("409A")).toBeInTheDocument();
    expect(screen.getByText("Resume")).toBeInTheDocument();
    expect(screen.getByText("Contracts")).toBeInTheDocument();
    expect(screen.getByText("Invoicer")).toBeInTheDocument();
    expect(screen.getByText("doaide.com")).toBeInTheDocument();
  });

  describe("feature highlights section", () => {
    it("renders all six feature cards", () => {
      renderLanding();

      expect(screen.getByText("GSTR-2B Reconciliation")).toBeInTheDocument();
      // "ITC Calculator" also appears in the tool categories grid — check that at least one exists
      expect(screen.getAllByText("ITC Calculator").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("GST Return Filing")).toBeInTheDocument();
      expect(screen.getByText("Deadline Alerts")).toBeInTheDocument();
      expect(screen.getByText("Supplier Tracking")).toBeInTheDocument();
      expect(screen.getByText("AI Invoice Parsing")).toBeInTheDocument();
    });

    it("has a section heading", () => {
      renderLanding();

      expect(screen.getByText("Everything You Need for GST Compliance")).toBeInTheDocument();
    });
  });

  describe("how it works section", () => {
    it("renders three steps", () => {
      renderLanding();

      expect(screen.getByText("Upload invoices")).toBeInTheDocument();
      expect(screen.getByText("Auto-reconcile")).toBeInTheDocument();
      expect(screen.getByText("File returns")).toBeInTheDocument();
    });

    it("shows step numbers", () => {
      renderLanding();

      expect(screen.getAllByText("1").length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText("2").length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText("3").length).toBeGreaterThanOrEqual(1);
    });

    it("shows the subtitle", () => {
      renderLanding();

      expect(screen.getByText(/Get started in under 2 minutes/)).toBeInTheDocument();
    });
  });

  describe("demo video section", () => {
    it("renders the demo heading", () => {
      renderLanding();

      expect(screen.getByText("See DoAide GST in Action")).toBeInTheDocument();
    });

    it("shows the demo caption", () => {
      renderLanding();

      expect(screen.getByText(/try it free/)).toBeInTheDocument();
    });

    it("links to signup", () => {
      renderLanding();

      const link = screen.getByText(/try it free/).closest("a");
      expect(link).toHaveAttribute("href", "/login");
    });
  });

  describe("testimonials section", () => {
    it("renders testimonial quotes", () => {
      renderLanding();

      expect(screen.getByText(/cut our reconciliation time/)).toBeInTheDocument();
      expect(screen.getByText(/missing ITC on mismatched invoices/)).toBeInTheDocument();
      expect(screen.getByText(/free plan handles our monthly volume/)).toBeInTheDocument();
    });

    it("shows reviewer names and roles", () => {
      renderLanding();

      expect(screen.getByText("Priya S.")).toBeInTheDocument();
      expect(screen.getByText("CA, Mumbai")).toBeInTheDocument();
    });
  });

  describe("FAQ section", () => {
    it("renders all FAQ questions", () => {
      renderLanding();

      expect(screen.getByText("What is GST and who needs to file GST returns?")).toBeInTheDocument();
      expect(screen.getByText("How does GSTR-2B reconciliation work?")).toBeInTheDocument();
      expect(screen.getByText("What is Input Tax Credit (ITC) and how is it calculated?")).toBeInTheDocument();
      expect(screen.getByText("Is DoAide GST really free?")).toBeInTheDocument();
      expect(screen.getByText("What are HSN codes and why do they matter for GST?")).toBeInTheDocument();
      expect(screen.getByText("What happens if I miss a GST filing deadline?")).toBeInTheDocument();
      expect(screen.getByText("Can DoAide GST help with GST compliance for small businesses?")).toBeInTheDocument();
    });

    it("answers are hidden by default", () => {
      renderLanding();

      expect(screen.queryByText(/indirect tax on goods and services/)).not.toBeInTheDocument();
    });

    it("expands an answer when the question is clicked", async () => {
      renderLanding();

      await userEvent.click(screen.getByText("Is DoAide GST really free?"));

      expect(screen.getByText(/All features are included free/)).toBeInTheDocument();
    });

    it("collapses an open answer when clicked again", async () => {
      renderLanding();

      const question = screen.getByText("Is DoAide GST really free?");
      await userEvent.click(question);
      expect(screen.getByText(/All features are included free/)).toBeInTheDocument();

      await userEvent.click(question);
      expect(screen.queryByText(/All features are included free/)).not.toBeInTheDocument();
    });

    it("closes the previous answer when opening a new one", async () => {
      renderLanding();

      await userEvent.click(screen.getByText("Is DoAide GST really free?"));
      expect(screen.getByText(/All features are included free/)).toBeInTheDocument();

      await userEvent.click(screen.getByText("How does GSTR-2B reconciliation work?"));
      expect(screen.queryByText(/All features are included free/)).not.toBeInTheDocument();
      expect(screen.getByText(/eligible ITC based on suppliers/)).toBeInTheDocument();
    });
  });

  describe("CTA section", () => {
    it("renders the call to action", () => {
      renderLanding();

      expect(screen.getByText("Need Automated GST Filing?")).toBeInTheDocument();
      expect(screen.getByText("Create Free Account")).toBeInTheDocument();
      expect(screen.getByText(/View Plans/)).toBeInTheDocument();
    });
  });

  describe("InstantLookup section", () => {
    it("shows the GSTIN verification search box", () => {
      renderLanding();

      expect(
        screen.getByLabelText("GSTIN or search term"),
      ).toBeInTheDocument();
    });

    it("shows only the always-true trust claims while stats are unavailable", () => {
      renderLanding();

      expect(screen.getByText("25+")).toBeInTheDocument();
      expect(screen.getByText("Free GST tools")).toBeInTheDocument();
      expect(screen.getByText("100%")).toBeInTheDocument();
      expect(screen.getByText("Free to start")).toBeInTheDocument();
      expect(screen.queryByText("Invoices processed")).not.toBeInTheDocument();
    });

    it("shows the real counters once the stats clear the floor", async () => {
      getUsageStats.mockResolvedValueOnce({
        businesses: 450,
        invoices: 9800,
        gstin_lookups: 0,
      });
      renderLanding();

      expect(await screen.findByText("Businesses on DoAide GST")).toBeInTheDocument();
      expect(screen.getByText("Invoices processed")).toBeInTheDocument();
    });

    it("keeps a below-floor figure off the trust bar", async () => {
      getUsageStats.mockResolvedValueOnce({
        businesses: 450,
        invoices: 7,
        gstin_lookups: 0,
      });
      renderLanding();

      expect(await screen.findByText("Businesses on DoAide GST")).toBeInTheDocument();
      expect(screen.queryByText("Invoices processed")).not.toBeInTheDocument();
    });

    it("shows compliance trust badges", () => {
      renderLanding();

      expect(screen.getAllByText("GST-compliant calculations").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("Updated for FY 2026-27")).toBeInTheDocument();
      expect(screen.getByText("No login required")).toBeInTheDocument();
      expect(screen.getByText("Results in seconds")).toBeInTheDocument();
    });

    it("renders tool category sections", () => {
      renderLanding();

      expect(screen.getByText("Calculators")).toBeInTheDocument();
      expect(screen.getByText("Lookup & Verification")).toBeInTheDocument();
      expect(screen.getByText("Compliance & Filing")).toBeInTheDocument();
      expect(screen.getByText("Planning & Reference")).toBeInTheDocument();
    });

    it("renders tool cards within categories", () => {
      renderLanding();

      const section = document.querySelector(".landing-tool-cards");
      expect(section).not.toBeNull();
      expect(section.textContent).toContain("GST Calculator");
    });

    it("submits a GSTIN-shaped query to the lookup route", async () => {
      renderLanding();

      const input = screen.getByLabelText("GSTIN or search term");
      await userEvent.type(input, "27AAPFU0939F1ZV");
      await userEvent.click(screen.getByText("Verify"));
    });

    it("submits a non-GSTIN query to the lookup route with q param", async () => {
      renderLanding();

      const input = screen.getByLabelText("GSTIN or search term");
      await userEvent.type(input, "test query");
      await userEvent.click(screen.getByText("Verify"));
    });

    it("does nothing on empty submit", async () => {
      renderLanding();

      await userEvent.click(screen.getByText("Verify"));
    });
  });

  describe("Popular Searches section", () => {
    it("renders the section heading", () => {
      renderLanding();

      expect(screen.getByText("Popular GST Lookups")).toBeInTheDocument();
    });

    it("shows sample GSTIN and HSN codes as links", () => {
      renderLanding();

      expect(screen.getByText("27AAPFU0939F1ZV")).toBeInTheDocument();
      expect(screen.getByText("HSN 8471")).toBeInTheDocument();
      expect(screen.getByText("SAC 9983")).toBeInTheDocument();
    });

    it("links popular searches to the right pages", () => {
      renderLanding();

      const gstinLink = screen.getByText("27AAPFU0939F1ZV").closest("a");
      expect(gstinLink).toHaveAttribute("href", "/gstin/27AAPFU0939F1ZV");
    });
  });

  describe("footer navigation", () => {
    it("has links to blog, pricing, and resources", () => {
      renderLanding();

      const pricingLinks = screen.getAllByText("Pricing");
      expect(pricingLinks.length).toBeGreaterThan(0);
      expect(screen.getByText("Blog")).toBeInTheDocument();
      expect(screen.getByText("GST Filing Guide")).toBeInTheDocument();
      expect(screen.getAllByText("HSN Code Finder").length).toBeGreaterThan(0);
      expect(screen.getByText("All GST Tools & Guides")).toBeInTheDocument();
      expect(screen.getAllByText("Due Dates Calendar").length).toBeGreaterThan(0);
    });

    it("has links to guides and comparison pages", () => {
      renderLanding();

      expect(screen.getByText("GST Guides")).toBeInTheDocument();
      expect(screen.getByText("Best GST Software")).toBeInTheDocument();
      expect(screen.getByText("GST Filing Guide")).toBeInTheDocument();
    });

    it("shows trust signals", () => {
      renderLanding();

      expect(screen.getByText("256-bit SSL encrypted")).toBeInTheDocument();
      expect(screen.getAllByText("GST-compliant calculations").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("Your data stays private")).toBeInTheDocument();
    });

    it("has comparison page links", () => {
      renderLanding();

      expect(screen.getByText("DoAide vs ClearTax")).toBeInTheDocument();
      expect(screen.getByText("DoAide vs Zoho GST")).toBeInTheDocument();
      expect(screen.getByText("DoAide vs Tally Prime")).toBeInTheDocument();
      expect(screen.getByText("DoAide vs Busy")).toBeInTheDocument();
    });
  });

  describe("Deadline Countdown section", () => {
    it("renders the deadline countdown heading", () => {
      renderLanding();
      expect(screen.getByText("GST Filing Deadline Countdown")).toBeInTheDocument();
    });

    it("shows GSTR-1 and GSTR-3B deadlines", () => {
      renderLanding();
      expect(screen.getByText("GSTR-1")).toBeInTheDocument();
      expect(screen.getByText("GSTR-3B")).toBeInTheDocument();
    });
  });

  describe("Business Counter section", () => {
    it("renders the business counter", () => {
      renderLanding();
      expect(screen.getByRole("status", { name: "Business usage count" })).toBeInTheDocument();
      expect(screen.getByText("Built for Indian businesses")).toBeInTheDocument();
    });
  });

  describe("GST News section", () => {
    it("renders the news heading", () => {
      renderLanding();
      expect(screen.getByText(/GST News/)).toBeInTheDocument();
    });

    it("shows news items with tags", () => {
      renderLanding();
      expect(screen.getByText("Rate Change")).toBeInTheDocument();
      expect(screen.getByText("Compliance")).toBeInTheDocument();
    });
  });
});
