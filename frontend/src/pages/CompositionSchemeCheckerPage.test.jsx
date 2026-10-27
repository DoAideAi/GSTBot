import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import CompositionSchemeCheckerPage, { checkEligibility } from "./CompositionSchemeCheckerPage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("../lib/share", () => ({
  fullUrl: (p) => `http://localhost${p}`,
  whatsappUrl: (text, url) => `https://wa.me/?text=${encodeURIComponent(`${text} ${url}`)}`,
  twitterUrl: (text, url) => `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`,
  copyToClipboard: vi.fn().mockResolvedValue(true),
}));
vi.mock("../lib/api", () => ({
  api: { subscribe: vi.fn().mockResolvedValue({ subscribed: true, new: true, message: "Done" }) },
}));
vi.mock("../lib/track", () => ({ track: vi.fn() }));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/tools/composition-scheme-checker"]}>
      <CompositionSchemeCheckerPage />
    </MemoryRouter>,
  );
}

describe("CompositionSchemeCheckerPage", () => {
  it("renders the title and subtitle", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: /Composition Scheme Eligibility Checker/i })).toBeInTheDocument();
    expect(screen.getByText(/check if your business qualifies/i)).toBeInTheDocument();
  });

  it("shows business type, state, and turnover fields", () => {
    renderPage();
    expect(screen.getByLabelText(/Business Type/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/State/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Annual Aggregate Turnover/i)).toBeInTheDocument();
  });

  it("shows no result before state and turnover are provided", () => {
    renderPage();
    expect(screen.queryByText("Eligible ✓")).not.toBeInTheDocument();
    expect(screen.queryByText("Not Eligible ✗")).not.toBeInTheDocument();
  });

  it("shows eligible result for manufacturer below limit", async () => {
    renderPage();
    await userEvent.selectOptions(screen.getByLabelText(/State/i), "Maharashtra");
    await userEvent.type(screen.getByLabelText(/Annual Aggregate Turnover/i), "5000000");

    expect(screen.getByText("Eligible ✓")).toBeInTheDocument();
    const resultArea = screen.getByText("Eligible ✓").closest("[aria-live]");
    expect(within(resultArea).getByText(/1% \(0\.5% CGST \+ 0\.5% SGST\)/)).toBeInTheDocument();
  });

  it("shows not eligible when turnover exceeds limit", async () => {
    renderPage();
    await userEvent.selectOptions(screen.getByLabelText(/State/i), "Maharashtra");
    await userEvent.type(screen.getByLabelText(/Annual Aggregate Turnover/i), "20000000");

    expect(screen.getByText("Not Eligible ✗")).toBeInTheDocument();
    expect(screen.getByText(/exceeds the/)).toBeInTheDocument();
  });

  it("applies special category state limit for goods suppliers", async () => {
    renderPage();
    await userEvent.selectOptions(screen.getByLabelText(/State/i), "Sikkim");
    await userEvent.type(screen.getByLabelText(/Annual Aggregate Turnover/i), "8000000");

    expect(screen.getByText("Not Eligible ✗")).toBeInTheDocument();
    const resultArea = screen.getByText("Not Eligible ✗").closest("[aria-live]");
    expect(within(resultArea).getByText(/special category state/)).toBeInTheDocument();
  });

  it("shows special state notice for NE states", async () => {
    renderPage();
    await userEvent.selectOptions(screen.getByLabelText(/State/i), "Mizoram");
    expect(screen.getByText(/is a special category state/)).toBeInTheDocument();
    expect(screen.getByText(/₹75 lakh instead of ₹1\.5 crore/)).toBeInTheDocument();
  });

  it("applies ₹50L limit for service providers regardless of state", async () => {
    renderPage();
    await userEvent.selectOptions(screen.getByLabelText(/Business Type/i), "Service Provider");
    await userEvent.selectOptions(screen.getByLabelText(/State/i), "Delhi");
    await userEvent.type(screen.getByLabelText(/Annual Aggregate Turnover/i), "6000000");

    expect(screen.getByText("Not Eligible ✗")).toBeInTheDocument();
  });

  it("shows 6% rate for eligible service providers", async () => {
    renderPage();
    await userEvent.selectOptions(screen.getByLabelText(/Business Type/i), "Service Provider");
    await userEvent.selectOptions(screen.getByLabelText(/State/i), "Karnataka");
    await userEvent.type(screen.getByLabelText(/Annual Aggregate Turnover/i), "4000000");

    expect(screen.getByText("Eligible ✓")).toBeInTheDocument();
    const resultArea = screen.getByText("Eligible ✓").closest("[aria-live]");
    expect(within(resultArea).getByText(/6% \(3% CGST \+ 3% SGST\)/)).toBeInTheDocument();
  });

  it("shows 5% rate for eligible restaurants", async () => {
    renderPage();
    await userEvent.selectOptions(screen.getByLabelText(/Business Type/i), "Restaurant (not serving alcohol)");
    await userEvent.selectOptions(screen.getByLabelText(/State/i), "Gujarat");
    await userEvent.type(screen.getByLabelText(/Annual Aggregate Turnover/i), "10000000");

    expect(screen.getByText("Eligible ✓")).toBeInTheDocument();
    const resultArea = screen.getByText("Eligible ✓").closest("[aria-live]");
    expect(within(resultArea).getByText(/5% \(2\.5% CGST \+ 2\.5% SGST\)/)).toBeInTheDocument();
  });

  it("displays quarterly tax estimate", async () => {
    renderPage();
    await userEvent.selectOptions(screen.getByLabelText(/State/i), "Tamil Nadu");
    await userEvent.type(screen.getByLabelText(/Annual Aggregate Turnover/i), "10000000");

    expect(screen.getByText(/Estimated Quarterly Tax/)).toBeInTheDocument();
  });

  it("renders composition vs regular comparison table", async () => {
    renderPage();
    await userEvent.selectOptions(screen.getByLabelText(/State/i), "Rajasthan");
    await userEvent.type(screen.getByLabelText(/Annual Aggregate Turnover/i), "8000000");

    expect(screen.getByText("Composition vs Regular Scheme")).toBeInTheDocument();
    expect(screen.getByText("Net Tax Outgo")).toBeInTheDocument();
    expect(screen.getByText("Not Available")).toBeInTheDocument();
  });

  it("renders FAQ section", () => {
    renderPage();
    expect(screen.getByText("Frequently Asked Questions")).toBeInTheDocument();
    expect(screen.getByText(/What is the GST Composition Scheme\?/)).toBeInTheDocument();
    expect(screen.getByText(/What are the tax rates under the Composition Scheme\?/)).toBeInTheDocument();
  });

  it("renders WhatsApp share button in results", async () => {
    renderPage();
    await userEvent.selectOptions(screen.getByLabelText(/State/i), "Kerala");
    await userEvent.type(screen.getByLabelText(/Annual Aggregate Turnover/i), "5000000");

    const whatsappLinks = screen.getAllByLabelText("Share on WhatsApp");
    expect(whatsappLinks.length).toBeGreaterThanOrEqual(1);
  });

  it("lists ineligible business categories", () => {
    renderPage();
    expect(screen.getByText(/Inter-state suppliers of goods/)).toBeInTheDocument();
    expect(screen.getByText(/Manufacturers of ice cream, pan masala, or tobacco/)).toBeInTheDocument();
  });
});

