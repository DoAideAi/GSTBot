import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StubAuth } from "../test/auth";
import SuppliersPage from "./SuppliersPage";

function supplier(overrides = {}) {
  return {
    id: 1,
    gstin: "29AAGCB7383J1Z4",
    legal_name: "Northwind Supplies Pvt Ltd",
    trade_name: "Northwind",
    state_code: "29",
    compliance_score: 92,
    risk_level: "low",
    total_invoices: 24,
    matched_invoices: 22,
    mismatched_invoices: 1,
    missing_invoices: 1,
    late_filings: 0,
    last_filed_period: "2026-04",
    last_seen_at: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function scoreDetail(overrides = {}) {
  return {
    gstin: "29AAGCB7383J1Z4",
    score: 92,
    risk_level: "low",
    confidence: 0.85,
    components: [
      {
        name: "match_rate",
        score: 93.75,
        weight: 50,
        detail: "22 matched, 1 mismatched, 1 never filed, of 24",
      },
      { name: "timeliness", score: 100, weight: 20, detail: "Files on the due date" },
      {
        name: "consistency",
        score: 88,
        weight: 20,
        detail: "Match rate varies by 6 points across 3 periods",
      },
      { name: "recency", score: null, weight: 10, detail: "Never seen filing" },
    ],
    observations: [
      { period: "2026-02", matched: 6, mismatched: 0, missing: 1, filing_delay_days: 4 },
      { period: "2026-03", matched: 8, mismatched: 1, missing: 0, filing_delay_days: 0 },
      { period: "2026-04", matched: 8, mismatched: 0, missing: 0, filing_delay_days: null },
    ],
    invoices_observed: 24,
    periods_observed: 3,
    recommended_provision_pct: 6.8,
    recommendation: "Broadly reliable. Hold 6.8% of the credit until the 2B confirms it.",
    ...overrides,
  };
}

function detail(overrides = {}) {
  return {
    ...supplier(),
    score_detail: scoreDetail(),
    exposure: {
      invoice_count: 24,
      tax_total: "180000.00",
      tax_at_risk: "9000.00",
      unpaid_count: 2,
    },
    ...overrides,
  };
}

/**
 * Route by URL: the list refetches on every filter and search keystroke, and
 * the detail and rescore calls interleave with it.
 */
function mockApi({ items = [supplier()], detail: one = detail(), rescored = 3, fail } = {}) {
  global.fetch = vi.fn(async (url, options = {}) => {
    const target = String(url);
    const json = (body, status = 200) => ({
      ok: status < 400,
      status,
      statusText: status < 400 ? "OK" : "Error",
      text: async () => JSON.stringify(body),
    });

    if (fail) return json({ detail: fail.message }, fail.status);
    if (options.method === "POST" && target.includes("/suppliers/rescore")) {
      return json({ rescored, items: [] });
    }
    if (/\/suppliers\/\d+/.test(target)) return json(one);
    return json({ items, total: items.length });
  });
}

const renderPage = ({ role } = {}) =>
  render(
    <MemoryRouter>
      <StubAuth role={role}>
        <SuppliersPage />
      </StubAuth>
    </MemoryRouter>,
  );

/**
 * A fetch that hands back the levers instead of resolving on its own.
 *
 * Ordering bugs need the second answer to arrive before the first, which a
 * mock that resolves by itself can never produce.
 */
function deferredFetch() {
  const pending = [];
  global.fetch = vi.fn(
    (url, options = {}) =>
      new Promise((resolve, reject) => {
        pending.push({
          url: String(url),
          method: options.method ?? "GET",
          signal: options.signal,
          answer: (body, { status = 200 } = {}) =>
            resolve({
              ok: status < 400,
              status,
              statusText: "",
              text: async () => JSON.stringify(body),
            }),
        });
        options.signal?.addEventListener("abort", () => {
          const err = new Error("The operation was aborted.");
          err.name = "AbortError";
          reject(err);
        });
      }),
  );
  return pending;
}

/** Resolves once the list has replaced the loading placeholder. */
const loaded = (total = 1) =>
  screen.findByRole("heading", { name: `${total} supplier${total === 1 ? "" : "s"}` });

describe("SuppliersPage", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("lists a supplier with its risk band and counts", async () => {
    mockApi();
    renderPage();

    await loaded();
    expect(screen.getByText("Low risk")).toBeInTheDocument();
    expect(screen.getByText("Northwind Supplies Pvt Ltd")).toBeInTheDocument();
    expect(screen.getByText("29AAGCB7383J1Z4")).toBeInTheDocument();
    // The score renders as a meter, labelled for anyone not seeing the bar —
    // and named for the supplier, because a column of bars all called
    // "Compliance score" says nothing about which row is which.
    expect(
      screen.getByRole("progressbar", {
        name: "Compliance score for Northwind Supplies Pvt Ltd",
      }),
    ).toHaveAttribute("aria-valuetext", "92 of 100");
    expect(screen.getByText("April 2026")).toBeInTheDocument();
  });

  it("distinguishes an unrated supplier from a badly rated one", async () => {
    mockApi({
      items: [
        supplier({
          id: 2,
          compliance_score: null,
          risk_level: "unknown",
          last_filed_period: null,
        }),
      ],
    });
    renderPage();

    await loaded();
    // Scoped to the row: "Unrated" is also one of the filter buttons.
    const row = within(screen.getByRole("table"));
    expect(row.getByText("Unrated")).toBeInTheDocument();
    // Never an empty bar, which would read as a score of zero.
    expect(row.getByText("No evidence yet")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /out of 100/ })).not.toBeInTheDocument();
  });

  it("explains an empty register rather than showing a bare table", async () => {
    mockApi({ items: [] });
    renderPage();

    await loaded(0);
    expect(screen.getByText(/No suppliers yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  describe("when a filter matches nothing", () => {
    /** Rows for the whole register, nothing once a filter narrows it. */
    function mockFilterable() {
      global.fetch = vi.fn(async (url) => {
        const params = new URL(String(url), "http://localhost").searchParams;
        const narrowed = params.has("risk_level") || params.has("search");
        const items = narrowed ? [] : [supplier()];
        return {
          ok: true,
          status: 200,
          statusText: "OK",
          text: async () => JSON.stringify({ items, total: items.length }),
        };
      });
    }

    it("does not tell a populated register that it is empty", async () => {
      const user = userEvent.setup();
      mockFilterable();
      renderPage();
      await loaded();

      await user.click(screen.getByRole("button", { name: "High risk" }));

      expect(await screen.findByText("No suppliers match these filters.")).toBeInTheDocument();
      // "No suppliers yet" also explains why — none parsed, none reconciled —
      // and both halves are false when a risk chip is the reason.
      expect(screen.queryByText(/No suppliers yet/i)).not.toBeInTheDocument();
    });

    it("offers a way back to the whole register", async () => {
      const user = userEvent.setup();
      mockFilterable();
      renderPage();
      await loaded();

      await user.type(screen.getByRole("searchbox"), "zzz");
      await screen.findByText("No suppliers match these filters.");

      await user.click(screen.getByRole("button", { name: "Clear filters" }));

      expect(await screen.findByText("Northwind Supplies Pvt Ltd")).toBeInTheDocument();
      expect(screen.getByRole("searchbox")).toHaveValue("");
    });

    it("still explains an empty register when nothing is filtered", async () => {
      // The first-run screen has to survive the fix: a register with no
      // suppliers and no filters is the one case that sentence is for.
      mockApi({ items: [] });
      renderPage();

      await loaded(0);
      expect(screen.getByText(/No suppliers yet/i)).toBeInTheDocument();
      expect(screen.queryByText("No suppliers match these filters.")).not.toBeInTheDocument();
    });
  });

  it("opens the breakdown behind a supplier's score", async () => {
    const user = userEvent.setup();
    mockApi();
    renderPage();

    await loaded();
    await user.click(screen.getByRole("button", { name: "Details" }));

    const panel = (
      await screen.findByRole("heading", { name: "How the score is made up" })
    ).closest("section");

    expect(within(panel).getByText("Match rate")).toBeInTheDocument();
    expect(within(panel).getByText("Filing timeliness")).toBeInTheDocument();
    expect(
      within(panel).getByText("22 matched, 1 mismatched, 1 never filed, of 24"),
    ).toBeInTheDocument();
    // Confidence and the provisioning advice are the point of the panel.
    expect(within(panel).getByText("85%")).toBeInTheDocument();
    expect(within(panel).getByText("6.8%")).toBeInTheDocument();
    expect(
      within(panel).getByText(/Hold 6.8% of the credit until the 2B confirms it/),
    ).toBeInTheDocument();
  });

  it("shows a component with no evidence as unscored, not as zero", async () => {
    const user = userEvent.setup();
    mockApi();
    renderPage();

    await loaded();
    await user.click(screen.getByRole("button", { name: "Details" }));

    const panel = (
      await screen.findByRole("heading", { name: "How the score is made up" })
    ).closest("section");
    // Recency has never been observed; it must not render a zero-width bar.
    expect(within(panel).getByText("Never seen filing")).toBeInTheDocument();
    expect(within(panel).getByText("No evidence yet")).toBeInTheDocument();
  });

  it("reports the filing history newest first", async () => {
    const user = userEvent.setup();
    mockApi();
    renderPage();

    await loaded();
    await user.click(screen.getByRole("button", { name: "Details" }));

    const history = (await screen.findByRole("heading", { name: "Filing history" }))
      .nextElementSibling;
    const periods = within(history)
      .getAllByRole("row")
      .slice(1)
      .map((row) => row.cells[0].textContent);
    expect(periods).toEqual(["April 2026", "March 2026", "February 2026"]);

    expect(within(history).getByText("4 days late")).toBeInTheDocument();
    expect(within(history).getByText("On time")).toBeInTheDocument();
    // An unknown filing date is a dash, not "on time".
    expect(within(history).getByText("—")).toBeInTheDocument();
  });

  it("shows the credit currently resting on a supplier", async () => {
    const user = userEvent.setup();
    mockApi();
    renderPage();

    await loaded();
    await user.click(screen.getByRole("button", { name: "Details" }));

    const exposure = (await screen.findByRole("heading", { name: "Exposure right now" }))
      .nextElementSibling;
    expect(within(exposure).getByText("₹9,000.00")).toBeInTheDocument();
    expect(within(exposure).getByText("2")).toBeInTheDocument();
  });

  it("groups the credit at risk the way an Indian business reads it", async () => {
    // The API sends this as a decimal string, and this figure alone used to be
    // rendered with a bare ₹ in front of it rather than through `rupees` —
    // "₹180000.00" on the one screen whose job is saying how much credit a
    // single supplier is putting at risk. Lakh grouping is why `rupees` exists.
    const user = userEvent.setup();
    mockApi({ detail: detail({ exposure: {
      invoice_count: 24,
      tax_total: "900000.00",
      tax_at_risk: "180000.00",
      unpaid_count: 2,
    } }) });
    renderPage();

    await loaded();
    await user.click(screen.getByRole("button", { name: "Details" }));

    const exposure = (await screen.findByRole("heading", { name: "Exposure right now" }))
      .nextElementSibling;
    expect(within(exposure).getByText("₹1,80,000.00")).toBeInTheDocument();
  });

  it("shows a zero rather than a bare currency sign when there is no figure", async () => {
    const user = userEvent.setup();
    mockApi({ detail: detail({ exposure: {
      invoice_count: 0,
      tax_total: "0.00",
      tax_at_risk: null,
      unpaid_count: 0,
    } }) });
    renderPage();

    await loaded();
    await user.click(screen.getByRole("button", { name: "Details" }));

    const exposure = (await screen.findByRole("heading", { name: "Exposure right now" }))
      .nextElementSibling;
    expect(within(exposure).getByText("₹0.00")).toBeInTheDocument();
  });

  it("closes the detail panel again", async () => {
    const user = userEvent.setup();
    mockApi();
    renderPage();

    await loaded();
    await user.click(screen.getByRole("button", { name: "Details" }));
    await screen.findByRole("heading", { name: "How the score is made up" });

    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(
      screen.queryByRole("heading", { name: "How the score is made up" }),
    ).not.toBeInTheDocument();
  });

  describe("reaching the detail panel without a mouse", () => {
    // The panel renders above the table it is opened from. So tabbing on from
    // the Details button walks *away* from what the click produced, and a
    // keyboard user never arrives at it at all — the click appears to have
    // done nothing. Focus is what makes the button report its own result.

    it("moves focus into the panel when it opens", async () => {
      const user = userEvent.setup();
      mockApi();
      renderPage();

      await loaded();
      await user.click(screen.getByRole("button", { name: "Details" }));

      const panel = await screen.findByRole("region", {
        name: "Northwind Supplies Pvt Ltd",
      });
      await waitFor(() => expect(panel).toHaveFocus());
    });

    it("names the panel by the supplier in it", async () => {
      // Not by a fixed caption. The panel is one slot that several rows open,
      // and "Supplier detail" gives a screen reader no way to tell which
      // supplier it landed on.
      const user = userEvent.setup();
      mockApi();
      renderPage();

      await loaded();
      await user.click(screen.getByRole("button", { name: "Details" }));

      expect(
        await screen.findByRole("region", { name: "Northwind Supplies Pvt Ltd" }),
      ).toBeInTheDocument();
    });

    it("does not add a tab stop everyone has to pass through", async () => {
      // tabIndex -1: a programmatic target, not a new stop on the way to the
      // table below it.
      const user = userEvent.setup();
      mockApi();
      renderPage();

      await loaded();
      await user.click(screen.getByRole("button", { name: "Details" }));

      const panel = await screen.findByRole("region", {
        name: "Northwind Supplies Pvt Ltd",
      });
      expect(panel).toHaveAttribute("tabindex", "-1");
    });

    it("puts focus back on the row that opened it when it closes", async () => {
      // Focus was sitting on a Close button about to be unmounted, so the
      // browser dropped it to <body> and the next Tab restarted from the top
      // of the document — past the header, the filters and every row above.
      const user = userEvent.setup();
      mockApi();
      renderPage();

      await loaded();
      const trigger = screen.getByRole("button", { name: "Details" });
      await user.click(trigger);
      await screen.findByRole("heading", { name: "How the score is made up" });

      await user.click(screen.getByRole("button", { name: "Close" }));

      expect(trigger).toHaveFocus();
    });

    it("closes on Escape, like the nav drawer and the switcher", async () => {
      const user = userEvent.setup();
      mockApi();
      renderPage();

      await loaded();
      await user.click(screen.getByRole("button", { name: "Details" }));
      await screen.findByRole("heading", { name: "How the score is made up" });

      await user.keyboard("{Escape}");

      await waitFor(() =>
        expect(
          screen.queryByRole("heading", { name: "How the score is made up" }),
        ).not.toBeInTheDocument(),
      );
    });

    it("returns focus to the row on Escape too", async () => {
      const user = userEvent.setup();
      mockApi();
      renderPage();

      await loaded();
      const trigger = screen.getByRole("button", { name: "Details" });
      await user.click(trigger);
      await screen.findByRole("heading", { name: "How the score is made up" });

      await user.keyboard("{Escape}");

      await waitFor(() => expect(trigger).toHaveFocus());
    });

    it("stops listening for Escape once the panel is gone", async () => {
      // The listener is on `document`, so an un-removed one would keep firing
      // `onClose` on every Escape pressed anywhere on the page afterwards —
      // including the one that dismisses the browser's own find bar.
      const user = userEvent.setup();
      const remove = vi.spyOn(document, "removeEventListener");
      mockApi();
      renderPage();

      await loaded();
      await user.click(screen.getByRole("button", { name: "Details" }));
      await screen.findByRole("heading", { name: "How the score is made up" });
      await user.click(screen.getByRole("button", { name: "Close" }));

      expect(remove).toHaveBeenCalledWith("keydown", expect.any(Function));
    });
  });

  describe("the score bars in the breakdown", () => {
    it("reports each component as a progress bar named for its component", async () => {
      // They were `role="img"` captioned "94 out of 100": four pictures, none
      // of which said which component it was a picture of, while the
      // identical-looking bar on the dashboard was a progressbar carrying its
      // value and range. One widget, two readings, one set of tests.
      const user = userEvent.setup();
      mockApi();
      renderPage();

      await loaded();
      await user.click(screen.getByRole("button", { name: "Details" }));

      const bar = await screen.findByRole("progressbar", { name: "Match rate score" });
      expect(bar).toHaveAttribute("aria-valuenow", "94");
      expect(bar).toHaveAttribute("aria-valuemax", "100");
    });

    it("still renders an unscored component as words rather than an empty bar", async () => {
      // `recency` has no score in the fixture. A bar at zero would read as
      // "scored zero" instead of "never seen filing".
      const user = userEvent.setup();
      mockApi();
      renderPage();

      await loaded();
      await user.click(screen.getByRole("button", { name: "Details" }));

      expect(await screen.findByText("No evidence yet")).toBeInTheDocument();
      expect(screen.queryByRole("progressbar", { name: "Recency score" })).toBeNull();
    });
  });

  it("filters the list by risk band", async () => {
    const user = userEvent.setup();
    mockApi();
    renderPage();

    await loaded();
    await user.click(screen.getByRole("button", { name: "High risk" }));

    await waitFor(() =>
      expect(global.fetch.mock.calls.at(-1)[0]).toContain("risk_level=high"),
    );

    // "All" clears the filter rather than sending an empty parameter.
    await user.click(screen.getByRole("button", { name: "All" }));
    await waitFor(() =>
      expect(global.fetch.mock.calls.at(-1)[0]).not.toContain("risk_level"),
    );
  });

  it("searches by name or GSTIN", async () => {
    const user = userEvent.setup();
    mockApi();
    renderPage();

    await loaded();
    await user.type(screen.getByRole("searchbox"), "north");

    await waitFor(() =>
      expect(global.fetch.mock.calls.at(-1)[0]).toContain("search=north"),
    );
  });

  describe("a search the user is still typing into", () => {
    /**
     * A fetch that hands each request back to the test instead of answering it.
     *
     * The bug this covers is an ordering one, so the test has to be able to
     * answer the *second* request before the first. A mock that resolves on its
     * own can only ever answer them in order, which is the one case that was
     * never broken.
     */
    function deferredFetch() {
      const pending = [];
      global.fetch = vi.fn(
        (url, options = {}) =>
          new Promise((resolve, reject) => {
            const entry = {
              url: String(url),
              signal: options.signal,
              answer: (body) =>
                resolve({
                  ok: true,
                  status: 200,
                  statusText: "OK",
                  text: async () => JSON.stringify(body),
                }),
            };
            // Rejecting the way the real thing does: an aborted fetch does not
            // resolve with a partial answer, it rejects with an AbortError.
            options.signal?.addEventListener("abort", () => {
              const err = new Error("The operation was aborted.");
              err.name = "AbortError";
              reject(err);
            });
            pending.push(entry);
          }),
      );
      return pending;
    }

    const named = (name) => supplier({ id: name.length, legal_name: name });

    it("abandons the request the next keystroke supersedes", async () => {
      const user = userEvent.setup();
      const pending = deferredFetch();
      renderPage();

      await waitFor(() => expect(pending).toHaveLength(1));
      pending[0].answer({ items: [named("Northwind Supplies Pvt Ltd")], total: 1 });
      await loaded();

      await user.type(screen.getByRole("searchbox"), "no");
      await waitFor(() => expect(pending.length).toBeGreaterThan(2));

      // Everything before the newest request has been called off. Each of them
      // describes a search term the box no longer holds.
      const superseded = pending.slice(1, -1);
      expect(superseded.length).toBeGreaterThan(0);
      superseded.forEach((request) => expect(request.signal.aborted).toBe(true));
      expect(pending.at(-1).signal.aborted).toBe(false);
    });

    it("does not let a slow earlier answer overwrite a newer one", async () => {
      const user = userEvent.setup();
      const pending = deferredFetch();
      renderPage();

      await waitFor(() => expect(pending).toHaveLength(1));
      pending[0].answer({ items: [named("Northwind Supplies Pvt Ltd")], total: 1 });
      await loaded();

      await user.type(screen.getByRole("searchbox"), "no");
      await waitFor(() => expect(pending.length).toBeGreaterThan(2));

      // The newest request answers first, which is the whole point: responses
      // do not come back in the order they were sent.
      const newest = pending.at(-1);
      expect(newest.url).toContain("search=no");
      newest.answer({ items: [named("Nordic Tooling")], total: 1 });
      await screen.findByText("Nordic Tooling");

      // Now the request for "n" finally lands. It was aborted, so its answer
      // never reaches the page — before this, it repainted the table with rows
      // for a term the search box had already moved past.
      pending[1].answer({ items: [named("Ansel Metals"), named("Bharat Cables")], total: 2 });

      await waitFor(() => expect(screen.getByText("Nordic Tooling")).toBeInTheDocument());
      expect(screen.queryByText("Ansel Metals")).not.toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "1 supplier" })).toBeInTheDocument();
    });

    it("does not raise an error banner for a request it cancelled itself", async () => {
      const user = userEvent.setup();
      const pending = deferredFetch();
      renderPage();

      await waitFor(() => expect(pending).toHaveLength(1));
      pending[0].answer({ items: [named("Northwind Supplies Pvt Ltd")], total: 1 });
      await loaded();

      await user.type(screen.getByRole("searchbox"), "no");
      await waitFor(() => expect(pending.length).toBeGreaterThan(2));
      pending.at(-1).answer({ items: [named("Nordic Tooling")], total: 1 });

      await screen.findByText("Nordic Tooling");
      // "signal is aborted without reason" in front of someone who simply kept
      // typing would be worse than the stale rows the abort exists to prevent.
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });

  it("rescores every supplier and reloads the list", async () => {
    const user = userEvent.setup();
    mockApi({ rescored: 3 });
    renderPage();

    await loaded();
    await user.click(screen.getByRole("button", { name: "Rescore all" }));

    expect(await screen.findByText("Rescored 3 supplier(s)")).toBeInTheDocument();
    const posted = global.fetch.mock.calls.find(([, options]) => options?.method === "POST");
    expect(posted[0]).toContain("/suppliers/rescore");
    // The list is refetched afterwards, so the screen reflects the new scores.
    expect(global.fetch.mock.calls.at(-1)[0]).toContain("/suppliers");
    expect(global.fetch.mock.calls.at(-1)[1]?.method ?? "GET").toBe("GET");
  });

  it("surfaces an API failure", async () => {
    mockApi({ fail: { status: 403, message: "This business has been deactivated. Contact support to reactivate it." } });
    renderPage();

    expect(await screen.findByText("This business has been deactivated. Contact support to reactivate it.")).toBeInTheDocument();
  });

  /**
   * The list loads, and a later call fails. `mockApi`'s `fail` breaks every
   * request, which would never get us past the placeholder — so these route
   * the failure at one URL and leave the rest working.
   */
  describe("when a follow-up call fails after the list is on screen", () => {
    function mockApiFailing(predicate, { status = 500, message = "Server error" } = {}) {
      global.fetch = vi.fn(async (url, options = {}) => {
        const target = String(url);
        const json = (body, code = 200) => ({
          ok: code < 400,
          status: code,
          statusText: code < 400 ? "OK" : "Error",
          text: async () => JSON.stringify(body),
        });

        if (predicate(target, options)) return json({ detail: message }, status);
        if (options.method === "POST" && target.includes("/suppliers/rescore")) {
          return json({ rescored: 3, items: [] });
        }
        if (/\/suppliers\/\d+/.test(target)) return json(detail());
        return json({ items: [supplier()], total: 1 });
      });
    }

    it("does not leave the old rows under a search they do not match", async () => {
      // The register is captioned by the search box and the risk chip alone,
      // so rows that survive a failed search are being asserted to match a
      // term they were never tested against — and the count above them says
      // how many suppliers matched it.
      const user = userEvent.setup();
      mockApiFailing((url) => url.includes("search="), {
        status: 500,
        message: "Search is unavailable",
      });
      renderPage();
      await loaded();

      await user.type(screen.getByRole("searchbox"), "Northwind");

      expect(await screen.findByText("Search is unavailable")).toBeInTheDocument();
      expect(screen.queryByText(/Northwind Supplies Pvt Ltd/)).not.toBeInTheDocument();
      // Nor does it answer the search on the strength of never having run it.
      // "No suppliers match these filters" is a finding about the register, and
      // a failed search establishes nothing about who is in it.
      expect(
        screen.queryByText("No suppliers match these filters."),
      ).not.toBeInTheDocument();
      expect(screen.queryByText(/No suppliers yet/i)).not.toBeInTheDocument();
      // Nor in the heading, which is the more emphatic place to say it.
      expect(
        screen.queryByRole("heading", { name: /^0 suppliers$/ }),
      ).not.toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Suppliers", level: 2 })).toBeInTheDocument();
    });

    it("keeps the list when one supplier's detail cannot be opened", async () => {
      const user = userEvent.setup();
      mockApiFailing((url) => /\/suppliers\/\d+/.test(url), {
        status: 404,
        message: "Supplier not found",
      });
      renderPage();

      await loaded();
      await user.click(screen.getByRole("button", { name: "Details" }));

      expect(await screen.findByText("Supplier not found")).toBeInTheDocument();
      // The row it was opened from is still there — a failed drill-down must
      // not take the register with it.
      expect(screen.getByText("Northwind Supplies Pvt Ltd")).toBeInTheDocument();
    });

    it("reports a rescore that did not run", async () => {
      const user = userEvent.setup();
      mockApiFailing(
        (url, options) => options.method === "POST" && url.includes("/suppliers/rescore"),
        { status: 503, message: "Scoring is backed up, try again shortly" },
      );
      renderPage();

      await loaded();
      await user.click(screen.getByRole("button", { name: "Rescore all" }));

      expect(
        await screen.findByText("Scoring is backed up, try again shortly"),
      ).toBeInTheDocument();
      // No success notice alongside the error, and the button is usable again.
      expect(screen.queryByText(/Rescored/)).not.toBeInTheDocument();
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Rescore all" })).not.toBeDisabled(),
      );
    });
  });

  describe("the last-filed column", () => {
    it("falls back to when the supplier was last seen if they have never filed", async () => {
      mockApi({
        items: [supplier({ last_filed_period: null, last_seen_at: "2026-03-09" })],
      });
      renderPage();

      await loaded();
      expect(screen.getByText("09 Mar 2026")).toBeInTheDocument();
    });

    it("shows a dash for a supplier that has neither filed nor been seen", async () => {
      mockApi({ items: [supplier({ last_filed_period: null, last_seen_at: null })] });
      renderPage();

      await loaded();
      const row = screen.getByText("29AAGCB7383J1Z4").closest("tr");
      expect(within(row).getByText("—")).toBeInTheDocument();
    });
  });

  // The list load is aborted when the filters move. Neither of these is that
  // load: they are started by a button rather than by the filters, and the
  // filters stay live while they run.
  describe("when the filters change while a request is in flight", () => {
    it("reloads under the filters on screen, not the ones the rescore began with", async () => {
      const user = userEvent.setup();
      const pending = deferredFetch();
      renderPage();

      await waitFor(() => expect(pending).toHaveLength(1));
      pending[0].answer({ items: [supplier()], total: 1 });
      await loaded();

      // Rescoring walks every supplier's whole reconciliation history, so it
      // is slow enough that narrowing the list while it runs is ordinary.
      await user.click(screen.getByRole("button", { name: "Rescore all" }));
      await waitFor(() => expect(pending).toHaveLength(2));
      expect(pending[1].method).toBe("POST");

      await user.click(screen.getByRole("button", { name: "High risk" }));
      await waitFor(() => expect(pending).toHaveLength(3));
      expect(pending[2].url).toContain("risk_level=high");
      pending[2].answer({ items: [], total: 0 });

      pending[1].answer({ rescored: 3, items: [] });

      // The refresh the rescore asks for has to describe the chip that is
      // pressed. Reloading under the filters captured when the button was
      // clicked put the whole register back on screen with "High risk" still
      // selected — and, being started by hand rather than by the effect, that
      // load carried no signal, so nothing could cancel it either.
      await waitFor(() => expect(pending).toHaveLength(4));
      expect(pending[3].url).toContain("risk_level=high");
    });

    it("keeps the breakdown of the supplier asked for last", async () => {
      const user = userEvent.setup();
      const pending = deferredFetch();
      renderPage();

      await waitFor(() => expect(pending).toHaveLength(1));
      pending[0].answer({
        items: [
          supplier(),
          supplier({ id: 2, gstin: "27AACCM6094J1Z3", legal_name: "Deccan Hardware" }),
        ],
        total: 2,
      });
      await loaded(2);

      const [first, second] = screen.getAllByRole("button", { name: "Details" });
      await user.click(first);
      await waitFor(() => expect(pending).toHaveLength(2));
      await user.click(second);
      await waitFor(() => expect(pending).toHaveLength(3));

      // The second click answers first, which is the whole point.
      pending[2].answer(
        detail({ id: 2, gstin: "27AACCM6094J1Z3", legal_name: "Deccan Hardware" }),
      );
      await screen.findByRole("heading", { name: "Deccan Hardware" });

      pending[1].answer(detail());

      // The panel is one slot, so a late first answer simply replaced the
      // second — the breakdown, the provision and the exposure all swapped to
      // a supplier the user had already clicked past.
      await waitFor(() =>
        expect(screen.getByRole("heading", { name: "Deccan Hardware" })).toBeInTheDocument(),
      );
      expect(
        screen.queryByRole("heading", { name: "Northwind Supplies Pvt Ltd" }),
      ).not.toBeInTheDocument();
    });

    it("does not banner a superseded breakdown's failure over the one that loaded", async () => {
      const user = userEvent.setup();
      const pending = deferredFetch();
      renderPage();

      await waitFor(() => expect(pending).toHaveLength(1));
      pending[0].answer({
        items: [
          supplier(),
          supplier({ id: 2, gstin: "27AACCM6094J1Z3", legal_name: "Deccan Hardware" }),
        ],
        total: 2,
      });
      await loaded(2);

      const [first, second] = screen.getAllByRole("button", { name: "Details" });
      await user.click(first);
      await waitFor(() => expect(pending).toHaveLength(2));
      await user.click(second);
      await waitFor(() => expect(pending).toHaveLength(3));

      pending[2].answer(
        detail({ id: 2, gstin: "27AACCM6094J1Z3", legal_name: "Deccan Hardware" }),
      );
      await screen.findByRole("heading", { name: "Deccan Hardware" });

      // The refusal is about a supplier the user has already clicked past, so
      // its banner would sit over a breakdown that loaded perfectly well.
      pending[1].answer({ detail: "Supplier 1 could not be scored." }, { status: 500 });

      await waitFor(() =>
        expect(screen.getByRole("heading", { name: "Deccan Hardware" })).toBeInTheDocument(),
      );
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });

  /**
   * The fallbacks that only run on the rows nobody fixtures.
   *
   * Every test above builds its suppliers off `supplier()`, which carries a
   * legal name, a known risk level and a score in the nineties. So the naming
   * fallback, the unrecognised-risk branch and the warning banner have run
   * exactly zero times across this file — they are covered by line count
   * because the components that hold them render, not because anything
   * asserted what they do. Each one below is reachable from real API data:
   * the GSTIN lookup returns suppliers with no legal name, `risk_level` is a
   * string the backend is free to extend, and a score under 60 is the whole
   * point of scoring.
   */
  describe("rows the fixtures do not cover", () => {
    it("falls back to the trade name when a supplier has no legal name", async () => {
      mockApi({ items: [supplier({ legal_name: null })] });
      renderPage();
      await loaded();

      expect(screen.getByText("Northwind")).toBeInTheDocument();
    });

    it("shows a dash rather than a blank cell when a supplier has neither name", async () => {
      // Both names absent is what a supplier first seen in a 2B looks like:
      // the GSTIN is all the portal gave us. A blank cell there reads as a
      // rendering bug rather than as missing data.
      mockApi({ items: [supplier({ legal_name: null, trade_name: null })] });
      renderPage();
      await loaded();

      expect(screen.getByText("—")).toBeInTheDocument();
      expect(screen.getByText("29AAGCB7383J1Z4")).toBeInTheDocument();
    });

    it("heads the breakdown with the GSTIN when a supplier has no name at all", async () => {
      // The detail panel has its own fallback chain, ending at the GSTIN
      // rather than at a dash — a panel titled "—" tells the reader nothing
      // about which supplier they opened.
      const user = userEvent.setup();
      const nameless = { legal_name: null, trade_name: null };
      mockApi({
        items: [supplier(nameless)],
        detail: detail(nameless),
      });
      renderPage();
      await loaded();

      await user.click(screen.getByRole("button", { name: "Details" }));

      await screen.findByRole("heading", { name: "29AAGCB7383J1Z4" });
    });

    it("prints a scoring component it has no label for under its own name", async () => {
      // `COMPONENT_LABELS[name] ?? name`. The backend owns the component list
      // and can add to it; a new one must show up in the breakdown as
      // `dispute_rate` rather than as an empty cell the reader cannot ask
      // about.
      const user = userEvent.setup();
      mockApi({
        detail: detail({
          score_detail: scoreDetail({
            components: [
              { name: "dispute_rate", score: 70, weight: 100, detail: "One open dispute" },
            ],
          }),
        }),
      });
      renderPage();
      await loaded();

      await user.click(screen.getByRole("button", { name: "Details" }));

      expect(await screen.findByText("dispute_rate")).toBeInTheDocument();
    });

    it("shows a dash for a supplier there is not yet enough evidence to score", async () => {
      // A supplier seen on one invoice in one period has no filing history to
      // score against, and the backend sends the score as null rather than
      // inventing a zero. Rendering that null as an empty cell reads as a
      // score of nothing, which is the opposite claim — the dash says the
      // score is unknown, which is what the confidence figure beside it is
      // there to qualify.
      const user = userEvent.setup();
      mockApi({
        detail: detail({
          score_detail: scoreDetail({
            score: null,
            risk_level: "unknown",
            confidence: 0.1,
            invoices_observed: 1,
            periods_observed: 1,
          }),
        }),
      });
      renderPage();
      await loaded();

      await user.click(screen.getByRole("button", { name: "Details" }));

      // Scoped to the panel's key-value block: "Score" also heads a column of
      // the table listing it, and another of the table behind the panel.
      const panel = (await screen.findByRole("heading", { name: /Northwind|29AAG/ })).closest(
        "section",
      );
      const score = within(panel.querySelector(".kv")).getByText("Score").closest("div");
      expect(within(score).getByText("—")).toBeInTheDocument();
    });

    it("labels a risk level it does not recognise as unrated", async () => {
      // `RISK[level] ?? RISK.unknown`. A backend that adds a `critical` level
      // before the frontend learns the word must not render an unstyled chip
      // with no text in it.
      mockApi({ items: [supplier({ risk_level: "critical" })] });
      renderPage();
      await loaded();

      // Scoped to the row: the risk filter above the table offers "Unrated"
      // as an option, so an unscoped query passes on the dropdown alone.
      expect(within(screen.getByRole("table")).getByText("Unrated")).toBeInTheDocument();
    });

    it("warns on the recommendation when the score is below 60", async () => {
      const user = userEvent.setup();
      mockApi({
        items: [supplier({ compliance_score: 41, risk_level: "high" })],
        detail: detail({
          score_detail: scoreDetail({
            score: 41,
            risk_level: "high",
            recommendation: "Hold 30% of the credit until this supplier files.",
          }),
        }),
      });
      renderPage();
      await loaded();

      await user.click(screen.getByRole("button", { name: "Details" }));

      const banner = await screen.findByRole("status");
      expect(banner).toHaveTextContent("Hold 30% of the credit");
      expect(banner).toHaveClass("banner-warn");
    });

    it("leaves the recommendation neutral when the score clears 60", async () => {
      // The paired case. Without it, a banner hard-coded to `banner-warn`
      // would satisfy the test above and mark every supplier as a problem.
      const user = userEvent.setup();
      mockApi();
      renderPage();
      await loaded();

      await user.click(screen.getByRole("button", { name: "Details" }));

      const banner = await screen.findByRole("status");
      expect(banner).toHaveClass("banner-neutral");
    });
  });
});

describe("a viewer", () => {
  afterEach(() => vi.restoreAllMocks());

  it("is not offered the rescore", async () => {
    mockApi();
    renderPage({ role: "viewer" });
    await loaded();

    expect(screen.queryByRole("button", { name: /Rescore all/ })).toBeNull();
  });

  it("keeps the scores, which are the whole read", async () => {
    // No notice on this screen on purpose: the table is still complete, and a
    // list that lost one button does not read as broken. Bannering every page
    // in the app would make the notice something people stop seeing.
    mockApi();
    renderPage({ role: "viewer" });

    await loaded();
    expect(screen.getByText("Northwind Supplies Pvt Ltd")).toBeInTheDocument();
    expect(screen.queryByText(/read-only/)).toBeNull();
  });

  it("leaves an owner the rescore", async () => {
    mockApi();
    renderPage();
    await loaded();

    expect(screen.getByRole("button", { name: /Rescore all/ })).toBeInTheDocument();
  });
});

describe("SuppliersPage beyond the first page", () => {
  // The heading counted every supplier ("120 suppliers") and the table showed
  // the API's first page of fifty with no way on: the rest of the register —
  // the lower-risk end, since the list is riskiest first — was out of reach
  // except by searching for a name already known.
  function server(total) {
    const all = Array.from({ length: total }, (_, i) =>
      supplier({ id: i + 1, legal_name: `Supplier ${i + 1}`, trade_name: null }),
    );
    global.fetch = vi.fn(async (url) => {
      const u = new URL(String(url), "http://x");
      const limit = Number(u.searchParams.get("limit") ?? 50);
      const offset = Number(u.searchParams.get("offset") ?? 0);
      return {
        ok: true,
        status: 200,
        statusText: "",
        text: async () => JSON.stringify({ items: all.slice(offset, offset + limit), total: all.length }),
      };
    });
  }

  function renderSuppliers() {
    return render(
      <MemoryRouter>
        <StubAuth>
          <SuppliersPage />
        </StubAuth>
      </MemoryRouter>,
    );
  }

  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("pages through all of them", async () => {
    server(120);
    const user = userEvent.setup();
    renderSuppliers();
    expect(await screen.findByText("1–50 of 120")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("51–100 of 120")).toBeInTheDocument();
    expect(await screen.findByText("Supplier 51")).toBeInTheDocument();
    expect(String(global.fetch.mock.calls.at(-1)[0])).toContain("offset=50");
  });

  it("starts a new search from the first page", async () => {
    server(120);
    const user = userEvent.setup();
    renderSuppliers();
    await screen.findByText("1–50 of 120");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("51–100 of 120");

    await user.type(screen.getByRole("searchbox"), "S");

    await waitFor(() => expect(String(global.fetch.mock.calls.at(-1)[0])).not.toContain("offset=50"));
  });

  it("shows no pager when everything fits on one page", async () => {
    server(3);
    renderSuppliers();
    await screen.findByText("Supplier 1");
    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
  });

  describe("a page that emptied behind the user", () => {
    // P36 M9, as on the invoice register: a page past the end came back empty
    // and read as "No suppliers yet" over suppliers that exist.
    it("steps back to the last page there is", async () => {
      const offsets = [];
      global.fetch = vi.fn(async (url) => {
        const target = String(url);
        const from = Number(new URL(target, "http://localhost").searchParams.get("offset") ?? 0);
        offsets.push(from);
        const body =
          offsets.length === 1
            ? { items: [supplier()], total: 120 }
            : from >= 30
              ? { items: [], total: 30 }
              : { items: [supplier({ id: 9, legal_name: "Still Here Traders", trade_name: "Still Here Traders" })], total: 30 };
        return {
          ok: true,
          status: 200,
          statusText: "OK",
          text: async () => JSON.stringify({ ...body, limit: 50, offset: from }),
        };
      });
      render(
        <MemoryRouter>
          <StubAuth>
            <SuppliersPage />
          </StubAuth>
        </MemoryRouter>,
      );
      await userEvent.click(await screen.findByRole("button", { name: "Next" }));

      expect(await screen.findByText("Still Here Traders")).toBeInTheDocument();
      expect(screen.queryByText(/No suppliers yet/)).not.toBeInTheDocument();
      expect(offsets).toEqual([0, 50, 0]);
    });
  });
});
