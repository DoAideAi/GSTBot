import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Gstr9SummaryPage from "./Gstr9SummaryPage";

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

const DRAFT_KEY = "gst.gstr9-summary.draft";

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/gstr9-summary"]}>
      <Gstr9SummaryPage />
    </MemoryRouter>,
  );
}

describe("Gstr9SummaryPage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders the heading and a twelve-month grid with no summary", () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "GSTR-9 Summary Generator" })).toBeInTheDocument();
    expect(screen.getByLabelText("March GSTR-3B ITC claimed")).toBeInTheDocument();
    expect(screen.queryByText(/GSTR-9 Summary — FY/)).not.toBeInTheDocument();
  });

  it("summarises a single month and flags the short payment", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("April GSTR-1 taxable value"), { target: { value: "100000" } });
    fireEvent.change(screen.getByLabelText("April GSTR-1 tax"), { target: { value: "18000" } });
    fireEvent.change(screen.getByLabelText("April GSTR-3B tax"), { target: { value: "15000" } });
    fireEvent.change(screen.getByLabelText(/Date you will pay/), { target: { value: "2025-05-20" } });
    expect(screen.getByText("GSTR-9 Summary — FY 2025-26")).toBeInTheDocument();
    expect(screen.getByText("Months that don't match")).toBeInTheDocument();
    expect(screen.getByText("Short paid — pay via DRC-03")).toBeInTheDocument();
    // Paying on the due date → no interest, DRC-03 is the ₹3,000 gap alone.
    expect(screen.getAllByText("₹3,000.00").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/GSTR-9 is optional up to ₹2 crore/)).toBeInTheDocument();
  });

  it("loads the sample year with both kinds of mismatch and an ITC warning", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Load sample year" }));
    expect(screen.getByText(/Sample year loaded/)).toBeInTheDocument();
    const mismatch = screen.getByRole("region", { name: "Month-wise GSTR-1 vs GSTR-3B differences" });
    expect(mismatch).toHaveTextContent(/August.*Short paid/);
    expect(mismatch).toHaveTextContent(/January.*Paid more than declared/);
    expect(screen.getByText(/GSTR-9 is mandatory/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/more ITC than GSTR-2B supports/);
  });

  it("reports unclaimed GSTR-2B credit with the Section 16(4) deadline", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("April GSTR-3B ITC claimed"), { target: { value: "1000" } });
    fireEvent.change(screen.getByLabelText(/Table 8A/), { target: { value: "5000" } });
    expect(screen.getByText(/was never claimed/)).toHaveTextContent("30 November 2026");
    expect(screen.getByText(/agree for every month/)).toBeInTheDocument();
  });

  it("fills the grid from pasted spreadsheet rows", () => {
    renderPage();
    fireEvent.change(screen.getByPlaceholderText(/April/), {
      target: { value: "April\t10,00,000\t1,80,000\t10,00,000\t1,80,000\t1,00,000\nMay\t1\t1\t1\t1\t1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Fill table" }));
    expect(screen.getByText("Filled 2 months from the pasted rows.")).toBeInTheDocument();
    expect(screen.getByLabelText("April GSTR-1 taxable value")).toHaveValue(1000000);
  });

  it("says so when the paste has no numbers", () => {
    renderPage();
    fireEvent.change(screen.getByPlaceholderText(/April/), { target: { value: "Month\tValue" } });
    fireEvent.click(screen.getByRole("button", { name: "Fill table" }));
    expect(screen.getByText(/No numeric rows found/)).toBeInTheDocument();
  });

  it("keeps a draft in localStorage and restores it", () => {
    const { unmount } = renderPage();
    fireEvent.change(screen.getByLabelText("June GSTR-1 tax"), { target: { value: "4242" } });
    expect(JSON.parse(window.localStorage.getItem(DRAFT_KEY)).months[2].r1Tax).toBe("4242");
    unmount();
    renderPage();
    expect(screen.getByLabelText("June GSTR-1 tax")).toHaveValue(4242);
  });

  it("ignores a corrupt draft and clears everything on demand", () => {
    window.localStorage.setItem(DRAFT_KEY, "{not json");
    renderPage();
    expect(screen.getByLabelText("April GSTR-1 tax")).toHaveValue(null);
    fireEvent.click(screen.getByRole("button", { name: "Load sample year" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(screen.queryByText(/GSTR-9 Summary — FY/)).not.toBeInTheDocument();
  });
});
