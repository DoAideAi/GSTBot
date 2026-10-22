import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import PrintButton from "../components/PrintButton";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { formatINR } from "../lib/gstCalc";

// 3% on the metal (HSN 7108/7113), 5% on making charges as job work — the two
// legs are taxed separately on a jeweller's invoice, which is why a plain
// single-rate calculator gets gold wrong.
const GOLD_RATE = 3;
const MAKING_RATE = 5;

const round2 = (n) => Math.round(n * 100) / 100;

export function calculateGoldGst(goldValue, makingCharges, makingMode) {
  if (!Number.isFinite(goldValue) || goldValue <= 0) return null;
  const making = Number.isFinite(makingCharges) && makingCharges > 0 ? makingCharges : 0;
  const makingAmount = round2(makingMode === "percent" ? (goldValue * making) / 100 : making);
  const goldGst = round2((goldValue * GOLD_RATE) / 100);
  const makingGst = round2((makingAmount * MAKING_RATE) / 100);
  return {
    goldValue: round2(goldValue),
    makingAmount,
    goldGst,
    makingGst,
    totalGst: round2(goldGst + makingGst),
    total: round2(goldValue + makingAmount + goldGst + makingGst),
  };
}

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST on Gold Calculator",
  url: "https://gst.doaide.com/gst-on-gold",
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const FAQ_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    { "@type": "Question", name: "What is the GST rate on gold in India?", acceptedAnswer: { "@type": "Answer", text: "Gold and gold jewellery attract 3% GST on the value of the metal (HSN 7108 for gold, 7113 for jewellery). Making charges are taxed separately at 5% as a job-work service." } },
    { "@type": "Question", name: "How is GST on gold jewellery calculated?", acceptedAnswer: { "@type": "Answer", text: "Total price = gold value + making charges + 3% GST on the gold value + 5% GST on the making charges. For ₹1,00,000 of gold with 10% making charges: ₹1,00,000 + ₹10,000 + ₹3,000 + ₹500 = ₹1,13,500." } },
    { "@type": "Question", name: "Is there GST when I sell my old gold jewellery?", acceptedAnswer: { "@type": "Answer", text: "No. An individual selling personal jewellery to a jeweller is not making a taxable supply, so no GST applies on the sale. When you exchange old gold for new, GST is still charged on the full value of the new jewellery." } },
    { "@type": "Question", name: "Does digital gold attract GST?", acceptedAnswer: { "@type": "Answer", text: "Yes. Buying digital gold attracts the same 3% GST as physical gold, charged on the purchase value at the time of buying. No further GST applies when you sell it back on the platform." } },
    { "@type": "Question", name: "Is GST on gold the same for coins and bars?", acceptedAnswer: { "@type": "Answer", text: "Gold coins and bars attract 3% GST on value. Since there are little or no making charges, the 5% making-charge GST is usually nil or very small compared to jewellery." } },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "GST on Gold Calculator" },
];

