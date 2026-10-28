import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import ErrorBanner from "../components/ErrorBanner";
import Meter from "../components/Meter";
import { SkeletonTable } from "../components/Skeleton";
import TableScroll from "../components/TableScroll";
import { useAuth } from "../hooks/useAuth";
import { usePageTitle } from "../hooks/usePageTitle";
import { api, isAbortError } from "../lib/api";
import { dateLabel, periodLabel, rupees } from "../lib/format";

const RISK = {
  low: { label: "Low risk", tone: "good" },
  medium: { label: "Medium risk", tone: "warn" },
  high: { label: "High risk", tone: "bad" },
  unknown: { label: "Unrated", tone: "neutral" },
};

const COMPONENT_LABELS = {
  match_rate: "Match rate",
  timeliness: "Filing timeliness",
  consistency: "Consistency",
  recency: "Recency",
};

/** The Details button for a row, addressable after the list has re-rendered. */
const detailsButtonId = (id) => `supplier-details-${id}`;

function RiskChip({ level }) {
  const meta = RISK[level] ?? RISK.unknown;
  return <span className={`chip chip-${meta.tone}`}>{meta.label}</span>;
}

/**
 * A 0-100 bar. Unscored components render as a dash, never as an empty bar.
 *
 * Delegates to `Meter` rather than laying out its own pair of divs. The two
 * had already drifted: this one announced itself as `role="img"`, so the four
 * component bars in the breakdown were a picture captioned "58 out of 100"
 * while the identical-looking bar on the dashboard was a progressbar carrying
 * its value, its range and its own label. Same widget, two readings, and only
 * one of them had tests.
 */
function ScoreMeter({ value, label }) {
  if (value === null || value === undefined) {
    return <span className="muted">No evidence yet</span>;
  }
  return <Meter value={Math.round(value)} max={100} label={label} />;
}

