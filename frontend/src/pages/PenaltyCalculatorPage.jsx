import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import PrintButton from "../components/PrintButton";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { formatINR } from "../lib/gstCalc";

const RETURN_TYPES = [
  { key: "gstr1", label: "GSTR-1", lateFeePerDay: 50, maxLateFee: 10000 },
  { key: "gstr3b", label: "GSTR-3B", lateFeePerDay: 50, maxLateFee: 10000 },
  { key: "gstr3b_nil", label: "GSTR-3B (Nil Return)", lateFeePerDay: 20, maxLateFee: 500 },
  { key: "gstr1_nil", label: "GSTR-1 (Nil Return)", lateFeePerDay: 20, maxLateFee: 500 },
  { key: "gstr9", label: "GSTR-9 (Annual)", lateFeePerDay: 200, maxLateFee: null },
];

const INTEREST_RATE = 18;

function daysBetween(from, to) {
  const ms = to.getTime() - from.getTime();
  return Math.max(0, Math.ceil(ms / 86400000));
}

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST Late Filing Penalty Calculator",
  url: "https://gst.doaide.com/penalty-calculator",
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
      name: "What is the late fee for GSTR-3B?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "₹50/day (₹25 CGST + ₹25 SGST) for regular returns, max ₹10,000. For nil returns, ₹20/day (₹10 CGST + ₹10 SGST), max ₹500.",
      },
    },
    {
      "@type": "Question",
      name: "What is the interest rate on late GST payment?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Interest on late GST payment is 18% per annum on the outstanding tax liability, from the day after the due date until actual payment. It applies only to the net cash liability after adjusting ITC.",
      },
    },
    {
      "@type": "Question",
      name: "Is there a maximum cap on GST late fees?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes. GSTR-1/3B: ₹10,000 per return (₹5,000 CGST + ₹5,000 SGST). Nil returns: ₹500. GSTR-9: ₹200/day, no upper cap, subject to 0.5% of state turnover.",
      },
    },
    {
      "@type": "Question",
      name: "How is GST penalty different from late fee?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Late fee is for delayed filing. Penalty under Sections 122-125 is for offences like tax evasion, incorrect invoicing, or failure to register. Interest is on late tax payment. All three are separate.",
      },
    },
    {
      "@type": "Question",
      name: "Can GST late fee be waived?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "The government periodically issues amnesty schemes waiving or reducing late fees for past periods. Check latest CBIC notifications for any ongoing waivers.",
      },
    },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "Penalty Calculator" },
];

