import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import BulkGstinPage, { MAX_GSTINS, parseGstins, resultsCsv } from "./BulkGstinPage";

const mockBulk = vi.fn();
vi.mock("../lib/api", () => ({ api: { validateGstinBulk: (...a) => mockBulk(...a) } }));
const mockSave = vi.fn();
vi.mock("../lib/download", () => ({ saveBlob: (...a) => mockSave(...a) }));

const RESPONSE = {
  results: [
    { gstin: "27AAPFU0939F1ZV", valid: true, state_code: "27", state_name: "Maharashtra", pan: "AAPFU0939F" },
    { gstin: "29AAACB1234C1Z9", valid: false, error: "Check digit does not match." },
  ],
  total: 2,
  valid_count: 1,
  invalid_count: 1,
};

function renderPage() {
  return render(
    <MemoryRouter>
      <BulkGstinPage />
    </MemoryRouter>,
  );
}

const box = () => screen.getByRole("textbox", { name: "GSTINs" });

describe("parseGstins", () => {
  it("reads a spreadsheet column, a comma list, or both, once each", () => {
    expect(parseGstins(" 27aapfu0939f1zv\n29AAACB1234C1Z9, 27AAPFU0939F1ZV;\t\n")).toEqual([
      "27AAPFU0939F1ZV",
      "29AAACB1234C1Z9",
    ]);
    expect(parseGstins("   ")).toEqual([]);
  });
});

describe("resultsCsv", () => {
  it("writes one row per GSTIN and neutralises a formula", () => {
    const csv = resultsCsv([
      ...RESPONSE.results,
      { gstin: "=HYPERLINK(1)", valid: false, error: 'Not a GSTIN, "really"' },
    ]);
    const lines = csv.trim().split("\r\n");
    expect(lines[0]).toBe("GSTIN,Valid,State,State code,PAN,Reason");
    expect(lines[1]).toBe("27AAPFU0939F1ZV,Yes,Maharashtra,27,AAPFU0939F,");
    expect(lines[3]).toBe(`'=HYPERLINK(1),No,,,,"Not a GSTIN, ""really"""`);
  });
});

describe("BulkGstinPage", () => {
  beforeEach(() => {
    mockBulk.mockReset();
    mockSave.mockReset();
  });
  afterEach(() => vi.restoreAllMocks());

  it("counts what was pasted and sends each GSTIN once", async () => {
    mockBulk.mockResolvedValue(RESPONSE);
    renderPage();
    await userEvent.type(box(), "27AAPFU0939F1ZV\n29AAACB1234C1Z9\n27aapfu0939f1zv");
    expect(screen.getByText(/2 of 100/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Validate 2 GSTINs" }));
    expect(mockBulk).toHaveBeenCalledWith(["27AAPFU0939F1ZV", "29AAACB1234C1Z9"]);
  });

  it("shows each result, the totals, and why an invalid one failed", async () => {
    mockBulk.mockResolvedValue(RESPONSE);
    renderPage();
    await userEvent.type(box(), "27AAPFU0939F1ZV 29AAACB1234C1Z9");
    await userEvent.click(screen.getByRole("button", { name: /validate/i }));

    expect(await screen.findByText(/valid,/)).toHaveTextContent("1 valid, 1 invalid, of 2 checked.");
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("Maharashtra (27)");
    expect(rows[1]).toHaveTextContent("Check digit does not match.");
  });

  it("filters to the invalid ones and downloads all of them", async () => {
    mockBulk.mockResolvedValue(RESPONSE);
    renderPage();
    await userEvent.type(box(), "27AAPFU0939F1ZV 29AAACB1234C1Z9");
    await userEvent.click(screen.getByRole("button", { name: /validate/i }));
    await userEvent.click(await screen.findByRole("button", { name: "Invalid only" }));
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(2);

    await userEvent.click(screen.getByRole("button", { name: "Download CSV" }));
    const [blob, name] = mockSave.mock.calls[0];
    expect(name).toBe("gstin-validation.csv");
    // jsdom's Blob has no text(); FileReader reads it the same way.
    const text = await new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.readAsText(blob);
    });
    expect(text.trim().split("\r\n")).toHaveLength(3);
  });

  it("refuses more than the limit before sending anything", async () => {
    renderPage();
    const many = Array.from({ length: MAX_GSTINS + 1 }, (_, i) => `27AAPFU${String(i).padStart(4, "0")}F1ZV`);
    await userEvent.click(box());
    await userEvent.paste(many.join("\n"));
    expect(screen.getByRole("alert")).toHaveTextContent(/at most 100/);
    expect(screen.getByRole("button", { name: /validate/i })).toBeDisabled();
    expect(mockBulk).not.toHaveBeenCalled();
  });

  it("offers the plans to a business without one, instead of an error", async () => {
    mockBulk.mockRejectedValue(Object.assign(new Error("This feature requires a paid subscription."), { status: 403 }));
    renderPage();
    await userEvent.type(box(), "27AAPFU0939F1ZV");
    await userEvent.click(screen.getByRole("button", { name: /validate/i }));
    expect(await screen.findByRole("link", { name: "See plans" })).toHaveAttribute("href", "/pricing");
    expect(screen.getByRole("link", { name: "GSTIN validator" })).toHaveAttribute("href", "/gstin-validator");
  });

  it("says what went wrong for any other failure", async () => {
    mockBulk.mockRejectedValue(Object.assign(new Error("Too many requests (429)."), { status: 429 }));
    renderPage();
    await userEvent.type(box(), "27AAPFU0939F1ZV");
    await userEvent.click(screen.getByRole("button", { name: /validate/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many requests (429).");
  });
});
