import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StubAuth } from "../test/auth";
import AlertsPage from "./AlertsPage";

function alert(overrides = {}) {
  return {
    id: 1,
    alert_type: "filing_deadline",
    severity: "critical",
    status: "pending",
    title: "GSTR-3B for 2026-04 is overdue",
    message:
      "GSTR-3B for 2026-04 was due on 2026-05-20 and has not been recorded as filed.",
    period: "2026-04",
    due_date: "2026-05-20",
    channel: null,
    sent_at: null,
    context: { return_type: "gstr3b" },
    created_at: "2026-05-21T04:00:00Z",
    updated_at: "2026-05-21T04:00:00Z",
    ...overrides,
  };
}

function page(items, overrides = {}) {
  return {
    items,
    total: items.length,
    open_total: items.filter((a) =>
      ["pending", "sent", "read", "failed"].includes(a.status),
    ).length,
    limit: 50,
    offset: 0,
    ...overrides,
  };
}

/** Answer each call in order, so an action's response differs from the list. */
function mockFetch(...bodies) {
  const fetch = vi.fn();
  bodies.forEach((body) => {
    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: "",
      text: async () => JSON.stringify(body),
    });
  });
  global.fetch = fetch;
  return fetch;
}

function renderPage({ role } = {}) {
  return render(
    <MemoryRouter>
      <StubAuth role={role}>
        <AlertsPage />
      </StubAuth>
    </MemoryRouter>,
  );
}

