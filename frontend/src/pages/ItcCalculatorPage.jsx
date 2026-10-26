import { useMemo, useState } from "react";
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
import WhatsAppFloat from "../components/WhatsAppFloat";
import { track } from "../lib/track";

const ELIGIBLE = [
  { key: "business", label: "Business goods & services" },
  { key: "capital", label: "Capital goods" },
];

const BLOCKED = [
  { key: "motor", label: "Motor vehicles", section: "s.17(5)(a)" },
  { key: "food", label: "Food & beverages / catering", section: "s.17(5)(b)(i)" },
  { key: "club", label: "Club membership / health & fitness", section: "s.17(5)(b)(ii)" },
  { key: "personal", label: "Personal consumption", section: "s.17(5)(g)" },
  { key: "gifts", label: "Gifts & free samples", section: "s.17(5)(h)" },
  { key: "construction", label: "Construction of immovable property", section: "s.17(5)(d)" },
  { key: "exempt", label: "Used for exempt supplies", section: "s.17(2)" },
];

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST ITC Calculator",
  url: "https://gst.doaide.com/itc-calculator",
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
      name: "How is ITC calculated under GST?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "ITC equals GST on eligible purchases minus blocked credits and proportional reversal for exempt supplies. Only GST on inputs used for taxable supplies is claimable.",
      },
    },
    {
      "@type": "Question",
      name: "What are blocked credits under Section 17(5)?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Blocked credits include GST on motor vehicles, food, club memberships, personal consumption, gifts, free samples, and construction (except plant and machinery).",
      },
    },
    {
      "@type": "Question",
      name: "What is proportional ITC reversal under Section 17(2)?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "When inputs serve both taxable and exempt supplies, ITC is reversed proportionally based on the exempt-to-total turnover ratio. This limits ITC to the taxable share.",
      },
    },
    {
      "@type": "Question",
      name: "Can ITC be claimed on capital goods?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes, ITC on capital goods for business is available in full in the period when goods are received. No installment requirement under GST unlike the old regime.",
      },
    },
    {
      "@type": "Question",
      name: "What is the time limit for claiming ITC?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "ITC must be claimed by the earlier of the September GSTR-3B deadline or the annual return filing date of the following year. For FY 2026-27, the deadline is November 30, 2027.",
      },
    },
  ],
};

const HOWTO_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "HowTo",
  name: "How to calculate eligible Input Tax Credit",
  description: "Work out how much of the GST paid on purchases can be claimed as ITC.",
  step: [
    { "@type": "HowToStep", name: "Enter the GST paid on purchases", text: "Total input tax for the period, split across IGST, CGST and SGST as billed." },
    { "@type": "HowToStep", name: "Mark the ineligible portions", text: "Blocked credits under Section 17(5) and purchases used for exempt supplies cannot be claimed." },
    { "@type": "HowToStep", name: "Read the eligible credit", text: "The calculator totals what can go into GSTR-3B Table 4A — cross-check it against GSTR-2B before filing." },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "ITC Calculator" },
];

