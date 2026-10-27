import { useMemo, useState } from "react";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import WhatsAppFloat from "../components/WhatsAppFloat";
import { usePageTitle } from "../hooks/usePageTitle";
// The ₹75 lakh states come from the shared list so this page and the others
// that ask about state cannot disagree — this one used to add Himachal Pradesh.
import { LOWER_LIMIT_STATES as SPECIAL_CATEGORY_STATES } from "../lib/compositionTax";
import { formatINR } from "../lib/gstCalc";
import { track } from "../lib/track";

const ALL_STATES = [
  "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
  "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand",
  "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
  "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab",
  "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
  "Uttar Pradesh", "Uttarakhand", "West Bengal",
  "Andaman & Nicobar Islands", "Chandigarh", "Dadra & Nagar Haveli and Daman & Diu",
  "Delhi", "Jammu & Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
];

const BUSINESS_TYPES = [
  { key: "manufacturer", label: "Manufacturer" },
  { key: "trader", label: "Trader / Dealer" },
  { key: "restaurant", label: "Restaurant (not serving alcohol)" },
  { key: "service_provider", label: "Service Provider" },
];

const TAX_RATES = {
  manufacturer: { rate: 1, label: "1% (0.5% CGST + 0.5% SGST)" },
  trader: { rate: 1, label: "1% (0.5% CGST + 0.5% SGST)" },
  restaurant: { rate: 5, label: "5% (2.5% CGST + 2.5% SGST)" },
  service_provider: { rate: 6, label: "6% (3% CGST + 3% SGST)" },
};

const REGULAR_RATES = {
  manufacturer: 18,
  trader: 18,
  restaurant: 5,
  service_provider: 18,
};

const INELIGIBLE_CATEGORIES = [
  "Inter-state suppliers of goods",
  "E-commerce operators or suppliers through e-commerce platforms",
  "Manufacturers of ice cream, pan masala, or tobacco products",
  "Casual taxable persons",
  "Non-resident taxable persons",
  "Suppliers of goods through e-commerce operators who are required to collect tax at source",
];

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST Composition Scheme Eligibility Checker",
  url: "https://gst.doaide.com/tools/composition-scheme-checker",
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
      name: "What is the GST Composition Scheme?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "A simplified GST scheme for small businesses under Section 10. Pay tax at a lower fixed rate on turnover with quarterly filing, but you cannot claim Input Tax Credit.",
      },
    },
    {
      "@type": "Question",
      name: "What is the turnover limit for the GST Composition Scheme?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "₹1.5 crore for manufacturers, traders, and restaurants. ₹50 lakh for service providers. Special category states have a reduced limit of ₹75 lakh for goods suppliers.",
      },
    },
    {
      "@type": "Question",
      name: "What are the tax rates under the Composition Scheme?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Manufacturers and traders pay 1% (0.5% CGST + 0.5% SGST), restaurants not serving alcohol pay 5% (2.5% CGST + 2.5% SGST), and service providers pay 6% (3% CGST + 3% SGST) on their turnover.",
      },
    },
    {
      "@type": "Question",
      name: "Can a composition dealer claim Input Tax Credit (ITC)?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "No. Composition dealers cannot claim ITC on purchases. The regular scheme with ITC may result in lower net tax for businesses with significant taxable inputs.",
      },
    },
    {
      "@type": "Question",
      name: "Who cannot opt for the GST Composition Scheme?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Inter-state suppliers, e-commerce operators, ice cream/pan masala/tobacco manufacturers, casual taxable persons, and non-resident taxable persons are ineligible.",
      },
    },
    {
      "@type": "Question",
      name: "What returns does a composition dealer need to file?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "CMP-08 quarterly (within 18 days of quarter end) and GSTR-4 annually (by 30th April). No monthly GSTR-1 or GSTR-3B filing required.",
      },
    },
    {
      "@type": "Question",
      name: "How does the Composition Scheme compare with the regular GST scheme?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Composition offers lower rates and quarterly filing but no ITC. Regular scheme has higher rates but ITC claims may reduce net tax for input-heavy businesses.",
      },
    },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "Tools", url: "https://gst.doaide.com/resources" },
  { name: "Composition Scheme Checker" },
];

