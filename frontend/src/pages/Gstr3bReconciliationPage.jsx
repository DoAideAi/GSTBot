import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import PrintButton from "../components/PrintButton";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { formatINR } from "../lib/gstCalc";

const round2 = (n) => Math.round(n * 100) / 100;

// Rule 88C intimates a GSTR-1 vs 3B liability gap (DRC-01B), Rule 88D an ITC
// claim beyond GSTR-2B (DRC-01C). The portal tolerates small rounding, so a
// gap under one rupee is reported as matched rather than as a notice risk.
const TOLERANCE = 1;

export function reconcileGstr3b({ g1Tax, b3Tax, itc2b, itcClaimed }) {
  const hasLiability = Number.isFinite(g1Tax) && Number.isFinite(b3Tax);
  const hasItc = Number.isFinite(itc2b) && Number.isFinite(itcClaimed);
  if (!hasLiability && !hasItc) return null;

  const result = { liability: null, itc: null };

  if (hasLiability) {
    const diff = round2(b3Tax - g1Tax);
    let status = "matched";
    if (diff < -TOLERANCE) status = "shortfall";
    else if (diff > TOLERANCE) status = "excess";
    result.liability = { diff, status };
  }

  if (hasItc) {
    const diff = round2(itcClaimed - itc2b);
    let status = "matched";
    if (diff > TOLERANCE) status = "excess";
    else if (diff < -TOLERANCE) status = "unclaimed";
    result.itc = { diff, status };
  }

  return result;
}

const SITE = "https://gst.doaide.com";

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GSTR-3B Reconciliation Helper",
  url: `${SITE}/gstr3b-reconciliation`,
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const HOWTO_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "HowTo",
  name: "How to reconcile GSTR-3B before filing",
  description: "Compare GSTR-3B liability with GSTR-1 and ITC with GSTR-2B to catch DRC-01B and DRC-01C notices before they are issued.",
  step: [
    { "@type": "HowToStep", name: "Enter the liability figures", text: "Total tax per GSTR-1 for the period, and the tax you are declaring in GSTR-3B Table 3.1(a)." },
    { "@type": "HowToStep", name: "Enter the ITC figures", text: "ITC available in GSTR-2B, and the ITC you are claiming in GSTR-3B Table 4A." },
    { "@type": "HowToStep", name: "Read the verdicts", text: "A liability shortfall flags DRC-01B (Rule 88C) risk; an ITC excess flags DRC-01C (Rule 88D) risk." },
    { "@type": "HowToStep", name: "Fix before filing", text: "Correct the 3B figures, pay any shortfall with interest at 18% per annum, then file." },
  ],
};

const FAQ_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    { "@type": "Question", name: "What is a DRC-01B notice?", acceptedAnswer: { "@type": "Answer", text: "An intimation under Rule 88C, issued when GSTR-3B declares less tax than GSTR-1 reported. Pay the difference with interest or explain it within 7 days, or the next GSTR-1 is blocked." } },
    { "@type": "Question", name: "What is a DRC-01C notice?", acceptedAnswer: { "@type": "Answer", text: "An intimation under Rule 88D issued when ITC claimed in GSTR-3B exceeds what GSTR-2B makes available. You must reverse the excess with interest or explain it within 7 days, or the next GSTR-1 is blocked." } },
    { "@type": "Question", name: "Why does GSTR-3B differ from GSTR-1?", acceptedAnswer: { "@type": "Answer", text: "Common causes: amendments and credit notes reported in one return but not the other, advances taxed in 3B before invoicing, typos in manual 3B entry, and supplies reported in the wrong period." } },
    { "@type": "Question", name: "Can I claim more ITC than GSTR-2B shows?", acceptedAnswer: { "@type": "Answer", text: "No. Since 1 January 2022, Section 16(2)(aa) restricts ITC to invoices appearing in GSTR-2B. Claiming beyond it triggers DRC-01C and requires reversal with interest." } },
    { "@type": "Question", name: "What interest applies to a GSTR-3B shortfall?", acceptedAnswer: { "@type": "Answer", text: "18% per annum on the unpaid tax from the due date until payment, under Section 50. Wrongly availed and utilised ITC also attracts 18%." } },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: SITE },
  { name: "GSTR-3B Reconciliation" },
];

