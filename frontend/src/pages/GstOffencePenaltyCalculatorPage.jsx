import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import DoAideFooter from "../components/DoAideFooter";
import FaqSection, { faqSchema } from "../components/FaqSection";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { formatINR } from "../lib/gstCalc";
import { computeOffencePenalty, VIOLATIONS } from "../lib/gstOffencePenalties";

const PATH = "/gst-offence-penalty-calculator";

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST Penalty Calculator — Sections 122, 123 & 125",
  url: `https://gst.doaide.com${PATH}`,
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "GST Offence Penalty Calculator" },
];

const INPUT_LABELS = {
  tax: "Tax involved — CGST + SGST together, or IGST (₹)",
  refund: "Refund amount obtained (₹)",
  days: "Days the information return is late",
};

const FAQS = [
  {
    q: "What is the penalty for GST evasion under Section 122?",
    a: "The tax evaded or ₹10,000, whichever is higher. The SGST Act levies the same again, so an intra-state case pays at least ₹20,000 in all. Inter-state cases pay it once under the IGST Act.",
  },
  {
    q: "What is the penalty for issuing a fake GST invoice?",
    a: "Under Section 122(1)(ii), the tax on the invoice or ₹10,000 per Act, whichever is higher. Section 122(1A) adds the same penalty for anyone who arranged the invoice and kept the benefit.",
  },
  {
    q: "What is the penalty for not taking GST registration?",
    a: "Under Section 122(1)(xi), the tax evaded or ₹10,000 per Act, whichever is higher, on top of the unpaid tax and 18% interest.",
  },
  {
    q: "What is the general penalty under Section 125?",
    a: "Up to ₹25,000 under each Act for a breach with no penalty of its own, such as wrong invoice particulars. It is a ceiling, and the officer decides the amount.",
  },
  {
    q: "Is the penalty for an unfiled return the same as Section 122?",
    a: "No. A late or missing return attracts a late fee under Section 47, plus 18% interest on unpaid tax. Section 122 is for evasion and fraud.",
  },
  {
    q: "Can a GST penalty be waived or reduced?",
    a: "Section 126 bars a penalty for minor breaches, meaning tax under ₹5,000 or an easily corrected error made without fraud. Paying the tax and interest before a show cause notice also cuts the penalty sharply.",
  },
];

