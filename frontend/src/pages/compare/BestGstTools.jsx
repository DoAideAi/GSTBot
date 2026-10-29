import { useState } from "react";
import { Link } from "react-router-dom";
import SeoHead from "../../components/SeoHead";
import ShareButtons from "../../components/ShareButtons";
import DoAideFooter from "../../components/DoAideFooter";
import ToolsNav from "../../components/ToolsNav";
import { usePageTitle } from "../../hooks/usePageTitle";

const TOOLS = [
  {
    rank: 1, name: "DoAide GST Calculator", free: true,
    features: ["CGST/SGST/IGST breakdown", "Inclusive & exclusive GST", "All GST 2.0 slab rates (5%, 18%, 40%)", "HSN code search", "GSTIN verification", "No signup required"],
    pricing: "100% Free", rating: "4.8", ratingCount: "4,100+",
    verdict: "Best overall free GST calculator with a full suite of GST tools — calculator, GSTIN lookup, HSN search, filing dates, and ITC calculator. No login needed.",
    link: "/calculator",
  },
  {
    rank: 2, name: "ClearTax GST Calculator", free: true,
    features: ["CGST/SGST/IGST breakdown", "Inclusive & exclusive GST", "Standard slab rates", "Part of ClearTax ecosystem"],
    pricing: "Free (basic) / Rs 7,999/yr (filing)", rating: "4.5", ratingCount: "2,800+",
    verdict: "Reliable basic calculator from a well-known brand. Filing and advanced features require paid plans.",
    link: "/compare/cleartax",
  },
  {
    rank: 3, name: "Zoho GST Calculator", free: false,
    features: ["Built into Zoho Books", "GST-compliant invoicing", "Bank reconciliation", "Inventory with GST"],
    pricing: "Rs 1,499/mo+", rating: "4.4", ratingCount: "1,200+",
    verdict: "Great if you use Zoho Books. Not available as a standalone free calculator.",
    link: "/compare/zoho-gst",
  },
  {
    rank: 4, name: "Tax2Win GST Calculator", free: true,
    features: ["Basic GST calculation", "Inclusive & exclusive modes", "Simple interface"],
    pricing: "Free (calculator only)", rating: "4.2", ratingCount: "900+",
    verdict: "Simple web-based calculator. Limited to basic calculations — no HSN search or GSTIN lookup.",
    link: null,
  },
  {
    rank: 5, name: "GSTHero Calculator", free: true,
    features: ["GST calculation", "GST return filing", "E-invoicing"],
    pricing: "Free (basic) / Paid plans", rating: "4.1", ratingCount: "600+",
    verdict: "Filing-focused platform with a basic free calculator. Signup required for most features.",
    link: null,
  },
];

const FAQ_ITEMS = [
  {
    q: "What is the best free GST calculator in India in 2026?",
    a: "DoAide GST Calculator is the best free GST calculator in India in 2026 — instant CGST, SGST and IGST calculation for every slab, plus free HSN code search, GSTIN verification and filing date reminders, with no signup.",
  },
  {
    q: "How to calculate GST online for free?",
    a: "Visit gst.doaide.com/calculator, enter the amount, select a GST 2.0 rate (5%, 18%, or 40%), choose inclusive or exclusive, and select intra or inter-state. It shows the CGST, SGST, or IGST breakdown.",
  },
  {
    q: "Is DoAide GST Calculator accurate?",
    a: "Yes. DoAide GST Calculator uses the latest GST 2.0 slab rates from CBIC. It supports all standard rates including 5%, 18%, and 40%. Results are instant and verified against official formulas.",
  },
  {
    q: "Do I need to sign up to use a free GST calculator?",
    a: "No. DoAide GST Calculator works instantly with no signup, no login, and no email required. Other calculators like ClearTax also offer free basic calculators, but advanced features typically require registration.",
  },
  {
    q: "Which GST calculator supports HSN code search?",
    a: "DoAide GST is one of the few platforms that combines a GST calculator with free HSN/SAC code search, GSTIN verification, and a filing dates calendar — all in one place without requiring an account.",
  },
];

const FAQ_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: FAQ_ITEMS.map((item) => ({
    "@type": "Question",
    name: item.q,
    acceptedAnswer: { "@type": "Answer", text: item.a },
  })),
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "Compare", url: "https://gst.doaide.com/compare" },
  { name: "Best Free GST Calculator India 2026" },
];

function FaqSection() {
  const [openIndex, setOpenIndex] = useState(null);
  return (
    <section className="compare-faq" aria-labelledby="faq-heading">
      <h2 id="faq-heading">Frequently Asked Questions</h2>
      <dl className="compare-faq-list">
        {FAQ_ITEMS.map((item, i) => (
          <div key={i} className="compare-faq-item">
            <dt>
              <button
                className="compare-faq-q"
                aria-expanded={openIndex === i}
                onClick={() => setOpenIndex(openIndex === i ? null : i)}
              >
                {item.q}
                <span aria-hidden="true">{openIndex === i ? "−" : "+"}</span>
              </button>
            </dt>
            {openIndex === i && <dd className="compare-faq-a">{item.a}</dd>}
          </div>
        ))}
      </dl>
    </section>
  );
}

