/**
 * What every screen shows while it is waiting.
 *
 * Three of the pages have a loading assertion in their own file and six do
 * not, which is the shape this kind of coverage always ends up in: whoever
 * wrote the page that jumped when its data landed added the test, and the rest
 * were never asked. A placeholder is easy to leave off and invisible when it is
 * missing — the page simply renders empty for 300ms and then fills in, which
 * nobody notices locally and everybody notices on a phone connection.
 *
 * So this is the sweep rather than nine separate assertions: every route is
 * mounted against a server that has not answered yet, and each is required to
 * be showing a placeholder that says what it is loading. A page that lands
 * without one fails here rather than in a bug report about the screen
 * flickering.
 *
 * The requirement is a *labelled* one. `Skeleton.jsx` puts the label in a
 * visually hidden span inside an `aria-live` region precisely so that waiting
 * is announced rather than being a silent gap, and a bar with no label is a
 * decoration that leaves a screen reader with nothing to say.
 */
import { render, screen, waitFor } from "@testing-library/react";
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
 * The books, behind a server that answers when told to.
 *
 * The session endpoints are let through: `Protected` renders its own
 * placeholder until `/auth/me` lands, and every page skeleton below would be
 * hidden behind it. Everything else waits for `release`, which is what makes
 * "before the first response" a state a test can stand in rather than race.
 */
function gatedBackend() {
  const backend = installBackend({ invoices: [PURCHASE, SALE], imported: true });
  const answer = backend.fetch;
  const waiting = [];

  global.fetch = vi.fn((input, init) => {
    const href = String(input);
    if (href.includes("/auth/me") || href.includes("/businesses/mine")) {
      return answer(input, init);
    }
    return new Promise((resolve) => {
      waiting.push(() => resolve(answer(input, init)));
    });
  });

  return { release: () => waiting.splice(0).forEach((send) => send()) };
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
 * Every screen that loads something, and the placeholder it owes the user.
 *
 * `settled` is what has to be on screen once the answer lands — without it a
 * page could satisfy this file by never leaving its skeleton, which is the one
 * failure a "the skeleton appears" assertion invites.
 */
const SCREENS = [
  { route: "/", loading: "Loading dashboard…", settled: /Umang Traders/ },
  { route: "/invoices", loading: "Loading invoices…", settled: /INV-2026-0042/ },
  { route: "/invoices/1", loading: "Loading invoice…", settled: /INV-2026-0042/ },
  { route: "/reconcile", loading: "Loading the GSTR-2B…", settled: /GSTR-2B for/ },
  { route: "/itc", loading: "Loading the ITC position…", settled: /Credit available/ },
  { route: "/filing", loading: "Loading the return preview…", settled: /Ready to file/ },
  { route: "/suppliers", loading: "Loading suppliers…", settled: /Northwind/ },
  { route: "/alerts", loading: "Loading alerts…", settled: /GSTR-3B for 2026-04/ },
  { route: "/status", loading: "Checking system status…", settled: /DoAide GST/ },
];

describe("what a screen shows before its data lands", () => {
  let gate;

  beforeEach(() => {
    vi.setSystemTime(TODAY);
    localStorage.setItem("gstbot_token", "flow-token");
    gate = gatedBackend();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it.each(SCREENS)("$route says what it is loading", async ({ route, loading }) => {
    renderApp(route);

    const label = await screen.findByText(loading);
    // The region, not the bars. The bars are `aria-hidden` decoration; the
    // region is what a screen reader is told about, and `aria-busy` is what
    // says it is not simply empty.
    const region = label.closest("[aria-live]");
    expect(region).toHaveAttribute("aria-busy", "true");
    expect(region).toHaveAttribute("aria-live", "polite");
    expect(label).toHaveClass("visually-hidden");
  });

  it.each(SCREENS)("$route replaces it with the answer", async ({ route, loading, settled }) => {
    renderApp(route);
    await screen.findByText(loading);

    gate.release();

    // Ten seconds rather than the default one, in a twenty-second test: under
    // CI's coverage instrumentation, with every file running in parallel, the
    // lazy page chunk can take seconds to land. '/suppliers' failed there on
    // commits that touched no frontend, first at the 1s wait and then at the
    // 5s test timeout once the wait was longer.
    await waitFor(
      () => expect(screen.getAllByText(settled).length).toBeGreaterThan(0),
      { timeout: 10000 },
    );
    expect(screen.queryByText(loading)).not.toBeInTheDocument();
  }, 20000);

  it("holds a protected route behind its own placeholder until the session is confirmed", async () => {
    // Before any page's skeleton there is this one, and it is the reason the
    // rest are reachable at all: rendering the redirect on a null `user` that
    // has simply not arrived yet bounces a signed-in visitor to the login page
    // on every refresh.
    let confirm;
    global.fetch = vi.fn(
      () => new Promise((resolve) => {
        confirm = resolve;
      }),
    );

    renderApp("/");
    const label = await screen.findByText("Checking your session…");
    expect(label.closest("[aria-live]")).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();

    // Left resolved rather than dangling: an unsettled promise at teardown
    // resolves into an unmounted tree and React warns about the state update.
    confirm({
      ok: true,
      status: 200,
      statusText: "",
      text: async () => JSON.stringify({}),
    });
    await waitFor(() =>
      expect(screen.queryByText("Checking your session…")).not.toBeInTheDocument(),
    );
  });

  it("locks the upload form behind a spinner rather than a skeleton", async () => {
    // The one screen with no placeholder, deliberately: nothing is being
    // fetched when it opens. Its waiting state is a batch in flight, and what
    // it owes the user then is a count and a locked picker — a skeleton would
    // mean throwing away the results already listed above it.
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderApp("/upload");

    await screen.findByRole("heading", { name: "Upload invoices", level: 1 });
    await user.upload(
      screen.getByLabelText("Choose files"),
      new File(["%PDF-1.4"], "bill.pdf", { type: "application/pdf" }),
    );

    // The spinner's own hidden label and the count beside it: one says
    // something is happening, the other says how much of the batch is left.
    const progress = await screen.findByRole("status");
    expect(progress).toHaveTextContent("Extracting…");
    expect(progress).toHaveTextContent("Extracting 1 of 1");
    expect(screen.getByLabelText("Purchase (claim ITC)")).toBeDisabled();

    gate.release();
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    expect(screen.getByLabelText("Purchase (claim ITC)")).toBeEnabled();
  });
});
