import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
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
import { calculateLateFee, CRORE, daysLate, LATE_FEE_RETURNS, LATE_FEE_TABLE } from "../lib/gstPenalties";

const RETURN_TYPES = LATE_FEE_RETURNS;

// Representative turnover for each band the caps are keyed on.
const TURNOVER_BANDS = [
  { value: 1 * CRORE, label: "Up to ₹1.5 crore" },
  { value: 3 * CRORE, label: "₹1.5 – ₹5 crore" },
  { value: 10 * CRORE, label: "₹5 – ₹20 crore" },
  { value: 25 * CRORE, label: "Above ₹20 crore" },
];

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST Late Fee Calculator",
  url: "https://gst.doaide.com/late-fee-calculator",
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
      name: "What is the late fee for filing GSTR-3B after the due date?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "₹50/day (₹25 CGST + ₹25 SGST), capped by last year's aggregate turnover: ₹2,000 up to ₹1.5 crore, ₹5,000 for ₹1.5–5 crore and ₹10,000 above ₹5 crore. Nil returns: ₹20/day, max ₹500.",
      },
    },
    {
      "@type": "Question",
      name: "Is there a cap on GST late fees?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes. GSTR-1/3B: ₹2,000, ₹5,000 or ₹10,000 by turnover band (Notifications 19 and 20/2021-CT); nil returns ₹500. GSTR-4: ₹2,000 (₹500 nil). GSTR-9: 0.04% of state turnover up to ₹20 crore, 0.5% above.",
      },
    },
    {
      "@type": "Question",
      name: "What is the late fee for GSTR-9?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "From FY 2022-23 (Notification 7/2023-CT): ₹50/day capped at 0.04% of state turnover for aggregate turnover up to ₹5 crore, ₹100/day capped at 0.04% for ₹5–20 crore, and ₹200/day capped at 0.5% above ₹20 crore.",
      },
    },
    {
      "@type": "Question",
      name: "Can late fees be waived by the government?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes. The government has issued amnesty schemes waiving or reducing late fees for delayed returns.",
      },
    },
  ],
};

const HOWTO_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "HowTo",
  name: "How to calculate GST late filing fees",
  description: "Work out the late fee for a delayed GSTR-1, GSTR-3B, GSTR-9 or GSTR-4, with the CGST/SGST split and statutory caps.",
  step: [
    { "@type": "HowToStep", name: "Pick the return", text: "Each return has its own daily fee and cap." },
    { "@type": "HowToStep", name: "Enter the days late", text: "From the due date to the day you will actually file." },
    { "@type": "HowToStep", name: "Mark a nil return", text: "Nil returns carry a lower daily fee." },
    { "@type": "HowToStep", name: "Read the fee", text: "Daily fee times days, capped by turnover rules, split equally into CGST and SGST." },
  ],
};

