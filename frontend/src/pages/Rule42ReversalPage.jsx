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
import { NON_BUSINESS_SHARE, computeRule42 } from "../lib/rule42";

const PATH = "/itc-reversal-rule-42";

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "Rule 42 ITC Reversal Calculator",
  url: `https://gst.doaide.com${PATH}`,
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "Rule 42 ITC Reversal Calculator" },
];

const ERRORS = {
  negative: "Enter amounts of zero or more.",
  "parts-exceed-total": "The credit you have set aside for specific uses is more than the total credit. Check the first five boxes.",
  "no-turnover": "Enter total turnover for the period. If you had none, use the figures from the last period that had turnover.",
  "exempt-exceeds-total": "Exempt turnover cannot be more than total turnover.",
};

const FAQS = [
  {
    q: "When does Rule 42 apply?",
    a: "When inputs or input services are used both for taxable supplies and for exempt supplies or non-business purposes. A business that makes only taxable supplies has no common credit to reverse.",
  },
  {
    q: "What counts as exempt turnover for Rule 42?",
    a: "Nil-rated, wholly exempt and non-GST supplies, and supplies on which the recipient pays tax under reverse charge. Interest on deposits and loans is left out unless you are a bank or NBFC.",
  },
  {
    q: "Is the Rule 42 reversal done every month?",
    a: "Yes, provisionally, using that month's turnover. After the year ends you redo it on the full-year turnover. Report any shortfall by the September return of the next year, with interest.",
  },
  {
    q: "Where is the Rule 42 reversal shown in GSTR-3B?",
    a: "In Table 4(B)(1), along with Rule 43 and section 17(5) reversals. It is a permanent reversal, so it is not reclaimed later the way a Rule 37 reversal is.",
  },
  {
    q: "Does Rule 42 cover capital goods?",
    a: "No. Common credit on capital goods is apportioned under Rule 43, spread over a useful life of five years. This calculator handles inputs and input services only.",
  },
];

const FIELDS = [
  ["total", "T — Total ITC on inputs and input services for the period"],
  ["nonBusiness", "T1 — Used only for non-business purposes"],
  ["exemptOnly", "T2 — Used only for exempt supplies"],
  ["blocked", "T3 — Blocked under section 17(5)"],
  ["taxableOnly", "T4 — Used only for taxable supplies (including exports)"],
  ["exemptTurnover", "E — Exempt turnover for the period"],
  ["totalTurnover", "F — Total turnover for the period"],
];

export default function Rule42ReversalPage() {
  usePageTitle("Rule 42 ITC Reversal Calculator — Common Credit Apportionment");
  const [values, setValues] = useState({});
  const [nonBusinessUse, setNonBusinessUse] = useState(false);

  const set = (key) => (e) => setValues((v) => ({ ...v, [key]: e.target.value }));
  const result = useMemo(
    () => (values.total ? computeRule42({ ...values, commonUsedForNonBusiness: nonBusinessUse }) : null),
    [values, nonBusinessUse],
  );

  return (
    <div className="tool-page">
      <SeoHead
        title="Rule 42 ITC Reversal Calculator — Common Credit on Exempt Supplies"
        description="Calculate ITC reversal under Rule 42 of the CGST Rules: C1, C2, D1, D2 and C3 worked out from your exempt and total turnover. Free, no login."
        path={PATH}
        jsonLd={[TOOL_SCHEMA, faqSchema(FAQS)]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">Rule 42 ITC Reversal Calculator</h1>
          <p className="tool-subtitle">
            If you make both taxable and exempt supplies, part of your common input tax credit has
            to be reversed every month. Enter the period&apos;s figures to see how much.
          </p>

          <div className="calc-card">
            {FIELDS.map(([key, label]) => (
              <label className="calc-label" key={key}>
                {label} (₹)
                <input
                  type="number"
                  className="calc-input"
                  value={values[key] ?? ""}
                  onChange={set(key)}
                  placeholder="0"
                  min="0"
                  inputMode="decimal"
                />
              </label>
            ))}

            <label className="calc-checkbox-label">
              <input
                type="checkbox"
                checked={nonBusinessUse}
                onChange={(e) => setNonBusinessUse(e.target.checked)}
              />{" "}
              Common inputs are also used partly for non-business purposes
            </label>

            {result?.error && (
              <p className="calc-error" role="alert">
                {ERRORS[result.error]}
              </p>
            )}

            {result && !result.error && (
              <div className="calc-result" aria-live="polite">
                <div className="calc-result-row">
                  <span>C1 — Credit taken to the ledger</span>
                  <strong>{formatINR(result.C1)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>C2 — Common credit</span>
                  <strong>{formatINR(result.C2)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>D1 — Exempt share ({(result.exemptRatio * 100).toFixed(2)}% of C2)</span>
                  <strong>{formatINR(result.D1)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>D2 — Non-business share ({NON_BUSINESS_SHARE}% of C2)</span>
                  <strong>{formatINR(result.D2)}</strong>
                </div>
                <div className="calc-result-row calc-total">
                  <span>ITC to reverse (D1 + D2)</span>
                  <strong>{formatINR(result.reversal)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>C3 — Common credit you keep</span>
                  <strong>{formatINR(result.C3)}</strong>
                </div>
                <div className="calc-result-row calc-total">
                  <span>Eligible ITC for the period (T4 + C3)</span>
                  <strong>{formatINR(result.eligible)}</strong>
                </div>
                <p>
                  Report {formatINR(result.reversal)} in GSTR-3B Table 4(B)(1). The{" "}
                  {formatINR(result.notCredited)} in T1, T2 and T3 is never credited in the first
                  place.
                </p>
                <div className="calc-result-actions">
                  <ShareButtons
                    path={PATH}
                    text={`Rule 42 ITC reversal worked out in seconds: ${formatINR(result.reversal)} — free on DoAide GST`}
                    toolName="Rule 42 ITC Reversal Calculator"
                  />
                </div>
              </div>
            )}
          </div>

          <section className="tool-info">
            <h2>How the Rule 42 formula works</h2>
            <ol>
              <li>Take out credit that was never yours to keep: non-business (T1), exempt-only (T2) and <Link to="/input-tax-credit">blocked under 17(5)</Link> (T3). What remains is C1.</li>
              <li>Take out credit used only for taxable supplies (T4). It is kept in full. What remains, C2, is the common credit.</li>
              <li>Reverse the exempt share of C2 in proportion to turnover: D1 = E ÷ F × C2.</li>
              <li>If common inputs also serve non-business use, reverse a flat 5% of C2 as D2.</li>
              <li>Repeat on full-year figures after 31 March, and settle the difference by the September return.</li>
            </ol>
            <p>
              Working out the year-end figures? The <Link to="/gstr9-summary">GSTR-9 summary</Link> and{" "}
              <Link to="/itc-reconciliation-dashboard">ITC dashboard</Link> show the year in one view.
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
