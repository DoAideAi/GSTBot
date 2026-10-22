import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import GstOnGoldPage, { calculateGoldGst } from "./GstOnGoldPage";

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
    <MemoryRouter initialEntries={["/gst-on-gold"]}>
      <GstOnGoldPage />
    </MemoryRouter>,
  );
}

describe("calculateGoldGst", () => {
  it("refuses a missing or non-positive gold value", () => {
    expect(calculateGoldGst(NaN, 10, "percent")).toBeNull();
    expect(calculateGoldGst(0, 10, "percent")).toBeNull();
    expect(calculateGoldGst(-5, 10, "percent")).toBeNull();
  });

  it("treats blank or negative making charges as zero", () => {
    expect(calculateGoldGst(100000, NaN, "percent")).toMatchObject({ makingAmount: 0, makingGst: 0, totalGst: 3000 });
    expect(calculateGoldGst(100000, -2, "rupees")).toMatchObject({ makingAmount: 0, totalGst: 3000 });
  });

  it("taxes gold at 3% and percentage making charges at 5%", () => {
    expect(calculateGoldGst(100000, 10, "percent")).toEqual({
      goldValue: 100000,
      makingAmount: 10000,
      goldGst: 3000,
      makingGst: 500,
      totalGst: 3500,
      total: 113500,
    });
  });

  it("taxes rupee-denominated making charges at 5%", () => {
    expect(calculateGoldGst(100000, 8000, "rupees")).toMatchObject({
      makingAmount: 8000,
      makingGst: 400,
      total: 111400,
    });
  });
});

describe("GstOnGoldPage", () => {
  it("renders the title and subtitle", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "GST on Gold Calculator" })).toBeInTheDocument();
    expect(screen.getByText(/Gold is taxed twice on one invoice/)).toBeInTheDocument();
  });

  it("shows no result before a gold value is entered", () => {
    renderPage();
    expect(screen.queryByText("Total GST")).not.toBeInTheDocument();
  });

  it("calculates the full bill for gold with 10% making charges", () => {
    renderPage();
    fireEvent.change(screen.getByPlaceholderText("e.g. 100000"), { target: { value: "100000" } });
    expect(screen.getByText("GST on gold (3%)")).toBeInTheDocument();
    expect(screen.getByText("₹3,000.00")).toBeInTheDocument();
    expect(screen.getByText("GST on making charges (5%)")).toBeInTheDocument();
    expect(screen.getByText("₹500.00")).toBeInTheDocument();
    expect(screen.getByText("₹1,13,500.00")).toBeInTheDocument();
  });

  it("switches making charges to a rupee amount", () => {
    renderPage();
    fireEvent.change(screen.getByPlaceholderText("e.g. 100000"), { target: { value: "100000" } });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "rupees" } });
    fireEvent.change(screen.getByPlaceholderText("e.g. 8000"), { target: { value: "8000" } });
    expect(screen.getByText("₹400.00")).toBeInTheDocument();
    expect(screen.getByText("₹1,11,400.00")).toBeInTheDocument();
  });

  it("drops the making-charge GST to zero when making charges are cleared", () => {
    renderPage();
    fireEvent.change(screen.getByPlaceholderText("e.g. 100000"), { target: { value: "100000" } });
    fireEvent.change(screen.getByPlaceholderText("e.g. 10"), { target: { value: "" } });
    expect(screen.getAllByText("₹0.00").length).toBe(2);
    expect(screen.getByText("₹1,03,000.00")).toBeInTheDocument();
  });
});
