import { useMemo, useState } from "react";
import Breadcrumb from "../components/Breadcrumb";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";

const ENTITY_TYPES = [
  { key: "proprietorship", label: "Proprietorship / Individual" },
  { key: "partnership", label: "Partnership Firm / LLP" },
  { key: "company", label: "Private / Public Company" },
  { key: "trust", label: "Trust / Society / NGO" },
  { key: "huf", label: "Hindu Undivided Family (HUF)" },
];

const SUPPLY_TYPES = [
  { key: "goods_only", label: "Only goods" },
  { key: "services_only", label: "Only services" },
  { key: "both", label: "Both goods and services" },
];

const REG_TYPES = {
  regular: {
    name: "Regular Registration",
    section: "Section 22",
    color: "#3b82f6",
    features: [
      "Can collect GST from customers",
      "Eligible for Input Tax Credit (ITC)",
      "Can make interstate supplies",
      "Must file GSTR-1, GSTR-3B monthly/quarterly",
      "No turnover ceiling after registration",
    ],
  },
  composition: {
    name: "Composition Scheme",
    section: "Section 10",
    color: "#34d399",
    features: [
      "Pay GST at fixed low rate on turnover",
      "Simpler filing: CMP-08 quarterly, GSTR-4 annual",
      "Cannot collect GST from customers",
      "Cannot claim ITC",
      "Cannot make interstate outward supplies",
    ],
  },
  casual: {
    name: "Casual Taxable Person",
    section: "Section 2(20)",
    color: "#f59e42",
    features: [
      "For occasional supply in a state where no fixed place of business exists",
      "Valid for 90 days (extendable by another 90 days)",
      "Must pay estimated tax in advance",
      "Eligible for ITC like regular registration",
      "Must file regular returns during validity period",
    ],
  },
  nri: {
    name: "Non-Resident Taxable Person",
    section: "Section 2(77)",
    color: "#a78bfa",
    features: [
      "For non-residents making taxable supply in India",
      "Valid for 90 days (extendable by another 90 days)",
      "Must pay estimated tax in advance",
      "Eligible for ITC on goods/services used in India",
      "Must appoint an authorized signatory in India",
    ],
  },
};

function advise(answers) {
  const { supplyScope, turnover, interstate, isResident, occasionalSupply, ecommerce } = answers;
  const results = [];
  const reasons = [];

  if (isResident === "no") {
    results.push("nri");
    reasons.push("You are a non-resident making taxable supplies in India — NRI registration under Section 2(77) is mandatory.");
    return { recommended: results, reasons, disqualified: [] };
  }

  if (occasionalSupply === "yes" && isResident === "yes") {
    results.push("casual");
    reasons.push("You occasionally supply in states where you have no fixed place of business — Casual Taxable Person registration applies.");
    results.push("regular");
    reasons.push("Alternatively, if you plan ongoing business, Regular registration gives you a permanent GSTIN.");
    return { recommended: results, reasons, disqualified: [] };
  }

  const disqualified = [];

  const compositionEligible = (() => {
    if (interstate === "yes") { disqualified.push("Composition: Interstate outward supply disqualifies you"); return false; }
    if (ecommerce === "yes") { disqualified.push("Composition: E-commerce supply disqualifies you"); return false; }
    if (supplyScope === "services_only" && Number(turnover) > 5000000) { disqualified.push("Composition: Service providers' turnover exceeds ₹50 lakh limit"); return false; }
    if (supplyScope !== "services_only" && Number(turnover) > 15000000) { disqualified.push("Composition: Turnover exceeds ₹1.5 crore limit"); return false; }
    return true;
  })();

  if (compositionEligible && Number(turnover) <= (supplyScope === "services_only" ? 5000000 : 15000000)) {
    results.push("composition");
    const rate = supplyScope === "services_only" ? "6%" : "1%";
    reasons.push(`Your turnover qualifies for Composition Scheme with a flat ${rate} tax rate and simplified compliance.`);
  }

  results.push("regular");
  reasons.push("Regular registration gives full ITC access, interstate supply capability, and no ceiling on operations.");

  return { recommended: results, reasons, disqualified };
}

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST Registration Type Advisor",
  url: "https://gst.doaide.com/registration-type-advisor",
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
      name: "What are the types of GST registration in India?",
      acceptedAnswer: { "@type": "Answer", text: "Four main types: Regular (most businesses), Composition Scheme (small businesses, simplified compliance), Casual Taxable Person (temporary interstate supply), and Non-Resident Taxable Person." },
    },
    {
      "@type": "Question",
      name: "Who should opt for Composition Scheme?",
      acceptedAnswer: { "@type": "Answer", text: "Businesses with turnover below ₹1.5 crore (goods) or ₹50 lakh (services) that do not make interstate supplies, do not sell on e-commerce platforms, and want simplified tax payment at 1-6% of turnover." },
    },
    {
      "@type": "Question",
      name: "What is a Casual Taxable Person under GST?",
      acceptedAnswer: { "@type": "Answer", text: "A person who occasionally supplies goods/services in a state where they do not have a fixed place of business. Registration is valid for 90 days and estimated tax must be paid in advance." },
    },
    {
      "@type": "Question",
      name: "Can I switch from Composition to Regular GST registration?",
      acceptedAnswer: { "@type": "Answer", text: "Yes, you can switch from Composition to Regular by filing Form GST CMP-04 before the start of a financial year. If your turnover exceeds the threshold mid-year, you will be compulsorily migrated to Regular." },
    },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "Registration Type Advisor" },
];

