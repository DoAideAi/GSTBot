import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import DoAideFooter from "../components/DoAideFooter";
import FaqSection, { faqSchema } from "../components/FaqSection";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { GST_TCS_RATE, TDS_194O_RATE, computeEcommerceTcs } from "../lib/ecommerceTcs";
import { formatINR } from "../lib/gstCalc";

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "E-commerce TCS Calculator — GST Section 52",
  url: "https://gst.doaide.com/ecommerce-tcs-calculator",
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "E-commerce TCS Calculator" },
];

const FAQS = [
  {
    q: "What is the TCS rate under GST for e-commerce sellers?",
    a: "Operators such as Amazon, Flipkart and Meesho collect 0.5% of net taxable sales: 0.25% CGST + 0.25% SGST within a state, or 0.5% IGST across states. The rate was cut from 1% on 10 July 2024.",
  },
  {
    q: "On what value is GST TCS calculated?",
    a: "On net taxable sales: the month's sales through the operator less that month's returns, excluding GST. Supplies where the operator pays the tax itself under Section 9(5) are left out.",
  },
  {
    q: "What is Section 194-O TDS, and how is it different from GST TCS?",
    a: "194-O is income-tax TDS of 0.1% of gross sales (from 1 October 2024), claimed in your income-tax return. GST TCS is a separate 0.5% credited to your GST cash ledger. Both come off the same payout.",
  },
  {
    q: "How do I claim the TCS collected by the e-commerce operator?",
    a: "The operator reports it in GSTR-8 by the 10th of the next month. Accept it on the GST portal under TCS and TDS credit received, and it moves to your electronic cash ledger to pay GST.",
  },
  {
    q: "Does a small online seller need GST registration?",
    a: "Not always. Since 1 October 2023, sellers of goods making only intra-state sales through an operator can stay unregistered below the threshold. Service sellers below the threshold have long been exempt.",
  },
];

export default function EcommerceTcsCalculatorPage() {
  usePageTitle("E-commerce TCS Calculator — GST Section 52 & 194-O");
  const [grossSales, setGrossSales] = useState("");
  const [returns, setReturns] = useState("");
  const [interstatePct, setInterstatePct] = useState("0");

  const result = useMemo(
    () => (grossSales === "" ? null : computeEcommerceTcs({ grossSales, returns, interstatePct })),
    [grossSales, returns, interstatePct],
  );
  const invalid = grossSales !== "" && result === null;

  return (
    <div className="tool-page">
      <SeoHead
        title="E-commerce TCS Calculator — GST TCS 0.5% & 194-O TDS for Sellers"
        description="Calculate GST TCS (0.5%, Section 52) and income-tax TDS (0.1%, Section 194-O) deducted by Amazon, Flipkart and Meesho from your payout. Free, no login."
        path="/ecommerce-tcs-calculator"
        jsonLd={[TOOL_SCHEMA, faqSchema(FAQS)]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">E-commerce TCS Calculator</h1>
          <p className="tool-subtitle">
            Work out the GST TCS and 194-O TDS your marketplace deducts in a month, and check it
            against your payout statement. No sign-up required.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Sales through the marketplace this month, excluding GST (₹)
              <input
                type="number"
                className="calc-input"
                value={grossSales}
                onChange={(e) => setGrossSales(e.target.value)}
                placeholder="e.g. 500000"
                min="0"
                inputMode="decimal"
              />
            </label>

            <label className="calc-label">
              Customer returns this month, excluding GST (₹)
              <input
                type="number"
                className="calc-input"
                value={returns}
                onChange={(e) => setReturns(e.target.value)}
                placeholder="0"
                min="0"
                inputMode="decimal"
              />
            </label>

            <label className="calc-label">
              Share of sales to buyers in other states (%)
              <input
                type="number"
                className="calc-input"
                value={interstatePct}
                onChange={(e) => setInterstatePct(e.target.value)}
                min="0"
                max="100"
                inputMode="numeric"
              />
            </label>

            {invalid && (
              <p className="calc-error" role="alert">
                Enter amounts of zero or more.
              </p>
            )}

            {result && (
              <div className="calc-result" aria-live="polite">
                <div className="calc-result-row">
                  <span>Net taxable sales</span>
                  <strong>{formatINR(Math.max(result.net, 0))}</strong>
                </div>
                {result.excessReturns > 0 && (
                  <p>
                    Returns exceed sales by {formatINR(result.excessReturns)}, so no GST TCS is
                    collected this month.
                  </p>
                )}
                <div className="calc-result-row">
                  <span>CGST TCS ({GST_TCS_RATE / 2}%)</span>
                  <strong>{formatINR(result.cgst)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>SGST TCS ({GST_TCS_RATE / 2}%)</span>
                  <strong>{formatINR(result.sgst)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>IGST TCS ({GST_TCS_RATE}%)</span>
                  <strong>{formatINR(result.igst)}</strong>
                </div>
                <div className="calc-result-row calc-total">
                  <span>GST TCS (Section 52)</span>
                  <strong>{formatINR(result.tcs)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>Income-tax TDS (194-O, {TDS_194O_RATE}% of gross)</span>
                  <strong>{formatINR(result.tds194O)}</strong>
                </div>
                <div className="calc-result-row calc-total">
                  <span>Total withheld from payout</span>
                  <strong>{formatINR(result.totalWithheld)}</strong>
                </div>
                <p>
                  The GST TCS is claimed back through your cash ledger, and the 194-O TDS in your
                  income-tax return. Neither is a cost if you claim it.
                </p>
                <div className="calc-result-actions">
                  <ShareButtons
                    path="/ecommerce-tcs-calculator"
                    text={`My marketplace withholds ${formatINR(result.totalWithheld)} as GST TCS + 194-O TDS — checked free on DoAide GST`}
                    toolName="E-commerce TCS Calculator"
                  />
                </div>
              </div>
            )}
          </div>

          <section className="tool-info">
            <h2>Reconciling TCS with your payout</h2>
            <ol>
              <li>Download the marketplace&apos;s monthly TCS report and match its net taxable value to your own sales register.</li>
              <li>After the 10th of the next month, check the TCS shown on the GST portal against the figure above.</li>
              <li>Accept the TCS credit on the portal, then use it from your cash ledger when you pay GST through <Link to="/payment-challan">PMT-06</Link>.</li>
              <li>Declare the same sales in <Link to="/guides/how-to-file-gstr-1">GSTR-1</Link>, so the operator&apos;s figures and yours agree.</li>
            </ol>
          </section>

          <FaqSection faqs={FAQS} />

          <RelatedTools current="/ecommerce-tcs-calculator" />
        </div>
      </main>
      <DoAideFooter />
    </div>
  );
}

export { FAQS };
