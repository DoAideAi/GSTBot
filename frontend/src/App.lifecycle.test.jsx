/**
 * One month, start to finish, through the app a business actually uses.
 *
 * Every page in this suite is tested on its own against a mock written for it,
 * which is the right way to assert what a page does with an answer and the
 * wrong way to assert that the answer one page produced is the one the next
 * page asks about. A per-page fixture hands each screen its data directly, so
 * the handoffs — the invoice the upload created appearing in the register, the
 * run reconciling what was uploaded rather than what was seeded, the return
 * declaring the sale — are exactly what those tests cannot see.
 *
 * So this file mounts the whole app the way `main.jsx` does, over the single
 * mutable server in `test/backend.js`, and walks the lifecycle by clicking:
 * upload → parse → reconcile → file. The assertions are on what carried over
 * from the previous step, not on arithmetic the page tests already own.
 *
 * The clock is fixed at 14 May 2026 so "the month you are filing for" is
 * April: every period picker in the app opens on the current month, and a
 * return for a month that has not ended is one the server refuses to record.
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
import {
  PERIOD,
  PURCHASE,
  SALE,
  SUPPLIER_GSTIN,
  gstr2bFile,
  installBackend,
  invoiceFile,
} from "./test/backend";

/** 14 May 2026: April has ended, so April is what gets filed. */
const TODAY = new Date(2026, 4, 14);

/**
 * The whole app, composed as `main.jsx` composes it.
 *
 * StrictMode is the one thing left out. It double-invokes effects, which would
 * double every request this backend counts, and what is under test here is the
 * sequence of screens rather than React's own remount behaviour.
 */
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

/** Click a nav link and wait for the page it leads to. */
async function goTo(user, label, heading) {
  // Through the main menu, as a user moves between pages. A page can carry a
  // link of the same name (the filing page's "Next steps" has Dashboard).
  const menu = screen.getByRole("navigation", { name: "Main" });
  await user.click(within(menu).getByRole("link", { name: label }));
  return screen.findByRole("heading", { name: heading, level: 1 });
}

/** Choose April in whichever period picker the current page is showing. */
async function selectApril(user) {
  await user.selectOptions(screen.getByLabelText("Period"), PERIOD);
}

/**
 * A stat tile by its label.
 *
 * The figures repeat further down every screen that has these — the ITC
 * position is in the tiles, the by-head table and the set-off working — so a
 * bare text match would pass on the wrong one.
 */
function statCard(label) {
  const card = [...document.querySelectorAll(".stat-card")].find(
    (node) => node.querySelector(".stat-label")?.textContent === label,
  );
  if (!card) throw new Error(`no stat card labelled "${label}"`);
  return card;
}

