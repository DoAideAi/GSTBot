import { useMemo, useState } from "react";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import ExitIntentPopup from "../components/ExitIntentPopup";
import RelatedTools from "../components/RelatedTools";
import SaveResultsCTA from "../components/SaveResultsCTA";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { formatINR } from "../lib/gstCalc";

const BUSINESS_TYPES = [
  { key: "manufacturer", label: "Manufacturer", limit: 15000000 },
  { key: "trader", label: "Trader / Dealer", limit: 15000000 },
  { key: "restaurant", label: "Restaurant (not serving alcohol)", limit: 15000000 },
  { key: "service_provider", label: "Service Provider", limit: 5000000 },
  { key: "ice_cream", label: "Ice cream / Pan masala / Tobacco manufacturer", limit: 0 },
  { key: "interstate", label: "Interstate supplier", limit: 0 },
  { key: "ecommerce", label: "E-commerce operator / supplier through e-commerce", limit: 0 },
  { key: "casual", label: "Casual taxable person", limit: 0 },
  { key: "nri", label: "Non-resident taxable person", limit: 0 },
];

const TAX_RATES = {
  manufacturer: { rate: 1, label: "1% (0.5% CGST + 0.5% SGST)" },
  trader: { rate: 1, label: "1% (0.5% CGST + 0.5% SGST)" },
  restaurant: { rate: 5, label: "5% (2.5% CGST + 2.5% SGST)" },
  service_provider: { rate: 6, label: "6% (3% CGST + 3% SGST)" },
};

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST Composition Scheme Eligibility Checker",
  url: "https://gst.doaide.com/composition-scheme",
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
      name: "What is the turnover limit for GST Composition Scheme?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "₹1.5 crore for manufacturers and traders, ₹50 lakh for service providers. Arunachal Pradesh, Manipur, Meghalaya, Mizoram, Nagaland, Sikkim, Tripura and Uttarakhand have a limit of ₹75 lakh for goods; every other state, Himachal Pradesh included, uses ₹1.5 crore.",
      },
    },
    {
      "@type": "Question",
      name: "Can a service provider opt for Composition Scheme?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes, service providers with aggregate turnover up to ₹50 lakh can opt for the Composition Scheme under Section 10(2A) and pay GST at 6% (3% CGST + 3% SGST).",
      },
    },
    {
      "@type": "Question",
      name: "What are the restrictions under Composition Scheme?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Composition dealers cannot collect GST from customers, cannot claim Input Tax Credit, cannot make interstate supplies, and must file CMP-08 quarterly instead of regular GSTR-1 and GSTR-3B returns.",
      },
    },
    {
      "@type": "Question",
      name: "Who cannot opt for the Composition Scheme?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Ice cream, pan masala, tobacco manufacturers; interstate suppliers; e-commerce operators; casual taxable persons; and non-resident taxable persons are ineligible.",
      },
    },
    {
      "@type": "Question",
      name: "What is the tax rate under Composition Scheme?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Manufacturers and traders pay 1% (0.5% CGST + 0.5% SGST), restaurants pay 5% (2.5% CGST + 2.5% SGST), and service providers pay 6% (3% CGST + 3% SGST) on turnover.",
      },
    },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "Composition Scheme Checker" },
];

