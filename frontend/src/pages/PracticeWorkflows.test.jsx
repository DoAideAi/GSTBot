import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StubAuth } from "../test/auth";
import { api } from "../lib/api";
import PurchaseImportPage from "./PurchaseImportPage";
import ClientAccessPage from "./ClientAccessPage";
import JoinClientPage from "./JoinClientPage";
import ReviewWorkbenchPage from "./ReviewWorkbenchPage";
import ClientsPage from "./ClientsPage";

const PREVIEW = {
  id: 3,
  headers: ["Number"],
  fields: ["invoice_number"],
  required: ["invoice_number"],
  mapping: { invoice_number: "Number" },
  ready: 1,
  invalid: 1,
  duplicates: 0,
  rows: [
    { row: 2, data: { invoice_number: "A" }, errors: [], duplicate: false },
    {
      row: 3,
      data: { invoice_number: "B" },
      errors: ["Invalid GSTIN"],
      duplicate: false,
    },
  ],
};
const REVIEW = {
  run_id: 7,
  period: "2026-04",
  stale: false,
  unresolved: 1,
  approved: false,
  reviews: [],
  reviewers: [{ id: 1, name: "Accountant" }],
  events: [],
  findings: [
    {
      category: "missing_in_2b",
      invoice_number: "INV-7",
      books: { total_tax: "180" },
    },
  ],
};
function mount(component, role = "owner", path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <StubAuth role={role}>{component}</StubAuth>
    </MemoryRouter>,
  );
}

