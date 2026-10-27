import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import FaqSection, { faqSchema } from "../components/FaqSection";
import PrintButton from "../components/PrintButton";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { formatINR } from "../lib/gstCalc";
import { BUSINESS_TYPES, checkRegistration, STATES } from "../lib/gstRegistration";

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST Registration Eligibility Checker",
  url: "https://gst.doaide.com/registration-checker",
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const FAQS = [
  {
    q: "What is the turnover limit for GST registration?",
    a: "₹40 lakh for businesses selling only goods, and ₹20 lakh for services or a mix. Manipur, Mizoram, Nagaland and Tripura use ₹10 lakh for both. Ten states, Telangana included, keep goods at ₹20 lakh or ₹10 lakh.",
  },
  {
    q: "Which states have a lower GST registration limit?",
    a: "Manipur, Mizoram, Nagaland and Tripura: ₹10 lakh for everything. Arunachal Pradesh, Meghalaya, Puducherry, Sikkim, Telangana and Uttarakhand: ₹20 lakh for goods. Assam, Himachal Pradesh and J&K use the normal limits.",
  },
  {
    q: "Is GST registration mandatory for e-commerce sellers?",
    a: "For goods sold to other states, yes. Since 1 October 2023, goods sold only within your state through a marketplace need no registration below the limit, only an enrolment number. Services sold through a marketplace are exempt below the limit too.",
  },
  {
    q: "Do I need GST registration for inter-state supply?",
    a: "For goods, yes, from the first sale under Section 24(i). Inter-state services are exempt until turnover crosses the Section 22 limit, under Notification 10/2017-Integrated Tax.",
  },
  {
    q: "Who must register for GST whatever the turnover?",
    a: "Section 24 lists them: inter-state goods sellers, casual and non-resident taxable persons, input service distributors, reverse charge payers, agents of other suppliers, TDS deductors and e-commerce operators.",
  },
  {
    q: "How is aggregate turnover counted for GST registration?",
    a: "Across all branches under one PAN, all-India. It includes taxable, exempt and export supplies and inter-branch transfers to other states, but excludes the GST itself and inward reverse-charge supplies.",
  },
];

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "Registration Eligibility" },
];

