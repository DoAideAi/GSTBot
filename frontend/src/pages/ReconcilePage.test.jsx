import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { currentPeriod, periodLabel } from "../lib/format";
import { StubAuth } from "../test/auth";
import ReconcilePage from "./ReconcilePage";

const PERIOD = "2026-04";

function imported(overrides = {}) {
  return {
    id: 1,
    period: PERIOD,
    return_type: "gstr2b",
    status: "imported",
    invoice_count: 2,
    total_taxable_value: "550000.00",
    total_cgst: "0.00",
    total_sgst: "0.00",
    total_igst: "99000.00",
    total_cess: "0.00",
    created_at: "2026-05-14T10:00:00Z",
    other_periods: [],
    replaced_previous: false,
    message: "Imported 2 invoices for 2026-04",
    ...overrides,
  };
}

function run(overrides = {}) {
  return {
    id: 7,
    period: PERIOD,
    status: "completed",
    total_invoices: 3,
    matched_count: 1,
    mismatched_count: 1,
    missing_in_2b_count: 1,
    missing_in_books_count: 1,
    duplicate_count: 0,
    itc_eligible: "72000.00",
    itc_at_risk: "90000.00",
    itc_claimed: "162000.00",
    started_at: "2026-05-14T10:01:00Z",
    completed_at: "2026-05-14T10:01:02Z",
    error: null,
    created_at: "2026-05-14T10:01:00Z",
    report: {
      tolerance: "1.00",
      findings: [
        {
          category: "matched",
          invoice_id: 11,
          invoice_number: "INV-2026-0042",
          supplier_gstin: "29AAGCB7383J1Z4",
          supplier_name: "Northwind Supplies",
          invoice_date: "2026-04-15",
          matched_on: "exact",
          differences: [],
          books: { taxable_value: "450000.00", total_tax: "81000.00" },
          gstr2b: { taxable_value: "450000.00", total_tax: "81000.00" },
        },
        {
          category: "mismatched",
          invoice_id: 12,
          invoice_number: "DH/451",
          supplier_gstin: "27AACCM6094J1Z3",
          supplier_name: "Deccan Hardware",
          invoice_date: "2026-04-18",
          matched_on: "exact",
          differences: [
            { field: "igst", books: "18000.00", gstr2b: "16200.00", delta: "1800.00" },
          ],
          books: { taxable_value: "100000.00", total_tax: "18000.00" },
          gstr2b: { taxable_value: "100000.00", total_tax: "16200.00" },
        },
        {
          category: "missing_in_2b",
          invoice_id: 13,
          invoice_number: "GHOST-1",
          supplier_gstin: "29AAGCB7383J1Z4",
          supplier_name: "Northwind Supplies",
          invoice_date: "2026-04-20",
          differences: [],
          books: { taxable_value: "500000.00", total_tax: "90000.00" },
        },
        {
          category: "missing_in_books",
          invoice_number: "UNBOOKED-9",
          supplier_gstin: "27AACCM6094J1Z3",
          supplier_name: "Deccan Hardware",
          invoice_date: "2026-04-22",
          note: "In GSTR-2B but not in the purchase register",
          differences: [],
          gstr2b: { taxable_value: "10000.00", total_tax: "1800.00" },
        },
      ],
    },
    ...overrides,
  };
}

/** Route fetches by URL so the page's two parallel loads resolve independently. */
function mockApi({
  imported2b,
  latest,
  onPost,
  fail,
  history,
  detail,
  register,
  periods,
} = {}) {
  global.fetch = vi.fn(async (url, options = {}) => {
    const ok = (body) => ({
      ok: true,
      status: 200,
      statusText: "OK",
      text: async () => JSON.stringify(body),
    });
    const refused = (status, detail) => ({
      ok: false,
      status,
      statusText: "",
      text: async () => JSON.stringify({ detail }),
    });
    const notFound = () => refused(404, "Not found");

    if (options.method === "POST") return ok(await onPost(url, options));
    // The purchase-register check, answered before `fail` because it is not
    // one of the reads that failure is about: the tests below that break the
    // server are asserting on the 2B and the run, and a register panel
    // appearing or vanishing in the middle of them is noise. Refused unless a
    // test asked for one, which is the branch that renders no panel at all.
    if (url.includes("/filing/validate")) {
      return register ? ok(register) : refused(503, "Not checked");
    }
    // `fail` stands in for the server being unable to answer at all, which is
    // the case a 404 must not be confused with.
    if (fail) return refused(fail.status, fail.message);
    // Ahead of the single-period read below, which its path is a prefix of.
    // Answered empty by default: which months have a statement marks the
    // picker, and every test that is not about the picker would otherwise have
    // to describe one.
    if (url.includes("/gstr2b/periods")) return ok({ items: periods ?? [] });
    if (url.includes("/gstr2b/")) return imported2b ? ok(imported2b) : notFound();
    if (url.includes("/latest")) return latest ? ok(latest) : notFound();
    // The list of past runs. Answered empty by default so that the tests about
    // the two panels above do not each have to describe a history they are not
    // asserting on; `history` is for the ones that are.
    if (/\/reconciliation\?/.test(url)) return ok({ items: history ?? [], total: 0 });
    if (/\/reconciliation\/\d+$/.test(url)) {
      return detail ? ok(detail) : refused(500, "Could not load that run.");
    }
    return notFound();
  });
}

function renderPage({ role } = {}) {
  return render(
    <MemoryRouter>
      <StubAuth role={role}>
        <ReconcilePage />
      </StubAuth>
    </MemoryRouter>,
  );
}

/**
 * A fetch that hands back the levers instead of resolving on its own.
 *
 * The bugs here are ordering ones, so the test has to be able to answer the
 * second period before the first. A mock that resolves by itself can only
 * ever answer them in order, which is the one case that was never broken.
 *
 * This page sends two requests per period rather than one, so `pending`
 * fills two at a time and the URL is what says which of the pair is which.
 *
 * The list of past runs is a third read, and it is answered immediately rather
 * than queued: these tests are about the ordering of the pair that fills the
 * panels, and holding a third request would shift every index in them without
 * asserting anything new. The list has its own tests, abort included.
 */
