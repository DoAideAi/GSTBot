import { useCallback, useMemo, useState } from "react";
import Breadcrumb from "../components/Breadcrumb";
import { StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import ExitIntentPopup from "../components/ExitIntentPopup";
import RelatedTools from "../components/RelatedTools";
import SaveResultsCTA from "../components/SaveResultsCTA";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { formatINR } from "../lib/gstCalc";

const emptyEntry = { supplierGstin: "", invoiceNo: "", invoiceDate: "", gstr2aAmount: "", booksAmount: "" };

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST ITC Mismatch Calculator",
  url: "https://gst.doaide.com/itc-mismatch",
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const FAQ_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "What is ITC mismatch in GST?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "ITC mismatch occurs when the credit claimed in your books does not match the ITC in GSTR-2A/2B. Causes include invoices not uploaded by suppliers, amount differences, or timing gaps in reporting.",
      },
    },
    {
      "@type": "Question",
      name: "Why does ITC mismatch matter?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "ITC mismatches can lead to excess claims being disallowed, resulting in demand notices, interest at 18% p.a., and penalties. Regular reconciliation helps resolve mismatches before filing.",
      },
    },
    {
      "@type": "Question",
      name: "How do I resolve ITC mismatches?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Follow up with suppliers for missing invoices, verify amounts, check for duplicates, ensure correct GSTIN mapping, and reconcile monthly before filing GSTR-3B.",
      },
    },
    {
      "@type": "Question",
      name: "What is the difference between GSTR-2A and GSTR-2B?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "GSTR-2A is dynamic and changes when a supplier files or amends. GSTR-2B is static, generated monthly on the 14th from supplier filings up to that date. GSTR-2B is authoritative for ITC claims.",
      },
    },
    {
      "@type": "Question",
      name: "Can I claim ITC that is not in GSTR-2B?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Per Section 16(2)(aa), ITC can only be claimed if the invoice appears in GSTR-2B. If missing, follow up with the supplier to file or correct their GSTR-1 before claiming the credit.",
      },
    },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "ITC Mismatch Calculator" },
];

function classifyMismatch(gstr2a, books) {
  if (gstr2a > 0 && books === 0) return { type: "not_booked", label: "Not in Books", color: "#f59e42" };
  if (gstr2a === 0 && books > 0) return { type: "not_in_gstr2a", label: "Not in GSTR-2A/2B", color: "#f87171" };
  if (Math.abs(gstr2a - books) < 0.01) return { type: "matched", label: "Matched", color: "#34d399" };
  if (gstr2a > books) return { type: "excess_gstr2a", label: "GSTR-2A > Books", color: "#f59e42" };
  return { type: "excess_books", label: "Books > GSTR-2A", color: "#f87171" };
}