export default function CompositionSchemePage() {
  usePageTitle("GST Composition Scheme Eligibility Checker — Free Tool");

  const [businessType, setBusinessType] = useState("trader");
  const [turnover, setTurnover] = useState("");
  const [specialState, setSpecialState] = useState(false);

  const selected = BUSINESS_TYPES.find((b) => b.key === businessType);

  const result = useMemo(() => {
    if (!selected) return null;
    const amount = parseFloat(turnover);
    if (!Number.isFinite(amount) || amount < 0) return null;

    if (selected.limit === 0) {
      return {
        eligible: false,
        reason: `${selected.label} businesses are not eligible for the Composition Scheme under GST law, regardless of turnover.`,
        taxRate: null,
        estimatedTax: null,
      };
    }

    const effectiveLimit = specialState ? selected.limit * 0.5 : selected.limit;

    if (amount > effectiveLimit) {
      return {
        eligible: false,
        reason: `Turnover of ${formatINR(amount)} exceeds the ${formatINR(effectiveLimit)} limit${specialState ? " for special category states" : ""}. You must register under the regular GST scheme.`,
        taxRate: null,
        estimatedTax: null,
      };
    }

    const rateInfo = TAX_RATES[businessType];
    const estimatedTax = rateInfo ? Math.round(amount * rateInfo.rate) / 100 : null;

    return {
      eligible: true,
      reason: `With turnover of ${formatINR(amount)}, your ${selected.label.toLowerCase()} business is eligible for the Composition Scheme${specialState ? " (special category state limit)" : ""}.`,
      taxRate: rateInfo,
      estimatedTax,
    };
  }, [businessType, turnover, specialState, selected]);

  return (
    <div className="tool-page">
      <SeoHead
        title="GST Composition Scheme Eligibility Checker — Free Tool"
        description="Check if your business is eligible for the GST Composition Scheme. Enter turnover and business type to get instant eligibility result with applicable tax rate. Free, no login required."
        path="/composition-scheme"
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">Composition Scheme Eligibility Checker</h1>
          <p className="tool-subtitle">
            Check if your business qualifies for the GST Composition Scheme. No sign-up required.
          </p>

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
              Aggregate Annual Turnover (₹)
              <input
                type="number"
                className="calc-input"
                value={turnover}
                onChange={(e) => setTurnover(e.target.value)}
                placeholder="Enter your aggregate annual turnover"
                min="0"
                step="1"
                inputMode="numeric"
                autoFocus
              />
            </label>

            <label className="calc-checkbox-label">
              <input
                type="checkbox"
                checked={specialState}
                onChange={(e) => setSpecialState(e.target.checked)}
              />
              Registered in a ₹75 lakh state (Arunachal, Manipur, Meghalaya, Mizoram, Nagaland, Sikkim, Tripura, Uttarakhand)
            </label>

            {result && (
              <div className="calc-result" aria-live="polite">
                <div className="calc-result-row calc-total" style={{ color: result.eligible ? "#34d399" : "#f87171" }}>
                  <span>Eligibility</span>
                  <strong>{result.eligible ? "Eligible" : "Not Eligible"}</strong>
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
                    {result.estimatedTax !== null && (
                      <div className="calc-result-row">
                        <span>Estimated Annual Tax</span>
                        <strong>{formatINR(result.estimatedTax)}</strong>
                      </div>
                    )}
                  </>
                )}
                <div className="calc-result-actions">
                  <ShareButtons
                    path="/composition-scheme"
                    text={`GST Composition Scheme: ${result.eligible ? "Eligible" : "Not Eligible"} — checked free on DoAide GST`}
                  />
                </div>
              </div>
            )}
          </div>

          {result && (
            <SaveResultsCTA resultSummary={`Composition Scheme: ${result.eligible ? "Eligible" : "Not Eligible"}${result.taxRate ? ` at ${result.taxRate.label}` : ""}`} />
          )}
          <EmailCapture
            source="composition-scheme"
            heading="Stay updated on GST scheme changes"
            subtext="Get notified when composition scheme rules change — free email alerts."
            buttonLabel="Notify Me"
            compact
          />

          <section className="tool-info">
            <h2>GST Composition Scheme — Complete Guide</h2>
            <p>
              The Composition Scheme under GST (Section 10) is a simplified tax scheme for small
              businesses. It allows eligible taxpayers to pay GST at a fixed rate on turnover
              instead of the regular rates, with simpler compliance requirements.
            </p>
            <h3>Turnover Limits</h3>
            <ul>
              <li><strong>Manufacturers &amp; Traders:</strong> ₹1.5 crore (₹75 lakh for special category states)</li>
              <li><strong>Service Providers:</strong> ₹50 lakh (under Section 10(2A))</li>
              <li><strong>Restaurants:</strong> ₹1.5 crore (not serving alcohol)</li>
            </ul>
            <h3>Tax Rates Under Composition Scheme</h3>
            <ul>
              <li><strong>Manufacturers &amp; Traders:</strong> 1% (0.5% CGST + 0.5% SGST)</li>
              <li><strong>Restaurants:</strong> 5% (2.5% CGST + 2.5% SGST)</li>
              <li><strong>Service Providers:</strong> 6% (3% CGST + 3% SGST)</li>
            </ul>
            <h3>Key Restrictions</h3>
            <ul>
              <li>Cannot collect GST from customers</li>
              <li>Cannot claim Input Tax Credit (ITC)</li>
              <li>Cannot make interstate outward supplies</li>
              <li>Must mention &quot;Composition taxable person&quot; on every notice/signboard</li>
              <li>Must mention &quot;Bill of Supply&quot; on every bill (not Tax Invoice)</li>
            </ul>
            <h3>Filing Requirements</h3>
            <ul>
              <li><strong>CMP-08:</strong> Quarterly statement (within 18 days of quarter end)</li>
              <li><strong>GSTR-4:</strong> Annual return (by 30th April of following year)</li>
              <li>No requirement to file GSTR-1, GSTR-2, or GSTR-3B</li>
            </ul>
          </section>

          <section className="tool-info">
            <h2>Frequently Asked Questions</h2>

            <h3>What is the turnover limit for GST Composition Scheme?</h3>
            <p>
              The turnover limit is ₹1.5 crore for manufacturers, traders, and restaurants.
              For service providers, it is ₹50 lakh. Arunachal Pradesh, Manipur, Meghalaya, Mizoram, Nagaland, Sikkim,
              Tripura and Uttarakhand have a reduced limit of ₹75 lakh for manufacturers/traders.
              Himachal Pradesh, Assam and Jammu &amp; Kashmir use the full ₹1.5 crore.
            </p>

            <h3>Can a service provider opt for Composition Scheme?</h3>
            <p>
              Yes, service providers with aggregate turnover up to ₹50 lakh can opt for the
              Composition Scheme under Section 10(2A). They pay GST at 6% (3% CGST + 3% SGST)
              on their turnover.
            </p>

            <h3>What are the restrictions under Composition Scheme?</h3>
            <p>
              Composition dealers cannot collect GST from customers, cannot claim Input Tax
              Credit, cannot make interstate outward supplies, and must file CMP-08 quarterly
              and GSTR-4 annually instead of regular returns.
            </p>

            <h3>Who cannot opt for the Composition Scheme?</h3>
            <p>
              Manufacturers of ice cream, pan masala, and tobacco products; businesses making
              interstate supplies; e-commerce operators and suppliers through e-commerce
              platforms; casual taxable persons; and non-resident taxable persons.
            </p>

            <h3>What is the tax rate under Composition Scheme?</h3>
            <p>
              Manufacturers and traders pay 1%, restaurants (not serving alcohol) pay 5%,
              and service providers pay 6% on their turnover. These rates include both
              CGST and SGST components.
            </p>

            <h3>Can I switch from Composition to Regular scheme?</h3>
            <p>
              Yes, you can switch from Composition to Regular scheme by filing Form GST CMP-04
              before the start of the financial year. You can also be compulsorily migrated
              if your turnover exceeds the threshold during the year.
            </p>

            <h3>Is the Composition Scheme available for goods and services both?</h3>
            <p>
              Yes. Originally only for goods suppliers, the scheme was extended to service
              providers (up to ₹50 lakh turnover) through the insertion of Section 10(2A)
              via the CGST Amendment Act, 2018.
            </p>
          </section>

          <InlineCTA variant="save" />
          <RelatedTools current="/composition-scheme" />
          <CrossProductLinks page="composition-scheme" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
      <ExitIntentPopup />
    </div>
  );
}
