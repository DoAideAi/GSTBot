import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import GstOnRealEstatePage, { calculateRealEstateGst } from "./GstOnRealEstatePage";

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
    <MemoryRouter initialEntries={["/gst-on-real-estate"]}>
      <GstOnRealEstatePage />
    </MemoryRouter>,
  );
}

describe("calculateRealEstateGst", () => {
  it("refuses a missing or non-positive value", () => {
    expect(calculateRealEstateGst(NaN, "other")).toBeNull();
    expect(calculateRealEstateGst(0, "other")).toBeNull();
    expect(calculateRealEstateGst(-1, "affordable")).toBeNull();
  });

  it("applies the effective rate for each property category", () => {
    expect(calculateRealEstateGst(4000000, "affordable")).toMatchObject({ rate: 1, gst: 40000, itc: false, total: 4040000 });
    expect(calculateRealEstateGst(6000000, "other")).toMatchObject({ rate: 5, gst: 300000, itc: false, total: 6300000 });
    expect(calculateRealEstateGst(10000000, "commercial")).toMatchObject({ rate: 12, gst: 1200000, itc: true, total: 11200000 });
    expect(calculateRealEstateGst(5000000, "ready")).toMatchObject({ rate: 0, gst: 0, total: 5000000 });
  });
});

describe("GstOnRealEstatePage", () => {
  it("renders the title and subtitle", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "GST on Real Estate Calculator" })).toBeInTheDocument();
    expect(screen.getByText(/whether it is still under\s+construction/)).toBeInTheDocument();
  });

  it("shows no result before an amount is entered", () => {
    renderPage();
    expect(screen.queryByText("Agreement value", { selector: "span" })).not.toBeInTheDocument();
  });

  it("defaults to 5% for other residential property", () => {
    renderPage();
    fireEvent.change(screen.getByPlaceholderText("e.g. 6000000"), { target: { value: "6000000" } });
    expect(screen.getByText("GST (5% effective)")).toBeInTheDocument();
    expect(screen.getAllByText("₹3,00,000.00").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Not available")).toBeInTheDocument();
    expect(screen.getByText("₹63,00,000.00")).toBeInTheDocument();
  });

  it("switches to 1% for affordable housing", () => {
    renderPage();
    fireEvent.change(screen.getByPlaceholderText("e.g. 6000000"), { target: { value: "4000000" } });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "affordable" } });
    expect(screen.getByText("GST (1% effective)")).toBeInTheDocument();
    expect(screen.getAllByText("₹40,000.00").length).toBeGreaterThanOrEqual(1);
  });

  it("shows ITC available at the effective 12% commercial rate", () => {
    renderPage();
    fireEvent.change(screen.getByPlaceholderText("e.g. 6000000"), { target: { value: "10000000" } });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "commercial" } });
    expect(screen.getByText("GST (12% effective)")).toBeInTheDocument();
    expect(screen.getByText("Available")).toBeInTheDocument();
  });

  it("charges nothing on ready-to-move property", () => {
    renderPage();
    fireEvent.change(screen.getByPlaceholderText("e.g. 6000000"), { target: { value: "5000000" } });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "ready" } });
    expect(screen.getByText("GST (0% effective)")).toBeInTheDocument();
    expect(screen.getAllByText("₹50,00,000.00").length).toBe(2);
  });

  it("shows the category comparison table once an amount is entered", () => {
    renderPage();
    fireEvent.change(screen.getByPlaceholderText("e.g. 6000000"), { target: { value: "6000000" } });
    expect(screen.getByText("Same Property Across Categories")).toBeInTheDocument();
    expect(screen.getByText("₹7,20,000.00")).toBeInTheDocument();
  });
});
