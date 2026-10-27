import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { formatINR } from "../lib/gstCalc";
import { checkRegistration, NO_40_LAKH_STATES, STATES, TEN_LAKH_STATES, thresholdFor } from "../lib/gstRegistration";

// The limits come from lib/gstRegistration.js, which /registration-checker
// reads too. This page kept its own list once, calling every north-eastern
// and hill state "special category", and put Assam, Himachal Pradesh, J&K and
// Ladakh goods sellers at ₹20 lakh when they are at ₹40 lakh.
const LOWER_LIMIT_STATES = [...new Set([...NO_40_LAKH_STATES, ...TEN_LAKH_STATES])].sort();

const BUSINESS_TYPES = [
  { key: "goods", label: "Supply of goods" },
  { key: "services", label: "Supply of services" },
  { key: "both", label: "Both goods and services" },
];

function determineThreshold(state, businessType) {
  return thresholdFor(businessType, state).limit;
}

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST Registration Threshold Checker",
  url: "https://gst.doaide.com/turnover-limit",
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
      name: "What is the GST registration threshold for goods?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "₹40 lakh for businesses supplying only goods. Arunachal Pradesh, Meghalaya, Puducherry, Sikkim, Telangana and Uttarakhand use ₹20 lakh, and Manipur, Mizoram, Nagaland and Tripura ₹10 lakh. Assam, Himachal Pradesh, J&K and Ladakh use ₹40 lakh.",
      },
    },
    {
      "@type": "Question",
      name: "What is the GST registration threshold for services?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "₹20 lakh, or ₹10 lakh in Manipur, Mizoram, Nagaland and Tripura. The same limit applies to a business supplying both goods and services.",
      },
    },
    {
      "@type": "Question",
      name: "When is GST registration mandatory regardless of turnover?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Inter-state supply of goods, casual and non-resident taxable persons, reverse charge liability, e-commerce operators, input service distributors, agents and TDS deductors. Marketplace sellers within one state are exempt below the limit.",
      },
    },
    {
      "@type": "Question",
      name: "What is aggregate turnover under GST?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Includes taxable, exempt, export, and interstate supplies of persons with the same PAN, all-India basis. Excludes reverse charge inward supplies and GST.",
      },
    },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "Turnover Limit Checker" },
];

const MANDATORY_CASES = [
  "Interstate supply of taxable goods (any value)",
  "Interstate supply of taxable services (above threshold only)",
  "Casual taxable person making taxable supply",
  "Non-resident taxable person",
  "Person liable to pay tax under reverse charge",
  "E-commerce operator (TCS under Section 52)",
  "Person selling goods to other states through an e-commerce platform",
  "Person required to deduct TDS under Section 51",
  "Input service distributor",
  "Agent of a supplier or recipient",
  "Transfer of business (transferee must register)",
];

