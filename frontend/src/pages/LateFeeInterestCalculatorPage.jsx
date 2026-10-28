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
import {
  calculateLateReturnCost,
  CRORE,
  LATE_FEE_RETURNS,
  LATE_FEE_TABLE,
} from "../lib/gstPenalties";
import { todayInIndia } from "../lib/returnDueDates";

const PATH = "/gst-late-fee-interest-calculator";

const TURNOVER_OPTIONS = [
  { value: 1 * CRORE, label: "Up to ₹1.5 crore" },
  { value: 3 * CRORE, label: "₹1.5 – ₹5 crore" },
  { value: 10 * CRORE, label: "₹5 – ₹20 crore" },
  { value: 25 * CRORE, label: "Above ₹20 crore" },
];

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST Late Fee and Interest Calculator",
  url: `https://gst.doaide.com${PATH}`,
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const FAQ_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    { "@type": "Question", name: "What is the maximum late fee for GSTR-3B?", acceptedAnswer: { "@type": "Answer", text: "₹50 per day (₹25 CGST + ₹25 SGST), capped by aggregate turnover: ₹2,000 up to ₹1.5 crore, ₹5,000 for ₹1.5–5 crore and ₹10,000 above ₹5 crore. Nil returns pay ₹20 per day, capped at ₹500." } },
    { "@type": "Question", name: "What is the late fee for GSTR-9 after FY 2022-23?", acceptedAnswer: { "@type": "Answer", text: "₹50/day capped at 0.04% of state turnover for turnover up to ₹5 crore, ₹100/day capped at 0.04% for ₹5–20 crore, and ₹200/day capped at 0.5% above ₹20 crore (Notification 7/2023-Central Tax)." } },
    { "@type": "Question", name: "Is GST interest charged on the full tax or only the cash portion?", acceptedAnswer: { "@type": "Answer", text: "Only on the tax paid through the electronic cash ledger. The proviso to Section 50(1) exempts the part set off against input tax credit, as long as the return is filed before proceedings under Section 73 or 74 begin." } },
    { "@type": "Question", name: "Is interest on wrongly claimed ITC still 24%?", acceptedAnswer: { "@type": "Answer", text: "No. Since 5 July 2022 interest under Section 50(3) is 18% per annum, and it applies only when the wrong credit was both availed and utilised — credit that sat unused in the ledger attracts no interest." } },
    { "@type": "Question", name: "Can late fee and interest be paid from ITC?", acceptedAnswer: { "@type": "Answer", text: "No. Late fee and interest must be paid in cash through the electronic cash ledger. Input tax credit can only be used against tax." } },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "GST Late Fee & Interest Calculator" },
];

function today() {
  return todayInIndia();
}

