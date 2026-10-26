import { Link } from "react-router-dom";
import SeoHead from "../components/SeoHead";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";

const TOOLS = [
  {
    to: "/calculator",
    title: "GST Calculator",
    desc: "Calculate CGST, SGST, and IGST tax breakdown instantly for any amount and GST rate slab. Supports both inclusive and exclusive calculations.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect x="4" y="2" width="16" height="20" rx="2" />
        <line x1="8" y1="6" x2="16" y2="6" />
        <line x1="8" y1="10" x2="10" y2="10" /><line x1="14" y1="10" x2="16" y2="10" />
        <line x1="8" y1="14" x2="10" y2="14" /><line x1="14" y1="14" x2="16" y2="14" />
        <line x1="8" y1="18" x2="16" y2="18" />
      </svg>
    ),
  },
  {
    to: "/lookup",
    title: "GSTIN Verification",
    desc: "Verify any GST Identification Number instantly. Check state code, PAN, entity number, and check digit validity — no sign-up required.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="11" cy="11" r="8" />
        <line x1="21" y1="21" x2="16.65" y2="16.65" />
      </svg>
    ),
  },
  {
    to: "/hsn",
    title: "HSN Code Search",
    desc: "Search HSN and SAC codes by product or service name. Find the correct GST rate for any item — covers all 5 GST slabs.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="8" y1="13" x2="16" y2="13" />
        <line x1="8" y1="17" x2="13" y2="17" />
      </svg>
    ),
  },
  {
    to: "/due-dates",
    title: "GST Filing Due Dates",
    desc: "Complete calendar of GST filing deadlines for FY 2025-26 and 2026-27 — GSTR-1, GSTR-3B, GSTR-9, GSTR-9C, CMP-08, and IFF.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect x="3" y="4" width="18" height="18" rx="2" />
        <line x1="16" y1="2" x2="16" y2="6" />
        <line x1="8" y1="2" x2="8" y2="6" />
        <line x1="3" y1="10" x2="21" y2="10" />
      </svg>
    ),
  },
  {
    to: "/penalty-calculator",
    title: "Penalty Calculator",
    desc: "Calculate late filing penalties and interest for GSTR-1, GSTR-3B, and GSTR-9. Get exact late fees based on days of delay.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
    ),
  },
  {
    to: "/eway-bill",
    title: "E-Way Bill Checker",
    desc: "Check if your shipment requires an e-way bill under GST. Enter consignment value and distance for instant results.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect x="1" y="3" width="15" height="13" rx="2" />
        <polygon points="16 8 20 8 23 11 23 16 16 16 16 8" />
        <circle cx="5.5" cy="18.5" r="2.5" /><circle cx="18.5" cy="18.5" r="2.5" />
      </svg>
    ),
  },
  {
    to: "/input-tax-credit",
    title: "ITC Eligibility Checker",
    desc: "Check if your purchase qualifies for Input Tax Credit under GST. Covers blocked credits and Section 16 conditions.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
        <polyline points="22 4 12 14.01 9 11.01" />
      </svg>
    ),
  },
  {
    to: "/composition-scheme",
    title: "Composition Scheme Checker",
    desc: "Check if your business is eligible for the GST Composition Scheme. Get applicable tax rates and turnover limits.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M16 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
        <circle cx="8.5" cy="7" r="4" />
        <line x1="20" y1="8" x2="20" y2="14" /><line x1="23" y1="11" x2="17" y2="11" />
      </svg>
    ),
  },
  {
    to: "/invoice-generator",
    title: "GST Invoice Generator",
    desc: "Create GST-compliant tax invoices with automatic CGST/SGST/IGST calculation. Download as PDF for free.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
        <polyline points="10 9 9 9 8 9" />
      </svg>
    ),
  },
  {
    to: "/reverse-charge",
    title: "Reverse Charge Calculator",
    desc: "Calculate GST liability under Reverse Charge Mechanism (RCM) for legal, GTA, director fees, and other services.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <polyline points="1 4 1 10 7 10" /><polyline points="23 20 23 14 17 14" />
        <path d="M20.49 9A9 9 0 005.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 013.51 15" />
      </svg>
    ),
  },
  {
    to: "/itc-mismatch",
    title: "ITC Mismatch Calculator",
    desc: "Compare GSTR-2A/2B data with your purchase books. Find mismatches, excess claims, and missing invoices.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" />
        <path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" />
      </svg>
    ),
  },
  {
    to: "/registration-checker",
    title: "Registration Eligibility Checker",
    desc: "Answer 7 questions to find out if GST registration is mandatory for your business. Covers all Section 22 & 24 scenarios.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M16 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
        <circle cx="8.5" cy="7" r="4" />
        <polyline points="17 11 19 13 23 9" />
      </svg>
    ),
  },
  {
    to: "/return-calendar",
    title: "Return Due Date Calendar",
    desc: "Monthly calendar of GST filing deadlines — GSTR-1, GSTR-3B, GSTR-9, CMP-08, and IFF. With countdown timers.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect x="3" y="4" width="18" height="18" rx="2" />
        <line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" />
        <line x1="3" y1="10" x2="21" y2="10" />
        <path d="M8 14h.01" /><path d="M12 14h.01" /><path d="M16 14h.01" />
        <path d="M8 18h.01" /><path d="M12 18h.01" />
      </svg>
    ),
  },
  {
    to: "/interest-calculator",
    title: "Interest Calculator",
    desc: "Calculate interest on late GST payment under Section 50. Supports 18% and 24% rates with month-wise breakdown.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <line x1="12" y1="1" x2="12" y2="23" /><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6" />
      </svg>
    ),
  },
  {
    to: "/reverse-gst-calculator",
    title: "Reverse GST Calculator",
    desc: "Remove GST from a GST-inclusive price. Get the base amount and CGST/SGST or IGST split for any slab.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <polyline points="1 4 1 10 7 10" /><path d="M3.51 15a9 9 0 102.13-9.36L1 10" />
      </svg>
    ),
  },
  {
    to: "/gst-on-gold",
    title: "GST on Gold Calculator",
    desc: "Calculate GST on gold jewellery, coins, and digital gold — 3% on the gold value plus 5% on making charges, with the exact final bill.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v10" /><path d="M15 9.5c0-1-1.3-1.8-3-1.8s-3 .8-3 1.8 1.3 1.8 3 1.8 3 .8 3 1.8-1.3 1.8-3 1.8-3-.8-3-1.8" />
      </svg>
    ),
  },
  {
    to: "/gst-on-real-estate",
    title: "GST on Real Estate Calculator",
    desc: "GST on under-construction flats, affordable housing, commercial property, and ready-to-move homes — 1%, 5%, and effective 12% rates.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M3 21h18" /><path d="M5 21V7l7-4 7 4v14" />
        <path d="M9 21v-6h6v6" /><path d="M9 10h.01" /><path d="M15 10h.01" />
      </svg>
    ),
  },
  {
    to: "/hsn-sac-finder",
    title: "HSN/SAC Code Finder",
    desc: "Search HSN and SAC codes by product name, service description, or code number. Browse by category with GST rates.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
        <line x1="8" y1="11" x2="14" y2="11" />
      </svg>
    ),
  },
  {
    to: "/late-fee-calculator",
    title: "Late Fee Calculator",
    desc: "Calculate late filing fees for GSTR-1, GSTR-3B, GSTR-9, and GSTR-4. CGST/SGST breakup with caps and nil return rates.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
        <line x1="4" y1="21" x2="20" y2="21" strokeDasharray="2 2" />
      </svg>
    ),
  },
  {
    to: "/gst-late-fee-interest-calculator",
    title: "Late Fee & Interest Calculator",
    desc: "Late fee plus 18% interest on a delayed return in one step — turnover-based caps, post-2023 GSTR-9 slabs, interest on the cash portion only.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
        <line x1="17" y1="17" x2="21" y2="21" />
      </svg>
    ),
  },
  {
    to: "/gstr9-checklist",
    title: "GSTR-9 Annual Return Checklist",
    desc: "Step-by-step interactive checklist to prepare your GSTR-9 annual return. Track progress across all sections.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11" />
      </svg>
    ),
  },
  {
    to: "/gstr9-summary",
    title: "GSTR-9 Summary Generator",
    desc: "Twelve months of GSTR-1 and GSTR-3B side by side: GSTR-9 table totals, month-wise mismatches, and the DRC-03 amount with interest.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect x="3" y="3" width="18" height="18" rx="2" /><line x1="3" y1="9" x2="21" y2="9" /><line x1="9" y1="9" x2="9" y2="21" />
      </svg>
    ),
  },
  {
    to: "/itc-time-limit",
    title: "ITC Time Limit Checker",
    desc: "Last date to claim input tax credit on any invoice or debit note under Section 16(4). FY 2025-26 closes on 30 November 2026.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9" /><polyline points="12 7 12 12 15 14" />
      </svg>
    ),
  },
  {
    to: "/itc-180-day-rule",
    title: "180-Day ITC Reversal Calculator",
    desc: "Rule 37 reversal when a supplier is not paid within 180 days: the amount, the GSTR-3B period, and 18% interest.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9" /><polyline points="12 7 12 12 15 14" />
      </svg>
    ),
  },
  {
    to: "/itc-reversal-rule-42",
    title: "Rule 42 ITC Reversal Calculator",
    desc: "Apportion common input tax credit between taxable and exempt supplies — C1, C2, D1, D2 and C3 worked out for you.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9" /><polyline points="12 7 12 12 15 14" />
      </svg>
    ),
  },
  {
    to: "/ecommerce-tcs-calculator",
    title: "E-commerce TCS Calculator",
    desc: "0.5% GST TCS under Section 52 and 0.1% Section 194-O TDS that Amazon, Flipkart and Meesho deduct from seller payouts.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9" /><polyline points="12 7 12 12 15 14" />
      </svg>
    ),
  },
  {
    to: "/gst-state-codes",
    title: "GST State Codes",
    desc: "Every GST state and UT code, with a finder that reads the state from any GSTIN.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9" /><polyline points="12 7 12 12 15 14" />
      </svg>
    ),
  },
  {
    to: "/itc-reconciliation-dashboard",
    title: "ITC Reconciliation Dashboard",
    desc: "Books vs GSTR-2B vs GSTR-3B for the whole year. Excess claims with interest exposure, unclaimed credit, the Section 16(4) countdown and suppliers to chase.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <line x1="6" y1="20" x2="6" y2="12" /><line x1="12" y1="20" x2="12" y2="6" /><line x1="18" y1="20" x2="18" y2="14" />
      </svg>
    ),
  },
  {
    to: "/gstr2b-reconciliation",
    title: "GSTR-2B Reconciliation",
    desc: "Match your purchase register with GSTR-2B to find mismatches, missing invoices, and ITC at risk. Free, no login needed.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" />
        <path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" />
      </svg>
    ),
  },
  {
    to: "/gstr3b-reconciliation",
    title: "GSTR-3B Reconciliation",
    desc: "Check GSTR-3B against GSTR-1 liability and GSTR-2B credit before filing — catch DRC-01B and DRC-01C notice risks in seconds.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <polyline points="1 4 1 10 7 10" />
        <polyline points="23 20 23 14 17 14" />
        <path d="M20.49 9A9 9 0 005.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 013.51 15" />
      </svg>
    ),
  },
  {
    to: "/filing-checklist",
    title: "Filing Checklist",
    desc: "Every document, pre-filing check and step for GSTR-1, GSTR-3B, GSTR-9 and CMP-08 — progress tracked in your browser.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M9 11l3 3L22 4" />
        <path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11" />
      </svg>
    ),
  },
  {
    to: "/composition-tax-calculator",
    title: "Composition Tax Calculator",
    desc: "Quarter-by-quarter CMP-08 tax on the right base for your category, reverse charge on top, late-payment interest, and a running check against the composition limit.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect x="4" y="2" width="16" height="20" rx="2" /><line x1="8" y1="6" x2="16" y2="6" />
        <line x1="8" y1="11" x2="10" y2="11" /><line x1="14" y1="11" x2="16" y2="11" /><line x1="8" y1="16" x2="10" y2="16" /><line x1="14" y1="16" x2="16" y2="16" />
      </svg>
    ),
  },
  {
    to: "/tools/composition-scheme-checker",
    title: "Composition Scheme Checker",
    desc: "Check eligibility for GST Composition Scheme. Get tax rates, quarterly tax estimate, and comparison with regular scheme.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M16 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
        <circle cx="8.5" cy="7" r="4" />
        <line x1="18" y1="8" x2="18" y2="14" /><line x1="21" y1="11" x2="15" y2="11" />
      </svg>
    ),
  },
  {
    to: "/embed",
    title: "Embed GST Widgets",
    desc: "Add free GST calculator, GSTIN lookup, or HSN code finder widgets to your own website with a single line of code.",
    icon: (
      <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#F0B429" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <polyline points="16 18 22 12 16 6" />
        <polyline points="8 6 2 12 8 18" />
      </svg>
    ),
  },
];

