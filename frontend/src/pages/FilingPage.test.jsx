import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { periodLabel, previousPeriod as prevPeriod } from "../lib/format";
import { StubAuth } from "../test/auth";
import FilingPage from "./FilingPage";

const PERIOD = "2026-04";

function validation(overrides = {}) {
  const issues = overrides.issues ?? [];
  return {
    period: PERIOD,
    ok: issues.every((issue) => issue.severity !== "error"),
    invoice_count: 3,
    error_count: issues.filter((issue) => issue.severity === "error").length,
    warning_count: issues.filter((issue) => issue.severity === "warning").length,
    ...overrides,
    issues,
  };
}

function gstr1(overrides = {}) {
  return {
    period: PERIOD,
    return_type: "gstr1",
    document: {
      gstin: "29AAGCB7383J1Z4",
      fp: "042026",
      version: "GST3.0.4",
      hash: "hash",
      b2b: [{ ctin: "29AAGCB7383J1Z5", inv: [{ inum: "INV-1" }] }],
    },
    validation: validation(),
    ...overrides,
  };
}

function gstr3b(overrides = {}) {
  return {
    period: PERIOD,
    return_type: "gstr3b",
    document: {
      gstin: "29AAGCB7383J1Z4",
      ret_period: "042026",
      gstbot_set_off: {
        steps: [],
        cash_payable: { igst: "2000.00", cgst: "0.00", sgst: "0.00", cess: "0.00", total: "2000.00" },
        credit_carried_forward: {
          igst: "500.00",
          cgst: "0.00",
          sgst: "0.00",
          cess: "0.00",
          total: "500.00",
        },
        credit_used: { igst: "18000.00", cgst: "0.00", sgst: "0.00", cess: "0.00", total: "18000.00" },
        total_cash: "2000.00",
      },
      gstbot_reverse_charge: {
        taxable_value: "0.00",
        tax: { igst: "0.00", cgst: "0.00", sgst: "0.00", cess: "0.00", total: "0.00" },
        credit: { igst: "0.00", cgst: "0.00", sgst: "0.00", cess: "0.00", total: "0.00" },
        invoice_count: 0,
        cash_payable: "0.00",
      },
      gstbot_cash_payable: "2000.00",
    },
    validation: validation(),
    ...overrides,
  };
}

function standing(overrides = {}) {
  return {
    period: PERIOD,
    return_type: "gstr1",
    due_date: "2026-05-11",
    filed: false,
    filed_on: null,
    arn: null,
    filed_late: false,
    days_until_due: 5,
    ...overrides,
  };
}

function filingStatus(items = []) {
  return { as_of: "2026-05-06", items };
}

/**
 * The late-fee answer, defaulting to a return that is not late at all.
 *
 * Zero days is what every existing test on this page is entitled to see — none
 * of them are about a missed deadline — so the panel stays absent unless a test
 * asks for it, and a default that owed money would put an unexpected figure
 * into assertions about the return itself.
 */
function lateFee(overrides = {}) {
  return {
    period: PERIOD,
    return_type: "gstr1",
    due_date: "2026-05-11",
    as_of: "2026-05-06",
    filed_on: null,
    days_late: 0,
    projected: true,
    is_nil: false,
    net_tax_liability: "0.00",
    late_fee_cgst: "0.00",
    late_fee_sgst: "0.00",
    late_fee_total: "0.00",
    late_fee_tier: "upto_1_5_cr",
    interest: "0.00",
    total_payable: "0.00",
    ...overrides,
  };
}

/**
 * Route by URL rather than by call order: the page fires a preview fetch on
 * mount and again on every period or return-type change, so a queue of
 * responses would drift the moment a test changes one of them.
 */
function mockApi({
  gstr1: one = gstr1(),
  gstr3b: three = gstr3b(),
  status = 200,
  filingStatus: statusBody = filingStatus(),
  filingStatusStatus = 200,
  lateFee: lateFeeBody = lateFee(),
  lateFeeStatus = 200,
  onLateFee,
  onRecordFiled,
  recordFailure,
  exportFailure,
} = {}) {
  global.fetch = vi.fn(async (url, options) => {
    const href = String(url);

    // Before the preview fallback below, which matches on the return type
    // alone and would otherwise answer this with a whole GSTR-1.
    if (href.includes("/late-fee")) {
      onLateFee?.(href);
      const body =
        typeof lateFeeBody === "function" ? lateFeeBody(href) : lateFeeBody;
      return {
        ok: lateFeeStatus < 400,
        status: lateFeeStatus,
        statusText: lateFeeStatus < 400 ? "OK" : "Error",
        text: async () => JSON.stringify(body),
      };
    }
    if (href.includes("/filing/status")) {
      return {
        ok: filingStatusStatus < 400,
        status: filingStatusStatus,
        statusText: filingStatusStatus < 400 ? "OK" : "Error",
        text: async () => JSON.stringify(statusBody),
      };
    }
    if (/\/filing\/gstr(1|3b)\/filed$/.test(href)) {
      onRecordFiled?.({ url: href, body: JSON.parse(options?.body ?? "{}") });
      return {
        ok: !recordFailure,
        status: recordFailure?.status ?? 201,
        statusText: recordFailure ? "Error" : "Created",
        text: async () =>
          JSON.stringify(recordFailure?.body ?? { id: 1, period: PERIOD }),
      };
    }
    if (href.includes("/filing/export/")) {
      if (exportFailure) {
        return {
          ok: false,
          status: exportFailure.status ?? 500,
          statusText: "Error",
          text: async () => JSON.stringify(exportFailure.body ?? {}),
        };
      }
      return {
        ok: true,
        status: 200,
        statusText: "OK",
        blob: async () => new Blob(["{}"], { type: "application/json" }),
        headers: {
          get: () => 'attachment; filename="gstr1_29AAGCB7383J1Z4_042026.json"',
        },
      };
    }
    const body = String(url).includes("/filing/gstr3b") ? three : one;
    return {
      ok: status < 400,
      status,
      statusText: status < 400 ? "OK" : "Error",
      text: async () => JSON.stringify(body),
    };
  });
}

