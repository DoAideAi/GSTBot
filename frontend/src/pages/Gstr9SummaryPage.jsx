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
import TableScroll from "../components/TableScroll";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { formatINR } from "../lib/gstCalc";
import { emptyMonths, parsePastedMonths, summarizeGstr9 } from "../lib/gstr9Summary";
import { todayInIndia } from "../lib/returnDueDates";

const PATH = "/gstr9-summary";
const DRAFT_KEY = "gst.gstr9-summary.draft";
const FY_OPTIONS = ["2025-26", "2024-25", "2026-27"];

const COLUMNS = [
  { key: "r1Taxable", label: "GSTR-1 taxable value" },
  { key: "r1Tax", label: "GSTR-1 tax" },
  { key: "b3Taxable", label: "GSTR-3B taxable value" },
  { key: "b3Tax", label: "GSTR-3B tax" },
  { key: "b3Itc", label: "GSTR-3B ITC claimed" },
];

// A deliberately imperfect sample year: one month under-declared in GSTR-3B,
// one over-declared, and ITC claimed slightly beyond GSTR-2B.
function sampleMonths() {
  return emptyMonths().map((m, i) => {
    const base = 1500000 + i * 50000;
    const tax = Math.round(base * 0.18);
    return {
      ...m,
      r1Taxable: String(base),
      r1Tax: String(tax),
      b3Taxable: String(i === 4 ? base - 100000 : base),
      b3Tax: String(i === 4 ? tax - 18000 : i === 9 ? tax + 5000 : tax),
      b3Itc: String(Math.round(tax * 0.7)),
    };
  });
}

function loadDraft() {
  try {
    const raw = window.localStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed?.months) && parsed.months.length === 12 ? parsed : null;
  } catch {
    return null;
  }
}

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GSTR-9 Summary Generator",
  url: `https://gst.doaide.com${PATH}`,
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const FAQ_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    { "@type": "Question", name: "Which figures go into GSTR-9 Table 4 and Table 9?", acceptedAnswer: { "@type": "Answer", text: "Table 4 reports outward supplies as declared in GSTR-1 for the year. Table 9 reports the tax actually paid through GSTR-3B. Any gap between the two is either an error to explain or tax still to be paid." } },
    { "@type": "Question", name: "How do I pay tax found short while preparing GSTR-9?", acceptedAnswer: { "@type": "Answer", text: "Through Form DRC-03 (voluntary payment), in cash, with 18% interest from the GSTR-3B due date of the month it belonged to. It cannot be paid inside GSTR-9 itself through the ITC ledger." } },
    { "@type": "Question", name: "What does Table 8D in GSTR-9 show?", acceptedAnswer: { "@type": "Answer", text: "The difference between ITC available in GSTR-2B (Table 8A) and ITC claimed in GSTR-3B. A negative figure — more claimed than GSTR-2B supports — is one of the most common triggers for an ASMT-10 scrutiny notice." } },
    { "@type": "Question", name: "Who must file GSTR-9 for FY 2025-26?", acceptedAnswer: { "@type": "Answer", text: "Regular taxpayers with aggregate turnover above ₹2 crore must file GSTR-9 by 31 December 2026. Above ₹5 crore, the GSTR-9C reconciliation statement is also required. Composition dealers file GSTR-4 instead." } },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "GSTR-9 Summary Generator" },
];

