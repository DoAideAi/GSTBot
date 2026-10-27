import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import FaqSection, { faqSchema } from "../components/FaqSection";
import PrintButton from "../components/PrintButton";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import {
  daysBetween, deadlinesInMonth, FILER_TYPES, nextDeadlines, todayInIndia,
} from "../lib/returnDueDates";
import { STATE_CODES } from "../lib/stateCodes";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const STATES = STATE_CODES
  .filter((s) => /^(State|Union territory)$/.test(s.kind))
  .sort((a, b) => a.name.localeCompare(b.name));

function formatDate(isoDate) {
  const [y, m, d] = isoDate.split("-").map(Number);
  return `${d} ${MONTHS[m - 1].slice(0, 3)} ${y}`;
}

function countdown(days) {
  if (days < 0) return `Overdue by ${-days} day${days === -1 ? "" : "s"}`;
  if (days === 0) return "Due today";
  return `${days} day${days === 1 ? "" : "s"} remaining`;
}

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST Return Due Date Calendar",
  url: "https://gst.doaide.com/return-calendar",
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const FAQS = [
  {
    q: "What are the GST return due dates for monthly filers?",
    a: "GSTR-1 by the 11th and GSTR-3B by the 20th of the following month. GSTR-9 for the year is due on 31 December after the financial year ends.",
  },
  {
    q: "What are the due dates under the QRMP scheme?",
    a: "In the first two months of a quarter: optional IFF by the 13th and PMT-06 tax payment by the 25th. After the quarter: GSTR-1 by the 13th and GSTR-3B by the 22nd or 24th, depending on your state.",
  },
  {
    q: "Which states file quarterly GSTR-3B by the 22nd?",
    a: "Chhattisgarh, Madhya Pradesh, Gujarat, Maharashtra, Karnataka, Goa, Kerala, Tamil Nadu, Telangana, Andhra Pradesh, and the UTs of Daman and Diu, Dadra and Nagar Haveli, Puducherry, Andaman and Nicobar, and Lakshadweep. All others file by the 24th.",
  },
  {
    q: "Who can file GST returns quarterly?",
    a: "Taxpayers with aggregate turnover up to ₹5 crore in the previous financial year can opt into QRMP. They still pay tax monthly through PMT-06 but file GSTR-1 and GSTR-3B once a quarter.",
  },
  {
    q: "What are the due dates for composition dealers?",
    a: "CMP-08 by the 18th of the month after each quarter, and GSTR-4 by 30 April after the financial year ends.",
  },
  {
    q: "What happens if I miss a GST due date?",
    a: "A late fee of ₹50 a day (₹20 for nil returns), capped by turnover, plus 18% interest on tax paid late. The government sometimes extends a due date by notification; those extensions are not shown here.",
  },
];

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "Return Due Date Calendar" },
];

