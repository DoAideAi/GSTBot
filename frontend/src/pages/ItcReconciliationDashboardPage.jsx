import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import PrintButton from "../components/PrintButton";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import StatCard from "../components/StatCard";
import TableScroll from "../components/TableScroll";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { formatINR } from "../lib/gstCalc";
import { buildItcDashboard, emptyItcMonths } from "../lib/itcDashboard";
import { todayInIndia } from "../lib/returnDueDates";

const PATH = "/itc-reconciliation-dashboard";
const DRAFT_KEY = "gst.itc-dashboard.draft";
const FY_OPTIONS = ["2025-26", "2024-25", "2026-27"];

const COLUMNS = [
  { key: "books", label: "ITC as per books", color: "var(--ink-soft)" },
  { key: "gstr2b", label: "ITC in GSTR-2B", color: "var(--brand)" },
  { key: "claimed", label: "ITC claimed in 3B", color: "var(--good)" },
];

const STATUS = {
  matched: { label: "Matched", color: "var(--good)" },
  pending: { label: "Action needed", color: "var(--warn)" },
  excess: { label: "Excess claim", color: "var(--bad)" },
  empty: { label: "—", color: "var(--ink-faint)" },
};

const EMPTY_SUPPLIER = { name: "", books: "", gstr2b: "" };

function sampleData() {
  const months = emptyItcMonths().map((m, i) => {
    const books = 240000 + i * 15000;
    return { ...m, books: String(books), gstr2b: String(books), claimed: String(books) };
  });
  const julyIn2b = String(Number(months[3].books) - 42000);
  months[3] = { ...months[3], gstr2b: julyIn2b, claimed: julyIn2b }; // supplier didn't file; claimed only what 2B shows
  months[6] = { ...months[6], claimed: String(Number(months[6].books) + 18000) }; // claimed beyond 2B
  months[10] = { ...months[10], claimed: String(Number(months[10].books) - 25000) }; // left unclaimed
  const suppliers = [
    { name: "Shree Packaging", books: "142000", gstr2b: "100000" },
    { name: "Metro Freight", books: "36000", gstr2b: "36000" },
    { name: "Kaveri Chemicals", books: "58000", gstr2b: "40000" },
  ];
  return { months, suppliers };
}

function loadDraft() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(DRAFT_KEY) || "null");
    return Array.isArray(parsed?.months) && parsed.months.length === 12 ? parsed : null;
  } catch {
    return null;
  }
}

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "ITC Reconciliation Dashboard",
  url: `https://gst.doaide.com${PATH}`,
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const FAQ_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    { "@type": "Question", name: "What is ITC reconciliation in GST?", acceptedAnswer: { "@type": "Answer", text: "Matching the credit in your purchase books against what suppliers reported (GSTR-2B) and what you claimed in GSTR-3B. Under Rule 36(4), credit can only be claimed if it appears in GSTR-2B." } },
    { "@type": "Question", name: "What happens if I claim more ITC than GSTR-2B shows?", acceptedAnswer: { "@type": "Answer", text: "The excess is liable to be reversed, and if it was used to pay tax it carries 18% interest under Section 50(3). Large gaps trigger DRC-01C intimations and ASMT-10 scrutiny notices." } },
    { "@type": "Question", name: "What is the last date to claim ITC for FY 2025-26?", acceptedAnswer: { "@type": "Answer", text: "30 November 2026, or the date you file the annual return if earlier (Section 16(4)). Credit not claimed by then lapses permanently." } },
    { "@type": "Question", name: "My supplier has not filed GSTR-1. Can I still claim ITC?", acceptedAnswer: { "@type": "Answer", text: "Not until the invoice reflects in your GSTR-2B. Follow up with the supplier to upload it — the dashboard lists suppliers whose GSTR-2B figure trails your books, largest gap first." } },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "ITC Reconciliation Dashboard" },
];

function Bars({ row, max }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 120 }} aria-hidden="true">
      {COLUMNS.map((c) => (
        <div
          key={c.key}
          style={{ height: 6, borderRadius: 3, background: c.color, width: `${Math.max(1, (row[c.key] / max) * 100)}%` }}
        />
      ))}
    </div>
  );
}