export default function ItcMismatchPage() {
  usePageTitle("GST ITC Mismatch Calculator — GSTR-2A vs Books Reconciliation");

  const [entries, setEntries] = useState([{ ...emptyEntry }, { ...emptyEntry }, { ...emptyEntry }]);

  function updateEntry(index, field, value) {
    setEntries((prev) => prev.map((e, i) => i === index ? { ...e, [field]: value } : e));
  }

  function addEntry() {
    setEntries((prev) => [...prev, { ...emptyEntry }]);
  }

  const removeEntry = useCallback((index) => {
    setEntries((prev) => {
      if (prev.length <= 1) return prev;
      return prev.filter((_, i) => i !== index);
    });
  }, []);

  const analysis = useMemo(() => {
    const rows = entries.map((e) => {
      const gstr2a = parseFloat(e.gstr2aAmount) || 0;
      const books = parseFloat(e.booksAmount) || 0;
      const diff = Math.round((books - gstr2a) * 100) / 100;
      const classification = classifyMismatch(gstr2a, books);
      return { ...e, gstr2a, books, diff, ...classification };
    }).filter((r) => r.gstr2a > 0 || r.books > 0);

    if (rows.length === 0) return null;

    const totalGstr2a = rows.reduce((s, r) => s + r.gstr2a, 0);
    const totalBooks = rows.reduce((s, r) => s + r.books, 0);
    const matched = rows.filter((r) => r.type === "matched").length;
    const mismatched = rows.length - matched;
    const excessClaimed = rows.filter((r) => r.type === "excess_books" || r.type === "not_in_gstr2a")
      .reduce((s, r) => s + Math.abs(r.diff), 0);
    const notBooked = rows.filter((r) => r.type === "not_booked")
      .reduce((s, r) => s + r.gstr2a, 0);

    return {
      rows,
      totalGstr2a: Math.round(totalGstr2a * 100) / 100,
      totalBooks: Math.round(totalBooks * 100) / 100,
      totalDiff: Math.round((totalBooks - totalGstr2a) * 100) / 100,
      matched,
      mismatched,
      excessClaimed: Math.round(excessClaimed * 100) / 100,
      notBooked: Math.round(notBooked * 100) / 100,
    };
  }, [entries]);

  return (
    <div className="tool-page">
      <SeoHead
        title="GST ITC Mismatch Calculator — GSTR-2A vs Books Reconciliation"
        description="Compare your GSTR-2A/2B data with purchase books to find ITC mismatches. Identify excess claims, missing invoices, and amount differences instantly. Free, no login required."
        path="/itc-mismatch"
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">ITC Mismatch Calculator</h1>
          <p className="tool-subtitle">
            Compare GSTR-2A/2B with your books to find Input Tax Credit mismatches. No sign-up required.
          </p>

          <div className="calc-card">
            <p style={{ fontSize: "0.9rem", color: "var(--ink-soft)", marginBottom: "1rem" }}>
              Enter invoice-level GST amounts from GSTR-2A/2B and your purchase register to identify mismatches.
            </p>

            {entries.map((entry, i) => (
              <div key={i} className="form-grid line-row" style={{ "--cols": "1.5fr 1fr 1fr 1fr 1fr auto" }}>
                <label className="calc-label" style={{ margin: 0 }}>
                  <span className={i === 0 ? undefined : "line-later-label"}>Supplier GSTIN / Name</span>
                  <input
                    className="calc-input"
                    value={entry.supplierGstin}
                    onChange={(e) => updateEntry(i, "supplierGstin", e.target.value)}
                    placeholder="Supplier name or GSTIN"
                  />
                </label>
                <label className="calc-label" style={{ margin: 0 }}>
                  <span className={i === 0 ? undefined : "line-later-label"}>Invoice No.</span>
                  <input
                    className="calc-input"
                    value={entry.invoiceNo}
                    onChange={(e) => updateEntry(i, "invoiceNo", e.target.value)}
                    placeholder="INV-001"
                  />
                </label>
                <label className="calc-label" style={{ margin: 0 }}>
                  <span className={i === 0 ? undefined : "line-later-label"}>Invoice Date</span>
                  <input
                    type="date"
                    className="calc-input"
                    value={entry.invoiceDate}
                    onChange={(e) => updateEntry(i, "invoiceDate", e.target.value)}
                  />
                </label>
                <label className="calc-label" style={{ margin: 0 }}>
                  <span className={i === 0 ? undefined : "line-later-label"}>GSTR-2A/2B (₹)</span>
                  <input
                    type="number"
                    className="calc-input"
                    value={entry.gstr2aAmount}
                    onChange={(e) => updateEntry(i, "gstr2aAmount", e.target.value)}
                    placeholder="0.00"
                    min="0"
                    step="0.01"
                    inputMode="decimal"
                  />
                </label>
                <label className="calc-label" style={{ margin: 0 }}>
                  <span className={i === 0 ? undefined : "line-later-label"}>Books (₹)</span>
                  <input
                    type="number"
                    className="calc-input"
                    value={entry.booksAmount}
                    onChange={(e) => updateEntry(i, "booksAmount", e.target.value)}
                    placeholder="0.00"
                    min="0"
                    step="0.01"
                    inputMode="decimal"
                  />
                </label>
                <button
                  onClick={() => removeEntry(i)}
                  style={{ padding: "0.5rem", background: "none", border: "none", color: "#f87171", cursor: "pointer", fontSize: "1.2rem" }}
                  aria-label="Remove entry"
                  disabled={entries.length <= 1}
                >
                  ×
                </button>
              </div>
            ))}

            <button onClick={addEntry} style={{ marginTop: "0.5rem", padding: "0.5rem 1rem", background: "var(--brand)", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer", fontSize: "0.9rem" }}>
              + Add Entry
            </button>

            {analysis && (
              <div className="calc-result" aria-live="polite" style={{ marginTop: "1.5rem" }}>
                <h3 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "0.75rem" }}>Reconciliation Summary</h3>

                <div className="calc-result-row">
                  <span>Total GSTR-2A/2B ITC</span>
                  <strong>{formatINR(analysis.totalGstr2a)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>Total Books ITC</span>
                  <strong>{formatINR(analysis.totalBooks)}</strong>
                </div>
                <div className="calc-result-row calc-total" style={{ color: analysis.totalDiff === 0 ? "#34d399" : "#f87171" }}>
                  <span>Net Difference</span>
                  <strong>{analysis.totalDiff > 0 ? "+" : ""}{formatINR(analysis.totalDiff)}</strong>
                </div>

                <div className="form-grid form-grid-4" style={{ margin: "1rem 0" }}>
                  <div style={{ textAlign: "center", padding: "0.75rem", background: "var(--bg-card)", borderRadius: "8px" }}>
                    <div style={{ fontSize: "1.5rem", fontWeight: 700 }}>{analysis.rows.length}</div>
                    <div style={{ fontSize: "0.8rem", color: "var(--ink-soft)" }}>Total Entries</div>
                  </div>
                  <div style={{ textAlign: "center", padding: "0.75rem", background: "var(--bg-card)", borderRadius: "8px" }}>
                    <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "#34d399" }}>{analysis.matched}</div>
                    <div style={{ fontSize: "0.8rem", color: "var(--ink-soft)" }}>Matched</div>
                  </div>
                  <div style={{ textAlign: "center", padding: "0.75rem", background: "var(--bg-card)", borderRadius: "8px" }}>
                    <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "#f87171" }}>{analysis.mismatched}</div>
                    <div style={{ fontSize: "0.8rem", color: "var(--ink-soft)" }}>Mismatched</div>
                  </div>
                  <div style={{ textAlign: "center", padding: "0.75rem", background: "var(--bg-card)", borderRadius: "8px" }}>
                    <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "#f87171" }}>{formatINR(analysis.excessClaimed)}</div>
                    <div style={{ fontSize: "0.8rem", color: "var(--ink-soft)" }}>At Risk</div>
                  </div>
                </div>

                {analysis.rows.filter((r) => r.type !== "matched").length > 0 && (
                  <>
                    <h4 style={{ fontSize: "0.9rem", fontWeight: 600, margin: "1rem 0 0.5rem" }}>Mismatched Entries</h4>
                    {analysis.rows.filter((r) => r.type !== "matched").map((row, idx) => (
                      <div key={idx} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "0.5rem 0", borderBottom: "1px solid var(--border)", fontSize: "0.9rem" }}>
                        <div>
                          <strong>{row.supplierGstin || row.invoiceNo || `Entry ${idx + 1}`}</strong>
                          {row.invoiceNo && row.supplierGstin && <span style={{ color: "var(--ink-soft)", marginLeft: "0.5rem" }}>{row.invoiceNo}</span>}
                        </div>
                        <div style={{ textAlign: "right" }}>
                          <span style={{ color: row.color, fontWeight: 600, fontSize: "0.85rem" }}>{row.label}</span>
                          <br />
                          <span style={{ fontSize: "0.8rem", color: "var(--ink-soft)" }}>
                            2A: {formatINR(row.gstr2a)} | Books: {formatINR(row.books)} | Diff: {row.diff > 0 ? "+" : ""}{formatINR(row.diff)}
                          </span>
                        </div>
                      </div>
                    ))}
                  </>
                )}

                {analysis.notBooked > 0 && (
                  <p style={{ margin: "0.75rem 0 0", fontSize: "0.85rem", color: "#f59e42" }}>
                    ⚠ {formatINR(analysis.notBooked)} of ITC available in GSTR-2A/2B has not been booked in your purchase register.
                  </p>
                )}

                <div className="calc-result-actions">
                  <ShareButtons
                    path="/itc-mismatch"
                    text={`ITC Mismatch: ${analysis.matched} matched, ${analysis.mismatched} mismatched out of ${analysis.rows.length} entries — reconciled free on DoAide GST`}
                  />
                </div>
              </div>
            )}
          </div>

          {analysis && (
            <SaveResultsCTA resultSummary={`ITC Mismatch: ${analysis.matched} matched, ${analysis.mismatched} mismatched, ${formatINR(analysis.excessClaimed)} at risk`} />
          )}
          <EmailCapture
            source="itc-mismatch"
            heading="Automate your ITC reconciliation"
            subtext="Upload GSTR-2B and get automatic mismatch reports — sign up for the full platform."
            buttonLabel="Get Started"
            compact
          />

          <section className="tool-info">
            <h2>ITC Reconciliation — GSTR-2A/2B vs Books</h2>
            <p>
              ITC reconciliation is the process of comparing the Input Tax Credit reflected in
              your GSTR-2A/2B with the ITC recorded in your purchase register (books of accounts).
              Regular reconciliation is essential to avoid ITC mismatches that can lead to
              demand notices and penalties.
            </p>
            <h3>Types of ITC Mismatches</h3>
            <ul>
              <li><strong>Not in GSTR-2A/2B:</strong> Invoice booked in your records but supplier hasn&apos;t filed — ITC at risk of disallowance</li>
              <li><strong>Not in Books:</strong> Invoice appears in GSTR-2A/2B but not in your purchase register — potential ITC you&apos;re not claiming</li>
              <li><strong>Amount Difference:</strong> Same invoice with different GST amounts — needs verification with supplier</li>
              <li><strong>Matched:</strong> Invoice amounts match in both GSTR-2A/2B and books — no action needed</li>
            </ul>
            <h3>Why Reconciliation Matters</h3>
            <ul>
              <li>Section 16(2)(aa) requires invoices to appear in GSTR-2B for ITC claim</li>
              <li>Excess ITC claims attract interest at 18% p.a. and potential penalties</li>
              <li>Unclaimed ITC in GSTR-2A/2B means you&apos;re paying more tax than necessary</li>
              <li>Regular reconciliation prevents issues during GST audits and assessments</li>
            </ul>
          </section>

          <section className="tool-info">
            <h2>Frequently Asked Questions</h2>

            <h3>What is ITC mismatch in GST?</h3>
            <p>
              ITC mismatch occurs when the Input Tax Credit in your purchase register doesn&apos;t
              match GSTR-2A/2B. This can happen due to missing invoices, amount differences,
              or timing differences in supplier filings.
            </p>

            <h3>Why does ITC mismatch matter?</h3>
            <p>
              Mismatches can lead to excess ITC claims being disallowed, resulting in demand
              notices, interest at 18% p.a., and penalties. Regular reconciliation helps
              identify and resolve issues before filing returns.
            </p>

            <h3>How do I resolve ITC mismatches?</h3>
            <p>
              Follow up with suppliers to upload missing invoices, verify amounts with supplier
              records, check for duplicate entries, ensure correct GSTIN mapping, and reconcile
              monthly before filing GSTR-3B.
            </p>

            <h3>What is the difference between GSTR-2A and GSTR-2B?</h3>
            <p>
              GSTR-2A is dynamic and changes with each supplier filing. GSTR-2B is a static
              monthly statement generated on the 14th. GSTR-2B is the authoritative document
              for ITC claims.
            </p>

            <h3>Can I claim ITC not in GSTR-2B?</h3>
            <p>
              Per Section 16(2)(aa), ITC can only be claimed if invoice details appear in
              GSTR-2B. Follow up with suppliers to file/correct their GSTR-1 before claiming.
            </p>

            <h3>How often should I reconcile ITC?</h3>
            <p>
              Reconcile monthly, before filing GSTR-3B. This gives you time to follow up with
              suppliers for missing invoices. Also do a comprehensive reconciliation before
              filing the annual return GSTR-9.
            </p>

            <h3>What happens if I claim excess ITC?</h3>
            <p>
              Excess ITC must be reversed with interest at 18% p.a. from the date of claim
              to the date of reversal. In cases of fraud, a penalty of 100% of the tax amount
              may be levied under Section 74.
            </p>
          </section>

          <RelatedTools current="/itc-mismatch" />
          <CrossProductLinks page="itc-mismatch" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
      <ExitIntentPopup />
    </div>
  );
}