export default function PenaltyCalculatorPage() {
  usePageTitle("GST Late Filing Penalty Calculator — Interest & Late Fees");

  const [returnType, setReturnType] = useState("gstr3b");
  const [taxLiability, setTaxLiability] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [filingDate, setFilingDate] = useState("");

  const selectedReturn = RETURN_TYPES.find((r) => r.key === returnType);

  const result = useMemo(() => {
    if (!dueDate || !filingDate || !selectedReturn) return null;
    const due = new Date(dueDate);
    const filed = new Date(filingDate);
    if (isNaN(due) || isNaN(filed)) return null;
    const days = daysBetween(due, filed);
    if (days <= 0) return null;

    const lateFeeRaw = selectedReturn.lateFeePerDay * days;
    const lateFee = selectedReturn.maxLateFee
      ? Math.min(lateFeeRaw, selectedReturn.maxLateFee)
      : lateFeeRaw;

    const liability = parseFloat(taxLiability) || 0;
    const interest = liability > 0
      ? Math.round(liability * (INTEREST_RATE / 100) * (days / 365) * 100) / 100
      : 0;

    return { days, lateFee, interest, total: lateFee + interest };
  }, [returnType, taxLiability, dueDate, filingDate, selectedReturn]);

  return (
    <div className="tool-page">
      <SeoHead
        title="GST Late Filing Penalty Calculator — Interest & Late Fees"
        description="Calculate GST late filing penalties instantly. Get exact late fees and interest for GSTR-1, GSTR-3B, GSTR-9 based on days of delay. Free, no login required."
        path="/penalty-calculator"
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">GST Penalty Calculator</h1>
          <p className="tool-subtitle">
            Calculate late filing penalties and interest for GST returns. No sign-up required.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Return Type
              <select
                className="calc-select"
                value={returnType}
                onChange={(e) => setReturnType(e.target.value)}
              >
                {RETURN_TYPES.map((r) => (
                  <option key={r.key} value={r.key}>{r.label}</option>
                ))}
              </select>
            </label>

            <label className="calc-label">
              Tax Liability (₹) — leave blank if nil
              <input
                type="number"
                className="calc-input"
                value={taxLiability}
                onChange={(e) => setTaxLiability(e.target.value)}
                placeholder="Enter tax liability amount"
                min="0"
                step="0.01"
                inputMode="decimal"
              />
            </label>

            <label className="calc-label">
              Due Date
              <input
                type="date"
                className="calc-input"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
              />
            </label>

            <label className="calc-label">
              Actual Filing Date
              <input
                type="date"
                className="calc-input"
                value={filingDate}
                onChange={(e) => setFilingDate(e.target.value)}
              />
            </label>

            {result && (
              <div className="calc-result" aria-live="polite">
                <div className="calc-result-row">
                  <span>Days of Delay</span>
                  <strong>{result.days} days</strong>
                </div>
                <div className="calc-result-row">
                  <span>Late Fee ({selectedReturn.lateFeePerDay}/day{selectedReturn.maxLateFee ? `, max ${formatINR(selectedReturn.maxLateFee)}` : ""})</span>
                  <strong>{formatINR(result.lateFee)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>Interest @ {INTEREST_RATE}% p.a.</span>
                  <strong>{formatINR(result.interest)}</strong>
                </div>
                <div className="calc-result-row calc-total">
                  <span>Total Penalty</span>
                  <strong>{formatINR(result.total)}</strong>
                </div>

                <div className="calc-result-actions">
                  <ShareButtons
                    path="/penalty-calculator"
                    text={`GST late filing penalty for ${selectedReturn.label}: ${formatINR(result.total)} (${result.days} days late) — calculated free on DoAide GST`}
                  />
                  <PrintButton label="Print Result" />
                </div>
              </div>
            )}
          </div>

          <EmailCapture
            source="penalty-calculator"
            heading="Never miss a GST deadline"
            subtext="Get free email reminders before every GST filing due date."
            buttonLabel="Remind Me"
            compact
          />

          <section className="tool-info">
            <h2>How GST Late Fees & Interest Work</h2>
            <p>
              Late filing of GST returns attracts two types of penalties:
            </p>
            <h3>Late Fee</h3>
            <ul>
              <li><strong>Regular returns (GSTR-1, GSTR-3B):</strong> ₹50/day (₹25 CGST + ₹25 SGST), maximum ₹10,000 per return</li>
              <li><strong>Nil returns:</strong> ₹20/day (₹10 CGST + ₹10 SGST), maximum ₹500 per return</li>
              <li><strong>Annual return (GSTR-9):</strong> ₹200/day (₹100 CGST + ₹100 SGST), no upper cap — capped at 0.5% of turnover in the state</li>
            </ul>
            <h3>Interest on Late Payment</h3>
            <ul>
              <li><strong>18% per annum</strong> on the outstanding tax liability</li>
              <li>Calculated from the day after the due date until the date of payment</li>
              <li>Interest is charged only on the net cash liability (after adjusting ITC)</li>
            </ul>
          </section>

          <section className="tool-info">
            <h2>Frequently Asked Questions</h2>

            <h3>What is the late fee for GSTR-3B?</h3>
            <p>
              The late fee for GSTR-3B is ₹50 per day (₹25 CGST + ₹25 SGST) for regular
              returns, maximum ₹10,000 per return. For nil returns, it is ₹20 per day,
              maximum ₹500.
            </p>

            <h3>What is the interest rate on late GST payment?</h3>
            <p>
              Interest on late payment is 18% per annum on the outstanding tax liability,
              calculated from the day after the due date until the date of payment. It applies
              only on the net cash liability after adjusting ITC.
            </p>

            <h3>Is there a maximum cap on GST late fees?</h3>
            <p>
              Yes — ₹10,000 for GSTR-1 and GSTR-3B, ₹500 for nil returns. GSTR-9 has no
              upper cap but is limited to 0.5% of turnover in the state.
            </p>

            <h3>How is GST penalty different from late fee?</h3>
            <p>
              Late fee is for delayed filing. Penalty (Sections 122-125) is for offences like
              tax evasion or incorrect invoicing — work it out with the{" "}
              <Link to="/gst-offence-penalty-calculator">offence penalty calculator</Link>.
              Interest is for late payment of tax. All three are separate charges.
            </p>

            <h3>Can GST late fee be waived?</h3>
            <p>
              The government periodically issues amnesty schemes waiving or reducing late
              fees. Check the latest CBIC notifications for ongoing waiver schemes for
              your return period.
            </p>
          </section>

          <InlineCTA variant="save" />
          <RelatedTools current="/penalty-calculator" />
          <CrossProductLinks page="penalty-calculator" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}
