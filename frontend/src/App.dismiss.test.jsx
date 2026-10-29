/**
 * The banner every page puts its errors in, and the button on it nothing pressed.
 *
 * Seven pages render `<ErrorBanner … onDismiss={() => setError("")} />` and
 * the coverage report named all seven the same way: the handler was the only
 * function in the file no test ever called. That is the shape a dismissal gap
 * always has — the banner's *appearance* is what a page test is written about,
 * because that is the behaviour someone was fixing, and the × beside it is
 * added in the same commit and asserted in none.
 *
 * What it costs to leave alone is not the coverage figure. This banner is
 * `role="alert"`, so it is announced the moment it appears and it stays on
 * screen until something clears it; a dismissal that did not work would leave
 * a stale sentence sitting above a page that has since recovered, and the
 * banner is exactly where a user looks to find out whether it has. So the
 * sweep is over the route table rather than one page: a screen that lands
 * without a working × fails here rather than in a report about an error
 * message that would not go away.
 *
 * The dismissal is required to clear the *banner* and nothing else. Every one
 * of these pages says a second thing underneath — an empty panel, a skeleton
 * that never filled, a table with no rows — and those describe a period that
 * still has no data. Clearing them with the banner would turn "we could not
 * find out" into "there is nothing here", which is the one reading a user
 * acts on differently.
 *
 * One banner in the app deliberately has no ×, and it is asserted here as
 * such rather than left out: the invoice screen renders a second, undismissable
 * one for the case where the invoice never arrived, because there the sentence
 * is the whole page. See the second describe block.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import ErrorBoundary from "./components/ErrorBoundary";
import { AuthProvider } from "./hooks/useAuth";
import { PageTitleProvider } from "./hooks/usePageTitle";
import { StateCodesProvider } from "./hooks/useStateCodes";
import { PURCHASE, SALE, installBackend } from "./test/backend";

const TODAY = new Date(2026, 4, 14);

/**
 * The books, behind a server that has fallen over.
 *
 * The session endpoints are let through for the same reason `App.loading`
 * lets them through: `Protected` renders its own placeholder until `/auth/me`
 * lands, and a page that never mounts shows no banner to dismiss. Everything
 * else answers 500 — chosen over a 404 deliberately, because a 404 is the
 * ordinary empty state on several of these screens and is not an error at all.
 */
function brokenBackend(fails = () => true) {
  const backend = installBackend({ invoices: [PURCHASE, SALE], imported: true });
  const answer = backend.fetch;

  global.fetch = vi.fn((input, init) => {
    const href = String(input);
    if (href.includes("/auth/me") || href.includes("/businesses/mine")) {
      return answer(input, init);
    }
    if (!fails(href, (init?.method ?? "GET").toUpperCase())) {
      return answer(input, init);
    }
    const body = JSON.stringify({
      detail: "The server is having a bad day.",
      error: { code: "server_error", status: 500, message: "The server is having a bad day." },
      correlation_id: "dismisstest0000",
    });
    return Promise.resolve({
      ok: false,
      status: 500,
      statusText: "",
      text: async () => body,
      blob: async () => new Blob([body], { type: "application/json" }),
      headers: { get: () => null },
    });
  });
}

function renderApp(route) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <PageTitleProvider>
        <ErrorBoundary>
          <StateCodesProvider>
            <AuthProvider>
              <App />
            </AuthProvider>
          </StateCodesProvider>
        </ErrorBoundary>
      </PageTitleProvider>
    </MemoryRouter>,
  );
}

/**
 * Every screen that reports a failed read, and what it still says afterwards.
 *
 * `remains` is the sentence the page owes the user once the banner is gone.
 * Without it this file would pass on a page that cleared the whole screen on
 * dismissal, which is the failure a "the banner disappears" assertion invites.
 */
const SCREENS = [
  { route: "/", remains: /Dashboard/ },
  { route: "/invoices", remains: /Invoices/ },
  { route: "/reconcile", remains: /GSTR-2B/ },
  { route: "/itc", remains: /Input tax credit/i },
  { route: "/filing", remains: /Filing/ },
  { route: "/suppliers", remains: /Suppliers/ },
  { route: "/alerts", remains: /Alerts/ },
];

