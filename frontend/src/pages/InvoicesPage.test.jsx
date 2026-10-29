import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StubAuth } from "../test/auth";
import InvoicesPage from "./InvoicesPage";

const PAGE_SIZE = 25;

function invoice(overrides = {}) {
  return {
    id: 1,
    invoice_number: "INV-2026-0042",
    invoice_type: "purchase",
    invoice_date: "2026-04-15",
    counterparty_name: "Northwind Supplies",
    counterparty_gstin: "29AAGCB7383J1Z4",
    taxable_value: "450000.00",
    cgst: "0.00",
    sgst: "0.00",
    igst: "81000.00",
    cess: "0.00",
    total_value: "531000.00",
    invoice_value: "531000.00",
    status: "matched",
    ...overrides,
  };
}

/**
 * Capture every request URL, because what this page is *for* is turning
 * filters and pagination into a query string. The assertions read the
 * captured URLs rather than the rendered rows wherever the query is the point.
 */
function mockApi({ items = [invoice()], total = items.length, fail } = {}) {
  const urls = [];
  global.fetch = vi.fn(async (url) => {
    urls.push(String(url));
    if (fail) {
      return {
        ok: false,
        status: fail.status ?? 500,
        statusText: "Error",
        text: async () => JSON.stringify({ detail: fail.message }),
      };
    }
    return {
      ok: true,
      status: 200,
      statusText: "OK",
      text: async () => JSON.stringify({ items, total, limit: PAGE_SIZE, offset: 0 }),
    };
  });
  return urls;
}

function renderPage({ role } = {}) {
  return render(
    <MemoryRouter>
      <StubAuth role={role}>
        <InvoicesPage />
      </StubAuth>
    </MemoryRouter>,
  );
}