export function checkEligibility({ turnover, businessType, state }) {
  const amount = parseFloat(turnover);
  if (!Number.isFinite(amount) || amount < 0) return null;

  const isSpecialState = SPECIAL_CATEGORY_STATES.includes(state);
  const rateInfo = TAX_RATES[businessType];
  if (!rateInfo) return null;

  const isServiceProvider = businessType === "service_provider";
  const baseLimit = isServiceProvider ? 5000000 : 15000000;
  const effectiveLimit = isServiceProvider
    ? baseLimit
    : isSpecialState ? 7500000 : baseLimit;

  if (amount > effectiveLimit) {
    return {
      eligible: false,
      reason: `Turnover of ${formatINR(amount)} exceeds the ${formatINR(effectiveLimit)} limit${isSpecialState ? " for special category states" : ""} for ${isServiceProvider ? "service providers" : "goods suppliers"}. You must register under the regular GST scheme.`,
      taxRate: null,
      estimatedQuarterlyTax: null,
      regularComparison: null,
    };
  }

  const annualTax = Math.round(amount * rateInfo.rate) / 100;
  const quarterlyTax = Math.round(annualTax / 4 * 100) / 100;

  const regularRate = REGULAR_RATES[businessType];
  const regularAnnualTax = Math.round(amount * regularRate) / 100;
  const estimatedItc = Math.round(regularAnnualTax * 0.6 * 100) / 100;
  const regularNetTax = Math.round((regularAnnualTax - estimatedItc) * 100) / 100;

  return {
    eligible: true,
    reason: `Your ${BUSINESS_TYPES.find(b => b.key === businessType)?.label.toLowerCase()} business with turnover of ${formatINR(amount)} is eligible for the Composition Scheme${isSpecialState ? " (special category state)" : ""}.`,
    taxRate: rateInfo,
    turnoverLimit: effectiveLimit,
    estimatedAnnualTax: annualTax,
    estimatedQuarterlyTax: quarterlyTax,
    regularComparison: {
      regularRate,
      regularAnnualTax,
      estimatedItc,
      regularNetTax,
      compositionBetter: annualTax < regularNetTax,
    },
  };
}