export default function GstOnGoldPage() {
  usePageTitle("GST on Gold Calculator — 3% Gold + 5% Making Charges");

  const [goldValue, setGoldValue] = useState("");
  const [makingCharges, setMakingCharges] = useState("10");
  const [makingMode, setMakingMode] = useState("percent");

  const result = useMemo(
    () => calculateGoldGst(parseFloat(goldValue), parseFloat(makingCharges), makingMode),
    [goldValue, makingCharges, makingMode],
  );

  return (
    <div className="tool-page">
      <SeoHead
        title="GST on Gold Calculator — 3% Gold + 5% Making Charges"
        description="Calculate GST on gold jewellery, coins and digital gold: 3% on gold value plus 5% on making charges. Enter the gold price and making charges to get the final bill. Free, no login."
        path="/gst-on-gold"
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb items={[{ label: "Home", to: "/" }, { label: "GST on Gold Calculator" }]} />
          <h1 className="tool-title">GST on Gold Calculator</h1>
          <p className="tool-subtitle">
            Gold is taxed twice on one invoice — 3% on the metal and 5% on making charges.
            Enter both and get the exact final bill. No sign-up required.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Gold value (₹)
              <input
                type="number"
                className="calc-input"
                value={goldValue}
                onChange={(e) => setGoldValue(e.target.value)}
                placeholder="e.g. 100000"
                min="0"
                step="0.01"
                inputMode="decimal"
                autoFocus
              />
            </label>

            <label className="calc-label">
              Making charges
              <input
                type="number"
                className="calc-input"
                value={makingCharges}
                onChange={(e) => setMakingCharges(e.target.value)}
                placeholder={makingMode === "percent" ? "e.g. 10" : "e.g. 8000"}
                min="0"
                step="0.01"
                inputMode="decimal"
              />
            </label>

            <label className="calc-label">
              Making charges as
              <select
                className="calc-select"
                value={makingMode}
                onChange={(e) => setMakingMode(e.target.value)}
              >
                <option value="percent">% of gold value</option>
                <option value="rupees">₹ amount</option>
              </select>
            </label>

            {result && (
              <div className="calc-result" aria-live="polite">
                <div className="calc-result-row">
                  <span>Gold value</span>
                  <strong>{formatINR(result.goldValue)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>Making charges</span>
                  <strong>{formatINR(result.makingAmount)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>GST on gold ({GOLD_RATE}%)</span>
                  <strong>{formatINR(result.goldGst)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>GST on making charges ({MAKING_RATE}%)</span>
                  <strong>{formatINR(result.makingGst)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>Total GST</span>
                  <strong>{formatINR(result.totalGst)}</strong>
                </div>
                <div className="calc-result-row calc-total">
                  <span>Final price</span>
                  <strong>{formatINR(result.total)}</strong>
                </div>

                <div className="calc-result-actions">
                  <ShareButtons
                    path="/gst-on-gold"
                    text={`✅ GST on ${formatINR(result.goldValue)} of gold: ${formatINR(result.totalGst)} tax, final price ${formatINR(result.total)} — calculated free on DoAide GST`}
                  />
                  <PrintButton label="Print Result" />
                </div>
              </div>
            )}
          </div>

          <EmailCapture
            source="gst-on-gold"
            heading="Never miss a GST deadline"
            subtext="Get free email reminders before every GST filing deadline."
            buttonLabel="Remind Me"
            compact
          />

          <section className="tool-info">
            <h2>How GST on Gold Works</h2>
            <p>
              A jeweller&apos;s invoice has two taxable parts. The gold itself — whether
              jewellery, coins, bars, or digital gold — attracts <strong>3% GST</strong> on
              its value. The making charges are a job-work service and attract{" "}
              <strong>5% GST</strong> separately. Billing a single blended rate on the whole
              amount is wrong either way: 3% on everything under-taxes the making charges,
              5% on everything over-taxes the metal.
            </p>
            <h3>The Formula</h3>
            <ul>
              <li><strong>GST on gold</strong> = Gold value × 3%</li>
              <li><strong>GST on making</strong> = Making charges × 5%</li>
              <li><strong>Final price</strong> = Gold value + Making charges + both GST amounts</li>
            </ul>
            <p>
              Example: ₹1,00,000 of gold with 10% making charges → ₹3,000 GST on gold +
              ₹500 GST on making = ₹3,500 total tax, final bill ₹1,13,500.
            </p>
            <h3>What Buyers Should Check on the Bill</h3>
            <ul>
              <li>Gold value and making charges shown as separate line items</li>
              <li>3% charged only on the gold value, 5% only on the making charges</li>
              <li>HSN 7113 for jewellery on a tax invoice from a registered jeweller</li>
              <li>No GST charged on the value of old gold you traded in</li>
            </ul>
            <p>
              Calculating GST on something other than gold? Use the{" "}
              <Link to="/calculator">GST calculator</Link> for standard slabs, or look up
              the right rate with the <Link to="/hsn">HSN code finder</Link>.
            </p>
          </section>

          <InlineCTA variant="save" />
          <RelatedTools current="/gst-on-gold" />
          <CrossProductLinks page="gst-on-gold" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}
