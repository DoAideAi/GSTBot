import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import DoAideFooter from "../components/DoAideFooter";
import FaqSection, { faqSchema } from "../components/FaqSection";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { formatDay, itcClaimWindow } from "../lib/itcTimeLimits";

const PATH = "/itc-time-limit";

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "ITC Time Limit Checker — Section 16(4)",
  url: `https://gst.doaide.com${PATH}`,
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "ITC Time Limit Checker" },
];

const FAQS = [
  {
    q: "What is the last date to claim ITC for FY 2025-26?",
    a: "30 November 2026, or the date you file your GSTR-9 for 2025-26 if that is earlier. The GSTR-3B claiming the credit has to be filed by then, not just the invoice uploaded.",
  },
  {
    q: "Does the time limit run from the invoice date or the date I received the goods?",
    a: "From the financial year of the invoice date. An invoice dated in March 2026 belongs to FY 2025-26, even if the goods arrived in April.",
  },
  {
    q: "What about debit notes?",
    a: "Since 1 January 2021, a debit note counts from its own date, not the original invoice's. A debit note issued in May 2026 for a 2025 invoice can be claimed until 30 November 2027.",
  },
  {
    q: "Can ITC for FY 2017-18 to 2020-21 still be claimed?",
    a: "No new claims, but section 16(5) protects credit already claimed in any return filed up to 30 November 2021. Notices denying that credit can be challenged on that basis.",
  },
  {
    q: "My registration was cancelled and then restored. Does the deadline change?",
    a: "Section 16(6) allows credit for the cancelled period in returns filed within 30 days of the revocation order. It applies only if the credit was not already time-barred on the cancellation date.",
  },
];

function describeBasis(w) {
  if (w.basis === "16(5)") {
    return "Credit for FY 2020-21 and earlier stands only if it was claimed in a return filed by this date, under section 16(5).";
  }
  if (w.basis === "annual-return") {
    return `Your GSTR-9 for ${w.fy} was filed before 30 November, so the claimWindow closed on the day it was filed.`;
  }
  return `30 November after the end of FY ${w.fy}. Filing GSTR-9 for ${w.fy} before then closes it earlier.`;
}

export default function ItcTimeLimitPage() {
  usePageTitle("ITC Time Limit Checker — Last Date to Claim ITC under Section 16(4)");
  const [documentDate, setDocumentDate] = useState("");
  const [annualReturnDate, setAnnualReturnDate] = useState("");
  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);

  // Date inputs hand back "" for anything that is not a real date, so a null
  // window only ever means the invoice date is still empty.
  const claimWindow = useMemo(
    () => (documentDate ? itcClaimWindow({ documentDate, annualReturnDate, today }) : null),
    [documentDate, annualReturnDate, today],
  );

  return (
    <div className="tool-page">
      <SeoHead
        title="ITC Time Limit Checker — Last Date to Claim Input Tax Credit (Sec 16(4))"
        description="Find the last date to claim ITC on any invoice or debit note under Section 16(4). FY 2025-26 credit closes on 30 November 2026. Free, no login."
        path={PATH}
        jsonLd={[TOOL_SCHEMA, faqSchema(FAQS)]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">ITC Time Limit Checker</h1>
          <p className="tool-subtitle">
            Input tax credit you do not claim in time is lost for good. Enter an invoice or debit
            note date to see the last day you can claim it.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Invoice or debit note date
              <input
                type="date"
                className="calc-input"
                value={documentDate}
                onChange={(e) => setDocumentDate(e.target.value)}
              />
            </label>
            <label className="calc-label">
              Date you filed GSTR-9 for that year (if already filed)
              <input
                type="date"
                className="calc-input"
                value={annualReturnDate}
                onChange={(e) => setAnnualReturnDate(e.target.value)}
              />
            </label>

            {claimWindow && (
              <div className="calc-result" aria-live="polite">
                <div className="calc-result-row">
                  <span>Financial year</span>
                  <strong>{claimWindow.fy}</strong>
                </div>
                <div className="calc-result-row calc-total">
                  <span>Last date to claim ITC</span>
                  <strong>{formatDay(claimWindow.deadline)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>{claimWindow.daysLeft >= 0 ? "Days left" : "Closed"}</span>
                  <strong>
                    {claimWindow.daysLeft >= 0 ? claimWindow.daysLeft : `${-claimWindow.daysLeft} days ago`}
                  </strong>
                </div>
                <p>{describeBasis(claimWindow)}</p>
                {claimWindow.daysLeft >= 0 && claimWindow.basis !== "16(5)" && (
                  <p>
                    Claim it in a GSTR-3B filed on or before {formatDay(claimWindow.deadline)}. Check the
                    invoice is in your <Link to="/gstr2b-reconciliation">GSTR-2B</Link> first.
                  </p>
                )}
                <div className="calc-result-actions">
                  <ShareButtons
                    path={PATH}
                    text={`Last date to claim ITC for FY ${claimWindow.fy}: ${formatDay(claimWindow.deadline)} — checked free on DoAide GST`}
                    toolName="ITC Time Limit Checker"
                  />
                </div>
              </div>
            )}
          </div>

          <section className="tool-info">
            <h2>Before the claimWindow closes</h2>
            <ol>
              <li>Run a full-year <Link to="/itc-reconciliation-dashboard">books vs GSTR-2B vs GSTR-3B</Link> comparison and list credit still unclaimed.</li>
              <li>Chase suppliers whose invoices are missing from GSTR-2B. Credit they never report cannot be claimed at all.</li>
              <li>Claim what is left in the October GSTR-3B, due 20 November. A late October return filed by 30 November still counts.</li>
              <li>File <Link to="/gstr9-helper">GSTR-9</Link> only after the claim, since filing it early closes the claimWindow.</li>
            </ol>
            <p>
              Read the full guide:{" "}
              <Link to="/blog/last-date-to-claim-itc-fy-2025-26">last date to claim ITC for FY 2025-26</Link>.
            </p>
          </section>

          <FaqSection faqs={FAQS} />

          <RelatedTools current={PATH} />
        </div>
      </main>
      <DoAideFooter />
    </div>
  );
}

export { FAQS };
