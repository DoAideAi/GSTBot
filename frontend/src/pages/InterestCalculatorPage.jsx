import { useMemo, useState } from "react";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import FaqSection, { faqSchema } from "../components/FaqSection";
import EmailCapture from "../components/EmailCapture";
import PrintButton from "../components/PrintButton";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { formatINR } from "../lib/gstCalc";

const INTEREST_SCENARIOS = [
  { key: "late_payment", label: "Late payment of tax (Section 50(1))", rate: 18 },
  { key: "excess_itc", label: "ITC wrongly availed and utilised (Section 50(3))", rate: 18 },
  { key: "undue_refund", label: "Undue or excess refund (Section 50(1))", rate: 18 },
];

function daysBetween(from, to) {
  const ms = to.getTime() - from.getTime();
  return Math.max(0, Math.ceil(ms / 86400000));
}

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST Interest Calculator",
  url: "https://gst.doaide.com/interest-calculator",
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const HOWTO_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "HowTo",
  name: "How to calculate interest on late GST payment",
  description: "Work out the Section 50 interest on tax paid after the due date.",
  step: [
    { "@type": "HowToStep", name: "Enter the tax amount", text: "The tax that was paid late in cash — what is set off against credit carries no interest." },
    { "@type": "HowToStep", name: "Enter the days of delay", text: "From the due date until the payment date." },
    { "@type": "HowToStep", name: "Read the interest", text: "18% per annum, computed day-wise: tax × 18% × days ÷ 365." },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "Interest Calculator" },
];

const FAQS = [
  {
    q: "What is the interest rate on late GST payment?",
    a: "Under Section 50(1), 18% a year on tax paid late, from the day after the due date to the day of payment. Under Section 50(3), wrongly availed ITC that was used attracts 24% a year.",
  },
  {
    q: "Is GST interest charged on the gross or the net tax liability?",
    a: "On the net liability: the part paid in cash after setting off ITC. This applies retrospectively from 1 July 2017, unless the return is filed after Section 73 or 74 proceedings have begun.",
  },
  {
    q: "How is GST interest calculated?",
    a: "Interest = tax paid late × 18% × days of delay ÷ 365. For example, ₹1,00,000 paid 30 days late carries interest of about ₹1,479.",
  },
  {
    q: "How do I pay GST interest?",
    a: "In cash from the electronic cash ledger; ITC cannot be used. It is usually declared in the interest and late fee table of GSTR-3B, or paid separately through Form DRC-03.",
  },
];

