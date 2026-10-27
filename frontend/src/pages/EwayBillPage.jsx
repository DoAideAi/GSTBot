import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
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
import { ewayBillRequired, validityDays } from "../lib/ewayBill";

const SUPPLY_TYPES = [
  { key: "goods", label: "Goods (consignment value > ₹50,000)" },
  { key: "handicraft", label: "Handicraft goods (interstate, any value)" },
  { key: "job_work", label: "Job work (principal to job worker)" },
];

const VEHICLE_TYPES = [
  { key: "regular", label: "Regular vehicle" },
  { key: "over_dim", label: "Over-dimensional cargo" },
];

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "E-Way Bill Requirement Checker",
  url: "https://gst.doaide.com/eway-bill",
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
      name: "What is the threshold for e-way bill under GST?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Required when consignment value exceeds ₹50,000 (including GST). Some states have lower intrastate thresholds. Handicraft and job work may need it regardless of value.",
      },
    },
    {
      "@type": "Question",
      name: "How long is an e-way bill valid?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Regular vehicles: 1 day per 200 km. Over-dimensional cargo: 1 day per 20 km. Validity starts from the date and time of generation on the e-way bill portal.",
      },
    },
    {
      "@type": "Question",
      name: "What is the penalty for not generating an e-way bill?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Goods moved without a valid e-way bill can be detained or seized under Section 129. The penalty is ₹10,000 or the tax amount, whichever is higher. Release requires payment of tax and penalty.",
      },
    },
    {
      "@type": "Question",
      name: "Can an e-way bill be cancelled?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes, within 24 hours of generation if goods are not transported or information is incorrect. Cannot be cancelled if already verified by an officer during transit.",
      },
    },
    {
      "@type": "Question",
      name: "Who should generate the e-way bill?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Consignor generates it for outward movement, consignee for inward movement. The transporter can also generate it if neither party does.",
      },
    },
  ],
};

const HOWTO_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "HowTo",
  name: "How to check if an e-way bill is needed",
  description: "Decide from consignment value, supply type and distance whether an e-way bill is required and how long it stays valid.",
  step: [
    { "@type": "HowToStep", name: "Enter the consignment value", text: "The invoice value including GST — the ₹50,000 threshold is checked against it." },
    { "@type": "HowToStep", name: "Pick the supply type", text: "Ordinary goods, handicraft, or job work — the latter two can need a bill regardless of value." },
    { "@type": "HowToStep", name: "Enter the distance", text: "Kilometres to the destination; validity runs 1 day per 200 km (20 km for over-dimensional cargo)." },
    { "@type": "HowToStep", name: "Read the verdict", text: "Whether a bill is required and, if so, how many days it stays valid from generation." },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "E-Way Bill Checker" },
];

