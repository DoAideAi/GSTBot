import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import BrandMark from "../components/BrandMark";
import ThemeToggle from "../components/ThemeToggle";
import AnimatedCounter from "../components/AnimatedCounter";
import DeadlineCountdown from "../components/DeadlineCountdown";
import RecentTools from "../components/RecentTools";
import SeoHead from "../components/SeoHead";
import { usePageTitle } from "../hooks/usePageTitle";
import { track } from "../lib/track";
import { formatStat, getUsageStats } from "../lib/usageStats";


const FEATURES = [
  {
    title: "GSTR-2B Reconciliation",
    desc: "Auto-match your purchase invoices against the GSTR-2B statement. Flag mismatches instantly.",
    icon: (
      <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect x="3" y="3" width="8" height="10" rx="1.5" />
        <rect x="8" y="7" width="8" height="10" rx="1.5" />
        <circle cx="19" cy="17" r="3.5" />
        <line x1="21.5" y1="19.5" x2="23" y2="21" />
      </svg>
    ),
  },
  {
    title: "ITC Calculator",
    desc: "Calculate eligible Input Tax Credit automatically. Exclude blocked credits under Section 17(5).",
    icon: (
      <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect x="4" y="2" width="16" height="20" rx="2" />
        <line x1="8" y1="6" x2="16" y2="6" />
        <line x1="8" y1="10" x2="16" y2="10" />
        <line x1="8" y1="14" x2="12" y2="14" />
        <path d="M14 16l2 2 4-4" />
      </svg>
    ),
  },
  {
    title: "GST Return Preparation",
    desc: "Prepare GSTR-1 and GSTR-3B data for review and export. Complete filing separately on the GST portal.",
    icon: (
      <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="8" y1="13" x2="16" y2="13" />
        <line x1="8" y1="17" x2="13" y2="17" />
      </svg>
    ),
  },
  {
    title: "Deadline Alerts",
    desc: "Track GSTR-1 and GSTR-3B due dates and configure reminders for your filing workflow.",
    icon: (
      <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M18 8A6 6 0 106 8c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.73 21a2 2 0 01-3.46 0" />
      </svg>
    ),
  },
  {
    title: "Supplier Tracking",
    desc: "Monitor supplier compliance scores. Know which suppliers file on time and which put your ITC at risk.",
    icon: (
      <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M23 21v-2a4 4 0 00-3-3.87" />
        <path d="M16 3.13a4 4 0 010 7.75" />
      </svg>
    ),
  },
  {
    title: "AI Invoice Parsing",
    desc: "Upload supported invoice files. Review extracted GSTINs, amounts, HSN codes and tax breakdowns before using them.",
    icon: (
      <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M12 2L2 7l10 5 10-5-10-5z" />
        <path d="M2 17l10 5 10-5" />
        <path d="M2 12l10 5 10-5" />
      </svg>
    ),
  },
];

const HOW_IT_WORKS = [
  {
    step: "1",
    title: "Upload invoices",
    desc: "Upload supported PDFs, images or spreadsheets, or enter invoices manually. Review the extracted fields.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
        <polyline points="17 8 12 3 7 8" />
        <line x1="12" y1="3" x2="12" y2="15" />
      </svg>
    ),
  },
  {
    step: "2",
    title: "Auto-reconcile",
    desc: "DoAide matches your invoices against GSTR-2B, flags mismatches, and calculates eligible ITC.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
      </svg>
    ),
  },
  {
    step: "3",
    title: "Review and prepare",
    desc: "Review return summaries and export supported return data. Submission on the GST portal remains a separate step.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
        <polyline points="22 4 12 14.01 9 11.01" />
      </svg>
    ),
  },
];