describe("checkEligibility", () => {
  it("returns null for invalid turnover", () => {
    expect(checkEligibility({ turnover: "", businessType: "trader", state: "Delhi" })).toBeNull();
    expect(checkEligibility({ turnover: "abc", businessType: "trader", state: "Delhi" })).toBeNull();
    expect(checkEligibility({ turnover: "-100", businessType: "trader", state: "Delhi" })).toBeNull();
  });

  it("returns null for unknown business type", () => {
    expect(checkEligibility({ turnover: "1000000", businessType: "unknown", state: "Delhi" })).toBeNull();
  });

  it("calculates correct quarterly tax for manufacturer", () => {
    const r = checkEligibility({ turnover: "10000000", businessType: "manufacturer", state: "Maharashtra" });
    expect(r.eligible).toBe(true);
    expect(r.estimatedAnnualTax).toBe(100000);
    expect(r.estimatedQuarterlyTax).toBe(25000);
  });

  it("uses 75L limit for special category state goods supplier", () => {
    const eligible = checkEligibility({ turnover: "7000000", businessType: "trader", state: "Sikkim" });
    expect(eligible.eligible).toBe(true);
    const ineligible = checkEligibility({ turnover: "8000000", businessType: "trader", state: "Sikkim" });
    expect(ineligible.eligible).toBe(false);
  });

  it("a Himachal Pradesh trader uses the ₹1.5 crore limit, not ₹75 lakh", () => {
    const below = checkEligibility({ turnover: "14000000", businessType: "trader", state: "Himachal Pradesh" });
    expect(below.eligible).toBe(true);
    expect(below.turnoverLimit).toBe(15000000);
    const above = checkEligibility({ turnover: "16000000", businessType: "trader", state: "Himachal Pradesh" });
    expect(above.eligible).toBe(false);
  });

  it("an Uttarakhand trader uses the ₹75 lakh limit", () => {
    const r = checkEligibility({ turnover: "8000000", businessType: "trader", state: "Uttarakhand" });
    expect(r.eligible).toBe(false);
  });

  it("uses 50L limit for service provider even in special state", () => {
    const r = checkEligibility({ turnover: "6000000", businessType: "service_provider", state: "Manipur" });
    expect(r.eligible).toBe(false);
  });

  it("includes regular comparison data when eligible", () => {
    const r = checkEligibility({ turnover: "10000000", businessType: "manufacturer", state: "Gujarat" });
    expect(r.regularComparison).not.toBeNull();
    expect(r.regularComparison.regularRate).toBe(18);
    expect(r.regularComparison.regularAnnualTax).toBe(1800000);
    expect(r.regularComparison.estimatedItc).toBe(1080000);
    expect(r.regularComparison.compositionBetter).toBe(true);
  });
});
