import { useMemo, useState } from "react";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import ExitIntentPopup from "../components/ExitIntentPopup";
import PrintButton from "../components/PrintButton";
import RelatedTools from "../components/RelatedTools";
import SaveResultsCTA from "../components/SaveResultsCTA";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { formatINR } from "../lib/gstCalc";

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GSTR-9 Annual Return Helper",
  url: "https://gst.doaide.com/gstr9-helper",
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
      name: "What is GSTR-9?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "GSTR-9 is the annual return every registered taxpayer must file, except composition dealers, casual taxable persons, ISD, and TDS deductors. It consolidates GSTR-1 and GSTR-3B data for the year.",
      },
    },
    {
      "@type": "Question",
      name: "What is the due date for GSTR-9?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "GSTR-9 is due by 31st December of the year following the financial year. For FY 2025-26, the due date is 31st December 2026. Late filing attracts a fee of ₹200/day (₹100 CGST + ₹100 SGST), capped at 0.5% of turnover.",
      },
    },
    {
      "@type": "Question",
      name: "Who is exempt from filing GSTR-9?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Taxpayers with turnover up to ₹2 crore are exempt from GSTR-9. Composition dealers, casual and non-resident taxable persons, ISD, and TDS deductors are also exempt per the latest notification.",
      },
    },
    {
      "@type": "Question",
      name: "What is the difference between GSTR-9 and GSTR-9C?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "GSTR-9 summarizes all outward and inward supplies for the year. GSTR-9C is the self-certified reconciliation matching GSTR-9 with audited financials, mandatory for turnover above ₹5 crore.",
      },
    },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "GSTR-9 Annual Return Helper" },
];

const MONTHS = [
  "April", "May", "June", "July", "August", "September",
  "October", "November", "December", "January", "February", "March",
];

function emptyMonthly() {
  return MONTHS.map((m) => ({ month: m, outward: "", inward: "", taxPaid: "" }));
}