const FAQ_ITEMS = [
  {
    q: "Who is DoAide GST for?",
    a: "DoAide GST supports Indian accounting firms and businesses with invoice review, GSTR-2B reconciliation and return preparation.",
  },
  {
    q: "How does GSTR-2B reconciliation work?",
    a: "Import your GSTR-2B statement and compare it with purchase invoices. Review mismatches, missing entries and duplicates before using the results to prepare a return.",
  },
  {
    q: "Does DoAide file returns automatically?",
    a: "No. DoAide helps prepare and export return data. You or your accountant must review the figures and complete submission on the GST portal.",
  },
  {
    q: "Is DoAide GST really free?",
    a: "The public GST tools are free without signing in. SMB and CA customers can join a limited 60-day free pilot with no payment details. See pricing for available places, usage limits and regular prices afterward.",
  },
  {
    q: "Can I review uploaded invoice data?",
    a: "Yes. Review the extracted fields and correct them before reconciliation. Extraction and matching still need your review.",
  },
  {
    q: "Can I book a demo for my firm?",
    a: "Yes. Use the Book a demo link to prepare an email request describing your workflow. Send the email to request a time; availability is confirmed by reply.",
  },
  {
    q: "Can I keep using the free GST tools?",
    a: "Yes. The calculators, lookups and guides remain available at their existing addresses on gst.doaide.com.",
  },
];

function FaqSection() {
  const [openIndex, setOpenIndex] = useState(null);

  return (
    <section className="landing-faq" aria-labelledby="faq-heading">
      <h2 id="faq-heading" className="landing-section-title">Frequently Asked Questions</h2>
      <dl className="landing-faq-list">
        {FAQ_ITEMS.map((item, i) => (
          <div key={i} className="landing-faq-item">
            <dt>
              <button
                className="landing-faq-q"
                aria-expanded={openIndex === i}
                onClick={() => setOpenIndex(openIndex === i ? null : i)}
              >
                {item.q}
                <span className="landing-faq-chevron" aria-hidden="true">{openIndex === i ? "−" : "+"}</span>
              </button>
            </dt>
            {openIndex === i && <dd className="landing-faq-a">{item.a}</dd>}
          </div>
        ))}
      </dl>
    </section>
  );
}

