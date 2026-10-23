import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import LateFeeInterestCalculatorPage from "./LateFeeInterestCalculatorPage";

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
    <MemoryRouter initialEntries={["/gst-late-fee-interest-calculator"]}>
      <LateFeeInterestCalculatorPage />
    </MemoryRouter>,
  );
}

function setDates(due, filed) {
  fireEvent.change(screen.getByLabelText("Due date"), { target: { value: due } });
  fireEvent.change(screen.getByLabelText(/Filing & payment date/), { target: { value: filed } });
}

describe("LateFeeInterestCalculatorPage", () => {
  it("renders the heading and the caps reference table", () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: /GST Late Fee & Interest Calculator/ })).toBeInTheDocument();
    expect(screen.getByText("GSTR-3B / GSTR-1 — above ₹5 Cr")).toBeInTheDocument();
    expect(screen.getByText("0.5% of state turnover")).toBeInTheDocument();
  });

  it("shows nothing until a due date is entered", () => {
    renderPage();
    expect(screen.queryByText("Total payable in cash")).not.toBeInTheDocument();
  });

  it("combines the capped late fee with interest on cash tax", () => {
    renderPage();
    setDates("2026-06-20", "2026-09-28"); // 100 days
    fireEvent.change(screen.getByLabelText(/Tax paid in cash/), { target: { value: "100000" } });
    expect(screen.getByText("100 days")).toBeInTheDocument();
    expect(screen.getByText(/₹50.00\/day, capped/)).toBeInTheDocument();
    // ₹2,000 cap (turnover up to ₹1.5 Cr) + 100000 × 18% × 100/365 = ₹4,932
    expect(screen.getByText("₹2,000.00")).toBeInTheDocument();
    expect(screen.getByText("₹4,932.00")).toBeInTheDocument();
    expect(screen.getByText("₹6,932.00")).toBeInTheDocument();
  });

  it("raises the cap with the turnover band", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText(/Aggregate turnover/), { target: { value: String(10 * 10000000) } });
    setDates("2026-01-20", "2026-09-28");
    // Late fee row and total row — no tax entered, so they are equal.
    expect(screen.getAllByText("₹10,000.00")).toHaveLength(2);
    expect(screen.getByText(/Turnover above ₹5 Cr/)).toBeInTheDocument();
  });

  it("uses nil rates and hides the tax inputs for a nil return", () => {
    renderPage();
    fireEvent.click(screen.getByLabelText(/Nil return/));
    setDates("2026-09-20", "2026-09-30");
    expect(screen.queryByLabelText(/Tax paid in cash/)).not.toBeInTheDocument();
    expect(screen.getByText(/₹20.00\/day/)).toBeInTheDocument();
    expect(screen.getAllByText("₹200.00").length).toBeGreaterThanOrEqual(1);
  });

  it("asks for state turnover for GSTR-9 and hides the nil option", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Return"), { target: { value: "gstr9" } });
    expect(screen.getByLabelText(/Turnover in this state/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Nil return/)).not.toBeInTheDocument();
  });

  it("adds Section 50(3) interest once wrong ITC and its date are entered", () => {
    renderPage();
    setDates("2026-09-20", "2026-10-20");
    fireEvent.change(screen.getByLabelText(/ITC wrongly availed/), { target: { value: "50000" } });
    fireEvent.change(screen.getByLabelText(/Date that credit was utilised/), { target: { value: "2026-08-20" } });
    expect(screen.getByText(/Interest on wrong ITC \(18%, 61 days\)/)).toBeInTheDocument();
    expect(screen.getByText("₹1,504.00")).toBeInTheDocument();
  });

  it("reports no charge when filed on time", () => {
    renderPage();
    setDates("2026-09-20", "2026-09-20");
    expect(screen.getByText(/no late fee or interest/)).toBeInTheDocument();
  });
});
