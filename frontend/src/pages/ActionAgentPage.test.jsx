import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StubAuth } from "../test/auth";
import { api } from "../lib/api";
import ActionAgentPage from "./ActionAgentPage";
const REPORT = {
  period: "2026-10", generated_at: "2026-11-03T05:00:00Z",
  checked: ["overview", "reconciliation", "invoice_checks"],
  facts: { invoice_count: 4, output_tax: "100.20", book_credit_before_reconciliation: "80.10" },
  plan: { summary: "Review two missing supplier matches.",
    actions: [{ title: "Reconcile the missing matches", priority: "high", reason: "Two invoices are missing in GSTR-2B.", next_step: "Review the differences.", destination: "reconcile", sources: ["reconciliation"] }],
    caveats: ["This reflects the latest completed reconciliation."],
  },
};
function mount() { return render(<MemoryRouter><StubAuth><ActionAgentPage /></StubAuth></MemoryRouter>); }
function run() { fireEvent.click(screen.getByRole("button", { name: "Create action plan" })); }
describe("GST Action Agent", () => {
  beforeEach(() => { vi.spyOn(api, "reviewActions").mockResolvedValue(REPORT); });
  afterEach(() => vi.restoreAllMocks());
  it("waits for an explicit request before sending summaries", () => {
    mount();expect(api.reviewActions).not.toHaveBeenCalled();
    expect(screen.getByText(/Uses OpenAI to review summaries/)).toBeInTheDocument();
  });
  it("sends the selected period and focus, then shows evidence and safe links", async () => {
    mount();fireEvent.change(screen.getByLabelText("Filing period"), { target: { value: "2026-10" } });
    fireEvent.click(screen.getByRole("radio", { name: /Find ITC risks/ }));run();
    expect(await screen.findByText(REPORT.plan.summary)).toBeInTheDocument();
    expect(api.reviewActions).toHaveBeenCalledWith({ period: "2026-10", focus: "itc" }, { signal: expect.any(AbortSignal) });
    expect(screen.getByRole("link", { name: "Open reconciliation" })).toHaveAttribute("href", "/reconcile?period=2026-10");
    expect(screen.getByText("₹100.20")).toBeInTheDocument();
    expect(screen.getByLabelText("Records checked")).toHaveTextContent("Invoice checks");
  });
  it("shows the server error and lets the user try again", async () => {
    api.reviewActions.mockRejectedValueOnce(new Error("Daily review limit reached"));
    mount();run();expect(await screen.findByRole("alert")).toHaveTextContent("Daily review limit reached");
    run();expect(await screen.findByText(REPORT.plan.summary)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
  it("prevents duplicate requests and provides progress", () => {
    api.reviewActions.mockReturnValue(new Promise(() => {}));mount();run();
    expect(screen.getByRole("button", { name: "Reviewing records…" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Checking the relevant records");
    expect(api.reviewActions).toHaveBeenCalledTimes(1);
  });
  it("cancels the request and ignores a late answer", async () => {
    let resolve;api.reviewActions.mockReturnValue(new Promise(r => { resolve = r; }));
    mount();run();const signal = api.reviewActions.mock.calls[0][1].signal;
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));expect(signal.aborted).toBe(true);
    resolve(REPORT);
    await waitFor(() => expect(screen.getByRole("button", { name: "Create action plan" })).toBeEnabled());
    expect(screen.queryByText(REPORT.plan.summary)).not.toBeInTheDocument();
  });
  it("clears old results on period and focus changes", async () => {
    mount();run();await screen.findByText(REPORT.plan.summary);
    fireEvent.change(screen.getByLabelText("Filing period"), { target: { value: "2026-09" } });
    expect(screen.queryByText(REPORT.plan.summary)).not.toBeInTheDocument();
    run();await screen.findByText(REPORT.plan.summary);
    fireEvent.click(screen.getByRole("radio", { name: /Check filing readiness/ }));
    expect(screen.queryByText(REPORT.plan.summary)).not.toBeInTheDocument();
  });
  it("aborts on unmount or business switch", () => {
    api.reviewActions.mockReturnValue(new Promise(() => {}));const view=mount();run();
    const signal=api.reviewActions.mock.calls[0][1].signal;view.unmount();expect(signal.aborted).toBe(true);
  });
  it("renders generated text safely and rejects external link destinations", async () => {
    api.reviewActions.mockResolvedValue({ ...REPORT, plan: { ...REPORT.plan,
      summary: '<img src=x onerror="alert(1)">', actions: [{ ...REPORT.plan.actions[0], destination: "https://evil.example" }], caveats: [],
    } });
    mount();run();expect(await screen.findByText('<img src=x onerror="alert(1)">')).toBeInTheDocument();
    expect(document.querySelector('img[src="x"]')).toBeNull();
    expect(document.querySelector('a[href="https://evil.example"]')).toBeNull();
  });
});