function deferredFetch() {
  const pending = [];
  global.fetch = vi.fn(
    (url, options = {}) =>
      new Promise((resolve, reject) => {
        // The register check is a fourth read and is refused immediately, for
        // the same reason the list is answered immediately: these tests are
        // about the ordering of the pair that fills the panels, and holding
        // this one would shift every index in them without asserting
        // anything new. It has its own tests, abort included.
        if (String(url).includes("/gstr2b/periods")) {
          resolve({
            ok: true,
            status: 200,
            statusText: "OK",
            text: async () => JSON.stringify({ items: [] }),
          });
          return;
        }
        if (String(url).includes("/filing/validate")) {
          resolve({
            ok: false,
            status: 503,
            statusText: "",
            text: async () => JSON.stringify({ detail: "Not checked" }),
          });
          return;
        }
        if (/\/reconciliation\?/.test(String(url))) {
          resolve({
            ok: true,
            status: 200,
            statusText: "OK",
            text: async () => JSON.stringify({ items: [], total: 0 }),
          });
          return;
        }
        pending.push({
          url: String(url),
          method: options.method ?? "GET",
          signal: options.signal,
          answer: (body) =>
            resolve({
              ok: true,
              status: 200,
              statusText: "OK",
              text: async () => JSON.stringify(body),
            }),
          refuse: (status) =>
            resolve({
              ok: false,
              status,
              statusText: "",
              text: async () => JSON.stringify({ detail: "Not found" }),
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

/** Switch to the month before the default, whenever the suite happens to run. */
async function selectPreviousPeriod(user) {
  const select = screen.getByLabelText("Period");
  const value = select.options[1].value;
  await user.selectOptions(select, value);
  return value;
}

describe("ReconcilePage", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("tells a first-time user where to get the file", async () => {
    mockApi({});
    renderPage();

    expect(await screen.findByText(/No GSTR-2B yet/)).toBeInTheDocument();
    expect(screen.getByText(/upload the JSON or CSV from the GST portal/)).toBeInTheDocument();
  });

  describe("a period the server could not answer for", () => {
    // A 404 is this page's empty state and a 500 is not, but both arrive as a
    // rejected promise. Treating the whole rejected branch as "nothing here
    // yet" told a user their period was empty on the strength of never having
    // found out — and then invited them to import a 2B they had already
    // imported.
    it("reports a server failure instead of calling the period empty", async () => {
      mockApi({ fail: { status: 500, message: "Database unreachable" } });
      renderPage();

      expect(await screen.findByText("Database unreachable")).toBeInTheDocument();
      // And stops calling it empty, which is the half of this the banner does
      // not do on its own. The sentence is not a caption on the banner — it is
      // a finding about the period, and it comes with an instruction to go and
      // import a 2B that may well already be there.
      expect(screen.queryByText(/No GSTR-2B yet/)).not.toBeInTheDocument();
    });

    it("says something even when the edge answers with no body it can read", async () => {
      mockApi({ fail: { status: 503, message: null } });
      renderPage();

      // statusText is empty over HTTP/2, so the code has to carry the message.
      expect(await screen.findByText(/temporarily unavailable|503/)).toBeInTheDocument();
    });

    it("keeps the empty state silent when the period really is empty", async () => {
      mockApi({});
      renderPage();

      await screen.findByText(/No GSTR-2B yet/);
      // A 404 from both endpoints is the ordinary first visit to a period.
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("does not invite a run it could not find out about", async () => {
      // The other half of the same fault, on the other endpoint. The 2B loads,
      // the run endpoint answers 500, and the page offers "Run the
      // reconciliation to see what matches" — which says this period has never
      // been reconciled. Every figure that sentence is standing in for comes
      // from the run it claims does not exist.
      global.fetch = vi.fn(async (url) => {
        if (String(url).includes("/latest")) {
          return {
            ok: false,
            status: 500,
            statusText: "",
            text: async () => JSON.stringify({ detail: "Database unreachable" }),
          };
        }
        return {
          ok: true,
          status: 200,
          statusText: "OK",
          text: async () => JSON.stringify(imported()),
        };
      });
      renderPage();

      await screen.findByText(/invoices imported/);
      expect(await screen.findByText("Database unreachable")).toBeInTheDocument();
      expect(
        screen.queryByText(/Run the reconciliation to see what matches/),
      ).not.toBeInTheDocument();
    });

    it("does not raise a banner for the run alone being absent", async () => {
      // The common case after an import: a 2B is there, nothing has been
      // reconciled against it yet, and only the run endpoint answers 404.
      mockApi({ imported2b: imported() });
      renderPage();

      await screen.findByText(/invoices imported/);
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });

  it("cannot reconcile before a 2B exists", async () => {
    mockApi({});
    renderPage();

    await screen.findByText(/No GSTR-2B yet/);
    expect(screen.getByRole("button", { name: /Run reconciliation/ })).toBeDisabled();
  });

  it("enables reconciling once a 2B is imported", async () => {
    mockApi({ imported2b: imported() });
    renderPage();

    expect(await screen.findByText(/invoices imported/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run reconciliation/ })).toBeEnabled();
  });

  it("shows the ITC figures a run produced", async () => {
    mockApi({ imported2b: imported(), latest: run() });
    renderPage();

    expect(await screen.findByText("₹72,000.00")).toBeInTheDocument();
    expect(screen.getByText("₹1,62,000.00")).toBeInTheDocument();
    // ITC at risk is ₹90,000 and so is the one unfiled invoice behind it, so
    // the figure legitimately appears in both the tile and the findings table.
    expect(screen.getAllByText("₹90,000.00").length).toBeGreaterThan(0);
  });

  it("lists every finding with its outcome", async () => {
    mockApi({ imported2b: imported(), latest: run() });
    renderPage();

    expect(await screen.findByText("INV-2026-0042")).toBeInTheDocument();
    expect(screen.getByText("DH/451")).toBeInTheDocument();
    expect(screen.getByText("GHOST-1")).toBeInTheDocument();
    expect(screen.getByText("UNBOOKED-9")).toBeInTheDocument();
  });

  it("names the field that differs on a mismatch", async () => {
    mockApi({ imported2b: imported(), latest: run() });
    renderPage();

    const row = (await screen.findByText("DH/451")).closest("tr");
    expect(within(row).getByText("igst")).toBeInTheDocument();
    expect(within(row).getByText(/₹18,000.00 vs ₹16,200.00/)).toBeInTheDocument();
  });

  it("links a finding back to the invoice it is about", async () => {
    mockApi({ imported2b: imported(), latest: run() });
    renderPage();

    const link = await screen.findByRole("link", { name: "INV-2026-0042" });
    expect(link).toHaveAttribute("href", "/invoices/11");
  });

  it("leaves a portal-only invoice unlinked, since it has no invoice of ours", async () => {
    mockApi({ imported2b: imported(), latest: run() });
    renderPage();

    await screen.findByText("UNBOOKED-9");
    expect(screen.queryByRole("link", { name: "UNBOOKED-9" })).not.toBeInTheDocument();
  });

  it("filters the findings by outcome", async () => {
    const user = userEvent.setup();
    mockApi({ imported2b: imported(), latest: run() });
    renderPage();

    await screen.findByText("INV-2026-0042");
    await user.click(screen.getByRole("button", { name: /Missing in 2B \(1\)/ }));

    expect(screen.getByText("GHOST-1")).toBeInTheDocument();
    expect(screen.queryByText("INV-2026-0042")).not.toBeInTheDocument();
    // The filter explains what the category means and what to do about it.
    expect(screen.getByText(/This credit is at risk until they file/)).toBeInTheDocument();
  });

  it("puts every outcome back when the filter is cleared", async () => {
    // The way out of a filtered list. Every other chip narrows; this is the
    // only one that widens, and nothing in this suite had ever clicked it — a
    // screen that could be filtered and not unfiltered would have shipped
    // green.
    const user = userEvent.setup();
    mockApi({ imported2b: imported(), latest: run() });
    renderPage();

    await screen.findByText("INV-2026-0042");
    await user.click(screen.getByRole("button", { name: /Missing in 2B \(1\)/ }));
    expect(screen.queryByText("INV-2026-0042")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^All \(/ }));

    expect(screen.getByText("INV-2026-0042")).toBeInTheDocument();
    expect(screen.getByText("GHOST-1")).toBeInTheDocument();
    expect(screen.getByText("UNBOOKED-9")).toBeInTheDocument();
    // And the category's explanation goes with it. It described the filter
    // rather than the findings, so leaving it up would caption the whole list
    // with advice about one quarter of it.
    expect(
      screen.queryByText(/This credit is at risk until they file/),
    ).not.toBeInTheDocument();
  });

  it("runs a reconciliation and shows the result", async () => {
    const user = userEvent.setup();
    window.umami = { track: vi.fn() };
    mockApi({
      imported2b: imported(),
      onPost: async () => run(),
    });
    renderPage();

    await screen.findByText(/invoices imported/);
    await user.click(screen.getByRole("button", { name: /Run reconciliation/ }));

    expect(await screen.findByText("GHOST-1")).toBeInTheDocument();
    // The period is whichever month the picker defaults to, so this asserts
    // the confirmation shape rather than pinning the suite to a clock.
    expect(screen.getByText(/^Reconciled \w+ \d{4}$/)).toBeInTheDocument();
    expect(window.umami.track).toHaveBeenCalledWith("reconcile_run", { invoices: 3, matched: 1 });
    delete window.umami;
  });

  it("surfaces a failed run as the server explained it", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn(async (url, options = {}) => {
      if (options.method === "POST") {
        return {
          ok: false,
          status: 409,
          statusText: "Conflict",
          text: async () =>
            JSON.stringify({ detail: "No GSTR-2B has been imported for 2026-04." }),
        };
      }
      if (url.includes("/gstr2b/periods")) {
        return { ok: true, status: 200, statusText: "OK", text: async () => '{"items":[]}' };
      }
      if (url.includes("/gstr2b/")) {
        return {
          ok: true,
          status: 200,
          statusText: "OK",
          text: async () => JSON.stringify(imported()),
        };
      }
      return { ok: false, status: 404, statusText: "Not Found", text: async () => "{}" };
    });
    renderPage();

    await screen.findByText(/invoices imported/);
    await user.click(screen.getByRole("button", { name: /Run reconciliation/ }));

    expect(
      await screen.findByText(/No GSTR-2B has been imported for 2026-04/),
    ).toBeInTheDocument();
  });

  it("blames the month a failed run was for, not the month now selected", async () => {
    const user = userEvent.setup();
    const pending = deferredFetch();
    renderPage();

    const started = currentPeriod();
    const startedLoads = pending.splice(0);
    startedLoads.find((r) => r.url.includes("/gstr2b/")).answer(imported());
    startedLoads.find((r) => r.url.includes("/latest")).refuse(404);
    await screen.findByText(/invoices imported/);

    await user.click(screen.getByRole("button", { name: /Run reconciliation/ }));
    await waitFor(() => expect(pending).toHaveLength(1));
    const reconcile = pending.pop();
    expect(reconcile.method).toBe("POST");

    // The picker stays live while a run is in flight — nothing disables it.
    const moved = await selectPreviousPeriod(user);
    expect(moved).not.toBe(started);
    const movedLoads = pending.splice(0);
    movedLoads.find((r) => r.url.includes("/gstr2b/")).refuse(404);
    movedLoads.find((r) => r.url.includes("/latest")).refuse(404);
    await screen.findByText(/No GSTR-2B yet/);

    reconcile.refuse(500);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(`Could not reconcile ${periodLabel(started)}`);
    expect(banner).not.toHaveTextContent(periodLabel(moved));
  });

  it("uploads a 2B and reports what the server made of it", async () => {
    const user = userEvent.setup();
    window.umami = { track: vi.fn() };
    let posted = null;
    mockApi({
      onPost: async (url, options) => {
        posted = { url, body: options.body };
        return imported({ message: "Imported 2 invoices for 2026-04" });
      },
    });
    renderPage();

    await screen.findByText(/No GSTR-2B yet/);
    const file = new File(['{"data":{}}'], "gstr2b.json", { type: "application/json" });
    await user.upload(screen.getByLabelText(/Import GSTR-2B/), file);

    await waitFor(() =>
      expect(screen.getByText("Imported 2 invoices for 2026-04")).toBeInTheDocument(),
    );
    expect(posted.url).toContain("/reconciliation/gstr2b/import");
    expect(posted.body).toBeInstanceOf(FormData);
    expect(posted.body.get("file").name).toBe("gstr2b.json");
    expect(window.umami.track).toHaveBeenCalledWith("gstr2b_import", { format: "json" });
    delete window.umami;
  });

  it("follows the period the server read out of the file", async () => {
    const user = userEvent.setup();
    mockApi({
      onPost: async () =>
        imported({ period: "2026-02", message: "Imported 2 invoices for 2026-02" }),
    });
    renderPage();

    await screen.findByText(/No GSTR-2B yet/);
    const file = new File(['{"data":{}}'], "gstr2b.json", { type: "application/json" });
    await user.upload(screen.getByLabelText(/Import GSTR-2B/), file);

    // The picker moves to the file's period rather than leaving a stale month
    // on screen next to the newly imported statement.
    await waitFor(() =>
      expect(screen.getByLabelText(/Period/)).toHaveValue("2026-02"),
    );
  });

  it("offers to replace rather than import once one exists", async () => {
    mockApi({ imported2b: imported() });
    renderPage();

    expect(await screen.findByText(/Replace GSTR-2B/)).toBeInTheDocument();
  });

  it("refuses an oversized 2B without asking the server", async () => {
    const user = userEvent.setup();
    let posted = false;
    mockApi({
      onPost: async () => {
        posted = true;
        return imported();
      },
    });
    renderPage();
    await screen.findByText(/No GSTR-2B yet/);

    const file = new File(['{"data":{}}'], "gstr2b.json", { type: "application/json" });
    Object.defineProperty(file, "size", { value: 41 * 1024 * 1024 });
    await user.upload(screen.getByLabelText(/Import GSTR-2B/), file);

    expect(await screen.findByRole("alert")).toHaveTextContent(/over the 15 MB limit/);
    expect(posted).toBe(false);
  });

  it("refuses an empty 2B file", async () => {
    const user = userEvent.setup();
    mockApi({});
    renderPage();
    await screen.findByText(/No GSTR-2B yet/);

    const file = new File([""], "gstr2b.json", { type: "application/json" });
    Object.defineProperty(file, "size", { value: 0 });
    await user.upload(screen.getByLabelText(/Import GSTR-2B/), file);

    expect(await screen.findByRole("alert")).toHaveTextContent(/still be downloading/);
  });

  it("reloads the summary when the file was for the period on screen", async () => {
    // The period did not change, so nothing re-renders on its own — the page
    // has to refetch, or the freshly imported statement is invisible until a
    // manual reload.
    const user = userEvent.setup();
    const gstr2bGets = [];
    // The page opens on the current month, so the file has to come back
    // stamped with whatever that is for the periods to agree.
    const onScreen = () => screen.getByLabelText(/Period/).value;
    global.fetch = vi.fn(async (url, options = {}) => {
      const ok = (body) => ({
        ok: true,
        status: 200,
        statusText: "OK",
        text: async () => JSON.stringify(body),
      });
      if (options.method === "POST") return ok(imported({ period: onScreen() }));
      if (String(url).includes("/gstr2b/")) {
        gstr2bGets.push(url);
        // Not imported on the first look, imported afterwards.
        return gstr2bGets.length === 1
          ? { ok: false, status: 404, statusText: "Not Found", text: async () => "{}" }
          : ok(imported({ period: onScreen() }));
      }
      return { ok: false, status: 404, statusText: "Not Found", text: async () => "{}" };
    });
    renderPage();
    await screen.findByText(/No GSTR-2B yet/);
    const before = onScreen();

    const file = new File(['{"data":{}}'], "gstr2b.json", { type: "application/json" });
    await user.upload(screen.getByLabelText(/Import GSTR-2B/), file);

    await waitFor(() => expect(gstr2bGets.length).toBeGreaterThan(1));
    expect(screen.getByLabelText(/Period/)).toHaveValue(before);
  });

  it("explains a rejected import rather than reporting a silent success", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn(async (url, options = {}) => {
      if (options.method === "POST") {
        return {
          ok: false,
          status: 422,
          statusText: "Unprocessable Entity",
          text: async () =>
            JSON.stringify({ detail: "That file is a GSTR-2A, not a GSTR-2B" }),
        };
      }
      return { ok: false, status: 404, statusText: "Not Found", text: async () => "{}" };
    });
    renderPage();
    await screen.findByText(/No GSTR-2B yet/);

    const file = new File(['{"data":{}}'], "gstr2b.json", { type: "application/json" });
    await user.upload(screen.getByLabelText(/Import GSTR-2B/), file);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That file is a GSTR-2A, not a GSTR-2B",
    );
  });

  it("says a category is empty rather than showing a bare table", async () => {
    // A clean run has no duplicates, and an empty table under the "Duplicates"
    // heading reads as a page that failed to load.
    const user = userEvent.setup();
    mockApi({ imported2b: imported(), latest: run() });
    renderPage();
    await screen.findByText("INV-2026-0042");

    await user.click(screen.getByRole("button", { name: /Duplicate \(0\)/ }));

    expect(screen.getByText("Nothing in this category.")).toBeInTheDocument();
  });

  describe("when answers come back out of order", () => {
    it("abandons the pair of requests the previous period supersedes", async () => {
      const user = userEvent.setup();
      const pending = deferredFetch();
      renderPage();

      await waitFor(() => expect(pending).toHaveLength(2));
      pending[0].answer(imported());
      pending[1].answer(run());
      await screen.findByText("INV-2026-0042");

      await selectPreviousPeriod(user);
      await waitFor(() => expect(pending).toHaveLength(4));

      // Both halves of the superseded load are cancelled, not just the one the
      // page happened to be rendering.
      expect(pending[0].signal.aborted).toBe(true);
      expect(pending[1].signal.aborted).toBe(true);
      expect(pending[2].signal.aborted).toBe(false);
      expect(pending[3].signal.aborted).toBe(false);
    });

    it("does not put one month's exposure under another month's period", async () => {
      const user = userEvent.setup();
      const pending = deferredFetch();
      renderPage();

      await waitFor(() => expect(pending).toHaveLength(2));
      await selectPreviousPeriod(user);
      await waitFor(() => expect(pending).toHaveLength(4));

      // The second period answers first, which is the whole point: responses
      // do not come back in the order they were sent.
      pending[2].answer(imported({ invoice_count: 7 }));
      pending[3].answer(run({ itc_at_risk: "1234.00", report: { findings: [] } }));
      await screen.findByText("₹1,234.00");

      // Now the abandoned first period lands. Nothing on this screen carries
      // its own month, so before the abort its ₹90,000 at risk and its five
      // findings simply replaced the ones belonging to the period in the
      // picker.
      pending[0].answer(imported());
      pending[1].answer(run());

      await waitFor(() => expect(screen.getByText("7")).toBeInTheDocument());
      expect(screen.getByText("₹1,234.00")).toBeInTheDocument();
      expect(screen.queryByText("₹90,000.00")).not.toBeInTheDocument();
      expect(screen.queryByText("INV-2026-0042")).not.toBeInTheDocument();
    });

    it("does not raise an error banner for a request it cancelled itself", async () => {
      const user = userEvent.setup();
      const pending = deferredFetch();
      renderPage();

      await waitFor(() => expect(pending).toHaveLength(2));
      await selectPreviousPeriod(user);
      await waitFor(() => expect(pending).toHaveLength(4));

      pending[2].refuse(404);
      pending[3].refuse(404);
      await screen.findByText(/No GSTR-2B yet/);

      // An AbortError carries no status, so the 404-is-the-empty-state test
      // does not exempt it: left unguarded, "The operation was aborted."
      // reaches the banner of someone who simply changed month.
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });

  // The loads above are aborted when the period moves. These two are not
  // loads: they are the actions the page exists for, they are the slowest
  // requests it makes, and the period picker stays live throughout both.
  describe("when the period changes while an action is in flight", () => {
    it("does not put a superseded run's findings under the month now on screen", async () => {
      const user = userEvent.setup();
      const pending = deferredFetch();
      renderPage();

      await waitFor(() => expect(pending).toHaveLength(2));
      pending[0].answer(imported());
      pending[1].refuse(404);
      await screen.findByText(/invoices imported/);

      // Reconciling is the slowest thing this page does — it walks the whole
      // purchase register against the statement — so it is the request most
      // likely to still be running when someone moves on to another month.
      await user.click(screen.getByRole("button", { name: /Run reconciliation/ }));
      await waitFor(() => expect(pending).toHaveLength(3));
      expect(pending[2].method).toBe("POST");

      await selectPreviousPeriod(user);
      await waitFor(() => expect(pending).toHaveLength(5));
      pending[3].answer(imported({ invoice_count: 7 }));
      pending[4].refuse(404);
      await screen.findByText(/7\b/);

      // Now the run for the month that is no longer selected comes back.
      pending[2].answer(run());

      // Nothing below the picker carries its own month, so applying it would
      // report the previous month's ₹90,000 at risk, its findings and its
      // matched count as belonging to the period in the picker.
      await waitFor(() => expect(screen.getByText(/7\b/)).toBeInTheDocument());
      expect(screen.queryByText("₹90,000.00")).not.toBeInTheDocument();
      expect(screen.queryByText("GHOST-1")).not.toBeInTheDocument();
    });

    it("reloads the period the imported file was for, not the one it was started from", async () => {
      const user = userEvent.setup();
      const pending = deferredFetch();
      renderPage();

      await waitFor(() => expect(pending).toHaveLength(2));
      const startedOn = screen.getByLabelText("Period").value;
      pending[0].refuse(404);
      pending[1].refuse(404);
      await screen.findByText(/No GSTR-2B yet/);

      const file = new File(['{"data":{}}'], "gstr2b.json", { type: "application/json" });
      await user.upload(screen.getByLabelText(/Import GSTR-2B/), file);
      await waitFor(() => expect(pending).toHaveLength(3));
      expect(pending[2].method).toBe("POST");

      // A 2B is a few megabytes over a phone connection, and the picker is
      // live while it uploads.
      await selectPreviousPeriod(user);
      await waitFor(() => expect(pending).toHaveLength(5));
      pending[3].refuse(404);
      pending[4].refuse(404);

      pending[2].answer(imported({ period: startedOn, invoice_count: 42 }));

      // The statement was for the month the upload was started from, so that
      // is the month whose figures it may be shown under — the page follows
      // the file rather than refetching the month it left behind and
      // captioning it with the month in the picker.
      await waitFor(() => expect(screen.getByLabelText("Period")).toHaveValue(startedOn));
      const reload = pending.slice(5).filter((p) => p.url.includes("/gstr2b/"));
      expect(reload).toHaveLength(1);
      expect(reload[0].url).toContain(startedOn);
    });
  });

  describe("an invoice this statement declares late", () => {
    // A May 2B routinely carries April invoices the supplier filed late. The
    // report lists them, because the statement names them, but every counter
    // the server sends deliberately leaves them out — April already counted
    // them, and adding them here would grow April's matched count every time a
    // supplier caught up on an old one.
    //
    // So two numbers on this screen are right about different questions, and
    // the screen has to survive them disagreeing. The stat card is the period's
    // own tally and excludes the carried row; the chip beside the filter counts
    // the rows that filter yields and includes it. The "Late filing" marker is
    // the only thing on the page that explains why — without it the extra row
    // is unaccounted for, and a user counting rows finds one more than every
    // number beside them.

    /** The standard run plus one late-filed April invoice, matched. */
    function withCarried() {
      const base = run();
      return run({
        report: {
          ...base.report,
          findings: [
            ...base.report.findings,
            {
              category: "matched",
              invoice_id: 21,
              invoice_number: "APR/0098",
              supplier_gstin: "29AAGCB7383J1Z4",
              supplier_name: "Northwind Supplies",
              invoice_date: "2026-03-28",
              matched_on: "exact",
              carried: true,
              note: "Booked in 2026-03; declared in this statement",
              differences: [],
              books: { taxable_value: "20000.00", total_tax: "3600.00" },
              gstr2b: { taxable_value: "20000.00", total_tax: "3600.00" },
            },
          ],
        },
      });
    }

    it("marks the row so the extra line is not unexplained", async () => {
      mockApi({ imported2b: imported(), latest: withCarried() });
      renderPage();

      const row = (await screen.findByText("APR/0098")).closest("tr");
      const marker = within(row).getByText("Late filing");
      expect(marker).toBeInTheDocument();
      // Which month booked it rides on the marker rather than in a column of
      // its own, which would be empty on every other row.
      expect(marker).toHaveAttribute("title", "Booked in 2026-03; declared in this statement");
    });

    it("leaves the marker off the period's own rows", async () => {
      mockApi({ imported2b: imported(), latest: withCarried() });
      renderPage();

      const row = (await screen.findByText("INV-2026-0042")).closest("tr");
      expect(within(row).queryByText("Late filing")).not.toBeInTheDocument();
    });

    it("counts the carried row on the chip, which labels the list", async () => {
      mockApi({ imported2b: imported(), latest: withCarried() });
      renderPage();

      // Two matched rows are shown under this filter, so the chip says two.
      // Taken from the server's matched_count it said one, over a list of two.
      const chip = await screen.findByRole("button", { name: /^Matched \(/ });
      expect(chip).toHaveTextContent("Matched (2)");
      expect(screen.getByRole("button", { name: /^All \(/ })).toHaveTextContent("All (5)");

      await userEvent.click(chip);
      const rows = within(screen.getByRole("table")).getAllByRole("row");
      expect(rows).toHaveLength(3); // header + the two the chip counted
    });

    it("keeps the carried row off the stat card, which is the period's own", async () => {
      mockApi({ imported2b: imported(), latest: withCarried() });
      renderPage();

      // The run's own numerator over the run's own denominator. Taking the
      // numerator from the chip tally instead would read "2 / 3" — a period
      // that matched more invoices than it considered.
      const card = (await screen.findByText("Matched", { selector: ".stat-label" })).closest(
        ".stat-card",
      );
      expect(within(card).getByText("1 / 3")).toBeInTheDocument();
    });
  });

  /**
   * The other side of two branches every fixture above enters the same way.
   *
   * `run()` carries `itc_at_risk: "90000.00"` and one matched invoice of
   * three, so every assertion in this file has read the cards in their alarmed
   * state. A clean period — nothing at risk, everything matched — is the
   * outcome the product is for, and until here nothing rendered one.
   */
  describe("a period with nothing wrong", () => {
    it("reads the risk card as good when no ITC is at risk", async () => {
      mockApi({
        imported2b: imported(),
        latest: run({ itc_at_risk: "0.00" }),
      });
      renderPage();

      const card = (await screen.findByText("ITC at risk", { selector: ".stat-label" })).closest(
        ".stat-card",
      );
      expect(card).toHaveClass("tone-good");
    });

    it("reads the matched card as good only when every invoice matched", async () => {
      mockApi({
        imported2b: imported(),
        latest: run({ matched_count: 3, total_invoices: 3 }),
      });
      renderPage();

      const card = (await screen.findByText("Matched", { selector: ".stat-label" })).closest(
        ".stat-card",
      );
      expect(within(card).getByText("3 / 3")).toBeInTheDocument();
      expect(card).toHaveClass("tone-good");
    });
  });

  it("does nothing when the file picker is dismissed without a file", async () => {
    // Opening the picker and pressing Cancel fires `change` with an empty
    // FileList. The guard for it is one line and had never run: every other
    // upload test here hands over a file. Without it the extension check
    // reads `undefined.name` and the screen dies on a cancelled dialog.
    //
    // fireEvent rather than `user.upload(input, [])` — user-event treats an
    // empty upload as nothing to do and never dispatches the event, so the
    // guard would go on being unreached while the test passed.
    const onPost = vi.fn();
    mockApi({ imported2b: imported(), latest: run(), onPost });
    renderPage();
    await screen.findByText("ITC at risk", { selector: ".stat-label" });

    fireEvent.change(screen.getByLabelText(/Replace GSTR-2B|Import GSTR-2B/), {
      target: { files: [] },
    });

    expect(onPost).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does nothing when the picker reports no file list at all", async () => {
    // The sibling of the case above, and the reason the guard is `?? []`
    // rather than a length check: a picker reset programmatically reports
    // `files` as null in some browsers, and `Array.from(null)` throws.
    const onPost = vi.fn();
    mockApi({ imported2b: imported(), latest: run(), onPost });
    renderPage();
    await screen.findByText("ITC at risk", { selector: ".stat-label" });

    fireEvent.change(screen.getByLabelText(/Replace GSTR-2B|Import GSTR-2B/), {
      target: { files: null },
    });

    expect(onPost).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

// The report is written by the matcher, not by a form, and every field on a
// finding traces back to something the parser did or did not read off a scan.
// A row that renders only when all of them are present is a row that vanishes
// for exactly the invoices most in need of attention.
describe("a finding assembled from what the parser could not read", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  /** A run whose sole finding carries the bare minimum the matcher emits. */
  function bare(overrides = {}) {
    return run({
      total_invoices: 1,
      matched_count: 0,
      report: {
        tolerance: "1.00",
        findings: [
          {
            category: "missing_in_2b",
            invoice_id: 31,
            invoice_number: null,
            supplier_gstin: null,
            supplier_name: null,
            invoice_date: null,
            differences: [],
            books: { taxable_value: "50000.00", total_tax: "9000.00" },
            ...overrides,
          },
        ],
      },
    });
  }

  it("still links an invoice with no number, under a stand-in label", async () => {
    // This is the row that matters most — in the books, not in the 2B, so the
    // credit is at risk — and it is the one a photographed invoice with no
    // legible number produces. A blank cell here is an unclickable dead end.
    mockApi({ imported2b: imported(), latest: bare() });
    renderPage();

    const link = await screen.findByRole("link", { name: "(no number)" });
    expect(link).toHaveAttribute("href", "/invoices/31");
  });

  it("shows a dash for a supplier it could not name, and no stray GSTIN line", async () => {
    mockApi({ imported2b: imported(), latest: bare() });
    renderPage();

    const row = (await screen.findByRole("link", { name: "(no number)" })).closest("tr");
    // The supplier cell holds a name over a GSTIN. With neither read, the
    // dash stands in for the name and the GSTIN line renders as nothing —
    // not as the literal "null" that a bare interpolation would print.
    expect(row.querySelectorAll("td")[2].textContent).toBe("—");
  });

  it("prints an unlinked stand-in for a 2B row with no invoice id", async () => {
    // A finding the statement declares and the books never booked has no
    // invoice of ours to link to, so the same stand-in has to render as text.
    mockApi({
      imported2b: imported(),
      latest: bare({ category: "missing_in_books", invoice_id: null }),
    });
    renderPage();

    expect(await screen.findByText("(no number)")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "(no number)" })).not.toBeInTheDocument();
  });

  it("labels a category this build has never heard of, rather than blanking the chip", async () => {
    // The matcher's categories are a server-side enum. A build of this app
    // that predates a new one must not answer with an empty chip on a row it
    // is still showing every other column of.
    mockApi({
      imported2b: imported(),
      latest: bare({ category: "amended_by_supplier", invoice_number: "AMD-1" }),
    });
    renderPage();

    const row = (await screen.findByText("AMD-1")).closest("tr");
    expect(within(row).getByText("amended_by_supplier")).toBeInTheDocument();
  });

  it("marks a late filing with no note without an empty tooltip", async () => {
    mockApi({
      imported2b: imported(),
      latest: bare({ carried: true, note: null, invoice_number: "APR/1" }),
    });
    renderPage();

    const row = (await screen.findByText("APR/1")).closest("tr");
    expect(within(row).getByText("Late filing")).toHaveAttribute("title", "");
  });

  it("counts a run with no matched tally as none matched, not as all of them", async () => {
    // A run row written before the counter existed reads back null. Rendering
    // that as "null / 3" is merely ugly; letting it satisfy the all-matched
    // comparison would colour the card green on a period nothing matched in.
    mockApi({
      imported2b: imported(),
      latest: run({ matched_count: null, total_invoices: 3 }),
    });
    renderPage();

    const card = (await screen.findByText("Matched", { selector: ".stat-label" })).closest(
      ".stat-card",
    );
    expect(within(card).getByText("0 / 3")).toBeInTheDocument();
    expect(card).toHaveClass("tone-warn");
  });

  it("says something when the refusal it was handed carries no words", async () => {
    // `{"detail": ""}` from a proxy that rewrote the body. An empty string is
    // not nullish, so it survived every `??` on the way here and landed as an
    // error banner with nothing in it — which reads as a rendering bug rather
    // than as a period that could not be loaded.
    //
    // It is now caught a layer earlier, in `errorMessage`, where it can be
    // answered with the status the response actually carried rather than with
    // this page's guess at what the request was for. Every screen shares that
    // path and only this one had a fallback of its own, so the assertion moved
    // to the sentence the client supplies. The page's own "Could not load this
    // period." stays as the answer for a rejection that did not come from the
    // API at all, which is a thing this fetch mock cannot produce.
    mockApi({ fail: { status: 500, message: "" } });
    renderPage();

    expect(
      await screen.findByText("The server is having trouble (500). Please try again in a moment."),
    ).toBeInTheDocument();
  });
});

describe("the runs a period accumulates", () => {
  // Runs do not overwrite each other. A period is reconciled again each time a
  // supplier files late and the 2B is regenerated, and every run but the newest
  // was stored and unreachable — which matters because the older ones are the
  // evidence: credit claimed in June against a supplier who had not filed, and
  // the run that said so at the time, is the answer to a reversal in November.
  // The picker opens on the current month, and an earlier run is only applied
  // when it belongs to the month still on screen — so these have to be it.
  const SHOWN = currentPeriod();
  const LATEST = {
    id: 9,
    period: SHOWN,
    total_invoices: 3,
    matched_count: 3,
    itc_at_risk: "0.00",
    itc_eligible: "162000.00",
    completed_at: "2026-06-02T09:30:00Z",
    created_at: "2026-06-02T09:30:00Z",
  };
  const EARLIER = {
    id: 7,
    period: SHOWN,
    total_invoices: 3,
    matched_count: 1,
    itc_at_risk: "90000.00",
    itc_eligible: "72000.00",
    completed_at: "2026-05-14T10:01:02Z",
    created_at: "2026-05-14T10:01:00Z",
  };

  function renderWithHistory(options = {}) {
    mockApi({
      imported2b: imported(),
      latest: run({ id: 9, matched_count: 3, itc_at_risk: "0.00" }),
      history: [LATEST, EARLIER],
      ...options,
    });
    return render(
      <MemoryRouter>
        <StubAuth>
          <ReconcilePage />
        </StubAuth>
      </MemoryRouter>,
    );
  }

  afterEach(() => vi.restoreAllMocks());

  it("lists what each earlier run found, so the figures can be seen to have moved", async () => {
    renderWithHistory();
    const table = await screen.findByRole("region", { name: "Earlier reconciliation runs" });

    // The point of the list is the pair of numbers side by side: the same
    // period, two dates, and ₹90,000 of credit that stopped being at risk.
    expect(within(table).getByText("₹90,000.00")).toBeInTheDocument();
    expect(within(table).getByText("1 / 3")).toBeInTheDocument();
    expect(within(table).getByText("3 / 3")).toBeInTheDocument();
  });

  it("says nothing about history when the period has only ever been run once", async () => {
    // A single entry is the run already on screen, listed again under a heading
    // calling it history.
    renderWithHistory({ history: [LATEST] });
    await screen.findByText(/invoices imported/);
    expect(
      screen.queryByRole("region", { name: "Earlier reconciliation runs" }),
    ).not.toBeInTheDocument();
  });

  it("opens an earlier run's own findings, not the latest one's", async () => {
    const user = userEvent.setup();
    renderWithHistory({
      detail: run({ id: 7, itc_at_risk: "90000.00", completed_at: "2026-05-14T10:01:02Z" }),
    });
    await screen.findByRole("region", { name: "Earlier reconciliation runs" });

    await user.click(screen.getByRole("button", { name: /View the run from/ }));

    // The findings come from the run that was opened; the counts change with it.
    expect(await screen.findByText("GHOST-1")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/not the latest/i);
  });

  it("does not go on calling an earlier run the last run", async () => {
    // "Last run" is a claim about which run this is, and every figure beside it
    // is a past state of the period — an ITC at risk that has since been
    // resolved reads exactly like one that has not.
    const user = userEvent.setup();
    renderWithHistory({ detail: run({ id: 7, completed_at: "2026-05-14T10:01:02Z" }) });
    await screen.findByRole("region", { name: "Earlier reconciliation runs" });
    expect(screen.getByText(/Last run/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /View the run from/ }));

    await waitFor(() => expect(screen.queryByText(/Last run/)).not.toBeInTheDocument());
  });

  it("goes back to the latest run", async () => {
    const user = userEvent.setup();
    renderWithHistory({ detail: run({ id: 7, itc_at_risk: "90000.00" }) });
    await screen.findByRole("region", { name: "Earlier reconciliation runs" });
    await user.click(screen.getByRole("button", { name: /View the run from/ }));
    await screen.findByRole("status");

    await user.click(screen.getByRole("button", { name: /Back to the latest run/ }));

    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    expect(screen.getByText(/Last run/)).toBeInTheDocument();
  });

  it("comes back to the latest run from the row that names it", async () => {
    // The table's own way back, which is not the banner's. Once an earlier run
    // is applied the newest row stops being the one on screen and grows a
    // "View" of its own, and it is the control anyone reading the list reaches
    // for — the banner is above the fold they are no longer looking at.
    const user = userEvent.setup();
    renderWithHistory({ detail: run({ id: 7, itc_at_risk: "90000.00" }) });
    const table = await screen.findByRole("region", { name: "Earlier reconciliation runs" });

    await user.click(screen.getByRole("button", { name: /View the run from/ }));
    await screen.findByRole("status");

    // The newest row now offers itself, and the one being shown says so
    // instead. Asked for by its own date so this cannot pass by clicking the
    // button that was already there.
    await user.click(
      within(table).getByRole("button", { name: /View the run from 02 Jun 2026/ }),
    );

    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    expect(screen.getByText(/Last run/)).toBeInTheDocument();
  });

  it("counts a run that never got as far as matching as none matched", async () => {
    // A run that failed or is still queued has no matched_count. Rendered
    // straight, the cell reads " / 3" — a blank where a number belongs, on the
    // one screen whose whole job is to show the figures moving between runs.
    renderWithHistory({
      history: [LATEST, { ...EARLIER, matched_count: null }],
    });
    const table = await screen.findByRole("region", { name: "Earlier reconciliation runs" });

    expect(within(table).getByText("0 / 3")).toBeInTheDocument();
  });

  it("does not report a superseded run list as one the server could not answer", async () => {
    // Changing month aborts the list in flight, and a real browser rejects
    // that request rather than resolving it. Treated as a failure it raises a
    // banner blaming the server for an outage that never happened — over a
    // month whose own list arrived perfectly well.
    const user = userEvent.setup();
    const body = (b, status = 200) =>
      Promise.resolve({
        ok: status < 400,
        status,
        statusText: "",
        text: async () => JSON.stringify(b),
      });
    global.fetch = vi.fn((url, options = {}) => {
      const path = String(url);
      if (/\/reconciliation\?/.test(path)) {
        // Only the month being left is held; the month arrived at answers
        // normally, so anything on screen at the end came from the abort.
        if (path.includes(SHOWN)) {
          return new Promise((_resolve, reject) => {
            options.signal.addEventListener("abort", () =>
              reject(new DOMException("The operation was aborted.", "AbortError")),
            );
          });
        }
        return body({ items: [LATEST, EARLIER], total: 2 });
      }
      if (path.includes("/gstr2b/periods")) return body({ items: [] });
      if (path.includes("/gstr2b/")) return body(imported());
      if (path.includes("/latest")) return body(run());
      return body({ detail: "Not found" }, 404);
    });
    render(
      <MemoryRouter>
        <StubAuth>
          <ReconcilePage />
        </StubAuth>
      </MemoryRouter>,
    );
    await screen.findByText(/invoices imported/);

    await selectPreviousPeriod(user);

    await screen.findByRole("region", { name: "Earlier reconciliation runs" });
    expect(screen.queryByText(/Could not load the earlier runs/)).not.toBeInTheDocument();
  });

  it("says why an earlier run would not open", async () => {
    // The row carries the counts but not the report, so opening one is a
    // request of its own and can fail on its own. Silently doing nothing looks
    // like a dead button on the screen that decides which credit is safe.
    const user = userEvent.setup();
    renderWithHistory({ detail: undefined });
    await screen.findByRole("region", { name: "Earlier reconciliation runs" });

    await user.click(screen.getByRole("button", { name: /View the run from/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not open the run/);
  });

  it("still lists a run whose timestamps did not survive the round trip", async () => {
    // A queued or failed run has no completed_at, and the row is the only place
    // it can be seen at all — labelling it by a blank date would render
    // "Invalid Date" in the table this page is read from.
    renderWithHistory({
      history: [{ ...LATEST, completed_at: null, created_at: null }, EARLIER],
    });
    const table = await screen.findByRole("region", { name: "Earlier reconciliation runs" });
    expect(within(table).getByText(/an unrecorded time/)).toBeInTheDocument();
  });

  it("says the earlier runs could not be loaded rather than showing none", async () => {
    // Empty and unknown are different answers, and only one of them means the
    // period has been reconciled once.
    mockApi({ imported2b: imported(), latest: run(), fail: undefined });
    global.fetch = vi.fn(async (url) => {
      const body = (b, status = 200) => ({
        ok: status < 400,
        status,
        statusText: "",
        text: async () => JSON.stringify(b),
      });
      if (/\/reconciliation\?/.test(String(url))) return body({ detail: "boom" }, 500);
      if (String(url).includes("/gstr2b/")) return body(imported());
      if (String(url).includes("/latest")) return body(run());
      return body({ detail: "Not found" }, 404);
    });
    render(
      <MemoryRouter>
        <StubAuth>
          <ReconcilePage />
        </StubAuth>
      </MemoryRouter>,
    );

    expect(await screen.findByText(/Could not load the earlier runs/)).toBeInTheDocument();
  });

  it("drops an earlier run that lands after the user has changed month", async () => {
    // Every figure on this screen is captioned by the period picker, so a run
    // belonging to another month has nowhere honest to go.
    const user = userEvent.setup();
    let release;
    const held = new Promise((resolve) => {
      release = resolve;
    });
    global.fetch = vi.fn(async (url) => {
      const body = (b, status = 200) => ({
        ok: status < 400,
        status,
        statusText: "",
        text: async () => JSON.stringify(b),
      });
      const path = String(url);
      if (/\/reconciliation\/\d+$/.test(path)) {
        await held;
        return body(run({ id: 7, itc_at_risk: "90000.00" }));
      }
      if (/\/reconciliation\?/.test(path)) {
        return body({ items: [LATEST, EARLIER], total: 2 });
      }
      if (path.includes("/gstr2b/periods")) return body({ items: [] });
      if (path.includes("/gstr2b/")) return body(imported());
      if (path.includes("/latest")) return body(run({ id: 9, itc_at_risk: "0.00" }));
      return body({ detail: "Not found" }, 404);
    });
    render(
      <MemoryRouter>
        <StubAuth>
          <ReconcilePage />
        </StubAuth>
      </MemoryRouter>,
    );
    await screen.findByRole("region", { name: "Earlier reconciliation runs" });
    await user.click(screen.getByRole("button", { name: /View the run from/ }));

    await selectPreviousPeriod(user);
    release();

    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  });
});


// The register's own problems are the ones the matcher cannot report. A
// supplier GSTIN that is missing or does not checksum comes back from a run
// as "missing in 2B", which is the same row a supplier who never filed
// produces — and the two are fixed in different places.
describe("the purchase register check", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  // Defaults to the month the picker opens on, unlike the fixtures above:
  // the panel is guarded on the report's period matching the one on screen,
  // so a report for another month is the "arrived late" case rather than
  // the ordinary one.
  function report(overrides = {}) {
    const issues = overrides.issues ?? [];
    return {
      period: currentPeriod(),
      ok: issues.every((issue) => issue.severity !== "error"),
      invoice_count: 3,
      error_count: issues.filter((issue) => issue.severity === "error").length,
      warning_count: issues.filter((issue) => issue.severity === "warning").length,
      ...overrides,
      issues,
    };
  }

  const MISSING_GSTIN = {
    invoice_id: 21,
    invoice_number: "DH/451",
    field: "counterparty_gstin",
    severity: "error",
    message: "Supplier GSTIN is missing; ITC cannot be claimed without it",
  };
  const MISSING_HSN = {
    invoice_id: 22,
    invoice_number: "NW/9",
    field: "hsn_code",
    severity: "warning",
    message: "HSN code is missing",
  };

  it("blames the books rather than the supplier for a GSTIN that is missing", async () => {
    mockApi({ imported2b: imported(), register: report({ issues: [MISSING_GSTIN] }) });
    renderPage();

    expect(await screen.findByText(/will stop an invoice matching/)).toBeInTheDocument();
    const table = screen.getByRole("region", {
      name: `Purchase register problems for ${periodLabel(currentPeriod())}`,
    });
    expect(
      within(table).getByText(/Supplier GSTIN is missing/),
    ).toBeInTheDocument();
    // The row is fixed by opening the invoice, so the number is a way in.
    expect(within(table).getByRole("link", { name: "DH/451" })).toHaveAttribute(
      "href",
      "/invoices/21",
    );
  });

  it("asks for the purchase register to be checked before the run, not after", async () => {
    mockApi({ imported2b: imported(), register: report({ issues: [MISSING_GSTIN] }) });
    renderPage();

    expect(
      await screen.findByText(/Fix these first, then run the reconciliation/),
    ).toBeInTheDocument();
  });

  it("lists the rows that block a match above the ones that merely ought to be fixed", async () => {
    // The server answers in invoice order, which buries the one row that
    // has to be corrected among a dozen that need not be.
    mockApi({
      imported2b: imported(),
      register: report({ issues: [MISSING_HSN, MISSING_GSTIN] }),
    });
    renderPage();

    const table = await screen.findByRole("region", {
      name: `Purchase register problems for ${periodLabel(currentPeriod())}`,
    });
    const severities = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getAllByRole("cell")[0].textContent);
    expect(severities).toEqual(["Error", "Warning"]);
  });

  it("does not say a warning will stop an invoice matching", async () => {
    // A missing HSN code is worth fixing before the credit is filed and has
    // nothing to do with whether 2B finds the row. Wording it as a blocker
    // would send someone to correct invoices that were going to match.
    mockApi({ imported2b: imported(), register: report({ issues: [MISSING_HSN] }) });
    renderPage();

    expect(
      await screen.findByText(/worth a look before you file the credit/),
    ).toBeInTheDocument();
    // The instruction is what must not appear: there is nothing to fix before
    // running, and the count above it would be zero.
    expect(
      screen.queryByText(/Fix these first, then run the reconciliation/),
    ).not.toBeInTheDocument();
  });

  it("counts the rows that block a match, not every issue in the register", async () => {
    mockApi({
      imported2b: imported(),
      register: report({
        issues: [MISSING_GSTIN, MISSING_HSN, { ...MISSING_GSTIN, invoice_id: 23 }],
      }),
    });
    renderPage();

    const line = await screen.findByText(/will stop an invoice matching/);
    expect(line.textContent).toMatch(/2 problems/);
  });

  it("says the unmatched rows are the supplier's side when the books are clean", async () => {
    mockApi({ imported2b: imported(), register: report({ issues: [] }) });
    renderPage();

    expect(
      await screen.findByText(/Anything unmatched below is the supplier's side/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/will stop an invoice matching/),
    ).not.toBeInTheDocument();
  });

  it("does not call a period's books clean when nothing is booked in it", async () => {
    // An empty register matches nothing, and "all your invoices check out"
    // over zero invoices is a reassurance about work that was never done.
    mockApi({
      imported2b: imported(),
      register: report({ issues: [], invoice_count: 0 }),
    });
    renderPage();

    expect(
      await screen.findByText(/No purchase invoices booked for/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/carry a supplier GSTIN that checks out/),
    ).not.toBeInTheDocument();
  });

  it("says nothing at all when the register could not be checked", async () => {
    // The default mock refuses this endpoint. Silence is the honest answer:
    // announcing a clean register on the strength of never having read it
    // sends someone chasing a supplier over a GSTIN they mistyped.
    mockApi({ imported2b: imported() });
    renderPage();

    await screen.findByText(/invoices imported/);
    expect(screen.queryByText(/Your purchase register/)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Anything unmatched below is the supplier's side/),
    ).not.toBeInTheDocument();
  });

  it("does not caption one month's register problems with another month's name", async () => {
    // The check follows the picker, and a slow answer for the month being
    // left would otherwise land under the month being arrived at — reporting
    // April's missing GSTIN as May's.
    const user = userEvent.setup();
    let release;
    const held = new Promise((resolve) => {
      release = resolve;
    });
    global.fetch = vi.fn(async (url) => {
      const body = (b, status = 200) => ({
        ok: status < 400,
        status,
        statusText: "",
        text: async () => JSON.stringify(b),
      });
      const path = String(url);
      if (path.includes("/filing/validate")) {
        await held;
        return body(report({ period: currentPeriod(), issues: [MISSING_GSTIN] }));
      }
      if (/\/reconciliation\?/.test(path)) return body({ items: [], total: 0 });
      if (path.includes("/gstr2b/periods")) return body({ items: [] });
      if (path.includes("/gstr2b/")) return body(imported());
      return body({ detail: "Not found" }, 404);
    });
    renderPage();

    const period = await selectPreviousPeriod(user);
    expect(period).not.toBe(currentPeriod());
    release();

    await waitFor(() =>
      expect(screen.queryByText(/will stop an invoice matching/)).not.toBeInTheDocument(),
    );
  });
});

// The picker offered a fixed twelve months and said nothing about which of
// them held a statement. Both halves of that were costing something: a new
// tenant stepped through months looking for the one they had imported, and a
// 2B older than a year had no option to select at all — so the runs stored
// against it, kept precisely as evidence for a reversal raised months later,
// could not be reached from the screen that holds them.
describe("the period picker", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  /** A month far enough back that the rolling twelve cannot reach it. */
  function longAgo(now = new Date()) {
    const date = new Date(now.getFullYear() - 2, now.getMonth(), 1);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
  }

  it("marks the months that actually have a statement", async () => {
    mockApi({ imported2b: imported(), periods: [currentPeriod()] });
    renderPage();

    await screen.findByText(/invoices imported/);
    const select = screen.getByLabelText("Period");
    const marked = [...select.options].filter((o) => o.text.includes("2B on file"));
    expect(marked).toHaveLength(1);
    expect(marked[0].value).toBe(currentPeriod());
  });

  it("reaches a period whose statement is older than the twelve it lists", async () => {
    const old = longAgo();
    mockApi({ imported2b: imported(), periods: [old] });
    renderPage();

    await screen.findByText(/invoices imported/);
    const select = screen.getByLabelText("Period");
    const option = [...select.options].find((o) => o.value === old);
    expect(option).toBeDefined();
    expect(option.text).toContain("2B on file");
  });

  it("keeps every month selectable when the list could not be loaded", async () => {
    // The marker is decoration. Losing it must leave the picker exactly as it
    // was before any of this existed — twelve months, all selectable.
    mockApi({ imported2b: imported(), fail: undefined });
    renderPage();

    await screen.findByText(/invoices imported/);
    const select = screen.getByLabelText("Period");
    expect(select.options).toHaveLength(12);
    expect([...select.options].some((o) => o.text.includes("2B on file"))).toBe(false);
  });

  it("does not blank the control when a payload arrives that is not a list", async () => {
    // Everything this list does is decorate a picker, and it renders through a
    // spread and a Set — so a malformed payload must not take down the screen
    // the import and the run live on.
    global.fetch = vi.fn(async (url) => {
      const body = (b, status = 200) => ({
        ok: status < 400,
        status,
        statusText: "",
        text: async () => JSON.stringify(b),
      });
      const path = String(url);
      if (path.includes("/gstr2b/periods")) return body({ oops: true });
      if (path.includes("/gstr2b/")) return body(imported());
      if (/\/reconciliation\?/.test(path)) return body({ items: [], total: 0 });
      return body({ detail: "Not found" }, 404);
    });
    renderPage();

    await screen.findByText(/invoices imported/);
    expect(screen.getByLabelText("Period").options).toHaveLength(12);
  });
});

describe("a viewer", () => {
  // The API answers 403 to both writes this screen makes — the 2B import and
  // the reconciliation run. Everything else on it is a read, and the split is
  // the whole claim of these tests: the two controls go, and not one finding,
  // figure or past run goes with them.
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("is not offered the import or the run", async () => {
    mockApi({ imported2b: imported(), latest: run() });
    renderPage({ role: "viewer" });
    await screen.findByText(/invoices imported/);

    expect(screen.queryByText(/^(Import|Replace) GSTR-2B$/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Run reconciliation/ })).toBeNull();
  });

  it("is left no hidden file input to drive", async () => {
    // The label is what a viewer would click, but the control is the input
    // behind it. Hiding only the label would leave a working file picker one
    // `dispatchEvent` away — and, in a browser, still reachable by tab.
    mockApi({ imported2b: imported(), latest: run() });
    renderPage({ role: "viewer" });
    await screen.findByText(/invoices imported/);

    expect(screen.queryByLabelText(/GSTR-2B$/)).toBeNull();
  });

  it("is told which role it holds and who can lift it", async () => {
    // Without this the screen is a 2B panel with nothing to do in it, which
    // reads as a page that failed to finish loading.
    mockApi({ imported2b: imported(), latest: run() });
    renderPage({ role: "viewer" });
    await screen.findByText(/invoices imported/);

    const notice = screen.getByText(/read-only/).closest(".banner");
    expect(notice).toHaveTextContent("Umang Traders Private Limited");
    expect(notice).toHaveTextContent("viewer");
    expect(notice).toHaveTextContent(/import GSTR-2B or run a reconciliation/);
  });

  it("keeps the findings, which are what it came to read", async () => {
    mockApi({ imported2b: imported(), latest: run() });
    renderPage({ role: "viewer" });

    // Every outcome, the ITC figures, and the link back to the invoice: what a
    // reconciliation found is exactly what someone without the authority to
    // re-run it is here for.
    expect(await screen.findByText("INV-2026-0042")).toBeInTheDocument();
    expect(screen.getByText("DH/451")).toBeInTheDocument();
    expect(screen.getByText("GHOST-1")).toBeInTheDocument();
    expect(screen.getByText("UNBOOKED-9")).toBeInTheDocument();
    expect(screen.getByText("₹72,000.00")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "INV-2026-0042" })).toHaveAttribute(
      "href",
      "/invoices/11",
    );
  });

  it("keeps the earlier runs, which are the evidence and not a write", async () => {
    // The reason the history exists at all — a run that said credit was at
    // risk in May, answering a reversal in November — is a question put to
    // whoever is reading, and reading is all a viewer does.
    const SHOWN = currentPeriod();
    mockApi({
      imported2b: imported(),
      latest: run({ id: 9, period: SHOWN, matched_count: 3, itc_at_risk: "0.00" }),
      history: [
        { id: 9, period: SHOWN, total_invoices: 3, matched_count: 3, itc_at_risk: "0.00" },
        {
          id: 7,
          period: SHOWN,
          total_invoices: 3,
          matched_count: 1,
          itc_at_risk: "90000.00",
          completed_at: "2026-05-14T10:01:02Z",
        },
      ],
    });
    renderPage({ role: "viewer" });

    const table = await screen.findByRole("region", { name: "Earlier reconciliation runs" });
    expect(within(table).getByText("₹90,000.00")).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: /View/ })).toBeInTheDocument();
  });

  it("keeps the period picker, so a viewer can read any month", async () => {
    mockApi({ imported2b: imported(), latest: run(), periods: [PERIOD] });
    renderPage({ role: "viewer" });
    await screen.findByText(/invoices imported/);

    expect(screen.getByLabelText("Period")).toBeEnabled();
  });

  it("leaves an owner both controls", async () => {
    // The other half: the gate is the role, not something that removed the
    // controls for everyone.
    mockApi({ imported2b: imported(), latest: run() });
    renderPage();
    await screen.findByText(/invoices imported/);

    expect(screen.getByText("Replace GSTR-2B")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run reconciliation/ })).toBeEnabled();
    expect(screen.queryByText(/read-only/)).toBeNull();
  });
});