describe("dismissing the error a page reports", () => {
  beforeEach(() => {
    vi.setSystemTime(TODAY);
    localStorage.setItem("gstbot_token", "dismiss-token");
    brokenBackend();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it.each(SCREENS)("$route lets the user close it", async ({ route, remains }) => {
    const user = userEvent.setup();
    renderApp(route);

    const banner = await screen.findByRole("alert");
    await user.click(within(banner).getByRole("button", { name: "Dismiss" }));

    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    // The page is still the page. Dismissing says "I have read this", not
    // "reload without it".
    expect(screen.getAllByText(remains).length).toBeGreaterThan(0);
  });

  it("says nothing about a period once the sentence about it has been closed", async () => {
    // The banner names what failed. Left behind after the user closes it, the
    // same sentence would still be the first thing read on the next visit to
    // this screen, describing a request that is no longer in flight.
    const user = userEvent.setup();
    renderApp("/reconcile");

    const banner = await screen.findByRole("alert");
    const message = banner.textContent;
    await user.click(within(banner).getByRole("button", { name: "Dismiss" }));

    await waitFor(() =>
      expect(screen.queryByText(message.replace(/×$/, ""))).not.toBeInTheDocument(),
    );
  });
});

describe("the invoice screen, which has two banners and only closes one", () => {
  beforeEach(() => {
    vi.setSystemTime(TODAY);
    localStorage.setItem("gstbot_token", "dismiss-token");
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("closes the refusal an action came back with", async () => {
    // The invoice is on screen and something done to it was refused. Closing
    // that leaves the whole document still readable, which is the state this
    // banner sits above.
    brokenBackend((href, method) => method !== "GET");
    const user = userEvent.setup();
    renderApp("/invoices/1");

    await screen.findByRole("button", { name: "Re-extract" });
    await user.click(screen.getByRole("button", { name: "Re-extract" }));

    const banner = await screen.findByRole("alert");
    await user.click(within(banner).getByRole("button", { name: "Dismiss" }));

    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Re-extract" })).toBeInTheDocument();
  });

  it("leaves the failure to load the invoice on screen, with nothing to close it", async () => {
    // Deliberately the one banner with no ×, and the page is the reason: when
    // the invoice itself never arrived this sentence is the entire content of
    // the screen. A dismissal here would clear the page to nothing and leave
    // the user with no statement of what went wrong and no invoice either —
    // so the way out is the browser's back button, not a button that empties
    // the page. Asserted so that adding the × looks like the regression it is.
    brokenBackend((href) => href.includes("/invoices/1"));
    renderApp("/invoices/1");

    const banner = await screen.findByRole("alert");
    expect(within(banner).queryByRole("button", { name: "Dismiss" })).toBeNull();
  });
});

describe("dismissing a refused sign-in", () => {
  beforeEach(() => {
    vi.setSystemTime(TODAY);
    localStorage.removeItem("gstbot_token");
    brokenBackend();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("closes the refusal so the form can be tried again", async () => {
    // The only one of these banners a user meets before they are signed in,
    // and the only one that sits over a form they are expected to correct and
    // resubmit. A rejection that would not close stays over the second
    // attempt, which then reads as having been refused as well.
    const user = userEvent.setup();
    renderApp("/login");

    await user.click(await screen.findByRole("tab", { name: "Sign in" }));
    await user.type(screen.getByLabelText("Email"), "owner@example.com");
    await user.type(screen.getByLabelText("Password"), "hunter2hunter2");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    const banner = await screen.findByRole("alert");
    await user.click(within(banner).getByRole("button", { name: "Dismiss" }));

    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });
});

describe("a deep link opened while signed out", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("is remembered, so signing in can come back to it", async () => {
    installBackend();
    renderApp("/invoices?status=failed");
    await waitFor(() => expect(sessionStorage.getItem("gstbot_return_to")).toBe("/invoices?status=failed"));
  });
});
