import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import PrintButton from "../components/PrintButton";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { LOWER_LIMIT_STATES, turnoverLimit } from "../lib/compositionTax";
import { formatINR } from "../lib/gstCalc";
import { STATE_CODES } from "../lib/stateCodes";
import WhatsAppFloat from "../components/WhatsAppFloat";
import { track } from "../lib/track";

const BUSINESS_TYPES = [
  { key: "manufacturer", label: "Manufacturer / Trader", compRate: 1 },
  { key: "restaurant", label: "Restaurant (not serving alcohol)", compRate: 5 },
  { key: "service", label: "Service Provider", compRate: 6 },
];

// Codes 25 and 28 survive only on old GSTINs, and 97/99 carry no state tax, so
// none of them is a place a new composition registration can be taken in.
const STATES = STATE_CODES.filter((s) => s.tax && s.code !== "25" && s.code !== "28");

// 40 is GST 2.0's slab (from 22 September 2025); 12 and 28 stay for supplies before it.
const GST_RATES = [5, 12, 18, 28, 40];

const FEATURES = [
  { feature: "Input Tax Credit", regular: "Available", composition: "Not available" },
  { feature: "Interstate Supply", regular: "Allowed", composition: "Not allowed" },
  { feature: "E-commerce Supply", regular: "Allowed", composition: "Not allowed" },
  { feature: "Filing Frequency", regular: "Monthly / Quarterly", composition: "Quarterly (CMP-08)" },
  { feature: "Invoicing", regular: "Can charge GST on invoice", composition: "Cannot charge GST" },
  { feature: "Turnover Limit", regular: "No limit", composition: "₹1.5 Cr (₹75 L in 8 states) / ₹50 L services" },
  { feature: "Annual Return", regular: "GSTR-9", composition: "GSTR-4" },
];

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST Scheme Comparison Calculator",
  url: "https://gst.doaide.com/scheme-comparison",
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
      name: "What is the difference between Regular and Composition GST scheme?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Regular scheme charges standard GST rates with ITC on purchases. Composition charges a flat lower rate (1-6%) but no ITC, no interstate sales, and no GST on invoices.",
      },
    },
    {
      "@type": "Question",
      name: "Who is eligible for the Composition Scheme?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Businesses with turnover up to ₹1.5 crore (₹50 lakh for services) can opt in. Ice cream, tobacco, and pan masala makers, interstate suppliers, and casual taxable persons are not eligible.",
      },
    },
    {
      "@type": "Question",
      name: "Does the composition turnover limit depend on the state?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes, for goods. Arunachal Pradesh, Manipur, Meghalaya, Mizoram, Nagaland, Sikkim, Tripura and Uttarakhand cap it at ₹75 lakh. The ₹50 lakh services limit is the same everywhere.",
      },
    },
    {
      "@type": "Question",
      name: "Which scheme saves more tax — Regular or Composition?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "It depends on your purchase-to-sales ratio. High purchases favour Regular (ITC savings). Low purchases favour Composition (flat low rate). Use this calculator to compare.",
      },
    },
    {
      "@type": "Question",
      name: "Can I switch from Composition to Regular scheme?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes. File Form GST CMP-04 to switch to Regular at any time. Switching to Composition requires filing CMP-02 before March 31 and takes effect from the next financial year.",
      },
    },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "Scheme Comparison" },
];