function lastQuery(urls) {
  return new URL(urls.at(-1), "http://localhost").searchParams;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("InvoicesPage", () => {
  it("shows a loading skeleton before the first response lands", () => {
    mockApi();
    renderPage();
    // The skeleton announces itself through visually hidden text in a polite
    // live region rather than a role, so a screen reader is not left silent.
    expect(screen.getByText(/Loading invoices/)).toBeInTheDocument();
  });

  it("lists the invoices it fetched", async () => {
    mockApi({ items: [invoice(), invoice({ id: 2, invoice_number: "INV-2026-0043" })] });
    renderPage();

    expect(await screen.findByText("INV-2026-0042")).toBeInTheDocument();
    expect(screen.getByText("INV-2026-0043")).toBeInTheDocument();
  });

  it("links each row to its invoice", async () => {
    mockApi();
    renderPage();

    const link = await screen.findByRole("link", { name: "INV-2026-0042" });
    expect(link).toHaveAttribute("href", "/invoices/1");
  });

  it("falls back to the id when an invoice has no number", async () => {
    // An extraction that could not read the number still has to be reachable,
    // since correcting it is exactly what the user is here to do.
    mockApi({ items: [invoice({ invoice_number: null, id: 77 })] });
    renderPage();

    const link = await screen.findByRole("link", { name: "#77" });
    expect(link).toHaveAttribute("href", "/invoices/77");
  });

  it("sums the four tax heads into one column", async () => {
    // The table shows total tax, which no single field carries.
    mockApi({
      items: [
        invoice({ cgst: "40500.00", sgst: "40500.00", igst: "0.00", cess: "1000.00" }),
      ],
    });
    renderPage();

    const row = (await screen.findByText("INV-2026-0042")).closest("tr");
    expect(within(row).getByText("₹82,000.00")).toBeInTheDocument();
  });

  it("shows a dash for a counterparty that could not be read", async () => {
    mockApi({ items: [invoice({ counterparty_name: null, counterparty_gstin: null })] });
    renderPage();

    const row = (await screen.findByText("INV-2026-0042")).closest("tr");
    expect(within(row).getByText("—")).toBeInTheDocument();
    expect(within(row).getByText("No GSTIN")).toBeInTheDocument();
  });

  it("invites a first upload when there are none at all", async () => {
    mockApi({ items: [], total: 0 });
    renderPage();

    expect(await screen.findByText("No invoices yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /upload your first invoice/i })).toHaveAttribute(
      "href",
      "/upload",
    );
  });

  describe("when a filter matches nothing", () => {
    /** Rows for the unfiltered list, nothing once a query string narrows it. */
    function mockFilterable() {
      const urls = [];
      global.fetch = vi.fn(async (url) => {
        const text = String(url);
        urls.push(text);
        const params = new URL(text, "http://localhost").searchParams;
        const narrowed = params.has("search") || params.has("status") || params.has("invoice_type");
        const items = narrowed ? [] : [invoice()];
        return {
          ok: true,
          status: 200,
          statusText: "OK",
          text: async () => JSON.stringify({ items, total: items.length, limit: PAGE_SIZE, offset: 0 }),
        };
      });
      return urls;
    }

    it("does not tell a stocked book that it is empty", async () => {
      const user = userEvent.setup();
      mockFilterable();
      renderPage();
      await screen.findByText("INV-2026-0042");

      await user.type(screen.getByRole("searchbox"), "zzz");

      expect(await screen.findByText("No invoices match these filters.")).toBeInTheDocument();
      // The books are not empty, so neither the claim nor the first-upload
      // invitation belongs on screen.
      expect(screen.queryByText("No invoices yet.")).not.toBeInTheDocument();
      expect(
        screen.queryByRole("link", { name: /upload your first invoice/i }),
      ).not.toBeInTheDocument();
    });

    it("offers a way back to the full list", async () => {
      const user = userEvent.setup();
      mockFilterable();
      renderPage();
      await screen.findByText("INV-2026-0042");

      await user.selectOptions(screen.getByLabelText("Status"), "failed");
      await screen.findByText("No invoices match these filters.");

      await user.click(screen.getByRole("button", { name: "Clear filters" }));

      expect(await screen.findByText("INV-2026-0042")).toBeInTheDocument();
      expect(screen.getByLabelText("Status")).toHaveValue("");
    });

    it("still invites a first upload when nothing is filtered", async () => {
      // The first-run screen has to survive the fix: an account with no
      // invoices and no filters is the one case the invitation is for.
      mockApi({ items: [], total: 0 });
      renderPage();

      expect(await screen.findByText("No invoices yet.")).toBeInTheDocument();
      expect(screen.queryByText("No invoices match these filters.")).not.toBeInTheDocument();
    });
  });

  it("surfaces a failed load and lets it be dismissed", async () => {
    mockApi({ fail: { status: 500, message: "Database unreachable" } });
    renderPage();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Database unreachable");

    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not tell a business its books are empty when it could not read them", async () => {
    // "No invoices yet", under a button offering to upload their first, is the
    // sentence this page is careful never to show a filtered view — and a
    // failed load showed it to everyone. On a book with five hundred invoices
    // it reads as the books having been lost.
    mockApi({ fail: { status: 500, message: "Database unreachable" } });
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Database unreachable");
    expect(screen.queryByText("No invoices yet.")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Upload your first invoice/ }),
    ).not.toBeInTheDocument();
  });

  it("does not leave the previous rows under filters they were not fetched for", async () => {
    mockApi({ items: [invoice({ counterparty_name: "Northwind Supplies" })] });
    renderPage();
    await screen.findByText("Northwind Supplies");

    global.fetch = vi.fn(async () => ({
      ok: false,
      status: 500,
      statusText: "Error",
      text: async () => JSON.stringify({ detail: "Database unreachable" }),
    }));
    await userEvent.selectOptions(screen.getByLabelText("Status"), "failed");

    expect(await screen.findByRole("alert")).toHaveTextContent("Database unreachable");
    expect(screen.queryByText("Northwind Supplies")).not.toBeInTheDocument();
    // Nor the pager's count, which is a statement about how many invoices the
    // filters matched.
    expect(screen.queryByText(/of 1$/)).not.toBeInTheDocument();
  });

  describe("filters", () => {
    it("sends the selected type as a query parameter", async () => {
      const urls = mockApi();
      renderPage();
      await screen.findByText("INV-2026-0042");

      await userEvent.selectOptions(screen.getByLabelText("Type"), "purchase");

      await waitFor(() => expect(lastQuery(urls).get("invoice_type")).toBe("purchase"));
    });

    it("sends the selected status as a query parameter", async () => {
      const urls = mockApi();
      renderPage();
      await screen.findByText("INV-2026-0042");

      await userEvent.selectOptions(screen.getByLabelText("Status"), "mismatched");

      await waitFor(() => expect(lastQuery(urls).get("status")).toBe("mismatched"));
    });

    it("sends the search text as a query parameter", async () => {
      const urls = mockApi();
      renderPage();
      await screen.findByText("INV-2026-0042");

      await userEvent.type(screen.getByLabelText("Search"), "Northwind");

      await waitFor(() => expect(lastQuery(urls).get("search")).toBe("Northwind"));
    });

    it("omits a filter that is set back to All rather than sending it empty", async () => {
      // An empty `status=` is a filter for the empty status, not for none.
      const urls = mockApi();
      renderPage();
      await screen.findByText("INV-2026-0042");

      await userEvent.selectOptions(screen.getByLabelText("Status"), "parsed");
      await waitFor(() => expect(lastQuery(urls).get("status")).toBe("parsed"));

      await userEvent.selectOptions(screen.getByLabelText("Status"), "");
      await waitFor(() => expect(lastQuery(urls).has("status")).toBe(false));
    });

    it("returns to the first page when a filter changes", async () => {
      // Otherwise a narrower filter lands on an offset past the end of the
      // new result set and the table reads as empty.
      const urls = mockApi({ items: [invoice()], total: 80 });
      renderPage();
      await screen.findByText("INV-2026-0042");

      await userEvent.click(screen.getByRole("button", { name: "Next" }));
      await waitFor(() => expect(lastQuery(urls).get("offset")).toBe(String(PAGE_SIZE)));

      await userEvent.selectOptions(screen.getByLabelText("Type"), "sales");
      await waitFor(() => expect(lastQuery(urls).get("offset")).toBe("0"));
    });
  });

  describe("pagination", () => {
    it("cannot go back from the first page", async () => {
      mockApi({ items: [invoice()], total: 80 });
      renderPage();
      await screen.findByText("INV-2026-0042");

      expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    });

    it("cannot go forward from the last page", async () => {
      mockApi({ items: [invoice()], total: 1 });
      renderPage();
      await screen.findByText("INV-2026-0042");

      expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    });

    it("advances by a page", async () => {
      const urls = mockApi({ items: [invoice()], total: 80 });
      renderPage();
      await screen.findByText("INV-2026-0042");

      await userEvent.click(screen.getByRole("button", { name: "Next" }));

      await waitFor(() => expect(lastQuery(urls).get("offset")).toBe("25"));
      expect(lastQuery(urls).get("limit")).toBe("25");
    });

    it("goes back a page", async () => {
      const urls = mockApi({ items: [invoice()], total: 80 });
      renderPage();
      await screen.findByText("INV-2026-0042");

      await userEvent.click(screen.getByRole("button", { name: "Next" }));
      await waitFor(() => expect(lastQuery(urls).get("offset")).toBe("25"));

      await userEvent.click(screen.getByRole("button", { name: "Previous" }));
      await waitFor(() => expect(lastQuery(urls).get("offset")).toBe("0"));
    });

    it("counts the visible range from one, not zero", async () => {
      mockApi({ items: [invoice()], total: 80 });
      renderPage();
      await screen.findByText("INV-2026-0042");

      expect(screen.getByText("1–25 of 80")).toBeInTheDocument();
    });

    it("does not claim more rows than exist on a short last page", async () => {
      mockApi({ items: [invoice()], total: 3 });
      renderPage();
      await screen.findByText("INV-2026-0042");

      expect(screen.getByText("1–3 of 3")).toBeInTheDocument();
    });
  });

  it("keeps the table scrollable in its own container on a narrow screen", async () => {
    // The page must never scroll horizontally as a whole; the table does.
    mockApi();
    const { container } = renderPage();
    await screen.findByText("INV-2026-0042");

    expect(container.querySelector(".table-scroll table")).toBeInTheDocument();
  });
  describe("accessibility furniture", () => {
    it("names the screen in the document title", async () => {
      mockApi();
      renderPage();
      await screen.findByText("INV-2026-0042");
      expect(document.title).toBe("Invoices · DoAide GST");
    });

    it("makes the scroll container a named, focusable region", async () => {
      mockApi();
      renderPage();
      await screen.findByText("INV-2026-0042");

      // Seven columns overflow on a phone. `overflow-x: auto` alone leaves the
      // hidden columns unreachable from a keyboard — there is nothing focusable
      // inside the overflow for Tab to land on.
      const region = screen.getByRole("region", { name: "Invoices" });
      expect(region).toHaveAttribute("tabindex", "0");
      expect(within(region).getByRole("table")).toBeInTheDocument();
    });

    it("announces the range after paging", async () => {
      // Next replaces the rows in place. Without a live region the only
      // feedback from the press is that focus stayed on the button.
      mockApi({ items: [invoice()], total: 60 });
      renderPage();
      await screen.findByText("INV-2026-0042");

      expect(screen.getByRole("status")).toHaveTextContent("1–25 of 60");
      await userEvent.click(screen.getByRole("button", { name: "Next" }));
      await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("26–50 of 60"));
    });
  });

  describe("refetching over rows that are already on screen", () => {
    it("dims the table instead of replacing it with placeholders", async () => {
      mockApi();
      const { container } = renderPage();
      await screen.findByText("INV-2026-0042");

      let release;
      global.fetch = vi.fn(
        () =>
          new Promise((resolve) => {
            release = () =>
              resolve({
                ok: true,
                status: 200,
                statusText: "OK",
                text: async () =>
                  JSON.stringify({ items: [], total: 0, limit: PAGE_SIZE, offset: 0 }),
              });
          }),
      );
      await userEvent.selectOptions(screen.getByLabelText("Status"), "failed");

      await waitFor(() =>
        expect(container.querySelector(".page")).toHaveAttribute("aria-busy", "true"),
      );
      // Swapping the rows for skeletons on every filter change reads as "your
      // invoices are gone"; the previous answer stays up, dimmed.
      expect(screen.getByText("INV-2026-0042")).toBeInTheDocument();
      expect(container.querySelector(".results")).toHaveClass("is-refreshing");

      release();
    });

    it("is not busy once the rows have landed", async () => {
      mockApi();
      const { container } = renderPage();
      await screen.findByText("INV-2026-0042");
      expect(container.querySelector(".page")).toHaveAttribute("aria-busy", "false");
      expect(container.querySelector(".results")).not.toHaveClass("is-refreshing");
    });

    it("leaves the filters usable while the rows are being refetched", async () => {
      // `.is-refreshing` carries `pointer-events: none`. Dimming the whole page
      // would take the search box down with the rows — and the search box is
      // what triggered the refetch, mid-word.
      mockApi();
      const { container } = renderPage();
      await screen.findByText("INV-2026-0042");

      global.fetch = vi.fn(() => new Promise(() => {}));
      await userEvent.selectOptions(screen.getByLabelText("Status"), "failed");

      await waitFor(() =>
        expect(container.querySelector(".results")).toHaveClass("is-refreshing"),
      );
      expect(container.querySelector(".filters")).not.toHaveClass("is-refreshing");
      expect(container.querySelector(".filters").closest(".is-refreshing")).toBeNull();
    });

    it("still shows placeholders on the very first load", async () => {
      // Nothing to dim yet — a blank page with no explanation is the thing the
      // skeleton exists to prevent.
      mockApi();
      const { container } = renderPage();
      expect(container.querySelector(".skeleton-table")).toBeInTheDocument();
      await screen.findByText("INV-2026-0042");
    });
  });

  describe("sorting", () => {
    it("sorts by the clicked column, largest or newest first, on the first click", async () => {
      const urls = mockApi();
      renderPage();
      await screen.findByText("INV-2026-0042");

      await userEvent.click(screen.getByRole("columnheader", { name: "Date" }).querySelector("button"));

      await waitFor(() => expect(urls.at(-1)).toContain("sort=date_desc"));
      expect(screen.getByRole("columnheader", { name: "Date" })).toHaveAttribute(
        "aria-sort",
        "descending",
      );
    });

    it("reverses direction on a second click of the same column", async () => {
      const urls = mockApi();
      renderPage();
      await screen.findByText("INV-2026-0042");
      const dateHeader = () => screen.getByRole("columnheader", { name: "Date" });

      await userEvent.click(within(dateHeader()).getByRole("button"));
      await waitFor(() => expect(urls.at(-1)).toContain("sort=date_desc"));

      await userEvent.click(within(dateHeader()).getByRole("button"));
      await waitFor(() => expect(urls.at(-1)).toContain("sort=date_asc"));
      expect(dateHeader()).toHaveAttribute("aria-sort", "ascending");
    });

    it("reverses an ascending column to descending", async () => {
      // The other way round from the case above. "Invoice" opens ascending
      // because it is a sequence, so its second click is the one that runs
      // the asc-to-desc arm — the arm no column that opens descending reaches.
      const urls = mockApi();
      renderPage();
      await screen.findByText("INV-2026-0042");
      const header = () => screen.getByRole("columnheader", { name: "Invoice" });

      await userEvent.click(within(header()).getByRole("button"));
      await waitFor(() => expect(urls.at(-1)).toContain("sort=number_asc"));

      await userEvent.click(within(header()).getByRole("button"));
      await waitFor(() => expect(urls.at(-1)).toContain("sort=number_desc"));
      expect(header()).toHaveAttribute("aria-sort", "descending");
    });

    it("starts a newly clicked column at its own default rather than the old column's direction", async () => {
      const urls = mockApi();
      renderPage();
      await screen.findByText("INV-2026-0042");

      // "Invoice" defaults to ascending — a sequence, not a magnitude — unlike
      // "Date" and "Total", which open on the most recent or the largest.
      await userEvent.click(within(screen.getByRole("columnheader", { name: "Date" })).getByRole("button"));
      await waitFor(() => expect(urls.at(-1)).toContain("sort=date_desc"));

      await userEvent.click(
        within(screen.getByRole("columnheader", { name: "Invoice" })).getByRole("button"),
      );
      await waitFor(() => expect(urls.at(-1)).toContain("sort=number_asc"));
      expect(urls.at(-1)).not.toContain("date");
    });

    it("returns to page one when the sort changes", async () => {
      mockApi({ items: [invoice()], total: 60 });
      renderPage();
      await screen.findByText("INV-2026-0042");

      await userEvent.click(screen.getByRole("button", { name: "Next" }));
      await waitFor(() => expect(screen.getByText("26–50 of 60")).toBeInTheDocument());

      await userEvent.click(
        within(screen.getByRole("columnheader", { name: "Total" })).getByRole("button"),
      );
      await waitFor(() => expect(screen.getByText("1–25 of 60")).toBeInTheDocument());
    });
  });

  describe("a request this page cancelled itself", () => {
    /**
     * A fetch that rejects the way a browser does when the signal aborts.
     *
     * The mocks above resolve immediately, so the effect's cleanup always
     * fires after the answer has already landed and the abort rejection never
     * happens. Every keystroke in the search box supersedes a request, so in
     * a browser it happens constantly.
     */
    function abortingFetch() {
      const pending = [];
      global.fetch = vi.fn(
        (url, options = {}) =>
          new Promise((resolve, reject) => {
            pending.push({
              url: String(url),
              answer: (body) =>
                resolve({
                  ok: true,
                  status: 200,
                  statusText: "OK",
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

    it("does not banner its own cancellation, or blank the rows it already has", async () => {
      // "signal is aborted without reason" in front of someone who simply kept
      // typing is worse than the stale rows the abort exists to prevent — and
      // clearing `data` would take the table down between keystrokes.
      const pending = abortingFetch();
      renderPage();

      pending[0].answer({ items: [invoice()], total: 1, limit: PAGE_SIZE, offset: 0 });
      await screen.findByText("INV-2026-0042");

      // A keystroke supersedes the request the next one starts.
      await userEvent.type(screen.getByRole("searchbox"), "AC");
      await waitFor(() => expect(pending.length).toBeGreaterThan(2));

      pending.at(-1).answer({ items: [invoice()], total: 1, limit: PAGE_SIZE, offset: 0 });

      expect(await screen.findByText("INV-2026-0042")).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });
});

describe("a viewer", () => {
  // This page has no write of its own — its one control is a link to Upload,
  // whose every route is writer-only. So what goes is an invitation, and the
  // list, the filters, the sort and the pages all stay: a viewer reading their
  // books is the case this screen serves best.
  afterEach(() => vi.restoreAllMocks());

  it("is not invited to a screen where every control would be refused", async () => {
    mockApi();
    renderPage({ role: "viewer" });
    await screen.findByText("INV-2026-0042");

    expect(screen.queryByRole("link", { name: "Upload" })).toBeNull();
  });

  it("is told who can upload the first invoice, instead of being asked to", async () => {
    // An empty state whose only sentence asks for something the reader cannot
    // do is worse than one that names who to ask — the viewer would otherwise
    // click through to Upload and find that screen empty too.
    mockApi({ items: [], total: 0 });
    renderPage({ role: "viewer" });

    expect(await screen.findByText("No invoices yet.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Upload your first invoice/ })).toBeNull();
    expect(
      screen.getByText("An owner or an accountant can upload the first one."),
    ).toBeInTheDocument();
  });

  it("keeps the whole list, and is not bannered about it", async () => {
    // No ReadOnlyNotice on this screen on purpose: a table that lost one
    // header button still does its job, and a banner on every page in the app
    // is a banner people stop reading.
    const urls = mockApi({ items: [invoice(), invoice({ id: 2, invoice_number: "INV-2" })] });
    renderPage({ role: "viewer" });

    expect(await screen.findByText("INV-2026-0042")).toBeInTheDocument();
    expect(screen.getByText("INV-2")).toBeInTheDocument();
    expect(screen.queryByText(/read-only/)).toBeNull();
    expect(urls).toHaveLength(1);
  });

  it("keeps the filters and the sort, which are reads", async () => {
    const urls = mockApi();
    renderPage({ role: "viewer" });
    await screen.findByText("INV-2026-0042");

    await userEvent.selectOptions(screen.getByLabelText("Status"), "mismatched");
    await waitFor(() => expect(lastQuery(urls).get("status")).toBe("mismatched"));

    await userEvent.click(screen.getByRole("button", { name: /^Date/ }));
    await waitFor(() => expect(lastQuery(urls).get("sort")).toBe("date_desc"));
  });

  it("leaves an owner both invitations", async () => {
    mockApi({ items: [], total: 0 });
    renderPage();

    expect(await screen.findByText("No invoices yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Upload" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Upload your first invoice/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("An owner or an accountant can upload the first one."),
    ).toBeNull();
  });

  describe("a page that emptied behind the user", () => {
    // P36 M9: another login deletes invoices while this one is paging. Next
    // was enabled by the old total, the page it asks for is past the end, and
    // the answer is an empty page whose total is still positive. Rendered as
    // it came, that was "No invoices yet. Upload your first invoice" over a
    // book of twenty invoices, with no pager to get back by.
    function mockShrinking() {
      const offsets = [];
      global.fetch = vi.fn(async (url) => {
        const from = Number(new URL(String(url), "http://localhost").searchParams.get("offset"));
        offsets.push(from);
        const body =
          offsets.length === 1
            ? { items: [invoice()], total: 60 }
            : from >= 20
              ? { items: [], total: 20 }
              : { items: [invoice({ id: 7, invoice_number: "INV-STILL-HERE" })], total: 20 };
        return {
          ok: true,
          status: 200,
          statusText: "OK",
          text: async () => JSON.stringify({ ...body, limit: PAGE_SIZE, offset: from }),
        };
      });
      return offsets;
    }

    it("steps back to the last page there is, not to the empty state", async () => {
      const offsets = mockShrinking();
      renderPage();
      await userEvent.click(await screen.findByRole("button", { name: "Next" }));

      expect(await screen.findByText("INV-STILL-HERE")).toBeInTheDocument();
      expect(screen.queryByText("No invoices yet.")).not.toBeInTheDocument();
      expect(offsets).toEqual([0, 25, 0]);
    });
  });
});