export default function BestGstTools() {
  usePageTitle("Best Free GST Calculator India 2026 — Top 5 Compared | DoAide");

  return (
    <div className="tool-page">
      <SeoHead
        title="Best Free GST Calculator India 2026 — Top 5 Compared | DoAide"
        description="Compare the best free GST calculators in India for 2026. Side-by-side comparison of DoAide GST, ClearTax, Zoho, Tax2Win, and GSTHero — features, pricing, and ratings."
        path="/compare/best-gst-tools"
        jsonLd={FAQ_SCHEMA}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="compare-container">
          <div className="compare-hero">
            <h1>Best Free GST Calculator India 2026</h1>
            <p className="compare-intro">
              Looking for the best free GST calculator in India? We compared the top 5 GST
              calculators on features, pricing, accuracy, and ease of use to help you pick the
              right tool for your business.
            </p>
          </div>

          <section className="compare-section">
            <h2>Top 5 GST Calculators Compared</h2>
            {TOOLS.map((tool) => (
              <div key={tool.rank} className="compare-pricing-card" style={{ marginBottom: 24 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
                  <span style={{ background: tool.rank === 1 ? "var(--accent)" : "var(--muted)", color: tool.rank === 1 ? "#fff" : "inherit", borderRadius: "50%", width: 32, height: 32, display: "inline-flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 14 }}>
                    #{tool.rank}
                  </span>
                  <h3 style={{ margin: 0 }}>{tool.name}</h3>
                  {tool.free && <span style={{ background: "#22c55e20", color: "#22c55e", padding: "2px 10px", borderRadius: 12, fontSize: 12, fontWeight: 600 }}>FREE</span>}
                </div>
                <div className="compare-price">{tool.pricing}</div>
                <p style={{ margin: "8px 0", fontSize: 14 }}>{tool.verdict}</p>
                <ul style={{ margin: "12px 0", paddingLeft: 20 }}>
                  {tool.features.map((f) => <li key={f} style={{ fontSize: 14, marginBottom: 4 }}>{f}</li>)}
                </ul>
                <div style={{ display: "flex", gap: 16, alignItems: "center", fontSize: 13, color: "var(--text-secondary)" }}>
                  <span>⭐ {tool.rating}/5 ({tool.ratingCount} reviews)</span>
                  {tool.link && <Link to={tool.link} style={{ color: "var(--brand-ink)", textDecoration: "none", fontWeight: 500 }}>
                    {tool.rank === 1 ? "Try Free →" : "See comparison →"}
                  </Link>}
                </div>
              </div>
            ))}
          </section>

          <section className="compare-section">
            <h2>Feature Comparison Table</h2>
            <div className="compare-table-wrap">
              <table className="compare-table">
                <thead>
                  <tr>
                    <th>Feature</th>
                    <th>DoAide GST</th>
                    <th>ClearTax</th>
                    <th>Zoho</th>
                    <th>Tax2Win</th>
                    <th>GSTHero</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ["GST Calculator", true, true, true, true, true],
                    ["CGST/SGST/IGST Split", true, true, true, true, true],
                    ["HSN Code Search", true, true, false, false, false],
                    ["GSTIN Lookup", true, true, false, false, true],
                    ["Filing Dates Calendar", true, false, false, false, false],
                    ["ITC Calculator", true, true, false, false, true],
                    ["No Signup Required", true, false, false, true, false],
                    ["Mobile Friendly", true, true, true, true, true],
                    ["100% Free (All Tools)", true, false, false, false, false],
                  ].map(([name, ...vals]) => (
                    <tr key={name}>
                      <td>{name}</td>
                      {vals.map((v, i) => (
                        <td key={i} className={v ? "compare-yes" : "compare-no"}>{v ? "✓" : "✗"}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="compare-cta">
            <h2>Try India's Best Free GST Calculator</h2>
            <p>
              Calculate GST instantly — no signup, no fees. CGST, SGST, IGST breakdown for
              all slab rates. Plus free GSTIN lookup, HSN search, and filing reminders.
            </p>
            <div className="compare-cta-buttons">
              <Link to="/calculator" className="btn btn-primary">Open GST Calculator</Link>
              <Link to="/lookup" className="btn compare-cta-secondary">GSTIN Lookup</Link>
            </div>
          </section>

          <FaqSection />

          <section className="compare-links">
            <h2>Compare GST Tools</h2>
            <div className="compare-links-grid">
              <Link to="/compare/cleartax">DoAide GST vs ClearTax</Link>
              <Link to="/compare/zoho-gst">DoAide GST vs Zoho GST</Link>
              <Link to="/compare/tally">DoAide GST vs Tally Prime</Link>
              <Link to="/best-gst-software">Best GST Software in India 2026</Link>
            </div>
            <ShareButtons
              path="/compare/best-gst-tools"
              text="Best Free GST Calculator India 2026 — see the top 5 compared"
              label="Share this comparison"
            />
          </section>
        </div>
      </main>
      <DoAideFooter />
    </div>
  );
}