describe("AlertsPage", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("shows what each alert says", async () => {
    mockFetch(page([alert()]));
    renderPage();

    expect(await screen.findByText(/GSTR-3B for 2026-04 is overdue/)).toBeInTheDocument();
    expect(screen.getByText(/has not been recorded as filed/)).toBeInTheDocument();
  });

  it("asks for open alerts by default", async () => {
    const fetch = mockFetch(page([alert()]));
    renderPage();

    await screen.findByText(/is overdue/);
    expect(fetch.mock.calls[0][0]).toContain("scope=open");
  });

  it("labels an overdue return more loudly than an upcoming one", async () => {
    mockFetch(page([alert({ severity: "info", title: "GSTR-1 for 2026-05 is due in 5 days" })]));
    renderPage();

    expect(await screen.findByText("Upcoming")).toBeInTheDocument();
  });

  it("dismisses an alert and takes it off the open list", async () => {
    // The sweep's central rule is that a dismissal is respected and the alert
    // is not raised again tomorrow. Until this page existed no client could
    // produce one, so the rule could never fire and a business that filed on
    // the portal without recording it here was told it was late every morning
    // with no way to stop it.
    mockFetch(page([alert()]), alert({ status: "dismissed" }));
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Dismiss" }));

    await waitFor(() =>
      expect(screen.queryByText(/GSTR-3B for 2026-04 is overdue/)).not.toBeInTheDocument(),
    );
  });

  it("posts the dismissal to the alert it was clicked on", async () => {
    const fetch = mockFetch(
      page([alert({ id: 7 })]),
      alert({ id: 7, status: "dismissed" }),
    );
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Dismiss" }));

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(fetch.mock.calls[1][0]).toContain("/alerts/7/dismiss");
    expect(fetch.mock.calls[1][1].method).toBe("POST");
  });

  it("keeps a read alert on the open list", async () => {
    // Seen is not handled. A filing deadline someone has looked at is exactly
    // as unmet as one they have not, so reading it must not clear the badge —
    // which is the bug the backend's OPEN_STATUSES already exists to prevent.
    mockFetch(page([alert()]), alert({ status: "read" }));
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Mark as read" }));

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Mark as read" })).not.toBeInTheDocument(),
    );
    expect(screen.getByText(/GSTR-3B for 2026-04 is overdue/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
  });

  it("takes the new status from the server rather than assuming it", async () => {
    // Dismissing an alert the sweep already resolved leaves it resolved: it
    // closed because the return was filed, and recording that as a dismissal
    // would lose the difference between an alert that worked and one that was
    // swatted away.
    mockFetch(
      page([alert({ status: "read" })], { open_total: 1 }),
      alert({ status: "resolved" }),
    );
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Dismiss" }));

    // Gone from the open list, and never described as dismissed on the way out.
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument(),
    );
    expect(screen.queryByText("Dismissed")).not.toBeInTheDocument();
  });

  it("distinguishes a filed return from a swatted reminder under closed", async () => {
    const fetch = mockFetch(
      page([
        alert({ id: 1, status: "resolved", title: "GSTR-1 for 2026-03 is overdue" }),
        alert({ id: 2, status: "dismissed", title: "GSTR-3B for 2026-03 is overdue" }),
      ]),
      page([
        alert({ id: 1, status: "resolved", title: "GSTR-1 for 2026-03 is overdue" }),
        alert({ id: 2, status: "dismissed", title: "GSTR-3B for 2026-03 is overdue" }),
      ]),
    );
    renderPage();

    await screen.findByText(/GSTR-1 for 2026-03/);
    await userEvent.click(screen.getByRole("button", { name: "Closed" }));

    await waitFor(() => expect(fetch.mock.calls[1][0]).toContain("scope=closed"));
    expect(await screen.findByText("Filed")).toBeInTheDocument();
    expect(screen.getByText("Dismissed")).toBeInTheDocument();
  });

  it("offers no actions on an alert that is already closed", async () => {
    mockFetch(page([alert({ status: "resolved" })]));
    renderPage();

    await screen.findByText(/is overdue/);
    expect(screen.queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mark as read" })).not.toBeInTheDocument();
  });

  it("points a deadline alert at the screen that closes it properly", async () => {
    // Recording the filing is what resolves the alert; dismissing only
    // silences it. The route to the former should not be something to go and
    // find.
    mockFetch(page([alert()]));
    renderPage();

    expect(await screen.findByRole("link", { name: /Record filing/ })).toHaveAttribute(
      "href",
      "/filing",
    );
  });

  it("says the list is empty rather than showing nothing", async () => {
    mockFetch(page([]));
    renderPage();
    expect(await screen.findByText(/Nothing outstanding/)).toBeInTheDocument();
  });

  it("says an empty tab is empty in the terms of that tab", async () => {
    // Three tabs, three different findings. "Nothing outstanding" under
    // "Closed" would claim there is no backlog, which is the one thing the
    // closed tab says nothing about; "Nothing closed yet" under "All" would
    // claim alerts exist and are all open. Each sentence is acted on.
    mockFetch(page([]), page([]), page([]));
    renderPage();
    await screen.findByText(/Nothing outstanding/);

    await userEvent.click(screen.getByRole("button", { name: "Closed" }));
    expect(await screen.findByText("Nothing closed yet.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "All" }));
    expect(await screen.findByText(/No alerts yet/)).toBeInTheDocument();
  });

  it("labels a severity this build has never heard of, rather than a blank chip", async () => {
    // The severities are a server-side enum, and the chip is the whole of how
    // urgent an alert looks. A build that predates a new one must render the
    // row at its quietest rather than with nothing where the chip goes —
    // silence and "not urgent" are different claims, and only one is safe.
    mockFetch(page([alert({ severity: "catastrophic" })]));
    const { container } = renderPage();

    const row = (await screen.findByText(/is overdue/)).closest("li");
    expect(within(row).getByText("Upcoming")).toBeInTheDocument();
    expect(container.querySelector(".alert-row")).toHaveClass("is-neutral");
  });

  it("leaves the other rows alone when one of several is acted on", async () => {
    // The list is rebuilt from the acted-on alert's response, so every row
    // that is not it has to come through the rebuild unchanged. Marking one
    // read and finding a sibling's title or status altered would be a page
    // rewriting rows the server never spoke about.
    mockFetch(
      page([alert({ id: 1 }), alert({ id: 2, title: "GSTR-1 for 2026-04 is due soon" })]),
      alert({ id: 1, status: "read" }),
    );
    renderPage();
    await screen.findByText(/GSTR-1 for 2026-04 is due soon/);

    const first = screen.getByText(/GSTR-3B for 2026-04 is overdue/).closest("li");
    await userEvent.click(within(first).getByRole("button", { name: "Mark as read" }));

    await waitFor(() =>
      expect(within(first).queryByRole("button", { name: "Mark as read" })).not.toBeInTheDocument(),
    );
    // The sibling is untouched: still open, still offering both actions.
    const second = screen.getByText(/GSTR-1 for 2026-04 is due soon/).closest("li");
    expect(within(second).getByRole("button", { name: "Mark as read" })).toBeInTheDocument();
    expect(within(second).getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
  });

  it("does not banner a load it cancelled itself", async () => {
    // Switching tabs twice quickly aborts the middle load. Its rejection is
    // an expected part of the flow, and reporting it would put an error over
    // a list that arrived perfectly well.
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
    renderPage();

    pending[0].answer(page([alert()]));
    await screen.findByText(/is overdue/);

    await userEvent.click(screen.getByRole("button", { name: "Closed" }));
    await userEvent.click(screen.getByRole("button", { name: "All" }));
    await waitFor(() => expect(pending.length).toBe(3));

    pending[2].answer(page([alert({ status: "dismissed" })]));

    expect(await screen.findByText("Dismissed")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("reports a failure to load instead of looking empty", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "",
      text: async () => JSON.stringify({ detail: "Database unreachable" }),
    });
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent(/Database unreachable/);
    // And does not also say the backlog is clear. "Nothing outstanding" is the
    // one wrong answer this screen can give, because it is the answer a
    // business acts on by doing nothing.
    expect(screen.queryByText(/Nothing outstanding/)).not.toBeInTheDocument();
  });

  it("does not leave one tab's alerts under another tab", async () => {
    // The same fault the abort guard on this load exists to stop — closed
    // alerts under an "Open" tab — reached by the other road. A scope whose
    // load fails has no list of its own, and the rows left sitting there are
    // the tab the user just left: open alerts, with their Dismiss buttons
    // live, under a tab that says Closed.
    mockFetch(page([alert()]));
    renderPage();
    await screen.findByText(/GSTR-3B for 2026-04 is overdue/);

    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "",
      text: async () => JSON.stringify({ detail: "Database unreachable" }),
    });
    await userEvent.click(screen.getByRole("button", { name: /^Closed$/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Database unreachable/);
    expect(
      screen.queryByText(/GSTR-3B for 2026-04 is overdue/),
    ).not.toBeInTheDocument();
  });

  it("leaves the row alone when the action fails", async () => {
    const fetch = vi.fn();
    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: "",
      text: async () => JSON.stringify(page([alert()])),
    });
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: "",
      text: async () => JSON.stringify({ detail: "Could not save" }),
    });
    global.fetch = fetch;
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Dismiss" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not save/);
    // Still there, still dismissible — an optimistic removal would have hidden
    // an alert the server still considers open. Scoped to the row, because the
    // error banner has a Dismiss button of its own.
    const row = screen.getByRole("listitem");
    expect(within(row).getByText(/GSTR-3B for 2026-04 is overdue/)).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Dismiss" })).toBeEnabled();
  });

  it("names which alert failed when several are on screen", async () => {
    // `pending` is a set precisely because more than one row can be in flight
    // at once — so a banner that only repeats the server's message ("Could not
    // save") gives no way to tell which of several alerts needs a retry.
    const fetch = vi.fn();
    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: "",
      text: async () =>
        JSON.stringify(
          page([
            alert({ id: 1, title: "GSTR-3B for 2026-04 is overdue" }),
            alert({ id: 2, title: "GSTR-1 for 2026-04 is overdue" }),
          ]),
        ),
    });
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: "",
      text: async () => JSON.stringify({ detail: "Could not save" }),
    });
    global.fetch = fetch;
    renderPage();

    const rows = await screen.findAllByRole("listitem");
    await userEvent.click(within(rows[1]).getByRole("button", { name: "Dismiss" }));

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/GSTR-1 for 2026-04 is overdue/);
    expect(banner).not.toHaveTextContent(/GSTR-3B for 2026-04 is overdue/);
  });

  it("only disables the row being acted on", async () => {
    // Clearing a backlog is one row at a time, so a page-wide busy flag would
    // make every other alert unclickable while one request is in flight.
    let release;
    const fetch = vi.fn();
    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: "",
      text: async () => JSON.stringify(page([alert({ id: 1 }), alert({ id: 2 })])),
    });
    fetch.mockReturnValueOnce(new Promise((resolve) => (release = resolve)));
    global.fetch = fetch;
    renderPage();

    const rows = await screen.findAllByRole("listitem");
    await userEvent.click(within(rows[0]).getByRole("button", { name: "Dismiss" }));

    expect(within(rows[0]).getByRole("button", { name: "Dismiss" })).toBeDisabled();
    expect(within(rows[1]).getByRole("button", { name: "Dismiss" })).toBeEnabled();

    release({
      ok: true,
      status: 200,
      statusText: "",
      text: async () => JSON.stringify(alert({ id: 1, status: "dismissed" })),
    });
  });

  it("counts the open alerts on the tab", async () => {
    mockFetch(page([alert({ id: 1 }), alert({ id: 2 })]));
    renderPage();
    expect(await screen.findByRole("button", { name: /Open \(2\)/ })).toBeInTheDocument();
  });

  /** A fetch whose list is fixed and whose every dismiss is held open. */
  function heldDismissals(list) {
    const releases = [];
    const fetch = vi.fn(async (url, options) => {
      const body = (data) => ({
        ok: true,
        status: 200,
        statusText: "",
        text: async () => JSON.stringify(data),
      });
      if (options?.method === "POST" || String(url).includes("/dismiss")) {
        const id = Number(String(url).match(/alerts\/(\d+)/)[1]);
        await new Promise((resolve) => releases.push(resolve));
        return body(alert({ id, status: "dismissed" }));
      }
      return body(list);
    });
    global.fetch = fetch;
    return { fetch, releaseAll: () => releases.forEach((resolve) => resolve()) };
  }

  it("keeps a row disabled while its own request is still in flight", async () => {
    // The per-row busy flag has to be per row. Held as a single id, the second
    // row clicked took the flag off the first — so a row whose dismissal was
    // still in the air went clickable again, which is the one state this
    // button is disabled to prevent. Clearing a backlog is a run of quick
    // clicks down the list, so two in flight at once is the normal case here,
    // not an edge one.
    const { releaseAll } = heldDismissals(
      page([alert({ id: 1 }), alert({ id: 2 }), alert({ id: 3 })]),
    );
    renderPage();

    const rows = await screen.findAllByRole("listitem");
    await userEvent.click(within(rows[0]).getByRole("button", { name: "Dismiss" }));
    await userEvent.click(within(rows[1]).getByRole("button", { name: "Dismiss" }));

    // Both are waiting on the network; neither may be clicked again.
    expect(within(rows[0]).getByRole("button", { name: "Dismiss" })).toBeDisabled();
    expect(within(rows[1]).getByRole("button", { name: "Dismiss" })).toBeDisabled();
    // The row nobody touched stays live — the reason the flag is per row.
    expect(within(rows[2]).getByRole("button", { name: "Dismiss" })).toBeEnabled();

    releaseAll();
  });

  it("does not let a re-enabled row take the same alert off the count twice", async () => {
    // What the lost busy flag costs. Dismissing the same alert twice is
    // harmless server-side — it was already dismissed and stays dismissed —
    // but each answer comes back closed, and the badge is decremented once per
    // answer. The count then under-reports the backlog until the next load,
    // and under-reporting is the direction that gets a deadline missed.
    const { fetch, releaseAll } = heldDismissals(
      page([alert({ id: 1 }), alert({ id: 2 }), alert({ id: 3 })]),
    );
    renderPage();

    await screen.findByRole("button", { name: /Open \(3\)/ });
    const rows = screen.getAllByRole("listitem");
    await userEvent.click(within(rows[0]).getByRole("button", { name: "Dismiss" }));
    await userEvent.click(within(rows[1]).getByRole("button", { name: "Dismiss" }));
    await userEvent.click(within(rows[0]).getByRole("button", { name: "Dismiss" }));

    releaseAll();

    // Alert 1 and alert 2, once each: one left open.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Open \(1\)/ })).toBeInTheDocument(),
    );
    const dismissals = fetch.mock.calls.filter(([url]) => String(url).includes("/dismiss"));
    expect(dismissals).toHaveLength(2);
  });
});