export default function SchemeComparisonPage() {
  usePageTitle("GST Scheme Comparison — Regular vs Composition Calculator");

  const [turnover, setTurnover] = useState("");
  const [purchases, setPurchases] = useState("");
  const [bizType, setBizType] = useState("manufacturer");
  const [gstRate, setGstRate] = useState(18);
  const [stateCode, setStateCode] = useState("27");

  const selectedBiz = BUSINESS_TYPES.find((b) => b.key === bizType);
  const selectedState = STATES.find((s) => s.code === stateCode);
  const limit = turnoverLimit(bizType, LOWER_LIMIT_STATES.includes(selectedState.name));

  const result = useMemo(() => {
    const t = parseFloat(turnover);
    const p = parseFloat(purchases);
    if (!Number.isFinite(t) || t <= 0 || !selectedBiz) return null;
    const pVal = Number.isFinite(p) && p >= 0 ? p : 0;

    const outputTax = Math.round(t * (gstRate / 100) * 100) / 100;
    const itc = Math.round(pVal * (gstRate / 100) * 100) / 100;
    const regularTax = Math.max(0, Math.round((outputTax - itc) * 100) / 100);
    const compositionTax = Math.round(t * (selectedBiz.compRate / 100) * 100) / 100;
    const savings = Math.round((regularTax - compositionTax) * 100) / 100;
    const overLimit = t > limit;

    track("scheme_comparison", { turnover: t, bizType, state: stateCode });

    return { regularTax, compositionTax, outputTax, itc, savings, overLimit };
  }, [turnover, purchases, bizType, gstRate, selectedBiz, limit, stateCode]);

  // Composition tax is intra-state only, so it always splits evenly between
  // CGST and the state's own levy; regular output tax is shown the same way
  // because a composition-eligible business sells within its state.
  const localTax = selectedState.tax;

  const maxBar = result ? Math.max(result.regularTax, result.compositionTax, 1) : 1;

  return (
    <div className="tool-page">
      <SeoHead
        title="GST Scheme Comparison Calculator — Regular vs Composition"
        description="Compare GST tax under Composition vs Regular scheme by turnover, business type and state — 1%, 5% or 6% flat rate against output tax less ITC. Free, no sign-up."
        path="/scheme-comparison"
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">GST Scheme Comparison Calculator</h1>
          <p className="tool-subtitle">
            Compare tax liability under Regular vs Composition scheme. No sign-up required.
          </p>

          <div className="how-it-works">
            <h2 className="how-it-works-title">How It Works</h2>
            <div className="how-it-works-steps">
              <div className="how-it-works-step">
                <div className="how-it-works-num">1</div>
                <h3>Enter Details</h3>
                <p>Enter your annual turnover, purchases, and business type</p>
              </div>
              <div className="how-it-works-step">
                <div className="how-it-works-num">2</div>
                <h3>Compare Schemes</h3>
                <p>See tax liability under both Regular and Composition schemes</p>
              </div>
              <div className="how-it-works-step">
                <div className="how-it-works-num">3</div>
                <h3>Make a Decision</h3>
                <p>Choose the scheme that saves you more money</p>
              </div>
            </div>
          </div>

          <div className="calc-card">
            <label className="calc-label">
              Annual Turnover (₹)
              <input
                type="number"
                className="calc-input"
                value={turnover}
                onChange={(e) => setTurnover(e.target.value)}
                placeholder="Enter annual turnover"
                min="0"
                inputMode="decimal"
                autoFocus
              />
            </label>

            <label className="calc-label">
              Annual Purchases (₹)
              <input
                type="number"
                className="calc-input"
                value={purchases}
                onChange={(e) => setPurchases(e.target.value)}
                placeholder="Enter annual purchases (for ITC calculation)"
                min="0"
                inputMode="decimal"
              />
            </label>

            <label className="calc-label">
              Business Type
              <select
                className="calc-select"
                value={bizType}
                onChange={(e) => setBizType(e.target.value)}
              >
                {BUSINESS_TYPES.map((b) => (
                  <option key={b.key} value={b.key}>
                    {b.label} ({b.compRate}% composition)
                  </option>
                ))}
              </select>
            </label>

            <label className="calc-label">
              State of Registration
              <select
                className="calc-select"
                value={stateCode}
                onChange={(e) => setStateCode(e.target.value)}
              >
                {STATES.map((s) => (
                  <option key={s.code} value={s.code}>{s.name}</option>
                ))}
              </select>
            </label>

            <label className="calc-label">
              GST Rate on Output (%)
              <select
                className="calc-select"
                value={gstRate}
                onChange={(e) => setGstRate(Number(e.target.value))}
              >
                {GST_RATES.map((r) => (
                  <option key={r} value={r}>{r}%</option>
                ))}
              </select>
            </label>

            {result && (
              <div className="calc-result" aria-live="polite">
                {result.overLimit && (
                  <div className="calc-result-row calc-warning">
                    <span>Your turnover exceeds the Composition Scheme limit ({formatINR(limit)} in {selectedState.name}). You must register under the Regular scheme.</span>
                  </div>
                )}

                <div className="comparison-chart" role="img" aria-label="Tax comparison chart">
                  <div className="comparison-bar-group">
                    <div className="comparison-bar-label">Regular Scheme</div>
                    <div className="comparison-bar-track">
                      <div
                        className="comparison-bar"
                        style={{ width: `${Math.max(2, (result.regularTax / maxBar) * 100)}%`, background: "var(--brand, #F0B429)" }}
                      >
                        {formatINR(result.regularTax)}
                      </div>
                    </div>
                  </div>
                  <div className="comparison-bar-group">
                    <div className="comparison-bar-label">Composition Scheme</div>
                    <div className="comparison-bar-track">
                      <div
                        className="comparison-bar"
                        style={{ width: `${Math.max(2, (result.compositionTax / maxBar) * 100)}%`, background: "var(--good, #48BB78)" }}
                      >
                        {formatINR(result.compositionTax)}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="calc-result-row">
                  <span>Output Tax @ {gstRate}%</span>
                  <strong>{formatINR(result.outputTax)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>Input Tax Credit (ITC)</span>
                  <strong>−{formatINR(result.itc)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>Net Tax (Regular)</span>
                  <strong>{formatINR(result.regularTax)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>Tax (Composition @ {selectedBiz.compRate}%)</span>
                  <strong>{formatINR(result.compositionTax)}</strong>
                </div>
                <div className="calc-result-row calc-total">
                  <span>{result.savings >= 0 ? "Composition saves" : "Regular saves"}</span>
                  <strong>{formatINR(Math.abs(result.savings))}</strong>
                </div>

                <table className="comparison-table" aria-label="Annual tax under each scheme">
                  <thead>
                    <tr>
                      <th>Annual tax</th>
                      <th>Regular @ {gstRate}%</th>
                      <th>Composition @ {selectedBiz.compRate}%</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>Output tax</td>
                      <td>{formatINR(result.outputTax)}</td>
                      <td>{formatINR(result.compositionTax)}</td>
                    </tr>
                    <tr>
                      <td>Less ITC</td>
                      <td>−{formatINR(result.itc)}</td>
                      <td>Not available</td>
                    </tr>
                    <tr>
                      <td>CGST</td>
                      <td>{formatINR(result.regularTax / 2)}</td>
                      <td>{formatINR(result.compositionTax / 2)}</td>
                    </tr>
                    <tr>
                      <td>{localTax}</td>
                      <td>{formatINR(result.regularTax / 2)}</td>
                      <td>{formatINR(result.compositionTax / 2)}</td>
                    </tr>
                    <tr>
                      <td><strong>Net payable</strong></td>
                      <td><strong>{formatINR(result.regularTax)}</strong></td>
                      <td><strong>{formatINR(result.compositionTax)}</strong></td>
                    </tr>
                  </tbody>
                </table>

                <table className="comparison-table">
                  <thead>
                    <tr>
                      <th>Feature</th>
                      <th>Regular</th>
                      <th>Composition</th>
                    </tr>
                  </thead>
                  <tbody>
                    {FEATURES.map((f) => (
                      <tr key={f.feature}>
                        <td>{f.feature}</td>
                        <td>{f.regular}</td>
                        <td>{f.composition}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                <div className="calc-result-actions">
                  <ShareButtons
                    path="/scheme-comparison"
                    text={`GST Regular vs Composition: Regular ${formatINR(result.regularTax)} vs Composition ${formatINR(result.compositionTax)} — compared free on DoAide GST`}
                  />
                  <PrintButton label="Print Comparison" />
                </div>
              </div>
            )}
          </div>

          <EmailCapture
            source="scheme-comparison"
            heading="Get GST scheme updates"
            subtext="Stay updated when composition scheme rules change — free email alerts."
            buttonLabel="Notify Me"
            compact
          />

          <section className="tool-info">
            <h2>Understanding GST Schemes</h2>
            <p>
              India&apos;s GST system offers two main schemes for businesses. The Regular
              scheme charges standard GST rates but allows Input Tax Credit on purchases.
              The Composition scheme charges a flat lower rate but with no ITC, no interstate
              supply, and no ability to charge GST on invoices.
            </p>
            <h3>When to Choose Regular Scheme</h3>
            <ul>
              <li>Your purchases are a significant portion of your turnover (high ITC benefit)</li>
              <li>You supply goods or services interstate</li>
              <li>You sell on e-commerce platforms</li>
              <li>Your customers need GST invoices for their own ITC claims</li>
            </ul>
            <h3>When to Choose Composition Scheme</h3>
            <ul>
              <li>You sell only within your state to end consumers</li>
              <li>Your purchases are small relative to turnover</li>
              <li>You want simpler compliance with quarterly filings</li>
              <li>Your turnover is below the limit (₹1.5 crore, ₹75 lakh in eight special category states, ₹50 lakh for services)</li>
            </ul>
            <p>
              Already on composition? Work out each quarter&apos;s CMP-08 payment in the{" "}
              <Link to="/composition-tax-calculator">composition tax calculator</Link>, confirm you qualify with the{" "}
              <Link to="/tools/composition-scheme-checker">eligibility checker</Link>, or check whether you need to register
              at all with the <Link to="/turnover-limit">turnover limit checker</Link>. Your state&apos;s GST code is on the{" "}
              <Link to="/gst-state-codes">state code list</Link>.
            </p>
          </section>

          <section className="tool-info">
            <h2>Frequently Asked Questions</h2>

            <h3>What is the difference between Regular and Composition GST scheme?</h3>
            <p>
              Regular scheme: pay GST at standard rates, claim ITC, do interstate supply.
              Composition scheme: pay a flat lower rate (1-6%), no ITC, no interstate supply,
              cannot charge GST on invoices. The right choice depends on your purchase-to-sales
              ratio and customer profile.
            </p>

            <h3>Who is eligible for the Composition Scheme?</h3>
            <p>
              Businesses with turnover up to ₹1.5 crore (₹50 lakh for services). Excludes
              ice cream, pan masala and tobacco manufacturers, interstate suppliers,
              e-commerce operators, and casual or non-resident taxable persons.
            </p>

            <h3>Does the composition turnover limit depend on the state?</h3>
            <p>
              For goods, yes. Arunachal Pradesh, Manipur, Meghalaya, Mizoram, Nagaland, Sikkim,
              Tripura and Uttarakhand cap it at ₹75 lakh. The ₹50 lakh services limit is the same everywhere.
            </p>

            <h3>Which scheme saves more tax?</h3>
            <p>
              If your purchases are large relative to turnover, Regular wins because ITC
              offsets most of the output tax. If purchases are small, the Composition scheme&apos;s
              flat 1-6% rate is usually cheaper than the net regular tax.
            </p>

            <h3>Can I switch between schemes?</h3>
            <p>
              You can switch from Composition to Regular at any time (Form GST CMP-04).
              Switching from Regular to Composition is only allowed at the start of a
              financial year (Form GST CMP-02 before March 31).
            </p>
          </section>

          <RelatedTools current="/scheme-comparison" />
          <CrossProductLinks page="scheme-comparison" />
        </div>
      </main>
      <DoAideFooter />
      <WhatsAppFloat path="/scheme-comparison" text="Free GST Scheme Comparison — Regular vs Composition calculator" />
    </div>
  );
}