/**
 * Step the picker to a completed period that differs from the default.
 *
 * The picker opens on the previous month (already completed). This selects one
 * month further back so tests that need a period change see a real transition.
 */
async function selectCompletedPeriod(user) {
  const select = await screen.findByLabelText("Period");
  const target = select.options[2].value;
  await user.selectOptions(select, target);
  return target;
}

/**
 * Step the picker to the current month, which has not ended yet.
 *
 * The page now defaults to the previous month. Tests about the "period not
 * ended" guard need to move forward to the current month explicitly.
 */
async function selectCurrentPeriod(user) {
  const select = await screen.findByLabelText("Period");
  await user.selectOptions(select, select.options[0].value);
  return select.options[0].value;
}

function renderPage({ role } = {}) {
  return render(
    <MemoryRouter>
      <StubAuth role={role}>
        <FilingPage />
      </StubAuth>
    </MemoryRouter>,
  );
}

/** Resolves once a preview has replaced the loading placeholder. */
const loaded = () => screen.findByRole("heading", { name: "Export" });

/** The tiles repeat their figures further down, so assert against the tile. */
function statCard(container, label) {
  const card = [...container.querySelectorAll(".stat-card")].find(
    (node) => node.querySelector(".stat-label")?.textContent === label,
  );
  if (!card) throw new Error(`no stat card labelled "${label}"`);
  return card;
}