describe("CA workflows", () => {
  beforeEach(() => {
    vi.spyOn(api, "registerMappings").mockResolvedValue({ items: [] });
    vi.spyOn(api, "previewRegister").mockResolvedValue(PREVIEW);
    vi.spyOn(api, "commitRegister").mockResolvedValue({
      imported: 1,
      duplicates_skipped: 0,
      invalid_skipped: 1,
    });
    vi.spyOn(api, "invitations").mockResolvedValue({ items: [] });
    vi.spyOn(api, "clientMembers").mockResolvedValue({ items: [] });
    vi.spyOn(api, "createInvitation").mockResolvedValue({
      token: "a".repeat(43),
    });
    vi.spyOn(api, "reviewWorkbench").mockResolvedValue(REVIEW);
    vi.spyOn(api, "saveFindingReview").mockResolvedValue({});
    vi.spyOn(api, "approveReviewedReport").mockResolvedValue({});
    vi.spyOn(api, "practiceClients").mockResolvedValue({
      items: [
        {
          id: 1,
          name: "Client One",
          purchase_count: 0,
          has_2b: false,
          run_id: null,
          unresolved: null,
          next_action: "Import purchases",
        },
      ],
      total: 1,
    });
  });
  afterEach(() => vi.restoreAllMocks());

  it("requires a preview and explicit consent before skipping invalid rows", async () => {
    mount(<PurchaseImportPage />);
    expect(api.previewRegister).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Purchase register"), {
      target: {
        files: [new File(["data"], "register.csv", { type: "text/csv" })],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview register" }));
    const commit = await screen.findByRole("button", {
      name: "Import 1 invoices",
    });
    expect(commit).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(commit).toBeEnabled();
    fireEvent.click(commit);
    expect(await screen.findByText("1 invoices imported.")).toBeInTheDocument();
    expect(api.commitRegister).toHaveBeenCalledWith(3, {
      skip_invalid: true,
      save_mapping_name: null,
    });
  });

  it("requires another preview after changing a mapping", async () => {
    mount(<PurchaseImportPage />);
    fireEvent.change(screen.getByLabelText("Purchase register"), {
      target: { files: [new File(["data"], "r.csv")] },
    });
    fireEvent.click(screen.getByText("Preview register"));
    await screen.findByText("2. Match your columns");
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.change(screen.getByLabelText("invoice number *"), {
      target: { value: "" },
    });
    expect(
      screen.getByRole("button", { name: "Import 1 invoices" }),
    ).toBeDisabled();
    expect(screen.getByText(/Mapping changed/)).toBeInTheDocument();
  });

  it("does not offer uploads to a viewer", () => {
    mount(<PurchaseImportPage />, "viewer");
    expect(screen.getByLabelText("Purchase register")).toBeDisabled();
  });

  it("shows a failed import without claiming that invoices were imported", async () => {
    api.commitRegister.mockRejectedValueOnce(
      new Error("No invoice places remain."),
    );
    mount(<PurchaseImportPage />);
    fireEvent.change(screen.getByLabelText("Purchase register"), {
      target: { files: [new File(["data"], "r.csv")] },
    });
    fireEvent.click(screen.getByText("Preview register"));
    await screen.findByText("2. Match your columns");
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Import 1 invoices" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No invoice places remain.",
    );
    expect(screen.queryByText("1 invoices imported.")).not.toBeInTheDocument();
  });

  it("creates a shareable invitation without pretending an email was sent", async () => {
    mount(<ClientAccessPage />);
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "reviewer@example.com" },
    });
    fireEvent.click(screen.getByText("Create invitation link"));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "No email has been sent.",
    );
    expect(screen.getByLabelText("Invitation link").value).toContain("/join#");
    expect(api.createInvitation).toHaveBeenCalledWith({
      email: "reviewer@example.com",
      role: "accountant",
    });
  });

  it("limits invitation management to owners", () => {
    mount(<ClientAccessPage />, "accountant");
    expect(screen.getByText("Ask the business owner")).toBeInTheDocument();
    expect(api.invitations).not.toHaveBeenCalled();
  });

  it("blocks an invitation addressed to a different signed-in email", async () => {
    vi.spyOn(api, "inspectInvitation").mockResolvedValue({
      business_name: "Client Two",
      email: "someone@example.com",
      role: "viewer",
    });
    mount(<JoinClientPage />, "owner", `/join#${"a".repeat(43)}`);
    expect(
      await screen.findByText(/Switch to the invited email/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Accept viewer access")).not.toBeInTheDocument();
  });

  it("records a versioned review and never silently approves the report", async () => {
    mount(
      <Routes>
        <Route path="/review/:runId" element={<ReviewWorkbenchPage />} />
      </Routes>,
      "owner",
      "/review/7",
    );
    fireEvent.click(await screen.findByText(/INV-7/));
    fireEvent.change(screen.getByLabelText("Review status"), {
      target: { value: "resolved" },
    });
    fireEvent.change(screen.getByLabelText("Decision"), {
      target: { value: "accept_match" },
    });
    fireEvent.change(screen.getByLabelText("Evidence and resolution note"), {
      target: { value: "Evidence checked" },
    });
    fireEvent.click(screen.getByText("Save review"));
    await waitFor(() =>
      expect(api.saveFindingReview).toHaveBeenCalledWith("7", 0, {
        version: 0,
        status: "resolved",
        decision: "accept_match",
        assignee_id: null,
        note: "Evidence checked",
      }),
    );
    expect(api.approveReviewedReport).not.toHaveBeenCalled();
  });

  it("blocks review and export when the underlying data changed", async () => {
    api.reviewWorkbench.mockResolvedValue({
      ...REVIEW,
      stale: true,
      approved: true,
    });
    mount(
      <Routes>
        <Route path="/review/:runId" element={<ReviewWorkbenchPage />} />
      </Routes>,
      "owner",
      "/review/7",
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "source data changed",
    );
    fireEvent.click(screen.getByText(/INV-7/));
    expect(screen.getByText("Save review")).toBeDisabled();
    expect(screen.getByText("Export reviewed CSV")).toBeDisabled();
  });

  it("shows missing client inputs without treating unknown results as zero exceptions", async () => {
    mount(<ClientsPage />);
    expect(await screen.findByText("Client One")).toBeInTheDocument();
    expect(screen.getByText("Not reconciled")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Import purchases" }),
    ).toBeInTheDocument();
  });
});
