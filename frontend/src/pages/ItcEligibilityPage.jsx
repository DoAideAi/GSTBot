import { useMemo, useState } from "react";
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
import { formatINR } from "../lib/gstCalc";

const PURCHASE_TYPES = [
  { key: "business_goods", label: "Goods for business use", eligible: true },
  { key: "business_services", label: "Services for business use", eligible: true },
  { key: "capital_goods", label: "Capital goods for business", eligible: true },
  { key: "motor_vehicle", label: "Motor vehicles (except specified)", eligible: false, reason: "ITC blocked under Section 17(5)(a) — motor vehicles and conveyances, except when used for transportation of goods, passengers (>13 seats), or driving training." },
  { key: "food_beverages", label: "Food & beverages, outdoor catering", eligible: false, reason: "ITC blocked under Section 17(5)(b)(i) — food and beverages, outdoor catering, beauty treatment, health services, cosmetic and plastic surgery, unless used for further supply of the same category." },
  { key: "membership", label: "Club membership, health & fitness", eligible: false, reason: "ITC blocked under Section 17(5)(b)(ii) — membership of a club, health and fitness centre." },
  { key: "personal_use", label: "Goods/services for personal use", eligible: false, reason: "ITC blocked under Section 17(5)(g) — goods or services used for personal consumption." },
  { key: "gift", label: "Gifts and free samples", eligible: false, reason: "ITC blocked under Section 17(5)(h) — goods lost, stolen, destroyed, written off, or disposed of by way of gift or free samples." },
  { key: "construction", label: "Construction of immovable property", eligible: false, reason: "ITC blocked under Section 17(5)(d) — construction of immovable property (except plant and machinery) on own account, including when used for business." },
  { key: "composition", label: "Purchases by composition dealer", eligible: false, reason: "ITC not available under Section 10 — composition scheme dealers cannot claim input tax credit." },
  { key: "exempt_supply", label: "Used for exempt supplies", eligible: false, reason: "ITC must be reversed under Section 17(2) — when goods/services are used for making exempt supplies, ITC attributable to exempt supplies must be reversed." },
];

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST Input Tax Credit Eligibility Checker",
  url: "https://gst.doaide.com/input-tax-credit",
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
      name: "What is Input Tax Credit (ITC) under GST?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "ITC allows businesses to reduce GST liability by claiming credit for GST paid on business purchases. It ensures tax is levied only on value addition at each stage of the supply chain.",
      },
    },
    {
      "@type": "Question",
      name: "What are blocked credits under Section 17(5)?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "GST on motor vehicles (with exceptions), food, club memberships, personal use, gifts, construction (except plant/machinery), and composition scheme purchases.",
      },
    },
    {
      "@type": "Question",
      name: "What are the conditions for claiming ITC?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Valid tax invoice required, goods/services received, supplier paid GST, return filed, invoice in GSTR-2B, and payment to supplier within 180 days.",
      },
    },
    {
      "@type": "Question",
      name: "Can ITC be claimed on motor vehicles?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Blocked under Section 17(5)(a). Exceptions: vehicles for transporting goods, passenger transport (>13 seats), driving training, or further supply (dealers/lessors).",
      },
    },
    {
      "@type": "Question",
      name: "What happens if payment is not made within 180 days?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "If payment is not made to the supplier within 180 days of the invoice date, the ITC claimed must be reversed along with interest. The credit can be reclaimed when payment is eventually made.",
      },
    },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "ITC Eligibility Checker" },
];

const CONDITIONS = [
  { key: "tax_invoice", label: "I have a valid tax invoice or debit note" },
  { key: "goods_received", label: "Goods/services have been received" },
  { key: "tax_paid", label: "Supplier has paid the GST to the government" },
  { key: "return_filed", label: "I have filed the relevant GST return" },
  { key: "gstr2b", label: "Invoice appears in my GSTR-2B" },
  { key: "payment_180", label: "Payment made to supplier within 180 days" },
];

