import { useMemo, useState } from "react";
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
import TableScroll from "../components/TableScroll";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { formatINR } from "../lib/gstCalc";
import { CATEGORIES, compositionYear, emptyQuarters, LOWER_LIMIT_STATES } from "../lib/compositionTax";

const PATH = "/composition-tax-calculator";
const FY_OPTIONS = ["2025-26", "2026-27", "2024-25"];
const RCM_RATES = ["5", "18", "40"];

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST Composition Tax Calculator (CMP-08)",
  url: `https://gst.doaide.com${PATH}`,
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const FAQ_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    { "@type": "Question", name: "How is composition tax calculated?", acceptedAnswer: { "@type": "Answer", text: "Manufacturers pay 1% and restaurants 5% of total turnover in the state. Traders pay 1% of taxable supplies, and service providers under Section 10(2A) pay 6%. The tax is split equally into CGST and SGST." } },
    { "@type": "Question", name: "Do composition dealers pay reverse charge?", acceptedAnswer: { "@type": "Answer", text: "Yes. Reverse-charge purchases, such as goods transport or legal services, are taxed at the normal GST rate in CMP-08 on top of the composition tax, and no ITC can be claimed on them." } },
    { "@type": "Question", name: "When is CMP-08 due?", acceptedAnswer: { "@type": "Answer", text: "By the 18th of the month after each quarter: 18 July, 18 October, 18 January and 18 April. Late payment carries 18% interest. The annual GSTR-4 return is due by 30 April after the financial year." } },
    { "@type": "Question", name: "What happens if I cross the composition turnover limit mid-year?", acceptedAnswer: { "@type": "Answer", text: "You leave the scheme from the day turnover crosses ₹1.5 crore (₹75 lakh in some special category states, ₹50 lakh for service providers). File CMP-04 within 7 days and charge regular GST from that day." } },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "Composition Tax Calculator" },
];

