import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import AnimatedCounter from "../components/AnimatedCounter";
import BusinessCounter from "../components/BusinessCounter";
import DeadlineCountdown from "../components/DeadlineCountdown";
import GstNewsUpdates from "../components/GstNewsUpdates";
import RecentTools from "../components/RecentTools";
import SeoHead from "../components/SeoHead";
import StickyToolsBanner from "../components/StickyToolsBanner";
import TrendingTools from "../components/TrendingTools";
import { usePageTitle } from "../hooks/usePageTitle";
import { track } from "../lib/track";

const DOAIDE_PRODUCTS = [
  { name: "Docs", url: "https://docs.doaide.com" },
  { name: "Resume", url: "https://resume.doaide.com" },
  { name: "409A", url: "https://409a.doaide.com" },
  { name: "GST", url: "https://gst.doaide.com" },
  { name: "Contracts", url: "https://contracts.doaide.com" },
  { name: "Invoicer", url: "https://invoicer.doaide.com" },
  { name: "Jobs", url: "https://job.doaide.com" },
  { name: "Desk", url: "https://desk.doaide.com" },
  { name: "Pulse", url: "https://pulse.doaide.com" },
];

function RobotFace({ size = 32, color }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width={size} height={size} aria-hidden="true">
      <line x1="16" y1="6" x2="16" y2="2" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="16" cy="1.5" r="1.5" fill={color} />
      <rect x="5" y="6" width="22" height="17" rx="5" fill={color} />
      <ellipse cx="11" cy="13" rx="2.5" ry="3" fill="#0A0A0B" />
      <ellipse cx="21" cy="13" rx="2.5" ry="3" fill="#0A0A0B" />
      <circle cx="11.5" cy="12.5" r="1" fill={color} opacity="0.6" />
      <circle cx="21.5" cy="12.5" r="1" fill={color} opacity="0.6" />
      <path d="M12 19Q16 22 20 19" stroke="#0A0A0B" strokeWidth="1.2" fill="none" strokeLinecap="round" />
      <rect x="1" y="10" width="4" height="5" rx="2" fill={color} opacity="0.8" />
      <rect x="27" y="10" width="4" height="5" rx="2" fill={color} opacity="0.8" />
    </svg>
  );
}


const FEATURES = [
  {
    title: "GSTR-2B Reconciliation",
    desc: "Auto-match your purchase invoices against the GSTR-2B statement. Flag mismatches instantly.",
    icon: (
      <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
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
      <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect x="4" y="2" width="16" height="20" rx="2" />
        <line x1="8" y1="6" x2="16" y2="6" />
        <line x1="8" y1="10" x2="16" y2="10" />
        <line x1="8" y1="14" x2="12" y2="14" />
        <path d="M14 16l2 2 4-4" />
      </svg>
    ),
  },
  {
    title: "GST Return Filing",
    desc: "Prepare GSTR-1 and GSTR-3B returns in minutes. Export-ready for the GST portal.",
    icon: (
      <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="8" y1="13" x2="16" y2="13" />
        <line x1="8" y1="17" x2="13" y2="17" />
      </svg>
    ),
  },
  {
    title: "Deadline Alerts",
    desc: "Never miss a filing deadline. Get notified before GSTR-1 and GSTR-3B due dates.",
    icon: (
      <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M18 8A6 6 0 106 8c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.73 21a2 2 0 01-3.46 0" />
      </svg>
    ),
  },
  {
    title: "Supplier Tracking",
    desc: "Monitor supplier compliance scores. Know which suppliers file on time and which put your ITC at risk.",
    icon: (
      <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M23 21v-2a4 4 0 00-3-3.87" />
        <path d="M16 3.13a4 4 0 010 7.75" />
      </svg>
    ),
  },
  {
    title: "AI Invoice Parsing",
    desc: "Upload invoices in any format. AI extracts GSTIN, amounts, HSN codes, and tax breakup automatically.",
    icon: (
      <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
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
    desc: "Upload your sales and purchase invoices in any format — PDF, Excel, or structured data — or enter them manually.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
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
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
      </svg>
    ),
  },
  {
    step: "3",
    title: "File returns",
    desc: "Download your prepared GSTR-1 and GSTR-3B, ready to submit on the GST portal.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
        <polyline points="22 4 12 14.01 9 11.01" />
      </svg>
    ),
  },
];