export default function Gstr9HelperPage() {
  usePageTitle("GSTR-9 Annual Return Helper — Free Calculator");

  const [financialYear, setFinancialYear] = useState("2025-26");
  const [monthlyData, setMonthlyData] = useState(emptyMonthly);
  const [exemptSupply, setExemptSupply] = useState("");
  const [nilRatedSupply, setNilRatedSupply] = useState("");
  const [nonGstSupply, setNonGstSupply] = useState("");
  const [itcReversed, setItcReversed] = useState("");
  const [itcReclaimed, setItcReclaimed] = useState("");
  const [lateFee, setLateFee] = useState("");

  const updateMonth = (index, field, value) => {
    setMonthlyData((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
  };

  const summary = useMemo(() => {
    let totalOutward = 0;
    let totalInward = 0;
    let totalTaxPaid = 0;
    let filledMonths = 0;

    for (const m of monthlyData) {
      const o = parseFloat(m.outward);
      const i = parseFloat(m.inward);
      const t = parseFloat(m.taxPaid);
      if (Number.isFinite(o)) totalOutward += o;
      if (Number.isFinite(i)) totalInward += i;
      if (Number.isFinite(t)) totalTaxPaid += t;
      if (Number.isFinite(o) || Number.isFinite(i) || Number.isFinite(t)) filledMonths++;
    }

    if (filledMonths === 0) return null;

    const exempt = parseFloat(exemptSupply) || 0;
    const nilRated = parseFloat(nilRatedSupply) || 0;
    const nonGst = parseFloat(nonGstSupply) || 0;
    const reversed = parseFloat(itcReversed) || 0;
    const reclaimed = parseFloat(itcReclaimed) || 0;
    const fee = parseFloat(lateFee) || 0;

    const netItc = Math.round((totalInward - reversed + reclaimed) * 100) / 100;
    const totalTurnover = Math.round((totalOutward + exempt + nilRated + nonGst) * 100) / 100;

    return {
      totalOutward: Math.round(totalOutward * 100) / 100,
      totalInward: Math.round(totalInward * 100) / 100,
      totalTaxPaid: Math.round(totalTaxPaid * 100) / 100,
      exempt,
      nilRated,
      nonGst,
      itcReversed: reversed,
      itcReclaimed: reclaimed,
      netItc,
      totalTurnover,
      lateFee: fee,
      filledMonths,
    };
  }, [monthlyData, exemptSupply, nilRatedSupply, nonGstSupply, itcReversed, itcReclaimed, lateFee]);

  return (
    <div className="tool-page">
      <SeoHead
        title="GSTR-9 Annual Return Helper — Free GST Calculator"
        description="Calculate your GSTR-9 annual return summary. Enter monthly outward supplies, inward ITC, and tax paid to get the complete annual picture. Free, no login required."
        path="/gstr9-helper"
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">GSTR-9 Annual Return Helper</h1>
          <p className="tool-subtitle">
            Summarize your annual GST data from monthly returns. Enter GSTR-3B values to get a GSTR-9 overview. No sign-up required.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Financial Year
              <select
                className="calc-select"
                value={financialYear}
                onChange={(e) => setFinancialYear(e.target.value)}
              >
                <option value="2025-26">2025-26</option>
                <option value="2024-25">2024-25</option>
                <option value="2023-24">2023-24</option>
              </select>
            </label>

            <h3 style={{ margin: "1rem 0 0.5rem", fontSize: "1rem" }}>Monthly Data (from GSTR-3B)</h3>
            <div style={{ overflowX: "auto" }}>
              <table className="data-table" style={{ width: "100%", fontSize: "0.85rem" }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: "left", padding: "0.5rem" }}>Month</th>
                    <th style={{ textAlign: "right", padding: "0.5rem" }}>Outward Supplies (₹)</th>
                    <th style={{ textAlign: "right", padding: "0.5rem" }}>ITC Claimed (₹)</th>
                    <th style={{ textAlign: "right", padding: "0.5rem" }}>Tax Paid (₹)</th>
                  </tr>
                </thead>
                <tbody>
                  {monthlyData.map((m, i) => (
                    <tr key={m.month}>
                      <td style={{ padding: "0.4rem 0.5rem", whiteSpace: "nowrap" }}>{m.month}</td>
                      <td style={{ padding: "0.4rem 0.25rem" }}>
                        <input
                          type="number"
                          className="calc-input"
                          style={{ margin: 0, padding: "0.35rem 0.5rem", textAlign: "right" }}
                          value={m.outward}
                          onChange={(e) => updateMonth(i, "outward", e.target.value)}
                          aria-label={`${m.month}: Outward supplies (₹)`}
                          placeholder="0"
                          min="0"
                          inputMode="numeric"
                        />
                      </td>
                      <td style={{ padding: "0.4rem 0.25rem" }}>
                        <input
                          type="number"
                          className="calc-input"
                          style={{ margin: 0, padding: "0.35rem 0.5rem", textAlign: "right" }}
                          value={m.inward}
                          onChange={(e) => updateMonth(i, "inward", e.target.value)}
                          aria-label={`${m.month}: ITC claimed (₹)`}
                          placeholder="0"
                          min="0"
                          inputMode="numeric"
                        />
                      </td>
                      <td style={{ padding: "0.4rem 0.25rem" }}>
                        <input
                          type="number"
                          className="calc-input"
                          style={{ margin: 0, padding: "0.35rem 0.5rem", textAlign: "right" }}
                          value={m.taxPaid}
                          onChange={(e) => updateMonth(i, "taxPaid", e.target.value)}
                          aria-label={`${m.month}: Tax paid (₹)`}
                          placeholder="0"
                          min="0"
                          inputMode="numeric"
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <h3 style={{ margin: "1.25rem 0 0.5rem", fontSize: "1rem" }}>Additional Details</h3>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
              <label className="calc-label">
                Exempt Supply (₹)
                <input type="number" className="calc-input" value={exemptSupply} onChange={(e) => setExemptSupply(e.target.value)} placeholder="0" min="0" inputMode="numeric" />
              </label>
              <label className="calc-label">
                Nil-Rated Supply (₹)
                <input type="number" className="calc-input" value={nilRatedSupply} onChange={(e) => setNilRatedSupply(e.target.value)} placeholder="0" min="0" inputMode="numeric" />
              </label>
              <label className="calc-label">
                Non-GST Supply (₹)
                <input type="number" className="calc-input" value={nonGstSupply} onChange={(e) => setNonGstSupply(e.target.value)} placeholder="0" min="0" inputMode="numeric" />
              </label>
              <label className="calc-label">
                ITC Reversed (₹)
                <input type="number" className="calc-input" value={itcReversed} onChange={(e) => setItcReversed(e.target.value)} placeholder="0" min="0" inputMode="numeric" />
              </label>
              <label className="calc-label">
                ITC Reclaimed (₹)
                <input type="number" className="calc-input" value={itcReclaimed} onChange={(e) => setItcReclaimed(e.target.value)} placeholder="0" min="0" inputMode="numeric" />
              </label>
              <label className="calc-label">
                Late Fee Paid (₹)
                <input type="number" className="calc-input" value={lateFee} onChange={(e) => setLateFee(e.target.value)} placeholder="0" min="0" inputMode="numeric" />
              </label>
            </div>

            {summary && (
              <div className="calc-result" aria-live="polite" style={{ marginTop: "1rem" }}>
                <h3 style={{ margin: "0 0 0.5rem", fontSize: "1rem" }}>
                  GSTR-9 Summary — FY {financialYear}
                  <PrintButton style={{ marginLeft: "0.5rem" }} />
                </h3>
                <div className="calc-result-row">
                  <span>Months Entered</span>
                  <strong>{summary.filledMonths} / 12</strong>
                </div>
                <div className="calc-result-row calc-total">
                  <span>Total Taxable Outward Supplies</span>
                  <strong>{formatINR(summary.totalOutward)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>Exempt Supplies</span>
                  <strong>{formatINR(summary.exempt)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>Nil-Rated Supplies</span>
                  <strong>{formatINR(summary.nilRated)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>Non-GST Supplies</span>
                  <strong>{formatINR(summary.nonGst)}</strong>
                </div>
                <div className="calc-result-row calc-total">
                  <span>Total Annual Turnover</span>
                  <strong>{formatINR(summary.totalTurnover)}</strong>
                </div>
                <hr style={{ border: "none", borderTop: "1px solid var(--border-color, #333)", margin: "0.5rem 0" }} />
                <div className="calc-result-row">
                  <span>Total ITC Claimed</span>
                  <strong>{formatINR(summary.totalInward)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>ITC Reversed</span>
                  <strong style={{ color: "#f87171" }}>({formatINR(summary.itcReversed)})</strong>
                </div>
                <div className="calc-result-row">
                  <span>ITC Reclaimed</span>
                  <strong style={{ color: "#34d399" }}>{formatINR(summary.itcReclaimed)}</strong>
                </div>
                <div className="calc-result-row calc-total">
                  <span>Net ITC Available</span>
                  <strong>{formatINR(summary.netItc)}</strong>
                </div>
                <hr style={{ border: "none", borderTop: "1px solid var(--border-color, #333)", margin: "0.5rem 0" }} />
                <div className="calc-result-row calc-total">
                  <span>Total Tax Paid</span>
                  <strong>{formatINR(summary.totalTaxPaid)}</strong>
                </div>
                {summary.lateFee > 0 && (
                  <div className="calc-result-row">
                    <span>Late Fees Paid</span>
                    <strong style={{ color: "#f87171" }}>{formatINR(summary.lateFee)}</strong>
                  </div>
                )}

                {summary.totalTurnover > 20000000 && (
                  <p style={{ margin: "0.75rem 0 0", padding: "0.5rem", background: "rgba(251, 191, 36, 0.1)", borderRadius: "0.375rem", fontSize: "0.9rem", lineHeight: 1.4 }}>
                    <strong>Note:</strong> With turnover above ₹2 crore, GSTR-9 filing is mandatory.
                    {summary.totalTurnover > 50000000 && " With turnover above ₹5 crore, GSTR-9C (reconciliation statement) is also required."}
                  </p>
                )}

                <div className="calc-result-actions">
                  <ShareButtons
                    path="/gstr9-helper"
                    text={`GSTR-9 Summary FY ${financialYear}: Turnover ${formatINR(summary.totalTurnover)}, Tax Paid ${formatINR(summary.totalTaxPaid)} — prepared on DoAide GST`}
                    toolName="GSTR-9 Helper"
                  />
                </div>
              </div>
            )}
          </div>

          {summary && (
            <SaveResultsCTA resultSummary={`GSTR-9 FY ${financialYear}: Turnover ${formatINR(summary.totalTurnover)}, Tax ${formatINR(summary.totalTaxPaid)}`} />
          )}
          <EmailCapture
            source="gstr9-helper"
            heading="Automate your GSTR-9 filing"
            subtext="GSTIndia auto-fills your annual return from uploaded invoices — sign up free."
            buttonLabel="Start Free"
            compact
          />

          <section className="tool-info">
            <h2>GSTR-9 Annual Return — Complete Guide</h2>
            <p>
              GSTR-9 is the annual return that consolidates all monthly/quarterly returns filed
              during a financial year. It includes details of outward and inward supplies, ITC
              claimed and reversed, tax paid, and demands and refunds.
            </p>
            <h3>Who Must File GSTR-9?</h3>
            <ul>
              <li>All regular taxpayers with turnover above ₹2 crore</li>
              <li>Taxpayers below ₹2 crore are exempt (latest notification)</li>
              <li>Composition dealers file GSTR-9A instead</li>
              <li>Casual/non-resident taxable persons, ISD, and TDS deductors are exempt</li>
            </ul>
            <h3>GSTR-9 Tables</h3>
            <ul>
              <li><strong>Part I (Tables 1-3):</strong> Basic details — GSTIN, legal name, FY</li>
              <li><strong>Part II (Tables 4-5):</strong> Outward and inward supplies</li>
              <li><strong>Part III (Tables 6-8):</strong> ITC details — claimed, reversed, ineligible</li>
              <li><strong>Part IV (Table 9):</strong> Tax paid — IGST, CGST, SGST, Cess</li>
              <li><strong>Part V (Tables 10-14):</strong> Amendments, late fee, demands, refunds</li>
            </ul>
            <h3>GSTR-9C (Reconciliation Statement)</h3>
            <p>
              Taxpayers with turnover above ₹5 crore must also file GSTR-9C, which is a
              self-certified reconciliation between GSTR-9 and the audited financial statements.
              It highlights differences between books and returns.
            </p>
            <h3>Late Fee</h3>
            <ul>
              <li>₹200/day (₹100 CGST + ₹100 SGST) for each day of delay</li>
              <li>Maximum cap: 0.5% of turnover in the state/UT (0.25% CGST + 0.25% SGST)</li>
              <li>No late fee for nil returns (zero tax liability and zero turnover)</li>
            </ul>
          </section>

          <section className="tool-info">
            <h2>Frequently Asked Questions</h2>

            <h3>What is GSTR-9?</h3>
            <p>
              GSTR-9 is the annual GST return that consolidates all monthly/quarterly returns
              (GSTR-1 and GSTR-3B) filed during the financial year. It covers outward supplies,
              inward ITC, tax paid, and amendments.
            </p>

            <h3>What is the due date for GSTR-9?</h3>
            <p>
              31st December of the year following the financial year. For FY 2025-26, the
              due date is 31st December 2026. Late filing attracts ₹200/day, capped at
              0.5% of state turnover.
            </p>

            <h3>Who is exempt from filing GSTR-9?</h3>
            <p>
              Taxpayers with turnover up to ₹2 crore, composition dealers (they file GSTR-9A),
              casual and non-resident taxable persons, ISD, and TDS/TCS deductors.
            </p>

            <h3>What is the difference between GSTR-9 and GSTR-9C?</h3>
            <p>
              GSTR-9 is the annual return with all supply and ITC details. GSTR-9C is the
              self-certified reconciliation statement comparing GSTR-9 with audited financials.
              GSTR-9C is required only for turnover above ₹5 crore.
            </p>
          </section>

          <InlineCTA variant="save" />
          <RelatedTools current="/gstr9-helper" />
          <CrossProductLinks page="gstr9-helper" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
      <ExitIntentPopup />
    </div>
  );
}
