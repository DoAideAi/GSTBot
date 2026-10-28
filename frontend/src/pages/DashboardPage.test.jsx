import { render, screen, waitFor, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StubAuth } from "../test/auth";
import DashboardPage, { deadlineBanner } from "./DashboardPage";

const BUCKET = {
  count: 0,
  taxable_value: "0.00",
  cgst: "0.00",
  sgst: "0.00",
  igst: "0.00",
  cess: "0.00",
  total_tax: "0.00",
  total_value: "0.00",
};

function dashboard(overrides = {}) {
  return {
    business_gstin: "27AAPFU0939F1ZV",
    business_name: "Umang Traders",
    period: "2026-04",
    counts: { total: 3, sales: 1, purchase: 2, by_status: { parsed: 3 }, needs_review: 1 },
    sales: { ...BUCKET, count: 1, igst: "18000.00", total_tax: "18000.00" },
    purchase: { ...BUCKET, count: 2, igst: "9000.00", total_tax: "9000.00" },
    // Every purchase claimable, which is the ordinary case. The tests below
    // that care about the difference set `credit` lower than `purchase`.
    credit: { ...BUCKET, count: 2, igst: "9000.00", total_tax: "9000.00" },
    net_liability: {
      cgst: "0.00",
      sgst: "0.00",
      igst: "9000.00",
      cess: "0.00",
      total: "9000.00",
    },
    output_tax: "18000.00",
    input_tax_credit: "9000.00",
    itc_at_risk: "0.00",
    plan_usage: {
      plan: "free",
      invoices_this_month: 3,
      monthly_limit: 50,
      remaining: 47,
    },
    recent_periods: [],
    open_alerts: 0,
    next_due_date: "2026-05-20",
    gstr1_due_date: "2026-05-11",
    last_reconciliation: null,
    ...overrides,
  };
}

function mockDashboard(body) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: "",
    text: async () => JSON.stringify(body),
  });
}

function renderPage({ role } = {}) {
  return render(
    <MemoryRouter>
      <StubAuth role={role}>
        <DashboardPage />
      </StubAuth>
    </MemoryRouter>,
  );
}

/** A tile by its label — the figures repeat further down the page. */
function statCard(container, label) {
  const card = [...container.querySelectorAll(".stat-card")].find(
    (node) => node.querySelector(".stat-label")?.textContent === label,
  );
  if (!card) throw new Error(`no stat card labelled "${label}"`);
  return card;
}