export default function ItcReconciliationDashboardPage() {
  usePageTitle("ITC Reconciliation Dashboard — Books vs GSTR-2B vs GSTR-3B");

  const draft = useMemo(loadDraft, []);
  const [fy, setFy] = useState(draft?.fy || FY_OPTIONS[0]);
  const [months, setMonths] = useState(draft?.months || emptyItcMonths);
  const [suppliers, setSuppliers] = useState(draft?.suppliers?.length ? draft.suppliers : [EMPTY_SUPPLIER]);
  const today = useMemo(() => todayInIndia(), []);

  useEffect(() => {
    try {
      window.localStorage.setItem(DRAFT_KEY, JSON.stringify({ fy, months, suppliers }));
    } catch {
      // Storage unavailable — the dashboard still works for this visit.
    }
  }, [fy, months, suppliers]);

  const dash = useMemo(() => buildItcDashboard({ months, fy, today, suppliers }), [months, fy, today, suppliers]);

  const setCell = (i, key, value) => setMonths((prev) => prev.map((m, j) => (j === i ? { ...m, [key]: value } : m)));
  const setSupplier = (i, key, value) => setSuppliers((prev) => prev.map((s, j) => (j === i ? { ...s, [key]: value } : s)));

  const loadSample = () => {
    const s = sampleData();
    setMonths(s.months);
    setSuppliers(s.suppliers);
  };
  const reset = () => {
    setMonths(emptyItcMonths());
    setSuppliers([EMPTY_SUPPLIER]);
  };

  const riskTone = dash ? { high: "bad", medium: "warn", low: "good" }[dash.risk] : "neutral";

  return (
    <div className="tool-page">
      <SeoHead
        title="ITC Reconciliation Dashboard — Books vs GSTR-2B vs GSTR-3B"
        description="Free ITC reconciliation dashboard: compare purchase-book credit, GSTR-2B and GSTR-3B month by month. Spot excess claims, unclaimed credit before 30 November, and suppliers to chase."
        path={PATH}
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb items={[{ label: "Home", to: "/" }, { label: "Free Tools", to: "/resources" }, { label: "ITC Reconciliation Dashboard" }]} />
          <h1 className="tool-title">ITC Reconciliation Dashboard</h1>
          <p className="tool-subtitle">
            Your year of input tax credit on one screen: what your books say, what GSTR-2B supports,
            and what you claimed. Every gap is sorted into excess (notice risk), unclaimed (money left
            behind) or supplier-pending (chase them). Figures stay in your browser.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Financial year
              <select className="calc-select" value={fy} onChange={(e) => setFy(e.target.value)}>
                {FY_OPTIONS.map((y) => (
                  <option key={y} value={y}>FY {y}</option>
                ))}
              </select>
            </label>
            <div className="calc-result-actions">
              <button type="button" className="btn btn-ghost" onClick={loadSample}>Load sample year</button>
              <button type="button" className="btn btn-ghost" onClick={reset}>Clear all</button>
            </div>

            <TableScroll label="Monthly ITC figures">
              <table className="calendar-table">
                <thead>
                  <tr>
                    <th>Month</th>
                    {COLUMNS.map((c) => (
                      <th key={c.key}>{c.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {months.map((m, i) => (
                    <tr key={m.month}>
                      <td>{m.month}</td>
                      {COLUMNS.map((c) => (
                        <td key={c.key}>
                          <input
                            type="number"
                            className="calc-input"
                            aria-label={`${m.month} ${c.label}`}
                            value={m[c.key]}
                            onChange={(e) => setCell(i, c.key, e.target.value)}
                            min="0"
                            inputMode="decimal"
                          />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
          </div>

          {dash && (
            <section aria-live="polite" style={{ marginTop: "1rem" }}>
              <h2>FY {fy} at a glance</h2>
              <div className="stat-grid">
                <StatCard
                  label="Overall risk"
                  value={{ high: "High", medium: "Medium", low: "Low" }[dash.risk]}
                  sub={`${dash.matchedMonths} of ${dash.filledMonths} months matched`}
                  tone={riskTone}
                />
                <StatCard label="Claimed backed by GSTR-2B" value={`${dash.coverage}%`} sub={`${formatINR(dash.totals.claimed)} claimed`} tone={dash.coverage < 100 ? "bad" : "good"} />
                <StatCard
                  label="Excess ITC claimed"
                  value={formatINR(dash.totals.excess)}
                  sub={dash.totals.interestExposure > 0 ? `≈ ${formatINR(dash.totals.interestExposure)} interest at 18%` : "No 50(3) exposure"}
                  tone={dash.totals.excess > 0 ? "bad" : "good"}
                />
                <StatCard label="Unclaimed eligible ITC" value={formatINR(dash.totals.unclaimed)} sub="In GSTR-2B and your books" tone={dash.totals.unclaimed > 0 ? "warn" : "good"} />
                <StatCard label="Awaiting suppliers" value={formatINR(dash.totals.supplierGap)} sub="In books, missing from GSTR-2B" tone={dash.totals.supplierGap > 0 ? "warn" : "good"} />
                <StatCard
                  label="Section 16(4) deadline"
                  value={dash.deadlinePassed ? "Passed" : `${dash.daysLeft} days`}
                  sub={`Claim FY ${fy} credit by 30 Nov ${Number(fy.slice(0, 4)) + 1}`}
                  tone={dash.deadlinePassed ? "bad" : dash.daysLeft <= 45 ? "warn" : "neutral"}
                />
              </div>

              {dash.deadlinePassed && dash.totals.unclaimed > 0 && (
                <p className="calc-note" role="alert">
                  The claim window for FY {fy} has closed — {formatINR(dash.totals.unclaimed)} of unclaimed credit has lapsed.
                </p>
              )}

              <TableScroll label="Month-wise reconciliation">
                <table className="calendar-table">
                  <thead>
                    <tr>
                      <th>Month</th>
                      <th>Books / 2B / Claimed</th>
                      <th>Excess</th>
                      <th>Unclaimed</th>
                      <th>Supplier gap</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dash.months.map((r) => (
                      <tr key={r.month}>
                        <td>{r.month}</td>
                        <td><Bars row={r} max={dash.maxValue} /></td>
                        <td>{r.excess ? formatINR(r.excess) : "—"}</td>
                        <td>{r.unclaimed ? formatINR(r.unclaimed) : "—"}</td>
                        <td>{r.supplierGap ? formatINR(r.supplierGap) : "—"}</td>
                        <td style={{ color: STATUS[r.status].color, fontWeight: 600 }}>{STATUS[r.status].label}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableScroll>
              <p className="calc-note">
                Bars, top to bottom: {COLUMNS.map((c) => c.label).join(" · ")}.
              </p>

              <div className="calc-result-actions">
                <ShareButtons path={PATH} text={`Reconciled a full year of ITC — books vs GSTR-2B vs 3B — on the free DoAide GST dashboard`} />
                <PrintButton label="Print Dashboard" />
              </div>
            </section>
          )}

          <section className="calc-card" style={{ marginTop: "1rem" }}>
            <h2 style={{ marginTop: 0 }}>Supplier follow-up list</h2>
            <p className="calc-note">Add suppliers with their annual ITC in your books and in GSTR-2B. Those trailing by more than ₹100 are listed for follow-up.</p>
            {suppliers.map((s, i) => (
              <div key={i} className="calc-grid">
                <input className="calc-input" aria-label={`Supplier ${i + 1} name`} placeholder="Supplier name" value={s.name} onChange={(e) => setSupplier(i, "name", e.target.value)} />
                <input className="calc-input" type="number" aria-label={`Supplier ${i + 1} ITC in books`} placeholder="ITC in books" value={s.books} onChange={(e) => setSupplier(i, "books", e.target.value)} min="0" />
                <input className="calc-input" type="number" aria-label={`Supplier ${i + 1} ITC in GSTR-2B`} placeholder="ITC in GSTR-2B" value={s.gstr2b} onChange={(e) => setSupplier(i, "gstr2b", e.target.value)} min="0" />
              </div>
            ))}
            <button type="button" className="btn btn-ghost" onClick={() => setSuppliers((prev) => [...prev, EMPTY_SUPPLIER])}>
              + Add supplier
            </button>
            {dash && dash.followUps.length > 0 && (
              <ol aria-label="Suppliers to chase">
                {dash.followUps.map((s) => (
                  <li key={s.name}>
                    <strong>{s.name}</strong> — {formatINR(s.gap)} not yet in your GSTR-2B
                  </li>
                ))}
              </ol>
            )}
          </section>

          <EmailCapture
            source="itc-reconciliation-dashboard"
            heading="Don't let ITC lapse"
            subtext="We'll remind you before the 30 November Section 16(4) deadline."
            buttonLabel="Remind Me"
            compact
          />

          <section className="tool-info">
            <h2>Reading the Dashboard</h2>
            <ul>
              <li><strong>Excess claim</strong> — claimed more than GSTR-2B shows. Reverse it through GSTR-3B or DRC-03; if it was used to pay tax, 18% interest applies from the month it was used.</li>
              <li><strong>Unclaimed</strong> — eligible credit present in both your books and GSTR-2B but not taken. Claim it in a later GSTR-3B before 30 November.</li>
              <li><strong>Supplier gap</strong> — in your books but not in GSTR-2B. The supplier has not filed GSTR-1 or reported it wrongly; you cannot claim it until it shows up.</li>
            </ul>
            <p>
              For invoice-level matching, upload both registers to the{" "}
              <Link to="/gstr2b-reconciliation">GSTR-2B reconciliation tool</Link>. Closing the year? Carry these
              totals into the <Link to="/gstr9-summary">GSTR-9 summary</Link> (Tables 6 and 8).
            </p>
          </section>

          <InlineCTA variant="save" />
          <RelatedTools current={PATH} />
          <CrossProductLinks page="itc-reconciliation-dashboard" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}