const LIABILITY_VERDICTS = {
  matched: { tone: "calc-valid", title: "Liability matches GSTR-1", text: "Table 3.1(a) agrees with GSTR-1 within rounding. No Rule 88C exposure on these figures." },
  shortfall: { tone: "calc-invalid", title: "3B is short of GSTR-1 — DRC-01B risk", text: "You are declaring less tax in GSTR-3B than GSTR-1 reported. Rule 88C flags exactly this; pay the difference with 18% interest or be ready to explain it within 7 days of the intimation." },
  excess: { tone: "calc-valid", title: "3B declares more than GSTR-1", text: "No notice risk — the department does not mind being overpaid — but check for a sale missing from GSTR-1 or an amendment yet to be reported, or you may be paying tax your buyer never sees as credit." },
};

const ITC_VERDICTS = {
  matched: { tone: "calc-valid", title: "ITC claim matches GSTR-2B", text: "Table 4A is within what GSTR-2B makes available. No Rule 88D exposure on these figures." },
  excess: { tone: "calc-invalid", title: "ITC claimed beyond GSTR-2B — DRC-01C risk", text: "Section 16(2)(aa) restricts ITC to invoices in GSTR-2B. Reverse the excess or chase the suppliers who have not filed GSTR-1 — their miss is your blocked credit." },
  unclaimed: { tone: "calc-valid", title: "ITC left unclaimed", text: "GSTR-2B offers more credit than you are claiming. Check for eligible invoices you missed — unclaimed ITC is interest-free working capital left on the table (watch the Section 16(4) time limit)." },
};

