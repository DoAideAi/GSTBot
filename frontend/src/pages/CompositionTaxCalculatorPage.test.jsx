import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import CompositionTaxCalculatorPage from "./CompositionTaxCalculatorPage";

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
    <MemoryRouter initialEntries={["/composition-tax-calculator"]}>
      <CompositionTaxCalculatorPage />
    </MemoryRouter>,
  );
}

const liability = () => screen.getByRole("region", { name: "Quarterly CMP-08 liability" });

describe("CompositionTaxCalculatorPage", () => {
  it("renders the inputs and the rates table with no result", () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Composition Tax Calculator" })).toBeInTheDocument();
    expect(screen.getByText("Service provider, s.10(2A)")).toBeInTheDocument();
    expect(screen.queryByText(/CMP-08 — FY/)).not.toBeInTheDocument();
  });

  it("charges a manufacturer 1% on taxable plus exempt turnover, split CGST/SGST", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Q1 (Apr–Jun) taxable turnover"), { target: { value: "1000000" } });
    fireEvent.change(screen.getByLabelText("Q1 (Apr–Jun) exempt turnover"), { target: { value: "200000" } });
    expect(within(liability()).getByText("₹12,000.00 (₹6,000.00 + ₹6,000.00)")).toBeInTheDocument();
    expect(within(liability()).getByText("2025-07-18")).toBeInTheDocument();
    expect(screen.getByText(/GSTR-4 for FY 2025-26 is due by 2026-04-30/)).toBeInTheDocument();
  });

  it("excludes exempt turnover for traders and explains why", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Business category"), { target: { value: "trader" } });
    expect(screen.getByText(/pay 1% on taxable supplies only/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Q1 (Apr–Jun) taxable turnover"), { target: { value: "1000000" } });
    fireEvent.change(screen.getByLabelText("Q1 (Apr–Jun) exempt turnover"), { target: { value: "200000" } });
    expect(within(liability()).getByText("₹10,000.00 (₹5,000.00 + ₹5,000.00)")).toBeInTheDocument();
  });

  it("adds reverse-charge tax at the selected rate and interest for late payment", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Q2 (Jul–Sep) taxable turnover"), { target: { value: "3650000" } });
    fireEvent.change(screen.getByLabelText("Q2 (Jul–Sep) RCM inward value"), { target: { value: "100000" } });
    fireEvent.change(screen.getByLabelText("Q2 (Jul–Sep) RCM rate"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Q2 (Jul–Sep) paid on"), { target: { value: "2025-11-17" } });
    // ₹36,500 + ₹5,000 RCM = ₹41,500, 30 days late → ₹614 interest.
    expect(within(liability()).getByText("₹5,000.00")).toBeInTheDocument();
    expect(within(liability()).getByText("₹614.00 (30 days)")).toBeInTheDocument();
    expect(screen.getByText("Interest on late CMP-08")).toBeInTheDocument();
  });

  it("warns when cumulative turnover crosses the service-provider limit", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Business category"), { target: { value: "service" } });
    expect(screen.queryByLabelText(/₹75 lakh limit state/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Q1 (Apr–Jun) taxable turnover"), { target: { value: "3000000" } });
    fireEvent.change(screen.getByLabelText("Q2 (Jul–Sep) taxable turnover"), { target: { value: "2500000" } });
    expect(screen.getByRole("alert")).toHaveTextContent(/crossed the ₹50,00,000.00 limit in Q2 \(Jul–Sep\)/);
    expect(screen.getByRole("progressbar", { name: "Composition turnover limit used" })).toBeInTheDocument();
  });

  it("lowers the goods limit to ₹75 lakh for special category states", () => {
    renderPage();
    fireEvent.click(screen.getByLabelText(/₹75 lakh limit state/));
    fireEvent.change(screen.getByLabelText("Q1 (Apr–Jun) taxable turnover"), { target: { value: "3750000" } });
    expect(screen.getByText(/Composition limit used: 50% of ₹75,00,000.00/)).toBeInTheDocument();
  });

  it("moves due dates with the financial year", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Financial year"), { target: { value: "2026-27" } });
    fireEvent.change(screen.getByLabelText("Q4 (Jan–Mar) taxable turnover"), { target: { value: "100" } });
    expect(within(liability()).getByText("2027-04-18")).toBeInTheDocument();
  });
});
