/**
 * A DoAide GST API small enough to keep in one file and whole enough to walk
 * through.
 *
 * Every other test in this suite mounts one page and mocks the one or two
 * endpoints it reads. That is the right shape for asserting what a page does
 * with an answer, and it is the wrong shape for asserting that the answer one
 * page produced is the one the next page asks about — because a per-page mock
 * hands each screen its fixture directly, and a lifecycle that never carries a
 * value forward cannot be the one that breaks.
 *
 * So this is a single mutable server behind `global.fetch`: an upload adds an
 * invoice, the invoice list is the invoices that were uploaded, the 2B is what
 * was imported, a run is matched against both, and the return is built from
 * whatever is in the register by then. The figures are recomputed from the
 * stored rows on every read rather than canned, so a flow that skips a step
 * sees the screen a user who skipped it would see.
 *
 * It is deliberately not a reimplementation of the backend. The GST
 * arithmetic — tax splits, set-off order, late fees, scoring — is owned by the
 * Python suite and is fixed here at whatever the seeded documents make it.
 * What this reproduces faithfully is the *shape* of each response, the status
 * codes, and the one rule the RBAC flow turns on: a viewer's writes come back
 * 403 from the server, not merely hidden by the client.
 */
import { vi } from "vitest";

export const BUSINESS_GSTIN = "27AAPFU0939F1ZV";
export const SUPPLIER_GSTIN = "29AAGCB7383J1Z4";
export const CUSTOMER_GSTIN = "27AACCM6094J1Z3";
export const PERIOD = "2026-04";

/** The month the invoice date falls in, which is how the server derives it. */
function periodOf(date) {
  return date.slice(0, 7);
}

function money(value) {
  return Number(value).toFixed(2);
}

function heads({ igst = 0, cgst = 0, sgst = 0, cess = 0 } = {}) {
  return {
    igst: money(igst),
    cgst: money(cgst),
    sgst: money(sgst),
    cess: money(cess),
    total: money(igst + cgst + sgst + cess),
  };
}

/**
 * The two documents a flow uploads, as the parser would have returned them.
 *
 * Inter-state in, intra-state out: the purchase carries IGST alone and the
 * sale splits CGST+SGST, which is what makes the set-off on the ITC screen
 * have something to do — 81,000 of IGST credit against 36,000 of CGST+SGST
 * liability leaves nothing payable in cash.
 */
export const PURCHASE = {
  invoice_number: "INV-2026-0042",
  invoice_type: "purchase",
  invoice_date: "2026-04-15",
  counterparty_name: "Northwind Supplies Pvt Ltd",
  counterparty_gstin: SUPPLIER_GSTIN,
  taxable_value: "450000.00",
  cgst: "0.00",
  sgst: "0.00",
  igst: "81000.00",
  cess: "0.00",
  total_value: "531000.00",
  invoice_value: "531000.00",
  status: "parsed",
};

export const SALE = {
  invoice_number: "UT-2026-0101",
  invoice_type: "sales",
  invoice_date: "2026-04-22",
  counterparty_name: "Deccan Hardware",
  counterparty_gstin: CUSTOMER_GSTIN,
  taxable_value: "200000.00",
  cgst: "18000.00",
  sgst: "18000.00",
  igst: "0.00",
  cess: "0.00",
  total_value: "236000.00",
  invoice_value: "236000.00",
  status: "parsed",
};

/** A `File` the upload page will accept — the extension is what it checks. */
export function invoiceFile(name = "northwind-0042.pdf") {
  return new File(["%PDF-1.4 stub"], name, { type: "application/pdf" });
}

export function gstr2bFile(name = "gstr2b-2026-04.json") {
  return new File(["{}"], name, { type: "application/json" });
}

class Refusal extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

/** The role refusal, worded as `require_writer` words it. */
function refuseViewer() {
  throw new Refusal(
    403,
    "Your role on this business is viewer, which cannot make changes. " +
      "Ask an owner or an accountant.",
  );
}

/**
 * Install the fake API on `global.fetch` and return a handle on its state.
 *
 * `role` is the role `/auth/me` reports and the one every write is checked
 * against, so a test asking for a viewer gets a viewer everywhere rather than
 * a client that merely hides the buttons.
 */
