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
import { calculateInterest, calculateLateFee, daysLate, INTEREST_RATE } from "../lib/gstPenalties";

// The fee arithmetic is lib/gstPenalties.js, shared with /late-fee-calculator.
// This page used to carry its own table, with a flat ₹10,000 cap on GSTR-1/3B
// and GSTR-9 at ₹200 a day without limit — both superseded in 2021 and 2023.
const RETURN_TYPES = [
  { key: "gstr1", label: "GSTR-1", ret: "gstr1", nil: false },
  { key: "gstr3b", label: "GSTR-3B", ret: "gstr3b", nil: false },
  { key: "gstr3b_nil", label: "GSTR-3B (Nil Return)", ret: "gstr3b", nil: true },
  { key: "gstr1_nil", label: "GSTR-1 (Nil Return)", ret: "gstr1", nil: true },
  { key: "gstr9", label: "GSTR-9 (Annual)", ret: "gstr9", nil: false },
];

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
        text: "₹50/day (₹25 CGST + ₹25 SGST), capped by last year's turnover: ₹2,000 up to ₹1.5 crore, ₹5,000 up to ₹5 crore, ₹10,000 above. Nil returns: ₹20/day, max ₹500.",
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
        text: "Yes. GSTR-1/3B: ₹2,000, ₹5,000 or ₹10,000 by turnover; nil returns ₹500. GSTR-9 from FY 2022-23: ₹50 to ₹200 a day by turnover, capped at 0.04% of state turnover, or 0.5% above ₹20 crore.",
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
  const [turnover, setTurnover] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [filingDate, setFilingDate] = useState("");

  const selectedReturn = RETURN_TYPES.find((r) => r.key === returnType);

  const result = useMemo(() => {
    if (!dueDate || !filingDate) return null;
    const days = daysLate(dueDate, filingDate);
    if (days <= 0) return null;

    // Turnover sets the GSTR-1/3B cap band and, for GSTR-9, the cap itself
    // (the state turnover, which is the aggregate for a single registration).
    const t = parseFloat(turnover) || 0;
    const fee = calculateLateFee(selectedReturn.ret, days, { nil: selectedReturn.nil, aato: t, stateTurnover: t });
    const interest = selectedReturn.nil ? 0 : calculateInterest(parseFloat(taxLiability) || 0, days);

    return { days, fee, interest, total: fee.fee + interest };
  }, [taxLiability, turnover, dueDate, filingDate, selectedReturn]);

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
              Aggregate turnover in the previous FY (₹) — sets the cap
              <input
                type="number"
                className="calc-input"
                value={turnover}
                onChange={(e) => setTurnover(e.target.value)}
                placeholder="e.g. 12000000"
                min="0"
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
                  <span>Late Fee ({formatINR(result.fee.perDay)}/day{result.fee.cap !== null ? `, max ${formatINR(result.fee.cap)}` : ""})</span>
                  <strong>{formatINR(result.fee.fee)}</strong>
                </div>
                <p className="calc-note">
                  {result.fee.basis}.
                  {result.fee.cap === null && " Enter turnover to apply the GSTR-9 cap."}
                </p>
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
              <li><strong>Regular returns (GSTR-1, GSTR-3B):</strong> ₹50/day (₹25 CGST + ₹25 SGST), capped at ₹2,000 for turnover up to ₹1.5 crore, ₹5,000 up to ₹5 crore and ₹10,000 above</li>
              <li><strong>Nil returns:</strong> ₹20/day (₹10 CGST + ₹10 SGST), maximum ₹500 per return</li>
              <li><strong>Annual return (GSTR-9):</strong> ₹50/day up to ₹5 crore turnover and ₹100/day up to ₹20 crore, capped at 0.04% of state turnover; ₹200/day above ₹20 crore, capped at 0.5%</li>
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
              The late fee for GSTR-3B is ₹50 per day (₹25 CGST + ₹25 SGST), capped by the
              previous year&apos;s turnover: ₹2,000 up to ₹1.5 crore, ₹5,000 up to ₹5 crore and
              ₹10,000 above. For nil returns, it is ₹20 per day, maximum ₹500.
            </p>

            <h3>What is the interest rate on late GST payment?</h3>
            <p>
              Interest on late payment is 18% per annum on the outstanding tax liability,
              calculated from the day after the due date until the date of payment. It applies
              only on the net cash liability after adjusting ITC.
            </p>

            <h3>Is there a maximum cap on GST late fees?</h3>
            <p>
              Yes. GSTR-1 and GSTR-3B are capped at ₹2,000, ₹5,000 or ₹10,000 by turnover, and
              nil returns at ₹500. GSTR-9 from FY 2022-23 is capped at 0.04% of state turnover, or
              0.5% above ₹20 crore. The{" "}
              <Link to="/late-fee-calculator">late fee calculator</Link> has the full table.
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