export default function EwayBillPage() {
  usePageTitle("E-Way Bill Requirement Checker — Check if E-Way Bill is Needed");

  const [supplyType, setSupplyType] = useState("goods");
  const [consignmentValue, setConsignmentValue] = useState("");
  const [distance, setDistance] = useState("");
  const [vehicleType, setVehicleType] = useState("regular");
  const [interstate, setInterstate] = useState(false);

  const result = useMemo(() => {
    const value = parseFloat(consignmentValue);
    const dist = parseFloat(distance);
    if (!Number.isFinite(value) || value < 0) return null;

    const isHandicraft = supplyType === "handicraft";
    const isJobWork = supplyType === "job_work";

    let required = false;
    let reason = "";

    if (isHandicraft && interstate) {
      required = true;
      reason = "E-way bill is mandatory for interstate movement of handicraft goods regardless of value.";
    } else if (isJobWork) {
      required = true;
      reason = "E-way bill is required for movement of goods to a job worker, regardless of the consignment value.";
    } else if (ewayBillRequired(value)) {
      required = true;
      reason = `Consignment value (${formatINR(value)}) exceeds the ₹50,000 threshold. E-way bill is mandatory.`;
    } else {
      required = false;
      reason = `Consignment value (${formatINR(value)}) does not exceed ₹50,000. E-way bill is generally not required for intrastate movement.`;
      if (interstate && value > 0) {
        reason += " However, some states have lower thresholds for intrastate movement. Check your state's rules.";
      }
    }

    let validity = null;
    if (required && Number.isFinite(dist) && dist > 0) {
      validity = validityDays(dist, vehicleType === "over_dim");
    }

    return { required, reason, validity, distance: dist };
  }, [supplyType, consignmentValue, distance, vehicleType, interstate]);

  return (
    <div className="tool-page">
      <SeoHead
        title="E-Way Bill Requirement Checker — Check if E-Way Bill is Needed"
        description="Check if your shipment needs an e-way bill under GST. Enter consignment value and distance to get instant results. Free tool, no login required."
        path="/eway-bill"
        jsonLd={[TOOL_SCHEMA, HOWTO_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">E-Way Bill Checker</h1>
          <p className="tool-subtitle">
            Check if your shipment requires an e-way bill under GST. No sign-up required.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Type of Supply
              <select
                className="calc-select"
                value={supplyType}
                onChange={(e) => setSupplyType(e.target.value)}
              >
                {SUPPLY_TYPES.map((s) => (
                  <option key={s.key} value={s.key}>{s.label}</option>
                ))}
              </select>
            </label>

            <label className="calc-label">
              Consignment Value (₹)
              <input
                type="number"
                className="calc-input"
                value={consignmentValue}
                onChange={(e) => setConsignmentValue(e.target.value)}
                placeholder="Enter total consignment value"
                min="0"
                step="0.01"
                inputMode="decimal"
                autoFocus
              />
            </label>

            <label className="calc-checkbox-label">
              <input
                type="checkbox"
                checked={interstate}
                onChange={(e) => setInterstate(e.target.checked)}
              />
              Interstate movement
            </label>

            <label className="calc-label">
              Approximate Distance (km) — for validity calculation
              <input
                type="number"
                className="calc-input"
                value={distance}
                onChange={(e) => setDistance(e.target.value)}
                placeholder="Enter distance in km"
                min="0"
                inputMode="numeric"
              />
            </label>

            <label className="calc-label">
              Vehicle Type
              <select
                className="calc-select"
                value={vehicleType}
                onChange={(e) => setVehicleType(e.target.value)}
              >
                {VEHICLE_TYPES.map((v) => (
                  <option key={v.key} value={v.key}>{v.label}</option>
                ))}
              </select>
            </label>

            {result && (
              <div className="calc-result" aria-live="polite">
                <div className="calc-result-row calc-total" style={{ color: result.required ? "#f59e42" : "#34d399" }}>
                  <span>E-Way Bill</span>
                  <strong>{result.required ? "Required" : "Not Required"}</strong>
                </div>
                <p style={{ margin: "0.5rem 0", fontSize: "0.95rem", lineHeight: 1.5 }}>
                  {result.reason}
                </p>
                {result.validity && (
                  <div className="calc-result-row">
                    <span>Validity ({result.distance} km)</span>
                    <strong>{result.validity} day{result.validity > 1 ? "s" : ""}</strong>
                  </div>
                )}
                <div className="calc-result-actions">
                  <ShareButtons
                    path="/eway-bill"
                    text={`E-way bill ${result.required ? "required" : "not required"} — checked free on DoAide GST`}
                  />
                  <PrintButton label="Print Result" />
                </div>
              </div>
            )}
          </div>

          <EmailCapture
            source="eway-bill"
            heading="Get E-Way Bill updates"
            subtext="Stay updated on e-way bill rule changes — free email alerts."
            buttonLabel="Notify Me"
            compact
          />

          <section className="tool-info">
            <h2>E-Way Bill Rules Under GST</h2>
            <p>
              An E-Way Bill (Electronic Way Bill) is a document required for the movement of
              goods worth more than ₹50,000 under GST. It is generated on the e-way bill portal
              and must be carried by the transporter.
            </p>
            <h3>When is an E-Way Bill Required?</h3>
            <ul>
              <li>Movement of goods valued above ₹50,000 (including GST)</li>
              <li>Interstate movement of handicraft goods by exempted dealers — any value</li>
              <li>Movement of goods for job work — regardless of value</li>
              <li>Interstate movement by principal to job worker — regardless of value</li>
            </ul>
            <h3>E-Way Bill Validity</h3>
            <ul>
              <li><strong>Regular vehicles:</strong> 1 day for every 200 km or part thereof</li>
              <li><strong>Over-dimensional cargo:</strong> 1 day for every 20 km or part thereof</li>
              <li>Validity starts from the date and time of generation</li>
            </ul>
            <h3>Exemptions from E-Way Bill</h3>
            <ul>
              <li>Goods transported by non-motorized conveyance</li>
              <li>Goods transported from port, airport, or land customs station to an ICD or CFS</li>
              <li>Transit cargo from or to Nepal or Bhutan</li>
              <li>Goods specified in Annexure to Rule 138(14) — e.g., LPG for household use, kerosene, postal baggage</li>
            </ul>
          </section>

          <section className="tool-info">
            <h2>Frequently Asked Questions</h2>

            <h3>What is the threshold for e-way bill under GST?</h3>
            <p>
              An e-way bill is required for consignment values exceeding ₹50,000 (including
              GST). Some states have lower thresholds for intrastate movement. Handicraft goods
              and job work may require e-way bills regardless of value.
            </p>

            <h3>How long is an e-way bill valid?</h3>
            <p>
              For regular vehicles: 1 day per 200 km. For over-dimensional cargo: 1 day per
              20 km. Validity starts from the date and time of generation on the portal.
            </p>

            <h3>What is the penalty for not generating an e-way bill?</h3>
            <p>
              Goods moved without a valid e-way bill can be detained under Section 129. The
              penalty is ₹10,000 or the tax amount, whichever is higher. Goods and vehicle
              are released on payment.
            </p>

            <h3>Can an e-way bill be cancelled?</h3>
            <p>
              Yes, within 24 hours of generation if goods are not transported or information
              is incorrect. It cannot be cancelled if verified by an officer during transit.
            </p>

            <h3>Who should generate the e-way bill?</h3>
            <p>
              The consignor (supplier) for outward movement, or the consignee (recipient) for
              inward movement. The transporter can generate it if neither party does.
            </p>
          </section>

          <p>
            Need the bill itself? The{" "}
            <Link to="/eway-bill-generator">e-way bill generator</Link> prepares Part A and Part B
            from your invoice and vehicle details.
          </p>

          <InlineCTA variant="save" />
          <RelatedTools current="/eway-bill" />
          <CrossProductLinks page="eway-bill" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}