export function installBackend({ role = "owner", invoices = [], imported = false } = {}) {
  const state = {
    role,
    invoices: [],
    nextInvoiceId: 1,
    // period -> the imported statement
    statements: {},
    runs: [],
    nextRunId: 1,
    // `${returnType}:${period}` -> what was recorded
    filings: {},
    alerts: [
      {
        id: 1,
        alert_type: "filing_deadline",
        severity: "warning",
        status: "pending",
        title: `GSTR-3B for ${PERIOD} is due soon`,
        message: `GSTR-3B for ${PERIOD} is due on 2026-05-20.`,
        period: PERIOD,
        due_date: "2026-05-20",
        channel: null,
        sent_at: null,
        context: { return_type: "gstr3b" },
        created_at: "2026-05-14T04:00:00Z",
        updated_at: "2026-05-14T04:00:00Z",
      },
    ],
    /** Every request this fake served, as `"METHOD /path"`. */
    calls: [],
  };

  for (const seed of invoices) addInvoice(state, seed);
  if (imported) importStatement(state, PERIOD);

  const fetchMock = vi.fn(async (input, init = {}) => {
    const href = String(input);
    const [path, search = ""] = href.replace("/api/v1", "").split("?");
    const params = new URLSearchParams(search);
    const method = (init.method ?? "GET").toUpperCase();
    state.calls.push(`${method} ${path}`);

    try {
      const answer = route(state, method, path, params, init);
      if (answer === undefined) throw new Refusal(404, "Not Found");
      return jsonResponse(answer.status ?? 200, answer.body, answer.headers);
    } catch (err) {
      if (err instanceof Refusal) {
        return jsonResponse(err.status, {
          detail: err.detail,
          error: { code: "refused", status: err.status, message: err.detail },
          correlation_id: "flowtest0000000",
        });
      }
      throw err;
    }
  });

  global.fetch = fetchMock;
  return { state, fetch: fetchMock };
}

function jsonResponse(status, body, headers = {}) {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    // Empty, as it is over HTTP/2 — which is what production serves, and what
    // `statusMessage` in the client is written against.
    statusText: "",
    text: async () => text,
    blob: async () => new Blob([text], { type: "application/json" }),
    headers: { get: (name) => headers[name.toLowerCase()] ?? null },
  };
}

function addInvoice(state, seed) {
  const row = { id: state.nextInvoiceId, ...seed };
  state.nextInvoiceId += 1;
  state.invoices.push(row);
  return row;
}

function importStatement(state, period) {
  // The statement declares the purchases in the register at import time, which
  // is what makes a run against it match. A flow testing the supplier who did
  // not file imports first and uploads afterwards.
  const purchases = state.invoices.filter(
    (row) => row.invoice_type === "purchase" && periodOf(row.invoice_date) === period,
  );
  const statement = {
    id: Object.keys(state.statements).length + 1,
    period,
    return_type: "gstr2b",
    status: "imported",
    invoice_count: purchases.length,
    total_taxable_value: money(sum(purchases, "taxable_value")),
    total_cgst: money(sum(purchases, "cgst")),
    total_sgst: money(sum(purchases, "sgst")),
    total_igst: money(sum(purchases, "igst")),
    total_cess: "0.00",
    created_at: "2026-05-14T10:00:00Z",
    other_periods: [],
    replaced_previous: false,
    message: `Imported ${purchases.length} invoices for ${period}`,
    declared: purchases.map((row) => row.invoice_number),
  };
  state.statements[period] = statement;
  return statement;
}

function sum(rows, field) {
  return rows.reduce((total, row) => total + Number(row[field] ?? 0), 0);
}

function inPeriod(state, period, type) {
  return state.invoices.filter(
    (row) =>
      periodOf(row.invoice_date) === period && (type ? row.invoice_type === type : true),
  );
}