export default function LateFeeInterestCalculatorPage() {
  usePageTitle("GST Late Fee & Interest Calculator 2026 — GSTR-3B, GSTR-1, GSTR-9");

  const [returnType, setReturnType] = useState("gstr3b");
  const [aato, setAato] = useState(TURNOVER_OPTIONS[0].value);
  const [stateTurnover, setStateTurnover] = useState("");
  const [nil, setNil] = useState(false);
  const [dueDate, setDueDate] = useState("");
  const [filingDate, setFilingDate] = useState(today);
  const [cashTax, setCashTax] = useState("");
  const [wrongItc, setWrongItc] = useState("");
  const [itcSince, setItcSince] = useState("");

  const result = useMemo(() => {
    if (!dueDate || !filingDate) return null;
    return calculateLateReturnCost({
      returnType,
      dueDate,
      filingDate,
      nil,
      aato,
      stateTurnover: parseFloat(stateTurnover) || 0,
      cashTax: parseFloat(cashTax) || 0,
      wrongItcUtilised: parseFloat(wrongItc) || 0,
      itcUtilisedSince: itcSince || undefined,
    });
  }, [returnType, aato, stateTurnover, nil, dueDate, filingDate, cashTax, wrongItc, itcSince]);

  const label = LATE_FEE_RETURNS.find((r) => r.key === returnType)?.label;
  const showNil = returnType !== "gstr9";

  return (
    <div className="tool-page">
      <SeoHead
        title="GST Late Fee & Interest Calculator 2026 — GSTR-3B, GSTR-1, GSTR-9"
        description="Work out the late fee and 18% interest on a delayed GST return in one go. Uses the turnover-based caps (₹2,000 / ₹5,000 / ₹10,000), the post-2023 GSTR-9 slabs, and interest on the cash portion only."
        path={PATH}
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb items={[{ label: "Home", to: "/" }, { label: "Free Tools", to: "/resources" }, { label: "Late Fee & Interest" }]} />
          <h1 className="tool-title">GST Late Fee &amp; Interest Calculator</h1>
          <p className="tool-subtitle">
            Missed a due date? See exactly what you owe — late fee under Section 47 plus interest
            under Section 50 — using the caps CBIC actually notified, not the Act&apos;s ₹200/day headline.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Return
              <select className="calc-select" value={returnType} onChange={(e) => setReturnType(e.target.value)}>
                {LATE_FEE_RETURNS.map((r) => (
                  <option key={r.key} value={r.key}>{r.label}</option>
                ))}
              </select>
            </label>

            <label className="calc-label">
              Aggregate turnover (previous FY)
              <select className="calc-select" value={aato} onChange={(e) => setAato(Number(e.target.value))}>
                {TURNOVER_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </label>

            {returnType === "gstr9" && (
              <label className="calc-label">
                Turnover in this state / UT for the year (₹)
                <input
                  type="number"
                  className="calc-input"
                  value={stateTurnover}
                  onChange={(e) => setStateTurnover(e.target.value)}
                  placeholder="e.g. 25000000"
                  min="0"
                  inputMode="decimal"
                />
              </label>
            )}

            {showNil && (
              <label className="calc-checkbox-label">
                <input type="checkbox" checked={nil} onChange={(e) => setNil(e.target.checked)} />
                Nil return (no outward supply, no tax payable)
              </label>
            )}

            <label className="calc-label">
              Due date
              <input type="date" className="calc-input" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
            </label>

            <label className="calc-label">
              Filing &amp; payment date
              <input type="date" className="calc-input" value={filingDate} onChange={(e) => setFilingDate(e.target.value)} />
            </label>

            {!nil && (
              <>
                <label className="calc-label">
                  Tax paid in cash (₹)
                  <input
                    type="number"
                    className="calc-input"
                    value={cashTax}
                    onChange={(e) => setCashTax(e.target.value)}
                    placeholder="Net cash liability, e.g. 100000"
                    min="0"
                    inputMode="decimal"
                  />
                </label>
                <label className="calc-label">
                  ITC wrongly availed and utilised (₹, optional)
                  <input
                    type="number"
                    className="calc-input"
                    value={wrongItc}
                    onChange={(e) => setWrongItc(e.target.value)}
                    placeholder="e.g. 0"
                    min="0"
                    inputMode="decimal"
                  />
                </label>
                {parseFloat(wrongItc) > 0 && (
                  <label className="calc-label">
                    Date that credit was utilised
                    <input type="date" className="calc-input" value={itcSince} onChange={(e) => setItcSince(e.target.value)} />
                  </label>
                )}
              </>
            )}

            {result && (
              <div className="calc-result" aria-live="polite">
                {result.filedDays === 0 && result.total === 0 ? (
                  <p className="calc-note">Filed on or before the due date — no late fee or interest.</p>
                ) : (
                  <>
                    <div className="calc-result-row">
                      <span>Days late</span>
                      <strong>{result.filedDays} days</strong>
                    </div>
                    <div className="calc-result-row">
                      <span>Late fee ({formatINR(result.lateFee.perDay)}/day{result.lateFee.capped ? ", capped" : ""})</span>
                      <strong>{formatINR(result.lateFee.fee)}</strong>
                    </div>
                    <div className="calc-result-row">
                      <span>&nbsp;&nbsp;CGST / SGST share</span>
                      <strong>{formatINR(result.lateFee.cgst)} / {formatINR(result.lateFee.sgst)}</strong>
                    </div>
                    <div className="calc-result-row">
                      <span>Interest on cash tax (18% p.a.)</span>
                      <strong>{formatINR(result.interestOnTax)}</strong>
                    </div>
                    {result.interestOnItc > 0 && (
                      <div className="calc-result-row">
                        <span>Interest on wrong ITC (18%, {result.itcDays} days)</span>
                        <strong>{formatINR(result.interestOnItc)}</strong>
                      </div>
                    )}
                    <div className="calc-result-row calc-total">
                      <span>Total payable in cash</span>
                      <strong>{formatINR(result.total)}</strong>
                    </div>
                    <p className="calc-note">{result.lateFee.basis}. Late fee and interest cannot be paid from ITC.</p>
                    <div className="calc-result-actions">
                      <ShareButtons
                        path={PATH}
                        text={`${label} filed ${result.filedDays} days late: late fee ${formatINR(result.lateFee.fee)} + interest ${formatINR(result.interestOnTax + result.interestOnItc)} — checked free on DoAide GST`}
                      />
                      <PrintButton label="Print Result" />
                    </div>
                  </>
                )}
              </div>
            )}
          </div>

          <section className="tool-info">
            <h2>GST Late Fee Caps in Force (2026)</h2>
            <table className="calendar-table">
              <thead>
                <tr>
                  <th>Return &amp; turnover</th>
                  <th>Per day (CGST + SGST)</th>
                  <th>Maximum</th>
                </tr>
              </thead>
              <tbody>
                {LATE_FEE_TABLE.map((row) => (
                  <tr key={row.ret}>
                    <td>{row.ret}</td>
                    <td>{formatINR(row.perDay)}</td>
                    <td>{row.cap}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <EmailCapture
            source="late-fee-interest-calculator"
            heading="Stop paying late fees"
            subtext="Free email reminders before every GSTR-1, GSTR-3B and GSTR-9 due date."
            buttonLabel="Remind Me"
            compact
          />

          <section className="tool-info">
            <h2>How the Two Charges Work</h2>
            <h3>Late fee — Section 47</h3>
            <p>
              Charged for every day the return is filed after its due date, whether or not any tax is
              due. The Act allows ₹200 a day, but CBIC has capped it far lower: GSTR-1 and GSTR-3B pay
              ₹50 a day with a ceiling of ₹2,000, ₹5,000 or ₹10,000 depending on last year&apos;s
              turnover. GSTR-9 has its own turnover-linked slabs from FY 2022-23.
            </p>
            <h3>Interest — Section 50</h3>
            <ul>
              <li><strong>Late payment (50(1))</strong> — 18% a year, day by day, on the tax paid through the cash ledger. The part set off against ITC is not charged.</li>
              <li><strong>Wrong ITC (50(3))</strong> — 18% a year, but only on credit that was both claimed and actually used to pay tax.</li>
              <li>Interest runs from the day after the due date to the day of payment: <em>tax × 18% × days ÷ 365</em>.</li>
            </ul>
            <p>
              Need the monthly deadlines? See the <Link to="/due-dates">GST due dates calendar</Link>.
              Reconciling a whole year first? Try the <Link to="/gstr9-summary">GSTR-9 summary tool</Link>.
            </p>
          </section>

          <InlineCTA variant="remind" />
          <RelatedTools current={PATH} />
          <CrossProductLinks page="late-fee-interest-calculator" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}