function SupplierDetail({ supplier, onClose }) {
  const detail = supplier.score_detail;
  const panelRef = useRef(null);

  // The panel renders above the table it was opened from, so tabbing on from
  // the Details button moves *away* from what the click just produced — a
  // keyboard user never reaches it, and a screen reader is told nothing
  // happened at all. Moving focus into the panel is what makes the button
  // report its own result.
  //
  // Keyed on the supplier, so clicking Details on a second row while the panel
  // is open moves focus again rather than leaving it on the previous heading.
  useEffect(() => {
    panelRef.current?.focus();
  }, [supplier.id]);

  // Escape closes it, like the nav drawer and the business switcher. Without
  // this the only way out is to find the Close button, which is the one thing
  // a keyboard user who has just been moved here cannot do by muscle memory.
  useEffect(() => {
    function onKeyDown(event) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <section
      className="panel"
      ref={panelRef}
      // -1, not 0: a programmatic focus target, not a new stop on the tab
      // order that everyone has to pass through on the way to the table.
      tabIndex={-1}
      aria-labelledby="supplier-detail-heading"
    >
      <div className="page-head">
        <div>
          <h2 id="supplier-detail-heading">
            {supplier.legal_name || supplier.trade_name || supplier.gstin}
          </h2>
          <p className="muted small">{supplier.gstin}</p>
        </div>
        <button type="button" className="btn btn-ghost" onClick={onClose}>
          Close
        </button>
      </div>

      <div className="kv">
        <div>
          <span className="muted">Score</span>
          <strong>{detail.score ?? "—"}</strong>
        </div>
        <div>
          <span className="muted">Confidence</span>
          <strong>{(detail.confidence * 100).toFixed(0)}%</strong>
        </div>
        <div>
          <span className="muted">Evidence</span>
          <strong>
            {detail.invoices_observed} invoices, {detail.periods_observed} periods
          </strong>
        </div>
        <div>
          <span className="muted">Suggested provision</span>
          <strong>{detail.recommended_provision_pct}%</strong>
        </div>
      </div>

      <div className={detail.score !== null && detail.score < 60 ? "banner banner-warn" : "banner banner-neutral"} role="status">
        {detail.recommendation}
      </div>

      <h3>How the score is made up</h3>
      <TableScroll label="How the score is made up">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Component</th>
              <th scope="col">Weight</th>
              <th scope="col">Score</th>
              <th scope="col">What it measures</th>
            </tr>
          </thead>
          <tbody>
            {detail.components.map((component) => (
              <tr key={component.name}>
                <td>{COMPONENT_LABELS[component.name] ?? component.name}</td>
                <td className="numeric">{component.weight}%</td>
                <td>
                  {/* Named per row. Four bars all called "Score" is what a
                      screen reader reads out when it lists the controls on
                      this panel, and none of them says which component. */}
                  <ScoreMeter
                    value={component.score}
                    label={`${COMPONENT_LABELS[component.name] ?? component.name} score`}
                  />
                </td>
                <td className="muted small">{component.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>

      <h3>Exposure right now</h3>
      <div className="kv">
        <div>
          <span className="muted">Invoices</span>
          <strong>{supplier.exposure.invoice_count}</strong>
        </div>
        <div>
          <span className="muted">Credit at risk</span>
          {/* Through the formatter like every other figure on the product.
              The API sends this as a decimal string, so a bare ₹ in front of
              it rendered "₹180000.00" — no lakh grouping, on the one screen
              whose job is saying how much credit one supplier is putting at
              risk. It also rendered a lone "₹" when the field was absent,
              where `rupees` gives ₹0.00. */}
          <strong>{rupees(supplier.exposure.tax_at_risk)}</strong>
        </div>
        <div>
          <span className="muted">Unpaid</span>
          <strong>{supplier.exposure.unpaid_count}</strong>
        </div>
      </div>

      {detail.observations.length > 0 && (
        <>
          <h3>Filing history</h3>
          <TableScroll label="Filing history">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Period</th>
                  <th scope="col" className="numeric">Matched</th>
                  <th scope="col" className="numeric">Mismatched</th>
                  <th scope="col" className="numeric">Never filed</th>
                  <th scope="col">Filed</th>
                </tr>
              </thead>
              <tbody>
                {[...detail.observations].reverse().map((observation) => (
                  <tr key={observation.period}>
                    <td>{periodLabel(observation.period)}</td>
                    <td className="numeric">{observation.matched}</td>
                    <td className="numeric">{observation.mismatched}</td>
                    <td className="numeric">{observation.missing}</td>
                    <td>
                      {observation.filing_delay_days === null ||
                      observation.filing_delay_days === undefined
                        ? "—"
                        : observation.filing_delay_days > 0
                          ? `${observation.filing_delay_days} days late`
                          : "On time"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        </>
      )}
    </section>
  );
}

export default function SuppliersPage() {
  usePageTitle("Suppliers");
  const { canWrite } = useAuth();
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [risk, setRisk] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  // Whether the register on screen failed to load, as opposed to loading and
  // coming back empty. `error` cannot answer that: opening a breakdown or
  // rescoring fills the same banner while the list behind it is perfectly
  // good, so reading the banner would blank a list with nothing wrong with it.
  const [loadFailed, setLoadFailed] = useState(false);
  // Bumped to refetch under the filters already selected. A rescore changes no
  // state the load effect depends on, so without this there is nothing for it
  // to react to.
  const [reloadToken, setReloadToken] = useState(0);
  // Which breakdown the panel is waiting for. The panel is one slot and the
  // Details buttons stay live while it loads, so an answer has to prove it is
  // still the one that was asked for.
  const detailRequest = useRef(0);
  // The supplier whose Details button opened the panel, so closing it can put
  // focus back on that row rather than dropping it to the top of the document.
  const openedFrom = useRef(null);

  const load = useCallback(async (params, { signal } = {}) => {
    setLoading(true);
    setError("");
    try {
      const data = await api.listSuppliers(params, { signal });
      setItems(data.items);
      setTotal(data.total);
      setLoadFailed(false);
    } catch (err) {
      // A superseded request has already been replaced by a newer one, which
      // owns the list, the banner and the spinner from here on. Returning
      // before `finally` would skip the reset, so the check is repeated there.
      if (isAbortError(err)) return;
      setError(err.message);
      // The rows on screen were fetched under the previous search term and
      // risk chip, and no answer is coming to replace them. Left up, they are
      // asserted to match a term they were never tested against — and the
      // heading above them says how many suppliers matched it. That is the
      // out-of-order fault the abort guard exists to stop, reached by the
      // other road.
      setItems([]);
      setTotal(0);
      setLoadFailed(true);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  // Every keystroke in the search box is a new request, and responses do not
  // come back in the order they were sent. Left unguarded, the answer for
  // "ACM" landing after the answer for "ACME" left the table showing rows the
  // search box no longer described — and, because each request cleared the
  // banner and the spinner on its own, an error from a superseded request
  // could sit over results that had since succeeded.
  //
  // Aborting the previous request on the way out of the effect fixes both: the
  // superseded response never arrives, so it cannot be applied out of order,
  // and the connection is released rather than spending a slot in the read
  // limit that a fast typist would otherwise exhaust mid-word.
  useEffect(() => {
    const controller = new AbortController();
    load({ risk_level: risk, search }, { signal: controller.signal });
    return () => controller.abort();
  }, [load, risk, search, reloadToken]);

  /**
   * Stop whatever the panel is waiting for from arriving in it, and put focus
   * back where it came from.
   *
   * Closing moved focus nowhere, which meant it was sitting on a Close button
   * about to be unmounted: the browser drops it to `<body>`, and the next Tab
   * starts again from the top of the document. Someone who opened one row's
   * breakdown to compare it with the next had to tab past the whole header,
   * the filters and the rows above to get back to where they were.
   *
   * The button is found by id rather than held as a node, because the list
   * behind the panel refetches — a filter typed, a rescore finished — and the
   * node captured when the panel opened is by then detached and unfocusable.
   * A row that has since filtered out of the list has no button to go back to;
   * `?.` is that case, and it leaves focus alone rather than moving it
   * somewhere arbitrary.
   *
   * `useCallback` because the panel's Escape handler depends on it, and a new
   * identity every render would rebind that listener on every keystroke typed
   * into the search box.
   */
  const closeDetail = useCallback(() => {
    detailRequest.current += 1;
    setSelected(null);
    const id = openedFrom.current;
    openedFrom.current = null;
    if (id !== null) document.getElementById(detailsButtonId(id))?.focus();
  }, []);

  async function handleSelect(id) {
    // Which row to hand focus back to on close. Recorded before the request
    // rather than on arrival, so a click on a second row while the first is
    // still loading returns to the row actually clicked last.
    openedFrom.current = id;
    // Answers do not come back in the order they were sent, and the panel is
    // captioned by the supplier in it rather than by the row that was clicked
    // — so a slow first answer landing after a second one did not look stale.
    // It read as the breakdown, the provision and the exposure of a supplier
    // the user had already clicked past.
    const ticket = (detailRequest.current += 1);
    setError("");
    try {
      const supplier = await api.getSupplier(id);
      if (detailRequest.current !== ticket) return;
      setSelected(supplier);
    } catch (err) {
      // A superseded request's failure belongs to a panel that is no longer
      // open, so its banner would sit over a breakdown that loaded fine.
      if (detailRequest.current !== ticket) return;
      setError(err.message);
    }
  }

  async function handleRescore() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api.rescoreSuppliers();
      setNotice(`Rescored ${result.rescored} supplier(s)`);
      // Asked for rather than called directly, so the refresh describes the
      // chip and the search box as they are *now*. Rescoring walks every
      // supplier's whole history, and reloading under the filters captured
      // when the button was clicked put the unfiltered register back on
      // screen with a risk chip still selected — a load started by hand
      // carries no signal, so the effect could not cancel it either.
      setReloadToken((token) => token + 1);
      closeDetail();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Suppliers</h1>
          <p className="muted">
            How reliably each supplier files, built from your own reconciliations — and
            how much of their credit is worth providing against.
          </p>
        </div>
        {/* The only write here. The scores themselves, and the per-supplier
            detail below, are a read a viewer keeps in full — no notice, because
            a list that is still complete does not read as broken for having one
            fewer button. */}
        {canWrite && (
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy}
            onClick={handleRescore}
          >
            {busy ? "Working…" : "Rescore all"}
          </button>
        )}
      </div>

      <ErrorBanner message={error} onDismiss={() => setError("")} />
      {notice && (
        <div className="banner banner-good" role="status">
          {notice}
        </div>
      )}

      <div className="filters">
        <label className="filter-search">
          <span className="visually-hidden">Search suppliers</span>
          <input
            type="search"
            placeholder="Search by name or GSTIN"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <div className="filter-row">
          {[
            ["", "All"],
            ["high", "High risk"],
            ["medium", "Medium"],
            ["low", "Low"],
            ["unknown", "Unrated"],
          ].map(([value, label]) => (
            <button
              key={value || "all"}
              type="button"
              className={risk === value ? "chip chip-neutral is-active" : "chip chip-neutral"}
              onClick={() => setRisk(value)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {selected && <SupplierDetail supplier={selected} onClose={closeDetail} />}

      <section className="panel">
        {/* Counted only when the count was fetched. "0 suppliers" over a load
            that failed is the same false finding as the empty state below it,
            and the more emphatic of the two for being a heading. */}
        <h2>
          {loadFailed ? "Suppliers" : `${total} supplier${total === 1 ? "" : "s"}`}
        </h2>
        {loading ? (
          <SkeletonTable rows={6} columns={5} label="Loading suppliers" />
        ) : loadFailed ? (
          // Nothing, rather than either empty state below. Both are findings
          // about the register — that no supplier matches these filters, or
          // that there are none at all — and a load that failed establishes
          // neither. Saying so would answer the search on the strength of
          // never having run it, which is the same fault the sentence below
          // was split in two to avoid.
          null
        ) : items.length === 0 && (risk || search) ? (
          // Not "no suppliers yet". That sentence also explains why the list is
          // empty — none parsed, none reconciled — and both halves are false
          // when the reason is a risk chip or a search term. On a book with a
          // hundred suppliers it reads as the scoring having been lost.
          <div className="empty">
            <p>No suppliers match these filters.</p>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                setRisk("");
                setSearch("");
              }}
            >
              Clear filters
            </button>
          </div>
        ) : items.length === 0 ? (
          <div className="empty">
            <p>
              No suppliers yet. They are created as purchase invoices are parsed, and scored
              once a period has been reconciled.
            </p>
            {canWrite && (
              <Link to="/upload" className="btn btn-primary">Upload invoices</Link>
            )}
          </div>
        ) : (
          <TableScroll label="Suppliers">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Risk</th>
                  <th scope="col">Supplier</th>
                  <th scope="col">Score</th>
                  <th scope="col" className="numeric">Matched</th>
                  <th scope="col" className="numeric">Never filed</th>
                  <th scope="col">Last filed</th>
                  <th scope="col" />
                </tr>
              </thead>
              <tbody>
                {items.map((supplier) => (
                  <tr key={supplier.id}>
                    <td>
                      <RiskChip level={supplier.risk_level} />
                    </td>
                    <td>
                      <div>{supplier.legal_name || supplier.trade_name || "—"}</div>
                      <div className="muted small">{supplier.gstin}</div>
                    </td>
                    <td>
                      <ScoreMeter
                        value={supplier.compliance_score}
                        label={`Compliance score for ${
                          supplier.legal_name || supplier.trade_name || supplier.gstin
                        }`}
                      />
                    </td>
                    <td className="numeric">{supplier.matched_invoices}</td>
                    <td className="numeric">{supplier.missing_invoices}</td>
                    <td>
                      {supplier.last_filed_period
                        ? periodLabel(supplier.last_filed_period)
                        : supplier.last_seen_at
                          ? dateLabel(supplier.last_seen_at)
                          : "—"}
                    </td>
                    <td>
                      <button
                        type="button"
                        id={detailsButtonId(supplier.id)}
                        className="btn btn-ghost"
                        onClick={() => handleSelect(supplier.id)}
                      >
                        Details
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        )}
      </section>

      <nav className="next-steps" aria-label="Next steps">
        <Link to="/reconcile" className="btn btn-ghost">Reconcile invoices</Link>
        <Link to="/invoices" className="btn btn-ghost">View invoices</Link>
      </nav>
    </div>
  );
}
