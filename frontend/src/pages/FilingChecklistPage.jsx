import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import Meter from "../components/Meter";
import PrintButton from "../components/PrintButton";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";

// Item ids are stable storage keys: progress saved against them survives a
// reworded label, so never reuse an id for a different obligation.
export const CHECKLISTS = {
  gstr1: {
    label: "GSTR-1 (monthly/quarterly sales return)",
    groups: [
      {
        title: "Documents to collect",
        items: [
          { id: "g1-sales", text: "All sales invoices for the period, serially numbered" },
          { id: "g1-notes", text: "Credit and debit notes issued during the period" },
          { id: "g1-exports", text: "Export invoices with shipping bill numbers and dates" },
          { id: "g1-advances", text: "Advances received against future supplies (Table 11)" },
        ],
      },
      {
        title: "Pre-filing checks",
        items: [
          { id: "g1-gstin", text: "B2B buyers' GSTINs verified as active" },
          { id: "g1-hsn", text: "HSN summary ready — 4 digits (turnover ≤ ₹5 crore) or 6 digits (above)" },
          { id: "g1-series", text: "Document series summary complete, cancelled invoices accounted for" },
          { id: "g1-pos", text: "Place of supply checked on inter-state invoices (IGST, not CGST+SGST)" },
        ],
      },
      {
        title: "Filing steps",
        items: [
          { id: "g1-upload", text: "B2B invoices uploaded or imported on the GST portal / IFF" },
          { id: "g1-b2c", text: "B2C summary (intra-state rate-wise, inter-state ≥ ₹1 lakh invoice-wise) entered" },
          { id: "g1-verify", text: "Summary reviewed against the sales register total" },
          { id: "g1-file", text: "Return filed with DSC or EVC, acknowledgement saved" },
        ],
      },
    ],
  },
  gstr3b: {
    label: "GSTR-3B (monthly summary return)",
    groups: [
      {
        title: "Documents to collect",
        items: [
          { id: "b3-2b", text: "GSTR-2B statement downloaded for the period" },
          { id: "b3-sales", text: "Outward supplies summary (matches what GSTR-1 reported)" },
          { id: "b3-itc", text: "Purchase register / ITC workings for the period" },
          { id: "b3-ledger", text: "Electronic cash and credit ledger balances checked" },
        ],
      },
      {
        title: "Pre-filing checks",
        items: [
          { id: "b3-match1", text: "Table 3.1(a) liability agrees with GSTR-1 — a gap invites a DRC-01B notice" },
          { id: "b3-match2b", text: "ITC claimed in Table 4 is within GSTR-2B — excess invites DRC-01C" },
          { id: "b3-rcm", text: "Reverse charge liability added (Table 3.1(d)) and its ITC claimed" },
          { id: "b3-reversal", text: "ITC reversals done — 180-day unpaid invoices, exempt-supply share (Rules 42/43)" },
          { id: "b3-interest", text: "Interest at 18% computed if tax is being paid after the due date" },
        ],
      },
      {
        title: "Filing steps",
        items: [
          { id: "b3-autopop", text: "Auto-populated figures reviewed, not accepted blindly" },
          { id: "b3-challan", text: "Shortfall paid through PMT-06 challan (cash ledger topped up)" },
          { id: "b3-offset", text: "Liability offset in the prescribed order (IGST credit first)" },
          { id: "b3-file", text: "Return filed with DSC or EVC, acknowledgement saved" },
        ],
      },
    ],
  },
  gstr9: {
    label: "GSTR-9 (annual return)",
    groups: [
      {
        title: "Documents to collect",
        items: [
          { id: "g9-returns", text: "All GSTR-1 and GSTR-3B filings for the financial year" },
          { id: "g9-books", text: "Audited financial statements / books of account" },
          { id: "g9-itc", text: "Year's ITC register and GSTR-2A/2B statements" },
          { id: "g9-amend", text: "Amendments and notes made in the next year's April–October returns" },
        ],
      },
      {
        title: "Pre-filing checks",
        items: [
          { id: "g9-turnover", text: "Turnover per returns reconciled with books (basis for Table 4/5)" },
          { id: "g9-itcrec", text: "ITC per 3B reconciled with 2A and books (Tables 6–8)" },
          { id: "g9-hsn", text: "HSN-wise outward summary ready (Table 17)" },
          { id: "g9-9c", text: "GSTR-9C applicability checked (turnover above ₹5 crore)" },
        ],
      },
      {
        title: "Filing steps",
        items: [
          { id: "g9-draft", text: "System-computed draft downloaded and differences explained" },
          { id: "g9-liability", text: "Additional liability, if any, paid through DRC-03" },
          { id: "g9-file", text: "Return filed before 31 December, acknowledgement saved" },
        ],
      },
    ],
  },
  cmp08: {
    label: "CMP-08 (composition scheme, quarterly)",
    groups: [
      {
        title: "Documents to collect",
        items: [
          { id: "c8-sales", text: "Quarter's sales summary from bills of supply" },
          { id: "c8-rcm", text: "Inward supplies liable to reverse charge, if any" },
        ],
      },
      {
        title: "Pre-filing checks",
        items: [
          { id: "c8-limit", text: "Cumulative turnover still within the composition limit (₹1.5 crore)" },
          { id: "c8-rate", text: "Right rate applied — 1% traders/manufacturers, 5% restaurants, 6% services" },
        ],
      },
      {
        title: "Filing steps",
        items: [
          { id: "c8-declare", text: "Self-assessed tax declared in CMP-08" },
          { id: "c8-pay", text: "Tax paid by the 18th of the month after the quarter" },
          { id: "c8-annual", text: "Reminder set for GSTR-4 (annual, 30 April)" },
        ],
      },
    ],
  },
};

