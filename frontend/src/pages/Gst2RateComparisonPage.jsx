import { useMemo, useState } from "react";
import Breadcrumb from "../components/Breadcrumb";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import FaqSection, { faqSchema } from "../components/FaqSection";
import EmailCapture from "../components/EmailCapture";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { allProducts } from "../lib/hsnData";

const RATE_MIGRATION = {
  12: [5, 18],
  28: [18, 40],
};

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST 2.0 Rate Comparison Tool",
  url: "https://gst.doaide.com/rate-comparison",
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "GST 2.0 Rate Comparison" },
];

const FAQS = [
  {
    q: "What changed in GST 2.0?",
    a: "From 22 September 2025, most goods moved to two main slabs — 5% and 18% — replacing the earlier 5%, 12%, 18% and 28% structure. A 40% rate applies to luxury and sin goods, and many essentials became nil-rated.",
  },
  {
    q: "Did items in the 12% slab go up or down?",
    a: "Most items that were at 12% moved down to 5%, including many processed foods and everyday goods. A smaller number moved to 18%. Check the specific product, since the move depends on its HSN code.",
  },
  {
    q: "What happened to the 28% slab?",
    a: "Most 28% items, such as cement, air conditioners, televisions and small cars, moved to 18%. Luxury and sin goods such as tobacco products, aerated sugary drinks and large cars moved to 40%.",
  },
  {
    q: "Is health and life insurance free of GST now?",
    a: "Yes. Individual life and health insurance policies became exempt from GST under GST 2.0, down from 18%.",
  },
];

export default function Gst2RateComparisonPage() {
  usePageTitle("GST 2.0 Rate Comparison — Old vs New GST Rates");
  const [query, setQuery] = useState("");

  const products = useMemo(() => allProducts(), []);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q.length < 2) return [];
    return products
      .filter((p) => p.product.toLowerCase().includes(q) || (p.hsn && p.hsn.includes(q)))
      .slice(0, 20);
  }, [query, products]);

  return (
    <div className="tool-page">
      <SeoHead
        title="GST 2.0 Rate Comparison — Old vs New GST Rates for Any Item"
        description="Compare old and new GST rates under GST 2.0 for any product or service. See how the abolished 12% and 28% slabs have been reorganized into the new 3-slab structure."
        path="/rate-comparison"
        jsonLd={[TOOL_SCHEMA, faqSchema(FAQS)]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">GST 2.0 Rate Comparison</h1>
          <p className="tool-subtitle">
            Compare old GST rates with new GST 2.0 rates for any product or service. See what changed.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Search product or HSN code
              <input
                type="text"
                className="calc-input"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="e.g. cement, insurance, tobacco, 8471"
                autoFocus
              />
            </label>

            {results.length > 0 && (
              <div style={{ overflowX: "auto", marginTop: "1rem" }}>
                <table className="comparison-table">
                  <thead>
                    <tr>
                      <th>Item</th>
                      <th>HSN/SAC</th>
                      <th>Old Rate</th>
                      <th>New Rate (GST 2.0)</th>
                      <th>Change</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.map((p, i) => {
                      const newRate = p.rate;
                      const oldRate = RATE_MIGRATION[12]?.includes(newRate) && newRate <= 5 ? 12
                        : RATE_MIGRATION[28]?.includes(newRate) && newRate >= 40 ? 28
                        : newRate === 0 && p.product.toLowerCase().includes("insurance") ? 18
                        : newRate;
                      const diff = newRate - oldRate;
                      const changeColor = diff < 0 ? "#34d399" : diff > 0 ? "#f87171" : "var(--ink-soft)";
                      const changeText = diff === 0 ? "No change" : diff < 0 ? `↓ ${Math.abs(diff)}% lower` : `↑ ${diff}% higher`;

                      return (
                        <tr key={i}>
                          <td>{p.product}</td>
                          <td><code>{p.hsn || "—"}</code></td>
                          <td>{oldRate}%</td>
                          <td><strong>{newRate}%</strong></td>
                          <td style={{ color: changeColor }}>{changeText}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {results.length > 0 && (
              <div className="calc-result-actions" style={{ marginTop: "1rem" }}>
                <ShareButtons
                  path="/rate-comparison"
                  text={`Compare old vs new GST 2.0 rates for "${query}" — free tool on DoAide GST`}
                  toolName="GST 2.0 Rate Comparison"
                />
              </div>
            )}

            {query.length >= 2 && results.length === 0 && (
              <p style={{ padding: "1rem", color: "var(--ink-soft)", textAlign: "center" }}>
                No matching products found. Try a different search term.
              </p>
            )}
          </div>

          <section className="tool-info">
            <h2>Key GST 2.0 Rate Changes</h2>
            <div style={{ overflowX: "auto" }}>
              <table className="comparison-table">
                <thead>
                  <tr><th>Category</th><th>Old Rate</th><th>New Rate</th></tr>
                </thead>
                <tbody>
                  <tr><td>Health &amp; life insurance</td><td>18%</td><td><strong style={{ color: "#34d399" }}>0%</strong></td></tr>
                  <tr><td>Cancer drugs</td><td>12%</td><td><strong style={{ color: "#34d399" }}>5%</strong></td></tr>
                  <tr><td>33 life-saving medicines</td><td>5–12%</td><td><strong style={{ color: "#34d399" }}>0%</strong></td></tr>
                  <tr><td>Cement</td><td>28%</td><td><strong style={{ color: "#34d399" }}>18%</strong></td></tr>
                  <tr><td>Processed food</td><td>12%</td><td>5% or 18%</td></tr>
                  <tr><td>Smartphones</td><td>12%</td><td>18%</td></tr>
                  <tr><td>Tobacco products</td><td>28% + cess</td><td><strong style={{ color: "#f87171" }}>40%</strong></td></tr>
                  <tr><td>Aerated drinks</td><td>28% + 12% cess</td><td><strong style={{ color: "#f87171" }}>40%</strong></td></tr>
                  <tr><td>Vehicles above ₹20L</td><td>28% + cess</td><td><strong style={{ color: "#f87171" }}>40%</strong></td></tr>
                  <tr><td>Bikes above 350cc</td><td>28% + cess</td><td><strong style={{ color: "#f87171" }}>40%</strong></td></tr>
                </tbody>
              </table>
            </div>
          </section>

          <EmailCapture
            source="rate-comparison"
            heading="Get notified about GST rate changes"
            subtext="Free email alerts when GST rates change."
            buttonLabel="Notify Me"
            compact
          />

          <FaqSection faqs={FAQS} />

          <RelatedTools current="/rate-comparison" />
          <CrossProductLinks page="rate-comparison" />
        </div>
      </main>
      <DoAideFooter />
    </div>
  );
}
