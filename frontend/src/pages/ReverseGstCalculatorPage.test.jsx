import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import ReverseGstCalculatorPage from "./ReverseGstCalculatorPage";

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
    <MemoryRouter initialEntries={["/reverse-gst-calculator"]}>
      <ReverseGstCalculatorPage />
    </MemoryRouter>,
  );
}

describe("ReverseGstCalculatorPage", () => {
  it("renders the title and subtitle", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Reverse GST Calculator" })).toBeInTheDocument();
    expect(screen.getByText(/Remove GST from a price that already includes it/)).toBeInTheDocument();
  });

  it("shows no result before an amount is entered", () => {
    renderPage();
    expect(screen.queryByText("Base Amount (excl. GST)")).not.toBeInTheDocument();
  });

  it("extracts 18% GST from an inclusive amount", () => {
    renderPage();
    fireEvent.change(screen.getByPlaceholderText("e.g. 1180"), { target: { value: "1180" } });
    expect(screen.getByText("Base Amount (excl. GST)")).toBeInTheDocument();
    expect(screen.getAllByText("₹1,000.00").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("CGST (9%)")).toBeInTheDocument();
    expect(screen.getAllByText("₹90.00").length).toBe(2);
    expect(screen.getByText("GST Removed")).toBeInTheDocument();
  });

  it("switches to IGST for interstate supply", () => {
    renderPage();
    fireEvent.change(screen.getByPlaceholderText("e.g. 1180"), { target: { value: "1180" } });
    fireEvent.click(screen.getByLabelText(/Interstate supply/));
    expect(screen.getByText("IGST (18%)")).toBeInTheDocument();
    expect(screen.queryByText("CGST (9%)")).not.toBeInTheDocument();
    expect(screen.getAllByText("₹180.00").length).toBeGreaterThanOrEqual(2);
  });

  it("recalculates when the rate changes", () => {
    renderPage();
    fireEvent.change(screen.getByPlaceholderText("e.g. 1180"), { target: { value: "1050" } });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "5" } });
    expect(screen.getByText("CGST (2.5%)")).toBeInTheDocument();
    expect(screen.getAllByText("₹1,000.00").length).toBeGreaterThanOrEqual(1);
  });

  it("shows the rate comparison table once an amount is entered", () => {
    renderPage();
    fireEvent.change(screen.getByPlaceholderText("e.g. 1180"), { target: { value: "1180" } });
    expect(screen.getByText("Same Amount at Other GST Rates")).toBeInTheDocument();
    expect(screen.getAllByText("40%").length).toBeGreaterThanOrEqual(2);
  });
});