export default function InterestCalculatorPage() {
  usePageTitle("GST Interest Calculator — Late Payment Interest under Section 50");

  const [scenario, setScenario] = useState("late_payment");
  const [taxAmount, setTaxAmount] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [paymentDate, setPaymentDate] = useState("");

  const selected = INTEREST_SCENARIOS.find((s) => s.key === scenario);

  const result = useMemo(() => {
    if (!dueDate || !paymentDate || !selected) return null;
    const amount = parseFloat(taxAmount);
    if (!Number.isFinite(amount) || amount <= 0) return null;

    const due = new Date(dueDate);
    const paid = new Date(paymentDate);
    if (isNaN(due) || isNaN(paid)) return null;

    const days = daysBetween(due, paid);
    if (days <= 0) return null;

    const interest = Math.round(amount * (selected.rate / 100) * (days / 365) * 100) / 100;
    const monthlyBreakdown = [];
    let remaining = days;
    const current = new Date(due);

    while (remaining > 0) {
      const monthEnd = new Date(current.getFullYear(), current.getMonth() + 1, 0);
      const daysInThisPeriod = Math.min(
        remaining,
        Math.ceil((monthEnd - current) / 86400000) + 1,
      );
      const periodInterest = Math.round(amount * (selected.rate / 100) * (daysInThisPeriod / 365) * 100) / 100;
      monthlyBreakdown.push({
        period: current.toLocaleDateString("en-IN", { month: "short", year: "numeric" }),
        days: daysInThisPeriod,
        interest: periodInterest,
      });
      remaining -= daysInThisPeriod;
      current.setMonth(current.getMonth() + 1);
      current.setDate(1);
    }

    return { days, interest, rate: selected.rate, amount, monthlyBreakdown };
  }, [scenario, taxAmount, dueDate, paymentDate, selected]);

  return (
    <div className="tool-page">
      <SeoHead
        title="GST Interest Calculator — Late Payment Interest under Section 50"
        description="Calculate interest on late GST payment under Section 50. 18% p.a. on late tax and on wrongly utilised ITC (the old 24% ended in July 2022). Free, no login required."
        path="/interest-calculator"
        jsonLd={[TOOL_SCHEMA, HOWTO_SCHEMA, faqSchema(FAQS)]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb items={[{ label: "Home", to: "/" }, { label: "Interest Calculator" }]} />
          <h1 className="tool-title">GST Interest Calculator</h1>
          <p className="tool-subtitle">
            Calculate interest on late GST payment under Section 50. No sign-up required.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Scenario
              <select
                className="calc-select"
                value={scenario}
                onChange={(e) => setScenario(e.target.value)}
              >
                {INTEREST_SCENARIOS.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.label} — {s.rate}% p.a.
                  </option>
                ))}
              </select>
            </label>

            <label className="calc-label">
              Tax Amount (₹)
              <input
                type="number"
                className="calc-input"
                value={taxAmount}
                onChange={(e) => setTaxAmount(e.target.value)}
                placeholder="Enter outstanding tax amount"
                min="0"
                step="0.01"
                inputMode="decimal"
                autoFocus
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
              Payment Date
              <input
                type="date"
                className="calc-input"
                value={paymentDate}
                onChange={(e) => setPaymentDate(e.target.value)}
              />
            </label>

            {result && (
              <div className="calc-result" aria-live="polite">
                <div className="calc-result-row">
                  <span>Tax Amount</span>
                  <strong>{formatINR(result.amount)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>Delay Period</span>
                  <strong>{result.days} days</strong>
                </div>
                <div className="calc-result-row">
                  <span>Interest Rate</span>
                  <strong>{result.rate}% p.a.</strong>
                </div>
                <div className="calc-result-row calc-total">
                  <span>Interest Payable</span>
                  <strong>{formatINR(result.interest)}</strong>
                </div>

                {result.monthlyBreakdown.length > 1 && (
                  <details style={{ marginTop: "0.75rem" }}>
                    <summary style={{ cursor: "pointer", fontSize: "0.9rem", fontWeight: 600 }}>
                      Month-wise Breakdown
                    </summary>
                    <table className="calendar-table" style={{ marginTop: "0.5rem" }}>
                      <thead>
                        <tr>
                          <th>Period</th>
                          <th>Days</th>
                          <th>Interest</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.monthlyBreakdown.map((m, i) => (
                          <tr key={i}>
                            <td>{m.period}</td>
                            <td>{m.days}</td>
                            <td>{formatINR(m.interest)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </details>
                )}

                <div className="calc-result-actions">
                  <ShareButtons
                    path="/interest-calculator"
                    text={`GST interest on ${formatINR(result.amount)} for ${result.days} days: ${formatINR(result.interest)} — calculated free on DoAide GST`}
                  />
                  <PrintButton label="Print Result" />
                </div>
              </div>
            )}
          </div>

          <EmailCapture
            source="interest-calculator"
            heading="Avoid GST interest penalties"
            subtext="Get free email reminders before every GST filing deadline."
            buttonLabel="Remind Me"
            compact
          />

          <section className="tool-info">
            <h2>GST Interest Under Section 50</h2>
            <p>
              When GST is paid after the due date, interest is charged on the outstanding
              amount from the day after the due date until the date of actual payment.
            </p>
            <h3>Interest Rates</h3>
            <ul>
              <li><strong>18% per annum</strong> — on late payment of tax (Section 50(1)). Calculated on net cash liability after adjusting ITC.</li>
              <li><strong>18% per annum</strong> — on ITC wrongly availed <em>and utilised</em> (Section 50(3)). This was 24% until 5 July 2022 (Notification 14/2022-CT); credit that was claimed but never used attracts no interest.</li>
            </ul>
            <h3>Key Points</h3>
            <ul>
              <li>Interest is calculated on a per-day basis from the day after the due date</li>
              <li>Since the Chhattisgarh HC ruling, interest is charged on net cash liability (after ITC offset), not on gross liability</li>
              <li>Interest must be paid along with the late return or through DRC-03</li>
              <li>Interest is automatic — the portal calculates and adds it when you file late</li>
            </ul>
          </section>

          <InlineCTA variant="save" />
          <FaqSection faqs={FAQS} />

          <RelatedTools current="/interest-calculator" />
          <CrossProductLinks page="interest-calculator" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}
