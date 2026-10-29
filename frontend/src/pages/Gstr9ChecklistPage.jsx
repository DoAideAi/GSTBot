import { useCallback, useMemo, useState } from "react";
import Breadcrumb from "../components/Breadcrumb";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import PrintButton from "../components/PrintButton";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";

const SECTIONS = [
  {
    title: "Part I — Basic Details",
    items: [
      { id: "1a", text: "Verify GSTIN, legal name, and trade name" },
      { id: "1b", text: "Confirm financial year and filing period" },
      { id: "1c", text: "Check if GSTR-9 is applicable (turnover above ₹2 crore threshold)" },
      { id: "1d", text: "Verify principal place of business address" },
    ],
  },
  {
    title: "Part II — Outward & Inward Supplies",
    items: [
      { id: "2a", text: "Reconcile GSTR-1 outward supplies with books of accounts" },
      { id: "2b", text: "Verify B2B taxable supplies (Table 4A)" },
      { id: "2c", text: "Verify B2C supplies and nil-rated/exempt supplies" },
      { id: "2d", text: "Check credit/debit notes issued during the year" },
      { id: "2e", text: "Reconcile advances received and adjusted" },
      { id: "2f", text: "Verify HSN-wise summary of outward supplies (Table 17)" },
    ],
  },
  {
    title: "Part III — Input Tax Credit",
    items: [
      { id: "3a", text: "Reconcile ITC as per GSTR-3B with books of accounts" },
      { id: "3b", text: "Verify ITC on inward supplies from GSTR-2B" },
      { id: "3c", text: "Check ITC reversals under Rule 37, 39, 42, 43" },
      { id: "3d", text: "Verify ITC on imports (goods & services)" },
      { id: "3e", text: "Check ineligible/blocked ITC under Section 17(5)" },
      { id: "3f", text: "Reconcile ITC availed vs ITC available in GSTR-2B" },
      { id: "3g", text: "Verify HSN-wise summary of inward supplies (Table 18)" },
    ],
  },
  {
    title: "Part IV — Tax Paid",
    items: [
      { id: "4a", text: "Verify tax paid through cash ledger (monthly GSTR-3B)" },
      { id: "4b", text: "Verify tax paid through ITC ledger" },
      { id: "4c", text: "Reconcile interest, late fee, penalty paid during the year" },
      { id: "4d", text: "Check TDS/TCS credits received and claimed" },
    ],
  },
  {
    title: "Part V — Amendments & Corrections",
    items: [
      { id: "5a", text: "Report any amendments to outward supplies of prior FY" },
      { id: "5b", text: "Report any amendments to inward supplies of prior FY" },
      { id: "5c", text: "Report ITC availed/reversed for prior FY in current year" },
      { id: "5d", text: "Check for any pending GSTR-1/3B amendments" },
    ],
  },
  {
    title: "Part VI — Other Information",
    items: [
      { id: "6a", text: "Report demands & refunds (if any)" },
      { id: "6b", text: "Report supplies received from composition dealers" },
      { id: "6c", text: "Report goods sent on approval basis / returns" },
      { id: "6d", text: "Cross-verify HSN summary with purchase/sales registers" },
      { id: "6e", text: "Verify late fee computation (₹200/day, CGST+SGST)" },
    ],
  },
  {
    title: "Pre-Filing Verification",
    items: [
      { id: "7a", text: "All GSTR-1 and GSTR-3B for the year are filed" },
      { id: "7b", text: "Books of accounts are finalized" },
      { id: "7c", text: "Tax audit (if applicable) is completed" },
      { id: "7d", text: "GSTR-9C reconciliation statement prepared (if turnover > ₹5 crore)" },
      { id: "7e", text: "Digital signature certificate (DSC) is ready" },
      { id: "7f", text: "Review for any pending ITC claims before GSTR-9 cut-off" },
    ],
  },
];

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GSTR-9 Annual Return Checklist",
  url: "https://gst.doaide.com/gstr9-checklist",
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const FAQ_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "Who needs to file GSTR-9?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "All regular GST-registered taxpayers must file GSTR-9. Composition dealers file GSTR-9A. Exempted if turnover is under ₹2 crore.",
      },
    },
    {
      "@type": "Question",
      name: "What is the due date for GSTR-9?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "GSTR-9 is due by 31st December of the following financial year. E.g., FY 2025-26 GSTR-9 is due by 31st Dec 2026.",
      },
    },
    {
      "@type": "Question",
      name: "Is GSTR-9C mandatory?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "GSTR-9C is mandatory for taxpayers with turnover above ₹5 crore. It is a self-certified reconciliation statement.",
      },
    },
    {
      "@type": "Question",
      name: "What is the late fee for GSTR-9?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "₹200/day (₹100 CGST + ₹100 SGST), subject to maximum of 0.5% of turnover in the state/UT.",
      },
    },
  ],
};

const STORAGE_KEY = "gstr9-checklist";

function loadChecked() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
  } catch {
    return {};
  }
}

