import { useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";

/*
 * Canonical GST filing deadlines. Monthly filers follow the standard
 * calendar; quarterly (QRMP) filers have different dates for GSTR-3B
 * depending on their state — Cat A (22nd) vs Cat B (24th) — and use
 * IFF instead of monthly GSTR-1.
 *
 * Annual returns (GSTR-9, GSTR-9C) and composition scheme (CMP-08)
 * are included because users searching "GST filing due dates" need
 * the full picture, not just the monthly ones.
 */

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const RETURN_TYPES = [
  { key: "gstr1", label: "GSTR-1", color: "#4f8cff" },
  { key: "gstr3b", label: "GSTR-3B", color: "#34d399" },
  { key: "gstr9", label: "GSTR-9", color: "#f59e42" },
  { key: "gstr9c", label: "GSTR-9C", color: "#f87171" },
  { key: "cmp08", label: "CMP-08", color: "#a78bfa" },
  { key: "iff", label: "IFF (QRMP)", color: "#fbbf24" },
  { key: "pmt06", label: "PMT-06 (QRMP)", color: "#22d3ee" },
  { key: "gstr4", label: "GSTR-4", color: "#c084fc" },
];

function isQuarterEnd(monthIndex) {
  return monthIndex % 3 === 2; // Mar, Jun, Sep, Dec
}

/**
 * Builds the deadline rows for a given financial year.
 *
 * The tax period is one month behind the due-date month for monthly
 * returns (e.g. Jan return is due in Feb). Quarter-end months trigger
 * CMP-08 and suppress IFF. Annual returns appear once in December
 * of the following calendar year.
 */
function buildDeadlines(startYear) {
  const rows = [];

  // Monthly deadlines: April of startYear through March of startYear+1
  for (let m = 0; m < 12; m++) {
    const taxMonth = (m + 3) % 12; // 0-indexed: April=3, so shift
    const taxYear = m < 9 ? startYear : startYear + 1;
    const dueMonth = (taxMonth + 1) % 12;
    const dueYear = dueMonth === 0 ? taxYear + 1 : taxYear;
    const taxLabel = `${MONTHS[taxMonth]} ${taxYear}`;

    const deadlines = {};

    // GSTR-1: 11th of following month (monthly), 13th (quarterly).
    // GSTR-3B: 20th (monthly); 22nd/24th by state category (quarterly).
    // The quarterly dates ride on the quarter-end row, as /return-calendar
    // lists them — a QRMP filer reading only "11th" would file early or,
    // worse, believe the 3B was already late.
    const due = `${dueMonth + 1 > 9 ? "" : "0"}${dueMonth + 1}-${String(dueYear).slice(2)}`;
    deadlines.gstr1 = `${due} · 11th${isQuarterEnd(taxMonth) ? " (QRMP 13th)" : ""}`;
    deadlines.gstr3b = `${due} · 20th${isQuarterEnd(taxMonth) ? " (QRMP 22nd/24th)" : ""}`;

    // CMP-08: 18th of month following quarter-end
    if (isQuarterEnd(taxMonth)) {
      deadlines.cmp08 = `${dueMonth + 1 > 9 ? "" : "0"}${dueMonth + 1}-${String(dueYear).slice(2)} · 18th`;
    }

    // IFF: 13th of following month, only for non-quarter-end months
    if (!isQuarterEnd(taxMonth)) {
      deadlines.iff = `${due} · 13th`;
      // PMT-06: QRMP tax for the first two months of a quarter, 25th
      deadlines.pmt06 = `${due} · 25th`;
    }

    rows.push({ taxPeriod: taxLabel, ...deadlines });
  }

  // Annual returns for the FY
  rows.push({
    taxPeriod: `FY ${startYear}-${String(startYear + 1).slice(2)} (Annual)`,
    gstr9: `31st Dec ${startYear + 1}`,
    gstr9c: `31st Dec ${startYear + 1}`,
    gstr4: `30th Apr ${startYear + 1}`,
  });

  return rows;
}

const YEARS = [
  { label: "FY 2025-26", start: 2025 },
  { label: "FY 2026-27", start: 2026 },
];

const FAQ_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "What is the due date for GSTR-1 filing?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "GSTR-1 is due on the 11th of the month following the tax period for monthly filers, and the 13th for quarterly (QRMP) filers.",
      },
    },
    {
      "@type": "Question",
      name: "What is the due date for GSTR-3B filing?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "GSTR-3B is due on the 20th of the following month for monthly filers. Quarterly filers in Category A states file by the 22nd, and Category B states by the 24th.",
      },
    },
    {
      "@type": "Question",
      name: "When is the due date for GSTR-9 annual return?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "GSTR-9 (annual return) is due on 31st December of the year following the financial year. For example, GSTR-9 for FY 2025-26 is due on 31st December 2026.",
      },
    },
    {
      "@type": "Question",
      name: "What is the GSTR-9C reconciliation statement deadline?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "GSTR-9C is a self-certified reconciliation statement due on the same date as GSTR-9 — 31st December of the following year. It is mandatory for taxpayers with turnover above ₹5 crore.",
      },
    },
    {
      "@type": "Question",
      name: "When do composition scheme dealers file CMP-08?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "CMP-08 is a quarterly statement filed by composition scheme dealers. It is due on the 18th of the month following the quarter (e.g., 18th July for April-June quarter).",
      },
    },
    {
      "@type": "Question",
      name: "What is IFF and when is it due?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "IFF (Invoice Furnishing Facility) is for QRMP scheme taxpayers to upload B2B invoices in non-quarter months. It is due on the 13th of the following month and is optional.",
      },
    },
  ],
};