export default function ItcCalculatorPage() {
  usePageTitle("Free ITC Calculator — Input Tax Credit with Blocked Credits");

  const initValues = () => {
    const v = {};
    ELIGIBLE.forEach((e) => { v[e.key] = ""; });
    BLOCKED.forEach((b) => { v[b.key] = ""; });
    return v;
  };
  const [values, setValues] = useState(initValues);
  const [exemptTurnover, setExemptTurnover] = useState("");
  const [totalTurnover, setTotalTurnover] = useState("");

  const set = (key, val) => setValues((prev) => ({ ...prev, [key]: val }));

  const result = useMemo(() => {
    const parse = (k) => { const v = parseFloat(values[k]); return Number.isFinite(v) && v >= 0 ? v : 0; };

    const eligibleItems = ELIGIBLE.map((e) => ({ ...e, amount: parse(e.key) }));
    const blockedItems = BLOCKED.map((b) => ({ ...b, amount: parse(b.key) }));

    const eligibleTotal = eligibleItems.reduce((s, e) => s + e.amount, 0);
    const blockedTotal = blockedItems.reduce((s, b) => s + b.amount, 0);
    const totalGst = Math.round((eligibleTotal + blockedTotal) * 100) / 100;

    if (totalGst <= 0) return null;

    const et = parseFloat(exemptTurnover) || 0;
    const tt = parseFloat(totalTurnover) || 0;
    const proportionalReversal = et > 0 && tt > 0
      ? Math.round(eligibleTotal * (et / tt) * 100) / 100
      : 0;

    const netItc = Math.round(Math.max(0, eligibleTotal - proportionalReversal) * 100) / 100;
    const utilisation = totalGst > 0 ? Math.round((netItc / totalGst) * 10000) / 100 : 0;

    track("itc_calculate", { totalGst, netItc });

    return {
      eligibleItems, blockedItems,
      eligibleTotal: Math.round(eligibleTotal * 100) / 100,
      blockedTotal: Math.round(blockedTotal * 100) / 100,
      totalGst, proportionalReversal, netItc, utilisation,
    };
  }, [values, exemptTurnover, totalTurnover]);

  return (
    <div className="tool-page">
      <SeoHead
        title="Free ITC Calculator — Input Tax Credit with Blocked Credits"
        description="Calculate your net Input Tax Credit after applying blocked credit rules under Section 17(5). Category-wise breakdown with proportional reversal for exempt supplies. Free."
        path="/itc-calculator"
        jsonLd={[TOOL_SCHEMA, HOWTO_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">ITC Calculator</h1>
          <p className="tool-subtitle">
            Calculate your net Input Tax Credit after blocked credits and proportional reversal. No sign-up required.
          </p>

          <div className="how-it-works">
            <h2 className="how-it-works-title">How It Works</h2>
            <div className="how-it-works-steps">
              <div className="how-it-works-step">
                <div className="how-it-works-num">1</div>
                <h3>Enter GST Paid</h3>
                <p>Enter GST amounts paid under different purchase categories</p>
              </div>
              <div className="how-it-works-step">
                <div className="how-it-works-num">2</div>
                <h3>Review Blocked Credits</h3>
                <p>See which credits are blocked under Section 17(5)</p>
              </div>
              <div className="how-it-works-step">
                <div className="how-it-works-num">3</div>
                <h3>Get Net ITC</h3>
                <p>Get your net claimable Input Tax Credit amount</p>
              </div>
            </div>
          </div>

          <div className="calc-card">
            <h3 className="calc-section-heading">Eligible Purchases (GST paid)</h3>
            {ELIGIBLE.map((e) => (
              <label key={e.key} className="calc-label">
                {e.label} (₹)
                <input
                  type="number"
                  className="calc-input"
                  value={values[e.key]}
                  onChange={(ev) => set(e.key, ev.target.value)}
                  placeholder="0"
                  min="0"
                  step="0.01"
                  inputMode="decimal"
                />
              </label>
            ))}

            <h3 className="calc-section-heading">Blocked Credits — Section 17(5)</h3>
            {BLOCKED.map((b) => (
              <label key={b.key} className="calc-label">
                {b.label} — {b.section} (₹)
                <input
                  type="number"
                  className="calc-input"
                  value={values[b.key]}
                  onChange={(ev) => set(b.key, ev.target.value)}
                  placeholder="0"
                  min="0"
                  step="0.01"
                  inputMode="decimal"
                />
              </label>
            ))}

            <h3 className="calc-section-heading">Proportional Reversal — Section 17(2)</h3>
            <label className="calc-label">
              Turnover from Exempt Supplies (₹)
              <input
                type="number"
                className="calc-input"
                value={exemptTurnover}
                onChange={(e) => setExemptTurnover(e.target.value)}
                placeholder="0"
                min="0"
                inputMode="decimal"
              />
            </label>
            <label className="calc-label">
              Total Turnover (₹)
              <input
                type="number"
                className="calc-input"
                value={totalTurnover}
                onChange={(e) => setTotalTurnover(e.target.value)}
                placeholder="0"
                min="0"
                inputMode="decimal"
              />
            </label>

            <div style={{ padding: "0.75rem 1rem", background: "rgba(245,158,66,0.1)", border: "1px solid rgba(245,158,66,0.3)", borderRadius: "0.5rem", marginTop: "1rem", fontSize: "0.85rem", lineHeight: 1.6 }}>
              <strong style={{ color: "#f59e42" }}>GST 2.0 — Hard ITC Validation</strong>
              <p style={{ margin: "0.5rem 0 0" }}>
                Under GST 2.0, the GST portal now applies <strong>hard blocks</strong> on ITC
                claims that do not match GSTR-2B. If your claimed ITC exceeds the amount
                reflected in GSTR-2B, the excess will be <strong>automatically rejected</strong> during
                GSTR-3B filing — you will not be able to submit the return until the mismatch
                is resolved. Ensure all supplier invoices appear in your GSTR-2B before claiming ITC.
              </p>
            </div>

            {result && (
              <div className="calc-result" aria-live="polite">
                <div className="calc-result-row">
                  <span>Eligible ITC (Business + Capital)</span>
                  <strong>{formatINR(result.eligibleTotal)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>Blocked Credits (Section 17(5))</span>
                  <strong className="calc-blocked">{formatINR(result.blockedTotal)}</strong>
                </div>
                {result.proportionalReversal > 0 && (
                  <div className="calc-result-row">
                    <span>Proportional Reversal (Section 17(2))</span>
                    <strong className="calc-blocked">{formatINR(result.proportionalReversal)}</strong>
                  </div>
                )}
                <div className="calc-result-row">
                  <span>Total GST Paid</span>
                  <strong>{formatINR(result.totalGst)}</strong>
                </div>
                <div className="calc-result-row calc-total">
                  <span>Net Claimable ITC</span>
                  <strong>{formatINR(result.netItc)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>ITC Utilisation</span>
                  <strong>{result.utilisation}%</strong>
                </div>

                <div className="calc-result-actions">
                  <ShareButtons
                    path="/itc-calculator"
                    text={`Net ITC: ${formatINR(result.netItc)} out of ${formatINR(result.totalGst)} GST paid (${result.utilisation}%) — calculated free on DoAide GST`}
                  />
                  <PrintButton label="Print Result" />
                </div>
              </div>
            )}
          </div>

          <EmailCapture
            source="itc-calculator"
            heading="Get ITC rule updates"
            subtext="Stay updated when ITC rules or blocked credit lists change — free email alerts."
            buttonLabel="Notify Me"
            compact
          />

          <section className="tool-info">
            <h2>How ITC Calculation Works</h2>
            <p>
              Input Tax Credit lets you offset GST paid on business purchases against your
              output tax liability. However, not all GST paid is claimable — credits on
              certain categories are &ldquo;blocked&rdquo; under Section 17(5), and credits
              used for exempt supplies must be reversed proportionally under Section 17(2).
            </p>
            <h3>Eligible Credits</h3>
            <ul>
              <li>Goods and services used for business purposes</li>
              <li>Capital goods used for taxable supplies</li>
              <li>Inputs used in manufacturing or trading</li>
            </ul>
            <h3>Blocked Credits — Section 17(5)</h3>
            <ul>
              <li>Motor vehicles and conveyances (except for specified business uses)</li>
              <li>Food, beverages, outdoor catering, beauty treatment</li>
              <li>Club memberships, health and fitness centre</li>
              <li>Personal consumption</li>
              <li>Gifts, free samples, destroyed/lost goods</li>
              <li>Construction of immovable property (except plant &amp; machinery)</li>
            </ul>
          </section>

          <section className="tool-info">
            <h2>Frequently Asked Questions</h2>

            <h3>How is ITC calculated under GST?</h3>
            <p>
              Total GST on eligible purchases minus blocked credits under Section 17(5)
              minus proportional reversal for exempt supplies. The remaining amount is
              your net claimable ITC.
            </p>

            <h3>What are blocked credits under Section 17(5)?</h3>
            <p>
              GST on motor vehicles, food and beverages, club memberships, personal use,
              gifts, and construction cannot be claimed as ITC, with certain narrow exceptions
              (e.g. vehicles used for goods transport).
            </p>

            <h3>What is proportional ITC reversal under Section 17(2)?</h3>
            <p>
              When you make both taxable and exempt supplies, ITC must be reversed in
              proportion to exempt turnover: Reversal = Eligible ITC &times;
              (Exempt Turnover &divide; Total Turnover).
            </p>

            <h3>Can ITC be claimed on capital goods?</h3>
            <p>
              Yes, ITC on capital goods used for business is available in full in the
              period the goods are received. No installments are required under GST.
            </p>

            <h3>What is the time limit for claiming ITC?</h3>
            <p>
              ITC must be claimed by the earlier of: filing GSTR-3B for September of
              the following year, or filing GSTR-9 for that year.
            </p>
          </section>

          <InlineCTA variant="save" />
          <RelatedTools current="/itc-calculator" />
          <CrossProductLinks page="itc-calculator" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
      <WhatsAppFloat path="/itc-calculator" text="Free ITC Calculator — calculate Input Tax Credit eligibility" />
    </div>
  );
}