describe("an action that outlives the tab it was started on", () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  /** A fetch whose *dismiss* call is held open until the test releases it. */
  function heldDismiss({ openList, closedList }) {
    let release;
    const held = new Promise((resolve) => {
      release = resolve;
    });
    const fetch = vi.fn(async (url, options) => {
      const body = (data) => ({
        ok: true,
        status: 200,
        statusText: "",
        text: async () => JSON.stringify(data),
      });
      if (options?.method === "POST" || String(url).includes("/dismiss")) {
        await held;
        return body(alert({ id: 1, status: "dismissed" }));
      }
      return body(String(url).includes("scope=closed") ? closedList : openList);
    });
    global.fetch = fetch;
    return { fetch, release: () => release() };
  }

  it("does not pull the row out of the tab it now belongs to", async () => {
    // Dismissing under "Open" and stepping to "Closed" while the request is
    // still going: the answer describes the open list, which is gone. Applied
    // to the closed list it removed the very alert that had just earned its
    // place there.
    const { fetch, release } = heldDismiss({
      openList: page([alert({ id: 1 })]),
      closedList: page([alert({ id: 1, status: "dismissed" })]),
    });
    renderPage();

    await screen.findByText(/is overdue/);
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    await userEvent.click(screen.getByRole("button", { name: "Closed" }));
    await waitFor(() => expect(fetch.mock.calls.at(-1)[0]).toContain("scope=closed"));

    release();

    // The closed tab keeps the alert the server says is closed.
    expect(await screen.findByText("Dismissed")).toBeInTheDocument();
  });

  it("does not take the same alert off the open count twice", async () => {
    // The reload for the new tab already set `open_total` from the server, so
    // a late decrement on top of it takes off one that had already gone — and
    // the badge then under-reports the backlog until the next load.
    const { fetch, release } = heldDismiss({
      openList: page([alert({ id: 1 }), alert({ id: 2 }), alert({ id: 3 })]),
      closedList: page([alert({ id: 1, status: "dismissed" })], { open_total: 2 }),
    });
    renderPage();

    await screen.findByRole("button", { name: /Open \(3\)/ });
    await userEvent.click(screen.getAllByRole("button", { name: "Dismiss" })[0]);
    await userEvent.click(screen.getByRole("button", { name: "Closed" }));
    await waitFor(() => expect(fetch.mock.calls.at(-1)[0]).toContain("scope=closed"));

    release();
    await screen.findByText("Dismissed");

    // Two left open, not one.
    expect(screen.getByRole("button", { name: /Open \(2\)/ })).toBeInTheDocument();
  });

  it("still says so when the action itself failed", async () => {
    // Held until after the tab has changed, so the rejection lands in the same
    // window the two tests above are about. Unlike a superseded load, this is
    // something the user asked for — it failing is worth saying wherever they
    // happen to be standing, so it is the one thing that outlives the tab.
    let reject;
    const held = new Promise((_resolve, r) => {
      reject = r;
    });
    const fetch = vi.fn(async (url, options) => {
      const body = (data, status = 200) => ({
        ok: status < 300,
        status,
        statusText: "",
        text: async () => JSON.stringify(data),
      });
      if (options?.method === "POST") {
        await held;
        return body({}, 500);
      }
      return body(String(url).includes("scope=closed") ? page([]) : page([alert({ id: 1 })]));
    });
    global.fetch = fetch;
    renderPage();

    await screen.findByText(/is overdue/);
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    await userEvent.click(screen.getByRole("button", { name: "Closed" }));
    await waitFor(() => expect(fetch.mock.calls.at(-1)[0]).toContain("scope=closed"));

    reject(new TypeError("Failed to fetch"));

    // The banner says what happened, not what the browser called it. A `fetch`
    // that rejects has not reached the server at all, and `Failed to fetch` —
    // or `Load failed`, or `NetworkError when attempting to fetch resource`,
    // depending on whose browser this is — names none of that and suggests
    // nothing to do about it. What is asserted is still this test's own point:
    // the failure of something the user asked for outlives the tab they were
    // on when they asked.
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Could not reach the server/,
    );
  });
});

