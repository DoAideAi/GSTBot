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
import { formatINR, GST_SLABS, reverseCalculate } from "../lib/gstCalc";

const COMMON_RATES = [5, 18, 40];

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "Reverse GST Calculator",
  url: "https://gst.doaide.com/reverse-gst-calculator",
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const FAQ_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    { "@type": "Question", name: "How do I remove GST from a total amount?", acceptedAnswer: { "@type": "Answer", text: "Divide the GST-inclusive amount by (1 + GST rate/100). For ₹1,180 at 18% GST: 1180 / 1.18 = ₹1,000 base price and ₹180 GST." } },
    { "@type": "Question", name: "What is the reverse GST formula?", acceptedAnswer: { "@type": "Answer", text: "Base amount = Total / (1 + rate/100). GST amount = Total − Base amount. For 18% GST the divisor is 1.18, for 5% it is 1.05, and for 40% it is 1.40." } },
    { "@type": "Question", name: "Why do I need a reverse GST calculation?", acceptedAnswer: { "@type": "Answer", text: "When a price is quoted inclusive of GST — like an MRP or a customer quote — you must back-calculate the taxable value to raise a correct invoice, record it in books, and report it in GSTR-1 and GSTR-3B." } },
    { "@type": "Question", name: "Is the reverse GST calculation different for IGST?", acceptedAnswer: { "@type": "Answer", text: "No. The base amount is the same. For interstate supply the entire tax shows as IGST; for intrastate it splits equally into CGST and SGST." } },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "Reverse GST Calculator" },
];

export default function ReverseGstCalculatorPage() {
  usePageTitle("Reverse GST Calculator — Remove GST from Any Amount");

  const [amount, setAmount] = useState("");
  const [rate, setRate] = useState(18);
  const [interstate, setInterstate] = useState(false);

  const result = useMemo(() => {
    const total = parseFloat(amount);
    if (!Number.isFinite(total) || total <= 0) return null;
    return reverseCalculate(total, rate, { interstate });
  }, [amount, rate, interstate]);

  const comparison = useMemo(() => {
    const total = parseFloat(amount);
    if (!Number.isFinite(total) || total <= 0) return null;
    return COMMON_RATES.map((r) => ({ rate: r, calc: reverseCalculate(total, r) }));
  }, [amount]);

  return (
    <div className="tool-page">
      <SeoHead
        title="Reverse GST Calculator — Remove GST from Any Amount"
        description="Remove GST from a GST-inclusive price instantly. Enter the total, get the base amount and GST split (CGST/SGST or IGST) for 5%, 18%, 40% and all slabs. Free, no login."
        path="/reverse-gst-calculator"
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb items={[{ label: "Home", to: "/" }, { label: "Reverse GST Calculator" }]} />
          <h1 className="tool-title">Reverse GST Calculator</h1>
          <p className="tool-subtitle">
            Remove GST from a price that already includes it. Enter the total, get the taxable
            value and tax breakup. No sign-up required.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Total amount (including GST)
              <input
                type="number"
                className="calc-input"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="e.g. 1180"
                min="0"
                step="0.01"
                inputMode="decimal"
                autoFocus
              />
            </label>

            <label className="calc-label">
              GST Rate (%)
              <select
                className="calc-select"
                value={rate}
                onChange={(e) => setRate(Number(e.target.value))}
              >
                {GST_SLABS.map((r) => (
                  <option key={r} value={r}>
                    {r}%
                  </option>
                ))}
              </select>
            </label>

            <label className="calc-checkbox-label">
              <input
                type="checkbox"
                checked={interstate}
                onChange={(e) => setInterstate(e.target.checked)}
              />
              Interstate supply (IGST instead of CGST + SGST)
            </label>

            {result && (
              <div className="calc-result" aria-live="polite">
                <div className="calc-result-row">
                  <span>Base Amount (excl. GST)</span>
                  <strong>{formatINR(result.taxable)}</strong>
                </div>
                {result.interstate ? (
                  <div className="calc-result-row">
                    <span>IGST ({rate}%)</span>
                    <strong>{formatINR(result.igst)}</strong>
                  </div>
                ) : (
                  <>
                    <div className="calc-result-row">
                      <span>CGST ({rate / 2}%)</span>
                      <strong>{formatINR(result.cgst)}</strong>
                    </div>
                    <div className="calc-result-row">
                      <span>SGST ({rate / 2}%)</span>
                      <strong>{formatINR(result.sgst)}</strong>
                    </div>
                  </>
                )}
                <div className="calc-result-row">
                  <span>GST Removed</span>
                  <strong>{formatINR(result.total - result.taxable)}</strong>
                </div>
                <div className="calc-result-row calc-total">
                  <span>Total (incl. GST)</span>
                  <strong>{formatINR(result.total)}</strong>
                </div>

                <div className="calc-result-actions">
                  <ShareButtons
                    path="/reverse-gst-calculator"
                    text={`✅ Removed ${rate}% GST from ${formatINR(result.total)}: base ${formatINR(result.taxable)}, GST ${formatINR(result.total - result.taxable)} — calculated free on DoAide GST`}
                  />
                  <PrintButton label="Print Result" />
                </div>
              </div>
            )}
          </div>

          {comparison && (
            <section className="tool-info">
              <h2>Same Amount at Other GST Rates</h2>
              <table className="calendar-table">
                <thead>
                  <tr>
                    <th>GST Rate</th>
                    <th>Base Amount</th>
                    <th>GST Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {comparison.map(({ rate: r, calc }) => (
                    <tr key={r}>
                      <td>{r}%</td>
                      <td>{formatINR(calc.taxable)}</td>
                      <td>{formatINR(calc.total - calc.taxable)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          <EmailCapture
            source="reverse-gst-calculator"
            heading="Never miss a GST deadline"
            subtext="Get free email reminders before every GST filing deadline."
            buttonLabel="Remind Me"
            compact
          />

          <section className="tool-info">
            <h2>How Reverse GST Calculation Works</h2>
            <p>
              A reverse GST calculation (also called GST-inclusive or back-calculation) extracts
              the tax from a price that already includes GST. This is what you need when a
              customer quote, MRP, or receipt shows only the final amount.
            </p>
            <h3>The Formula</h3>
            <ul>
              <li><strong>Base amount</strong> = Total ÷ (1 + GST rate ÷ 100)</li>
              <li><strong>GST amount</strong> = Total − Base amount</li>
            </ul>
            <p>
              Example: a ₹1,180 bill at 18% GST → base = 1180 ÷ 1.18 = ₹1,000, GST = ₹180.
              For intrastate supply that splits into ₹90 CGST + ₹90 SGST; for interstate it is
              ₹180 IGST.
            </p>
            <h3>When You Need It</h3>
            <ul>
              <li>Raising a tax invoice from a GST-inclusive quote or MRP</li>
              <li>Recording GST-inclusive expenses correctly in your books</li>
              <li>Reporting taxable value (not the gross amount) in GSTR-1 and GSTR-3B</li>
              <li>Checking a vendor&apos;s invoice where the tax split looks wrong</li>
            </ul>
            <p>
              Need to add GST on top of a base price instead? Use the{" "}
              <Link to="/calculator">GST calculator</Link>. Not sure which rate applies?{" "}
              Try the <Link to="/hsn">HSN code finder</Link>.
            </p>
          </section>

          <InlineCTA variant="save" />
          <RelatedTools current="/reverse-gst-calculator" />
          <CrossProductLinks page="reverse-gst-calculator" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}