const TOOL_CATEGORIES = [
  {
    title: "Calculators",
    tools: [
      { to: "/calculator", title: "GST Calculator", desc: "CGST, SGST, IGST breakdown instantly" },
      { to: "/reverse-gst-calculator", title: "Reverse GST Calculator", desc: "Remove GST from an inclusive price" },
      { to: "/gst-on-gold", title: "GST on Gold", desc: "3% gold + 5% making charges, exact bill" },
      { to: "/gst-on-real-estate", title: "GST on Real Estate", desc: "Flats, affordable housing & commercial" },
      { to: "/penalty-calculator", title: "Penalty Calculator", desc: "Late filing penalties & interest" },
      { to: "/late-fee-calculator", title: "Late Fee Calculator", desc: "Late filing fees for any GST return" },
      { to: "/gst-late-fee-interest-calculator", title: "Late Fee + Interest", desc: "What a late return really costs" },
      { to: "/interest-calculator", title: "Interest Calculator", desc: "Interest on delayed GST payment" },
      { to: "/itc-calculator", title: "ITC Calculator", desc: "Calculate eligible Input Tax Credit" },
      { to: "/rcm-calculator", title: "RCM Calculator", desc: "Reverse charge mechanism with ITC" },
      { to: "/itc-time-limit", title: "ITC Time Limit", desc: "Last date to claim ITC under 16(4)" },
      { to: "/itc-180-day-rule", title: "180-Day ITC Reversal", desc: "Rule 37 reversal for unpaid suppliers" },
      { to: "/itc-reversal-rule-42", title: "Rule 42 ITC Reversal", desc: "Common credit on exempt supplies" },
    ],
  },
  {
    title: "Lookup & Verification",
    tools: [
      { to: "/lookup", title: "GSTIN Lookup", desc: "Verify any GST number — check validity & state" },
      { to: "/hsn", title: "HSN Code Finder", desc: "Search HSN/SAC codes & GST rates" },
      { to: "/hsn-sac-finder", title: "HSN/SAC Finder", desc: "Search codes by product name" },
      { to: "/gstin-validator", title: "GSTIN Validator", desc: "Validate format and checksum" },
      { to: "/registration-checker", title: "Registration Checker", desc: "Check if a business is GST registered" },
    ],
  },
  {
    title: "Compliance & Filing",
    tools: [
      { to: "/input-tax-credit", title: "ITC Eligibility", desc: "Check ITC eligibility for any purchase" },
      { to: "/eway-bill", title: "E-Way Bill Checker", desc: "Check if your shipment needs an e-way bill" },
      { to: "/reverse-charge", title: "Reverse Charge", desc: "Check RCM applicability" },
      { to: "/itc-mismatch", title: "ITC Mismatch Finder", desc: "Find mismatches in ITC claims" },
      { to: "/audit-checklist", title: "Audit Checklist", desc: "GSTR-9C compliance tracker" },
      { to: "/gstr9-checklist", title: "GSTR-9 Checklist", desc: "Annual return filing checklist" },
      { to: "/gstr9-summary", title: "GSTR-9 Summary", desc: "Annual GSTR-1 vs 3B reconciliation" },
      { to: "/itc-reconciliation-dashboard", title: "ITC Dashboard", desc: "Books vs GSTR-2B vs 3B for the year" },
      { to: "/composition-scheme", title: "Composition Scheme", desc: "Check eligibility & benefits" },
      { to: "/scheme-comparison", title: "Scheme Comparison", desc: "Regular vs Composition scheme" },
      { to: "/tools/composition-scheme-checker", title: "Composition Checker", desc: "Eligibility, tax rate & quarterly estimate" },
      { to: "/composition-tax-calculator", title: "Composition Tax Calculator", desc: "CMP-08 tax per quarter with RCM & interest" },
    ],
  },
  {
    title: "Planning & Reference",
    tools: [
      { to: "/due-dates", title: "Due Dates Calendar", desc: "Never miss a GST filing deadline" },
      { to: "/return-calendar", title: "Return Calendar", desc: "Full return due date calendar" },
      { to: "/invoice-generator", title: "Invoice Generator", desc: "Create GST-compliant invoices" },
      { to: "/payment-challan", title: "Payment Challan", desc: "Generate GST payment challans" },
      { to: "/registration-type-advisor", title: "Registration Advisor", desc: "Find the right GST registration type" },
      { to: "/turnover-limit", title: "Turnover Limit", desc: "Check GST registration threshold" },
    ],
  },
  {
    title: "GST 2.0 Tools",
    tools: [
      { to: "/rate-comparison", title: "Rate Comparison", desc: "Compare old vs new GST 2.0 rates" },
      { to: "/migration-checker", title: "Migration Checker", desc: "Check if contracts need rate updates" },
      { to: "/insurance-savings", title: "Insurance Savings", desc: "Calculate insurance GST savings" },
      { to: "/guides/gst-2-guide", title: "GST 2.0 Guide", desc: "Complete guide to GST 2.0 changes" },
    ],
  },
];