describe("DashboardPage", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("shows the headline figures in rupees", async () => {
    mockDashboard(dashboard());
    renderPage();

    // The headline figure shows in the stat tile and again in the tax
    // breakdown, so this is findAll rather than find.
    expect((await screen.findAllByText(/₹18,000.00/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/₹9,000.00/).length).toBeGreaterThan(0);
  });

  it("identifies the business", async () => {
    mockDashboard(dashboard());
    renderPage();
    expect(await screen.findByText(/27AAPFU0939F1ZV/)).toBeInTheDocument();
  });

  it("breaks tax down per head", async () => {
    mockDashboard(dashboard());
    renderPage();

    // Each head is shown separately because credit cannot be pooled across
    // them — a single netted figure would misstate what is actually payable.
    expect(await screen.findByRole("row", { name: /IGST/ })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /CGST/ })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /SGST/ })).toBeInTheDocument();
  });

  it("shows claimable credit in the credit column, not every purchase", async () => {
    // The two are different figures and the API sends both. `purchase` is the
    // tax on every purchase; `credit` is the claimable part — excluding what is
    // blocked under s.17(5) and what the supplier never charged under reverse
    // charge. `net_liability` is computed against `credit`, so showing
    // `purchase` here left the row not subtracting: 18,000 output less 9,000
    // "credit" with 18,000 payable.
    mockDashboard(
      dashboard({
        purchase: { ...BUCKET, count: 2, igst: "9000.00", total_tax: "9000.00" },
        credit: { ...BUCKET, count: 0, igst: "0.00", total_tax: "0.00" },
        input_tax_credit: "0.00",
        net_liability: {
          cgst: "0.00",
          sgst: "0.00",
          igst: "18000.00",
          cess: "0.00",
          total: "18000.00",
        },
      }),
    );
    renderPage();

    const row = await screen.findByRole("row", { name: /IGST/ });
    const cells = within(row).getAllByRole("cell");
    expect(cells[0]).toHaveTextContent("₹18,000.00"); // Output
    expect(cells[1]).toHaveTextContent("₹0.00"); // Credit — blocked, so nil.
    expect(cells[2]).toHaveTextContent("₹18,000.00"); // Payable
  });

  it("agrees with the input tax credit card above it", async () => {
    // The card has always shown `credit.total_tax`. The table showing
    // `purchase` meant the same screen gave two answers to one question.
    mockDashboard(
      dashboard({
        purchase: { ...BUCKET, count: 2, igst: "9000.00", total_tax: "9000.00" },
        credit: { ...BUCKET, count: 1, igst: "4000.00", total_tax: "4000.00" },
        input_tax_credit: "4000.00",
      }),
    );
    renderPage();

    const row = await screen.findByRole("row", { name: /IGST/ });
    const credit = within(row).getAllByRole("cell")[1];
    expect(credit).toHaveTextContent("₹4,000.00");
    // The unclaimable ₹9,000 is not what this column means.
    expect(credit).not.toHaveTextContent("₹9,000.00");
  });

  it("links to the alerts that are waiting", async () => {
    // `open_alerts` was fetched on every load and rendered nowhere, so the
    // sweep could raise an alert that no screen ever mentioned.
    mockDashboard(dashboard({ open_alerts: 3 }));
    renderPage();

    expect(await screen.findByText(/3 alerts need your attention/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /View alerts/ })).toHaveAttribute(
      "href",
      "/alerts",
    );
  });

  it("counts a single alert in the singular", async () => {
    // The banner is one sentence and the whole of it is a count. "1 alerts
    // need your attention" is the string a business sees on the morning the
    // first deadline alert of the month is raised.
    mockDashboard(dashboard({ open_alerts: 1 }));
    renderPage();

    expect(await screen.findByText(/1 alert needs your attention/)).toBeInTheDocument();
  });

  it("says nothing about alerts when there are none", async () => {
    mockDashboard(dashboard({ open_alerts: 0 }));
    renderPage();

    await screen.findByText(/Needs review/);
    expect(screen.queryByRole("link", { name: /View alerts/ })).not.toBeInTheDocument();
  });

  it("counts invoices needing review", async () => {
    mockDashboard(dashboard());
    renderPage();
    expect(await screen.findByText("Needs review")).toBeInTheDocument();
  });

  it("reads a settled, clean period as good rather than as three warnings", async () => {
    // Every tile on this row is a tone, and the tones are what someone takes
    // in before any of the numbers. A month with nothing payable, nothing at
    // risk and nothing to review must not colour like a month with all three
    // — the whole point of the row is that a bad colour means look here.
    mockDashboard(
      dashboard({
        counts: { total: 3, sales: 1, purchase: 2, by_status: { parsed: 3 }, needs_review: 0 },
        net_liability: { cgst: "0.00", sgst: "0.00", igst: "0.00", cess: "0.00", total: "0.00" },
        itc_at_risk: "0.00",
      }),
    );
    const { container } = renderPage();

    await screen.findByText("Needs review");
    expect(statCard(container, "Net liability")).toHaveClass("tone-good");
    expect(statCard(container, "ITC at risk")).toHaveClass("tone-good");
    // The count keeps its plain styling; nothing needs chasing.
    const row = screen.getByText("Needs review").closest("div");
    expect(row.querySelector("dd")).not.toHaveClass("is-warn");
  });

  it("reads credit its suppliers have not filed for as bad, not merely a warning", async () => {
    // This is the figure that becomes a reversal with interest if the supplier
    // never files. It is the loudest thing on the row on purpose.
    mockDashboard(dashboard({ itc_at_risk: "45000.00" }));
    const { container } = renderPage();

    await screen.findByText("Needs review");
    expect(statCard(container, "ITC at risk")).toHaveClass("tone-bad");
  });

  it("warns loudly once a deadline has passed", async () => {
    vi.setSystemTime(new Date(2026, 5, 1)); // 1 June, past both due dates.
    mockDashboard(dashboard());
    renderPage();

    const banners = await screen.findAllByRole("status");
    expect(banners.some((b) => b.textContent.includes("overdue"))).toBe(true);
    vi.useRealTimers();
  });

  it("shows the remaining free-tier allowance", async () => {
    mockDashboard(dashboard());
    renderPage();
    expect(await screen.findByText(/47 remaining/)).toBeInTheDocument();
  });

  it("says unlimited for a plan with no cap", async () => {
    mockDashboard(
      dashboard({
        plan_usage: {
          plan: "pro",
          invoices_this_month: 900,
          monthly_limit: 0,
          remaining: null,
        },
      }),
    );
    renderPage();
    expect(await screen.findByText(/unlimited/)).toBeInTheDocument();
  });

  it("surfaces a failed load instead of showing stale zeroes", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      text: async () => JSON.stringify({ detail: "Database unavailable" }),
    });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Database unavailable");
  });

  it("offers to try a failed load again, and recovers when it works", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      text: async () => JSON.stringify({ detail: "Database unavailable" }),
    });
    renderPage();
    const retry = await screen.findByRole("button", { name: "Try again" });

    mockDashboard(dashboard());
    fireEvent.click(retry);
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  describe("the filing deadline notices", () => {
    // The fixture has GSTR-1 due 11 May 2026 and GSTR-3B due 20 May 2026.
    afterEach(() => vi.useRealTimers());

    async function noticesOn(year, monthIndex, day, body = dashboard()) {
      vi.setSystemTime(new Date(year, monthIndex, day));
      mockDashboard(body);
      renderPage();
      return screen.findAllByRole("status");
    }

    it("shows both GSTR-1 and GSTR-3B banners", async () => {
      const notices = await noticesOn(2026, 4, 1);
      const texts = notices.map((n) => n.textContent);

      expect(texts.some((t) => t.includes("GSTR-1"))).toBe(true);
      expect(texts.some((t) => t.includes("GSTR-3B"))).toBe(true);
    });

    it("stays quiet in tone when the GSTR-3B deadline is comfortably away", async () => {
      const notices = await noticesOn(2026, 4, 1); // 19 days from GSTR-3B.
      const gstr3b = notices.find((n) => n.textContent.includes("GSTR-3B"));

      expect(gstr3b).toHaveClass("banner-neutral");
      expect(gstr3b).toHaveTextContent(/19 days left/);
    });

    it("turns GSTR-3B to a warning inside a week", async () => {
      const notices = await noticesOn(2026, 4, 15); // 5 days from GSTR-3B.
      const gstr3b = notices.find((n) => n.textContent.includes("GSTR-3B"));

      expect(gstr3b).toHaveClass("banner-warn");
      expect(gstr3b).toHaveTextContent(/5 days left/);
    });

    it("escalates GSTR-3B to the overdue styling inside three days", async () => {
      const notices = await noticesOn(2026, 4, 18); // 2 days from GSTR-3B.
      const gstr3b = notices.find((n) => n.textContent.includes("GSTR-3B"));

      expect(gstr3b).toHaveClass("banner-bad");
      expect(gstr3b).toHaveTextContent(/2 days left/);
    });

    it("counts the GSTR-3B day itself as still open", async () => {
      const notices = await noticesOn(2026, 4, 20);
      const gstr3b = notices.find((n) => n.textContent.includes("GSTR-3B"));

      expect(gstr3b).toHaveClass("banner-bad");
      expect(gstr3b).toHaveTextContent(/is due today/);
      expect(gstr3b).not.toHaveTextContent(/overdue/);
    });

    it("shows GSTR-1 as overdue when past the 11th", async () => {
      const notices = await noticesOn(2026, 4, 14); // 3 days past GSTR-1.
      const gstr1 = notices.find((n) => n.textContent.includes("GSTR-1"));

      expect(gstr1).toHaveClass("banner-bad");
      expect(gstr1).toHaveTextContent(/3 days overdue/);
    });

    it("says nothing at all when no deadline is known", async () => {
      vi.setSystemTime(new Date(2026, 4, 1));
      mockDashboard(dashboard({ next_due_date: null, gstr1_due_date: null }));
      renderPage();

      await screen.findByText(/Umang Traders/);
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });
  });

  describe("the net liability trend", () => {
    const trend = [
      { period: "2026-02", net_liability: { total: "4000.00" } },
      { period: "2026-03", net_liability: { total: "8000.00" } },
      { period: "2026-04", net_liability: { total: "0.00" } },
    ];

    it("is hidden until there is more than one period to compare", async () => {
      mockDashboard(dashboard({ recent_periods: [] }));
      renderPage();

      await screen.findByText(/Umang Traders/);
      expect(screen.queryByText("Net liability trend")).not.toBeInTheDocument();
    });

    it("plots a bar per period, labelled by month", async () => {
      mockDashboard(dashboard({ recent_periods: trend }));
      const { container } = renderPage();

      expect(await screen.findByText("Net liability trend")).toBeInTheDocument();
      expect(container.querySelectorAll(".chart-col")).toHaveLength(3);
      expect([...container.querySelectorAll(".chart-label")].map((n) => n.textContent)).toEqual([
        "02",
        "03",
        "04",
      ]);
    });

    it("scales the bars against the tallest period, not against the total", async () => {
      mockDashboard(dashboard({ recent_periods: trend }));
      const { container } = renderPage();

      await screen.findByText("Net liability trend");
      const bars = [...container.querySelectorAll(".chart-bar")];
      expect(bars[1].style.height).toBe("100%"); // The peak.
      expect(bars[0].style.height).toBe("50%"); // Half of it.
    });

    it("still draws a sliver for a period with nothing owed", async () => {
      // A zero-height bar is indistinguishable from a missing month, which
      // reads as lost data rather than a nil return.
      mockDashboard(dashboard({ recent_periods: trend }));
      const { container } = renderPage();

      await screen.findByText("Net liability trend");
      expect([...container.querySelectorAll(".chart-bar")][2].style.height).toBe("2%");
    });

    it("gives each bar a readable figure on hover", async () => {
      mockDashboard(dashboard({ recent_periods: trend }));
      const { container } = renderPage();

      await screen.findByText("Net liability trend");
      // The bar itself only carries a height; the exact figure lives in the
      // tooltip, spelled out in full rather than the abbreviated axis label.
      expect(container.querySelector(".chart-bar")).toHaveAttribute(
        "title",
        "February 2026: ₹4,000.00",
      );
    });
  });

  describe("the period picker", () => {
    it("refetches for the chosen period", async () => {
      vi.setSystemTime(new Date(2026, 4, 1));
      mockDashboard(dashboard());
      renderPage();
      await screen.findByText(/Umang Traders/);

      await userEvent.selectOptions(screen.getByLabelText("Period"), "2026-03");

      await waitFor(() =>
        expect(global.fetch.mock.calls.at(-1)[0]).toContain("period=2026-03"),
      );
      vi.useRealTimers();
    });

    it("keeps the previous figures on screen while the new period loads", async () => {
      // Replacing a populated dashboard with skeletons reads as "your data is
      // gone"; the page dims instead and marks itself busy.
      vi.setSystemTime(new Date(2026, 4, 1));
      mockDashboard(dashboard());
      const { container } = renderPage();
      await screen.findByText(/Umang Traders/);

      let release;
      global.fetch = vi.fn(
        () => new Promise((resolve) => {
          release = () => resolve({
            ok: true,
            status: 200,
            statusText: "",
            text: async () => JSON.stringify(dashboard({ period: "2026-03" })),
          });
        }),
      );
      await userEvent.selectOptions(screen.getByLabelText("Period"), "2026-03");

      await waitFor(() =>
        expect(container.querySelector(".page")).toHaveAttribute("aria-busy", "true"),
      );
      expect(screen.getByText(/Umang Traders/)).toBeInTheDocument();

      release();
      vi.useRealTimers();
    });

    it("does not leave the old month's figures under the new month's label", async () => {
      // The counterpart to the test above, and the case where keeping them is
      // wrong. While a period loads there is an answer coming, so dimming the
      // previous month beats blanking it. When that answer is an error there
      // is nothing coming: the picker says March, the banner says the load
      // failed, and every figure on the page is April's — two of the four stat
      // cards carrying no period of their own to give it away.
      vi.setSystemTime(new Date(2026, 4, 1));
      mockDashboard(dashboard());
      renderPage();
      await screen.findByText(/Umang Traders/);
      expect(
        screen.getByRole("heading", { name: /Tax breakdown — April 2026/ }),
      ).toBeInTheDocument();

      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        text: async () => JSON.stringify({ detail: "Database unavailable" }),
      });
      await userEvent.selectOptions(screen.getByLabelText("Period"), "2026-03");

      expect(await screen.findByRole("alert")).toHaveTextContent("Database unavailable");
      expect(
        screen.queryByRole("heading", { name: /Tax breakdown — April 2026/ }),
      ).not.toBeInTheDocument();
      expect(screen.queryByText(/Umang Traders/)).not.toBeInTheDocument();
      vi.useRealTimers();
    });

    describe("when answers come back out of order", () => {
      /**
       * A fetch that hands back the levers instead of resolving on its own.
       *
       * The bug here is an ordering one, so the test has to be able to answer
       * the second request before the first. A mock that resolves by itself can
       * only ever answer them in order, which is the one case that was never
       * broken.
       */
      function deferredFetch() {
        const pending = [];
        global.fetch = vi.fn(
          (url, options = {}) =>
            new Promise((resolve, reject) => {
              pending.push({
                url: String(url),
                signal: options.signal,
                answer: (body) =>
                  resolve({
                    ok: true,
                    status: 200,
                    statusText: "",
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

      it("abandons the request the newer period supersedes", async () => {
        vi.setSystemTime(new Date(2026, 4, 1));
        const pending = deferredFetch();
        renderPage();

        await waitFor(() => expect(pending).toHaveLength(1));
        pending[0].answer(dashboard());
        await screen.findByText(/Umang Traders/);

        await userEvent.selectOptions(screen.getByLabelText("Period"), "2026-03");
        await waitFor(() => expect(pending).toHaveLength(2));
        await userEvent.selectOptions(screen.getByLabelText("Period"), "2026-02");
        await waitFor(() => expect(pending).toHaveLength(3));

        // March was called off the moment February was asked for. Only the
        // request describing the period actually selected is still in flight.
        expect(pending[1].url).toContain("period=2026-03");
        expect(pending[1].signal.aborted).toBe(true);
        expect(pending[2].url).toContain("period=2026-02");
        expect(pending[2].signal.aborted).toBe(false);
        vi.useRealTimers();
      });

      it("does not let one month's figures land under another month's label", async () => {
        vi.setSystemTime(new Date(2026, 4, 1));
        const pending = deferredFetch();
        renderPage();

        await waitFor(() => expect(pending).toHaveLength(1));
        pending[0].answer(dashboard());
        await screen.findByText(/Umang Traders/);

        await userEvent.selectOptions(screen.getByLabelText("Period"), "2026-03");
        await waitFor(() => expect(pending).toHaveLength(2));
        await userEvent.selectOptions(screen.getByLabelText("Period"), "2026-02");
        await waitFor(() => expect(pending).toHaveLength(3));

        // February answers first, which is the whole point: responses do not
        // come back in the order they were sent.
        pending[2].answer(
          dashboard({
            period: "2026-02",
            net_liability: {
              cgst: "0.00",
              sgst: "0.00",
              igst: "2100.00",
              cess: "0.00",
              total: "2100.00",
            },
          }),
        );
        // The figure shows in the stat tile and again in the tax breakdown.
        await screen.findAllByText("₹2,100.00");

        // Now March finally lands. It was called off, so its answer never
        // reaches the page — before this it repainted every figure, leaving
        // March's money sitting under a heading that reads February.
        pending[1].answer(
          dashboard({
            period: "2026-03",
            net_liability: {
              cgst: "0.00",
              sgst: "0.00",
              igst: "77000.00",
              cess: "0.00",
              total: "77000.00",
            },
          }),
        );

        await waitFor(() =>
          expect(
            screen.getByRole("region", { name: "Tax breakdown for February 2026" }),
          ).toBeInTheDocument(),
        );
        expect(screen.getAllByText("₹2,100.00").length).toBeGreaterThan(0);
        expect(screen.queryByText("₹77,000.00")).not.toBeInTheDocument();
        vi.useRealTimers();
      });

      it("does not raise an error banner for a request it cancelled itself", async () => {
        vi.setSystemTime(new Date(2026, 4, 1));
        const pending = deferredFetch();
        renderPage();

        await waitFor(() => expect(pending).toHaveLength(1));
        pending[0].answer(dashboard());
        await screen.findByText(/Umang Traders/);

        await userEvent.selectOptions(screen.getByLabelText("Period"), "2026-03");
        await waitFor(() => expect(pending).toHaveLength(2));
        await userEvent.selectOptions(screen.getByLabelText("Period"), "2026-02");
        await waitFor(() => expect(pending).toHaveLength(3));
        pending[2].answer(dashboard({ period: "2026-02" }));

        await screen.findByRole("region", { name: "Tax breakdown for February 2026" });
        // "signal is aborted without reason" in front of someone who simply
        // changed month would be worse than the stale figures the abort exists
        // to prevent.
        expect(screen.queryByRole("alert")).not.toBeInTheDocument();
        vi.useRealTimers();
      });
    });
  });
  describe("the plan usage meter", () => {
    it("reports usage as a progress bar rather than a bare width", async () => {
      mockDashboard(dashboard());
      renderPage();

      const bar = await screen.findByRole("progressbar", {
        name: "Invoices used this month",
      });
      expect(bar).toHaveAttribute("aria-valuetext", "3 of 50");
    });

    it("shows nothing to fill on an unlimited plan", async () => {
      mockDashboard(
        dashboard({
          plan_usage: {
            plan: "pro",
            invoices_this_month: 812,
            monthly_limit: null,
            remaining: null,
          },
        }),
      );
      renderPage();

      await screen.findByText(/812/);
      // No ceiling means no proportion to report; a bar stuck at zero or full
      // would both be lies.
      expect(screen.queryByRole("progressbar")).toBeNull();
    });

    it("marks an account that is over its limit", async () => {
      // The plan check runs at upload time, so an account moved to a smaller
      // plan is over the limit before it uploads anything.
      mockDashboard(
        dashboard({
          plan_usage: {
            plan: "free",
            invoices_this_month: 64,
            monthly_limit: 50,
            remaining: 0,
          },
        }),
      );
      const { container } = renderPage();

      const bar = await screen.findByRole("progressbar");
      expect(bar).toHaveAttribute("aria-valuetext", "64 of 50");
      expect(container.querySelector(".meter-fill")).toHaveClass("is-over");
    });
  });

  describe("the trend chart", () => {
    const PERIODS = [
      { period: "2026-03", net_liability: { total: "9000.00" } },
      { period: "2026-04", net_liability: { total: "12500.00" } },
    ];

    it("carries the same numbers in a table for anyone who cannot see the bars", async () => {
      mockDashboard(dashboard({ recent_periods: PERIODS }));
      renderPage();

      // Six divs with a height percentage are not a chart to a screen reader,
      // and there is no ARIA that makes them one. A table of the same figures
      // is the honest equivalent — and is what someone would want anyway.
      const table = await screen.findByRole("table", { name: "Net liability by period" });
      expect(table).toBeInTheDocument();
      expect(within(table).getByRole("row", { name: /March 2026.*₹9,000.00/ })).toBeInTheDocument();
      expect(within(table).getByRole("row", { name: /April 2026.*₹12,500.00/ })).toBeInTheDocument();
    });

    it("hides the decorative bars from assistive tech", async () => {
      mockDashboard(dashboard({ recent_periods: PERIODS }));
      const { container } = renderPage();

      await screen.findByRole("table", { name: "Net liability by period" });
      expect(container.querySelector(".chart-bars")).toHaveAttribute("aria-hidden", "true");
    });

    it("does not cost the rest of the dashboard when a period is malformed", async () => {
      // `net_liability` null is the shape that used to blank the page: the
      // chart reads `.total` off every entry, and one null threw during render
      // — taking the stat cards and the tax table with it.
      vi.spyOn(console, "error").mockImplementation(() => {});
      mockDashboard(
        dashboard({
          recent_periods: [{ period: "2026-03", net_liability: null }],
        }),
      );
      renderPage();

      expect(
        await screen.findByText("The net liability trend could not be displayed"),
      ).toBeInTheDocument();
      // Everything the user actually came for is still on screen.
      expect(screen.getByText(/Umang Traders/)).toBeInTheDocument();
      expect(screen.getByRole("row", { name: /IGST/ })).toBeInTheDocument();
      expect(screen.getByRole("progressbar")).toBeInTheDocument();
    });
  });

  describe("accessibility furniture", () => {
    it("names the screen in the document title", async () => {
      mockDashboard(dashboard());
      renderPage();
      await screen.findByText(/Umang Traders/);
      expect(document.title).toBe("Dashboard · DoAide GST");
    });

    it("makes the tax table reachable when it has to scroll", async () => {
      mockDashboard(dashboard());
      renderPage();

      // Seven columns overflow the panel on a phone. Without a tab stop the
      // scrolled-out columns cannot be reached from a keyboard at all.
      const region = await screen.findByRole("region", {
        name: "Tax breakdown for April 2026",
      });
      expect(region).toHaveAttribute("tabindex", "0");
    });
  });

  describe("the quick actions panel", () => {
    it("offers upload when the user can write", async () => {
      mockDashboard(dashboard());
      renderPage();

      expect(await screen.findByRole("link", { name: "Upload invoices" })).toHaveAttribute(
        "href",
        "/upload",
      );
    });

    it("hides upload from a viewer", async () => {
      mockDashboard(dashboard());
      renderPage({ role: "viewer" });

      await screen.findByText("Quick actions");
      expect(screen.queryByRole("link", { name: "Upload invoices" })).not.toBeInTheDocument();
    });

    it("offers review when invoices need it", async () => {
      mockDashboard(dashboard({ counts: { total: 5, sales: 2, purchase: 3, by_status: { parsed: 5 }, needs_review: 3 } }));
      renderPage();

      expect(await screen.findByRole("link", { name: /Review 3 invoices/ })).toHaveAttribute(
        "href",
        "/invoices?status=parsed",
      );
    });

    it("offers first reconciliation when invoices exist but no recon has run", async () => {
      mockDashboard(dashboard({ last_reconciliation: null }));
      renderPage();

      expect(await screen.findByRole("link", { name: "Run first reconciliation" })).toHaveAttribute(
        "href",
        "/reconcile",
      );
    });

    it("hides first reconciliation once one has run", async () => {
      mockDashboard(dashboard({ last_reconciliation: { matched: 2, mismatched: 0, missing_in_2b: 0, missing_in_books: 0 } }));
      renderPage();

      await screen.findByText("Quick actions");
      expect(screen.queryByRole("link", { name: "Run first reconciliation" })).not.toBeInTheDocument();
    });
  });

  describe("the onboarding checklist", () => {
    it("appears for a new user with no GSTIN and no invoices", async () => {
      mockDashboard(dashboard({
        business_gstin: null,
        counts: { total: 0, sales: 0, purchase: 0, by_status: {}, needs_review: 0 },
      }));
      renderPage();

      expect(await screen.findByText("Get started")).toBeInTheDocument();
      expect(screen.getByText(/0 of 4 steps done/)).toBeInTheDocument();
    });

    it("disappears once the user has a GSTIN and invoices", async () => {
      mockDashboard(dashboard());
      renderPage();

      await screen.findByText("Quick actions");
      expect(screen.queryByText("Get started")).not.toBeInTheDocument();
    });

    it("marks the GSTIN step as done when one is registered", async () => {
      mockDashboard(dashboard({
        counts: { total: 0, sales: 0, purchase: 0, by_status: {}, needs_review: 0 },
      }));
      renderPage();

      expect(await screen.findByText("Get started")).toBeInTheDocument();
      expect(screen.getByText(/1 of 4 steps done/)).toBeInTheDocument();
    });

    it("hides action links from a viewer who cannot write", async () => {
      mockDashboard(dashboard({
        business_gstin: null,
        counts: { total: 0, sales: 0, purchase: 0, by_status: {}, needs_review: 0 },
      }));
      renderPage({ role: "viewer" });

      expect(await screen.findByText("Get started")).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: /Start/ })).not.toBeInTheDocument();
    });

    it("offers reconciliation once purchase invoices exist", async () => {
      mockDashboard(dashboard({
        business_gstin: null,
        counts: { total: 2, sales: 0, purchase: 2, by_status: { parsed: 2 }, needs_review: 0 },
      }));
      renderPage();

      expect(await screen.findByText("Get started")).toBeInTheDocument();
      const links = screen.getAllByRole("link", { name: /Start/ });
      const hrefs = links.map((l) => l.getAttribute("href"));
      expect(hrefs).toContain("/reconcile");
    });

    it("offers filing once any invoices exist", async () => {
      mockDashboard(dashboard({
        business_gstin: null,
        counts: { total: 1, sales: 1, purchase: 0, by_status: { parsed: 1 }, needs_review: 0 },
      }));
      renderPage();

      expect(await screen.findByText("Get started")).toBeInTheDocument();
      const links = screen.getAllByRole("link", { name: /Start/ });
      const hrefs = links.map((l) => l.getAttribute("href"));
      expect(hrefs).toContain("/filing");
    });
  });

  describe("the late fee warning", () => {
    it("shows the late fee estimate when GSTR-3B is overdue", async () => {
      mockDashboard(dashboard({
        late_fee_estimate: { days_late: 5, late_fee_total: "500.00", interest: "0.00" },
      }));
      renderPage();

      const [banner] = await screen.findAllByText(/5 days overdue/);
      expect(banner).toBeInTheDocument();
      expect(screen.getByText(/₹500.00/)).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "File now" })).toHaveAttribute("href", "/filing");
    });

    it("includes interest when there is some", async () => {
      mockDashboard(dashboard({
        late_fee_estimate: { days_late: 12, late_fee_total: "1200.00", interest: "350.00" },
      }));
      renderPage();

      expect(await screen.findByText(/interest/)).toBeInTheDocument();
      expect(screen.getByText(/₹350.00/)).toBeInTheDocument();
    });

    it("uses the singular when exactly one day overdue", async () => {
      mockDashboard(dashboard({
        late_fee_estimate: { days_late: 1, late_fee_total: "100.00", interest: "0.00" },
      }));
      renderPage();

      expect(await screen.findByText(/1 day overdue/)).toBeInTheDocument();
      // Word-bounded: the deadline banner counts from today's date, and
      // "161 days overdue" matched a bare /1 days/ once the calendar moved on.
      expect(screen.queryByText(/\b1 days\b/)).not.toBeInTheDocument();
    });

    it("stays hidden when there is no late fee", async () => {
      mockDashboard(dashboard());
      renderPage();

      await screen.findByText(/Umang Traders/);
      expect(screen.queryByText(/overdue.*late fee/)).not.toBeInTheDocument();
    });
  });

  describe("the reconciliation summary", () => {
    it("shows the match rate from the last reconciliation", async () => {
      mockDashboard(dashboard({
        last_reconciliation: { matched: 8, mismatched: 1, missing_in_2b: 1, missing_in_books: 0 },
      }));
      renderPage();

      expect(await screen.findByText(/80%/)).toBeInTheDocument();
      expect(screen.getByText(/8 of 10/)).toBeInTheDocument();
    });

    it("shows mismatched and missing counts", async () => {
      mockDashboard(dashboard({
        last_reconciliation: { matched: 5, mismatched: 2, missing_in_2b: 3, missing_in_books: 0 },
      }));
      renderPage();

      expect(await screen.findByText("Mismatched")).toBeInTheDocument();
      expect(screen.getByText("Missing in 2B")).toBeInTheDocument();
    });

    it("links to the full reconciliation page", async () => {
      mockDashboard(dashboard({
        last_reconciliation: { matched: 5, mismatched: 0, missing_in_2b: 0, missing_in_books: 0 },
      }));
      renderPage();

      expect(await screen.findByRole("link", { name: "View full reconciliation" })).toHaveAttribute(
        "href",
        "/reconcile",
      );
    });

    it("shows invoices missing from the books", async () => {
      mockDashboard(dashboard({
        last_reconciliation: { matched: 4, mismatched: 0, missing_in_2b: 0, missing_in_books: 2 },
      }));
      renderPage();

      expect(await screen.findByText("Missing in books")).toBeInTheDocument();
    });

    it("treats undefined fields as zero rather than crashing", async () => {
      mockDashboard(dashboard({
        last_reconciliation: { matched: 3 },
      }));
      renderPage();

      expect(await screen.findByText(/100%/)).toBeInTheDocument();
      expect(screen.getByText(/3 of 3/)).toBeInTheDocument();
    });

    it("treats a null matched count as zero", async () => {
      mockDashboard(dashboard({
        last_reconciliation: { matched: null, mismatched: 2, missing_in_2b: 0, missing_in_books: 0 },
      }));
      renderPage();

      expect(await screen.findByText(/0%/)).toBeInTheDocument();
      expect(screen.getByText(/0 of 2/)).toBeInTheDocument();
    });

    it("hides when every count is zero", async () => {
      mockDashboard(dashboard({
        last_reconciliation: { matched: 0, mismatched: 0, missing_in_2b: 0, missing_in_books: 0 },
      }));
      renderPage();

      await screen.findByText(/Umang Traders/);
      expect(screen.queryByText("Last reconciliation")).not.toBeInTheDocument();
    });

    it("stays hidden when no reconciliation has run", async () => {
      mockDashboard(dashboard());
      renderPage();

      await screen.findByText(/Umang Traders/);
      expect(screen.queryByText("Last reconciliation")).not.toBeInTheDocument();
    });
  });
});

describe("deadlineBanner wording", () => {
  // Midday, so a day boundary is never a question of which hour the test ran.
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 4, 20, 12, 0, 0));
  });
  afterEach(() => vi.useRealTimers());

  it("says one day, not one days, either side of the date", () => {
    expect(deadlineBanner("GSTR-3B", "2026-05-19").text).toMatch(/— 1 day overdue$/);
    expect(deadlineBanner("GSTR-3B", "2026-05-21").text).toMatch(/— 1 day left$/);
    expect(deadlineBanner("GSTR-3B", "2026-05-22").text).toMatch(/— 2 days left$/);
  });

  it("says the return is due today on the day, not that 0 days are left", () => {
    const banner = deadlineBanner("GSTR-3B", "2026-05-20");
    expect(banner.text).toMatch(/^GSTR-3B is due today/);
    expect(banner.text).not.toMatch(/0 days/);
    expect(banner.tone).toBe("bad");
  });
});
