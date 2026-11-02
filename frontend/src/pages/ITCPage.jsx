import { useCallback, useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import ErrorBanner from "../components/ErrorBanner";
import { SkeletonStats } from "../components/Skeleton";
import StatCard from "../components/StatCard";
import TableScroll from "../components/TableScroll";
import { usePageTitle } from "../hooks/usePageTitle";
import { api, isAbortError } from "../lib/api";
import { linkedPeriod, currentPeriod, dateLabel, periodLabel, rupees } from "../lib/format";

/** The last 12 filing periods, newest first. */
function recentPeriodOptions(now = new Date()) {
  const options = [];
  for (let i = 0; i < 12; i += 1) {
    const date = new Date(now.getFullYear(), now.getMonth() - i, 1);
    options.push(`${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`);
  }
  return options;
}

const HEADS = [
  { key: "igst", label: "IGST" },
  { key: "cgst", label: "CGST" },
  { key: "sgst", label: "SGST" },
  { key: "cess", label: "Cess" },
];

/**
 * A four-head breakdown with a total, used for credit, tax and reversals.
 *
 * `caption` heads the first column; `label` names the scroll region, which
 * wants to say which of the two breakdowns on this page it is rather than
 * repeating a column header.
 */
function HeadsTable({ caption, label, rows }) {
  return (
    <TableScroll label={label}>
      <table className="table">
        <thead>
          <tr>
            <th scope="col">{caption}</th>
            {HEADS.map((head) => (
              <th scope="col" key={head.key} className="numeric">
                {head.label}
              </th>
            ))}
            <th scope="col" className="numeric">
              Total
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <td>
                {row.label}
                {row.help && <div className="muted small">{row.help}</div>}
              </td>
              {HEADS.map((head) => (
                <td key={head.key} className="numeric">
                  {rupees(row.heads?.[head.key])}
                </td>
              ))}
              <td className="numeric">
                <strong>{rupees(row.heads?.total)}</strong>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroll>
  );
}

export default function ITCPage() {
  usePageTitle("ITC");
  const location = useLocation();
  const [period, setPeriod] = useState(() => linkedPeriod(location.search, currentPeriod()));
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [lapsing, setLapsing] = useState(null);

  const load = useCallback(async (target, { signal } = {}) => {
    setLoading(true);
    setError("");
    try {
      setSummary(await api.itc(target, {}, { signal }));
    } catch (err) {
      if (isAbortError(err)) return;
      setError(err.message);
      setSummary(null);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  // Responses do not come back in the order they were sent, and stepping
  // through months is how this screen is read. A late answer for one period
  // landing after another's puts that month's claimable credit, reversals and
  // cash payable under the wrong month's heading.
  useEffect(() => {
    const controller = new AbortController();
    load(period, { signal: controller.signal });
    return () => controller.abort();
  }, [load, period]);

  // Fetched once, not per period, because s.16(4) is not a question about a
  // month: the deadline governs a whole financial year, and the credit closest
  // to being lost is on invoices from a year the picker cannot reach. Tying it
  // to the picker would hide the answer behind the one control guaranteed not
  // to be pointing at it.
  //
  // Its failure is swallowed like the other secondary panels' — the page's job
  // is this period's position, and a banner about the lapsing panel would sit
  // over a set-off table that loaded perfectly.
  useEffect(() => {
    const controller = new AbortController();
    api
      .lapsingCredit(undefined, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setLapsing(data);
      })
      .catch(() => {
        if (!controller.signal.aborted) setLapsing(null);
      });
    return () => controller.abort();
  }, []);

  const rule37 = summary?.rule_37;
  const proportionate = summary?.proportionate;
  const setOff = summary?.set_off;
  // The whole cash figure, not the set-off's half: credit may not settle a
  // reverse-charge liability (s.49(4) with s.2(82)), so a screen showing only
  // what the waterfall left unsettled tells a business to find less money than
  // it owes. The backend adds the two; this reads its answer.
  const reverseCharge = summary?.reverse_charge;
  const reverseChargeCash = Number(reverseCharge?.cash_payable ?? 0);
  const cashPayable = summary?.cash_payable ?? setOff?.total_cash;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Input Tax Credit</h1>
          <p className="muted">
            What you can claim this period, what has to be reversed, and what the credit
            leaves you to pay in cash.
          </p>
        </div>
        <label className="period-picker">
          <span>Period</span>
          <select value={period} onChange={(e) => setPeriod(e.target.value)}>
            {[...new Set([period, ...recentPeriodOptions()])].sort().reverse().map((option) => (
              <option key={option} value={option}>
                {periodLabel(option)}
              </option>
            ))}
          </select>
        </label>
      </div>

      <ErrorBanner message={error} onDismiss={() => setError("")} />

      {loading ? (
        <SkeletonStats count={4} label="Loading the ITC position" />
      ) : !summary ? null : (
        <>
          {!summary.reconciled && (
            <div className="banner banner-warn" role="status">
              No reconciliation has been run for {periodLabel(period)}. These figures are
              what your books claim, not what GSTR-2B supports —{" "}
              <Link to="/reconcile">reconcile the period</Link> before relying on them.
            </div>
          )}

          <section className="stat-grid">
            <StatCard
              label="Credit available"
              value={rupees(summary.available.total)}
              sub={summary.reconciled ? "Confirmed against 2B" : "Unreconciled"}
              tone={summary.reconciled ? "good" : "warn"}
            />
            <StatCard
              label="To reverse"
              value={rupees(summary.total_reversal.total)}
              sub="Rules 37, 42 and 43"
              tone={Number(summary.total_reversal.total) > 0 ? "bad" : "good"}
            />
            <StatCard
              label="Net credit"
              value={rupees(summary.net_available.total)}
              sub="After every reversal"
            />
            <StatCard
              label="Cash to pay"
              value={rupees(cashPayable)}
              sub={
                reverseChargeCash > 0
                  ? `Includes ${rupees(reverseCharge.cash_payable)} on reverse charge`
                  : `Output tax ${rupees(summary.output_tax.total)}`
              }
              tone={Number(cashPayable) > 0 ? "warn" : "good"}
            />
          </section>

          <section className="panel">
            <h2>Position by tax head</h2>
            <HeadsTable
              caption="Head"
              label="Position by tax head"
              rows={[
                {
                  label: "Credit available",
                  heads: summary.available,
                  help: `${summary.invoice_count} purchase invoices${
                    summary.unclaimed_count
                      ? `, ${summary.unclaimed_count} carrying no claimable credit`
                      : ""
                  }`,
                },
                {
                  label: "Capital goods, this month",
                  heads: proportionate.capital_credit_this_month,
                  help: `One month of ${proportionate.capital_months} (Rule 43)`,
                },
                // Only when there is some. A row of zeros on every screen for
                // a rule most months never trigger is furniture, and the two
                // rows either side of it are read on every one of them.
                ...(Number(summary.rule_37_reavailment?.total ?? 0) > 0
                  ? [
                      {
                        label: "Re-availed: suppliers paid",
                        heads: summary.rule_37_reavailment,
                        help: "Credit an earlier return reversed under Rule 37, taken back now that the supplier has been paid",
                      },
                    ]
                  : []),
                { label: "Less: reversals", heads: summary.total_reversal },
                { label: "Net credit", heads: summary.net_available },
                { label: "Output tax", heads: summary.output_tax },
              ]}
            />
          </section>

          <section className="panel">
            <h2>How the credit settles</h2>
            <p className="muted small">
              Applied in the order sections 49, 49A and 49B require: IGST credit first and
              in full, then each of CGST and SGST against its own head and IGST. CGST
              credit can never settle SGST, or the reverse.
            </p>
            {setOff.steps.length === 0 ? (
              <p className="muted">No credit could be applied to this period’s liability.</p>
            ) : (
              <ul className="result-list">
                {setOff.steps.map((step) => (
                  <li key={`${step.credit_head}-${step.liability_head}`} className="result-row">
                    <span className="result-name">
                      {step.credit_head.toUpperCase()} credit → {step.liability_head.toUpperCase()}{" "}
                      liability
                    </span>
                    <span className="numeric">{rupees(step.amount)}</span>
                  </li>
                ))}
              </ul>
            )}
            <div className="kv">
              <div>
                <span className="muted">Output tax in cash</span>
                <strong>{rupees(setOff.total_cash)}</strong>
              </div>
              {reverseChargeCash > 0 && (
                <div>
                  <span className="muted">Reverse charge, in cash</span>
                  <strong>{rupees(reverseCharge.cash_payable)}</strong>
                </div>
              )}
              <div>
                <span className="muted">Credit carried forward</span>
                <strong>{rupees(setOff.credit_carried_forward.total)}</strong>
              </div>
            </div>
            {reverseChargeCash > 0 && (
              <p className="muted small">
                Credit cannot settle a reverse-charge liability — section 49(4) lets the
                ledger pay output tax, and section 2(82) puts reverse charge outside it.
                The {rupees(reverseCharge.cash_payable)} is paid on the challan whatever
                the ledger holds, and comes back as credit in this same return.
              </p>
            )}
          </section>

          <section className="panel">
            <h2>Rule 37 — unpaid suppliers</h2>
            <p className="muted small">
              Credit reverses on an invoice still unpaid {rule37.days} days after its date.
              Paying the supplier before then keeps it.
            </p>

            {rule37.overdue.length === 0 && rule37.approaching.length === 0 ? (
              <p className="muted">Nothing outstanding past the deadline or approaching it.</p>
            ) : (
              <TableScroll label="Rule 37 reversals">
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col">Status</th>
                      <th scope="col">Invoice</th>
                      <th scope="col">Supplier</th>
                      <th scope="col">Date</th>
                      <th scope="col" className="numeric">
                        Days
                      </th>
                      <th scope="col" className="numeric">
                        Credit
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...rule37.overdue, ...rule37.approaching].map((item) => (
                      <tr key={item.invoice_id}>
                        <td>
                          <span className={item.overdue ? "chip chip-bad" : "chip chip-warn"}>
                            {item.overdue ? "Reversed" : "Due soon"}
                          </span>
                        </td>
                        <td>
                          <Link to={`/invoices/${item.invoice_id}`}>
                            {item.invoice_number || "(no number)"}
                          </Link>
                        </td>
                        <td>
                          <div>{item.supplier_name || "—"}</div>
                          <div className="muted small">{item.supplier_gstin || ""}</div>
                        </td>
                        <td>{dateLabel(item.invoice_date)}</td>
                        <td className="numeric">
                          {item.overdue
                            ? `${item.days_outstanding} outstanding`
                            : `${item.days_remaining} left`}
                        </td>
                        <td className="numeric">{rupees(item.tax.total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableScroll>
            )}
          </section>

          <section className="panel">
            <h2>Rules 42 and 43 — exempt supplies</h2>
            <p className="muted small">
              Credit on purchases that fed exempt supplies has to be given back in
              proportion to exempt turnover.
            </p>
            <div className="kv">
              <div>
                <span className="muted">Exempt turnover</span>
                <strong>{rupees(proportionate.exempt_turnover)}</strong>
              </div>
              <div>
                <span className="muted">Total turnover</span>
                <strong>{rupees(proportionate.total_turnover)}</strong>
              </div>
              <div>
                <span className="muted">Exempt share</span>
                <strong>{(Number(proportionate.exempt_ratio) * 100).toFixed(2)}%</strong>
              </div>
            </div>
            <HeadsTable
              caption="Reversal"
              label="Proportionate reversals under rules 42 and 43"
              rows={[
                {
                  label: "Rule 42 — inputs and services",
                  heads: proportionate.rule_42_reversal,
                },
                {
                  label: "Rule 43 — capital goods",
                  heads: proportionate.rule_43_reversal,
                },
                {
                  // The share that lapsed in *this* period, not the standing
                  // exposure above it. Rule 37 is paid once, in the return for
                  // the month the 180 days ran out, so the running total the
                  // overdue list adds up to is not what this month reverses —
                  // and putting it in this row left the column not summing to
                  // the total beneath it.
                  label: "Rule 37 — unpaid suppliers",
                  heads: summary.rule_37_reversal,
                },
                { label: "Total to reverse", heads: summary.total_reversal },
              ]}
            />
          </section>
        </>
      )}

      {/* Outside the period block above, and deliberately. Every panel in it
          describes the month the picker is on; this one describes a deadline
          that does not care which month that is. Leaving it inside would also
          mean a period whose summary failed to load hid the one figure on this
          screen that cannot be recovered later. */}
      {lapsing?.years?.length > 0 && (
        <section className="panel">
          <h2>Section 16(4) — credit that expires</h2>
          <p className="muted small">
            Credit on a purchase must be taken into a GSTR-3B by the 30th of November
            after its financial year ends. Unlike Rules 37, 42 and 43, this one does not
            defer the credit — past the date it is gone, and no later filing brings it
            back.
          </p>

          <TableScroll label="Credit approaching its section 16(4) deadline">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Financial year</th>
                  <th scope="col">Deadline</th>
                  <th scope="col">Standing</th>
                  <th scope="col">To file</th>
                  <th scope="col" className="numeric">
                    Invoices
                  </th>
                  <th scope="col" className="numeric">
                    Credit
                  </th>
                </tr>
              </thead>
              <tbody>
                {lapsing.years.map((year) => (
                  <tr key={year.financial_year}>
                    <td>{year.financial_year}</td>
                    <td>{dateLabel(year.deadline)}</td>
                    <td>
                      {/* An expired year is the most important row here, not
                          the least — so it is named as lost rather than shown
                          as a countdown that has gone negative. */}
                      <span className={year.expired ? "chip chip-bad" : "chip chip-warn"}>
                        {year.expired ? "Lapsed" : `${year.days_remaining}d left`}
                      </span>
                    </td>
                    <td className="small">
                      {/* Naming the amount without naming what to file makes
                          this a warning rather than a task, which is why the
                          API returns the periods at all. */}
                      {year.periods.length > 0
                        ? year.periods.map((item) => periodLabel(item)).join(", ")
                        : "—"}
                    </td>
                    <td className="numeric">{year.invoice_count}</td>
                    <td className="numeric">{rupees(year.tax.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>

          <div className="kv">
            <div>
              <span className="muted">Still claimable</span>
              <strong>{rupees(lapsing.total_at_risk)}</strong>
            </div>
            <div>
              <span className="muted">Already lapsed</span>
              <strong>{rupees(lapsing.total_expired)}</strong>
            </div>
          </div>
          <p className="muted small">
            File the GSTR-3B for the periods named above and the credit is claimed.{" "}
            <Link to="/filing">Filing preparation</Link> builds them.
          </p>
        </section>
      )}
    </div>
  );
}
