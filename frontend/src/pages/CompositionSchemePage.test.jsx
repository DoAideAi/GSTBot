import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import CompositionSchemePage from "./CompositionSchemePage";

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
    <MemoryRouter initialEntries={["/composition-scheme"]}>
      <CompositionSchemePage />
    </MemoryRouter>,
  );
}

describe("CompositionSchemePage", () => {
  it("renders the page title and subtitle", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Composition Scheme Eligibility Checker" })).toBeInTheDocument();
    expect(screen.getByText(/Check if your business qualifies/)).toBeInTheDocument();
  });

  it("shows eligible result for trader below threshold", async () => {
    renderPage();
    await userEvent.type(screen.getByPlaceholderText(/aggregate annual turnover/i), "5000000");

    const result = document.querySelector(".calc-result");
    expect(result).not.toBeNull();
    expect(result.textContent).toContain("Eligible");
  });

  it("shows not eligible when turnover exceeds limit", async () => {
    renderPage();
    await userEvent.type(screen.getByPlaceholderText(/aggregate annual turnover/i), "20000000");

    const result = document.querySelector(".calc-result");
    expect(result).not.toBeNull();
    expect(result.textContent).toContain("Not Eligible");
  });

  it("shows not eligible for ice cream manufacturer regardless of turnover", async () => {
    renderPage();
    await userEvent.selectOptions(screen.getByRole("combobox"), "ice_cream");
    await userEvent.type(screen.getByPlaceholderText(/aggregate annual turnover/i), "100000");

    const result = document.querySelector(".calc-result");
    expect(result).not.toBeNull();
    expect(result.textContent).toContain("Not Eligible");
    expect(result.textContent).toContain("not eligible");
  });

  it("a goods business in a ₹75 lakh state is ineligible at ₹1 crore", async () => {
    renderPage();
    await userEvent.click(screen.getByLabelText(/₹75 lakh state/));
    await userEvent.type(screen.getByPlaceholderText(/aggregate annual turnover/i), "10000000");

    const result = document.querySelector(".calc-result");
    expect(result).not.toBeNull();
    expect(result.textContent).toContain("Not Eligible");
  });

  it("names Uttarakhand, not Himachal Pradesh, among the ₹75 lakh states", () => {
    renderPage();
    const label = screen.getByLabelText(/₹75 lakh state/).closest("label");
    expect(label.textContent).toContain("Uttarakhand");
    expect(label.textContent).not.toContain("Himachal");
  });

  it("shows tax rate for eligible businesses", async () => {
    renderPage();
    await userEvent.type(screen.getByPlaceholderText(/aggregate annual turnover/i), "5000000");

    const result = document.querySelector(".calc-result");
    expect(result.textContent).toContain("1%");
  });

  it("shows share buttons on result", async () => {
    renderPage();
    await userEvent.type(screen.getByPlaceholderText(/aggregate annual turnover/i), "5000000");
    expect(screen.getByLabelText("Share on WhatsApp")).toBeInTheDocument();
  });

  it("renders FAQ section", () => {
    renderPage();
    expect(screen.getByText("Frequently Asked Questions")).toBeInTheDocument();
    expect(screen.getByText(/turnover limit for GST Composition Scheme/)).toBeInTheDocument();
  });

  it("renders related tools", () => {
    renderPage();
    expect(screen.getByText("More Free GST Tools")).toBeInTheDocument();
  });
});
