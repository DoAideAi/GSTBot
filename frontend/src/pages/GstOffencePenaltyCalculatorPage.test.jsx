import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import GstOffencePenaltyCalculatorPage, { FAQS } from "./GstOffencePenaltyCalculatorPage";

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
    <MemoryRouter initialEntries={["/gst-offence-penalty-calculator"]}>
      <GstOffencePenaltyCalculatorPage />
    </MemoryRouter>,
  );
}

const row = (label) => screen.getByText(label).closest(".calc-result-row");

describe("GstOffencePenaltyCalculatorPage", () => {
  it("shows no penalty until the tax involved is entered", () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "GST Penalty Calculator" })).toBeInTheDocument();
    expect(screen.queryByText("Total penalty")).not.toBeInTheDocument();
  });

  it("charges evaded tax above the floor, half under each Act, citing Section 122(1)", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText(/Tax involved/), "400000");
    expect(row("Penalty under the CGST Act")).toHaveTextContent("2,00,000");
    expect(row("Penalty under the SGST/UTGST Act")).toHaveTextContent("2,00,000");
    expect(row("Total penalty")).toHaveTextContent("4,00,000");
    expect(row("Provision")).toHaveTextContent("Section 122(1), CGST Act");
  });

  it("explains that the ₹10,000 minimum, not the tax, set a small penalty", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText(/Tax involved/), "5000");
    expect(row("Total penalty")).toHaveTextContent("20,000");
    expect(screen.getByText(/minimum set the penalty here/)).toBeInTheDocument();
  });

  it("puts an inter-state case under the IGST Act alone", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByLabelText(/Inter-state supply/));
    await user.type(screen.getByLabelText(/Tax involved/), "5000");
    expect(row("Penalty under the IGST Act")).toHaveTextContent("10,000");
    expect(screen.queryByText("Penalty under the CGST Act")).not.toBeInTheDocument();
  });

  it("asks for the refund amount on a fraudulent refund", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("Violation"), "refund");
    await user.type(screen.getByLabelText(/Refund amount obtained/), "900000");
    expect(row("Total penalty")).toHaveTextContent("9,00,000");
    expect(row("Provision")).toHaveTextContent("Section 122(1)(viii)");
  });

  it("shows the Section 125 penalty as a ceiling with no amount asked", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("Violation"), "invoice_error");
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(row("Total penalty")).toHaveTextContent("Up to ₹50,000");
    expect(row("Provision")).toHaveTextContent("Section 125");
  });

  it("charges a late information return by the day under Section 123", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("Violation"), "info_return");
    await user.type(screen.getByLabelText(/Days the information return is late/), "20");
    expect(row("Total penalty")).toHaveTextContent("4,000");
  });

  it("sends an unfiled return to the late fee calculator rather than quoting a penalty", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("Violation"), "not_filed");
    expect(screen.queryByText("Total penalty")).not.toBeInTheDocument();
    expect(screen.getByText(/not a Section 122 penalty/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "late fee calculator" })[0]).toHaveAttribute("href", "/late-fee-calculator");
  });

  it("flags a negative amount instead of computing", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText(/Tax involved/), "-5");
    expect(screen.getByRole("alert")).toHaveTextContent("zero or more");
    expect(screen.queryByText("Total penalty")).not.toBeInTheDocument();
  });

  it("clears the amount when the violation changes, so a tax figure is not read as days", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText(/Tax involved/), "400000");
    await user.selectOptions(screen.getByLabelText("Violation"), "info_return");
    expect(screen.getByLabelText(/Days the information return is late/)).toHaveValue(null);
    expect(screen.queryByText("Total penalty")).not.toBeInTheDocument();
  });

  it("keeps every FAQ answer sentence under 220 characters and renders each one", () => {
    renderPage();
    for (const f of FAQS) {
      expect(screen.getByRole("heading", { name: f.q })).toBeInTheDocument();
      for (const s of f.a.split(/(?<=\.)\s/)) expect(s.length).toBeLessThanOrEqual(220);
    }
  });
});
