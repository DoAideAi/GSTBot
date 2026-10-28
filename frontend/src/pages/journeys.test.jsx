/**
 * Journey handoff tests.
 *
 * Each test asserts that a page offers the navigation links its users need to
 * reach the next step. These are not integration tests that walk a full flow —
 * the individual page suites cover behaviour — but they catch the dead-end
 * regression that M18 fixed: a page that renders fine but strands its visitor.
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StubAuth } from "../test/auth";

import ErrorBanner from "../components/ErrorBanner";
import InvoiceDetailPage from "./InvoiceDetailPage";
import SuppliersPage from "./SuppliersPage";

function jsonResponse(body, { status = 200 } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    text: async () => JSON.stringify(body),
  };
}

beforeEach(() => {
  global.fetch = vi.fn();
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("Journey 1: upload → review invoice → next step", () => {
  const purchase = {
    id: 42,
    invoice_number: "INV-001",
    invoice_type: "purchase",
    status: "parsed",
    counterparty_gstin: "27AAPFU0939F1ZV",
    counterparty_name: "Acme",
    invoice_date: "2026-04-15",
    hsn_code: "8471",
    taxable_value: "1000.00",
    cgst: "90.00",
    sgst: "90.00",
    igst: "0.00",
    cess: "0.00",
    total_value: "1180.00",
    invoice_value: "1180.00",
    warnings: [],
    parsed_with: "heuristics",
    extraction_confidence: 0.8,
  };

  it("a purchase invoice links back to all invoices", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse(purchase));
    render(
      <MemoryRouter initialEntries={["/invoices/42"]}>
        <StubAuth>
          <Routes>
            <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
          </Routes>
        </StubAuth>
      </MemoryRouter>,
    );
    await screen.findByLabelText("Counterparty GSTIN");
    expect(screen.getByRole("link", { name: /all invoices/i })).toHaveAttribute("href", "/invoices");
  });

  it("a purchase invoice offers reconciliation as the next step", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse(purchase));
    render(
      <MemoryRouter initialEntries={["/invoices/42"]}>
        <StubAuth>
          <Routes>
            <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
          </Routes>
        </StubAuth>
      </MemoryRouter>,
    );
    await screen.findByLabelText("Counterparty GSTIN");
    expect(screen.getByRole("link", { name: /reconcile/i })).toHaveAttribute("href", "/reconcile");
  });

  it("a sales invoice offers filing as the next step", async () => {
    const sales = { ...purchase, invoice_type: "sales" };
    global.fetch.mockResolvedValueOnce(jsonResponse(sales));
    render(
      <MemoryRouter initialEntries={["/invoices/42"]}>
        <StubAuth>
          <Routes>
            <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
          </Routes>
        </StubAuth>
      </MemoryRouter>,
    );
    await screen.findByLabelText("Counterparty GSTIN");
    expect(screen.getByRole("link", { name: /prepare gstr-1/i })).toHaveAttribute("href", "/filing");
  });
});

describe("Journey 5: upload → parsing failure → error feedback → retry", () => {
  const failed = {
    id: 99,
    invoice_number: null,
    invoice_type: "purchase",
    status: "failed",
    counterparty_gstin: null,
    counterparty_name: null,
    invoice_date: null,
    hsn_code: null,
    taxable_value: "0.00",
    cgst: "0.00",
    sgst: "0.00",
    igst: "0.00",
    cess: "0.00",
    total_value: "0.00",
    invoice_value: "0.00",
    warnings: [],
    parsed_with: null,
    extraction_confidence: null,
    parse_error: "Could not identify any invoice fields in the uploaded image.",
  };

  it("shows the parse error so the user knows what went wrong", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse(failed));
    render(
      <MemoryRouter initialEntries={["/invoices/99"]}>
        <StubAuth>
          <Routes>
            <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
          </Routes>
        </StubAuth>
      </MemoryRouter>,
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not identify any invoice fields/i);
  });

  it("offers re-extraction as a retry path", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse(failed));
    render(
      <MemoryRouter initialEntries={["/invoices/99"]}>
        <StubAuth role="owner">
          <Routes>
            <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
          </Routes>
        </StubAuth>
      </MemoryRouter>,
    );
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: /try re-extracting/i })).toBeInTheDocument();
  });
});

describe("Journey 2: paywall → pricing", () => {
  it("the paid-tier refusal links to pricing", () => {
    render(
      <ErrorBanner message="This feature requires a paid subscription. Visit /pricing to upgrade." />,
    );
    expect(screen.getByRole("link", { name: "See plans" })).toHaveAttribute("href", "/pricing");
  });

  it("the upload allowance banner links to pricing", () => {
    render(
      <ErrorBanner message="The monthly allowance ran out. 5 file(s) were not uploaded. Upgrade the plan or try again next month." />,
    );
    expect(screen.getByRole("link", { name: "See plans" })).toHaveAttribute("href", "/pricing");
  });
});

describe("Journey 3: suppliers → reconcile / invoices", () => {
  beforeEach(() => {
    global.fetch.mockResolvedValue(
      jsonResponse({ items: [], total: 0 }),
    );
  });

  it("links to reconciliation from an empty supplier list", async () => {
    render(
      <MemoryRouter>
        <StubAuth>
          <SuppliersPage />
        </StubAuth>
      </MemoryRouter>,
    );
    await screen.findByText(/no suppliers yet/i);
    expect(screen.getByRole("link", { name: /reconcile invoices/i })).toHaveAttribute("href", "/reconcile");
  });

  it("offers upload when the book is empty and the user can write", async () => {
    render(
      <MemoryRouter>
        <StubAuth role="owner">
          <SuppliersPage />
        </StubAuth>
      </MemoryRouter>,
    );
    await screen.findByText(/no suppliers yet/i);
    expect(screen.getByRole("link", { name: /upload invoices/i })).toHaveAttribute("href", "/upload");
  });
});