describe("FilingPage", () => {
  beforeEach(() => {
    localStorage.clear();
    // jsdom implements neither, and saveBlob calls both on every download.
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:mock"),
      revokeObjectURL: vi.fn(),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("reports a clean period as ready to file", async () => {
    mockApi();
    const { container } = renderPage();

    await loaded();
    expect(statCard(container, "Ready to file")).toHaveTextContent("Yes");
    expect(statCard(container, "Ready to file")).toHaveTextContent("Nothing blocking");
    expect(statCard(container, "Errors")).toHaveTextContent("0");
  });

  it("refuses to call a period with errors ready", async () => {
    mockApi({
      gstr1: gstr1({
        validation: validation({
          issues: [
            {
              invoice_id: 7,
              invoice_number: "INV-7",
              field: "counterparty_gstin",
              severity: "error",
              message: "29AAGCB7383J1Z9 is not a valid GSTIN",
            },
          ],
        }),
      }),
    });
    const { container } = renderPage();

    await loaded();
    expect(statCard(container, "Ready to file")).toHaveTextContent("No");
    expect(statCard(container, "Ready to file")).toHaveTextContent("1 to fix");
    expect(
      screen.getByText(/fix them before filing, or the portal will reject/i),
    ).toBeInTheDocument();
  });

  it("lists each validation issue against its invoice", async () => {
    mockApi({
      gstr1: gstr1({
        validation: validation({
          issues: [
            {
              invoice_id: 7,
              invoice_number: "INV-7",
              field: "counterparty_gstin",
              severity: "error",
              message: "29AAGCB7383J1Z9 is not a valid GSTIN",
            },
            {
              invoice_id: 8,
              invoice_number: "INV-8",
              field: "hsn_code",
              severity: "warning",
              message: "HSN code is missing",
            },
          ],
        }),
      }),
    });
    renderPage();

    await loaded();
    expect(screen.getByText("Error")).toBeInTheDocument();
    expect(screen.getByText("Warning")).toBeInTheDocument();
    // The field name is humanised rather than shown as a column name.
    expect(screen.getByText("counterparty gstin")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "INV-7" })).toHaveAttribute(
      "href",
      "/invoices/7",
    );
  });

  it("lists an issue about an invoice with no number, and one about no invoice", async () => {
    // Both shapes come out of the validator. An invoice whose number the
    // parser never read still has a GSTIN the portal will reject, and a
    // return-level issue — a period with no invoices at all, a GSTIN missing
    // from the business record — belongs to no invoice. A row that renders
    // blank for either is a defect the user is told about and cannot find.
    mockApi({
      gstr1: gstr1({
        validation: validation({
          issues: [
            {
              invoice_id: 9,
              invoice_number: null,
              field: "counterparty_gstin",
              severity: "error",
              message: "No supplier GSTIN was read from this invoice",
            },
            {
              invoice_id: null,
              invoice_number: null,
              field: "period",
              severity: "warning",
              message: "No invoices in this period",
            },
          ],
        }),
      }),
    });
    renderPage();

    await loaded();
    // The one with an invoice behind it is clickable under a stand-in label.
    expect(screen.getByRole("link", { name: "(no number)" })).toHaveAttribute(
      "href",
      "/invoices/9",
    );
    // The return-level one reads the same but has nowhere to go.
    expect(screen.getAllByText("(no number)")).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: "(no number)" })).toHaveLength(1);
  });

  it("says so plainly when there is nothing to fix", async () => {
    mockApi();
    renderPage();

    await loaded();
    expect(screen.getByText(/Nothing to fix/i)).toBeInTheDocument();
  });

  it("keeps the generated JSON hidden until it is asked for", async () => {
    const user = userEvent.setup();
    mockApi();
    renderPage();

    await loaded();
    expect(screen.queryByLabelText("Generated return JSON")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Show generated JSON/i }));
    const json = await screen.findByLabelText("Generated return JSON");
    expect(json).toHaveTextContent('"fp": "042026"');

    await user.click(screen.getByRole("button", { name: /Hide generated JSON/i }));
    expect(screen.queryByLabelText("Generated return JSON")).not.toBeInTheDocument();
  });

  it("fetches the other return when the type is switched", async () => {
    const user = userEvent.setup();
    mockApi();
    renderPage();

    await loaded();
    await user.click(screen.getByRole("button", { name: "GSTR-3B" }));

    await waitFor(() =>
      expect(global.fetch.mock.calls.at(-1)[0]).toContain("/filing/gstr3b"),
    );
    expect(screen.getByRole("button", { name: "GSTR-3B" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("shows what the credit leaves to pay, but only on GSTR-3B", async () => {
    const user = userEvent.setup();
    mockApi();
    renderPage();

    await loaded();
    expect(
      screen.queryByRole("heading", { name: "What this leaves to pay" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "GSTR-3B" }));

    const panel = (await screen.findByRole("heading", { name: "What this leaves to pay" }))
      .closest("section");
    expect(within(panel).getByText("₹2,000.00")).toBeInTheDocument();
    expect(within(panel).getByText("₹18,000.00")).toBeInTheDocument();
    expect(within(panel).getByText("₹500.00")).toBeInTheDocument();
  });

  it("counts the reverse-charge liability in the cash it asks for", async () => {
    // Credit cannot settle it, so it is not in the set-off's figure — and a
    // business reading only that one is told to find too little money.
    const user = userEvent.setup();
    const document = gstr3b();
    mockApi({
      gstr3b: {
        ...document,
        document: {
          ...document.document,
          gstbot_reverse_charge: {
            ...document.document.gstbot_reverse_charge,
            cash_payable: "9000.00",
          },
          gstbot_cash_payable: "11000.00",
        },
      },
    });
    renderPage();

    await loaded();
    await user.click(screen.getByRole("button", { name: "GSTR-3B" }));

    const panel = (await screen.findByRole("heading", { name: "What this leaves to pay" }))
      .closest("section");
    expect(within(panel).getByText("₹11,000.00")).toBeInTheDocument();
    expect(within(panel).getByText("₹9,000.00")).toBeInTheDocument();
  });

  it("falls back to the set-off's own figure when the combined one is absent", async () => {
    // `gstbot_cash_payable` and `gstbot_reverse_charge` are the later of the
    // two shapes this document has had. A return generated before them — one
    // being re-read from a stored preview — still has to render a cash figure
    // and a set-off panel rather than "₹0.00" under a heading asking what is
    // left to pay.
    const user = userEvent.setup();
    const document = gstr3b();
    mockApi({
      gstr3b: {
        ...document,
        document: {
          ...document.document,
          gstbot_cash_payable: null,
          gstbot_reverse_charge: null,
        },
      },
    });
    renderPage();

    await loaded();
    await user.click(screen.getByRole("button", { name: "GSTR-3B" }));

    const panel = (await screen.findByRole("heading", { name: "What this leaves to pay" }))
      .closest("section");
    expect(within(panel).getByText("₹2,000.00")).toBeInTheDocument();
    // And says nothing about a reverse charge it knows nothing about.
    expect(within(panel).queryByText("Of which reverse charge")).not.toBeInTheDocument();
  });

  it("downloads an export under the name the server gave it", async () => {
    const user = userEvent.setup();
    window.umami = { track: vi.fn() };
    mockApi();
    renderPage();

    await loaded();
    await user.click(screen.getByRole("button", { name: /Download GSTR-1 JSON/i }));

    expect(
      await screen.findByText("Downloaded gstr1_29AAGCB7383J1Z4_042026.json"),
    ).toBeInTheDocument();
    expect(global.fetch.mock.calls.at(-1)[0]).toContain("/filing/export/gstr1.json");
    expect(URL.createObjectURL).toHaveBeenCalled();
    // The object URL is released rather than leaked once the click is done.
    expect(URL.revokeObjectURL).toHaveBeenCalled();
    expect(window.umami.track).toHaveBeenCalledWith("filing_export", {
      return_type: "gstr1",
      format: "json",
    });
    delete window.umami;
  });

  it("says so when the export cannot be produced", async () => {
    // The download is the point of this screen: the JSON is what gets uploaded
    // to the portal, and a business that believes it has the file stops
    // looking for it. A failure that leaves the button enabled and the page
    // silent is indistinguishable from a browser that saved the file quietly —
    // right up to the deadline.
    const user = userEvent.setup();
    mockApi({ exportFailure: { status: 409, body: { detail: "Period is not yet complete" } } });
    renderPage();

    await loaded();
    await user.click(screen.getByRole("button", { name: /Download GSTR-1 JSON/i }));

    // The server's sentence is carried whole; what is added in front of it is
    // which return it was about, because none of these refusals say.
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("Period is not yet complete");
    expect(banner).toHaveTextContent(
      `Could not download the GSTR-1 for ${periodLabel(prevPeriod())}`,
    );
    // Nothing was handed to the browser to save.
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("lets the download be retried after one fails", async () => {
    // `busy` gates every button on the panel, so a failure that skipped the
    // reset would leave the screen with no way to try again short of a reload.
    const user = userEvent.setup();
    mockApi({ exportFailure: { status: 500, body: { detail: "Export failed" } } });
    renderPage();

    await loaded();
    await user.click(screen.getByRole("button", { name: /Download GSTR-1 JSON/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Export failed");
    expect(screen.getByRole("button", { name: /Download GSTR-1 JSON/i })).toBeEnabled();
  });

  it("asks for CSV separately from JSON", async () => {
    const user = userEvent.setup();
    mockApi();
    renderPage();

    await loaded();
    await user.click(screen.getByRole("button", { name: "Download CSV" }));

    await waitFor(() =>
      expect(global.fetch.mock.calls.at(-1)[0]).toContain("/filing/export/gstr1.csv"),
    );
  });

  it("surfaces an API failure", async () => {
    mockApi({ gstr1: { detail: "This business has been deactivated. Contact support to reactivate it." }, status: 403 });
    renderPage();

    expect(await screen.findByText("This business has been deactivated. Contact support to reactivate it.")).toBeInTheDocument();
  });

  it("reloads when the period changes", async () => {
    const user = userEvent.setup();
    mockApi();
    renderPage();

    await loaded();
    const select = screen.getByLabelText("Period");
    // A month different from the default (previous month), to trigger a reload.
    const other = select.options[2].value;
    await user.selectOptions(select, other);

    await waitFor(() =>
      expect(global.fetch.mock.calls.at(-1)[0]).toContain(`period=${other}`),
    );
  });

  describe("recording that a return was filed", () => {
    /**
     * Nothing in this product can observe a submission to the portal, so the
     * deadline alerting has only this record to go on. Until it existed there
     * was no way to say so from the app at all — the endpoint was live and
     * unreachable — which left every business permanently overdue on returns
     * they had already filed.
     */
    const markFiled = () => screen.findByRole("button", { name: /Mark GSTR-1 as filed/i });

    it("sends the period and return type the picker is showing", async () => {
      const user = userEvent.setup();
      const onRecordFiled = vi.fn();
      mockApi({ onRecordFiled });
      renderPage();

      const period = await selectCompletedPeriod(user);
      await user.click(await markFiled());

      await waitFor(() => expect(onRecordFiled).toHaveBeenCalled());
      const { url, body } = onRecordFiled.mock.calls[0][0];
      expect(url).toContain("/filing/gstr1/filed");
      expect(body.period).toBe(period);
    });

    it("records the return type the toggle is on, not the one it started on", async () => {
      const user = userEvent.setup();
      const onRecordFiled = vi.fn();
      mockApi({ onRecordFiled });
      renderPage();

      await loaded();
      await selectCompletedPeriod(user);
      await user.click(screen.getByRole("button", { name: "GSTR-3B" }));
      await user.click(await screen.findByRole("button", { name: /Mark GSTR-3B as filed/i }));

      await waitFor(() => expect(onRecordFiled).toHaveBeenCalled());
      expect(onRecordFiled.mock.calls[0][0].url).toContain("/filing/gstr3b/filed");
    });

    it("sends an ARN when one is typed, upper-cased and without spaces", async () => {
      const user = userEvent.setup();
      window.umami = { track: vi.fn() };
      const onRecordFiled = vi.fn();
      mockApi({ onRecordFiled });
      renderPage();

      await selectCompletedPeriod(user);
      await user.type(
        await screen.findByLabelText(/ARN/i),
        "aa2704 26000000 x",
      );
      await user.click(await markFiled());

      await waitFor(() => expect(onRecordFiled).toHaveBeenCalled());
      expect(onRecordFiled.mock.calls[0][0].body.arn).toBe("AA270426000000X");
      // Whether an ARN was given, not the ARN: it identifies the filing.
      await waitFor(() =>
        expect(window.umami.track).toHaveBeenCalledWith("return_recorded_filed", {
          return_type: "gstr1",
          with_arn: true,
        }),
      );
      delete window.umami;
    });

    it("omits the ARN entirely rather than sending an empty one", async () => {
      const user = userEvent.setup();
      const onRecordFiled = vi.fn();
      mockApi({ onRecordFiled });
      renderPage();

      await selectCompletedPeriod(user);
      await user.click(await markFiled());

      await waitFor(() => expect(onRecordFiled).toHaveBeenCalled());
      // On the server an absent ARN means "not to hand" and leaves a stored one
      // alone; an empty string is not an ARN and would be refused.
      expect(onRecordFiled.mock.calls[0][0].body).not.toHaveProperty("arn");
    });

    it("refuses something that is plainly not an ARN before sending it", async () => {
      const user = userEvent.setup();
      const onRecordFiled = vi.fn();
      mockApi({ onRecordFiled });
      renderPage();

      await selectCompletedPeriod(user);
      await user.type(await screen.findByLabelText(/ARN/i), "AB12");
      await user.click(await markFiled());

      expect(await screen.findByRole("alert")).toHaveTextContent(/does not look like an ARN/i);
      expect(onRecordFiled).not.toHaveBeenCalled();
    });

    it("clears the ARN complaint as soon as the field is corrected", async () => {
      // The message sits under the field and is about what is in it. Left up
      // while someone retypes, it reads as a standing refusal of the value
      // they are looking at — and the submit that would clear it is the very
      // thing the message is telling them not to press.
      const user = userEvent.setup();
      mockApi({ onRecordFiled: vi.fn() });
      renderPage();

      await selectCompletedPeriod(user);
      const field = await screen.findByLabelText(/ARN/i);
      await user.type(field, "AB12");
      await user.click(await markFiled());
      await screen.findByRole("alert");

      await user.type(field, "3456789012");

      await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
      expect(field).not.toHaveAttribute("aria-invalid");
    });

    it("names a recorded filing whose acknowledgement was never supplied", async () => {
      // The ARN is optional on purpose — it is often not to hand at the moment
      // someone marks a return done. The sentence still has to read as a
      // sentence, without a dangling "(ARN )".
      mockApi({
        filingStatus: filingStatus([
          standing({ period: prevPeriod(), filed: true, filed_on: "2026-05-09", arn: null }),
        ]),
      });
      renderPage();

      const note = await screen.findByText(/Already recorded as filed on/i);
      expect(note).not.toHaveTextContent("ARN");
      expect(note).toHaveTextContent(/corrects the reference rather than filing twice/);
    });

    it("confirms the filing by naming its own period", async () => {
      const user = userEvent.setup();
      mockApi();
      renderPage();

      await selectCompletedPeriod(user);
      await user.click(await markFiled());

      expect(await screen.findByRole("status")).toHaveTextContent(/Recorded GSTR-1 for/i);
    });

    it("refetches the status so the panel stops calling it outstanding", async () => {
      const user = userEvent.setup();
      mockApi();
      renderPage();

      await loaded();
      await selectCompletedPeriod(user);
      const before = global.fetch.mock.calls.filter((call) =>
        String(call[0]).includes("/filing/status"),
      ).length;

      await user.click(await markFiled());

      await waitFor(() => {
        const after = global.fetch.mock.calls.filter((call) =>
          String(call[0]).includes("/filing/status"),
        ).length;
        expect(after).toBeGreaterThan(before);
      });
    });

    it("reports a refusal from the server rather than claiming success", async () => {
      const user = userEvent.setup();
      mockApi({
        recordFailure: {
          status: 422,
          body: { detail: "2026-04 could not have been filed on 2026-04-02." },
        },
      });
      renderPage();

      await selectCompletedPeriod(user);
      await user.click(await markFiled());

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "2026-04 could not have been filed on 2026-04-02.",
      );
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });

    it("does not offer to record a month that has not ended", async () => {
      // The picker defaults to the previous month (completed), so switch to
      // the current month to test the guard.
      const user = userEvent.setup();
      mockApi();
      renderPage();

      await loaded();
      await selectCurrentPeriod(user);

      expect(await markFiled()).toBeDisabled();
      expect(screen.getByLabelText(/ARN/i)).toBeDisabled();
      expect(screen.getByText(/has not ended yet, so there is nothing to record/i))
        .toBeInTheDocument();
    });

    it("offers it again as soon as a completed period is picked", async () => {
      const user = userEvent.setup();
      mockApi();
      renderPage();

      await loaded();
      await selectCurrentPeriod(user);
      await selectCompletedPeriod(user);

      expect(await markFiled()).toBeEnabled();
      expect(
        screen.queryByText(/has not ended yet, so there is nothing to record/i),
      ).not.toBeInTheDocument();
    });
  });

  describe("the filing status panel", () => {
    it("shows each period's standing, due date and reference", async () => {
      mockApi({
        filingStatus: filingStatus([
          standing({
            filed: true,
            filed_on: "2026-05-09",
            arn: "AA270426000000X",
            days_until_due: 2,
          }),
          standing({ return_type: "gstr3b", due_date: "2026-05-20", days_until_due: -4 }),
        ]),
      });
      renderPage();

      const table = await screen.findByRole("region", { name: "Filing status by period" });
      expect(within(table).getByText("Filed")).toBeInTheDocument();
      expect(within(table).getByText("AA270426000000X")).toBeInTheDocument();
      expect(within(table).getByText("Overdue by 4d")).toBeInTheDocument();
    });

    it("counts down a return that is still inside its deadline", async () => {
      // The standing every return has for most of its life, and the only one
      // no test rendered: each case above either filed the return or let it go
      // overdue, so the chip a user actually sees on the filing screen most
      // days was the one branch of `standingChip` nothing executed.
      mockApi({
        filingStatus: filingStatus([standing({ days_until_due: 5 })]),
      });
      renderPage();

      const table = await screen.findByRole("region", { name: "Filing status by period" });
      expect(within(table).getByText("Due in 5d")).toBeInTheDocument();
      expect(within(table).queryByText(/Overdue/)).not.toBeInTheDocument();
    });

    it("does not call a return overdue on the day it is due", async () => {
      // The boundary between the two unfiled chips. A return due today is
      // still filable today — the portal accepts it until midnight — so
      // rounding zero into the overdue branch would tell a business it had
      // already missed a deadline it has hours left to meet, and the late fee
      // it implies is ₹50 a day it does not yet owe.
      mockApi({
        filingStatus: filingStatus([standing({ days_until_due: 0 })]),
      });
      renderPage();

      const table = await screen.findByRole("region", { name: "Filing status by period" });
      expect(within(table).getByText("Due in 0d")).toBeInTheDocument();
      expect(within(table).queryByText(/Overdue/)).not.toBeInTheDocument();
    });

    it("names a return type this build does not know, rather than blanking the cell", async () => {
      // The status table lists whatever the server tracks. GSTR-9 or a CMP-08
      // added there before this screen learns to preview it must still appear
      // with its period and due date — the table is what says a deadline is
      // coming, and a row with no return name on it says nothing at all.
      mockApi({
        filingStatus: filingStatus([
          standing({ return_type: "gstr9", due_date: "2026-12-31", days_until_due: 200 }),
        ]),
      });
      renderPage();

      const table = await screen.findByRole("region", { name: "Filing status by period" });
      expect(within(table).getByText("GSTR9")).toBeInTheDocument();
      expect(within(table).getByText("31 Dec 2026")).toBeInTheDocument();
    });

    it("marks a return filed after its due date as late rather than on time", async () => {
      mockApi({
        filingStatus: filingStatus([
          standing({ filed: true, filed_on: "2026-05-19", filed_late: true }),
        ]),
      });
      renderPage();

      const table = await screen.findByRole("region", { name: "Filing status by period" });
      expect(within(table).getByText("Filed late")).toBeInTheDocument();
      expect(within(table).queryByText("Filed")).not.toBeInTheDocument();
    });

    it("says a period is already recorded rather than offering it blind", async () => {
      mockApi({
        filingStatus: filingStatus([
          standing({
            period: prevPeriod(),
            filed: true,
            filed_on: "2026-05-09",
            arn: "AA270426000000X",
          }),
        ]),
      });
      renderPage();

      expect(
        await screen.findByText(/Already recorded as filed on/i),
      ).toHaveTextContent("AA270426000000X");
    });

    it("keeps the export working when the status panel cannot load", async () => {
      // The page's job is preparing a return. A status panel that 500s must not
      // make the export buttons look broken, or put a banner over a page that
      // is working.
      mockApi({ filingStatusStatus: 500 });
      renderPage();

      await loaded();
      expect(
        screen.getByRole("button", { name: /Download GSTR-1 JSON/i }),
      ).toBeEnabled();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(
        screen.queryByRole("region", { name: "Filing status by period" }),
      ).not.toBeInTheDocument();
    });
  });

  describe("when answers come back out of order", () => {
    /**
     * A fetch that hands back the levers instead of resolving on its own.
     *
     * The bug here is an ordering one, so the test has to be able to answer the
     * second request before the first. A mock that resolves by itself can only
     * ever answer them in order, which is the one case that was never broken.
     */
    function deferredFetch() {
      const pending = [];
      global.fetch = vi.fn(
        (url, options = {}) =>
          new Promise((resolve, reject) => {
            // The filing-status panel fetches independently of the picker, so
            // it is answered immediately and kept out of `pending`. The
            // ordering under test is between the two *previews*; queueing an
            // unrelated third request here would only shift every index.
            //
            // The late fee does follow the picker, and so is a genuine second
            // ordering problem — but it is not this one, and it has its own
            // test. Answered here rather than queued for the same reason: these
            // tests index into `pending` to answer the second request before the
            // first, and an extra entry per change moves every index they name.
            if (String(url).includes("/filing/status")) {
              resolve({
                ok: true,
                status: 200,
                statusText: "OK",
                text: async () => JSON.stringify(filingStatus()),
              });
              return;
            }
            if (String(url).includes("/late-fee")) {
              resolve({
                ok: true,
                status: 200,
                statusText: "OK",
                text: async () => JSON.stringify(lateFee()),
              });
              return;
            }
            pending.push({
              url: String(url),
              signal: options.signal,
              answer: (body) =>
                resolve({
                  ok: true,
                  status: 200,
                  statusText: "OK",
                  text: async () => JSON.stringify(body),
                }),
            });
            // An aborted fetch does not resolve with a partial answer; it
            // rejects with an AbortError, so the mock has to as well.
            options.signal?.addEventListener("abort", () => {
              const err = new Error("The operation was aborted.");
              err.name = "AbortError";
              reject(err);
            });
          }),
      );
      return pending;
    }

    it("abandons the preview the other return type supersedes", async () => {
      const user = userEvent.setup();
      const pending = deferredFetch();
      renderPage();

      await waitFor(() => expect(pending).toHaveLength(1));
      pending[0].answer(gstr1());
      await loaded();

      await user.click(screen.getByRole("button", { name: "GSTR-3B" }));
      await waitFor(() => expect(pending).toHaveLength(2));

      expect(pending[0].url).toContain("/filing/gstr1");
      expect(pending[0].signal.aborted).toBe(true);
      expect(pending[1].url).toContain("/filing/gstr3b");
      expect(pending[1].signal.aborted).toBe(false);
    });

    it("does not preview one return while offering to file the other", async () => {
      const user = userEvent.setup();
      const pending = deferredFetch();
      renderPage();

      await waitFor(() => expect(pending).toHaveLength(1));
      await user.click(screen.getByRole("button", { name: "GSTR-3B" }));
      await waitFor(() => expect(pending).toHaveLength(2));

      // GSTR-3B answers first, which is the whole point: responses do not come
      // back in the order they were sent.
      pending[1].answer(gstr3b());
      await loaded();
      expect(
        screen.getByRole("heading", { name: "What this leaves to pay" }),
      ).toBeInTheDocument();

      // Now the abandoned GSTR-1 lands. The heading, the export buttons and the
      // validation verdict all follow the toggle rather than the response, so
      // before this the page offered to file GSTR-3B over a GSTR-1 preview.
      pending[0].answer(gstr1({ validation: validation({ invoice_count: 99 }) }));

      await waitFor(() =>
        expect(
          screen.getByRole("heading", { name: "What this leaves to pay" }),
        ).toBeInTheDocument(),
      );
      expect(
        screen.getByRole("button", { name: /Download GSTR-3B JSON/i }),
      ).toBeInTheDocument();
      expect(screen.queryByText("99")).not.toBeInTheDocument();
    });

    it("does not raise an error banner for a request it cancelled itself", async () => {
      const user = userEvent.setup();
      const pending = deferredFetch();
      renderPage();

      await waitFor(() => expect(pending).toHaveLength(1));
      await user.click(screen.getByRole("button", { name: "GSTR-3B" }));
      await waitFor(() => expect(pending).toHaveLength(2));
      pending[1].answer(gstr3b());

      await loaded();
      // "signal is aborted without reason" in front of someone who simply
      // switched return would be worse than the stale preview the abort exists
      // to prevent.
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });

  describe("a download that outlives the controls that named it", () => {
    /**
     * Answer the previews and the status panel at once, but hold the export.
     *
     * An export builds the whole return rather than previewing it, so it is
     * the request most likely to still be running when the picker or the type
     * toggle has moved on — neither of which is disabled while it runs.
     */
    function deferredExport() {
      const exports = [];
      global.fetch = vi.fn(async (url) => {
        const href = String(url);
        if (href.includes("/filing/export/")) {
          return new Promise((resolve) => {
            exports.push({
              url: href,
              fail: (status, detail) =>
                resolve({
                  ok: false,
                  status,
                  statusText: "Error",
                  text: async () => JSON.stringify({ detail }),
                }),
            });
          });
        }
        if (href.includes("/filing/status")) {
          return {
            ok: true,
            status: 200,
            statusText: "OK",
            text: async () => JSON.stringify(filingStatus()),
          };
        }
        return {
          ok: true,
          status: 200,
          statusText: "OK",
          text: async () =>
            JSON.stringify(href.includes("/filing/gstr3b") ? gstr3b() : gstr1()),
        };
      });
      return exports;
    }

    it("blames the month a failed export was for, not the month now selected", async () => {
      const user = userEvent.setup();
      const exports = deferredExport();
      renderPage();

      await loaded();
      const started = prevPeriod();
      await user.click(screen.getByRole("button", { name: /Download GSTR-1 JSON/i }));
      await waitFor(() => expect(exports).toHaveLength(1));

      // An ordinary thing to do while waiting: only the download buttons are
      // disabled during an export, not the picker that decides what it is.
      const moved = await selectCompletedPeriod(user);
      expect(moved).not.toBe(started);

      // The export carries a tighter limit of its own, and its refusal names
      // no period — so left bare it is read as a fact about whatever is up.
      exports[0].fail(429, "Too many requests. Retry in 34 seconds.");

      const banner = await screen.findByRole("alert");
      expect(banner).toHaveTextContent("Too many requests. Retry in 34 seconds.");
      expect(banner).toHaveTextContent(periodLabel(started));
      // The month the user is now looking at has failed to export nothing.
      expect(banner).not.toHaveTextContent(periodLabel(moved));
    });

    it("blames the return a failed export was for, not the return now shown", async () => {
      const user = userEvent.setup();
      const exports = deferredExport();
      renderPage();

      await loaded();
      await user.click(screen.getByRole("button", { name: /Download GSTR-1 JSON/i }));
      await waitFor(() => expect(exports).toHaveLength(1));
      expect(exports[0].url).toContain("/filing/export/gstr1.json");

      // Waited on by the set-off panel rather than by the download button:
      // `busy` is shared, so while the GSTR-1 export runs the GSTR-3B button
      // is sitting there reading "Working…".
      await user.click(screen.getByRole("button", { name: "GSTR-3B" }));
      await screen.findByRole("heading", { name: "What this leaves to pay" });

      exports[0].fail(500, "Export failed");

      // Both returns are being prepared for the same month, so the period
      // alone does not separate them — over a GSTR-3B preview, an unattributed
      // "Export failed" is read as the GSTR-3B being the one that cannot go.
      const banner = await screen.findByRole("alert");
      expect(banner).toHaveTextContent("Could not download the GSTR-1");
      expect(banner).not.toHaveTextContent("GSTR-3B");
    });

    it("lets a download that lands late name itself without help", async () => {
      // The counterpart to the two above, and the reason the confirmation is
      // left alone: the server names the file for the return type and the
      // period precisely so it does not arrive as `download (3)`, so a success
      // that lands after the picker moved already says what it was.
      const user = userEvent.setup();
      mockApi();
      renderPage();

      await loaded();
      await user.click(screen.getByRole("button", { name: /Download GSTR-1 JSON/i }));
      expect(
        await screen.findByText("Downloaded gstr1_29AAGCB7383J1Z4_042026.json"),
      ).toBeInTheDocument();
    });
  });

  describe("what a missed deadline has cost", () => {
    /**
     * A late-fee answer that echoes the period and return type it was asked
     * about, the way the server does.
     *
     * The page will not render a figure whose period does not match the picker
     * — a stale answer for a month the user has left is a number they might go
     * and pay — so a fixed body would leave every test here asserting on an
     * empty panel and passing for the wrong reason.
     */
    function owedFor(overrides = {}) {
      return (href) => {
        // Read off the query string by hand: `beforeEach` replaces the global
        // `URL` with a plain object carrying the two blob helpers jsdom lacks,
        // so `new URL(...)` is not a constructor anywhere in this file.
        const period = /[?&]period=([^&]+)/.exec(href)?.[1];
        return lateFee({
          period,
          return_type: href.includes("/gstr3b/") ? "gstr3b" : "gstr1",
          days_late: 34,
          late_fee_cgst: "850.00",
          late_fee_sgst: "850.00",
          late_fee_total: "1700.00",
          interest: "1183.00",
          total_payable: "2883.00",
          ...overrides,
        });
      };
    }

    const panel = () => screen.findByRole("heading", { name: "What being late has cost" });

    it("puts a figure on a deadline the business has already missed", async () => {
      mockApi({ lateFee: owedFor() });
      renderPage();

      await panel();
      expect(screen.getByText("₹1,700.00")).toBeInTheDocument();
      expect(screen.getByText("₹2,883.00")).toBeInTheDocument();
    });

    it("says the amount is still growing while the return is unfiled", async () => {
      mockApi({ lateFee: owedFor({ projected: true }) });
      renderPage();

      expect(await panel()).toBeInTheDocument();
      expect(screen.getByText(/grows every day until it is filed/)).toBeInTheDocument();
    });

    it("counts a single day as one day rather than one days", async () => {
      // The sentence carries a rupee figure a business may act on, so it should
      // not read as though it were generated.
      mockApi({ lateFee: owedFor({ days_late: 1 }) });
      renderPage();

      await panel();
      expect(screen.getByText(/is 1 day past its/)).toBeInTheDocument();
    });

    it("stops calling it a projection once the filing has been recorded", async () => {
      mockApi({ lateFee: owedFor({ projected: false, filed_on: "2026-06-14" }) });
      renderPage();

      expect(await panel()).toBeInTheDocument();
      expect(screen.getByText(/Filed 34 days after the/)).toBeInTheDocument();
      expect(screen.queryByText(/grows every/)).not.toBeInTheDocument();
    });

    it("counts interest on a GSTR-3B, which is the only return that pays cash", async () => {
      const user = userEvent.setup();
      mockApi({ lateFee: owedFor() });
      renderPage();

      await panel();
      // Not on the GSTR-1 the page opens on: s.50 interest arises on the tax a
      // return settles, and a GSTR-1 settles none.
      expect(screen.queryByText("Interest (s.50)")).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "GSTR-3B" }));
      expect(await screen.findByText("Interest (s.50)")).toBeInTheDocument();
      expect(screen.getByText("₹1,183.00")).toBeInTheDocument();
    });

    it("says nothing at all about a return that is still inside its deadline", async () => {
      // The default: zero days late. A panel headed "what being late has cost"
      // reading nil over a period that is not late reads as a threat.
      mockApi();
      renderPage();

      await loaded();
      expect(
        screen.queryByRole("heading", { name: "What being late has cost" }),
      ).not.toBeInTheDocument();
    });

    it("splits the fee the way the portal asks for it", async () => {
      mockApi({ lateFee: owedFor() });
      renderPage();

      await panel();
      expect(screen.getByText(/₹850\.00 CGST and ₹850\.00 SGST/)).toBeInTheDocument();
    });

    it("asks again after a filing is recorded, so the clock stops on screen", async () => {
      const user = userEvent.setup();
      const asked = [];
      mockApi({ lateFee: owedFor(), onLateFee: (href) => asked.push(href) });
      renderPage();

      await panel();
      const before = asked.length;

      await selectCompletedPeriod(user);
      await user.click(screen.getByRole("button", { name: /Mark GSTR-1 as filed/i }));

      // Recording is the moment the figure stops growing: the same endpoint
      // answers a running projection while the return is outstanding and the
      // settled amount once it is not.
      await waitFor(() => expect(asked.length).toBeGreaterThan(before + 1));
    });

    it("does not let a late fee it could not load break the export buttons", async () => {
      // Same trade as the status table's. This panel is a consequence of the
      // period, not the work the page exists to do.
      mockApi({ lateFeeStatus: 500 });
      renderPage();

      await loaded();
      expect(
        screen.queryByRole("heading", { name: "What being late has cost" }),
      ).not.toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /Download GSTR-1 JSON/i }),
      ).toBeEnabled();
    });

    it("never shows a figure belonging to a period the picker has left", async () => {
      const user = userEvent.setup();
      // Pinned to the month the page opens on, whatever is asked for — which is
      // what a superseded response that resolved anyway looks like.
      const stuck = prevPeriod();
      mockApi({ lateFee: () => lateFee({ period: stuck, days_late: 34, total_payable: "2883.00" }) });
      renderPage();

      await panel();
      await selectCompletedPeriod(user);

      await waitFor(() =>
        expect(
          screen.queryByRole("heading", { name: "What being late has cost" }),
        ).not.toBeInTheDocument(),
      );
    });
  });
});

describe("a viewer", () => {
  afterEach(() => vi.restoreAllMocks());

  it("cannot record a filing", async () => {
    mockApi();
    renderPage({ role: "viewer" });
    await loaded();

    expect(screen.queryByRole("button", { name: /Mark GSTR-1 as filed/i })).toBeNull();
    expect(screen.queryByLabelText(/ARN/)).toBeNull();
  });

  it("keeps the exports, which are reads and the reason it is on this page", async () => {
    // The point of the split. A viewer downloading the JSON and handing it to
    // the CA who can file it is the normal way this product gets used by a
    // business that has an outside accountant — gating the exports along with
    // the recording would have broken that for no gain.
    mockApi();
    renderPage({ role: "viewer" });
    await loaded();

    expect(screen.getByRole("button", { name: /Download GSTR-1 JSON/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download CSV" })).toBeInTheDocument();
  });

  it("is told why the recording is missing", async () => {
    mockApi();
    renderPage({ role: "viewer" });
    await loaded();

    expect(
      screen.getByText(/Ask an owner or an accountant to record the filing/),
    ).toBeInTheDocument();
  });

  it("leaves an owner the recording form", async () => {
    mockApi();
    renderPage();
    await loaded();

    expect(screen.getByRole("button", { name: /Mark GSTR-1 as filed/i })).toBeInTheDocument();
  });
});