function InstantLookup() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  // Real aggregates from /meta/stats. The trust bar used to assert hardcoded
  // five-figure counts; now a figure appears only once the backend can back
  // it, and the always-true claims hold the line until then.
  const [stats, setStats] = useState(null);

  useEffect(() => {
    let mounted = true;
    getUsageStats().then((s) => {
      if (mounted) setStats(s);
    });
    return () => {
      mounted = false;
    };
  }, []);

  const trustItems = [];
  if (stats && formatStat(stats.businesses)) {
    trustItems.push({
      figure: <AnimatedCounter end={stats.businesses} suffix="+" />,
      label: "Businesses on DoAide GST",
    });
  }
  if (stats && formatStat(stats.invoices)) {
    trustItems.push({
      figure: <AnimatedCounter end={stats.invoices} suffix="+" />,
      label: "Invoices processed",
    });
  }
  trustItems.push({ figure: "25+", label: "Free GST tools" });
  trustItems.push({ figure: "100%", label: "Free to start" });

  const handleSubmit = (e) => {
    e.preventDefault();
    const q = query.trim().toUpperCase();
    if (!q) return;
    if (/^\d{2}[A-Z]{5}\d{4}[A-Z]\w/.test(q)) {
      navigate(`/gstin/${q}`);
    } else {
      navigate(`/lookup?q=${encodeURIComponent(q)}`);
    }
  };

  return (
    <section className="gst-hero">
      <div className="gst-wrap gst-hero-grid">
        <div className="gst-hero-copy">
          <span className="gst-eyebrow"><span /> For businesses &amp; accounting firms</span>
          <h1 className="landing-hero-title">Everyday GST work.<br /><em>A clearer starting point.</em></h1>
          <p className="landing-hero-subtitle">25+ free tools to calculate tax, check GSTINs and find the right codes. Your next task, without the clutter.</p>
          <div className="gst-hero-actions">
            <a href="#tools" className="btn btn-primary">Explore free tools <span aria-hidden="true">↗</span></a>
            <Link to="/login" className="btn btn-ghost">Open your workspace</Link>
          </div>
          <p><Link to="/pricing">Try SMB or CA free for 60 days</Link> · No payment details required. Limited pilot places.</p>
          <div className="landing-trust-bar">
            {trustItems.map((item) => (
              <div key={item.label} className="landing-trust-item"><strong>{item.figure}</strong><span>{item.label}</span></div>
            ))}
          </div>
        </div>
        <div className="gst-lookup-card">
          <div className="gst-card-overline"><span className="gst-tool-icon" aria-hidden="true">✓</span><span>QUICK CHECK</span></div>
          <h2>Start with a GSTIN.</h2>
          <p>Look up a business registration before you get to work.</p>
          <form onSubmit={handleSubmit} className="landing-search-box" role="search" aria-label="GSTIN verification">
            <label htmlFor="gstin-quick-check">GSTIN or business search</label>
            <input id="gstin-quick-check" type="text" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. 27AAPFU0939F1ZV" className="landing-search-input" spellCheck={false} autoComplete="off" aria-label="GSTIN or search term" />
            <button type="submit" className="btn btn-primary landing-search-btn">Verify <span aria-hidden="true">→</span></button>
          </form>
          <div className="gst-lookup-note"><span aria-hidden="true">↳</span> No login required for public tools.</div>
          <div className="gst-lookup-links"><Link to="/hsn">Find an HSN code ↗</Link><Link to="/calculator">Calculate GST ↗</Link></div>
        </div>
      </div>
    </section>
  );
}

const FEATURED_PATHS = ["/calculator", "/lookup", "/hsn", "/invoice-generator", "/itc-calculator", "/due-dates"];

function ToolsDirectory() {
  const [category, setCategory] = useState("Popular");
  const [search, setSearch] = useState("");
  const allTools = TOOL_CATEGORIES.flatMap((group) => group.tools.map((tool) => ({ ...tool, category: group.title })));
  const query = search.trim().toLowerCase();
  const shown = allTools.filter((tool) => {
    const matches = `${tool.title} ${tool.desc}`.toLowerCase().includes(query);
    if (query && category === "Popular") return matches;
    if (category === "Popular") return FEATURED_PATHS.includes(tool.to);
    return matches && (category === "All tools" || category === tool.category);
  });
  const reset = () => { setSearch(""); setCategory("Popular"); };

  return (
    <section className="gst-directory gst-wrap" id="tools" aria-labelledby="tools-heading">
      <div className="gst-section-heading"><div><p className="gst-kicker">Your GST toolkit</p><h2 id="tools-heading">What are you working on?</h2><p>Pick a tool and get straight to it. No account needed.</p></div>
        <label className="gst-tool-search"><span className="visually-hidden">Search GST tools</span><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></svg><input type="search" placeholder="Find a tool…" value={search} onChange={(e) => setSearch(e.target.value)} /></label>
      </div>
      <div className="gst-category-filters" role="group" aria-label="Filter GST tools">
        {["Popular", ...TOOL_CATEGORIES.map((group) => group.title), "All tools"].map((name) => <button key={name} type="button" aria-pressed={category === name} onClick={() => setCategory(name)}>{name}</button>)}
      </div>
      <p className="gst-results-count" role="status">{shown.length} {shown.length === 1 ? "tool" : "tools"}{query ? ` matching “${search.trim()}”` : " to get you started"}</p>
      <div className="landing-tool-cards">
        {shown.map((tool) => <Link key={tool.to} to={tool.to} className="landing-tool-card"><div className="gst-tool-top"><span className="gst-tool-icon" aria-hidden="true">{tool.category === "Calculators" ? "±" : tool.category === "Lookup & Verification" ? "⌕" : tool.category === "Compliance & Filing" ? "≡" : "◇"}</span><span className="gst-tool-arrow" aria-hidden="true">↗</span></div><strong>{tool.title}</strong><span>{tool.desc}</span><span className="landing-tool-cta">Open tool <span aria-hidden="true">→</span></span></Link>)}
      </div>
      {shown.length === 0 && <div className="gst-tools-empty"><h3>No matching tools</h3><p>Try a shorter search or choose another category.</p><button type="button" className="btn btn-ghost" onClick={reset}>Reset filters</button></div>}
      <div className="gst-directory-bottom"><span>Looking for a filing walkthrough?</span><Link to="/guides">Explore GST guides <span aria-hidden="true">→</span></Link></div>
    </section>
  );
}