const TESTIMONIALS = [
  { name: "Priya S.", role: "CA, Mumbai", stars: 5, quote: "DoAide GST cut our reconciliation time from 2 days to 20 minutes. The GSTR-2B matching is spot-on." },
  { name: "Rahul M.", role: "Founder, textile exports", stars: 5, quote: "We were missing ITC on mismatched invoices every month. DoAide caught them all in the first run." },
  { name: "Anita K.", role: "Accountant, retail chain", stars: 5, quote: "The free plan handles our monthly volume perfectly. Filing GSTR-3B used to be stressful — now it takes minutes." },
  { name: "Suresh Gupta", role: "Tax Consultant, Ahmedabad", stars: 4, quote: "The HSN code finder and penalty calculator are tools I use daily. Clients love the instant GST breakdowns." },
  { name: "Deepak Joshi", role: "Owner, electronics store, Jaipur", stars: 5, quote: "The invoice generator saved us from buying expensive billing software. We create 50+ invoices a month for free." },
  { name: "Meena R.", role: "Freelance accountant, Chennai", stars: 5, quote: "I handle GST for 12 small businesses. The return calendar and deadline alerts mean I never miss a date anymore." },
  { name: "Vikram Patel", role: "Startup founder, Bangalore", stars: 5, quote: "We didn't know our interstate invoices needed IGST instead of CGST+SGST. The GSTIN validator caught it before filing." },
  { name: "Sunita Agarwal", role: "CA firm, Kolkata", stars: 4, quote: "The ITC calculator handles Section 17(5) blocked credits correctly — something even some paid tools get wrong." },
];

