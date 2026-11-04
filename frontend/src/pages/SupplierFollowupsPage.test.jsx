import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { saveBlob } from "../lib/download";
import SupplierFollowupsPage from "./SupplierFollowupsPage";
vi.mock("../lib/api", () => ({ api: { supplierFollowups: vi.fn(), supplierDraft: vi.fn(), exportSupplierInvoices: vi.fn() }, isAbortError: () => false }));
vi.mock("../lib/download", () => ({ saveBlob: vi.fn() }));
const gstin = "27AAACR5055K1Z7";
const group = { gstin, name: "Example Supplier", count: 1, absolute_tax_difference: "180.10", items: [{ finding_index: 0, invoice_number: "INV-01", category: "missing_in_2b", books_tax: "180.10", gstr2b_tax: null, differences: "" }] };
const baseline = { run_id: 3, period: "2026-04", stale: false, suppliers: [group], total: 1, unassigned: 0 };
let copy;
const clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard");
function land() { return render(<MemoryRouter initialEntries={["/review/3/suppliers"]}><Routes><Route path="/review/:runId/suppliers" element={<SupplierFollowupsPage />} /></Routes></MemoryRouter>); }
beforeEach(() => {
  vi.resetAllMocks(); copy = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: copy } });
  api.supplierFollowups.mockResolvedValue(structuredClone(baseline));
  api.supplierDraft.mockResolvedValue({ gstin, subject: "Please review these invoices", body: "Draft invoice query", count: 1, fingerprint: "fixture-fingerprint" });
  api.exportSupplierInvoices.mockResolvedValue({ blob: new Blob(["test"]), filename: "supplier.csv" });
});
afterEach(() => { if (clipboardDescriptor) Object.defineProperty(navigator, "clipboard", clipboardDescriptor); else delete navigator.clipboard; });
it("shows missing 2B as absent and finds suppliers by name or GSTIN", async () => {
  land(); await screen.findByText("INV-01");
  expect(screen.getByRole("cell", { name: "Not present" })).toBeVisible();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "unknown" } });
  expect(screen.getByText("No matching suppliers")).toBeVisible();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: gstin } });
  expect(screen.getByText("INV-01")).toBeVisible();
  expect(api.supplierDraft).not.toHaveBeenCalled();
});
it("prepares only on request, copies user edits and downloads only the selected supplier", async () => {
  land(); fireEvent.click(await screen.findByRole("button", { name: "Prepare message for Example Supplier" }));
  const draft = await screen.findByRole("region", { name: "Supplier message draft" });
  fireEvent.change(within(draft).getByLabelText("Message"), { target: { value: "Please check invoice INV-01." } });
  fireEvent.click(within(draft).getByRole("button", { name: "Copy draft" }));
  await waitFor(() => expect(copy).toHaveBeenCalledWith("Subject: Please review these invoices\n\nPlease check invoice INV-01."));
  fireEvent.click(within(draft).getByRole("button", { name: "Download supplier invoice list" }));
  await waitFor(() => expect(saveBlob).toHaveBeenCalled());
  expect(api.exportSupplierInvoices).toHaveBeenCalledWith("3", gstin, "fixture-fingerprint");
  expect(await screen.findByRole("status")).toHaveTextContent("no message has been sent");
});
it("keeps editable text available when clipboard permission is refused", async () => {
  copy.mockRejectedValue(new Error("Denied")); land();
  fireEvent.click(await screen.findByRole("button", { name: "Prepare message for Example Supplier" }));
  fireEvent.click(await screen.findByRole("button", { name: "Copy draft" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Select and copy");
  expect(screen.getByLabelText("Message")).toHaveValue("Draft invoice query");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
it("disables current handoffs from historical data and flags missing supplier identities", async () => {
  api.supplierFollowups.mockResolvedValue({ ...baseline, stale: true, unassigned: 2 }); land();
  expect(await screen.findByRole("button", { name: "Prepare message for Example Supplier" })).toBeDisabled();
  expect(screen.getByText(/2 findings need a valid supplier GSTIN/)).toBeVisible();
  expect(screen.getByRole("link", { name: "Open Reconcile" })).toHaveAttribute("href", "/reconcile?period=2026-04");
});
it("clears old drafts on refresh and shows a stale-source refusal without claiming success", async () => {
  land(); fireEvent.click(await screen.findByRole("button", { name: "Prepare message for Example Supplier" }));
  await screen.findByLabelText("Message");
  api.exportSupplierInvoices.mockRejectedValue(new Error("Source data changed. Reconcile again."));
  fireEvent.click(screen.getByRole("button", { name: "Download supplier invoice list" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Source data changed");
  expect(saveBlob).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Refresh findings" }));
  await waitFor(() => expect(screen.queryByLabelText("Message")).not.toBeInTheDocument());
});
it("paginates a large supplier queue and resets the page when searching", async () => {
  api.supplierFollowups.mockResolvedValue({ ...baseline, suppliers: Array.from({ length: 21 }, (_, i) => ({ ...group, gstin: `GSTIN${i}`, name: `Supplier ${i}` })) });
  land(); fireEvent.click(await screen.findByRole("button", { name: "Next suppliers" }));
  expect(screen.getByRole("button", { name: "Prepare message for Supplier 20" })).toBeVisible();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Supplier 0" } });
  expect(screen.getByRole("button", { name: "Prepare message for Supplier 0" })).toBeVisible();
});
