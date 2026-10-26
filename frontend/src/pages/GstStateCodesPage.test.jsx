import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { STATE_CODES } from "../lib/stateCodes";
import GstStateCodesPage, { FAQS } from "./GstStateCodesPage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/gst-state-codes"]}>
      <GstStateCodesPage />
    </MemoryRouter>,
  );
}

describe("GstStateCodesPage", () => {
  it("lists every state code in the table", () => {
    renderPage();
    const table = screen.getByRole("region", { name: "GST state code table" });
    expect(within(table).getAllByRole("row")).toHaveLength(STATE_CODES.length + 1);
    const ladakh = within(table).getByText("Ladakh").closest("tr");
    expect(ladakh).toHaveTextContent("38");
    expect(ladakh).toHaveTextContent("CGST + UTGST");
  });

  it("names the state of a pasted GSTIN", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText("GSTIN or state code"), "29abcde1234f1z5");
    const answer = screen.getByText(/Intra-state supplies carry/).closest("p");
    expect(answer).toHaveTextContent("29 — Karnataka (State). Intra-state supplies carry CGST + SGST.");
  });

  it("says so when the prefix is not a state code", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText("GSTIN or state code"), "50");
    expect(screen.getByText(/does not start with a valid GST state code/)).toBeInTheDocument();
  });

  it("omits the tax line for codes without one", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText("GSTIN or state code"), "99");
    expect(screen.getByText(/Centre Jurisdiction \(/)).toBeInTheDocument();
    expect(screen.queryByText(/Intra-state supplies carry/)).not.toBeInTheDocument();
  });

  it("renders every FAQ", () => {
    renderPage();
    for (const f of FAQS) expect(screen.getByRole("heading", { name: f.q })).toBeInTheDocument();
  });
});