describe("a viewer", () => {
  // The API answers 403 to both alert writes. Before this, the buttons were
  // rendered anyway, so the only way to find out was to click one and read a
  // refusal — on a screen whose whole purpose is working through a backlog.
  it("is not offered the two actions it would be refused", async () => {
    mockFetch(page([alert()]));
    renderPage({ role: "viewer" });
    await screen.findByText(/is overdue/);

    expect(screen.queryByRole("button", { name: "Mark as read" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Dismiss" })).toBeNull();
    // And the shortcut to the filing screen goes with them: it leads to the
    // one control there that a viewer also does not have.
    expect(screen.queryByRole("link", { name: "Record filing" })).toBeNull();
  });

  it("still reads every alert, which is what it is here for", async () => {
    mockFetch(page([alert()]));
    renderPage({ role: "viewer" });

    expect(await screen.findByText(/is overdue/)).toBeInTheDocument();
    expect(screen.getByText(/was due on 2026-05-20/)).toBeInTheDocument();
    expect(screen.getByText("Overdue")).toBeInTheDocument();
  });

  it("leaves an owner both actions", async () => {
    // The other half of the claim: the gate is the role, not something that
    // removed the buttons for everyone.
    mockFetch(page([alert()]));
    renderPage();
    await screen.findByText(/is overdue/);

    expect(screen.getByRole("button", { name: "Mark as read" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
  });
});

describe("AlertsPage beyond the first page", () => {
  // The list asked for no page, so it showed the API's first fifty: a backlog
  // past that was there in the badge's count and nowhere on screen.
  const OPEN = ["pending", "sent", "read", "failed"];

  function server(count) {
    const store = Array.from({ length: count }, (_, i) =>
      alert({ id: i + 1, title: `Alert ${i + 1}` }),
    );
    global.fetch = vi.fn(async (url, init) => {
      const u = new URL(String(url), "http://x");
      const respond = (body) => ({
        ok: true, status: 200, statusText: "", text: async () => JSON.stringify(body),
      });
      const dismissed = u.pathname.match(/\/alerts\/(\d+)\/dismiss$/);
      if (dismissed && init?.method === "POST") {
        const row = store.find((a) => a.id === Number(dismissed[1]));
        row.status = "dismissed";
        return respond(row);
      }
      const scope = u.searchParams.get("scope") ?? "open";
      const limit = Number(u.searchParams.get("limit") ?? 50);
      const offset = Number(u.searchParams.get("offset") ?? 0);
      const inScope = store.filter((a) => (scope === "open") === OPEN.includes(a.status));
      return respond({
        items: inScope.slice(offset, offset + limit),
        total: inScope.length,
        open_total: store.filter((a) => OPEN.includes(a.status)).length,
        limit,
        offset,
      });
    });
  }

  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("pages through the whole backlog", async () => {
    server(120);
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText("1–50 of 120")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("51–100 of 120")).toBeInTheDocument();
    expect(await screen.findByText("Alert 51")).toBeInTheDocument();
  });

  it("brings the next alert up after a dismissal instead of skipping it", async () => {
    server(51);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("1–50 of 51");
    expect(screen.queryByText("Alert 51")).not.toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: /Dismiss/ })[0]);

    expect(await screen.findByText("Alert 51")).toBeInTheDocument();
  });

  it("starts another tab from its first page", async () => {
    server(120);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("1–50 of 120");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("51–100 of 120");

    await user.click(screen.getByRole("button", { name: "Closed" }));

    await waitFor(() => expect(String(global.fetch.mock.calls.at(-1)[0])).not.toContain("offset=50"));
  });
});
