/**
 * A viewer's whole session, page by page, against a server that means it.
 *
 * The per-page tests each mount one screen with `StubAuth role="viewer"` and
 * check that its controls are gone. That is the right question asked eleven
 * times, and it leaves two it cannot ask. The first is whether a viewer can
 * still *use* the product — a page hidden rather than made read-only passes
 * every "the button is absent" assertion while being a wall. The second is
 * whether hiding is all that stands there: `canWrite` decides what renders,
 * `require_writer` decides what happens, and a screen tested only against a
 * client-side flag would look identical whether or not the server agreed.
 *
 * So this walks the app as a viewer over the same fake server the lifecycle
 * flow uses, with the role set on the server as well as in the session: every
 * read answers, every write refuses 403, and the tour is checked for having
 * sent no write at all. The role comes from `/auth/me` rather than from a stub,
 * so `active_role` is doing the work it does in the browser.
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
import { PERIOD, PURCHASE, SALE, installBackend } from "./test/backend";

const TODAY = new Date(2026, 4, 14);

/** The books the viewer has been given sight of: a month, already reconciled. */
function preparedBooks(role) {
  const backend = installBackend({ role, invoices: [PURCHASE, SALE], imported: true });
  // A run, so the screens that report on one have something to report. Made
  // through the same path a write would take, before the role is applied to
  // anything the test drives.
  backend.state.runs.unshift({
    id: 1,
    period: PERIOD,
    status: "completed",
    total_invoices: 1,
    matched_count: 1,
    mismatched_count: 0,
    missing_in_2b_count: 0,
    missing_in_books_count: 0,
    duplicate_count: 0,
    itc_eligible: "81000.00",
    itc_at_risk: "0.00",
    itc_claimed: "81000.00",
    started_at: "2026-05-14T10:01:00Z",
    completed_at: "2026-05-14T10:01:02Z",
    error: null,
    created_at: "2026-05-14T10:01:00Z",
    report: { tolerance: "1.00", findings: [] },
  });
  return backend;
}