export default function GstOffencePenaltyCalculatorPage() {
  usePageTitle("GST Penalty Calculator — Sections 122, 123 & 125");
  const [violation, setViolation] = useState(VIOLATIONS[0].key);
  const [amount, setAmount] = useState("");
  const [interState, setInterState] = useState(false);

  const selected = VIOLATIONS.find((v) => v.key === violation);
  const result = useMemo(
    () => computeOffencePenalty({ violation, amount, interState }),
    [violation, amount, interState],
  );
  const invalid = selected.input && amount !== "" && result === null;

  return (
    <div className="tool-page">
      <SeoHead
        title="GST Penalty Calculator — Section 122, 123 & 125 Penalties"
        description="Calculate GST penalties for tax evasion, fake invoices, no registration, fraudulent refunds and wrong invoices under Sections 122, 123 and 125 of the CGST Act. Free."
        path={PATH}
        jsonLd={[TOOL_SCHEMA, faqSchema(FAQS)]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">GST Penalty Calculator</h1>
          <p className="tool-subtitle">
            The penalty for a GST offence under Sections 122, 123 and 125 of the CGST Act, split by
            Act, with the section it comes from. For a late return, use the{" "}
            <Link to="/late-fee-calculator">late fee calculator</Link>.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Violation
              <select
                className="calc-input"
                value={violation}
                onChange={(e) => {
                  setViolation(e.target.value);
                  setAmount("");
                }}
              >
                {VIOLATIONS.map((v) => (
                  <option key={v.key} value={v.key}>{v.label}</option>
                ))}
              </select>
            </label>
            <p className="calc-note">{selected.what}</p>

            {selected.input && (
              <label className="calc-label">
                {INPUT_LABELS[selected.input]}
                <input
                  type="number"
                  className="calc-input"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  placeholder={selected.input === "days" ? "e.g. 30" : "e.g. 250000"}
                  min="0"
                  inputMode="decimal"
                />
              </label>
            )}

            {selected.rule !== "lateFee" && (
              <label className="calc-checkbox-label">
                <input
                  type="checkbox"
                  checked={interState}
                  onChange={(e) => setInterState(e.target.checked)}
                />
                Inter-state supply (IGST)
              </label>
            )}

            {invalid && (
              <p className="calc-error" role="alert">
                Enter an amount of zero or more.
              </p>
            )}

            {result?.lateFee && (
              <div className="calc-result" aria-live="polite">
                <p>
                  A late or missing return is not a Section 122 penalty. It attracts a late fee
                  under <strong>Section 47</strong> — ₹50 a day for most returns, capped by
                  turnover — and 18% interest on any tax paid late. Work it out with the{" "}
                  <Link to="/late-fee-calculator">late fee calculator</Link> or the{" "}
                  <Link to="/gst-late-fee-interest-calculator">late fee + interest calculator</Link>.
                </p>
              </div>
            )}

            {result && !result.lateFee && (
              <div className="calc-result" aria-live="polite">
                {result.perAct.map((a) => (
                  <div className="calc-result-row" key={a.act}>
                    <span>Penalty under the {a.act}</span>
                    <strong>{result.upTo && "Up to "}{formatINR(a.penalty)}</strong>
                  </div>
                ))}
                <div className="calc-result-row calc-total">
                  <span>Total penalty</span>
                  <strong>{result.upTo && "Up to "}{formatINR(result.total)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>Provision</span>
                  <strong>{result.violation.section}, CGST Act</strong>
                </div>
                {result.floorApplied && (
                  <p>
                    The ₹10,000 minimum set the penalty here, not the amount — it applies under
                    each Act separately.
                  </p>
                )}
                {result.upTo && (
                  <p>This is the ceiling. The officer decides the actual amount up to it.</p>
                )}
                <p>
                  The penalty is in addition to the tax itself and 18% interest. See the{" "}
                  <Link to="/interest-calculator">interest calculator</Link>.
                </p>
                <div className="calc-result-actions">
                  <ShareButtons
                    path={PATH}
                    text={`GST penalty under ${result.violation.section}: ${result.upTo ? "up to " : ""}${formatINR(result.total)} — worked out free on DoAide GST`}
                    toolName="GST Penalty Calculator"
                  />
                </div>
              </div>
            )}
          </div>

          <section className="tool-info">
            <h2>GST penalties at a glance</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Offence</th>
                    <th>Section</th>
                    <th>Penalty per Act</th>
                  </tr>
                </thead>
                <tbody>
                  <tr><td>Tax evasion, wrong ITC, fake or missing invoice, no registration</td><td>122(1)</td><td>Tax involved or ₹10,000, whichever is higher</td></tr>
                  <tr><td>Refund obtained fraudulently</td><td>122(1)(viii)</td><td>Refund or ₹10,000, whichever is higher</td></tr>
                  <tr><td>Information return not furnished</td><td>123</td><td>₹100 a day, up to ₹5,000</td></tr>
                  <tr><td>Any breach with no penalty of its own</td><td>125</td><td>Up to ₹25,000</td></tr>
                  <tr><td>Return filed late</td><td>47 (late fee)</td><td>See the <Link to="/late-fee-calculator">late fee calculator</Link></td></tr>
                </tbody>
              </table>
            </div>
            <p>
              Each figure applies under the CGST Act and again under the SGST/UTGST Act, so an
              intra-state case pays it twice. Inter-state cases pay it once under the IGST Act.
              Check whether you needed to register with the{" "}
              <Link to="/registration-checker">registration checker</Link>, and pay any tax due
              through <Link to="/payment-challan">PMT-06</Link>.
            </p>
          </section>

          <FaqSection faqs={FAQS} />

          <RelatedTools current={PATH} />
        </div>
      </main>
      <DoAideFooter />
    </div>
  );
}

export { FAQS };