const POPULAR_SEARCHES = [
  { label: "27AAPFU0939F1ZV", desc: "Sample GSTIN — Maharashtra", to: "/gstin/27AAPFU0939F1ZV" },
  { label: "HSN 8471", desc: "Computers & laptops — 18% GST", to: "/hsn?q=8471" },
  { label: "HSN 6109", desc: "T-shirts & vests — 5% GST", to: "/hsn?q=6109" },
  { label: "SAC 9983", desc: "Professional services — 18% GST", to: "/hsn?q=9983" },
  { label: "HSN 0402", desc: "Milk & cream — 5% GST", to: "/hsn?q=0402" },
  { label: "SAC 9954", desc: "Construction services — 18% GST", to: "/hsn?q=9954" },
];

function PopularSearches() {
  return (
    <section className="landing-section landing-popular" aria-labelledby="popular-heading">
      <h2 id="popular-heading" className="landing-section-title">Popular GST Lookups</h2>
      <p className="landing-section-subtitle">Common GSTIN verifications and HSN/SAC code searches — click to try instantly.</p>
      <div className="landing-popular-grid">
        {POPULAR_SEARCHES.map((s) => (
          <Link key={s.label} to={s.to} className="landing-popular-card">
            <code className="landing-popular-code">{s.label}</code>
            <span className="landing-popular-desc">{s.desc}</span>
          </Link>
        ))}
      </div>
    </section>
  );
}