const STORAGE_KEY = "gst_filing_checklist_v1";

export function loadChecked() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    return stored && typeof stored === "object" && !Array.isArray(stored) ? stored : {};
  } catch {
    return {};
  }
}

export function saveChecked(checked) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(checked));
  } catch {
    // Private windows refuse storage; the tracker still works for the visit.
  }
}

export function itemsOf(returnType) {
  return (CHECKLISTS[returnType]?.groups ?? []).flatMap((group) => group.items);
}

const SITE = "https://gst.doaide.com";

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST Return Filing Checklist",
  url: `${SITE}/filing-checklist`,
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const HOWTO_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "HowTo",
  name: "How to prepare a GST return for filing",
  description: "Collect the documents, run the pre-filing checks, and file — tracked with a checklist that remembers your progress.",
  step: [
    { "@type": "HowToStep", name: "Pick the return", text: "Choose GSTR-1, GSTR-3B, GSTR-9 or CMP-08 to load its checklist." },
    { "@type": "HowToStep", name: "Collect the documents", text: "Tick off invoices, notes, GSTR-2B and ledger balances as you gather them." },
    { "@type": "HowToStep", name: "Run the pre-filing checks", text: "Reconcile liability with GSTR-1 and ITC with GSTR-2B before you touch the portal." },
    { "@type": "HowToStep", name: "File and save the acknowledgement", text: "File with DSC or EVC and keep the acknowledgement; progress is saved in your browser." },
  ],
};

const FAQ_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    { "@type": "Question", name: "What documents are needed to file GSTR-3B?", acceptedAnswer: { "@type": "Answer", text: "The month's GSTR-2B statement, an outward supplies summary that matches GSTR-1, the purchase register with ITC workings, and the electronic cash and credit ledger balances." } },
    { "@type": "Question", name: "What should I check before filing GSTR-3B?", acceptedAnswer: { "@type": "Answer", text: "That the declared liability agrees with GSTR-1 (a gap invites a DRC-01B notice), ITC claimed is within GSTR-2B (excess invites DRC-01C), reverse charge is added, and interest is computed for late payment." } },
    { "@type": "Question", name: "Is my checklist progress saved?", acceptedAnswer: { "@type": "Answer", text: "Yes — in your own browser, per return type. Nothing is uploaded, and clearing browser data clears the tracker." } },
    { "@type": "Question", name: "What is the HSN requirement in GSTR-1?", acceptedAnswer: { "@type": "Answer", text: "Taxpayers with turnover up to ₹5 crore report 4-digit HSN codes; above ₹5 crore, 6-digit codes are mandatory in Table 12." } },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: SITE },
  { name: "GST Return Filing Checklist" },
];

