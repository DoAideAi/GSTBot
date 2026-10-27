import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import PenaltyCalculatorPage from "./PenaltyCalculatorPage";

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
    <MemoryRouter initialEntries={["/penalty-calculator"]}>
      <PenaltyCalculatorPage />
    </MemoryRouter>,
  );
}

describe("PenaltyCalculatorPage", () => {
  it("renders the page title and subtitle", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "GST Penalty Calculator" })).toBeInTheDocument();
    expect(screen.getByText(/Calculate late filing penalties/)).toBeInTheDocument();
  });

  it("shows the ToolsNav component", () => {
    renderPage();
    expect(screen.getByRole("navigation", { name: "GST tools" })).toBeInTheDocument();
  });

  it("shows return type selector with all options", () => {
    renderPage();
    const select = screen.getByLabelText("Return Type");
    expect(select).toBeInTheDocument();
    expect(select.querySelectorAll("option")).toHaveLength(5);
  });

  it("shows no result before dates are entered", () => {
    renderPage();
    expect(screen.queryByText("Total Penalty")).not.toBeInTheDocument();
  });

  it("shows late fee when due date and filing date are entered", async () => {
    const user = userEvent.setup();
    renderPage();

    const dueDate = screen.getByLabelText("Due Date");
    const filingDate = screen.getByLabelText("Actual Filing Date");

    await user.type(dueDate, "2026-01-20");
    await user.type(filingDate, "2026-02-20");

    expect(screen.getByText(/Days of Delay/)).toBeInTheDocument();
    expect(screen.getByText("Total Penalty")).toBeInTheDocument();
  });

  it("shows interest calculation when tax liability is entered", async () => {
    const user = userEvent.setup();
    renderPage();

    const taxInput = screen.getByPlaceholderText("Enter tax liability amount");
    await user.type(taxInput, "100000");

    const dueDate = screen.getByLabelText("Due Date");
    const filingDate = screen.getByLabelText("Actual Filing Date");
    await user.type(dueDate, "2026-01-20");
    await user.type(filingDate, "2026-02-20");

    expect(screen.getByText(/18% p.a/)).toBeInTheDocument();
  });

  const row = (label) => screen.getByText(label).closest(".calc-result-row");

  async function late(user, { type, turnover, due = "2026-01-20", filed }) {
    if (type) await user.selectOptions(screen.getByLabelText("Return Type"), type);
    if (turnover) await user.type(screen.getByLabelText(/Aggregate turnover/), turnover);
    await user.type(screen.getByLabelText("Due Date"), due);
    await user.type(screen.getByLabelText("Actual Filing Date"), filed);
  }

  it("caps a GSTR-3B late fee at ₹2,000 for turnover up to ₹1.5 crore", async () => {
    const user = userEvent.setup();
    renderPage();
    await late(user, { turnover: "10000000", filed: "2026-05-20" });
    expect(row("Total Penalty")).toHaveTextContent("₹2,000");
  });

  it("caps a GSTR-3B late fee at ₹10,000 only above ₹5 crore", async () => {
    const user = userEvent.setup();
    renderPage();
    await late(user, { turnover: "60000000", filed: "2026-09-20" });
    expect(row("Total Penalty")).toHaveTextContent("₹10,000");
  });

  it("caps GSTR-9 at 0.04% of turnover and charges ₹50 a day up to ₹5 crore", async () => {
    const user = userEvent.setup();
    renderPage();
    await late(user, { type: "gstr9", turnover: "20000000", due: "2025-12-31", filed: "2026-12-31" });
    expect(screen.getByText(/₹50.00\/day, max ₹8,000/)).toBeInTheDocument();
    expect(row("Total Penalty")).toHaveTextContent("₹8,000");
  });

  it("charges no interest on a nil return even with a tax figure entered", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByPlaceholderText("Enter tax liability amount"), "100000");
    await late(user, { type: "gstr3b_nil", filed: "2026-02-20" });
    expect(row("Interest @ 18% p.a.")).toHaveTextContent("₹0");
    expect(row("Total Penalty")).toHaveTextContent("₹500");
  });

  it("renders FAQ section", () => {
    renderPage();
    expect(screen.getByText("How GST Late Fees & Interest Work")).toBeInTheDocument();
    expect(screen.getByText("Frequently Asked Questions")).toBeInTheDocument();
  });
});
