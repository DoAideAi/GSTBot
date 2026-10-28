import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import InvoiceGeneratorPage from "./InvoiceGeneratorPage";

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
    <MemoryRouter initialEntries={["/invoice-generator"]}>
      <InvoiceGeneratorPage />
    </MemoryRouter>,
  );
}

describe("InvoiceGeneratorPage", () => {
  it("dates a new invoice today in India, not today in UTC", () => {
    // 01:00 IST on 28 October is still 27 October in UTC.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-27T19:30:00Z"));
    try {
      renderPage();
      expect(screen.getByLabelText("Invoice Date")).toHaveValue("2026-10-28");
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders the page title and subtitle", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "GST Invoice Generator" })).toBeInTheDocument();
    expect(screen.getByText(/Create GST-compliant tax invoices/)).toBeInTheDocument();
  });

  it("shows seller and buyer input sections", () => {
    renderPage();
    expect(screen.getByText("Seller Details")).toBeInTheDocument();
    expect(screen.getByText("Buyer Details")).toBeInTheDocument();
  });

  it("shows the add item button", () => {
    renderPage();
    expect(screen.getByText("+ Add Item")).toBeInTheDocument();
  });

  it("shows total when item rate is entered", async () => {
    renderPage();
    const rateInputs = screen.getAllByPlaceholderText("0.00");
    await userEvent.type(rateInputs[0], "1000");

    const result = document.querySelector(".calc-result");
    expect(result).not.toBeNull();
    expect(result.textContent).toContain("Taxable Amount");
  });

  it("preview button is disabled without required fields", () => {
    renderPage();
    const previewBtn = screen.getByText("Preview Invoice");
    expect(previewBtn).toBeDisabled();
  });

  it("preview button enables with required fields filled", async () => {
    renderPage();
    const sellerName = screen.getAllByPlaceholderText(/business name/i)[0];
    const buyerName = screen.getAllByPlaceholderText(/business name/i)[1];
    const descInputs = screen.getAllByPlaceholderText("Item description");
    const rateInputs = screen.getAllByPlaceholderText("0.00");

    await userEvent.type(sellerName, "Test Seller");
    await userEvent.type(buyerName, "Test Buyer");
    await userEvent.type(descInputs[0], "Test Item");
    await userEvent.type(rateInputs[0], "1000");

    const previewBtn = screen.getByText("Preview Invoice");
    expect(previewBtn).not.toBeDisabled();
  });

  it("auto-generates an invoice number on load", () => {
    renderPage();
    const invoiceInput = screen.getByPlaceholderText("Auto-generated");
    expect(invoiceInput.value).toMatch(/^INV-\d{4}-\d{3}$/);
  });

  it("shows GSTIN validation feedback", async () => {
    renderPage();
    const gstinInputs = screen.getAllByPlaceholderText(/e\.g\./);
    await userEvent.type(gstinInputs[0], "INVALID");
    expect(screen.getByText(/GSTIN is 15 characters/)).toBeInTheDocument();
  });

  it("an unregistered buyer prints as URP and their chosen state sets IGST", async () => {
    renderPage();
    const [sellerName, buyerName] = screen.getAllByPlaceholderText(/business name/i);
    await userEvent.type(sellerName, "Test Seller");
    await userEvent.type(buyerName, "Walk-in Buyer");
    await userEvent.type(screen.getAllByPlaceholderText(/e\.g\./)[0], "27AAPFU0939F1ZV");
    await userEvent.click(screen.getByLabelText("Unregistered buyer (URP)"));
    expect(screen.getByDisplayValue("URP")).toBeDisabled();

    await userEvent.selectOptions(screen.getByLabelText(/Place of Supply/), "29");
    expect(screen.getByText("(Interstate — IGST)")).toBeInTheDocument();

    await userEvent.type(screen.getAllByPlaceholderText("Item description")[0], "Chair");
    await userEvent.type(screen.getAllByPlaceholderText("0.00")[0], "1000");
    await userEvent.click(screen.getByText("Preview Invoice"));
    expect(screen.getByText(/GSTIN: URP \(Unregistered\) · Place of supply: 29-Karnataka/)).toBeInTheDocument();
  });

  it("escapes the invoice number in the print window's title", async () => {
    const written = [];
    const fakeWindow = { document: { write: (html) => written.push(html), close: () => {} } };
    const open = vi.spyOn(window, "open").mockReturnValue(fakeWindow);
    try {
      renderPage();
      const [sellerName, buyerName] = screen.getAllByPlaceholderText(/business name/i);
      await userEvent.type(sellerName, "Test Seller");
      await userEvent.type(buyerName, "Buyer");
      const number = screen.getByLabelText("Invoice Number");
      await userEvent.clear(number);
      await userEvent.type(number, "</title><img src=x onerror=alert(1)>");
      await userEvent.type(screen.getAllByPlaceholderText("Item description")[0], "Chair");
      await userEvent.type(screen.getAllByPlaceholderText("0.00")[0], "1000");
      await userEvent.click(screen.getByText("Preview Invoice"));
      await userEvent.click(screen.getByText("Download PDF"));
    } finally {
      open.mockRestore();
    }
    expect(written).toHaveLength(1);
    const title = written[0].match(/<title>[\s\S]*?<\/title>/)[0];
    expect(title).toBe("<title>Invoice &lt;/title&gt;&lt;img src=x onerror=alert(1)&gt;</title>");
    expect(written[0]).not.toContain("<img src=x onerror");
  });

  it("offers GST 2.0 rates today, and the retired 12% and 28% only for an earlier invoice", async () => {
    renderPage();
    const rateOptions = () =>
      Array.from(document.querySelectorAll("select option")).map((o) => o.textContent);

    expect(rateOptions()).toContain("40%");
    expect(rateOptions()).not.toContain("12%");
    expect(rateOptions()).not.toContain("28%");

    const date = screen.getByLabelText("Invoice Date");
    await userEvent.clear(date);
    await userEvent.type(date, "2025-06-01");
    expect(rateOptions()).toContain("12%");
    expect(rateOptions()).toContain("28%");
  });

  it("renders FAQ section", () => {
    renderPage();
    expect(screen.getByText("Frequently Asked Questions")).toBeInTheDocument();
  });

  it("renders related tools", () => {
    renderPage();
    expect(screen.getByText("More Free GST Tools")).toBeInTheDocument();
  });
});
