import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import LateFeeCalculatorPage from "./LateFeeCalculatorPage";

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
vi.mock("../lib/track", () => ({ track: () => {} }));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/late-fee-calculator"]}>
      <LateFeeCalculatorPage />
    </MemoryRouter>,
  );
}

describe("LateFeeCalculatorPage", () => {
  it("renders the title and return type selector", () => {
    renderPage();
    expect(screen.getByText("GST Late Fee Calculator")).toBeInTheDocument();
    expect(screen.getByDisplayValue("GSTR-3B")).toBeInTheDocument();
  });

  it("shows no result before dates are entered", () => {
    renderPage();
    expect(screen.queryByText("Late Fee Calculation")).not.toBeInTheDocument();
  });

  it("calculates late fee for GSTR-3B", () => {
    renderPage();
    const dates = document.querySelectorAll('input[type="date"]');
    fireEvent.change(dates[0], { target: { value: "2026-01-20" } });
    fireEvent.change(dates[1], { target: { value: "2026-02-20" } });

    expect(screen.getByText("Late Fee Calculation")).toBeInTheDocument();
    expect(screen.getByText("31 days")).toBeInTheDocument();
  });

  it("shows on-time message when filing date <= due date", () => {
    renderPage();
    const dates = document.querySelectorAll('input[type="date"]');
    fireEvent.change(dates[0], { target: { value: "2026-02-20" } });
    fireEvent.change(dates[1], { target: { value: "2026-02-20" } });

    expect(screen.getByText(/filed on time/i)).toBeInTheDocument();
  });

  it("renders the quick reference table", () => {
    renderPage();
    expect(screen.getByText("GST Late Fee Rates — Quick Reference")).toBeInTheDocument();
    expect(screen.getAllByText("GSTR-9 (Annual Return)").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("GSTR-3B / GSTR-1 — ₹1.5 Cr to ₹5 Cr")).toBeInTheDocument();
  });

  it("shows turnover field for GSTR-9", () => {
    renderPage();
    fireEvent.change(screen.getByDisplayValue("GSTR-3B"), { target: { value: "gstr9" } });
    expect(screen.getByText(/Annual State Turnover/)).toBeInTheDocument();
  });

  it("ties every label to its control", () => {
    // These four labels had no htmlFor, so each control was announced unnamed.
    renderPage();
    expect(screen.getByLabelText("Return Type")).toBeInTheDocument();
    expect(screen.getByLabelText("Due Date")).toBeInTheDocument();
    expect(screen.getByLabelText("Filing Date")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Return Type"), { target: { value: "gstr9" } });
    expect(screen.getByLabelText("Annual State Turnover (₹)")).toBeInTheDocument();
  });

  it("caps GSTR-3B late fee at ₹2,000 for turnover up to ₹1.5 crore", () => {
    renderPage();
    const dates = document.querySelectorAll('input[type="date"]');
    fireEvent.change(dates[0], { target: { value: "2025-01-20" } });
    fireEvent.change(dates[1], { target: { value: "2026-01-20" } });
    expect(screen.getByText("Late Fee Calculation")).toBeInTheDocument();
    expect(screen.getByText("₹2,000.00")).toBeInTheDocument();
    expect(screen.getByText(/Turnover up to ₹1.5 Cr — max ₹2,000/)).toBeInTheDocument();
  });

  it("caps at ₹10,000 above ₹5 crore turnover", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText(/Aggregate Turnover/), { target: { value: String(10 * 10000000) } });
    const dates = document.querySelectorAll('input[type="date"]');
    fireEvent.change(dates[0], { target: { value: "2025-01-20" } });
    fireEvent.change(dates[1], { target: { value: "2026-01-20" } });
    expect(screen.getByText("₹10,000.00")).toBeInTheDocument();
  });

  it("applies the 0.04% GSTR-9 cap for turnover up to ₹5 crore", () => {
    renderPage();
    fireEvent.change(screen.getByDisplayValue("GSTR-3B"), { target: { value: "gstr9" } });
    fireEvent.change(screen.getByPlaceholderText("e.g. 5000000"), { target: { value: "25000000" } });
    const dates = document.querySelectorAll('input[type="date"]');
    fireEvent.change(dates[0], { target: { value: "2025-12-31" } });
    fireEvent.change(dates[1], { target: { value: "2026-10-31" } });
    // 304 days × ₹50 = ₹15,200, capped at 0.04% of ₹2.5 Cr = ₹10,000
    expect(screen.getByText("₹10,000.00")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Nil return/)).not.toBeInTheDocument();
  });
});
