import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import DoAideFooter from "../components/DoAideFooter";
import FaqSection, { faqSchema } from "../components/FaqSection";
import RelatedTools from "../components/RelatedTools";
import SeoHead, { BASE_URL } from "../components/SeoHead";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { allProducts, productSlug } from "../lib/hsnData";

// The hub for every /gst-rate/:product page. Without it those pages are only
// reachable through the sitemap and each other, so this list is as much for
// crawlers as for people scanning for a product.

const SLAB_NOTES = {
  0: "Nil-rated and exempt essentials",
  0.25: "Rough precious and semi-precious stones",
  3: "Gold, silver and jewellery",
  5: "Merit rate — daily-use goods and basic services",
  18: "Standard rate — most goods and services",
  40: "Demerit rate — luxury and sin goods",
};

const FAQS = [
  {
    q: "What are the GST rate slabs in India in 2026?",
    a: "Since GST 2.0 (22 September 2025): 0% for essentials, 5% merit rate, 18% standard rate and 40% for luxury and sin goods, plus 3% for gold and 0.25% for rough diamonds. The 12% and 28% slabs are gone.",
  },
  {
    q: "How is GST split into CGST, SGST and IGST?",
    a: "For a sale within a state, the rate is split equally between CGST and SGST — an 18% item carries 9% CGST and 9% SGST. For a sale to another state, the full rate is charged as IGST.",
  },
  {
    q: "How do I find the HSN code for a product?",
    a: "Open the product's page from this list to see its HSN code, or search the HSN code finder by name. Businesses with turnover up to ₹5 crore must print at least a 4-digit HSN code on B2B invoices; above ₹5 crore, 6 digits.",
  },
  {
    q: "Is this GST rate list official?",
    a: "No. It is a free reference compiled from the rate notifications. A rate can depend on a product's exact description and use, so confirm it with the notification or a tax professional before invoicing.",
  },
];

const BREADCRUMBS = [
  { name: "Home", url: BASE_URL },
  { name: "GST Rates List" },
];

/** "18% GST — Standard rate …", or just "12% GST" for a slab with no note. */
export function slabTitle(rate) {
  return SLAB_NOTES[rate] ? `${rate}% GST — ${SLAB_NOTES[rate]}` : `${rate}% GST`;
}

function titleCase(str) {
  return str.replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Products grouped by rate, lowest slab first, names A–Z within a slab. */
export function groupBySlab(products) {
  const groups = new Map();
  for (const p of products) {
    if (!groups.has(p.rate)) groups.set(p.rate, []);
    groups.get(p.rate).push(p);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a - b)
    .map(([rate, items]) => ({
      rate,
      items: [...items].sort((x, y) => x.product.localeCompare(y.product)),
    }));
}

export default function GstRatesIndexPage() {
  usePageTitle("GST Rates List 2026 — Product-wise GST Rates & HSN Codes");
  const [query, setQuery] = useState("");
  const products = allProducts();

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matching = q
      ? products.filter((p) => p.product.includes(q) || p.hsn.startsWith(q))
      : products;
    return groupBySlab(matching);
  }, [query, products]);

  const shown = groups.reduce((n, g) => n + g.items.length, 0);

  return (
    <div className="tool-page">
      <SeoHead
        title={`GST Rates List 2026 — ${products.length}+ Products with HSN Codes`}
        description="Product-wise GST rate list for 2026 after GST 2.0: 0%, 5%, 18% and 40% slabs with HSN codes and CGST/SGST split. Search any product — free, no login."
        path="/gst-rates"
        jsonLd={faqSchema(FAQS)}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb items={[{ label: "Home", to: "/" }, { label: "GST Rates List" }]} />
          <h1 className="tool-title">GST Rates List 2026 — Product-wise</h1>
          <p className="tool-subtitle">
            GST rates and HSN codes for {products.length}+ common goods and services under the
            GST 2.0 slabs. Pick a product for its CGST/SGST split and a worked example.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Filter by product name or HSN code
              <input
                className="calc-input"
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="e.g. cement, laptop, 8471"
              />
            </label>
            <p className="rate-label" aria-live="polite">
              {query ? `${shown} matching product${shown === 1 ? "" : "s"}` : `${shown} products`}
            </p>
            {groups.length === 0 && (
              <p>
                Nothing matches &ldquo;{query}&rdquo;. Try the <Link to="/hsn">HSN code finder</Link>, which
                searches every chapter.
              </p>
            )}
          </div>

          {groups.map((g) => (
            <section className="tool-info" key={g.rate} aria-labelledby={`slab-${g.rate}`}>
              <h2 id={`slab-${g.rate}`}>{slabTitle(g.rate)}</h2>
              <ul className="seo-links">
                {g.items.map((p) => (
                  <li key={p.product}>
                    <Link to={`/gst-rate/${productSlug(p.product)}`}>
                      GST on {titleCase(p.product)}
                    </Link>{" "}
                    <span className="hsn-code">HSN {p.hsn}</span>
                  </li>
                ))}
              </ul>
            </section>
          ))}

          <FaqSection faqs={FAQS}>
            <p>
              For the full rate notification by chapter, see the{" "}
              <Link to="/guides/gst-rates-list-2026">GST rates list guide</Link>, or work out the
              tax on an amount with the <Link to="/calculator">GST calculator</Link>.
            </p>
          </FaqSection>

          <RelatedTools current="/gst-rates" />
        </div>
      </main>
      <DoAideFooter />
    </div>
  );
}

export { FAQS };