describe("the invoice lifecycle, end to end", () => {
  let backend;

  beforeEach(() => {
    vi.setSystemTime(TODAY);
    localStorage.setItem("gstbot_token", "flow-token");
    backend = installBackend();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("carries one purchase and one sale from upload through to a filed return", async () => {
    const user = userEvent.setup();
    renderApp();

    // --- The books before anything is in them ---------------------------
    // The dashboard is the landing screen, and a business that has just signed
    // up should be told its books are empty rather than shown a broken one.
    await screen.findByRole("heading", { name: "Dashboard", level: 1 });
    await waitFor(() => expect(screen.getByText("Umang Traders")).toBeInTheDocument());

    // --- Upload the month's purchase ------------------------------------
    await goTo(user, "Upload", "Upload invoices");
    await user.upload(screen.getByLabelText("Choose files"), invoiceFile());

    // The extracted number, not the filename: what the page reports is what
    // the parser made of the document.
    expect(await screen.findByText(PURCHASE.invoice_number)).toBeInTheDocument();

    // --- And the sale, under the other type ------------------------------
    await user.click(screen.getByLabelText("Sales (feeds GSTR-1)"));
    await user.upload(screen.getByLabelText("Choose files"), invoiceFile("ut-0101.pdf"));
    expect(await screen.findByText(SALE.invoice_number)).toBeInTheDocument();

    // The type the radio was on is the type each was booked under. Getting
    // this wrong claims credit on the business's own output tax, so the
    // register below is checked for it rather than trusted.
    const purchase = backend.state.invoices.find(
      (row) => row.invoice_number === PURCHASE.invoice_number,
    );
    const sale = backend.state.invoices.find(
      (row) => row.invoice_number === SALE.invoice_number,
    );
    expect(purchase.invoice_type).toBe("purchase");
    expect(sale.invoice_type).toBe("sales");

    // --- Both are now in the register -----------------------------------
    await goTo(user, "Invoices", "Invoices");
    const rows = await screen.findAllByRole("row");
    expect(rows.length).toBe(3); // header, purchase, sale
    expect(screen.getByText(PURCHASE.counterparty_name)).toBeInTheDocument();
    expect(screen.getByText(SALE.counterparty_name)).toBeInTheDocument();

    // --- Opening one reaches the row the list linked to -------------------
    await user.click(screen.getByRole("link", { name: PURCHASE.invoice_number }));
    await screen.findByRole("heading", { name: PURCHASE.invoice_number, level: 1 });
    expect(screen.getByDisplayValue(SUPPLIER_GSTIN)).toBeInTheDocument();

    // --- Import the portal's 2B and match against it ----------------------
    await goTo(user, "Reconcile", "Reconciliation");
    await selectApril(user);
    await screen.findByText(/No GSTR-2B yet/);

    await user.upload(screen.getByLabelText("Import GSTR-2B"), gstr2bFile());
    // The count is the statement's own, and it counts the purchase that was
    // uploaded two steps ago rather than a fixture.
    await screen.findByText("Imported 1 invoices for 2026-04");

    await user.click(screen.getByRole("button", { name: "Run reconciliation" }));
    const findings = await screen.findByRole("heading", { name: "Findings", level: 2 });
    expect(findings).toBeInTheDocument();
    // Matched, because the statement declared exactly what the books hold.
    // This is the handoff the whole month turns on: a period reconciled
    // against the wrong statement reports everything missing.
    const run = backend.state.runs[0];
    expect(run.matched_count).toBe(1);
    expect(run.missing_in_2b_count).toBe(0);
    expect(run.itc_at_risk).toBe("0.00");

    // --- What that makes claimable ---------------------------------------
    await goTo(user, "ITC", "Input Tax Credit");
    await selectApril(user);
    // "Confirmed against 2B" is a claim this screen is entitled to make only
    // because of the run above — before it, the same period is captioned
    // "Unreconciled" over a banner saying so.
    await waitFor(() =>
      expect(statCard("Credit available")).toHaveTextContent("₹81,000.00"),
    );
    expect(statCard("Credit available")).toHaveTextContent("Confirmed against 2B");

    // --- Prepare and record the return ------------------------------------
    await goTo(user, "Filing", "Filing preparation");
    await selectApril(user);

    // Nothing blocking, on a period whose only sale carries a GSTIN that
    // checks out — the validation is of the invoices uploaded at the top of
    // this test, not of a fixture.
    await waitFor(() => expect(statCard("Ready to file")).toHaveTextContent("Yes"));
    expect(statCard("Invoices")).toHaveTextContent("1");

    // The GSTR-1 is built from that sale, so the customer's GSTIN is in the
    // document — which is what decides whether *they* can claim their credit.
    await user.click(screen.getByRole("button", { name: /Show generated JSON/ }));
    const document_ = await screen.findByLabelText("Generated return JSON");
    expect(document_).toHaveTextContent(SALE.counterparty_gstin);
    expect(document_).toHaveTextContent(SALE.invoice_number);

    await user.click(screen.getByRole("button", { name: "Mark GSTR-1 as filed" }));
    await screen.findByText(/Recorded GSTR-1 for April 2026 as filed/);
    expect(backend.state.filings[`gstr1:${PERIOD}`]).toMatchObject({ period: PERIOD });

    // The status table is refetched off the record rather than updated in
    // place, so what it now says is the server's answer and not the click's
    // optimism. The 3B beside it is still outstanding, which is the point of
    // recording them separately.
    const status = await screen.findByRole("region", { name: "Filing status by period" });
    await waitFor(() => expect(within(status).getByText("Filed")).toBeInTheDocument());

    // --- Back where we started, with the month in it ----------------------
    await goTo(user, "Dashboard", "Dashboard");
    await waitFor(() => expect(screen.getByText("Umang Traders")).toBeInTheDocument());
    // Two invoices, one of each direction: the same two that were uploaded.
    expect(backend.state.invoices).toHaveLength(2);
  });

  it("does not offer a reconciliation until there is a statement to match against", async () => {
    // The run button is disabled rather than absent, and the reason is on
    // screen above it. An enabled button here answers 422 — the server has
    // nothing to match — which reads as the app being broken.
    const user = userEvent.setup();
    renderApp("/reconcile");

    await screen.findByRole("heading", { name: "Reconciliation", level: 1 });
    await selectApril(user);
    await screen.findByText(/No GSTR-2B yet/);

    expect(screen.getByRole("button", { name: "Run reconciliation" })).toBeDisabled();
  });

  it("reports the credit at risk when the supplier never declared the invoice", async () => {
    // The path the product exists for: the 2B is imported first, and the
    // invoice is booked afterwards, so the statement does not declare it.
    // Every screen downstream has to agree that the credit is at risk.
    const user = userEvent.setup();
    backend = installBackend({ imported: true });
    renderApp("/upload");

    await screen.findByRole("heading", { name: "Upload invoices", level: 1 });
    await user.upload(screen.getByLabelText("Choose files"), invoiceFile());
    await screen.findByText(PURCHASE.invoice_number);

    await goTo(user, "Reconcile", "Reconciliation");
    await selectApril(user);
    await user.click(await screen.findByRole("button", { name: "Run reconciliation" }));

    await screen.findByRole("heading", { name: "Findings", level: 2 });
    const run = backend.state.runs[0];
    expect(run.missing_in_2b_count).toBe(1);
    expect(run.itc_at_risk).toBe("81000.00");
    expect(statCard("ITC at risk")).toHaveTextContent("₹81,000.00");

    // The ITC screen reaches the same conclusion through a different endpoint:
    // credit the statement does not support is not credit available to claim.
    // The two screens disagreeing is the bug this catches, and it is the one a
    // per-page fixture cannot produce.
    await goTo(user, "ITC", "Input Tax Credit");
    await selectApril(user);
    await waitFor(() => expect(statCard("Credit available")).toHaveTextContent("₹0.00"));
  });
});