export default function CompositionTaxCalculatorPage() {
  usePageTitle("GST Composition Tax Calculator — CMP-08 Quarterly Tax & GSTR-4");

  const [category, setCategory] = useState("manufacturer");
  const [fy, setFy] = useState(FY_OPTIONS[0]);
  const [lowerLimitState, setLowerLimitState] = useState(false);
  const [quarters, setQuarters] = useState(emptyQuarters);

  const year = useMemo(
    () => compositionYear({ category, quarters, fy, lowerLimitState }),
    [category, quarters, fy, lowerLimitState],
  );

  const setField = (i, key, value) => setQuarters((prev) => prev.map((q, j) => (j === i ? { ...q, [key]: value } : q)));
  const cat = CATEGORIES.find((c) => c.key === category);

  return (
    <div className="tool-page">
      <SeoHead
        title="GST Composition Tax Calculator — CMP-08 Quarterly Tax & GSTR-4"
        description="Calculate composition scheme tax for each quarter: 1% manufacturers and traders, 5% restaurants, 6% service providers, plus reverse charge, CMP-08 due dates, late-payment interest and the turnover limit. Free."
        path={PATH}
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb items={[{ label: "Home", to: "/" }, { label: "Free Tools", to: "/resources" }, { label: "Composition Tax Calculator" }]} />
          <h1 className="tool-title">Composition Tax Calculator</h1>
          <p className="tool-subtitle">
            Work out what each CMP-08 should pay — on the right turnover base for your category, with
            reverse charge added and interest if you are late — and watch the year&apos;s running total
            against your composition limit.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Business category
              <select className="calc-select" value={category} onChange={(e) => setCategory(e.target.value)}>
                {CATEGORIES.map((c) => (
                  <option key={c.key} value={c.key}>{c.label} — {c.rate}%</option>
                ))}
              </select>
            </label>
            <label className="calc-label">
              Financial year
              <select className="calc-select" value={fy} onChange={(e) => setFy(e.target.value)}>
                {FY_OPTIONS.map((y) => (
                  <option key={y} value={y}>FY {y}</option>
                ))}
              </select>
            </label>
            {category !== "service" && (
              <label className="calc-checkbox-label">
                <input type="checkbox" checked={lowerLimitState} onChange={(e) => setLowerLimitState(e.target.checked)} />
                Registered in a ₹75 lakh limit state ({LOWER_LIMIT_STATES.join(", ")})
              </label>
            )}
            <p className="calc-note">
              {cat.base === "total"
                ? `${cat.label}s pay ${cat.rate}% on total turnover in the state — exempt supplies are included.`
                : `${cat.label.split(" —")[0]}s pay ${cat.rate}% on taxable supplies only — exempt supplies are excluded.`}
            </p>

            <TableScroll label="Quarterly composition figures">
              <table className="calendar-table">
                <thead>
                  <tr>
                    <th>Quarter</th>
                    <th>Taxable turnover</th>
                    <th>Exempt / nil turnover</th>
                    <th>RCM inward value</th>
                    <th>RCM rate</th>
                    <th>CMP-08 paid on</th>
                  </tr>
                </thead>
                <tbody>
                  {quarters.map((q, i) => (
                    <tr key={q.quarter}>
                      <td>{q.quarter}</td>
                      {["taxable", "exempt", "rcmValue"].map((k) => (
                        <td key={k}>
                          <input
                            type="number"
                            className="calc-input"
                            aria-label={`${q.quarter} ${{ taxable: "taxable turnover", exempt: "exempt turnover", rcmValue: "RCM inward value" }[k]}`}
                            value={q[k]}
                            onChange={(e) => setField(i, k, e.target.value)}
                            min="0"
                            inputMode="decimal"
                          />
                        </td>
                      ))}
                      <td>
                        <select className="calc-select" aria-label={`${q.quarter} RCM rate`} value={q.rcmRate} onChange={(e) => setField(i, "rcmRate", e.target.value)}>
                          {RCM_RATES.map((r) => (
                            <option key={r} value={r}>{r}%</option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <input type="date" className="calc-input" aria-label={`${q.quarter} paid on`} value={q.paidOn} onChange={(e) => setField(i, "paidOn", e.target.value)} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
          </div>

          {year && (
            <div className="calc-card" aria-live="polite" style={{ marginTop: "1rem" }}>
              <h2 style={{ margin: "0 0 1rem" }}>CMP-08 — FY {fy}</h2>
              <TableScroll label="Quarterly CMP-08 liability">
                <table className="calendar-table">
                  <thead>
                    <tr>
                      <th>Quarter</th>
                      <th>Due</th>
                      <th>Composition tax (CGST + SGST)</th>
                      <th>RCM tax</th>
                      <th>Interest</th>
                      <th>Payable</th>
                    </tr>
                  </thead>
                  <tbody>
                    {year.quarters.map((q) => (
                      <tr key={q.quarter}>
                        <td>{q.quarter}</td>
                        <td>{q.dueDate}</td>
                        <td>{formatINR(q.compTax)} ({formatINR(q.cgst)} + {formatINR(q.sgst)})</td>
                        <td>{formatINR(q.rcmTax)}</td>
                        <td>{q.interest ? `${formatINR(q.interest)} (${q.daysLate} days)` : "—"}</td>
                        <td><strong>{formatINR(q.payable)}</strong></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableScroll>

              <div className="calc-result">
                <div className="calc-result-row"><span>Annual turnover</span><strong>{formatINR(year.annualTurnover)}</strong></div>
                <div className="calc-result-row"><span>Composition tax for the year</span><strong>{formatINR(year.totalCompTax)}</strong></div>
                <div className="calc-result-row"><span>Reverse-charge tax</span><strong>{formatINR(year.totalRcmTax)}</strong></div>
                {year.totalInterest > 0 && (
                  <div className="calc-result-row"><span>Interest on late CMP-08</span><strong>{formatINR(year.totalInterest)}</strong></div>
                )}
                <div className="calc-result-row calc-total"><span>Total for GSTR-4</span><strong>{formatINR(year.totalPayable)}</strong></div>
              </div>

              <p className="calc-note">Composition limit used: {year.limitUsedPct}% of {formatINR(year.limit)}</p>
              <Meter value={year.annualTurnover} max={year.limit} label="Composition turnover limit used" />
              {year.breached ? (
                <p className="calc-note" role="alert">
                  Turnover crossed the {formatINR(year.limit)} limit in {year.quarters[year.breachQuarter].quarter}. You are out of the
                  scheme from the day it was crossed: file CMP-04 within 7 days and charge regular GST from then on.
                </p>
              ) : (
                <p className="calc-note">GSTR-4 for FY {fy} is due by {year.gstr4DueDate}.</p>
              )}

              <div className="calc-result-actions">
                <ShareButtons
                  path={PATH}
                  text={`Composition tax for FY ${fy}: ${formatINR(year.totalPayable)} across four CMP-08s — calculated free on DoAide GST`}
                />
                <PrintButton label="Print Result" />
              </div>
            </div>
          )}

          <EmailCapture
            source="composition-tax-calculator"
            heading="CMP-08 reminders"
            subtext="An email before every 18th — July, October, January and April."
            buttonLabel="Remind Me"
            compact
          />

          <section className="tool-info">
            <h2>Composition Rates and Bases</h2>
            <table className="calendar-table">
              <thead>
                <tr><th>Category</th><th>Rate</th><th>Charged on</th><th>Turnover limit</th></tr>
              </thead>
              <tbody>
                <tr><td>Manufacturer</td><td>1% (0.5% + 0.5%)</td><td>Total turnover in the state</td><td>₹1.5 Cr (₹75 L*)</td></tr>
                <tr><td>Trader</td><td>1% (0.5% + 0.5%)</td><td>Taxable supplies only</td><td>₹1.5 Cr (₹75 L*)</td></tr>
                <tr><td>Restaurant</td><td>5% (2.5% + 2.5%)</td><td>Total turnover in the state</td><td>₹1.5 Cr (₹75 L*)</td></tr>
                <tr><td>Service provider, s.10(2A)</td><td>6% (3% + 3%)</td><td>Taxable supplies only</td><td>₹50 L</td></tr>
              </tbody>
            </table>
            <p className="calc-note">* Special category states listed above.</p>
            <p>
              Not sure the scheme suits you? Run the <Link to="/tools/composition-scheme-checker">eligibility checker</Link>{" "}
              or compare it with regular GST in the <Link to="/scheme-comparison">scheme comparison</Link>.
              Paid a CMP-08 late? The <Link to="/interest-calculator">interest calculator</Link> shows the day count.
            </p>
          </section>

          <InlineCTA variant="remind" />
          <RelatedTools current={PATH} />
          <CrossProductLinks page="composition-tax-calculator" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}