export default function CompositionSchemeCheckerPage() {
  usePageTitle("GST Composition Scheme Eligibility Checker — Turnover Limit, Tax Rate & Comparison");

  const [businessType, setBusinessType] = useState("manufacturer");
  const [turnover, setTurnover] = useState("");
  const [state, setState] = useState("");

  const result = useMemo(() => {
    if (!state || !turnover) return null;
    const r = checkEligibility({ turnover, businessType, state });
    if (r) track("composition_checker_calculate", { businessType, eligible: r.eligible });
    return r;
  }, [businessType, turnover, state]);

  return (
    <div className="tool-page">
      <SeoHead
        title="GST Composition Scheme Eligibility Checker — Turnover Limit, Tax Rate & Comparison"
        description="Check if your business qualifies for the GST Composition Scheme. Get eligibility, tax rate, quarterly tax estimate, and comparison with regular scheme. Free, no login."
        path="/tools/composition-scheme-checker"
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb items={[{ label: "Home", to: "/" }, { label: "Tools", to: "/resources" }, { label: "Composition Scheme Checker" }]} />
          <h1 className="tool-title">GST Composition Scheme Eligibility Checker</h1>
          <p className="tool-subtitle">
            Check if your business qualifies for the Composition Scheme under GST. Get your applicable tax rate, estimated quarterly tax, and a comparison with the regular scheme. No sign-up required.
          </p>

          <div className="how-it-works">
            <h2 className="how-it-works-title">How It Works</h2>
            <div className="how-it-works-steps">
              <div className="how-it-works-step">
                <div className="how-it-works-num">1</div>
                <h3>Enter Details</h3>
                <p>Select your business type, state, and annual turnover</p>
              </div>
              <div className="how-it-works-step">
                <div className="how-it-works-num">2</div>
                <h3>Check Eligibility</h3>
                <p>Instantly see if you qualify based on GST rules</p>
              </div>
              <div className="how-it-works-step">
                <div className="how-it-works-num">3</div>
                <h3>Compare Schemes</h3>
                <p>See composition vs regular scheme tax comparison</p>
              </div>
            </div>
          </div>

          <div className="calc-card">
            <label className="calc-label">
              Business Type
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
              State / Union Territory
              <select
                className="calc-select"
                value={state}
                onChange={(e) => setState(e.target.value)}
              >
                <option value="">— Select your state —</option>
                {ALL_STATES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </label>

            <label className="calc-label">
              Annual Aggregate Turnover (₹)
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

            {state && SPECIAL_CATEGORY_STATES.includes(state) && (
              <div style={{ padding: "0.5rem 0.75rem", background: "rgba(212,175,55,0.1)", border: "1px solid rgba(212,175,55,0.3)", borderRadius: "0.5rem", fontSize: "0.85rem", lineHeight: 1.5 }}>
                <strong style={{ color: "#D4AF37" }}>{state}</strong> is a special category state. Turnover limit for goods suppliers is ₹75 lakh instead of ₹1.5 crore.
              </div>
            )}

            {result && (
              <div className="calc-result" aria-live="polite">
                <div className="calc-result-row calc-total" style={{ color: result.eligible ? "#34d399" : "#f87171" }}>
                  <span>Eligibility</span>
                  <strong>{result.eligible ? "Eligible ✓" : "Not Eligible ✗"}</strong>
                </div>
                <p style={{ margin: "0.5rem 0", fontSize: "0.95rem", lineHeight: 1.5 }}>
                  {result.reason}
                </p>

                {result.eligible && result.taxRate && (
                  <>
                    <div className="calc-result-row">
                      <span>Applicable Tax Rate</span>
                      <strong>{result.taxRate.label}</strong>
                    </div>
                    <div className="calc-result-row">
                      <span>Estimated Annual Tax</span>
                      <strong>{formatINR(result.estimatedAnnualTax)}</strong>
                    </div>
                    <div className="calc-result-row calc-total">
                      <span>Estimated Quarterly Tax (CMP-08)</span>
                      <strong>{formatINR(result.estimatedQuarterlyTax)}</strong>
                    </div>

                    {result.regularComparison && (
                      <div style={{ marginTop: "1rem", padding: "0.75rem", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "0.5rem" }}>
                        <h4 style={{ margin: "0 0 0.75rem", fontSize: "0.95rem", color: "#D4AF37" }}>
                          Composition vs Regular Scheme
                        </h4>
                        <table style={{ width: "100%", fontSize: "0.9rem", borderCollapse: "collapse" }}>
                          <thead>
                            <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.1)" }}>
                              <th style={{ textAlign: "left", padding: "0.4rem 0" }}></th>
                              <th style={{ textAlign: "right", padding: "0.4rem 0" }}>Composition</th>
                              <th style={{ textAlign: "right", padding: "0.4rem 0" }}>Regular</th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr>
                              <td style={{ padding: "0.4rem 0" }}>Tax Rate</td>
                              <td style={{ textAlign: "right", padding: "0.4rem 0" }}>{result.taxRate.rate}%</td>
                              <td style={{ textAlign: "right", padding: "0.4rem 0" }}>{result.regularComparison.regularRate}%</td>
                            </tr>
                            <tr>
                              <td style={{ padding: "0.4rem 0" }}>Annual Tax</td>
                              <td style={{ textAlign: "right", padding: "0.4rem 0" }}>{formatINR(result.estimatedAnnualTax)}</td>
                              <td style={{ textAlign: "right", padding: "0.4rem 0" }}>{formatINR(result.regularComparison.regularAnnualTax)}</td>
                            </tr>
                            <tr>
                              <td style={{ padding: "0.4rem 0" }}>Input Tax Credit</td>
                              <td style={{ textAlign: "right", padding: "0.4rem 0", color: "#f87171" }}>Not Available</td>
                              <td style={{ textAlign: "right", padding: "0.4rem 0", color: "#34d399" }}>~{formatINR(result.regularComparison.estimatedItc)}</td>
                            </tr>
                            <tr style={{ borderTop: "1px solid rgba(255,255,255,0.1)", fontWeight: 600 }}>
                              <td style={{ padding: "0.5rem 0" }}>Net Tax Outgo</td>
                              <td style={{ textAlign: "right", padding: "0.5rem 0", color: result.regularComparison.compositionBetter ? "#34d399" : "inherit" }}>
                                {formatINR(result.estimatedAnnualTax)}
                              </td>
                              <td style={{ textAlign: "right", padding: "0.5rem 0", color: !result.regularComparison.compositionBetter ? "#34d399" : "inherit" }}>
                                {formatINR(result.regularComparison.regularNetTax)}
                              </td>
                            </tr>
                          </tbody>
                        </table>
                        <p style={{ margin: "0.5rem 0 0", fontSize: "0.85rem", color: "var(--text-secondary)" }}>
                          {result.regularComparison.compositionBetter
                            ? "💡 Composition Scheme results in lower net tax for your business. ITC estimates assume ~60% of output tax is claimable as credit."
                            : "💡 Regular scheme may result in lower net tax after claiming ITC. ITC estimates assume ~60% of output tax is claimable as credit — actual savings depend on your purchase pattern."}
                        </p>
                      </div>
                    )}
                  </>
                )}

                <div className="calc-result-actions">
                  <ShareButtons
                    path="/tools/composition-scheme-checker"
                    text={`GST Composition Scheme: ${result.eligible ? "Eligible" : "Not Eligible"}${result.taxRate ? ` at ${result.taxRate.label}` : ""} — checked free on DoAide GST`}
                    toolName="Composition Scheme Checker"
                  />
                </div>
              </div>
            )}
          </div>

          <section className="tool-info">
            <h2>Who Cannot Opt for the Composition Scheme?</h2>
            <p>The following categories of businesses are ineligible regardless of turnover:</p>
            <ul>
              {INELIGIBLE_CATEGORIES.map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
          </section>

          <EmailCapture
            source="composition-scheme-checker"
            heading="Get notified when composition scheme rules change"
            subtext="Free email alerts when turnover limits or tax rates are updated by the GST Council."
            buttonLabel="Notify Me"
            compact
          />

          <section className="tool-info">
            <h2>Composition Scheme — Key Facts</h2>
            <h3>Turnover Limits</h3>
            <ul>
              <li><strong>Manufacturers &amp; Traders:</strong> ₹1.5 crore (₹75 lakh for special category states)</li>
              <li><strong>Service Providers:</strong> ₹50 lakh under Section 10(2A)</li>
              <li><strong>Restaurants:</strong> ₹1.5 crore (not serving alcohol)</li>
            </ul>
            <h3>Tax Rates</h3>
            <ul>
              <li><strong>Manufacturers &amp; Traders:</strong> 1% (0.5% CGST + 0.5% SGST)</li>
              <li><strong>Restaurants:</strong> 5% (2.5% CGST + 2.5% SGST)</li>
              <li><strong>Service Providers:</strong> 6% (3% CGST + 3% SGST)</li>
            </ul>
            <h3>Key Restrictions</h3>
            <ul>
              <li>Cannot collect GST from customers — must issue &quot;Bill of Supply&quot; instead of Tax Invoice</li>
              <li>Cannot claim Input Tax Credit (ITC) on purchases</li>
              <li>Cannot make interstate outward supplies of goods</li>
              <li>Must mention &quot;Composition taxable person&quot; on every notice and signboard</li>
            </ul>
            <h3>Filing Requirements</h3>
            <ul>
              <li><strong>CMP-08:</strong> Quarterly self-assessed tax statement (due within 18 days of quarter end)</li>
              <li><strong>GSTR-4:</strong> Annual return (due by 30th April of the following year)</li>
              <li>No GSTR-1, GSTR-2, or GSTR-3B filing required</li>
            </ul>
          </section>

          <section className="tool-info">
            <h2>Frequently Asked Questions</h2>

            <h3>What is the GST Composition Scheme?</h3>
            <p>
              The Composition Scheme under Section 10 of the CGST Act is a simplified tax scheme
              for small businesses. It allows eligible taxpayers to pay GST at a fixed lower rate
              on their turnover, with simpler quarterly filing instead of monthly returns. However,
              composition dealers cannot collect GST from customers or claim Input Tax Credit.
            </p>

            <h3>What is the turnover limit for the GST Composition Scheme?</h3>
            <p>
              The limit is ₹1.5 crore for manufacturers, traders, and restaurants. Service providers
              under Section 10(2A) have a limit of ₹50 lakh. Arunachal Pradesh, Manipur,
              Meghalaya, Mizoram, Nagaland, Sikkim, Tripura and Uttarakhand have a reduced limit of
              ₹75 lakh for goods suppliers. Himachal Pradesh, Assam and Jammu &amp; Kashmir use the
              full ₹1.5 crore.
            </p>

            <h3>What are the tax rates under the Composition Scheme?</h3>
            <p>
              Manufacturers and traders pay 1% (0.5% CGST + 0.5% SGST), restaurants not serving
              alcohol pay 5% (2.5% CGST + 2.5% SGST), and service providers pay 6% (3% CGST + 3% SGST).
            </p>

            <h3>Can a composition dealer claim Input Tax Credit (ITC)?</h3>
            <p>
              No. Composition dealers cannot claim ITC on their purchases. This means the full cost
              of GST on inputs is borne by the business. For businesses with significant taxable
              purchases, the regular scheme with ITC may result in lower effective tax.
            </p>

            <h3>Who cannot opt for the GST Composition Scheme?</h3>
            <p>
              Inter-state suppliers, e-commerce operators, manufacturers of ice cream, pan masala,
              and tobacco products, casual taxable persons, and non-resident taxable persons cannot
              opt for the Composition Scheme.
            </p>

            <h3>What returns does a composition dealer file?</h3>
            <p>
              Composition dealers file CMP-08 quarterly (within 18 days of quarter end) and GSTR-4
              annually (by 30th April). They are exempt from monthly GSTR-1, GSTR-2, and GSTR-3B.
            </p>

            <h3>How does the Composition Scheme compare with the regular scheme?</h3>
            <p>
              Composition offers lower rates and simpler compliance but no ITC. Regular scheme has
              higher rates but ITC claims can reduce net tax significantly. Use the calculator above
              to compare for your specific turnover.
            </p>
          </section>

          <InlineCTA variant="save" />
          <RelatedTools current="/tools/composition-scheme-checker" />
          <CrossProductLinks page="composition-scheme-checker" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
      <WhatsAppFloat path="/tools/composition-scheme-checker" text="Free GST Composition Scheme Eligibility Checker — check turnover limit, tax rate & compare with regular scheme" />
    </div>
  );
}
