import { Link, Outlet } from "react-router-dom";
import SeoHead from "../components/SeoHead";
import { usePageTitle } from "../hooks/usePageTitle";

const ARTICLES = [
  {
    slug: "gst-filing-guide-india-2026",
    title: "Complete Guide to GST Filing in India 2026",
    description: "Step-by-step guide to filing GST returns — GSTR-1, GSTR-3B, and GSTR-2B reconciliation explained for Indian businesses.",
  },
  {
    slug: "hsn-code-lookup",
    title: "HSN Code Lookup: Everything You Need to Know",
    description: "Understand HSN codes, how to find the right code for your goods, and why accurate HSN classification matters for GST compliance.",
  },
  {
    slug: "gst-compliance-checklist-small-business",
    title: "GST Compliance Checklist for Small Businesses",
    description: "A practical checklist for small businesses to stay GST-compliant — from registration to return filing and ITC claims.",
  },
  {
    slug: "gst-registration-online-guide",
    title: "GST Registration Online: Complete Step-by-Step Guide 2026",
    description: "Step-by-step guide to GST registration online in India — documents required, portal walkthrough, timeline, and common rejection reasons.",
  },
  {
    slug: "gstr-3b-filing-guide",
    title: "GSTR-3B Filing: Due Dates, Format, and Common Mistakes",
    description: "Complete guide to GSTR-3B filing — due dates, format walkthrough, step-by-step process, 8 common mistakes, and late filing penalties.",
  },
  {
    slug: "itc-reconciliation-gstr-2a-guide",
    title: "ITC Reconciliation Under GST: How to Match GSTR-2A with Purchase Register",
    description: "Detailed guide to ITC reconciliation — match GSTR-2B with purchase register, resolve mismatches, and avoid ITC reversals.",
  },
  {
    slug: "gst-return-filing-calendar-2026-27",
    title: "GST Return Filing Calendar 2026-27: All Due Dates",
    description: "Complete GST filing calendar for FY 2026-27 — monthly due dates for GSTR-1, GSTR-3B, CMP-08, GSTR-9, with staggered deadlines by state.",
  },
  {
    slug: "e-invoice-under-gst-guide",
    title: "E-Invoice Under GST: Applicability, Format, and Process",
    description: "Comprehensive guide to e-invoicing under GST — turnover thresholds, IRN generation, schema format, IRP process, and penalties.",
  },
  {
    slug: "gst-penalties-interest-late-filing",
    title: "GST Penalties and Interest: Complete Guide to Avoiding Late Filing Fines",
    description: "All GST penalties in one place — late filing fees by return type, interest rates on unpaid tax, invoicing penalties, and practical tips to stay penalty-free.",
  },
  {
    slug: "gst-composition-scheme-guide",
    title: "GST Composition Scheme: Eligibility, Tax Rates & Benefits",
    description: "Everything about the Composition Scheme — eligibility, tax rates for manufacturers/traders/services, filing requirements, and a detailed comparison with regular GST.",
  },
  {
    slug: "eway-bill-gst-rules-guide",
    title: "E-Way Bill Under GST: Rules, Generation Process & Validity",
    description: "Complete guide to E-Way Bills — when required, how to generate, validity by distance, exemptions, penalties, and common mistakes to avoid.",
  },
  {
    slug: "how-to-file-gstr-1-step-by-step-2026",
    title: "How to File GSTR-1 Online Step by Step 2026",
    description: "Step-by-step guide to filing GSTR-1 online — login to GST portal, add invoices, verify B2B & B2C details, submit and file with DSC or EVC.",
  },
  {
    slug: "gst-registration-documents-required-2026",
    title: "GST Registration Documents Required 2026",
    description: "Complete checklist of documents needed for GST registration — PAN, Aadhaar, address proof, bank details for proprietorship, partnership, and company.",
  },
  {
    slug: "gstr-1-vs-gstr-3b-difference",
    title: "Difference Between GSTR-1 and GSTR-3B Explained",
    description: "Key differences between GSTR-1 and GSTR-3B — purpose, due dates, data granularity, ITC impact, and why filing order matters.",
  },
  {
    slug: "composition-scheme-vs-regular-scheme",
    title: "GST Composition Scheme vs Regular Scheme",
    description: "Compare Composition and Regular GST schemes — eligibility, tax rates, ITC rules, return filing frequency, and which is better for your business.",
  },
  {
    slug: "how-to-claim-input-tax-credit-gst",
    title: "How to Claim Input Tax Credit Under GST",
    description: "Step-by-step guide to claiming ITC — eligibility conditions, blocked credits, time limits, reversal rules, and GSTR-2B reconciliation.",
  },
  {
    slug: "gst-registration-complete-guide-2026",
    title: "Complete Guide to GST Registration in India 2026",
    description: "Everything about GST registration — types, eligibility, documents, online process, timelines, penalties, and post-registration compliance for all business types.",
  },
  {
    slug: "hsn-code-list-2026-complete-guide",
    title: "HSN Code List 2026 — Complete Guide to HSN Classification",
    description: "Complete HSN code list with GST rates for 2026. Understand the classification system, find codes for your products, and learn mandatory HSN requirements on invoices.",
  },
  {
    slug: "gst-2-changes-explained-india",
    title: "GST 2.0 Changes Explained — What's Changing in India's GST System",
    description: "Complete breakdown of GST 2.0 reforms — rate rationalization, slab restructuring, return simplification, e-invoicing expansion, and what businesses need to prepare for.",
  },
  {
    slug: "how-to-file-gst-returns-online",
    title: "How to File GST Returns Online — Complete Step-by-Step Guide 2026",
    description: "Step-by-step guide to filing GSTR-1, GSTR-3B, and GSTR-9 online. Due dates, late fees, QRMP scheme, and common mistakes to avoid.",
  },
  {
    slug: "gst-rates-services-2026",
    title: "GST Rates for Services 2026 — Complete Rate List with SAC Codes",
    description: "Complete GST rate list for all services in 2026 with SAC codes. IT, consulting, transport, healthcare, education, restaurants, hotels, and professional services.",
  },
  {
    slug: "difference-between-cgst-sgst-igst",
    title: "Difference Between CGST, SGST and IGST — Explained with Examples",
    description: "Understand when CGST+SGST vs IGST applies, how rates split, ITC set-off rules, and worked examples for interstate and intrastate supplies.",
  },
  {
    slug: "gst-late-filing-penalty-calculator",
    title: "GST Late Filing Penalty Calculator 2026",
    description: "Calculate GST late filing penalties and interest for GSTR-1, GSTR-3B, GSTR-9. Current rates, caps, worked examples, and an interactive calculator.",
  },
  {
    slug: "gst-compliance-tips-small-business-2026",
    title: "10 GST Compliance Tips Every Small Business Owner Must Know in 2026",
    description: "Practical GST compliance tips for Indian small businesses — avoid penalties, maximize ITC, file on time, and stay audit-ready.",
  },
  {
    slug: "reverse-charge-mechanism-gst-guide-2026",
    title: "Reverse Charge Mechanism Under GST — Complete Guide 2026",
    description: "Complete guide to RCM under GST — which services attract reverse charge, how to calculate, ITC eligibility, self-invoice rules, and GSTR-3B reporting.",
  },
  {
    slug: "gst-registration-process-step-by-step-2026",
    title: "GST Registration Process 2026: Complete Step-by-Step Guide",
    description: "Complete step-by-step guide to GST registration in India 2026 — eligibility, documents, portal walkthrough, Aadhaar authentication, timelines, and common rejection reasons.",
  },
  {
    slug: "gstr-3b-common-mistakes-how-to-avoid",
    title: "GSTR-3B Filing: Common Mistakes and How to Avoid Them",
    description: "Top 10 common GSTR-3B filing mistakes and how to avoid them — ITC mismatch, wrong tax period, missing RCM, GSTR-1 discrepancy, and penalty implications.",
  },
  {
    slug: "itc-rules-2026-what-every-business-must-know",
    title: "Input Tax Credit (ITC) Rules 2026: What Every Business Must Know",
    description: "Complete guide to ITC rules in 2026 — eligibility conditions, blocked credits, time limits, reversal rules, GSTR-2B matching, and ITC on capital goods.",
  },
  {
    slug: "gst-rate-finder-find-gst-rate-for-any-product",
    title: "GST Rate Finder: How to Find the Correct GST Rate for Any Product in 2026",
    description: "Find the right GST rate for any product or service — the 5%, 18% and 40% slabs, HSN and SAC codes, invoice rules, and common classification mistakes.",
  },
  {
    slug: "how-to-file-nil-gst-return-online-sms",
    title: "How to File a Nil GST Return Online (and by SMS) in 2026",
    description: "File nil GSTR-3B and GSTR-1 on the GST portal or by SMS to 14409 — who qualifies, SMS formats, due dates, late fees and mistakes to avoid.",
  },
  {
    slug: "gstr-1-vs-gstr-3b-mismatch-how-to-fix",
    title: "GSTR-1 vs GSTR-3B Mismatch: Why It Happens and How to Fix It",
    description: "Common causes of GSTR-1 and GSTR-3B mismatches, how to reconcile them, correcting errors with GSTR-1A, and replying to a DRC-01B notice.",
  },
  {
    slug: "gstr-9-annual-return-fy-2025-26-guide",
    title: "GSTR-9 Annual Return FY 2025-26: Due Date, Applicability, Late Fees",
    description: "Who must file GSTR-9 and GSTR-9C for FY 2025-26, the 31 December 2026 deadline, late fee slabs by turnover, table-wise walkthrough and pre-filing reconciliations.",
  },
  {
    slug: "gst-invoice-management-system-ims-guide",
    title: "GST Invoice Management System (IMS) Explained: Accept, Reject, Pending",
    description: "How IMS works on the GST portal — what accept, reject and pending do to your GSTR-2B and ITC, credit note rules, and a month-end IMS workflow.",
  },
  {
    slug: "gst-on-rental-income",
    title: "GST on Rental Income in India 2026: Rates, Exemptions & RCM",
    description: "When rent attracts GST — 18% on commercial property, the residential exemption, reverse charge on renting to registered businesses, and how to report rent in returns.",
  },
  {
    slug: "gst-rates-india-2026-complete-list",
    title: "GST Rates in India 2026: Complete List of All Slabs",
    description: "Every GST slab in force in 2026 — 0%, 5%, 18% and 40%, special rates for gold and diamonds, and where the old 12% and 28% goods moved.",
  },
];

export { ARTICLES };

export default function BlogLayout() {
  return (
    <div className="blog-layout">
      <header className="blog-header">
        <Link to="/" className="blog-home-link">← Back to DoAide GST</Link>
        <h1 className="blog-title">DoAide GST Blog</h1>
        <p className="blog-subtitle">Guides and resources for GST compliance in India</p>
      </header>
      <Outlet />
    </div>
  );
}

export function BlogIndex() {
  usePageTitle("GST Guides for Indian Businesses");
  return (
    <div className="blog-index">
      <SeoHead
        title="GST Guides for Indian Businesses — Filing, ITC, E-Invoicing & HSN Codes"
        description="Practical GST guides for Indian businesses: return filing, GSTR-1 and GSTR-3B, input tax credit, e-invoicing, e-way bills, registration and HSN codes."
        path="/blog"
      />
      {ARTICLES.map((a) => (
        <Link key={a.slug} to={`/blog/${a.slug}`} className="blog-card">
          <h2>{a.title}</h2>
          <p>{a.description}</p>
          <span className="blog-read-more">Read more →</span>
        </Link>
      ))}
    </div>
  );
}