function renderApp(route = "/") {
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

async function goTo(user, label, heading) {
  await user.click(screen.getByRole("link", { name: label }));
  return screen.findByRole("heading", { name: heading, level: 1 });
}

/** Requests this session sent that would have changed something. */
function writesSent(backend) {
  return backend.state.calls.filter((call) => !call.startsWith("GET "));
}

describe("a viewer's session, end to end", () => {
  let backend;

  beforeEach(() => {
    vi.setSystemTime(TODAY);
    localStorage.setItem("gstbot_token", "flow-token");
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("can read every screen the owner can", async () => {
    // The half that a "the button is gone" assertion cannot fail on. Read-only
    // access whose reads do not work is not read-only access.
    const user = userEvent.setup();
    backend = preparedBooks("viewer");
    renderApp();

    await screen.findByRole("heading", { name: "Dashboard", level: 1 });
    await waitFor(() => expect(screen.getByText("Umang Traders")).toBeInTheDocument());

    await goTo(user, "Invoices", "Invoices");
    expect(await screen.findByText(PURCHASE.invoice_number)).toBeInTheDocument();
    expect(screen.getByText(SALE.invoice_number)).toBeInTheDocument();

    await goTo(user, "Reconcile", "Reconciliation");
    await user.selectOptions(screen.getByLabelText("Period"), PERIOD);
    // The statement panel, populated: a viewer sees what was imported and
    // what the last run made of it, which is the whole reason to grant one.
    await screen.findByText(/invoices imported/);

    await goTo(user, "ITC", "Input Tax Credit");
    await user.selectOptions(screen.getByLabelText("Period"), PERIOD);
    await waitFor(() => expect(screen.getAllByText("Credit available").length).toBeGreaterThan(0));

    await goTo(user, "Filing", "Filing preparation");
    await user.selectOptions(screen.getByLabelText("Period"), PERIOD);
    await waitFor(() => expect(screen.getByText("Ready to file")).toBeInTheDocument());

    await goTo(user, "Suppliers", "Suppliers");
    expect(await screen.findByText(/Northwind/)).toBeInTheDocument();

    // The link's name carries the open count — "Alerts (1 open)" — once the
    // books have an alert, so it is matched by its start.
    await goTo(user, /^Alerts\b/, "Alerts");
    expect(await screen.findByText(/GSTR-3B for 2026-04 is due soon/)).toBeInTheDocument();

    // Nine screens, and not one request that would have changed anything.
    expect(writesSent(backend)).toEqual([]);
  });

  it("is told why the controls are missing, on the screens that are only controls", async () => {
    // Hiding a control with nothing in its place is the failure the notice
    // exists to prevent: the upload page without its dropzone is a page that
    // reads as broken, and a viewer who does not know they are a viewer files
    // a bug instead of asking for the access they need.
    const user = userEvent.setup();
    backend = preparedBooks("viewer");
    renderApp("/upload");

    await screen.findByRole("heading", { name: "Upload invoices", level: 1 });
    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent(/your role on Umang Traders Private Limited is viewer/i);
    expect(notice).toHaveTextContent(/ask an owner or an accountant to upload invoices/i);
    // The whole write is gone with it — a dropzone that answered 403 on drop
    // would be worse than no dropzone.
    expect(screen.queryByLabelText("Choose files")).not.toBeInTheDocument();

    await goTo(user, "Reconcile", "Reconciliation");
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        /ask an owner or an accountant to import GSTR-2B or run a reconciliation/i,
      ),
    );
    expect(screen.queryByRole("button", { name: "Run reconciliation" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/GSTR-2B$/)).not.toBeInTheDocument();
  });

  it("keeps the reads on a screen whose writes are gone", async () => {
    // Filing is the case that decides whether the rule is "hide the page" or
    // "hide the write": handing the exported JSON to the CA who *can* file it
    // is most of what a viewer is on this screen to do, so the export stays
    // and only the recording goes.
    const user = userEvent.setup();
    backend = preparedBooks("viewer");
    renderApp("/filing");

    await screen.findByRole("heading", { name: "Filing preparation", level: 1 });
    await user.selectOptions(screen.getByLabelText("Period"), PERIOD);

    expect(
      await screen.findByRole("button", { name: /Download GSTR-1 JSON/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download CSV" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Mark GSTR-1 as filed/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/ARN/)).not.toBeInTheDocument();
  });

  it("offers no row action an alert or an invoice would refuse", async () => {
    const user = userEvent.setup();
    backend = preparedBooks("viewer");
    renderApp("/alerts");

    await screen.findByRole("heading", { name: "Alerts", level: 1 });
    const alert = await screen.findByRole("listitem");
    expect(within(alert).queryByRole("button")).not.toBeInTheDocument();

    // And on one invoice, where the write is an edit rather than a button —
    // the fields are rendered read-only rather than removed, because a detail
    // page with its figures stripped out is not a detail page.
    await goTo(user, "Invoices", "Invoices");
    await user.click(await screen.findByRole("link", { name: PURCHASE.invoice_number }));
    await screen.findByRole("heading", { name: PURCHASE.invoice_number, level: 1 });

    // Rendered into the form's fields and the fieldset disabled around them,
    // rather than the form being removed: a field that looks editable and
    // silently discards what is typed into it is worse than one that never
    // invited the typing, and a detail page with its figures gone is not one.
    const name = screen.getByDisplayValue(PURCHASE.counterparty_name);
    expect(name).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Save/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete/ })).not.toBeInTheDocument();
    expect(writesSent(backend)).toEqual([]);
  });

  it("is refused by the server, not merely by the screen", async () => {
    // What the hiding is not. `canWrite` decides what renders and
    // `require_writer` decides what happens, and every assertion above would
    // read the same if the second had been left off — so the same session's
    // token is put through a write directly.
    backend = preparedBooks("viewer");
    renderApp("/");
    await screen.findByRole("heading", { name: "Dashboard", level: 1 });

    const { api } = await import("./lib/api");
    await expect(api.reconcile(PERIOD)).rejects.toThrow(/viewer/);

    // And the refusal is one a person can act on: it names the role held and
    // who to ask, rather than reporting a status.
    await expect(api.recordFiled("gstr1", { period: PERIOD })).rejects.toThrow(
      /Ask an owner or an accountant/,
    );
  });

  it("gives the same session every control back when the role does", async () => {
    // The control case. Every assertion above is "the control is absent", and
    // a page that rendered no controls for anybody would satisfy all of them.
    const user = userEvent.setup();
    backend = preparedBooks("owner");
    renderApp("/upload");

    await screen.findByRole("heading", { name: "Upload invoices", level: 1 });
    expect(screen.getByLabelText("Choose files")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    await goTo(user, "Reconcile", "Reconciliation");
    await user.selectOptions(screen.getByLabelText("Period"), PERIOD);
    expect(
      await screen.findByRole("button", { name: "Run reconciliation" }),
    ).toBeInTheDocument();
  });
});
