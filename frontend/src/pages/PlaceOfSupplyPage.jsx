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

const STATES = [
  { code: "01", name: "Jammu & Kashmir" },
  { code: "02", name: "Himachal Pradesh" },
  { code: "03", name: "Punjab" },
  { code: "04", name: "Chandigarh" },
  { code: "05", name: "Uttarakhand" },
  { code: "06", name: "Haryana" },
  { code: "07", name: "Delhi" },
  { code: "08", name: "Rajasthan" },
  { code: "09", name: "Uttar Pradesh" },
  { code: "10", name: "Bihar" },
  { code: "11", name: "Sikkim" },
  { code: "12", name: "Arunachal Pradesh" },
  { code: "13", name: "Nagaland" },
  { code: "14", name: "Manipur" },
  { code: "15", name: "Mizoram" },
  { code: "16", name: "Tripura" },
  { code: "17", name: "Meghalaya" },
  { code: "18", name: "Assam" },
  { code: "19", name: "West Bengal" },
  { code: "20", name: "Jharkhand" },
  { code: "21", name: "Odisha" },
  { code: "22", name: "Chhattisgarh" },
  { code: "23", name: "Madhya Pradesh" },
  { code: "24", name: "Gujarat" },
  { code: "25", name: "Daman & Diu" },
  { code: "26", name: "Dadra & Nagar Haveli" },
  { code: "27", name: "Maharashtra" },
  { code: "29", name: "Karnataka" },
  { code: "30", name: "Goa" },
  { code: "32", name: "Kerala" },
  { code: "33", name: "Tamil Nadu" },
  { code: "34", name: "Puducherry" },
  { code: "35", name: "Andaman & Nicobar" },
  { code: "36", name: "Telangana" },
  { code: "37", name: "Andhra Pradesh" },
  { code: "38", name: "Ladakh" },
  { code: "97", name: "Other Territory" },
];

// 40 is GST 2.0's slab (from 22 September 2025); 12 and 28 stay for supplies before it.
const GST_RATES = [0, 5, 12, 18, 28, 40];

const SUPPLY_CATEGORIES = [
  { key: "goods", label: "Goods" },
  { key: "services", label: "Services" },
];

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST Place of Supply Determiner",
  url: "https://gst.doaide.com/place-of-supply",
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
      name: "What is Place of Supply under GST?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Place of Supply determines whether a transaction is inter-state (IGST) or intra-state (CGST+SGST). It is based on supplier location and where goods are delivered or services consumed.",
      },
    },
    {
      "@type": "Question",
      name: "Why is Place of Supply important?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "It decides which tax applies, which state gets the revenue, and whether multi-state registration is needed. A wrong determination means wrong tax on the invoice, risking ITC denial for the buyer.",
      },
    },
    {
      "@type": "Question",
      name: "How is Place of Supply determined for goods?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "For goods with movement, the place of supply is the delivery location. For installed or assembled goods, it is the installation site. For bill-to-ship-to deals, it is the third party's principal place of business.",
      },
    },
    {
      "@type": "Question",
      name: "How is Place of Supply determined for services?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "For services, the default place of supply is the recipient's location if registered, otherwise the supplier's location. Special rules apply for immovable property, events, and transport.",
      },
    },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "Place of Supply Determiner" },
];