export default function ReturnDueDateCalendarPage() {
  usePageTitle("GST Return Due Date Calendar — Filing Deadlines 2026-27");

  const today = todayInIndia();
  const [thisYear, thisMonth] = today.split("-").map(Number);
  const [year, setYear] = useState(thisYear);
  const [month, setMonth] = useState(thisMonth);
  const [filer, setFiler] = useState("monthly");
  const [stateCode, setStateCode] = useState("");

  const dueDates = useMemo(() => deadlinesInMonth(year, month, filer, stateCode), [year, month, filer, stateCode]);
  const next = useMemo(() => nextDeadlines(today, filer, stateCode), [today, filer, stateCode]);

  function shiftMonth(by) {
    const total = year * 12 + (month - 1) + by;
    setYear(Math.floor(total / 12));
    setMonth((total % 12) + 1);
  }

  return (
    <div className="tool-page">
      <SeoHead
        title="GST Return Due Date Calendar 2026-27 — Monthly & QRMP Deadlines"
        description="GST return due dates for monthly, quarterly (QRMP) and composition filers: GSTR-1, GSTR-3B, IFF, PMT-06, CMP-08, GSTR-4 and GSTR-9, with the 22nd/24th split by state."
        path="/return-calendar"
        jsonLd={[TOOL_SCHEMA, faqSchema(FAQS)]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb items={[{ label: "Home", to: "/" }, { label: "Return Due Date Calendar" }]} />
          <h1 className="tool-title">GST Return Due Date Calendar</h1>
          <p className="tool-subtitle">
            Your GST filing deadlines by month, for how you file and where you are registered. No
            sign-up required.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              How you file
              <select className="calc-input" value={filer} onChange={(e) => setFiler(e.target.value)}>
                {FILER_TYPES.map((f) => (
                  <option key={f.key} value={f.key}>{f.label}</option>
                ))}
              </select>
            </label>

            {filer === "quarterly" && (
              <label className="calc-label">
                State of registration (sets the GSTR-3B date)
                <select className="calc-input" value={stateCode} onChange={(e) => setStateCode(e.target.value)}>
                  <option value="">Not chosen — show both dates</option>
                  {STATES.map((s) => (
                    <option key={s.code} value={s.code}>{s.name}</option>
                  ))}
                </select>
              </label>
            )}

            {next.length > 0 && (
              <div className="calc-result" aria-live="polite" data-testid="next-deadline">
                <div className="calc-result-row calc-total">
                  <span>Next deadline</span>
                  <strong>{formatDate(next[0].due)}</strong>
                </div>
                {next.map((d) => (
                  <div className="calc-result-row" key={d.form}>
                    <span>{d.form} — {d.covers}</span>
                    <strong>{countdown(daysBetween(today, d.due))}</strong>
                  </div>
                ))}
              </div>
            )}

            <div className="calendar-controls" style={{ marginTop: "1rem" }}>
              <button className="quiz-nav-btn" onClick={() => shiftMonth(-1)} aria-label="Previous month">←</button>
              <strong className="calendar-month-label">{MONTHS[month - 1]} {year}</strong>
              <button className="quiz-nav-btn" onClick={() => shiftMonth(1)} aria-label="Next month">→</button>
            </div>

            {dueDates.length === 0 ? (
              <p style={{ textAlign: "center", color: "var(--text-secondary)", padding: "1rem 0" }}>
                Nothing due in {MONTHS[month - 1]} {year}.
              </p>
            ) : (
              <div className="calendar-dates">
                {dueDates.map((d) => {
                  const days = daysBetween(today, d.due);
                  const isNext = next.some((n) => n.form === d.form && n.due === d.due);
                  return (
                    <div
                      key={`${d.form}-${d.due}`}
                      className={`calendar-date-card${days < 0 ? " past" : ""}${days >= 0 && days <= 3 ? " urgent" : ""}${days > 3 && days <= 7 ? " soon" : ""}`}
                    >
                      <div className="calendar-date-header">
                        <span className="calendar-type-badge">{d.form}</span>
                        <strong>{formatDate(d.due)}</strong>
                      </div>
                      <div className="calendar-date-label">{d.what} — {d.covers}</div>
                      <div className="calendar-date-countdown">
                        {isNext && <strong>Next up · </strong>}
                        {countdown(days)}
                        {d.optional && " · optional"}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            <div className="calc-result-actions" style={{ marginTop: "1rem" }}>
              <ShareButtons
                path="/return-calendar"
                text={`GST filing deadlines for ${MONTHS[month - 1]} ${year} — check free on DoAide GST`}
              />
              <PrintButton label="Print Calendar" />
            </div>
          </div>

          <EmailCapture
            source="return-calendar"
            heading="Never miss a GST deadline"
            subtext="Get free email reminders 3 days before every GST filing due date."
            buttonLabel="Remind Me"
            compact
          />

          <section className="tool-info">
            <h2>GST return due dates at a glance</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Return</th><th>Who files</th><th>Due</th></tr>
                </thead>
                <tbody>
                  <tr><td>GSTR-1</td><td>Monthly filers</td><td>11th of the next month</td></tr>
                  <tr><td>GSTR-3B</td><td>Monthly filers</td><td>20th of the next month</td></tr>
                  <tr><td>IFF (optional)</td><td>QRMP, months 1 and 2</td><td>13th of the next month</td></tr>
                  <tr><td>PMT-06</td><td>QRMP, months 1 and 2</td><td>25th of the next month</td></tr>
                  <tr><td>GSTR-1</td><td>QRMP, quarterly</td><td>13th after the quarter</td></tr>
                  <tr><td>GSTR-3B</td><td>QRMP, quarterly</td><td>22nd or 24th after the quarter, by state</td></tr>
                  <tr><td>CMP-08</td><td>Composition dealers</td><td>18th after the quarter</td></tr>
                  <tr><td>GSTR-4</td><td>Composition dealers</td><td>30 April after the year</td></tr>
                  <tr><td>GSTR-9</td><td>Regular taxpayers</td><td>31 December after the year</td></tr>
                </tbody>
              </table>
            </div>
            <p>
              Dates are as set by the CGST Rules; notified extensions are not shown. Missed one? Work
              out the cost with the <Link to="/late-fee-calculator">late fee calculator</Link> and
              the <Link to="/interest-calculator">interest calculator</Link>. See every year at once
              on the <Link to="/due-dates">due dates page</Link>.
            </p>
          </section>

          <FaqSection faqs={FAQS} />

          <InlineCTA variant="remind" />
          <RelatedTools current="/return-calendar" />
          <CrossProductLinks page="return-calendar" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}

export { FAQS };