export default function LandingPage() {
  usePageTitle("Free GST Tools India | GST Calculator, GSTIN Lookup & HSN Code Search");

  const softwareAppSchema = {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: "DoAide GST",
    url: "https://gst.doaide.com",
    applicationCategory: "BusinessApplication",
    applicationSubCategory: "Tax & Accounting",
    operatingSystem: "Any",
    description: "Free GST compliance suite for Indian businesses — GST calculator, GSTIN lookup, HSN code finder, GSTR-2B reconciliation, ITC calculator, invoice generator, and 25+ more tools.",
    offers: {
      "@type": "Offer",
      price: "0",
      priceCurrency: "INR",
      description: "Free public GST tools; account plans and limits are listed on the pricing page",
    },
    featureList: "GST Calculator, GSTIN Lookup, HSN Code Finder, GSTR-2B Reconciliation, ITC Calculator, Invoice Generator, Penalty Calculator, E-Way Bill Checker",
    screenshot: "https://gst.doaide.com/og-image.png",
    author: {
      "@type": "Organization",
      name: "DoAide",
      url: "https://doaide.com",
    },
  };

  return (
    <div className="landing-root">
      <SeoHead
        title="Free GST Calculator India | GSTIN Verification & HSN Code Search — DoAide GST"
        description="Free GST tools for Indian businesses: calculate tax breakdowns, look up GSTINs, search HSN codes and explore filing calendars. Public tools need no sign-up."
        path="/"
        jsonLd={softwareAppSchema}
      />
      <a href="#main" className="skip-link">Skip to content</a>
      <header className="landing-header landing-visible">
        <div className="gst-header-inner gst-wrap">
          <a href="https://doaide.com" className="landing-brand"><BrandMark /><span className="landing-brand-text">DoAide <em>GST</em></span></a>
          <nav className="gst-primary-nav" aria-label="Primary"><a href="#tools">Free tools</a><a href="#workflow">For your firm</a><Link to="/guides">Guides</Link><Link to="/pricing">Pricing</Link></nav>
          <div className="gst-header-actions"><ThemeToggle /><Link to="/login" className="gst-sign-in">Sign in</Link><a href="https://doaide.com/demo/" className="btn btn-primary gst-header-demo">Book a demo</a></div>
        </div>
      </header>
      <main id="main">
        <InstantLookup />
        <div className="gst-wrap gst-recent"><RecentTools /></div>
        <ToolsDirectory />

        <DeadlineCountdown />

        <section className="landing-section gst-workflow" id="workflow" aria-labelledby="features-heading">
          <p className="gst-kicker">Beyond the free tools</p>
          <h2 id="features-heading" className="landing-section-title">Invoice Review and Return Preparation</h2>
          <div className="landing-features-grid">
            {FEATURES.map((f) => (
              <div key={f.title} className="landing-feature-card">
                <div className="landing-feature-icon">{f.icon}</div>
                <h3>{f.title}</h3>
                <p>{f.desc}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="landing-section" aria-labelledby="how-heading">
          <h2 id="how-heading" className="landing-section-title">How It Works</h2>
          <p className="landing-section-subtitle">Import your data, review exceptions and prepare the figures for filing.</p>
          <div className="landing-steps">
            {HOW_IT_WORKS.map((s) => (
              <div key={s.step} className="landing-step">
                <div className="landing-step-icon">{s.icon}</div>
                <div className="landing-step-num">{s.step}</div>
                <h3>{s.title}</h3>
                <p>{s.desc}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="landing-section landing-demo" aria-labelledby="demo-heading">
          <h2 id="demo-heading" className="landing-section-title">See DoAide GST in Action</h2>
          <p className="landing-section-subtitle">Discuss your invoice review and reconciliation workflow in a demo for your firm.</p>
          <a href="https://doaide.com/demo/" className="btn btn-primary" onClick={() => track("demo_request_open")}>
            Book a demo
          </a>
          <p className="landing-demo-caption">Request a time by email. Availability is confirmed by reply.</p>
        </section>

        <PopularSearches />


        <FaqSection />


        <section className="landing-section landing-advisor-cta" aria-labelledby="advisor-heading">
          <h2 id="advisor-heading" className="landing-section-title">
            <svg viewBox="0 0 24 24" fill="currentColor" width="24" height="24" style={{ verticalAlign: "middle", marginRight: 6, color: "var(--brand, #2563eb)" }} aria-hidden="true">
              <path d="M12 1l2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5z" />
            </svg>
            Ask our AI Advisor any GST question — Free!
          </h2>
          <p style={{ textAlign: "center", color: "var(--text-secondary, #666)", maxWidth: 520, margin: "0 auto 16px" }}>
            Get instant answers on GST registration, filing, rates, ITC claims, and compliance — powered by AI.
          </p>
          <div style={{ textAlign: "center" }}>
            <Link to="/advisor" className="btn btn-primary">Try AI Advisor →</Link>
          </div>
        </section>

        <section className="landing-cta">
          <h2>Need Help Reconciling Client Invoices?</h2>
          <p>Explore invoice review, GSTR-2B matching and return preparation. Check current plans and limits before choosing an account plan.</p>
          <div className="landing-cta-actions">
            <Link to="/login" className="btn btn-primary landing-cta-btn" onClick={() => track("signup_click")}>
              Open GST App
            </Link>
            <Link to="/pricing" className="btn landing-cta-secondary">
              View Plans →
            </Link>
          </div>
        </section>
      </main>

      <footer className="landing-footer">
        <div className="landing-footer-nav">
          <div className="landing-footer-col">
            <h4>Free Tools</h4>
            <Link to="/calculator">GST Calculator</Link>
            <Link to="/lookup">GSTIN Lookup</Link>
            <Link to="/hsn">HSN Code Finder</Link>
            <Link to="/due-dates">Due Dates Calendar</Link>
            <Link to="/penalty-calculator">Penalty Calculator</Link>
            <Link to="/eway-bill">E-Way Bill Checker</Link>
            <Link to="/input-tax-credit">ITC Eligibility</Link>
            <Link to="/gstin-validator">GSTIN Validator</Link>
            <Link to="/scheme-comparison">Scheme Comparison</Link>
            <Link to="/itc-calculator">ITC Calculation</Link>
            <Link to="/embed">Embed Widget</Link>
            <Link to="/advisor">AI Advisor</Link>
          </div>
          <div className="landing-footer-col">
            <h4>Product</h4>
            <Link to="/pricing">Pricing</Link>
            <a href="#features-heading" onClick={(e) => { e.preventDefault(); document.getElementById("features-heading")?.scrollIntoView({ behavior: "smooth" }); }}>Features</a>
            <a href="#faq-heading" onClick={(e) => { e.preventDefault(); document.getElementById("faq-heading")?.scrollIntoView({ behavior: "smooth" }); }}>FAQ</a>
          </div>
          <div className="landing-footer-col">
            <h4>Resources</h4>
            <Link to="/resources">All GST Tools &amp; Guides</Link>
            <Link to="/guides">GST Guides</Link>
            <Link to="/blog">Blog</Link>
            <Link to="/best-gst-software">Best GST Software</Link>
            <Link to="/blog/gst-filing-guide-india-2026">GST Filing Guide</Link>
            <Link to="/guides/gst-registration-process">Registration Guide</Link>
            <Link to="/guides/gst-return-calendar-2026-27">Return Calendar</Link>
            <Link to="/guides/gst-rates-list-2026">GST Rates List</Link>
            <Link to="/blog/difference-between-cgst-sgst-igst">CGST vs SGST vs IGST</Link>
            <Link to="/blog/gst-late-filing-penalty-calculator">Penalty Calculator Guide</Link>
          </div>
          <div className="landing-footer-col">
            <h4>Compare</h4>
            <Link to="/compare/cleartax">DoAide vs ClearTax</Link>
            <Link to="/compare/zoho-gst">DoAide vs Zoho GST</Link>
            <Link to="/compare/tally">DoAide vs Tally Prime</Link>
            <Link to="/compare/busy">DoAide vs Busy</Link>
          </div>
          <div className="landing-footer-col">
            <h4>Company</h4>
            <a href="https://doaide.com/company/">About DoAide</a>
            <a href="mailto:support@doaide.com">Contact</a>
          </div>
        </div>
        <div className="landing-footer-trust">
          <div className="landing-footer-trust-item">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="var(--good)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
            <span>HTTPS connection</span>
          </div>
          <div className="landing-footer-trust-item">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="var(--good)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
              <polyline points="22 4 12 14.01 9 11.01" />
            </svg>
            <span>GST-compliant calculations</span>
          </div>
          <div className="landing-footer-trust-item">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="var(--good)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="3" y="11" width="18" height="11" rx="2" />
              <path d="M7 11V7a5 5 0 0110 0v4" />
            </svg>
            <span>Account-based access</span>
          </div>
        </div>
        <div className="landing-footer-bottom">
          <a href="https://doaide.com" className="landing-footer-home">
            <BrandMark size={20} />
            doaide.com
          </a>
          <span className="landing-footer-copy">&copy; 2026 DoAide</span>
        </div>
      </footer>
    </div>
  );
}