/** A run of the matcher: books against whatever the statement declared. */
function reconcile(state, period) {
  const statement = state.statements[period];
  if (!statement) {
    throw new Refusal(422, `No GSTR-2B has been imported for ${period}.`);
  }
  const books = inPeriod(state, period, "purchase");
  const declared = new Set(statement.declared);
  const matched = books.filter((row) => declared.has(row.invoice_number));
  const missing = books.filter((row) => !declared.has(row.invoice_number));

  const run = {
    id: state.nextRunId,
    period,
    status: "completed",
    total_invoices: books.length,
    matched_count: matched.length,
    mismatched_count: 0,
    missing_in_2b_count: missing.length,
    missing_in_books_count: 0,
    duplicate_count: 0,
    itc_eligible: money(sum(matched, "igst") + sum(matched, "cgst") + sum(matched, "sgst")),
    itc_at_risk: money(sum(missing, "igst") + sum(missing, "cgst") + sum(missing, "sgst")),
    itc_claimed: money(sum(books, "igst") + sum(books, "cgst") + sum(books, "sgst")),
    started_at: "2026-05-14T10:01:00Z",
    completed_at: "2026-05-14T10:01:02Z",
    error: null,
    created_at: "2026-05-14T10:01:00Z",
    report: {
      tolerance: "1.00",
      findings: [
        ...matched.map((row) => finding(row, "matched")),
        ...missing.map((row) => finding(row, "missing_in_2b")),
      ],
    },
  };
  state.nextRunId += 1;
  state.runs.unshift(run);
  return run;
}

function finding(row, category) {
  const tax = money(Number(row.igst) + Number(row.cgst) + Number(row.sgst));
  return {
    category,
    invoice_id: row.id,
    invoice_number: row.invoice_number,
    supplier_gstin: row.counterparty_gstin,
    supplier_name: row.counterparty_name,
    invoice_date: row.invoice_date,
    matched_on: category === "matched" ? "exact" : null,
    differences: [],
    books: { taxable_value: row.taxable_value, total_tax: tax },
    ...(category === "matched"
      ? { gstr2b: { taxable_value: row.taxable_value, total_tax: tax } }
      : {}),
  };
}

/** The ITC position, which follows the last run for the period. */
function itcSummary(state, period) {
  const run = state.runs.find((item) => item.period === period);
  const purchases = inPeriod(state, period, "purchase");
  const sales = inPeriod(state, period, "sales");
  const eligible = run
    ? run.report.findings.filter((f) => f.category === "matched")
    : purchases.map((row) => finding(row, "matched"));
  const available = heads({
    igst: eligible.reduce((t, f) => t + Number(f.books.total_tax), 0),
  });
  const output = heads({ cgst: sum(sales, "cgst"), sgst: sum(sales, "sgst") });

  return {
    period,
    available,
    output_tax: output,
    rule_37: {
      overdue: [],
      approaching: [],
      reversal: heads(),
      approaching_amount: heads(),
      days: 180,
      warning_days: 30,
    },
    proportionate: {
      exempt_turnover: "0.00",
      total_turnover: money(sum(sales, "taxable_value")),
      exempt_ratio: "0.000000",
      common_credit: available,
      rule_42_reversal: heads(),
      capital_credit: heads(),
      capital_credit_this_month: heads(),
      rule_43_reversal: heads(),
      total_reversal: heads(),
      capital_months: 60,
    },
    rule_37_reversal: heads(),
    rule_37_reavailment: heads(),
    total_reversal: heads(),
    net_available: available,
    set_off: {
      steps: [
        { credit_head: "igst", liability_head: "cgst", amount: output.cgst },
        { credit_head: "igst", liability_head: "sgst", amount: output.sgst },
      ],
      cash_payable: heads(),
      credit_carried_forward: heads({
        igst: Number(available.igst) - Number(output.total),
      }),
      credit_used: heads({ igst: Number(output.total) }),
      total_cash: "0.00",
    },
    reverse_charge: {
      taxable_value: "0.00",
      tax: heads(),
      credit: heads(),
      invoice_count: 0,
      cash_payable: "0.00",
    },
    cash_payable: "0.00",
    itc_at_risk: run ? run.itc_at_risk : "0.00",
    reconciled: Boolean(run),
    invoice_count: purchases.length,
    unclaimed_count: 0,
  };
}

function validationFor(state, period, invoiceType) {
  const rows = inPeriod(state, period, invoiceType);
  const issues = rows
    .filter((row) => !row.counterparty_gstin)
    .map((row) => ({
      severity: "error",
      code: "missing_counterparty_gstin",
      message: `${row.invoice_number} has no counterparty GSTIN.`,
      invoice_id: row.id,
      invoice_number: row.invoice_number,
      field: "counterparty_gstin",
    }));
  return {
    period,
    ok: issues.every((issue) => issue.severity !== "error"),
    invoice_count: rows.length,
    error_count: issues.filter((issue) => issue.severity === "error").length,
    warning_count: 0,
    issues,
  };
}