export default function PlaceOfSupplyPage() {
  usePageTitle("GST Place of Supply Determiner — Free Tool");

  const [supplierState, setSupplierState] = useState("");
  const [recipientState, setRecipientState] = useState("");
  const [supplyCategory, setSupplyCategory] = useState("goods");
  const [amount, setAmount] = useState("");
  const [gstRate, setGstRate] = useState(18);

  const result = useMemo(() => {
    if (!supplierState || !recipientState) return null;
    const value = parseFloat(amount);
    if (!Number.isFinite(value) || value < 0) return null;

    const isInterstate = supplierState !== recipientState;
    const supplierName = STATES.find((s) => s.code === supplierState)?.name || "";
    const recipientName = STATES.find((s) => s.code === recipientState)?.name || "";

    const totalTax = Math.round(value * gstRate) / 100;

    if (isInterstate) {
      return {
        interstate: true,
        supplierState: supplierName,
        recipientState: recipientName,
        placeOfSupply: recipientName,
        taxType: "IGST",
        igst: totalTax,
        cgst: 0,
        sgst: 0,
        totalTax,
        taxableValue: value,
        totalAmount: Math.round((value + totalTax) * 100) / 100,
        explanation: `Supplier in ${supplierName} and recipient in ${recipientName} — this is an inter-state supply. IGST at ${gstRate}% is applicable.`,
      };
    }

    const half = Math.round((totalTax / 2) * 100) / 100;
    const otherHalf = Math.round((totalTax - half) * 100) / 100;

    return {
      interstate: false,
      supplierState: supplierName,
      recipientState: recipientName,
      placeOfSupply: recipientName,
      taxType: "CGST + SGST",
      igst: 0,
      cgst: half,
      sgst: otherHalf,
      totalTax: Math.round((half + otherHalf) * 100) / 100,
      taxableValue: value,
      totalAmount: Math.round((value + half + otherHalf) * 100) / 100,
      explanation: `Both supplier and recipient are in ${supplierName} — this is an intra-state supply. CGST + SGST at ${gstRate / 2}% each is applicable.`,
    };
  }, [supplierState, recipientState, supplyCategory, amount, gstRate]);

  return (
    <div className="tool-page">
      <SeoHead
        title="GST Place of Supply Determiner — Free Online Tool"
        description="Determine the Place of Supply under GST. Enter supplier and recipient locations to check if IGST or CGST+SGST applies, with full tax breakdown. Free, no login required."
        path="/place-of-supply"
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">Place of Supply Determiner</h1>
          <p className="tool-subtitle">
            Find out whether your transaction is inter-state or intra-state and which GST applies. No sign-up required.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Supplier&apos;s State
              <select
                className="calc-select"
                value={supplierState}
                onChange={(e) => setSupplierState(e.target.value)}
              >
                <option value="">— Select state —</option>
                {STATES.map((s) => (
                  <option key={s.code} value={s.code}>{s.code} — {s.name}</option>
                ))}
              </select>
            </label>

            <label className="calc-label">
              Recipient&apos;s State (Place of Supply)
              <select
                className="calc-select"
                value={recipientState}
                onChange={(e) => setRecipientState(e.target.value)}
              >
                <option value="">— Select state —</option>
                {STATES.map((s) => (
                  <option key={s.code} value={s.code}>{s.code} — {s.name}</option>
                ))}
              </select>
            </label>

            <label className="calc-label">
              Type of Supply
              <select
                className="calc-select"
                value={supplyCategory}
                onChange={(e) => setSupplyCategory(e.target.value)}
              >
                {SUPPLY_CATEGORIES.map((c) => (
                  <option key={c.key} value={c.key}>{c.label}</option>
                ))}
              </select>
            </label>

            <label className="calc-label">
              Taxable Value (₹)
              <input
                type="number"
                className="calc-input"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="Enter taxable value"
                min="0"
                step="1"
                inputMode="numeric"
              />
            </label>

            <label className="calc-label">
              GST Rate (%)
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
                <div className="calc-result-row calc-total" style={{ color: result.interstate ? "#f59e42" : "#34d399" }}>
                  <span>Supply Type</span>
                  <strong>{result.interstate ? "Inter-State" : "Intra-State"}</strong>
                </div>
                <p style={{ margin: "0.5rem 0", fontSize: "0.95rem", lineHeight: 1.5 }}>
                  {result.explanation}
                </p>
                <div className="calc-result-row">
                  <span>Place of Supply</span>
                  <strong>{result.placeOfSupply}</strong>
                </div>
                <div className="calc-result-row">
                  <span>Tax Type</span>
                  <strong>{result.taxType}</strong>
                </div>
                <div className="calc-result-row">
                  <span>Taxable Value</span>
                  <strong>{formatINR(result.taxableValue)}</strong>
                </div>
                {result.interstate ? (
                  <div className="calc-result-row">
                    <span>IGST ({gstRate}%)</span>
                    <strong>{formatINR(result.igst)}</strong>
                  </div>
                ) : (
                  <>
                    <div className="calc-result-row">
                      <span>CGST ({gstRate / 2}%)</span>
                      <strong>{formatINR(result.cgst)}</strong>
                    </div>
                    <div className="calc-result-row">
                      <span>SGST ({gstRate / 2}%)</span>
                      <strong>{formatINR(result.sgst)}</strong>
                    </div>
                  </>
                )}
                <div className="calc-result-row calc-total">
                  <span>Total Amount</span>
                  <strong>{formatINR(result.totalAmount)}</strong>
                </div>
                <div className="calc-result-actions">
                  <ShareButtons
                    path="/place-of-supply"
                    text={`${result.interstate ? "Inter-state" : "Intra-state"} supply: ${result.taxType} at ${gstRate}% — checked on DoAide GST`}
                    toolName="Place of Supply Tool"
                  />
                </div>
              </div>
            )}
          </div>

          {result && (
            <SaveResultsCTA resultSummary={`${result.interstate ? "Inter-state" : "Intra-state"}: ${result.taxType} at ${gstRate}% on ${formatINR(result.taxableValue)}`} />
          )}
          <EmailCapture
            source="place-of-supply"
            heading="Get GST compliance alerts"
            subtext="Stay updated on place of supply rule changes — free email alerts."
            buttonLabel="Notify Me"
            compact
          />

          <section className="tool-info">
            <h2>Place of Supply Under GST — Complete Guide</h2>
            <p>
              Place of Supply (POS) is one of the most critical concepts under GST. It determines
              whether a transaction is inter-state (attracting IGST) or intra-state (attracting
              CGST + SGST/UTGST). Getting the POS wrong means applying the wrong tax, which can
              lead to ITC denial for the buyer and penalty for the supplier.
            </p>
            <h3>Place of Supply for Goods (Sections 10 &amp; 11)</h3>
            <ul>
              <li><strong>With movement:</strong> Where goods are delivered to the recipient</li>
              <li><strong>Without movement:</strong> Location where goods are made available (e.g., installed on site)</li>
              <li><strong>Bill-to-ship-to:</strong> Principal place of business of the third party who receives goods</li>
              <li><strong>On board a conveyance:</strong> Location where goods are loaded</li>
            </ul>
            <h3>Place of Supply for Services (Sections 12 &amp; 13)</h3>
            <ul>
              <li><strong>Default rule:</strong> Location of the recipient (if registered); otherwise location of the supplier</li>
              <li><strong>Immovable property:</strong> Where the property is located</li>
              <li><strong>Restaurant/catering:</strong> Where the services are performed</li>
              <li><strong>Training/events:</strong> Where the event is held (for in-person); location of recipient (for online)</li>
              <li><strong>Transport of goods:</strong> Location of the person transporting</li>
              <li><strong>Telecom:</strong> Billing address of the recipient</li>
            </ul>
            <h3>Why POS Matters</h3>
            <ul>
              <li>Determines IGST vs CGST+SGST application</li>
              <li>Wrong POS means the destination state loses revenue — they can demand tax</li>
              <li>The buyer&apos;s ITC claim gets rejected if the wrong tax type was charged</li>
              <li>May require registration in another state (for inter-state supplies)</li>
            </ul>
          </section>

          <section className="tool-info">
            <h2>Frequently Asked Questions</h2>

            <h3>What is Place of Supply under GST?</h3>
            <p>
              Place of Supply determines whether a transaction is inter-state or intra-state.
              It decides whether IGST or CGST+SGST applies and which state receives the tax
              revenue. It is based on the location of the supplier and where goods/services
              are consumed.
            </p>

            <h3>Why is Place of Supply important?</h3>
            <p>
              Wrong POS means wrong tax type on the invoice. The buyer&apos;s ITC claim gets
              rejected, the wrong state receives revenue, and both parties face penalties.
              Always verify POS before issuing invoices.
            </p>

            <h3>How is Place of Supply determined for goods?</h3>
            <p>
              For goods with movement, POS is where goods are delivered. For goods without
              movement (like installed machinery), it is the installation location. For
              bill-to-ship-to, it is the third party&apos;s principal place of business.
            </p>

            <h3>How is Place of Supply determined for services?</h3>
            <p>
              Default: location of the recipient if registered, otherwise supplier&apos;s location.
              Special rules apply for immovable property (property location), events (event
              location), transport (person arranging transport), and telecom (billing address).
            </p>
          </section>

          <InlineCTA variant="save" />
          <RelatedTools current="/place-of-supply" />
          <CrossProductLinks page="place-of-supply" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
      <ExitIntentPopup />
    </div>
  );
}