export default function Gstr9SummaryPage() {
  usePageTitle("GSTR-9 Summary Generator — GSTR-1 vs GSTR-3B Annual Reconciliation");

  const draft = useMemo(loadDraft, []);
  const [fy, setFy] = useState(draft?.fy || FY_OPTIONS[0]);
  const [months, setMonths] = useState(draft?.months || emptyMonths);
  const [itc2b, setItc2b] = useState(draft?.itc2b ?? "");
  const [itcReversed, setItcReversed] = useState(draft?.itcReversed ?? "");
  const [exempt, setExempt] = useState(draft?.exempt ?? "");
  const [payOn, setPayOn] = useState(() => todayInIndia());
  const [paste, setPaste] = useState("");
  const [pasteMsg, setPasteMsg] = useState("");

  useEffect(() => {
    try {
      window.localStorage.setItem(DRAFT_KEY, JSON.stringify({ fy, months, itc2b, itcReversed, exempt }));
    } catch {
      // Private mode or storage full — the tool works without the draft.
    }
  }, [fy, months, itc2b, itcReversed, exempt]);

  const summary = useMemo(
    () => summarizeGstr9({ months, itc2b, itcReversed, exempt, fy, payOn }),
    [months, itc2b, itcReversed, exempt, fy, payOn],
  );

  const updateCell = (index, key, value) => {
    setMonths((prev) => prev.map((m, i) => (i === index ? { ...m, [key]: value } : m)));
  };

  const applyPaste = () => {
    const { months: parsed, rows } = parsePastedMonths(paste);
    if (rows === 0) {
      setPasteMsg("No numeric rows found — paste one row per month, April first.");
      return;
    }
    setMonths(parsed);
    setPasteMsg(`Filled ${rows} month${rows === 1 ? "" : "s"} from the pasted rows.`);
  };

  const reset = () => {
    setMonths(emptyMonths());
    setItc2b("");
    setItcReversed("");
    setExempt("");
    setPasteMsg("");
  };

  const loadSample = () => {
    setMonths(sampleMonths());
    setItc2b("2650000");
    setItcReversed("25000");
    setExempt("350000");
    setPasteMsg("Sample year loaded — August is short-paid in GSTR-3B and January over-paid.");
  };

  return (
    <div className="tool-page">
      <SeoHead
        title="GSTR-9 Summary Generator — GSTR-1 vs GSTR-3B Annual Reconciliation"
        description="Enter twelve months of GSTR-1 and GSTR-3B figures and get your GSTR-9 Tables 4, 6, 8 and 9, the month-wise mismatches, the DRC-03 amount with interest, and whether GSTR-9C applies. Free, runs in your browser."
        path={PATH}
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb items={[{ label: "Home", to: "/" }, { label: "Free Tools", to: "/resources" }, { label: "GSTR-9 Summary" }]} />
          <h1 className="tool-title">GSTR-9 Summary Generator</h1>
          <p className="tool-subtitle">
            Put the year&apos;s GSTR-1 and GSTR-3B side by side. See the GSTR-9 table totals, every
            month that doesn&apos;t match, and what you would owe through DRC-03 before the portal
            shows it to you. Figures stay in your browser.
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

            <details>
              <summary>Paste from Excel or Google Sheets</summary>
              <label className="calc-label">
                One row per month, April first: GSTR-1 value, GSTR-1 tax, GSTR-3B value, GSTR-3B tax, ITC claimed
                <textarea
                  className="calc-input"
                  rows={5}
                  value={paste}
                  onChange={(e) => setPaste(e.target.value)}
                  placeholder={"April\t1500000\t270000\t1500000\t270000\t189000"}
                />
              </label>
              <button type="button" className="btn btn-ghost" onClick={applyPaste}>Fill table</button>
            </details>
            {pasteMsg && <p className="calc-note" role="status">{pasteMsg}</p>}

            <TableScroll label="Monthly GSTR-1 and GSTR-3B figures">
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
                            onChange={(e) => updateCell(i, c.key, e.target.value)}
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

            <label className="calc-label">
              ITC available as per GSTR-2B for the year (Table 8A, ₹)
              <input type="number" className="calc-input" value={itc2b} onChange={(e) => setItc2b(e.target.value)} min="0" inputMode="decimal" />
            </label>
            <label className="calc-label">
              ITC reversed during the year (Table 7, ₹)
              <input type="number" className="calc-input" value={itcReversed} onChange={(e) => setItcReversed(e.target.value)} min="0" inputMode="decimal" />
            </label>
            <label className="calc-label">
              Exempt, nil-rated and non-GST supplies (Table 5, ₹)
              <input type="number" className="calc-input" value={exempt} onChange={(e) => setExempt(e.target.value)} min="0" inputMode="decimal" />
            </label>
            <label className="calc-label">
              Date you will pay any shortfall (for interest)
              <input type="date" className="calc-input" value={payOn} onChange={(e) => setPayOn(e.target.value)} />
            </label>
          </div>

          {summary && (
            <div className="calc-card" aria-live="polite" style={{ marginTop: "1rem" }}>
              <h2 style={{ margin: "0 0 1rem" }}>GSTR-9 Summary — FY {fy}</h2>
              <div className="calc-result">
                <div className="calc-result-row"><span>Table 4 — outward taxable value (GSTR-1)</span><strong>{formatINR(summary.table4.taxable)}</strong></div>
                <div className="calc-result-row"><span>Table 4 — tax on outward supplies</span><strong>{formatINR(summary.table4.tax)}</strong></div>
                <div className="calc-result-row"><span>Table 9 — tax paid (GSTR-3B)</span><strong>{formatINR(summary.table9.taxPaid)}</strong></div>
                <div className="calc-result-row"><span>Table 6 — ITC claimed (GSTR-3B)</span><strong>{formatINR(summary.table6.itcClaimed)}</strong></div>
                <div className="calc-result-row"><span>Net ITC after Table 7 reversals</span><strong>{formatINR(summary.netItc)}</strong></div>
                {summary.table8.difference !== null && (
                  <div className="calc-result-row">
                    <span>Table 8D — GSTR-2B minus ITC claimed</span>
                    <strong>{formatINR(summary.table8.difference)}</strong>
                  </div>
                )}
                <div className="calc-result-row"><span>Aggregate turnover (approx.)</span><strong>{formatINR(summary.aggregateTurnover)}</strong></div>
                <div className="calc-result-row calc-total"><span>Payable via DRC-03 (tax + interest)</span><strong>{formatINR(summary.drc03Total)}</strong></div>
              </div>

              <p className="calc-note">{summary.applicability.note} Due date: 31 December {fy.slice(0, 4) * 1 + 1}.</p>
              {summary.table8.difference !== null && summary.table8.difference < 0 && (
                <p className="calc-note" role="alert">
                  You claimed {formatINR(-summary.table8.difference)} more ITC than GSTR-2B supports. Expect this to be
                  questioned — keep the invoices ready or reverse it through DRC-03.
                </p>
              )}
              {summary.table8.difference !== null && summary.table8.difference > 0 && (
                <p className="calc-note">
                  {formatINR(summary.table8.difference)} of GSTR-2B credit was never claimed. Credit for FY {fy} can
                  only be claimed until 30 November {fy.slice(0, 4) * 1 + 1} (Section 16(4)).
                </p>
              )}

              {(summary.shortPaidMonths.length > 0 || summary.overPaidMonths.length > 0) && (
                <>
                  <h3>Months that don&apos;t match</h3>
                  <TableScroll label="Month-wise GSTR-1 vs GSTR-3B differences">
                    <table className="calendar-table">
                      <thead>
                        <tr>
                          <th>Month</th>
                          <th>Tax gap (GSTR-1 − 3B)</th>
                          <th>Status</th>
                          <th>Interest</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...summary.shortPaidMonths, ...summary.overPaidMonths].map((m) => (
                          <tr key={m.month}>
                            <td>{m.month}</td>
                            <td>{formatINR(m.taxGap)}</td>
                            <td>{m.taxGap > 0 ? "Short paid — pay via DRC-03" : "Paid more than declared — check GSTR-1"}</td>
                            <td>{m.taxGap > 0 ? `${formatINR(m.interest)} (${m.interestDays} days)` : "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableScroll>
                </>
              )}
              {summary.shortPaidMonths.length === 0 && summary.overPaidMonths.length === 0 && (
                <p className="calc-note">GSTR-1 and GSTR-3B tax agree for every month entered.</p>
              )}

              <div className="calc-result-actions">
                <ShareButtons
                  path={PATH}
                  text={`Prepared my GSTR-9 summary for FY ${fy} in minutes — month-wise GSTR-1 vs 3B check, free on DoAide GST`}
                />
                <PrintButton label="Print Summary" />
              </div>
            </div>
          )}

          <EmailCapture
            source="gstr9-summary"
            heading="GSTR-9 is due 31 December"
            subtext="Get a reminder a month before, and again a week before."
            buttonLabel="Remind Me"
            compact
          />

          <section className="tool-info">
            <h2>How GSTR-9 Pulls the Year Together</h2>
            <ul>
              <li><strong>Tables 4 and 5</strong> — outward supplies, taken from GSTR-1. Taxable, exempt, nil-rated and non-GST supplies are reported separately.</li>
              <li><strong>Table 6</strong> — ITC claimed through GSTR-3B, by type (inputs, capital goods, services).</li>
              <li><strong>Table 7</strong> — credit reversed under Rules 37, 39, 42, 43 and elsewhere.</li>
              <li><strong>Table 8</strong> — ITC in GSTR-2B (8A) against what you claimed; the 8D difference is what officers look at first.</li>
              <li><strong>Table 9</strong> — tax actually paid, through cash and credit, as per GSTR-3B.</li>
            </ul>
            <p>
              Short payment found here is paid via DRC-03 with 18% interest from that month&apos;s GSTR-3B due date —
              this tool works that interest out month by month. Work through the{" "}
              <Link to="/gstr9-checklist">GSTR-9 checklist</Link> next, and match invoices with the{" "}
              <Link to="/itc-reconciliation-dashboard">ITC reconciliation dashboard</Link>. Filing late? See the{" "}
              <Link to="/gst-late-fee-interest-calculator">late fee calculator</Link> for the GSTR-9 slabs.
            </p>
          </section>

          <InlineCTA variant="save" />
          <RelatedTools current={PATH} />
          <CrossProductLinks page="gstr9-summary" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}