const GUIDES = [
  {
    to: "/guides/gst-registration",
    title: "How to Register for GST in India",
    desc: "Step-by-step GST registration guide. Documents required, eligibility, and common mistakes to avoid.",
  },
  {
    to: "/guides/how-to-file-gstr-1",
    title: "How to File GSTR-1",
    desc: "Complete guide to filing GSTR-1 for outward supplies. B2B, B2C, credit notes, and HSN summary.",
  },
  {
    to: "/guides/how-to-file-gstr-3b",
    title: "How to File GSTR-3B",
    desc: "Step-by-step GSTR-3B filing guide. Output liability, ITC claim, tax payment, and penalties.",
  },
  {
    to: "/blog/gst-filing-guide-india-2026",
    title: "GST Filing Guide for India 2026",
    desc: "Comprehensive overview of all GST returns, due dates, and filing requirements.",
  },
  {
    to: "/blog/hsn-code-lookup",
    title: "HSN Code Lookup Guide",
    desc: "How to find the correct HSN or SAC code for your products and services.",
  },
  {
    to: "/blog/gst-compliance-checklist-small-business",
    title: "GST Compliance Checklist",
    desc: "Monthly and quarterly GST compliance checklist for small businesses.",
  },
  {
    to: "/guides/input-tax-credit",
    title: "Input Tax Credit Guide",
    desc: "Complete ITC guide — eligibility, blocked credits, reversal rules, and practical examples.",
  },
  {
    to: "/guides/eway-bill",
    title: "E-Way Bill Guide",
    desc: "E-way bill rules, generation process, validity periods, exemptions, and penalties.",
  },
];

