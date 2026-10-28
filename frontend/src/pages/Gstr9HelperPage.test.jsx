import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import Gstr9HelperPage from "./Gstr9HelperPage";

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
    <MemoryRouter initialEntries={["/gstr9-helper"]}>
      <Gstr9HelperPage />
    </MemoryRouter>,
  );
}

describe("Gstr9HelperPage", () => {
  it("renders the page title and subtitle", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: /GSTR-9 Annual Return Helper/i })).toBeInTheDocument();
    expect(screen.getByText(/annual GST data/)).toBeInTheDocument();
  });

  it("shows the monthly data table with 12 months", () => {
    renderPage();
    expect(screen.getByText("April")).toBeInTheDocument();
    expect(screen.getByText("March")).toBeInTheDocument();
  });

  it("names each month's inputs, which sit in a table with no labels", () => {
    renderPage();
    expect(screen.getByLabelText("April: Outward supplies (₹)")).toBeInTheDocument();
    expect(screen.getByLabelText("March: ITC claimed (₹)")).toBeInTheDocument();
    expect(screen.getByLabelText("June: Tax paid (₹)")).toBeInTheDocument();
  });

  it("calculates summary when month data is entered", async () => {
    renderPage();
    const outwardInputs = screen.getAllByPlaceholderText("0");
    await userEvent.type(outwardInputs[0], "500000");

    const result = document.querySelector(".calc-result");
    expect(result).not.toBeNull();
    expect(result.textContent).toContain("Total Taxable Outward Supplies");
    expect(result.textContent).toContain("5,00,000");
  });

  it("shows GSTR-9C note when turnover exceeds 5 crore", async () => {
    renderPage();
    const outwardInputs = screen.getAllByPlaceholderText("0");
    await userEvent.type(outwardInputs[0], "60000000");

    const result = document.querySelector(".calc-result");
    expect(result.textContent).toContain("GSTR-9C");
    expect(result.textContent).toContain("reconciliation statement");
  });

  it("shows mandatory note when turnover exceeds 2 crore", async () => {
    renderPage();
    const outwardInputs = screen.getAllByPlaceholderText("0");
    await userEvent.type(outwardInputs[0], "25000000");

    const result = document.querySelector(".calc-result");
    expect(result.textContent).toContain("mandatory");
  });

  it("shows share buttons on result", async () => {
    renderPage();
    const outwardInputs = screen.getAllByPlaceholderText("0");
    await userEvent.type(outwardInputs[0], "500000");

    expect(screen.getByLabelText("Share on WhatsApp")).toBeInTheDocument();
  });

  it("renders FAQ section", () => {
    renderPage();
    expect(screen.getByText("Frequently Asked Questions")).toBeInTheDocument();
    expect(screen.getByText(/What is GSTR-9/)).toBeInTheDocument();
  });

  it("renders related tools", () => {
    renderPage();
    expect(screen.getByText("More Free GST Tools")).toBeInTheDocument();
  });
});