export default function TurnoverLimitPage() {
  usePageTitle("GST Registration Threshold — Check if You Need GST");

  const [state, setState] = useState("");
  const [businessType, setBusinessType] = useState("goods");
  const [turnover, setTurnover] = useState("");
  const [interstate, setInterstate] = useState(false);
  const [ecommerce, setEcommerce] = useState(false);

  const result = useMemo(() => {
    if (!state) return null;
    const threshold = determineThreshold(state, businessType);
    const interstateGoods = interstate && businessType !== "services";
    // Inter-state goods need registration whatever the turnover, so that
    // verdict does not wait for a figure; everything else does.
    if (turnover === "" && !interstateGoods) {
      return { required: null, threshold, reasons: [], notes: [], prompt: "Enter your aggregate turnover to check." };
    }
    const check = checkRegistration({ type: businessType, turnover: turnover === "" ? "0" : turnover, state, interState: interstate, ecommerce });
    if (!check) return { required: null, threshold, reasons: [], notes: [], prompt: "Enter a turnover of zero or more." };
    return { ...check, threshold };
  }, [state, businessType, turnover, interstate, ecommerce]);

  return (
    <div className="tool-page">
      <SeoHead
        title="GST Registration Threshold — Check if You Need GST Registration"
        description="Check if your business needs GST registration based on turnover, state, and supply type. Free threshold checker tool — no login required."
        path="/turnover-limit"
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">GST Registration Threshold Checker</h1>
          <p className="tool-subtitle">
            Check whether your business needs GST registration based on your turnover,
            state, and type of supply. No sign-up required.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              State / UT
              <select
                className="calc-select"
                value={state}
                onChange={(e) => setState(e.target.value)}
              >
                <option value="">Select your state</option>
                {STATES.map((s) => (
                  <option key={s} value={s}>{s}{LOWER_LIMIT_STATES.includes(s) ? " (lower limit)" : ""}</option>
                ))}
              </select>
            </label>

            <label className="calc-label">
              Type of Supply
              <select
                className="calc-select"
                value={businessType}
                onChange={(e) => setBusinessType(e.target.value)}
              >
                {BUSINESS_TYPES.map((b) => (
                  <option key={b.key} value={b.key}>{b.label}</option>
                ))}
              </select>
            </label>

            <label className="calc-label">
              Aggregate Annual Turnover (₹)
              <input
                type="number"
                className="calc-input"
                value={turnover}
                onChange={(e) => setTurnover(e.target.value)}
                placeholder="Enter your annual turnover"
                min="0"
                step="1"
                inputMode="numeric"
              />
            </label>

            <label className="calc-checkbox-label">
              <input
                type="checkbox"
                checked={interstate}
                onChange={(e) => setInterstate(e.target.checked)}
              />
              {businessType === "services" ? "Interstate supply of services" : "Interstate supply of taxable goods"}
            </label>

            <label className="calc-checkbox-label">
              <input
                type="checkbox"
                checked={ecommerce}
                onChange={(e) => setEcommerce(e.target.checked)}
              />
              Selling through e-commerce platform (Amazon, Flipkart, etc.)
            </label>

            {result && (
              <div className="calc-result" aria-live="polite">
                {result.threshold && (
                  <div className="calc-result-row">
                    <span>Applicable Threshold</span>
                    <strong>{formatINR(result.threshold)}</strong>
                  </div>
                )}
                {result.required !== null && (
                  <div className="calc-result-row calc-total" style={{ color: result.required ? "#f59e42" : "#34d399" }}>
                    <span>GST Registration</span>
                    <strong>{result.required ? "Required" : "Not Mandatory"}</strong>
                  </div>
                )}
                {result.prompt && <p style={{ margin: "0.5rem 0", fontSize: "0.95rem", lineHeight: 1.5 }}>{result.prompt}</p>}
                {result.reasons.map((r) => (
                  <p key={r.section} style={{ margin: "0.5rem 0", fontSize: "0.95rem", lineHeight: 1.5 }}>
                    <strong>{r.section}:</strong> {r.text}
                  </p>
                ))}
                {result.required === false && (
                  <p style={{ margin: "0.5rem 0", fontSize: "0.95rem", lineHeight: 1.5 }}>
                    Your aggregate turnover is within the {formatINR(result.threshold)} limit for {state}.
                    GST registration is not mandatory, but you may register voluntarily.
                  </p>
                )}
                {result.notes.map((n) => (
                  <p key={n} className="calc-note">{n}</p>
                ))}
                <div className="calc-result-actions">
                  <ShareButtons
                    path="/turnover-limit"
                    text={`GST registration ${result.required ? "required" : "not mandatory"} — checked free on DoAide GST`}
                  />
                </div>
              </div>
            )}
          </div>

          <EmailCapture
            source="turnover-limit"
            heading="Stay updated on GST thresholds"
            subtext="Get notified when GST registration thresholds change."
            buttonLabel="Notify Me"
            compact
          />

          <section className="tool-info">
            <h2>GST Registration Thresholds</h2>
            <table className="due-date-table">
              <thead>
                <tr>
                  <th>States and UTs</th>
                  <th>Goods only</th>
                  <th>Services, or both</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>All others, including Assam, Himachal Pradesh, J&amp;K and Ladakh</td>
                  <td>₹40 lakh</td>
                  <td>₹20 lakh</td>
                </tr>
                <tr>
                  <td>{NO_40_LAKH_STATES.filter((x) => !TEN_LAKH_STATES.includes(x)).join(", ")}</td>
                  <td>₹20 lakh</td>
                  <td>₹20 lakh</td>
                </tr>
                <tr>
                  <td>{TEN_LAKH_STATES.join(", ")}</td>
                  <td>₹10 lakh</td>
                  <td>₹10 lakh</td>
                </tr>
              </tbody>
            </table>

            <h3>Mandatory Registration (Regardless of Turnover)</h3>
            <ul>
              {MANDATORY_CASES.map((c, i) => <li key={i}>{c}</li>)}
            </ul>

            <h3>States with a lower limit</h3>
            <p>
              Only Manipur, Mizoram, Nagaland and Tripura use ₹10 lakh. The ₹40 lakh limit for
              goods does not apply in {NO_40_LAKH_STATES.filter((x) => !TEN_LAKH_STATES.includes(x)).join(", ")},
              which stay at ₹20 lakh. To check a specific business, use the{" "}
              <Link to="/registration-checker">registration eligibility checker</Link>.
            </p>
          </section>

          <section className="tool-info">
            <h2>Frequently Asked Questions</h2>

            <h3>What is aggregate turnover under GST?</h3>
            <p>
              Aggregate turnover includes all taxable, exempt, and export supplies of persons
              having the same PAN, computed on an all-India basis. It excludes inward supplies
              under reverse charge and tax amounts (CGST, SGST, IGST, cess).
            </p>

            <h3>Should I register even if below the threshold?</h3>
            <p>
              Voluntary registration is allowed and often beneficial — it lets you collect GST,
              claim ITC on purchases, sell to other registered businesses more easily, and
              list on government and e-commerce platforms that require a GSTIN.
            </p>

            <h3>What happens if I cross the threshold mid-year?</h3>
            <p>
              You must apply for GST registration within 30 days of your aggregate turnover
              crossing the applicable threshold. Failure to register attracts a penalty equal
              to the tax due or ₹10,000, whichever is higher.
            </p>
          </section>

          <RelatedTools current="/turnover-limit" />
          <CrossProductLinks page="turnover-limit" />
        </div>
      </main>
      <DoAideFooter />
    </div>
  );
}

export { LOWER_LIMIT_STATES, determineThreshold };