export default function RegistrationTypeAdvisorPage() {
  usePageTitle("GST Registration Type Advisor — Which Registration Suits Your Business?");

  const [answers, setAnswers] = useState({
    entityType: "proprietorship",
    supplyScope: "goods_only",
    turnover: "",
    interstate: "no",
    isResident: "yes",
    occasionalSupply: "no",
    ecommerce: "no",
  });

  const result = useMemo(() => {
    if (!answers.turnover && answers.isResident === "yes" && answers.occasionalSupply === "no") return null;
    return advise(answers);
  }, [answers]);

  const update = (key, value) => setAnswers((prev) => ({ ...prev, [key]: value }));

  return (
    <div className="tool-page">
      <SeoHead
        title="GST Registration Type Advisor — Which Registration Suits Your Business?"
        description="Find the right GST registration type for your business — Regular, Composition, Casual, or NRI. Answer a few questions and get a personalized recommendation. Free, no login required."
        path="/registration-type-advisor"
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">GST Registration Type Advisor</h1>
          <p className="tool-subtitle">
            Find the right GST registration type for your business. No sign-up required.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Entity Type
              <select className="calc-select" value={answers.entityType} onChange={(e) => update("entityType", e.target.value)}>
                {ENTITY_TYPES.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
              </select>
            </label>

            <label className="calc-label">
              Nature of Supply
              <select className="calc-select" value={answers.supplyScope} onChange={(e) => update("supplyScope", e.target.value)}>
                {SUPPLY_TYPES.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
              </select>
            </label>

            <label className="calc-label">
              Expected Annual Turnover (₹)
              <input
                type="number"
                className="calc-input"
                value={answers.turnover}
                onChange={(e) => update("turnover", e.target.value)}
                placeholder="Enter expected annual turnover"
                min="0"
                inputMode="numeric"
                autoFocus
              />
            </label>

            <label className="calc-checkbox-label">
              <input type="checkbox" checked={answers.interstate === "yes"} onChange={(e) => update("interstate", e.target.checked ? "yes" : "no")} />
              I make or plan to make interstate outward supplies
            </label>

            <label className="calc-checkbox-label">
              <input type="checkbox" checked={answers.ecommerce === "yes"} onChange={(e) => update("ecommerce", e.target.checked ? "yes" : "no")} />
              I supply through e-commerce platforms
            </label>

            <label className="calc-checkbox-label">
              <input type="checkbox" checked={answers.isResident === "no"} onChange={(e) => update("isResident", e.target.checked ? "no" : "yes")} />
              I am a non-resident (no fixed place of business in India)
            </label>

            <label className="calc-checkbox-label">
              <input type="checkbox" checked={answers.occasionalSupply === "yes"} onChange={(e) => update("occasionalSupply", e.target.checked ? "yes" : "no")} />
              I occasionally supply in states where I have no fixed business
            </label>

            {result && (
              <div className="calc-result" aria-live="polite">
                <h3 style={{ margin: "0 0 1rem", fontSize: "1.1rem" }}>Recommended Registration Type{result.recommended.length > 1 ? "s" : ""}</h3>

                {result.recommended.map((type, i) => {
                  const info = REG_TYPES[type];
                  return (
                    <div key={type} style={{ marginBottom: "1.5rem", padding: "1rem", background: "var(--surface-2, #1a1a2e)", borderRadius: "0.5rem", borderLeft: `4px solid ${info.color}` }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
                        <strong style={{ color: info.color, fontSize: "1.05rem" }}>
                          {i === 0 ? "★ " : ""}{info.name}
                        </strong>
                        <span style={{ fontSize: "0.8rem", color: "var(--ink-soft)", background: "var(--surface-3, #252540)", padding: "2px 8px", borderRadius: "4px" }}>{info.section}</span>
                      </div>
                      <p style={{ margin: "0.25rem 0 0.75rem", fontSize: "0.9rem", color: "var(--ink-soft)", lineHeight: 1.5 }}>
                        {result.reasons[i]}
                      </p>
                      <ul style={{ margin: 0, paddingLeft: "1.25rem", fontSize: "0.85rem", lineHeight: 1.8 }}>
                        {info.features.map((f, j) => <li key={j}>{f}</li>)}
                      </ul>
                    </div>
                  );
                })}

                {result.disqualified.length > 0 && (
                  <div style={{ marginTop: "0.5rem", padding: "0.75rem", background: "rgba(248,113,113,0.08)", borderRadius: "0.5rem", fontSize: "0.85rem" }}>
                    <strong style={{ color: "#f87171" }}>Not eligible for:</strong>
                    <ul style={{ margin: "0.5rem 0 0", paddingLeft: "1.25rem", lineHeight: 1.8 }}>
                      {result.disqualified.map((d, i) => <li key={i}>{d}</li>)}
                    </ul>
                  </div>
                )}

                <div className="calc-result-actions">
                  <ShareButtons
                    path="/registration-type-advisor"
                    text={`GST Registration: ${result.recommended.map((t) => REG_TYPES[t].name).join(" or ")} — find your type free on DoAide GST`}
                  />
                </div>
              </div>
            )}
          </div>

          <EmailCapture
            source="registration-type-advisor"
            heading="Stay updated on GST registration changes"
            subtext="Get notified when registration rules change — free email alerts."
            buttonLabel="Notify Me"
            compact
          />

          <section className="tool-info">
            <h2>GST Registration Types — Complete Comparison</h2>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem", lineHeight: 1.6, marginTop: "1rem" }}>
              <thead>
                <tr style={{ borderBottom: "2px solid var(--ink-soft)" }}>
                  <th style={{ textAlign: "left", padding: "0.5rem" }}>Feature</th>
                  <th style={{ textAlign: "left", padding: "0.5rem" }}>Regular</th>
                  <th style={{ textAlign: "left", padding: "0.5rem" }}>Composition</th>
                  <th style={{ textAlign: "left", padding: "0.5rem" }}>Casual</th>
                  <th style={{ textAlign: "left", padding: "0.5rem" }}>NRI</th>
                </tr>
              </thead>
              <tbody>
                <tr style={{ borderBottom: "1px solid var(--surface-3, #252540)" }}><td style={{ padding: "0.5rem" }}>ITC Eligible</td><td style={{ padding: "0.5rem" }}>Yes</td><td style={{ padding: "0.5rem" }}>No</td><td style={{ padding: "0.5rem" }}>Yes</td><td style={{ padding: "0.5rem" }}>Yes</td></tr>
                <tr style={{ borderBottom: "1px solid var(--surface-3, #252540)" }}><td style={{ padding: "0.5rem" }}>Collect GST</td><td style={{ padding: "0.5rem" }}>Yes</td><td style={{ padding: "0.5rem" }}>No</td><td style={{ padding: "0.5rem" }}>Yes</td><td style={{ padding: "0.5rem" }}>Yes</td></tr>
                <tr style={{ borderBottom: "1px solid var(--surface-3, #252540)" }}><td style={{ padding: "0.5rem" }}>Interstate Supply</td><td style={{ padding: "0.5rem" }}>Yes</td><td style={{ padding: "0.5rem" }}>No</td><td style={{ padding: "0.5rem" }}>Yes</td><td style={{ padding: "0.5rem" }}>Yes</td></tr>
                <tr style={{ borderBottom: "1px solid var(--surface-3, #252540)" }}><td style={{ padding: "0.5rem" }}>Validity</td><td style={{ padding: "0.5rem" }}>Permanent</td><td style={{ padding: "0.5rem" }}>Permanent</td><td style={{ padding: "0.5rem" }}>90 days</td><td style={{ padding: "0.5rem" }}>90 days</td></tr>
                <tr style={{ borderBottom: "1px solid var(--surface-3, #252540)" }}><td style={{ padding: "0.5rem" }}>Tax Rate</td><td style={{ padding: "0.5rem" }}>Standard rates</td><td style={{ padding: "0.5rem" }}>1-6% on turnover</td><td style={{ padding: "0.5rem" }}>Standard rates</td><td style={{ padding: "0.5rem" }}>Standard rates</td></tr>
                <tr><td style={{ padding: "0.5rem" }}>Filing</td><td style={{ padding: "0.5rem" }}>GSTR-1, 3B</td><td style={{ padding: "0.5rem" }}>CMP-08, GSTR-4</td><td style={{ padding: "0.5rem" }}>GSTR-1, 3B</td><td style={{ padding: "0.5rem" }}>GSTR-5</td></tr>
              </tbody>
            </table>
          </section>

          <section className="tool-info">
            <h2>Frequently Asked Questions</h2>

            <h3>What are the types of GST registration in India?</h3>
            <p>There are four main types: Regular (for most businesses), Composition Scheme (for small businesses with simplified compliance), Casual Taxable Person (for temporary interstate supply), and Non-Resident Taxable Person (for non-residents supplying in India).</p>

            <h3>Who should opt for Composition Scheme?</h3>
            <p>Businesses with turnover below ₹1.5 crore (goods) or ₹50 lakh (services) that do not make interstate supplies, do not sell on e-commerce platforms, and want simplified tax payment at 1-6% of turnover.</p>

            <h3>What is a Casual Taxable Person under GST?</h3>
            <p>A person who occasionally supplies goods or services in a state where they do not have a fixed place of business. Registration is valid for 90 days (extendable by 90 more) and estimated tax must be paid in advance.</p>

            <h3>Can I switch from Composition to Regular GST registration?</h3>
            <p>Yes, you can switch by filing Form GST CMP-04 before the start of a financial year. If your turnover exceeds the threshold mid-year, you will be compulsorily migrated to Regular.</p>

            <h3>What documents are needed for GST registration?</h3>
            <p>PAN card, Aadhaar card, business address proof, bank account details, photographs, and for companies/LLPs: incorporation certificate and board resolution. Casual and NRI registrants also need advance tax challan.</p>
          </section>

          <RelatedTools current="/registration-type-advisor" />
          <CrossProductLinks page="registration-type-advisor" />
        </div>
      </main>
      <DoAideFooter />
    </div>
  );
}
