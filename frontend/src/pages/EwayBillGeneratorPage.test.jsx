import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import EwayBillGeneratorPage, { FAQ_SCHEMA } from "./EwayBillGeneratorPage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("../lib/share", () => ({
  fullUrl: (p) => `http://localhost${p}`,
  whatsappUrl: () => "https://wa.me/",
  twitterUrl: () => "https://twitter.com/",
  copyToClipboard: vi.fn().mockResolvedValue(true),
}));
vi.mock("../lib/api", () => ({ api: { subscribe: vi.fn() } }));
vi.mock("../lib/track", () => ({ track: () => {} }));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/eway-bill-generator"]}>
      <EwayBillGeneratorPage />
    </MemoryRouter>,
  );
}

async function fillParties(user, recipientGstin = "29AABCU9603R1ZM") {
  await user.type(screen.getByLabelText("Supplier name"), "Acme Traders");
  await user.type(screen.getByLabelText("Supplier GSTIN"), "27AAPFU0939F1ZV");
  await user.type(screen.getByLabelText("Recipient name"), "Bharat Stores");
  if (recipientGstin) await user.type(screen.getByLabelText("Recipient GSTIN"), recipientGstin);
  await user.type(screen.getByLabelText("Document number"), "INV-001");
}

describe("EwayBillGeneratorPage", () => {
  it("says nothing about requirement until there is a value", () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "E-Way Bill Generator" })).toBeInTheDocument();
    expect(screen.queryByText("Required")).toBeNull();
  });

  it("an inter-state consignment over ₹50,000 needs a bill and is taxed as IGST", async () => {
    const user = userEvent.setup();
    renderPage();
    await fillParties(user);
    await user.type(screen.getByLabelText("Taxable value (₹)"), "50000");

    expect(screen.getByText("(Inter-state — IGST)")).toBeInTheDocument();
    expect(screen.getByText("Required")).toBeInTheDocument();
    const draft = screen.getByRole("region", { name: "E-way bill draft" });
    expect(within(draft).getByText(/Total consignment value: ₹59,000/)).toBeInTheDocument();
    expect(within(draft).getByText(/IGST ₹9,000/)).toBeInTheDocument();
  });

  it("a same-state consignment of exactly ₹50,000 with tax needs no bill and splits CGST+SGST", async () => {
    const user = userEvent.setup();
    renderPage();
    await fillParties(user, "27AABCU9603R1ZX");
    await user.selectOptions(screen.getByLabelText("GST rate"), "0");
    await user.type(screen.getByLabelText("Taxable value (₹)"), "50000");

    expect(screen.getByText("(Intra-state — CGST+SGST)")).toBeInTheDocument();
    expect(screen.getByText("Not required")).toBeInTheDocument();
    expect(screen.getByText(/does not exceed ₹50,000/)).toBeInTheDocument();
  });

  it("validity is a day per 200 km, ending at midnight of the last day", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText("Taxable value (₹)"), "100000");
    await user.type(screen.getByLabelText("Approximate distance (km)"), "450");
    await user.clear(screen.getByLabelText("Generation date"));
    await user.type(screen.getByLabelText("Generation date"), "2026-10-05");

    expect(screen.getByText("3 days, until midnight 2026-10-08")).toBeInTheDocument();
    await user.click(screen.getByLabelText(/Over-dimensional cargo/));
    expect(screen.getByText(/23 days/)).toBeInTheDocument();
  });

  it("a distance too large for any calendar does not take the page down", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText("Taxable value (₹)"), "100000");
    await user.type(screen.getByLabelText("Approximate distance (km)"), "1e12");

    expect(screen.getByLabelText("Approximate distance (km)")).toBeInTheDocument();
    expect(screen.queryByText(/until midnight/)).not.toBeInTheDocument();
  });

  it("an unregistered recipient appears as URP on the draft", async () => {
    const user = userEvent.setup();
    renderPage();
    await fillParties(user, "");
    await user.click(screen.getByLabelText("Unregistered recipient (URP)"));
    await user.selectOptions(screen.getByLabelText("Recipient state"), "27");
    await user.type(screen.getByLabelText("Taxable value (₹)"), "60000");

    expect(screen.getByLabelText("Recipient GSTIN")).toHaveValue("URP");
    const draft = screen.getByRole("region", { name: "E-way bill draft" });
    expect(within(draft).getByText(/Bharat Stores, GSTIN URP/)).toBeInTheDocument();
  });

  it("rail, air and ship ask for a transport document instead of a vehicle", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText("Vehicle number"), "TRUCK");
    expect(screen.getByText(/does not look like a registration number/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Mode"), "rail");
    expect(screen.queryByLabelText("Vehicle number")).toBeNull();
    expect(screen.getByLabelText(/Transport document number/)).toBeInTheDocument();
  });

  it("a malformed transporter ID is flagged", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText(/Transporter ID/), "12345");
    expect(screen.getByRole("alert")).toHaveTextContent(/15 characters/);
  });

  it("items can be added and removed", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByText("+ Add item"));
    expect(screen.getAllByRole("group", { name: /^Item / })).toHaveLength(2);
    await user.click(screen.getAllByText("Remove")[0]);
    expect(screen.getAllByRole("group", { name: /^Item / })).toHaveLength(1);
  });

  it("flags an HSN shorter than the portal accepts", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText("HSN"), "94");
    expect(screen.getByText(/at least 4 HSN digits/)).toBeInTheDocument();
  });

  it("a complete draft carries every Part A and Part B field entered", async () => {
    const user = userEvent.setup();
    renderPage();
    await fillParties(user);
    await user.type(screen.getByLabelText("Supplier address"), "Pune");
    await user.type(screen.getByLabelText("Recipient address"), "Bengaluru");
    await user.selectOptions(screen.getByLabelText("Document type"), "Delivery Challan");
    await user.clear(screen.getByLabelText("Document date"));
    await user.type(screen.getByLabelText("Document date"), "2026-10-20");
    await user.click(screen.getByText("+ Add item"));
    const [first, second] = screen.getAllByRole("group", { name: /^Item / });
    await user.type(within(first).getByLabelText("Description"), "Steel chairs");
    await user.clear(within(first).getByLabelText("Quantity"));
    await user.type(within(first).getByLabelText("Quantity"), "40");
    await user.type(within(first).getByLabelText("Taxable value (₹)"), "60000");
    await user.type(within(second).getByLabelText("Taxable value (₹)"), "-5");
    await user.selectOptions(screen.getByLabelText("Mode"), "rail");
    await user.type(screen.getByLabelText(/Transport document number/), "RR-7781");
    await user.type(screen.getByLabelText("Approximate distance (km)"), "840");

    const draft = screen.getByRole("region", { name: "E-way bill draft" });
    expect(within(draft).getByText(/Acme Traders, GSTIN 27AAPFU0939F1ZV, Pune/)).toBeInTheDocument();
    expect(within(draft).getByText(/Bharat Stores, GSTIN 29AABCU9603R1ZM, Bengaluru/)).toBeInTheDocument();
    expect(within(draft).getByText("Document: Delivery Challan INV-001 dated 2026-10-20")).toBeInTheDocument();
    expect(within(draft).getByText("Steel chairs")).toBeInTheDocument();
    expect(within(draft).getByText(/Total consignment value: ₹70,800/)).toBeInTheDocument();
    expect(within(draft).getByText("Transport document: RR-7781")).toBeInTheDocument();
    expect(within(draft).getByText("Distance: 840 km")).toBeInTheDocument();
  });

  it("blank Part B fields show as dashes on the draft", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText("Supplier name"), "Acme Traders");
    await user.type(screen.getByLabelText("Recipient name"), "Bharat Stores");
    await user.type(screen.getByLabelText("Document number"), "INV-002");
    await user.type(screen.getByLabelText("Taxable value (₹)"), "1000");

    const draft = screen.getByRole("region", { name: "E-way bill draft" });
    expect(within(draft).getByText("Supplier: Acme Traders, GSTIN —")).toBeInTheDocument();
    expect(within(draft).getByText("Recipient: Bharat Stores, GSTIN —")).toBeInTheDocument();
    expect(within(draft).getByText("Vehicle number: —")).toBeInTheDocument();
    expect(within(draft).getByText("Distance: —")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Mode"), "air");
    expect(within(draft).getByText("Transport document: —")).toBeInTheDocument();
  });

  it("the visible FAQ is the one in the JSON-LD", () => {
    renderPage();
    for (const q of FAQ_SCHEMA.mainEntity) {
      expect(screen.getByRole("heading", { name: q.name })).toBeInTheDocument();
    }
  });
});