export default function Gstr9ChecklistPage() {
  usePageTitle("GSTR-9 Annual Return Checklist — Free | DoAide GST");

  const [checked, setChecked] = useState(loadChecked);

  const toggle = useCallback((id) => {
    setChecked((prev) => {
      const next = { ...prev, [id]: !prev[id] };
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch { /* storage unavailable: nothing to keep */ }
      return next;
    });
  }, []);

  const resetAll = useCallback(() => {
    setChecked({});
    try { localStorage.removeItem(STORAGE_KEY); } catch { /* storage unavailable: nothing to keep */ }
  }, []);

  const allItems = useMemo(() => SECTIONS.flatMap((s) => s.items), []);
  const doneCount = useMemo(() => allItems.filter((i) => checked[i.id]).length, [checked, allItems]);
  const pct = allItems.length > 0 ? Math.round((doneCount / allItems.length) * 100) : 0;

  const sectionProgress = useMemo(
    () => SECTIONS.map((s) => {
      const done = s.items.filter((i) => checked[i.id]).length;
      return { done, total: s.items.length };
    }),
    [checked],
  );

  return (
    <div className="tool-page">
      <SeoHead
        title="GSTR-9 Annual Return Checklist — Free | DoAide GST"
        description="Complete GSTR-9 annual return checklist for GST. Step-by-step verification of outward supplies, ITC, tax paid, amendments, and HSN reconciliation."
        path="/gstr9-checklist"
        schemas={[TOOL_SCHEMA, FAQ_SCHEMA]}
      />
      <ToolsNav />
      <Breadcrumb
        items={[
          { label: "Home", to: "/" },
          { label: "Free Tools", to: "/resources" },
          { label: "GSTR-9 Checklist" },
        ]}
      />

      <main className="tool-main">
        <div className="tool-container">
          <h1 className="tool-title">GSTR-9 Annual Return Checklist</h1>
          <p className="tool-subtitle">
            Step-by-step checklist to prepare and verify your GST annual return. Progress is saved locally.
          </p>

          <div className="calc-card">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
              <span style={{ fontSize: "0.9rem", fontWeight: 500 }}>
                {doneCount} / {allItems.length} completed
              </span>
              <div style={{ display: "flex", gap: "0.5rem" }}>
                {doneCount > 0 && (
                  <button className="btn-secondary" onClick={resetAll} style={{ fontSize: "0.8rem", padding: "0.3rem 0.6rem" }}>
                    Reset All
                  </button>
                )}
                <PrintButton />
              </div>
            </div>
            <div style={{ height: 10, borderRadius: 5, background: "var(--surface-3, #252540)", overflow: "hidden", marginTop: "0.5rem" }}>
              <div style={{ height: "100%", borderRadius: 5, width: `${pct}%`, background: pct === 100 ? "#34d399" : "var(--brand)", transition: "width 0.3s ease" }} />
            </div>
            {pct === 100 && (
              <p style={{ marginTop: "0.75rem", color: "#34d399", fontWeight: 500 }}>
                All checks complete — your GSTR-9 is ready for filing!
              </p>
            )}
          </div>

          {SECTIONS.map((section, si) => {
            const sp = sectionProgress[si];
            return (
              <div key={section.title} className="calc-card" style={{ marginTop: "1rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
                  <h2 style={{ margin: 0, fontSize: "1rem", fontWeight: 600 }}>{section.title}</h2>
                  <span style={{ fontSize: "0.8rem", fontWeight: 500, color: sp.done === sp.total ? "#34d399" : "var(--ink-soft)", background: "var(--surface-3, #252540)", padding: "2px 8px", borderRadius: "4px" }}>
                    {sp.done}/{sp.total}
                  </span>
                </div>
                {section.items.map((item) => (
                  <label key={item.id} style={{ display: "flex", alignItems: "flex-start", gap: "0.75rem", padding: "0.6rem 0", borderBottom: "1px solid var(--surface-3, #252540)", cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={!!checked[item.id]}
                      onChange={() => toggle(item.id)}
                      style={{ marginTop: 3, flexShrink: 0 }}
                    />
                    <span style={{ fontSize: "0.9rem", lineHeight: 1.5, textDecoration: checked[item.id] ? "line-through" : "none", color: checked[item.id] ? "var(--ink-soft)" : "var(--ink)" }}>
                      {item.text}
                    </span>
                  </label>
                ))}
              </div>
            );
          })}

          <div className="calc-card" style={{ marginTop: "1.5rem" }}>
            <div className="calc-result-actions">
              <PrintButton />
              <ShareButtons title="GSTR-9 Annual Return Checklist" url="https://gst.doaide.com/gstr9-checklist" />
            </div>
          </div>

          <section className="tool-info">
            <h2>About GSTR-9 Annual Return</h2>
            <p>
              GSTR-9 is a consolidated annual return filed by regular GST-registered taxpayers. It summarizes all monthly/quarterly returns
              (GSTR-1 and GSTR-3B) filed during the financial year, covering outward supplies, input tax credit, tax paid, and amendments.
            </p>
            <p>
              Taxpayers with turnover above ₹5 crore must also file GSTR-9C, a self-certified reconciliation statement between GSTR-9
              and the audited financial statements. Use this checklist to ensure you have covered every section before filing.
            </p>
          </section>

          <EmailCapture context="gstr9-checklist" />
          <RelatedTools
            current="/gstr9-checklist"
            tools={[
              { to: "/late-fee-calculator", label: "Late Fee Calculator" },
              { to: "/return-calendar", label: "Return Calendar" },
              { to: "/interest-calculator", label: "Interest Calculator" },
              { to: "/itc-calculator", label: "ITC Calculator" },
            ]}
          />
          <CrossProductLinks />
          <DoAideFooter />
        </div>
      </main>
    </div>
  );
}