function returnDocument(state, period, returnType) {
  const sales = inPeriod(state, period, "sales");
  const fp = `${period.slice(5)}${period.slice(0, 4)}`;
  const validation = validationFor(state, period, "sales");

  if (returnType === "gstr1") {
    return {
      period,
      return_type: "gstr1",
      document: {
        gstin: BUSINESS_GSTIN,
        fp,
        version: "GST3.0.4",
        hash: "hash",
        b2b: sales.map((row) => ({
          ctin: row.counterparty_gstin,
          inv: [{ inum: row.invoice_number, idt: row.invoice_date, val: row.total_value }],
        })),
      },
      validation,
    };
  }

  const itc = itcSummary(state, period);
  return {
    period,
    return_type: "gstr3b",
    document: {
      gstin: BUSINESS_GSTIN,
      ret_period: fp,
      gstbot_set_off: {
        steps: itc.set_off.steps,
        cash_payable: itc.set_off.cash_payable,
        credit_carried_forward: itc.set_off.credit_carried_forward,
        credit_used: itc.set_off.credit_used,
        total_cash: itc.set_off.total_cash,
      },
      gstbot_reverse_charge: itc.reverse_charge,
    },
    validation,
  };
}

/** Six recent periods with each return's standing, as the status table reads it. */
function filingStatus(state) {
  const items = [];
  for (const returnType of ["gstr1", "gstr3b"]) {
    const recorded = state.filings[`${returnType}:${PERIOD}`];
    items.push({
      period: PERIOD,
      return_type: returnType,
      due_date: returnType === "gstr1" ? "2026-05-11" : "2026-05-20",
      days_until_due: 6,
      filed: Boolean(recorded),
      filed_late: false,
      filed_on: recorded?.filed_on ?? null,
      arn: recorded?.arn ?? null,
    });
  }
  return { as_of: "2026-05-14", items };
}