export default function FilingChecklistPage() {
  usePageTitle("GST Return Filing Checklist — Document Tracker");

  const [returnType, setReturnType] = useState("gstr3b");
  const [checked, setChecked] = useState(loadChecked);

  useEffect(() => {
    saveChecked(checked);
  }, [checked]);

  const doneIds = checked[returnType] ?? [];
  const items = itemsOf(returnType);
  const doneCount = items.filter((item) => doneIds.includes(item.id)).length;

  const toggle = (id) => {
    setChecked((prev) => {
      const current = prev[returnType] ?? [];
      const next = current.includes(id)
        ? current.filter((x) => x !== id)
        : [...current, id];
      return { ...prev, [returnType]: next };
    });
  };

  const reset = () => {
    setChecked((prev) => ({ ...prev, [returnType]: [] }));
  };

  return (
    <div className="tool-page">
      <SeoHead
        title="GST Return Filing Checklist — Document Tracker"
        description="Free GST return filing checklist for GSTR-1, GSTR-3B, GSTR-9 and CMP-08. Track the documents to collect, pre-filing checks and filing steps — progress saved in your browser. No login."
        path="/filing-checklist"
        jsonLd={[TOOL_SCHEMA, HOWTO_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb items={[{ label: "Home", to: "/" }, { label: "Filing Checklist" }]} />
          <h1 className="tool-title">GST Return Filing Checklist</h1>
          <p className="tool-subtitle">
            Every document, check and step for your return — tick them off as you go.
            Progress is saved in your browser, per return. No sign-up required.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Which return are you filing?
              <select
                className="calc-select"
                value={returnType}
                onChange={(e) => setReturnType(e.target.value)}
              >
                {Object.entries(CHECKLISTS).map(([key, { label }]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
            </label>

            <div className="calc-result" aria-live="polite">
              <div className="calc-result-row">
                <span>Progress</span>
                <strong>{doneCount} of {items.length} done</strong>
              </div>
              <Meter value={doneCount} max={items.length} label="Checklist progress" />
            </div>

            {CHECKLISTS[returnType].groups.map((group) => (
              <section key={group.title}>
                <h2 className="calc-section-heading">{group.title}</h2>
                {group.items.map((item) => (
                  <label key={item.id} className="calc-checkbox-label">
                    <input
                      type="checkbox"
                      checked={doneIds.includes(item.id)}
                      onChange={() => toggle(item.id)}
                    />
                    {item.text}
                  </label>
                ))}
              </section>
            ))}

            <div className="calc-result-actions">
              <button type="button" className="btn" onClick={reset}>
                Reset This Checklist
              </button>
              <ShareButtons
                path="/filing-checklist"
                text={`📋 Free GST return filing checklist — ${doneCount} of ${items.length} steps done for my ${CHECKLISTS[returnType].label.split(" ")[0]}. Track yours free on DoAide GST`}
              />
              <PrintButton label="Print Checklist" />
            </div>
          </div>

          <EmailCapture
            source="filing-checklist"
            heading="Never miss a GST deadline"
            subtext="Get free email reminders before every GST filing deadline."
            buttonLabel="Remind Me"
            compact
          />

          <section className="tool-info">
            <h2>Why a Checklist Beats Memory</h2>
            <p>
              Most GST notices are not about fraud — they are about mismatches. A
              GSTR-3B that disagrees with GSTR-1 invites a <strong>DRC-01B</strong>{" "}
              intimation; ITC claimed beyond GSTR-2B invites <strong>DRC-01C</strong>.
              Both checks take two minutes <em>before</em> filing and weeks of
              correspondence after. The pre-filing sections above exist because of
              exactly those two notices.
            </p>
            <p>
              Your ticks are stored only in this browser — nothing is uploaded. Use
              the <Link to="/gstr3b-reconciliation">GSTR-3B reconciliation helper</Link>{" "}
              for the liability and ITC checks, the{" "}
              <Link to="/due-dates">due-dates calendar</Link> for the deadline, and the{" "}
              <Link to="/late-fee-calculator">late-fee calculator</Link> if one slipped.
            </p>
            <h3>Due Dates at a Glance</h3>
            <ul>
              <li><strong>GSTR-1</strong> — 11th of the next month (monthly) or 13th after the quarter (QRMP)</li>
              <li><strong>GSTR-3B</strong> — 20th of the next month (22nd/24th for QRMP states)</li>
              <li><strong>CMP-08</strong> — 18th of the month after the quarter</li>
              <li><strong>GSTR-9</strong> — 31 December after the financial year</li>
            </ul>
          </section>

          <InlineCTA variant="save" />
          <RelatedTools current="/filing-checklist" />
          <CrossProductLinks page="filing-checklist" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}