export default function LateFeeCalculatorPage() {
  usePageTitle("GST Late Fee Calculator — Free Online | DoAide GST");

  const [returnType, setReturnType] = useState("gstr3b");
  const [isNil, setIsNil] = useState(false);
  const [dueDate, setDueDate] = useState("");
  const [filingDate, setFilingDate] = useState("");
  const [turnover, setTurnover] = useState("");
  const [aato, setAato] = useState(TURNOVER_BANDS[0].value);

  const result = useMemo(() => {
    if (!dueDate || !filingDate) return null;
    const days = daysLate(dueDate, filingDate);
    if (days === 0) return { days: 0, lateFee: 0, cgst: 0, sgst: 0 };
    const fee = calculateLateFee(returnType, days, {
      nil: isNil && returnType !== "gstr9",
      aato,
      stateTurnover: parseFloat(turnover) || 0,
    });
    return { days, lateFee: fee.fee, cgst: fee.cgst, sgst: fee.sgst, perDay: fee.perDay, basis: fee.basis };
  }, [returnType, isNil, dueDate, filingDate, turnover, aato]);

  return (
    <div className="tool-page">
      <SeoHead
        title="GST Late Fee Calculator — Free Online | DoAide GST"
        description="Calculate GST late filing fees for GSTR-1, GSTR-3B, GSTR-9 and GSTR-4. Get CGST & SGST breakup with daily penalty, caps, and nil return rates."
        path="/late-fee-calculator"
        jsonLd={[TOOL_SCHEMA, HOWTO_SCHEMA, FAQ_SCHEMA]}
      />
      <ToolsNav />
      <Breadcrumb
        items={[
          { label: "Home", to: "/" },
          { label: "Free Tools", to: "/resources" },
          { label: "Late Fee Calculator" },
        ]}
      />

      <main className="tool-main">
        <div className="tool-container">
          <h1 className="tool-title">GST Late Fee Calculator</h1>
          <p className="tool-subtitle">
            Late filing fees for GSTR-3B, GSTR-1, GSTR-4 &amp; GSTR-9 with the turnover-based caps in force. Need interest too? Use the <Link to="/gst-late-fee-interest-calculator">late fee + interest calculator</Link>.
          </p>

          <div className="calc-card">
            <div className="calc-grid">
              <div className="field">
                <label>Return Type</label>
                <select value={returnType} onChange={(e) => setReturnType(e.target.value)}>
                  {RETURN_TYPES.map((r) => (
                    <option key={r.key} value={r.key}>{r.label}</option>
                  ))}
                </select>
              </div>

              <div className="field">
                <label htmlFor="late-fee-aato">Aggregate Turnover (previous FY)</label>
                <select id="late-fee-aato" value={aato} onChange={(e) => setAato(Number(e.target.value))}>
                  {TURNOVER_BANDS.map((b) => (
                    <option key={b.value} value={b.value}>{b.label}</option>
                  ))}
                </select>
              </div>

              {returnType !== "gstr9" && (
                <div className="field">
                  <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
                    <input type="checkbox" checked={isNil} onChange={(e) => setIsNil(e.target.checked)} />
                    Nil return (no tax liability)
                  </label>
                </div>
              )}

              <div className="field">
                <label>Due Date</label>
                <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
              </div>

              <div className="field">
                <label>Filing Date</label>
                <input type="date" value={filingDate} onChange={(e) => setFilingDate(e.target.value)} />
              </div>

              {returnType === "gstr9" && (
                <div className="field">
                  <label>Annual State Turnover (₹)</label>
                  <input
                    type="number"
                    min="0"
                    placeholder="e.g. 5000000"
                    value={turnover}
                    onChange={(e) => setTurnover(e.target.value)}
                  />
                  <small style={{ color: "var(--ink-soft)", fontSize: "0.75rem" }}>Sets the cap: 0.04% of state turnover (0.5% above ₹20 crore)</small>
                </div>
              )}
            </div>
          </div>

          {result && (
            <div className="calc-card" style={{ marginTop: "1rem" }}>
              <h2 style={{ margin: "0 0 1rem" }}>Late Fee Calculation</h2>
              {result.days === 0 ? (
                <p style={{ color: "#34d399", fontWeight: 500, margin: 0 }}>Filed on time — no late fee applicable.</p>
              ) : (
                <>
                  <div className="calc-result-grid">
                    <div className="calc-result-row">
                      <span>Days Late</span>
                      <strong>{result.days} days</strong>
                    </div>
                    <div className="calc-result-row">
                      <span>Rate per Day</span>
                      <strong>{formatINR(result.perDay)}</strong>
                    </div>
                    <div className="calc-result-row calc-result-highlight">
                      <span>Total Late Fee</span>
                      <strong>{formatINR(result.lateFee)}</strong>
                    </div>
                    <div className="calc-result-row">
                      <span>CGST Late Fee</span>
                      <strong>{formatINR(result.cgst)}</strong>
                    </div>
                    <div className="calc-result-row">
                      <span>SGST Late Fee</span>
                      <strong>{formatINR(result.sgst)}</strong>
                    </div>
                  </div>
                  <p className="calc-note">{result.basis}.</p>
                  <div className="calc-result-actions">
                    <PrintButton />
                    <ShareButtons title="GST Late Fee Calculator" url="https://gst.doaide.com/late-fee-calculator" />
                  </div>
                </>
              )}
            </div>
          )}

          <section className="tool-info">
            <h2>GST Late Fee Rates — Quick Reference</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Return &amp; turnover</th>
                    <th>Per day</th>
                    <th>Max Cap</th>
                  </tr>
                </thead>
                <tbody>
                  {LATE_FEE_TABLE.map((r) => (
                    <tr key={r.ret}>
                      <td>{r.ret}</td>
                      <td>{formatINR(r.perDay)}</td>
                      <td>{r.cap}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {result && result.days > 0 && (
            <SaveResultsCTA resultSummary={`GST Late Fee: ${formatINR(result.lateFee)} (${result.days} days late) for ${RETURN_TYPES.find(r => r.key === returnType)?.label}`} />
          )}
          <EmailCapture context="late-fee-calculator" />
          <InlineCTA variant="remind" />
          <RelatedTools
            current="/late-fee-calculator"
            tools={[
              { to: "/penalty-calculator", label: "Penalty Calculator" },
              { to: "/interest-calculator", label: "Interest Calculator" },
              { to: "/return-calendar", label: "Return Calendar" },
              { to: "/due-dates", label: "Due Dates" },
            ]}
          />
          <CrossProductLinks />
          <DoAideFooter />
          <StickyMobileCTA />
          <ExitIntentPopup />
        </div>
      </main>
    </div>
  );
}