export default function ItcEligibilityPage() {
  usePageTitle("GST Input Tax Credit Eligibility Checker — ITC Calculator");

  const [purchaseType, setPurchaseType] = useState("business_goods");
  const [gstAmount, setGstAmount] = useState("");
  const [conditions, setConditions] = useState({
    tax_invoice: true,
    goods_received: true,
    tax_paid: true,
    return_filed: true,
    gstr2b: true,
    payment_180: true,
  });

  const selected = PURCHASE_TYPES.find((p) => p.key === purchaseType);

  const result = useMemo(() => {
    if (!selected) return null;
    const amount = parseFloat(gstAmount);
    if (!Number.isFinite(amount) || amount <= 0) return null;

    if (!selected.eligible) {
      return {
        eligible: false,
        amount: 0,
        reason: selected.reason,
        unmetConditions: [],
      };
    }

    const unmet = CONDITIONS.filter((c) => !conditions[c.key]);
    if (unmet.length > 0) {
      return {
        eligible: false,
        amount: 0,
        reason: "ITC conditions not fully met. All conditions must be satisfied to claim ITC.",
        unmetConditions: unmet,
      };
    }

    return {
      eligible: true,
      amount,
      reason: "This purchase is eligible for Input Tax Credit. Ensure the invoice is reflected in your GSTR-2B before claiming.",
      unmetConditions: [],
    };
  }, [purchaseType, gstAmount, conditions, selected]);

  function toggleCondition(key) {
    setConditions((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  return (
    <div className="tool-page">
      <SeoHead
        title="GST Input Tax Credit Eligibility Checker — Free ITC Tool"
        description="Check if your purchase is eligible for Input Tax Credit under GST. Enter purchase details to see ITC eligibility, blocked credits, and conditions. Free, no login required."
        path="/input-tax-credit"
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">ITC Eligibility Checker</h1>
          <p className="tool-subtitle">
            Check if your purchase qualifies for Input Tax Credit under GST. No sign-up required.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Type of Purchase
              <select
                className="calc-select"
                value={purchaseType}
                onChange={(e) => setPurchaseType(e.target.value)}
              >
                {PURCHASE_TYPES.map((p) => (
                  <option key={p.key} value={p.key}>{p.label}</option>
                ))}
              </select>
            </label>

            <label className="calc-label">
              GST Amount on Invoice (₹)
              <input
                type="number"
                className="calc-input"
                value={gstAmount}
                onChange={(e) => setGstAmount(e.target.value)}
                placeholder="Enter GST amount paid"
                min="0"
                step="0.01"
                inputMode="decimal"
                autoFocus
              />
            </label>

            {selected?.eligible && (
              <fieldset style={{ border: "none", padding: 0, margin: "0.5rem 0" }}>
                <legend style={{ fontWeight: 600, marginBottom: "0.5rem" }}>ITC Conditions (Section 16(2))</legend>
                {CONDITIONS.map((c) => (
                  <label key={c.key} className="calc-checkbox-label">
                    <input
                      type="checkbox"
                      checked={conditions[c.key]}
                      onChange={() => toggleCondition(c.key)}
                    />
                    {c.label}
                  </label>
                ))}
              </fieldset>
            )}

            {result && (
              <div className="calc-result" aria-live="polite">
                <div className="calc-result-row calc-total" style={{ color: result.eligible ? "#34d399" : "#f87171" }}>
                  <span>ITC Eligibility</span>
                  <strong>{result.eligible ? "Eligible" : "Not Eligible"}</strong>
                </div>
                {result.eligible && (
                  <div className="calc-result-row">
                    <span>Claimable ITC</span>
                    <strong>{formatINR(result.amount)}</strong>
                  </div>
                )}
                <p style={{ margin: "0.5rem 0", fontSize: "0.95rem", lineHeight: 1.5 }}>
                  {result.reason}
                </p>
                {result.unmetConditions.length > 0 && (
                  <ul style={{ margin: "0.5rem 0", paddingLeft: "1.25rem", fontSize: "0.9rem" }}>
                    {result.unmetConditions.map((c) => (
                      <li key={c.key} style={{ color: "#f87171" }}>{c.label}</li>
                    ))}
                  </ul>
                )}
                <div className="calc-result-actions">
                  <ShareButtons
                    path="/input-tax-credit"
                    text={`ITC ${result.eligible ? "eligible" : "not eligible"} — checked free on DoAide GST`}
                  />
                  <PrintButton label="Print Result" />
                </div>
              </div>
            )}
          </div>

          <EmailCapture
            source="itc-eligibility"
            heading="Stay updated on ITC rules"
            subtext="Get notified when ITC rules change — free email alerts."
            buttonLabel="Notify Me"
            compact
          />

          <section className="tool-info">
            <h2>Input Tax Credit (ITC) Under GST</h2>
            <p>
              Input Tax Credit allows businesses to reduce their GST liability by claiming
              credit for GST paid on business purchases. ITC is the backbone of GST&apos;s
              value-added tax mechanism.
            </p>
            <h3>Conditions for Claiming ITC (Section 16)</h3>
            <ul>
              <li>Possession of a valid tax invoice or debit note</li>
              <li>Goods or services must have been received</li>
              <li>Supplier must have paid the tax to the government</li>
              <li>The buyer must have filed the relevant return</li>
              <li>Invoice must appear in GSTR-2B</li>
              <li>Payment must be made to supplier within 180 days of invoice date</li>
            </ul>
            <h3>Blocked Credits (Section 17(5))</h3>
            <ul>
              <li>Motor vehicles and conveyances (with exceptions)</li>
              <li>Food, beverages, outdoor catering, beauty treatment, health services</li>
              <li>Club membership, fitness centre</li>
              <li>Life insurance, health insurance (unless obligatory for employees)</li>
              <li>Construction of immovable property (except plant & machinery)</li>
              <li>Goods/services for personal consumption</li>
              <li>Gifts and free samples</li>
              <li>Tax paid under composition scheme</li>
            </ul>
          </section>

          <section className="tool-info">
            <h2>Frequently Asked Questions</h2>

            <h3>What is Input Tax Credit (ITC) under GST?</h3>
            <p>
              ITC allows businesses to reduce their GST liability by claiming credit for GST
              paid on business purchases. It ensures tax is levied only on value addition
              at each stage of the supply chain.
            </p>

            <h3>What are blocked credits under Section 17(5)?</h3>
            <p>
              Blocked credits include GST on motor vehicles (with exceptions), food &amp;
              beverages, club memberships, personal consumption, gifts, construction of
              immovable property (except plant &amp; machinery), and composition scheme purchases.
            </p>

            <h3>What are the conditions for claiming ITC?</h3>
            <p>
              Under Section 16(2): valid tax invoice, goods/services received, supplier has
              paid GST, relevant return filed, invoice appears in GSTR-2B, and payment made
              to supplier within 180 days.
            </p>

            <h3>Can ITC be claimed on motor vehicles?</h3>
            <p>
              Generally blocked. Exceptions: vehicles for goods transport, passenger transport
              (&gt;13 seats), driving training, or further supply by dealers/lessors.
            </p>

            <h3>What happens if payment is not made within 180 days?</h3>
            <p>
              The ITC claimed must be reversed with interest. The credit can be reclaimed
              when payment is eventually made to the supplier.
            </p>
          </section>

          <RelatedTools current="/input-tax-credit" />
          <CrossProductLinks page="input-tax-credit" />
        </div>
      </main>
      <DoAideFooter />
    </div>
  );
}