export default function Gstr3bReconciliationPage() {
  usePageTitle("GSTR-3B Reconciliation — Match GSTR-1 & GSTR-2B Before Filing");

  const [g1Tax, setG1Tax] = useState("");
  const [b3Tax, setB3Tax] = useState("");
  const [itc2b, setItc2b] = useState("");
  const [itcClaimed, setItcClaimed] = useState("");

  const result = useMemo(
    () =>
      reconcileGstr3b({
        g1Tax: parseFloat(g1Tax),
        b3Tax: parseFloat(b3Tax),
        itc2b: parseFloat(itc2b),
        itcClaimed: parseFloat(itcClaimed),
      }),
    [g1Tax, b3Tax, itc2b, itcClaimed],
  );

  const shareText = useMemo(() => {
    if (!result) return "✅ Reconcile GSTR-3B with GSTR-1 and GSTR-2B before filing — free on DoAide GST";
    const clean =
      result.liability?.status !== "shortfall" && result.itc?.status !== "excess";
    return clean
      ? "✅ My GSTR-3B reconciles with GSTR-1 and GSTR-2B — checked free on DoAide GST"
      : "⚠️ Caught a GSTR-3B mismatch before filing — check yours free on DoAide GST";
  }, [result]);

  return (
    <div className="tool-page">
      <SeoHead
        title="GSTR-3B Reconciliation — Match GSTR-1 & GSTR-2B Before Filing"
        description="Reconcile GSTR-3B with GSTR-1 liability and GSTR-2B ITC before filing. Catch DRC-01B and DRC-01C notice risks in seconds. Free, no login required."
        path="/gstr3b-reconciliation"
        jsonLd={[TOOL_SCHEMA, HOWTO_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb items={[{ label: "Home", to: "/" }, { label: "GSTR-3B Reconciliation" }]} />
          <h1 className="tool-title">GSTR-3B Reconciliation Helper</h1>
          <p className="tool-subtitle">
            The two mismatches that trigger notices — GSTR-1 vs 3B liability (DRC-01B)
            and GSTR-2B vs 3B credit (DRC-01C) — checked before you file. No sign-up required.
          </p>

          <div className="calc-card">
            <h2 className="calc-section-heading">Output liability — GSTR-1 vs GSTR-3B</h2>
            <label className="calc-label">
              Total tax as per GSTR-1 (₹)
              <input
                type="number"
                className="calc-input"
                value={g1Tax}
                onChange={(e) => setG1Tax(e.target.value)}
                placeholder="e.g. 118000"
                min="0"
                step="0.01"
                inputMode="decimal"
                autoFocus
              />
            </label>
            <label className="calc-label">
              Tax declared in GSTR-3B Table 3.1(a) (₹)
              <input
                type="number"
                className="calc-input"
                value={b3Tax}
                onChange={(e) => setB3Tax(e.target.value)}
                placeholder="e.g. 118000"
                min="0"
                step="0.01"
                inputMode="decimal"
              />
            </label>

            <h2 className="calc-section-heading">Input credit — GSTR-2B vs GSTR-3B</h2>
            <label className="calc-label">
              ITC available in GSTR-2B (₹)
              <input
                type="number"
                className="calc-input"
                value={itc2b}
                onChange={(e) => setItc2b(e.target.value)}
                placeholder="e.g. 45000"
                min="0"
                step="0.01"
                inputMode="decimal"
              />
            </label>
            <label className="calc-label">
              ITC claimed in GSTR-3B Table 4A (₹)
              <input
                type="number"
                className="calc-input"
                value={itcClaimed}
                onChange={(e) => setItcClaimed(e.target.value)}
                placeholder="e.g. 45000"
                min="0"
                step="0.01"
                inputMode="decimal"
              />
            </label>

            {result && (
              <div className="calc-result" aria-live="polite">
                {result.liability && (
                  <>
                    <div className={`calc-result-row ${LIABILITY_VERDICTS[result.liability.status].tone}`}>
                      <span>Liability difference (3B − GSTR-1)</span>
                      <strong>{formatINR(result.liability.diff)}</strong>
                    </div>
                    <p className="calc-note">
                      <strong>{LIABILITY_VERDICTS[result.liability.status].title}.</strong>{" "}
                      {LIABILITY_VERDICTS[result.liability.status].text}
                    </p>
                  </>
                )}
                {result.itc && (
                  <>
                    <div className={`calc-result-row ${ITC_VERDICTS[result.itc.status].tone}`}>
                      <span>ITC difference (claimed − GSTR-2B)</span>
                      <strong>{formatINR(result.itc.diff)}</strong>
                    </div>
                    <p className="calc-note">
                      <strong>{ITC_VERDICTS[result.itc.status].title}.</strong>{" "}
                      {ITC_VERDICTS[result.itc.status].text}
                    </p>
                  </>
                )}

                <div className="calc-result-actions">
                  <ShareButtons path="/gstr3b-reconciliation" text={shareText} />
                  <PrintButton label="Print Result" />
                </div>
              </div>
            )}
          </div>

          <EmailCapture
            source="gstr3b-reconciliation"
            heading="Never miss a GST deadline"
            subtext="Get free email reminders before every GST filing deadline."
            buttonLabel="Remind Me"
            compact
          />

          <section className="tool-info">
            <h2>How GSTR-3B Reconciliation Works</h2>
            <p>
              GSTR-3B is a self-declared summary, and the department checks it against
              two sources it already holds: your own <strong>GSTR-1</strong> (what you
              said you sold) and your suppliers&apos; filings aggregated into{" "}
              <strong>GSTR-2B</strong> (what credit you are entitled to). Each
              comparison has its own rule and its own notice:
            </p>
            <ul>
              <li>
                <strong>Rule 88C / DRC-01B</strong> — tax in 3B below GSTR-1. Pay the
                difference with 18% interest or explain within 7 days; until then the
                next GSTR-1 is blocked.
              </li>
              <li>
                <strong>Rule 88D / DRC-01C</strong> — ITC in 3B above GSTR-2B. Reverse
                the excess with interest or explain within 7 days, with the same block.
              </li>
            </ul>
            <p>
              Line-by-line matching of purchase invoices belongs in the{" "}
              <Link to="/gstr2b-reconciliation">GSTR-2B reconciliation tool</Link>; this
              page is the five-second totals check that catches the two notices above.
              Filing late anyway? The <Link to="/late-fee-calculator">late-fee</Link> and{" "}
              <Link to="/interest-calculator">interest</Link> calculators give the damage.
            </p>
            <h3>Common Causes of a Mismatch</h3>
            <ul>
              <li>Credit notes reported in GSTR-1 but not netted in 3B (or vice versa)</li>
              <li>Amendments to earlier periods landing in a different month&apos;s totals</li>
              <li>Advances taxed in 3B before the invoice reaches GSTR-1</li>
              <li>Suppliers filing GSTR-1 late, so their invoices miss your 2B</li>
              <li>Manual entry typos — 3B is typed, GSTR-1 is uploaded</li>
            </ul>
          </section>

          <InlineCTA variant="save" />
          <RelatedTools current="/gstr3b-reconciliation" />
          <CrossProductLinks page="gstr3b-reconciliation" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}