export default function DueDatesPage() {
  usePageTitle("GST Filing Due Dates 2026-27 — Complete Deadline Calendar");
  const [selectedYear, setSelectedYear] = useState(1); // default to FY 2026-27

  const year = YEARS[selectedYear];
  const deadlines = buildDeadlines(year.start);

  return (
    <div className="tool-page">
      <SeoHead
        title="GST Filing Due Dates 2025-26 & 2026-27 — Complete Calendar"
        description="Complete GST filing due dates calendar for FY 2025-26 and 2026-27. GSTR-1, GSTR-3B, GSTR-9, CMP-08, IFF, PMT-06, GSTR-4 deadlines for monthly and quarterly filers."
        path="/due-dates"
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container due-dates-container">
          <Breadcrumb />
          <h1 className="tool-title">GST Filing Due Dates Calendar</h1>
          <p className="tool-subtitle">
            All GST return filing deadlines for {year.label} — GSTR-1, GSTR-3B, GSTR-9, GSTR-9C,
            CMP-08, and IFF. Never miss a deadline.
          </p>

          <div className="calc-card">
            <div className="calc-mode-toggle" role="group" aria-label="Financial year">
              {YEARS.map((y, i) => (
                <button
                  key={y.label}
                  className={`calc-mode-btn${selectedYear === i ? " active" : ""}`}
                  onClick={() => setSelectedYear(i)}
                >
                  {y.label}
                </button>
              ))}
            </div>

            <div className="due-dates-legend" role="list" aria-label="Return types">
              {RETURN_TYPES.map((rt) => (
                <span key={rt.key} className="due-dates-legend-item" role="listitem">
                  <span className="due-dates-dot" style={{ background: rt.color }} aria-hidden="true" />
                  {rt.label}
                </span>
              ))}
            </div>

            <div className="due-dates-table-wrap">
              <table className="due-dates-table" aria-label={`GST deadlines for ${year.label}`}>
                <thead>
                  <tr>
                    <th>Tax Period</th>
                    {RETURN_TYPES.map((rt) => (
                      <th key={rt.key}>{rt.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {deadlines.map((row) => (
                    <tr key={row.taxPeriod} className={row.taxPeriod.includes("Annual") ? "due-dates-annual-row" : ""}>
                      <td className="due-dates-period">{row.taxPeriod}</td>
                      {RETURN_TYPES.map((rt) => (
                        <td key={rt.key} className={row[rt.key] ? "due-dates-filled" : "due-dates-empty"}>
                          {row[rt.key] || "—"}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <ShareButtons
              path="/due-dates"
              text={`GST filing due dates for ${year.label} — complete deadline calendar on DoAide GST`}
            />

            <EmailCapture
              source="filing-dates"
              heading="Get GST filing reminders"
              subtext="Never miss a deadline — get free email reminders before each GSTR-1 and GSTR-3B due date."
              buttonLabel="Get Reminders"
            />
          </div>

          <section className="tool-info">
            <h2>Understanding GST Filing Deadlines</h2>
            <p>
              GST-registered businesses in India must file periodic returns with the government.
              Missing a deadline attracts a late fee of ₹50 per day (₹20 for nil returns), capped
              at ₹2,000 to ₹10,000 by turnover, plus 18% annual interest on the outstanding tax —
              see the <Link to="/late-fee-calculator">late fee calculator</Link>. For the dates
              that apply to you alone, use the{" "}
              <Link to="/return-calendar">return calendar</Link>.
            </p>

            <h3>Monthly vs Quarterly Filing</h3>
            <p>
              Businesses with turnover up to ₹5 crore can opt for the QRMP (Quarterly Return
              Monthly Payment) scheme, filing GSTR-1 and GSTR-3B quarterly instead of monthly.
              Under QRMP, the Invoice Furnishing Facility (IFF) lets you upload B2B invoices
              monthly so your buyers can claim ITC without waiting for the quarter.
            </p>

            <h3>GSTR-3B Due Dates for Quarterly Filers</h3>
            <p>
              Quarterly GSTR-3B deadlines vary by state. Category A states (Chhattisgarh,
              Madhya Pradesh, Gujarat, Maharashtra, Karnataka, Goa, Kerala, Tamil Nadu,
              Telangana, Andhra Pradesh, Daman &amp; Diu, Puducherry, and others) file by the
              22nd. Category B states (remaining states and UTs) file by the 24th.
            </p>

            <h3>Annual Returns</h3>
            <p>
              GSTR-9 is the annual return required for all regular taxpayers. GSTR-9C, the
              self-certified reconciliation statement, is additionally required for taxpayers
              with turnover exceeding ₹5 crore. Both are due by 31st December of the following
              financial year.
            </p>

            <h3>Composition Scheme — CMP-08</h3>
            <p>
              Dealers under the composition scheme file CMP-08 quarterly instead of monthly
              GSTR-1 and GSTR-3B. The quarterly statement is due by the 18th of the month
              following the quarter. They also file an annual return (GSTR-4) by 30th April
              of the following year.
            </p>
          </section>

          <InlineCTA variant="remind" />
          <RelatedTools current="/due-dates" />
          <CrossProductLinks page="due-dates" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(FAQ_SCHEMA) }}
      />
    </div>
  );
}

export { buildDeadlines, FAQ_SCHEMA, MONTHS, RETURN_TYPES, YEARS };
