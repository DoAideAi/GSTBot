import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import FaqSection, { faqSchema } from "../components/FaqSection";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { useToolFunnel } from "../hooks/useToolFunnel";
import { categories, byCategory, searchHSN } from "../lib/hsnData";
import { copyToClipboard } from "../lib/share";
import { track } from "../lib/track";

/** How long a query must stand before it counts as a search. */
const HSN_SEARCH_SETTLE_MS = 800;

const FAQS = [
  {
    q: "What is an HSN code?",
    a: "HSN (Harmonized System of Nomenclature) is an internationally standardised system of codes for classifying goods. Under GST, the HSN code on an invoice decides which tax rate applies to the item.",
  },
  {
    q: "How many digits of HSN code must I show on an invoice?",
    a: "Since 1 April 2021, businesses with turnover up to ₹5 crore must show at least 4 digits on B2B invoices (optional on B2C). Above ₹5 crore, 6 digits are required on all invoices.",
  },
  {
    q: "What is the difference between HSN and SAC codes?",
    a: "HSN codes classify goods; SAC (Services Accounting Code) codes classify services. SAC codes are 6 digits and always begin with 99.",
  },
  {
    q: "What happens if I use the wrong HSN code?",
    a: "A wrong code that leads to a lower rate means short-paid tax, which is recoverable with interest. A general penalty of up to ₹25,000 under Section 125 can also apply for an incorrect invoice.",
  },
];

export default function HsnFinderPage() {
  usePageTitle("HSN Code Finder — Search GST Rates by Product Name");
  const [query, setQuery] = useState("");
  const [copied, setCopied] = useState(null);
  const { start: startTool, complete: completeTool } = useToolFunnel("hsn_finder");

  const results = searchHSN(query);
  const cats = categories();

  // Counted once the query settles: tracking every keystroke logged "c",
  // "ce", "cem"… as six separate searches for one look-up of "cement".
  useEffect(() => {
    const term = query.trim();
    if (!term) return undefined;
    const timer = setTimeout(() => {
      track("hsn_search", { query: term });
      // Finished when a settled search found something: most visitors want
      // the rate on screen, not to copy the code, so a copy would undercount.
      if (searchHSN(term).length > 0) completeTool();
    }, HSN_SEARCH_SETTLE_MS);
    return () => clearTimeout(timer);
  }, [query, completeTool]);

  const handleCopy = async (text) => {
    const ok = await copyToClipboard(text);
    if (ok) {
      setCopied(text);
      setTimeout(() => setCopied(null), 2000);
    }
  };

  return (
    <div className="tool-page">
      <SeoHead
        title="HSN Code Finder — Search GST Rates by Product or Service"
        description="Find the correct HSN or SAC code and GST rate for any product or service. Search by name or code number. Free HSN code lookup — no signup required."
        path="/hsn"
        jsonLd={faqSchema(FAQS)}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">HSN / SAC Code Finder</h1>
          <p className="tool-subtitle">
            Search by product name or HSN code number. Find the correct GST rate instantly.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Search products or HSN/SAC codes
              <input
                type="search"
                className="calc-input"
                value={query}
                onChange={(e) => {
                  startTool();
                  setQuery(e.target.value);
                }}
                placeholder='e.g. "laptop", "1006", "construction services"'
                autoFocus
              />
            </label>


            {/* One short, always-mounted status line is what a screen reader
                announces — not the results table, which used to sit inside the
                live region and be read out in full on every keystroke. */}
            <p className="visually-hidden" role="status" aria-live="polite">
              {query.trim() ? (results.length === 0 ? "No results found" : `${results.length} result${results.length === 1 ? "" : "s"} found`) : ""}
            </p>

            {query.trim() && (
              <div className="hsn-results">
                {results.length === 0 ? (
                  <p className="hsn-empty">No matching HSN/SAC codes found. Try a different search term.</p>
                ) : (
                  <table className="hsn-table">
                    <thead>
                      <tr>
                        <th>Code</th>
                        <th>Description</th>
                        <th>GST Rate</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {results.map((item) => (
                        <tr key={item.code}>
                          <td className="hsn-code"><Link to={`/hsn/${item.code}`}>{item.code}</Link></td>
                          <td>
                            {item.desc}
                            {item.sac && <span className="hsn-sac-badge">SAC</span>}
                          </td>
                          <td className="hsn-rate">{item.rate}%</td>
                          <td>
                            <button
                              className="hsn-copy-btn"
                              onClick={() => handleCopy(item.code)}
                              aria-label={`Copy ${item.code}`}
                            >
                              {copied === item.code ? "Copied!" : "Copy"}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {results.length > 0 && (
                  <ShareButtons
                    path={`/hsn?q=${encodeURIComponent(query.trim())}`}
                    text={`HSN code for "${query.trim()}" — ${results[0].code} at ${results[0].rate}% GST. Search any product on DoAide GST`}
                  />
                )}
              </div>
            )}
          </div>

          {!query.trim() && (
            <section className="hsn-categories">
              <h2>Browse by Category</h2>
              <div className="hsn-cat-grid">
                {cats.map((cat) => {
                  const items = byCategory(cat);
                  return (
                    <button
                      key={cat}
                      className="hsn-cat-card"
                      onClick={() => setQuery(cat)}
                    >
                      <strong>{cat}</strong>
                      <span className="hsn-cat-count">{items.length} codes</span>
                    </button>
                  );
                })}
              </div>
            </section>
          )}

          <section className="hsn-categories" style={{ marginTop: "2rem" }}>
            <h2>Most Searched HSN Codes</h2>
            <div className="hsn-cat-grid">
              {[
                { code: "8517", label: "Mobile Phones" },
                { code: "8471", label: "Computers" },
                { code: "5208", label: "Cotton Fabric" },
                { code: "3004", label: "Medicines" },
                { code: "8703", label: "Motor Cars" },
                { code: "7113", label: "Jewellery" },
                { code: "2523", label: "Cement" },
                { code: "6109", label: "T-Shirts" },
                { code: "8528", label: "Televisions" },
                { code: "9403", label: "Furniture" },
                { code: "9983", label: "IT Services" },
                { code: "0401", label: "Milk" },
              ].map((item) => (
                <Link key={item.code} to={`/hsn/${item.code}`} className="hsn-cat-card">
                  <strong>{item.label}</strong>
                  <span className="hsn-cat-count">HSN {item.code}</span>
                </Link>
              ))}
            </div>
          </section>

          <section className="tool-info">
            <h2>What Are HSN and SAC Codes?</h2>
            <p>
              HSN (Harmonised System of Nomenclature) codes classify goods, while SAC (Services
              Accounting Code) codes classify services under GST. Every GST invoice must carry
              the correct HSN/SAC code — it determines the applicable tax rate.
            </p>
            <h3>HSN Reporting Requirements</h3>
            <ul>
              <li><strong>Up to ₹5 crore turnover:</strong> 4-digit HSN code on B2B invoices</li>
              <li><strong>Above ₹5 crore turnover:</strong> 6-digit HSN code on all invoices</li>
            </ul>
          </section>

          <InlineCTA variant="save" />
          <FaqSection faqs={FAQS} />

          <RelatedTools current="/hsn" />
          <CrossProductLinks page="hsn" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}