export default function ResourcesPage() {
  usePageTitle("Free GST Tools & Resources — Calculator, GSTIN Lookup, HSN Search");

  return (
    <div className="tool-page">
      <SeoHead
        title="Free GST Tools & Resources — Calculator, GSTIN Lookup, HSN Search"
        description="Complete collection of free GST tools for Indian businesses — GST calculator, GSTIN verification, HSN code search, filing due dates, and compliance guides."
        path="/resources"
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <h1 className="tool-title">Free GST Tools &amp; Resources</h1>
          <p className="tool-subtitle">
            Everything you need for GST compliance in India — free online tools and
            guides for calculating GST, verifying GSTIN numbers, searching HSN codes,
            and filing returns on time.
          </p>

          <section className="resources-section" aria-labelledby="tools-heading">
            <h2 id="tools-heading" className="resources-heading">Free GST Tools</h2>
            <div className="resources-grid">
              {TOOLS.map((t) => (
                <Link key={t.to} to={t.to} className="resources-card">
                  <div className="resources-icon">{t.icon}</div>
                  <h3>{t.title}</h3>
                  <p>{t.desc}</p>
                </Link>
              ))}
            </div>
          </section>

          <section className="resources-section" aria-labelledby="guides-heading">
            <h2 id="guides-heading" className="resources-heading">GST Guides &amp; Articles</h2>
            <div className="resources-grid">
              {GUIDES.map((g) => (
                <Link key={g.to} to={g.to} className="resources-card">
                  <h3>{g.title}</h3>
                  <p>{g.desc}</p>
                </Link>
              ))}
            </div>
          </section>

          <section className="resources-section" aria-labelledby="compare-heading">
            <h2 id="compare-heading" className="resources-heading">Compare GST Software</h2>
            <div className="resources-grid">
              <Link to="/best-gst-software" className="resources-card">
                <h3>Best GST Software in India 2026</h3>
                <p>Top 10 GST solutions compared &mdash; features, pricing, and ratings.</p>
              </Link>
              <Link to="/compare/cleartax" className="resources-card">
                <h3>DoAide GST vs ClearTax</h3>
                <p>Feature, pricing, and ease-of-use comparison.</p>
              </Link>
              <Link to="/compare/zoho-gst" className="resources-card">
                <h3>DoAide GST vs Zoho GST</h3>
                <p>Standalone vs ecosystem-based GST tools compared.</p>
              </Link>
              <Link to="/compare/tally" className="resources-card">
                <h3>DoAide GST vs Tally Prime</h3>
                <p>Web-based vs desktop GST software comparison.</p>
              </Link>
            </div>
          </section>

          <section className="resources-section" aria-labelledby="product-heading">
            <h2 id="product-heading" className="resources-heading">GST Compliance Platform</h2>
            <div className="resources-grid">
              <div className="resources-card resources-cta-card">
                <h3>Automate Your GST Filing</h3>
                <p>
                  Upload invoices, auto-reconcile with GSTR-2B, calculate ITC, and prepare
                  GSTR-1 &amp; GSTR-3B returns — free for up to 50 invoices/month.
                </p>
                <Link to="/" className="btn btn-primary resources-signup-btn">
                  Sign Up Free
                </Link>
              </div>
              <Link to="/pricing" className="resources-card">
                <h3>Pricing Plans</h3>
                <p>
                  Free forever for up to 50 invoices/month. Pro plans from ₹499/month
                  for higher volumes with priority support.
                </p>
              </Link>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}
