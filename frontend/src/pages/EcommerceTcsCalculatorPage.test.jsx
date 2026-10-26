import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import EcommerceTcsCalculatorPage, { FAQS } from "./EcommerceTcsCalculatorPage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));
vi.mock("../lib/share", () => ({
  fullUrl: (p) => `http://localhost${p}`,
  whatsappUrl: () => "https://wa.me/",
  twitterUrl: () => "https://twitter.com/",
  copyToClipboard: vi.fn().mockResolvedValue(true),
}));
vi.mock("../lib/track", () => ({ track: () => {} }));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/ecommerce-tcs-calculator"]}>
      <EcommerceTcsCalculatorPage />
    </MemoryRouter>,
  );
}

const row = (label) => screen.getByText(label).closest(".calc-result-row");

describe("EcommerceTcsCalculatorPage", () => {
  it("shows no result until sales are entered", () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "E-commerce TCS Calculator" })).toBeInTheDocument();
    expect(screen.queryByText("Total withheld from payout")).not.toBeInTheDocument();
  });

  it("computes TCS on net sales and 194-O on gross", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText(/Sales through the marketplace/), "1000000");
    await user.type(screen.getByLabelText(/Customer returns/), "100000");

    expect(row("GST TCS (Section 52)")).toHaveTextContent("4,500");
    expect(row("CGST TCS (0.25%)")).toHaveTextContent("2,250");
    expect(row("Income-tax TDS (194-O, 0.1% of gross)")).toHaveTextContent("1,000");
    expect(row("Total withheld from payout")).toHaveTextContent("5,500");
  });

  it("moves the inter-state share to IGST", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText(/Sales through the marketplace/), "200000");
    const share = screen.getByLabelText(/Share of sales to buyers in other states/);
    await user.clear(share);
    await user.type(share, "100");
    expect(row("IGST TCS (0.5%)")).toHaveTextContent("1,000");
    expect(row("CGST TCS (0.25%)")).toHaveTextContent("0");
  });

  it("explains a month where returns exceed sales", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText(/Sales through the marketplace/), "50000");
    await user.type(screen.getByLabelText(/Customer returns/), "80000");
    expect(screen.getByText(/Returns exceed sales by/)).toBeInTheDocument();
    expect(row("GST TCS (Section 52)")).toHaveTextContent("0");
  });

  it("flags a negative amount instead of computing", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText(/Sales through the marketplace/), "-5");
    expect(screen.getByRole("alert")).toHaveTextContent("zero or more");
    expect(screen.queryByText("Total withheld from payout")).not.toBeInTheDocument();
  });

  it("renders every FAQ", () => {
    renderPage();
    for (const f of FAQS) expect(screen.getByRole("heading", { name: f.q })).toBeInTheDocument();
  });
});