export default function RegistrationCheckerPage() {
  usePageTitle("GST Registration Eligibility Checker — Do I Need GST?");

  const [type, setType] = useState("goods");
  const [turnover, setTurnover] = useState("");
  const [state, setState] = useState("");
  const [interState, setInterState] = useState(false);
  const [ecommerce, setEcommerce] = useState(false);

  const compulsoryType = ["casual", "nonresident", "isd"].includes(type);
  const result = useMemo(
    () => checkRegistration({ type, turnover, state, interState, ecommerce }),
    [type, turnover, state, interState, ecommerce],
  );
  const invalid = !compulsoryType && turnover !== "" && state !== "" && result === null;

  return (
    <div className="tool-page">
      <SeoHead
        title="GST Registration Eligibility Checker — Do I Need GST? (2026)"
        description="Check if you need GST registration: the ₹40 lakh, ₹20 lakh or ₹10 lakh limit for your state, inter-state and e-commerce rules, and the Section 22 or 24 that applies. Free."
        path="/registration-checker"
        jsonLd={[TOOL_SCHEMA, faqSchema(FAQS)]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb items={[{ label: "Home", to: "/" }, { label: "Registration Eligibility" }]} />
          <h1 className="tool-title">GST Registration Eligibility Checker</h1>
          <p className="tool-subtitle">
            Whether your business has to register for GST, the turnover limit for your state, and
            the section that decides it. No sign-up required.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Business type
              <select className="calc-input" value={type} onChange={(e) => setType(e.target.value)}>
                {BUSINESS_TYPES.map((b) => (
                  <option key={b.key} value={b.key}>{b.label}</option>
                ))}
              </select>
            </label>

            {!compulsoryType && (
              <>
                <label className="calc-label">
                  Aggregate annual turnover, all branches under your PAN (₹)
                  <input
                    type="number"
                    className="calc-input"
                    value={turnover}
                    onChange={(e) => setTurnover(e.target.value)}
                    placeholder="e.g. 2500000"
                    min="0"
                    inputMode="decimal"
                  />
                </label>

                <label className="calc-label">
                  State or UT of business
                  <select className="calc-input" value={state} onChange={(e) => setState(e.target.value)}>
                    <option value="">Select state</option>
                    {STATES.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </label>

                <label className="calc-checkbox-label">
                  <input type="checkbox" checked={interState} onChange={(e) => setInterState(e.target.checked)} />
                  {type === "services" ? "I supply services to clients in other states" : "I sell goods to buyers in other states"}
                </label>

                <label className="calc-checkbox-label">
                  <input type="checkbox" checked={ecommerce} onChange={(e) => setEcommerce(e.target.checked)} />
                  I sell through e-commerce platforms (Amazon, Flipkart, Meesho)
                </label>
              </>
            )}

            {invalid && (
              <p className="calc-error" role="alert">
                Enter a turnover of zero or more.
              </p>
            )}

            {result && (
              <div className="calc-result" aria-live="polite">
                <div
                  className="calc-result-row calc-total"
                  style={{ color: result.required ? "#f59e42" : "#34d399" }}
                >
                  <span>GST registration</span>
                  <strong>{result.required ? "Required" : "Not required"}</strong>
                </div>
                {result.threshold && (
                  <div className="calc-result-row">
                    <span>Turnover limit for {state}</span>
                    <strong>{formatINR(result.threshold.limit)}</strong>
                  </div>
                )}

                {result.reasons.length > 0 ? (
                  <ul style={{ margin: "0.75rem 0", paddingLeft: "1.25rem", fontSize: "0.95rem", lineHeight: 1.6 }}>
                    {result.reasons.map((r) => (
                      <li key={r.section}><strong>{r.section}:</strong> {r.text}</li>
                    ))}
                  </ul>
                ) : (
                  <p>
                    Turnover is within the {result.threshold.section} limit and nothing in Section 24
                    applies. You may still register voluntarily to claim input tax credit.
                  </p>
                )}
                {result.notes.map((n) => (
                  <p key={n} className="calc-note">{n}</p>
                ))}
                {result.required && !compulsoryType && (
                  <p>
                    Turnover under ₹1.5 crore? Check the{" "}
                    <Link to="/tools/composition-scheme-checker">composition scheme</Link> before you apply.
                  </p>
                )}

                <div className="calc-result-actions">
                  <ShareButtons
                    path="/registration-checker"
                    text={`GST registration ${result.required ? "required" : "not required"} — checked free on DoAide GST`}
                  />
                  <PrintButton label="Print Result" />
                </div>
              </div>
            )}
          </div>

          <EmailCapture
            source="registration-checker"
            heading="Need help with GST registration?"
            subtext="Get a free step-by-step guide to register for GST in India."
            buttonLabel="Get Guide"
            compact
          />

          <section className="tool-info">
            <h2>GST registration limits by state</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>States and UTs</th><th>Goods only</th><th>Services or both</th></tr>
                </thead>
                <tbody>
                  <tr><td>All others, including Assam, Himachal Pradesh and J&amp;K</td><td>₹40 lakh</td><td>₹20 lakh</td></tr>
                  <tr><td>Arunachal Pradesh, Meghalaya, Puducherry, Sikkim, Telangana, Uttarakhand</td><td>₹20 lakh</td><td>₹20 lakh</td></tr>
                  <tr><td>Manipur, Mizoram, Nagaland, Tripura</td><td>₹10 lakh</td><td>₹10 lakh</td></tr>
                </tbody>
              </table>
            </div>
            <h3>Registration whatever the turnover (Section 24)</h3>
            <ul>
              <li>Selling goods to another state</li>
              <li>Casual and non-resident taxable persons</li>
              <li>Paying tax under <Link to="/reverse-charge">reverse charge</Link></li>
              <li>Agents supplying on behalf of others, and input service distributors</li>
              <li>E-commerce operators, and TDS deductors under Section 51</li>
            </ul>
            <p>
              Not sure which kind of registration fits? Try the{" "}
              <Link to="/registration-type-advisor">registration type advisor</Link>. See every
              limit side by side on the <Link to="/turnover-limit">turnover limit page</Link>.
              Registering late carries a penalty — see the{" "}
              <Link to="/gst-offence-penalty-calculator">offence penalty calculator</Link>.
            </p>
          </section>

          <FaqSection faqs={FAQS} />

          <InlineCTA variant="invoice" />
          <RelatedTools current="/registration-checker" />
          <CrossProductLinks page="registration-checker" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}

export { FAQS };