function route(state, method, path, params, init) {
  const period = params.get("period") || PERIOD;

  // ---- Auth -------------------------------------------------------------
  if (path === "/auth/login" && method === "POST") {
    return { body: { access_token: "flow-token", token_type: "bearer" } };
  }
  if (path === "/auth/me") {
    return {
      body: {
        id: 1,
        email: "owner@umang.example",
        full_name: "Umang Shah",
        role: state.role,
        active_role: state.role,
        business_id: 1,
        is_active: true,
        business: {
          id: 1,
          gstin: BUSINESS_GSTIN,
          legal_name: "Umang Traders Private Limited",
          trade_name: "Umang Traders",
          state_code: "27",
          plan: "free",
        },
      },
    };
  }
  if (path === "/businesses/mine") {
    return {
      body: {
        items: [
          {
            id: 1,
            gstin: BUSINESS_GSTIN,
            legal_name: "Umang Traders Private Limited",
            trade_name: "Umang Traders",
            plan: "free",
            role: state.role,
            is_home: true,
          },
        ],
      },
    };
  }

  // ---- Invoices ---------------------------------------------------------
  if (path === "/invoices/bulk" && method === "POST") {
    if (state.role === "viewer") refuseViewer();
    const form = init.body;
    const files = form.getAll("files");
    const invoiceType = form.get("invoice_type");
    const items = files.map((file) => {
      const seed = invoiceType === "sales" ? SALE : PURCHASE;
      const row = addInvoice(state, { ...seed, invoice_type: invoiceType, warnings: [] });
      return { filename: file.name, accepted: true, queued: false, invoice: row };
    });
    return {
      status: 201,
      body: { total: items.length, accepted: items.length, rejected: 0, items },
    };
  }
  if (path === "/invoices") {
    const type = params.get("invoice_type");
    const wanted = params.get("period");
    const rows = state.invoices.filter(
      (row) =>
        (!type || row.invoice_type === type) &&
        (!wanted || periodOf(row.invoice_date) === wanted),
    );
    return { body: { items: rows, total: rows.length, limit: 25, offset: 0 } };
  }
  const invoiceMatch = path.match(/^\/invoices\/(\d+)(\/reparse)?$/);
  if (invoiceMatch) {
    const row = state.invoices.find((item) => item.id === Number(invoiceMatch[1]));
    if (!row) throw new Refusal(404, "Invoice not found");
    if (method === "GET") return { body: row };
    if (state.role === "viewer") refuseViewer();
    if (method === "PATCH") {
      Object.assign(row, JSON.parse(init.body));
      return { body: row };
    }
    if (method === "DELETE") {
      state.invoices = state.invoices.filter((item) => item.id !== row.id);
      return { status: 204, body: "" };
    }
    return { body: row };
  }

  // ---- Dashboard --------------------------------------------------------
  if (path === "/dashboard") {
    const sales = inPeriod(state, period, "sales");
    const purchases = inPeriod(state, period, "purchase");
    const run = state.runs.find((item) => item.period === period);
    const bucket = (rows) => ({
      count: rows.length,
      taxable_value: money(sum(rows, "taxable_value")),
      cgst: money(sum(rows, "cgst")),
      sgst: money(sum(rows, "sgst")),
      igst: money(sum(rows, "igst")),
      cess: "0.00",
      total_tax: money(sum(rows, "cgst") + sum(rows, "sgst") + sum(rows, "igst")),
      total_value: money(sum(rows, "total_value")),
    });
    return {
      body: {
        business_gstin: BUSINESS_GSTIN,
        business_name: "Umang Traders",
        period,
        counts: {
          total: sales.length + purchases.length,
          sales: sales.length,
          purchase: purchases.length,
          by_status: { parsed: sales.length + purchases.length },
          needs_review: 0,
        },
        sales: bucket(sales),
        purchase: bucket(purchases),
        credit: bucket(purchases),
        net_liability: heads(),
        output_tax: money(sum(sales, "cgst") + sum(sales, "sgst") + sum(sales, "igst")),
        input_tax_credit: money(
          sum(purchases, "cgst") + sum(purchases, "sgst") + sum(purchases, "igst"),
        ),
        itc_at_risk: run ? run.itc_at_risk : "0.00",
        plan_usage: {
          plan: "free",
          invoices_this_month: sales.length + purchases.length,
          monthly_limit: 50,
          remaining: 50 - sales.length - purchases.length,
        },
        recent_periods: [],
        open_alerts: state.alerts.filter((a) => a.status !== "dismissed").length,
        next_due_date: "2026-05-20",
        last_reconciliation: run
          ? { id: run.id, period: run.period, matched: run.matched_count }
          : null,
      },
    };
  }

  // ---- Reconciliation ---------------------------------------------------
  if (path === "/reconciliation/gstr2b/periods") {
    return { body: { items: Object.keys(state.statements) } };
  }
  if (path === "/reconciliation/gstr2b/import" && method === "POST") {
    if (state.role === "viewer") refuseViewer();
    return { status: 201, body: importStatement(state, init.body.get("period") || PERIOD) };
  }
  const statementMatch = path.match(/^\/reconciliation\/gstr2b\/(\d{4}-\d{2})$/);
  if (statementMatch) {
    const statement = state.statements[statementMatch[1]];
    if (!statement) throw new Refusal(404, "No GSTR-2B imported for that period.");
    return { body: statement };
  }
  if (path === "/reconciliation/run" && method === "POST") {
    if (state.role === "viewer") refuseViewer();
    return { status: 201, body: reconcile(state, JSON.parse(init.body).period) };
  }
  if (path === "/reconciliation/latest") {
    const run = state.runs.find((item) => item.period === period);
    if (!run) throw new Refusal(404, "No reconciliation run for that period.");
    return { body: run };
  }
  if (path === "/reconciliation") {
    const rows = state.runs.filter((item) => item.period === period);
    return { body: { items: rows, total: rows.length, limit: 10, offset: 0 } };
  }
  const runMatch = path.match(/^\/reconciliation\/(\d+)$/);
  if (runMatch) {
    const run = state.runs.find((item) => item.id === Number(runMatch[1]));
    if (!run) throw new Refusal(404, "Reconciliation run not found");
    return { body: run };
  }

  // ---- ITC --------------------------------------------------------------
  if (path === "/itc/lapsing") {
    return { body: { years: [], total_at_risk: "0.00", total_expired: "0.00", lead_days: 90 } };
  }
  if (path === "/itc") return { body: itcSummary(state, period) };

  // ---- Filing -----------------------------------------------------------
  if (path === "/filing/status") return { body: filingStatus(state) };
  if (path === "/filing/validate") {
    return { body: validationFor(state, period, params.get("invoice_type") || "sales") };
  }
  if (path === "/filing/gstr1") return { body: returnDocument(state, period, "gstr1") };
  if (path === "/filing/gstr3b") return { body: returnDocument(state, period, "gstr3b") };

  const lateFeeMatch = path.match(/^\/filing\/(gstr1|gstr3b)\/late-fee$/);
  if (lateFeeMatch) {
    return {
      body: {
        period,
        return_type: lateFeeMatch[1],
        due_date: "2026-05-20",
        as_of: "2026-05-14",
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
      },
    };
  }

  const filedMatch = path.match(/^\/filing\/(gstr1|gstr3b)\/filed$/);
  if (filedMatch && method === "POST") {
    if (state.role === "viewer") refuseViewer();
    const payload = JSON.parse(init.body);
    const record = {
      period: payload.period,
      return_type: filedMatch[1],
      filed_on: "2026-05-14",
      arn: payload.arn ?? null,
    };
    state.filings[`${filedMatch[1]}:${payload.period}`] = record;
    return { status: 201, body: record };
  }

  const exportMatch = path.match(/^\/filing\/export\/(gstr1|gstr3b)\.(json|csv)$/);
  if (exportMatch) {
    const [, returnType, extension] = exportMatch;
    const filename = `${returnType}-${BUSINESS_GSTIN}-${period}.${extension}`;
    return {
      body:
        extension === "json"
          ? returnDocument(state, period, returnType).document
          : "period,return\n",
      headers: { "content-disposition": `attachment; filename="${filename}"` },
    };
  }

  // ---- Suppliers, alerts, health ---------------------------------------
  if (path === "/suppliers") {
    const gstins = [
      ...new Set(
        state.invoices
          .filter((row) => row.invoice_type === "purchase")
          .map((row) => row.counterparty_gstin),
      ),
    ];
    return {
      body: {
        items: gstins.map((gstin, index) => ({
          id: index + 1,
          gstin,
          legal_name: "Northwind Supplies Pvt Ltd",
          trade_name: "Northwind",
          state_code: gstin.slice(0, 2),
          compliance_score: 92,
          risk_level: "low",
          total_invoices: 1,
          matched_invoices: 1,
          mismatched_invoices: 0,
          missing_invoices: 0,
          late_filings: 0,
          last_filed_period: PERIOD,
          last_seen_at: null,
          created_at: "2026-04-15T00:00:00Z",
        })),
        total: gstins.length,
        limit: 25,
        offset: 0,
      },
    };
  }
  if (path === "/suppliers/rescore" && method === "POST") {
    if (state.role === "viewer") refuseViewer();
    return { body: { rescored: 1, period } };
  }
  if (path === "/alerts") {
    const open = state.alerts.filter((a) => a.status !== "dismissed");
    return { body: { items: open, total: open.length, open_total: open.length, limit: 50, offset: 0 } };
  }
  const alertMatch = path.match(/^\/alerts\/(\d+)\/(read|dismiss)$/);
  if (alertMatch && method === "POST") {
    if (state.role === "viewer") refuseViewer();
    const alert = state.alerts.find((item) => item.id === Number(alertMatch[1]));
    if (!alert) throw new Refusal(404, "Alert not found");
    alert.status = alertMatch[2] === "read" ? "read" : "dismissed";
    return { body: alert };
  }
  if (path === "/health") {
    return {
      body: {
        status: "ok",
        app: "DoAide GST",
        version: "0.1.0",
        environment: "test",
        database: "ok",
        redis: "ok",
        ai: "configured",
        health: "ok",
        checks: {
          database: { status: "ok", latency_ms: 1.2, pool: {} },
          redis: { status: "ok", latency_ms: 0.4, required_for: ["rate limiting"] },
          ai: { status: "configured", provider: "openrouter", model: "openai/gpt-oss-20b:free" },
        },
      },
    };
  }
  if (path === "/health/jobs") {
    return {
      body: {
        health: "ok",
        celery_enabled: true,
        workers: { reachable: true, names: ["celery@box"] },
        queue: { name: "celery", reachable: true, depth: 0 },
        jobs: [],
      },
    };
  }

  return undefined;
}