const FAQ_ITEMS = [
  {
    q: "What is GST and who needs to file GST returns?",
    a: "GST is India’s indirect tax on goods and services. Every registered business must file GSTR-1 and GSTR-3B. Registration is mandatory above ₹40 lakhs turnover for goods.",
  },
  {
    q: "How does GSTR-2B reconciliation work?",
    a: "GSTR-2B lists your eligible ITC based on suppliers’ filings. Reconciliation matches your purchase invoices against it. DoAide automates this so you claim the right amount.",
  },
  {
    q: "What is Input Tax Credit (ITC) and how is it calculated?",
    a: "ITC lets you offset tax paid on purchases against your output liability. DoAide reconciles invoices with GSTR-2B and excludes blocked credits to calculate your eligible ITC.",
  },
  {
    q: "Is DoAide GST really free?",
    a: "Yes. All features are included free for up to 50 invoices per month — no credit card required. Paid plans start at ₹499/month for higher volumes.",
  },
  {
    q: "What are HSN codes and why do they matter for GST?",
    a: "HSN codes classify goods for tax purposes and determine the GST rate. Wrong codes cause tax and ITC mismatches. DoAide validates HSN codes on your invoices automatically.",
  },
  {
    q: "What happens if I miss a GST filing deadline?",
    a: "Late filing attracts ₹50/day penalty (capped at ₹5,000) plus 18% interest on unpaid tax. DoAide sends alerts before each deadline so you never miss one.",
  },
  {
    q: "Can DoAide GST help with GST compliance for small businesses?",
    a: "Yes. DoAide handles invoices, GSTR-2B reconciliation, ITC calculation, and return prep — built for Indian SMBs. The free plan covers most small businesses.",
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
    <section className="landing-instant">
      <h1 className="landing-hero-title">Free GST Tools for Indian Businesses</h1>
      <p className="landing-hero-subtitle">25+ free tools — no login required. Calculate GST, verify GSTIN, search HSN codes, and more.</p>
      <form onSubmit={handleSubmit} className="landing-search-box">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Enter any GSTIN to verify instantly — no sign-up needed"
          className="landing-search-input"
          spellCheck={false}
          autoComplete="off"
        />
        <button type="submit" className="btn btn-primary landing-search-btn">
          Verify
        </button>
      </form>
      <div className="landing-trust-bar">
        <div className="landing-trust-item">
          <strong><AnimatedCounter end={12000} suffix="+" /></strong>
          <span>Businesses trust DoAide</span>
        </div>
        <div className="landing-trust-sep" aria-hidden="true" />
        <div className="landing-trust-item">
          <strong><AnimatedCounter end={50000} suffix="+" /></strong>
          <span>Invoices processed</span>
        </div>
        <div className="landing-trust-sep" aria-hidden="true" />
        <div className="landing-trust-item">
          <strong>100%</strong>
          <span>Free to start</span>
        </div>
      </div>
      <div className="landing-compliance-badges">
        <div className="landing-badge">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="var(--good)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
          </svg>
          <span>GST-compliant calculations</span>
        </div>
        <div className="landing-badge">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="var(--good)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
            <polyline points="22 4 12 14.01 9 11.01" />
          </svg>
          <span>Updated for FY 2026-27</span>
        </div>
        <div className="landing-badge">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="var(--good)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="3" y="11" width="18" height="11" rx="2" />
            <path d="M7 11V7a5 5 0 0110 0v4" />
          </svg>
          <span>No login required</span>
        </div>
        <div className="landing-badge">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="var(--good)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
          <span>Results in seconds</span>
        </div>
      </div>

      {TOOL_CATEGORIES.map((cat) => (
        <div key={cat.title} className="landing-category">
          <h2 className="landing-category-title">{cat.title}</h2>
          <div className="landing-tool-cards">
            {cat.tools.map((t) => (
              <Link key={t.to} to={t.to} className="landing-tool-card">
                <strong>{t.title}</strong>
                <span>{t.desc}</span>
                <span className="landing-tool-cta">Use Now →</span>
              </Link>
            ))}
          </div>
        </div>
      ))}
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
      description: "Free plan with up to 50 invoices/month",
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
        description="India's #1 free GST toolkit — calculate CGST, SGST, IGST instantly, verify any GSTIN, search HSN codes & GST rates, track filing due dates. Trusted by 12,000+ businesses. No sign-up required."
        path="/"
        jsonLd={softwareAppSchema}
      />
      <header className="landing-header landing-visible">
        <a href="https://doaide.com" className="landing-brand">
          <RobotFace size={28} color="#F0B429" />
          <span className="landing-brand-text">
            DoAide <em>GST</em>
          </span>
        </a>
      </header>

      <main>
        <div style={{ maxWidth: 900, margin: "0 auto", padding: "0 1rem" }}>
          <RecentTools />
        </div>
        <InstantLookup />

        <BusinessCounter />

        <DeadlineCountdown />

        <section className="landing-section" aria-labelledby="features-heading">
          <h2 id="features-heading" className="landing-section-title">Everything You Need for GST Compliance</h2>
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
          <p className="landing-section-subtitle">Get started in under 2 minutes — no technical setup required.</p>
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
          <p className="landing-section-subtitle">Watch how Indian businesses save hours every month on GST compliance.</p>
          <div className="landing-demo-placeholder" onClick={() => track("demo_video_click")}>
            <div className="landing-demo-play" aria-label="Play demo video">
              <svg viewBox="0 0 24 24" width="48" height="48" fill="#F0B429" aria-hidden="true">
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
            </div>
            <p className="landing-demo-caption">2-minute walkthrough: Upload → Reconcile → File</p>
          </div>
        </section>

        <section className="landing-section" aria-labelledby="testimonials-heading">
          <h2 id="testimonials-heading" className="landing-section-title">Trusted by Indian Businesses</h2>
          <div className="landing-testimonials">
            {TESTIMONIALS.map((t) => (
              <blockquote key={t.name} className="landing-testimonial">
                <div style={{ display: "flex", gap: "2px", marginBottom: "8px" }}>
                  {Array.from({ length: 5 }, (_, i) => (
                    <span key={i} style={{ color: i < t.stars ? "var(--brand)" : "var(--ink-faint)", fontSize: "14px" }}>★</span>
                  ))}
                </div>
                <p>&ldquo;{t.quote}&rdquo;</p>
                <footer>
                  <strong>{t.name}</strong>
                  <span>{t.role}</span>
                </footer>
              </blockquote>
            ))}
          </div>
        </section>

        <PopularSearches />

        <GstNewsUpdates />

        <FaqSection />

        <div style={{ maxWidth: 900, margin: "0 auto", padding: "0 1rem" }}>
          <TrendingTools />
        </div>

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
          <h2>Need Automated GST Filing?</h2>
          <p>Free for up to 50 invoices/month — upload invoices, auto-reconcile GSTR-2B, and prepare returns in minutes.</p>
          <div className="landing-cta-actions">
            <a href="#root" className="btn btn-primary landing-cta-btn" onClick={(e) => { e.preventDefault(); track("signup_click"); window.scrollTo({ top: 0, behavior: "smooth" }); }}>
              Create Free Account
            </a>
            <Link to="/pricing" className="btn landing-cta-secondary">
              View Plans →
            </Link>
          </div>
        </section>
      </main>

      <StickyToolsBanner />
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
            <a href="https://doaide.com">About DoAide</a>
            <a href="mailto:support@doaide.com">Contact</a>
          </div>
        </div>
        <div className="landing-footer-trust">
          <div className="landing-footer-trust-item">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="var(--good)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
            <span>256-bit SSL encrypted</span>
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
            <span>Your data stays private</span>
          </div>
        </div>
        <div className="landing-footer-products">
          {DOAIDE_PRODUCTS.map((p) => (
            <a key={p.name} href={p.url} className="landing-footer-link">
              {p.name}
            </a>
          ))}
        </div>
        <div className="landing-footer-bottom">
          <a href="https://doaide.com" className="landing-footer-home">
            <RobotFace size={16} color="#F0B429" />
            doaide.com
          </a>
          <span className="landing-footer-copy">&copy; 2026 DoAide</span>
        </div>
      </footer>
    </div>
  );
}
