import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Itc180DayRulePage, { FAQS as RULE37_FAQS } from "./Itc180DayRulePage";
import ItcTimeLimitPage, { FAQS as TIME_LIMIT_FAQS } from "./ItcTimeLimitPage";
import Rule42ReversalPage, { FAQS as RULE42_FAQS } from "./Rule42ReversalPage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));
vi.mock("../lib/share", () => ({
  fullUrl: (p) => `http://localhost${p}`,
  whatsappUrl: () => "https://wa.me/",
  twitterUrl: () => "https://twitter.com/",
  copyToClipboard: vi.fn().mockResolvedValue(true),
}));
vi.mock("../lib/track", () => ({ track: () => {} }));

const renderAt = (Page) => render(<MemoryRouter><Page /></MemoryRouter>);
const row = (label) => screen.getByText(label).closest(".calc-result-row");

describe("Rule42ReversalPage", () => {
  const fill = async (user, values) => {
    for (const [label, v] of values) await user.type(screen.getByLabelText(label), v);
  };

  it("shows nothing until the total credit is entered", () => {
    renderAt(Rule42ReversalPage);
    expect(screen.queryByText("ITC to reverse (D1 + D2)")).not.toBeInTheDocument();
  });

  it("reverses the exempt share of common credit, and 5% more for non-business use", async () => {
    const user = userEvent.setup();
    renderAt(Rule42ReversalPage);
    await fill(user, [
      [/^T — Total ITC/, "100000"],
      [/^T4 — /, "50000"],
      [/^E — /, "200000"],
      [/^F — /, "1000000"],
    ]);
    expect(row("ITC to reverse (D1 + D2)")).toHaveTextContent("10,000");
    expect(row("Eligible ITC for the period (T4 + C3)")).toHaveTextContent("90,000");

    await user.click(screen.getByLabelText(/partly for non-business purposes/));
    expect(row("ITC to reverse (D1 + D2)")).toHaveTextContent("12,500");
  });

  it("asks for turnover rather than dividing by nothing", async () => {
    const user = userEvent.setup();
    renderAt(Rule42ReversalPage);
    await user.type(screen.getByLabelText(/^T — Total ITC/), "1000");
    expect(screen.getByRole("alert")).toHaveTextContent("Enter total turnover");
  });

  it("refuses specific-use credit larger than the total", async () => {
    const user = userEvent.setup();
    renderAt(Rule42ReversalPage);
    await fill(user, [[/^T — Total ITC/, "1000"], [/^T3 — /, "5000"], [/^F — /, "10"]]);
    expect(screen.getByRole("alert")).toHaveTextContent("more than the total credit");
  });

  it("renders every FAQ", () => {
    renderAt(Rule42ReversalPage);
    for (const f of RULE42_FAQS) expect(screen.getByRole("heading", { name: f.q })).toBeInTheDocument();
  });
});

describe("ItcTimeLimitPage", () => {
  beforeEach(() => vi.useFakeTimers({ now: new Date("2026-10-26T06:00:00Z"), toFake: ["Date"] }));
  afterEach(() => vi.useRealTimers());

  it("gives 30 November 2026 for an FY 2025-26 invoice, with days left", async () => {
    const user = userEvent.setup();
    renderAt(ItcTimeLimitPage);
    await user.type(screen.getByLabelText("Invoice or debit note date"), "2026-03-15");
    expect(row("Last date to claim ITC")).toHaveTextContent("30 November 2026");
    expect(row("Days left")).toHaveTextContent("35");
    expect(screen.getByRole("link", { name: "GSTR-2B" })).toBeInTheDocument();
  });

  it("closes on the GSTR-9 date when it was filed first, and says how long ago", async () => {
    const user = userEvent.setup();
    renderAt(ItcTimeLimitPage);
    await user.type(screen.getByLabelText("Invoice or debit note date"), "2025-06-01");
    await user.type(screen.getByLabelText(/Date you filed GSTR-9/), "2026-09-10");
    expect(row("Last date to claim ITC")).toHaveTextContent("10 September 2026");
    expect(row("Closed")).toHaveTextContent("46 days ago");
    expect(screen.getByText(/closed on the day it was filed/)).toBeInTheDocument();
  });

  it("points FY 2020-21 and earlier to section 16(5)", async () => {
    const user = userEvent.setup();
    renderAt(ItcTimeLimitPage);
    await user.type(screen.getByLabelText("Invoice or debit note date"), "2019-08-01");
    expect(row("Last date to claim ITC")).toHaveTextContent("30 November 2021");
    expect(screen.getByText(/under section 16\(5\)/)).toBeInTheDocument();
  });

  it("renders every FAQ", () => {
    renderAt(ItcTimeLimitPage);
    for (const f of TIME_LIMIT_FAQS) expect(screen.getByRole("heading", { name: f.q })).toBeInTheDocument();
  });
});

describe("Itc180DayRulePage", () => {
  beforeEach(() => vi.useFakeTimers({ now: new Date("2026-06-30T06:00:00Z"), toFake: ["Date"] }));
  afterEach(() => vi.useRealTimers());

  const fill = async (user, { paid = "", utilised = "" } = {}) => {
    await user.type(screen.getByLabelText("Invoice date"), "2026-01-10");
    await user.type(screen.getByLabelText(/Invoice value including GST/), "118000");
    await user.type(screen.getByLabelText(/ITC claimed on the invoice/), "18000");
    if (paid) await user.type(screen.getByLabelText(/Amount paid to the supplier/), paid);
    if (utilised) await user.type(screen.getByLabelText(/Date the ITC was used/), utilised);
  };

  it("reverses the unpaid share in the return after day 180, with interest once used", async () => {
    const user = userEvent.setup();
    renderAt(Itc180DayRulePage);
    await fill(user, { paid: "59000", utilised: "2026-02-20" });
    expect(row("Pay the supplier by")).toHaveTextContent("9 July 2026");
    expect(screen.getByText(/9 days left/)).toBeInTheDocument();
    expect(row("ITC to reverse")).toHaveTextContent("9,000");
    expect(row("Reverse in GSTR-3B for")).toHaveTextContent("August 2026");
    expect(row("That return is due")).toHaveTextContent("20 September 2026");
    expect(screen.getByText(/Interest at 18% \(212 days\)/)).toBeInTheDocument();
  });

  it("needs no reversal when the supplier was paid in full", async () => {
    const user = userEvent.setup();
    renderAt(Itc180DayRulePage);
    await fill(user, { paid: "118000" });
    expect(screen.getByText(/nothing needs to be reversed/)).toBeInTheDocument();
    expect(screen.queryByText("ITC to reverse")).not.toBeInTheDocument();
  });

  it("refuses ITC larger than the invoice value", async () => {
    const user = userEvent.setup();
    renderAt(Itc180DayRulePage);
    await user.type(screen.getByLabelText("Invoice date"), "2026-01-10");
    await user.type(screen.getByLabelText(/Invoice value including GST/), "100");
    await user.type(screen.getByLabelText(/ITC claimed on the invoice/), "500");
    expect(screen.getByRole("alert")).toHaveTextContent("cannot be more than the invoice value");
  });

  it("renders every FAQ", () => {
    renderAt(Itc180DayRulePage);
    for (const f of RULE37_FAQS) expect(screen.getByRole("heading", { name: f.q })).toBeInTheDocument();
  });
});
