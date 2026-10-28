import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";
import { calculateInterest, calculateLateFee } from "../../lib/gstPenalties";

const RETURN_TYPES = [
  { value: "gstr1", label: "GSTR-1" },
  { value: "gstr3b", label: "GSTR-3B" },
  { value: "gstr9", label: "GSTR-9 (Annual)" },
  { value: "gstr4", label: "GSTR-4 (Composition)" },
];

// The same rules as the full calculators, not a copy of them: a table kept
// here drifted to ₹10/day nil fees and a flat ₹5,000 cap, and took the GSTR-9
// cap from the tax amount rather than the turnover it is a share of.
function calcPenalty(returnType, daysLate, isNil, taxAmount, turnover = 0) {
  if (daysLate <= 0) return { lateFee: 0, interest: 0, total: 0 };
  const { fee } = calculateLateFee(returnType, daysLate, { nil: isNil, aato: turnover });
  // A nil return has no tax to be late with.
  const interest = isNil ? 0 : calculateInterest(taxAmount, daysLate);
  return { lateFee: fee, interest, total: fee + interest };
}

function MiniCalculator() {
  const [returnType, setReturnType] = useState("gstr3b");
  const [daysLate, setDaysLate] = useState("");
  const [isNil, setIsNil] = useState(false);
  const [taxAmount, setTaxAmount] = useState("");
  const [turnover, setTurnover] = useState("");

  const result = calcPenalty(
    returnType, parseInt(daysLate) || 0, isNil, parseFloat(taxAmount) || 0, parseFloat(turnover) || 0,
  );

  return (
    <div className="calc-card" style={{ marginTop: "1rem" }}>
      <h3 style={{ fontSize: "1.1rem", fontWeight: 600, marginBottom: "1rem" }}>Quick Penalty Estimate</h3>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
        <label className="calc-label">
          Return Type
          <select className="calc-select" value={returnType} onChange={(e) => setReturnType(e.target.value)}>
            {RETURN_TYPES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </label>
        <label className="calc-label">
          Days Late
          <input type="number" className="calc-input" value={daysLate} onChange={(e) => setDaysLate(e.target.value)} placeholder="e.g. 30" min="0" inputMode="numeric" />
        </label>
        <label className="calc-label">
          Unpaid Tax Amount (₹)
          <input type="number" className="calc-input" value={taxAmount} onChange={(e) => setTaxAmount(e.target.value)} placeholder="For interest calculation" min="0" inputMode="decimal" />
        </label>
        <label className="calc-label">
          Previous Year Turnover (₹)
          <input type="number" className="calc-input" value={turnover} onChange={(e) => setTurnover(e.target.value)} placeholder="Sets the late fee cap" min="0" inputMode="decimal" />
        </label>
        <label className="calc-label" style={{ display: "flex", alignItems: "center", gap: "0.5rem", paddingTop: "1.5rem" }}>
          <input type="checkbox" checked={isNil} onChange={(e) => setIsNil(e.target.checked)} style={{ width: "18px", height: "18px" }} />
          Nil return (no tax liability)
        </label>
      </div>
      {(parseInt(daysLate) || 0) > 0 && (
        <div className="calc-result" aria-live="polite" style={{ marginTop: "1rem" }}>
          <div className="calc-result-row">
            <span>Late Fee</span>
            <strong>₹{result.lateFee.toLocaleString("en-IN")}</strong>
          </div>
          <div className="calc-result-row">
            <span>Interest (18% p.a.)</span>
            <strong>₹{result.interest.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
          </div>
          <div className="calc-result-row calc-total">
            <span>Total Penalty</span>
            <strong>₹{result.total.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
          </div>
        </div>
      )}
      <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginTop: "0.75rem" }}>
        For detailed calculations with all return types, use our full{" "}
        <Link to="/penalty-calculator">Penalty Calculator</Link> or{" "}
        <Link to="/late-fee-calculator">Late Fee Calculator</Link>.
      </p>
    </div>
  );
}

export default function GstLatePenaltyCalculator() {
  usePageTitle("GST Late Filing Penalty Calculator 2026 — Calculate Fees & Interest");

  useEffect(() => {
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.content = "Calculate GST late filing penalties and interest for GSTR-1, GSTR-3B, GSTR-9 and GSTR-4. Free online penalty calculator with current 2026 rates, caps, and worked examples.";

    let script = document.getElementById("blog-ld-json");
    if (!script) {
      script = document.createElement("script");
      script.id = "blog-ld-json";
      script.type = "application/ld+json";
      document.head.appendChild(script);
    }
    script.textContent = JSON.stringify([
      {
        "@context": "https://schema.org",
        "@type": "Article",
        headline: "GST Late Filing Penalty Calculator 2026",
        description: "Calculate GST late filing penalties and interest for all return types with current rates.",
        url: "https://gst.doaide.com/blog/gst-late-filing-penalty-calculator",
        datePublished: "2026-10-08",
        dateModified: "2026-10-08",
        publisher: { "@type": "Organization", name: "DoAide" },
      },
      {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: [
          { "@type": "Question", name: "What is the penalty for late filing of GST returns?", acceptedAnswer: { "@type": "Answer", text: "GSTR-1 and GSTR-3B late fee is ₹50/day (₹25 CGST + ₹25 SGST) for regular returns, capped at ₹5,000. Nil returns attract ₹20/day, capped at ₹1,000. Interest at 18% p.a. applies on unpaid tax." } },
          { "@type": "Question", name: "How is interest calculated on late GST payment?", acceptedAnswer: { "@type": "Answer", text: "Interest under Section 50 is charged at 18% per annum on the net tax liability (after adjusting ITC). It is calculated from the day after the due date until the date of actual payment." } },
          { "@type": "Question", name: "What is the maximum late fee for GSTR-3B?", acceptedAnswer: { "@type": "Answer", text: "The maximum late fee for GSTR-3B is ₹5,000 (₹2,500 CGST + ₹2,500 SGST) for regular returns and ₹1,000 (₹500 CGST + ₹500 SGST) for nil returns." } },
          { "@type": "Question", name: "Is there a penalty for late filing of GSTR-9 annual return?", acceptedAnswer: { "@type": "Answer", text: "Yes. GSTR-9 late fee is ₹200 per day (₹100 CGST + ₹100 SGST), subject to a maximum of 0.25% of the taxpayer's turnover in the state or Union Territory." } },
          { "@type": "Question", name: "Can GST late fees be waived?", acceptedAnswer: { "@type": "Answer", text: "The government periodically issues late fee amnesty schemes for delayed filings. These waivers are notified through GST Council recommendations and CBIC notifications. Check the GST portal for any current amnesty scheme." } },
        ],
      },
    ]);
    return () => { script?.remove(); };
  }, []);

  const tdStyle = { padding: "0.75rem 0.5rem", borderBottom: "1px solid var(--line, #e2e8f0)" };
  const thStyle = { textAlign: "left", padding: "0.75rem 0.5rem", borderBottom: "2px solid var(--line, #e2e8f0)" };

  return (
    <article className="blog-article">
      <h1>GST Late Filing Penalty Calculator 2026</h1>
      <p className="blog-meta">Updated October 2026 · 7 min read</p>

      <section>
        <h2>How GST Late Filing Penalties Work</h2>
        <p>
          Missing a GST filing deadline triggers two separate charges: a <strong>late fee</strong> under
          Section 47 of the CGST Act (a fixed amount per day of delay) and <strong>interest</strong> under
          Section 50 (18% per annum on the outstanding tax).
        </p>
        <p>
          The late fee starts the day after the due date and runs until the return is actually filed.
          Interest accrues on the net tax liability — the amount that was due but not paid by the deadline.
        </p>
      </section>

      <MiniCalculator />

      <section>
        <h2>Late Fee Rates by Return Type (2026)</h2>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.95rem" }}>
            <thead>
              <tr>
                <th style={thStyle}>Return</th>
                <th style={thStyle}>Regular (per day)</th>
                <th style={thStyle}>Nil (per day)</th>
                <th style={thStyle}>Maximum Cap</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style={tdStyle}>GSTR-1</td>
                <td style={tdStyle}>₹50 (₹25 CGST + ₹25 SGST)</td>
                <td style={tdStyle}>₹20 (₹10 + ₹10)</td>
                <td style={tdStyle}>₹5,000 / ₹1,000 (nil)</td>
              </tr>
              <tr>
                <td style={tdStyle}>GSTR-3B</td>
                <td style={tdStyle}>₹50 (₹25 CGST + ₹25 SGST)</td>
                <td style={tdStyle}>₹20 (₹10 + ₹10)</td>
                <td style={tdStyle}>₹5,000 / ₹1,000 (nil)</td>
              </tr>
              <tr>
                <td style={tdStyle}>GSTR-9</td>
                <td style={tdStyle}>₹200 (₹100 + ₹100)</td>
                <td style={tdStyle}>₹20 (₹10 + ₹10)</td>
                <td style={tdStyle}>0.25% of turnover</td>
              </tr>
              <tr>
                <td style={tdStyle}>GSTR-4</td>
                <td style={tdStyle}>₹50 (₹25 + ₹25)</td>
                <td style={tdStyle}>₹20 (₹10 + ₹10)</td>
                <td style={tdStyle}>₹2,000 / ₹500 (nil)</td>
              </tr>
              <tr>
                <td style={tdStyle}>GSTR-5 / GSTR-5A</td>
                <td style={tdStyle}>₹50 (₹25 + ₹25)</td>
                <td style={tdStyle}>₹20 (₹10 + ₹10)</td>
                <td style={tdStyle}>₹5,000 / ₹1,000 (nil)</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2>Interest on Late GST Payment</h2>
        <p>
          Interest is separate from the late fee and is charged at:
        </p>
        <ul>
          <li><strong>18% per annum</strong> — on the net tax liability (tax due minus ITC already available)</li>
          <li><strong>24% per annum</strong> — on tax collected but not deposited with the government (rare, applies to fraud/deliberate cases)</li>
        </ul>
        <p>
          The interest is calculated from the day after the due date to the date of actual payment.
          The formula is:
        </p>
        <div style={{ background: "var(--bg-card)", padding: "1rem 1.25rem", borderRadius: "8px", margin: "1rem 0", fontFamily: "monospace", fontSize: "0.95rem" }}>
          Interest = Tax Due × 18% × (Days Late ÷ 365)
        </div>
      </section>

      <section>
        <h2>Worked Example: GSTR-3B Filed 45 Days Late</h2>
        <p>
          A business has a net tax liability of ₹1,00,000 for the month and files GSTR-3B 45 days
          after the due date.
        </p>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.95rem" }}>
            <thead>
              <tr>
                <th style={thStyle}>Component</th>
                <th style={thStyle}>Calculation</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Amount</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style={tdStyle}>Late Fee</td>
                <td style={tdStyle}>₹50 × 45 days = ₹2,250</td>
                <td style={{ ...tdStyle, textAlign: "right" }}>₹2,250</td>
              </tr>
              <tr>
                <td style={tdStyle}>Interest</td>
                <td style={tdStyle}>₹1,00,000 × 18% × 45/365</td>
                <td style={{ ...tdStyle, textAlign: "right" }}>₹2,219</td>
              </tr>
              <tr style={{ fontWeight: 600 }}>
                <td style={tdStyle}>Total Penalty</td>
                <td style={tdStyle}>Late fee + Interest</td>
                <td style={{ ...tdStyle, textAlign: "right" }}>₹4,469</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p style={{ marginTop: "1rem" }}>
          For nil returns (zero tax liability), the late fee would be ₹20 × 45 = ₹900 with no interest
          (since there is no tax due).
        </p>
      </section>

      <section>
        <h2>How to Avoid GST Late Filing Penalties</h2>
        <ol>
          <li>
            <strong>Set up deadline alerts</strong> — Use our{" "}
            <Link to="/return-calendar">Return Due Date Calendar</Link> to see all upcoming deadlines
            at a glance.
          </li>
          <li>
            <strong>File nil returns on time</strong> — Even if you have no transactions, you must
            file nil returns. The penalty for missing a nil return is ₹20/day, up to ₹1,000.
          </li>
          <li>
            <strong>Pay tax before filing</strong> — Interest runs on the tax amount, not the return.
            If you cannot file the return on time, at least pay the estimated tax using a challan. Use
            our <Link to="/payment-challan">Payment Challan Generator</Link>.
          </li>
          <li>
            <strong>Use QRMP scheme</strong> — Businesses with turnover under ₹5 crore can file
            GSTR-1 and GSTR-3B quarterly (instead of monthly) under the QRMP scheme. This reduces
            the number of deadlines to track.
          </li>
          <li>
            <strong>Check for amnesty schemes</strong> — The GST Council periodically waives late
            fees for past periods. Filing during an amnesty window can save significant amounts.
          </li>
        </ol>
      </section>

      <section>
        <h2>Frequently Asked Questions</h2>

        <h3>What is the penalty for late filing of GST returns?</h3>
        <p>
          GSTR-1 and GSTR-3B attract ₹50 per day (₹25 CGST + ₹25 SGST) for regular returns,
          capped at ₹5,000. Nil returns attract ₹20 per day (₹10 CGST + ₹10 SGST), capped at ₹1,000.
          Interest at 18% per annum applies on the unpaid tax.
        </p>

        <h3>How is interest calculated on late GST payment?</h3>
        <p>
          Interest is calculated at 18% per annum on the net tax liability (after adjusting ITC).
          It runs from the day after the due date until the date of actual payment:
          Tax Due × 18% × (Days ÷ 365).
        </p>

        <h3>What is the maximum late fee for GSTR-3B?</h3>
        <p>
          The maximum late fee for GSTR-3B is ₹5,000 (₹2,500 CGST + ₹2,500 SGST) for regular
          returns. For nil returns, the cap is ₹1,000 (₹500 CGST + ₹500 SGST).
        </p>

        <h3>Can GST late fees be waived?</h3>
        <p>
          Yes. The government periodically announces amnesty schemes that waive or reduce late fees
          for past periods. These are notified through CBIC notifications. Check the GST portal for
          any active scheme.
        </p>

        <h3>Is there interest on nil returns?</h3>
        <p>
          No. Interest is charged on the tax amount due. If you filed a nil return (no tax liability),
          only the late fee applies, not interest.
        </p>
      </section>

      <section className="blog-cta">
        <h2>Calculate Your Exact Penalty</h2>
        <p>
          Use our free tools for detailed penalty and interest calculations for every GST return type.
        </p>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
          <Link to="/penalty-calculator" className="btn btn-primary">Full Penalty Calculator</Link>
          <Link to="/late-fee-calculator" className="btn" style={{ border: "1px solid var(--border)", color: "var(--ink)" }}>Late Fee Calculator</Link>
          <Link to="/" className="btn" style={{ border: "1px solid var(--border)", color: "var(--ink)" }}>Try DoAide GST free →</Link>
        </div>
      </section>
    </article>
  );
}
