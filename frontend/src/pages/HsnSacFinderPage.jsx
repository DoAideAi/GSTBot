import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import FaqSection, { faqSchema } from "../components/FaqSection";
import EmailCapture from "../components/EmailCapture";
import PrintButton from "../components/PrintButton";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { byCategory, categories, searchHSN } from "../lib/hsnData";

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST HSN/SAC Code Finder",
  url: "https://gst.doaide.com/hsn-sac-finder",
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "HSN/SAC Code Finder" },
];

const RATE_COLORS = {
  0: "#34d399",
  0.25: "#34d399",
  3: "#60a5fa",
  5: "#60a5fa",
  12: "#fbbf24",
  18: "#f59e42",
  28: "#f87171",
};

function RateBadge({ rate }) {
  const color = RATE_COLORS[rate] || "var(--text-secondary)";
  return (
    <span className="hsn-rate-badge" style={{ color, borderColor: color }}>
      {rate}%
    </span>
  );
}

const FAQS = [
  {
    q: "What is a SAC code under GST?",
    a: "A Services Accounting Code (SAC) is a 6-digit code that classifies a service for GST. Every SAC code begins with 99 — for example 998231 for accounting and auditing services.",
  },
  {
    q: "Is SAC code mandatory on a service invoice?",
    a: "Yes, on the same terms as HSN codes for goods: at least 4 digits on B2B invoices for businesses with turnover up to ₹5 crore, and 6 digits on all invoices above ₹5 crore.",
  },
  {
    q: "What is the GST rate on most services?",
    a: "Most services are taxed at 18%. A few, such as restaurant service and economy air travel, are at 5%, usually without ITC. Healthcare, education and individual life and health insurance are exempt.",
  },
  {
    q: "Can one invoice carry both HSN and SAC codes?",
    a: "Yes. When an invoice covers goods and services, such as a machine and its installation, each line carries its own code and rate, unless it is a composite supply taxed at the principal supply's rate.",
  },
];

export default function HsnSacFinderPage() {
  usePageTitle("GST HSN/SAC Code Finder — Search by Product or Service");

  const [query, setQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("");
  const allCategories = useMemo(() => categories(), []);

  const results = useMemo(() => {
    if (query.trim()) {
      return searchHSN(query, { limit: 50 });
    }
    if (selectedCategory) {
      return byCategory(selectedCategory);
    }
    return [];
  }, [query, selectedCategory]);

  const showBrowse = !query.trim() && !selectedCategory;

  return (
    <div className="tool-page">
      <SeoHead
        title="GST HSN/SAC Code Finder — Search by Product or Service"
        description="Find the correct HSN or SAC code for any product or service. Search by name, code number, or browse by category. Includes GST rate for every code. Free, no login."
        path="/hsn-sac-finder"
        jsonLd={[TOOL_SCHEMA, faqSchema(FAQS)]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb items={[{ label: "Home", to: "/" }, { label: "HSN/SAC Code Finder" }]} />
          <h1 className="tool-title">HSN/SAC Code Finder</h1>
          <p className="tool-subtitle">
            Search by product name, service description, or code number. Browse by category. No sign-up required.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Search by Product, Service, or Code
              <input
                type="text"
                className="calc-input"
                value={query}
                onChange={(e) => { setQuery(e.target.value); setSelectedCategory(""); }}
                placeholder="e.g. laptop, cement, IT services, 8517"
                autoFocus
              />
            </label>

            {!query.trim() && (
              <label className="calc-label">
                Or Browse by Category
                <select
                  className="calc-select"
                  value={selectedCategory}
                  onChange={(e) => { setSelectedCategory(e.target.value); setQuery(""); }}
                >
                  <option value="">Select a category</option>
                  {allCategories.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </label>
            )}

            {showBrowse && (
              <div className="hsn-category-grid">
                {allCategories.map((cat) => (
                  <button
                    key={cat}
                    className="hsn-category-btn"
                    onClick={() => setSelectedCategory(cat)}
                  >
                    {cat}
                    <span className="hsn-category-count">{byCategory(cat).length}</span>
                  </button>
                ))}
              </div>
            )}


            {/* One short, always-mounted status line is what a screen reader
                announces — not the results table, which used to sit inside the
                live region and be read out in full on every keystroke. */}
            <p className="visually-hidden" role="status" aria-live="polite">
              {(query.trim() || selectedCategory) ? (results.length === 0 ? "No results found" : `${results.length} result${results.length === 1 ? "" : "s"} found`) : ""}
            </p>

            {results.length > 0 && (
              <div className="hsn-results">
                <div className="hsn-results-header">
                  <span>{results.length} result{results.length !== 1 ? "s" : ""} found</span>
                  {(query || selectedCategory) && (
                    <button
                      className="quiz-nav-btn"
                      onClick={() => { setQuery(""); setSelectedCategory(""); }}
                      style={{ fontSize: "0.85rem" }}
                    >
                      Clear
                    </button>
                  )}
                </div>
                <table className="hsn-table">
                  <thead>
                    <tr>
                      <th>Code</th>
                      <th>Type</th>
                      <th>Description</th>
                      <th>Category</th>
                      <th>GST Rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.map((item) => (
                      <tr key={item.code}>
                        <td>
                          <Link to={`/hsn/${item.code}`} className="hsn-code-link">
                            {item.code}
                          </Link>
                        </td>
                        <td>{item.sac ? "SAC" : "HSN"}</td>
                        <td>{item.desc}</td>
                        <td>{item.category}</td>
                        <td><RateBadge rate={item.rate} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {(query.trim() || selectedCategory) && results.length === 0 && (
              <p style={{ textAlign: "center", color: "var(--text-secondary)", padding: "1rem 0" }}>
                No results found. Try a different search term or browse by category.
              </p>
            )}

            {results.length > 0 && (
              <div className="calc-result-actions" style={{ marginTop: "1rem" }}>
                <ShareButtons
                  path="/hsn-sac-finder"
                  text={`Found ${results.length} HSN/SAC codes — search free on DoAide GST`}
                />
                <PrintButton label="Print Results" />
              </div>
            )}
          </div>

          <EmailCapture
            source="hsn-sac-finder"
            heading="Get notified on GST rate changes"
            subtext="We'll email you when GST rates change for your products or services."
            buttonLabel="Notify Me"
            compact
          />

          <section className="tool-info">
            <h2>What are HSN and SAC Codes?</h2>
            <p>
              HSN (Harmonized System of Nomenclature) codes classify goods for GST purposes, while
              SAC (Services Accounting Codes) classify services. Every GST invoice must include the
              correct HSN or SAC code.
            </p>
            <h3>HSN Code Requirements on Invoices</h3>
            <ul>
              <li><strong>Turnover up to ₹5 crore:</strong> 4-digit HSN code mandatory</li>
              <li><strong>Turnover above ₹5 crore:</strong> 6-digit HSN code mandatory</li>
              <li><strong>Exports/imports:</strong> 8-digit HSN code mandatory</li>
            </ul>
            <h3>Why Correct HSN/SAC Codes Matter</h3>
            <ul>
              <li>Wrong codes can lead to incorrect GST rates being applied</li>
              <li>Mismatched codes between buyer and seller cause ITC reconciliation failures</li>
              <li>Incorrect HSN codes can trigger GST audit notices</li>
              <li>HSN summary in GSTR-1 must match invoice-level codes</li>
            </ul>
          </section>

          <InlineCTA variant="save" />
          <FaqSection faqs={FAQS} />

          <RelatedTools current="/hsn-sac-finder" />
          <CrossProductLinks page="hsn-sac-finder" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}
