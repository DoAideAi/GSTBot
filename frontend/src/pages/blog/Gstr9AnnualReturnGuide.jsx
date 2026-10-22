import { useEffect } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";

export default function Gstr9AnnualReturnGuide() {
  usePageTitle("GSTR-9 Annual Return FY 2025-26: Due Date, Applicability, Late Fees");

  useEffect(() => {
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.content = "GSTR-9 and GSTR-9C for FY 2025-26 — who must file, the 31 December 2026 due date, turnover limits, late fee slabs, table-wise filing steps and common mistakes.";

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
        headline: "GSTR-9 Annual Return FY 2025-26: Due Date, Applicability, Late Fees",
        description: "Who must file GSTR-9 and GSTR-9C for FY 2025-26, the 31 December 2026 deadline, late fee slabs by turnover, and a table-wise walkthrough.",
        url: "https://gst.doaide.com/blog/gstr-9-annual-return-fy-2025-26-guide",
        datePublished: "2026-10-22",
        dateModified: "2026-10-22",
        publisher: { "@type": "Organization", name: "DoAide" },
      },
      {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: [
          { "@type": "Question", name: "What is the due date for GSTR-9 for FY 2025-26?", acceptedAnswer: { "@type": "Answer", text: "31 December 2026. The annual return for a financial year is due by 31 December of the following financial year, unless the government extends it." } },
          { "@type": "Question", name: "Who is exempt from filing GSTR-9?", acceptedAnswer: { "@type": "Answer", text: "Filing is optional for taxpayers with turnover up to ₹2 crore. Composition taxpayers (who file GSTR-4 instead), casual and non-resident taxable persons, input service distributors and TDS/TCS deductors are excluded." } },
          { "@type": "Question", name: "Who must file GSTR-9C for FY 2025-26?", acceptedAnswer: { "@type": "Answer", text: "Registered taxpayers with aggregate turnover above ₹5 crore must file GSTR-9C, a self-certified reconciliation statement between the audited financial statements and the annual return." } },
          { "@type": "Question", name: "What is the late fee for GSTR-9?", acceptedAnswer: { "@type": "Answer", text: "For turnover up to ₹5 crore: ₹50 per day (₹25 CGST + ₹25 SGST) capped at 0.04% of turnover. ₹5-20 crore: ₹100 per day capped at 0.04%. Above ₹20 crore: ₹200 per day capped at 0.5% of turnover." } },
          { "@type": "Question", name: "Can GSTR-9 be revised after filing?", acceptedAnswer: { "@type": "Answer", text: "No. GSTR-9 cannot be revised once filed. Errors must be reported and tax paid through DRC-03, which is why reconciliation before filing is critical." } },
        ],
      },
    ]);
    return () => { if (script.parentNode) script.parentNode.removeChild(script); };
  }, []);

  return (
    <article className="blog-article">
      <h1>GSTR-9 Annual Return FY 2025-26: Due Date, Applicability, Late Fees</h1>
      <p className="blog-meta">Updated October 2026 · 9 min read</p>

      <section>
        <p>
          The GST annual return season is here: <strong>GSTR-9 for FY 2025-26 is due by
          31 December 2026</strong>, and for businesses above ₹5 crore turnover the GSTR-9C
          reconciliation statement is due with it. Unlike monthly returns, the annual return
          cannot be revised — a mistake here can only be fixed by paying through DRC-03. This
          guide covers who must file, what each table needs, the late fee slabs, and the
          reconciliations to finish before you press submit.
        </p>
        <p>
          Working through the return? Our free{" "}
          <Link to="/gstr9-checklist">GSTR-9 checklist</Link> and{" "}
          <Link to="/gstr9-helper">GSTR-9 summary helper</Link> cover the preparation
          step by step.
        </p>
      </section>

      <section>
        <h2>Who Must File GSTR-9 for FY 2025-26</h2>
        <ul>
          <li><strong>Mandatory:</strong> every regular registered taxpayer with aggregate turnover above ₹2 crore in FY 2025-26</li>
          <li><strong>Optional:</strong> regular taxpayers with turnover up to ₹2 crore (filing is relaxed by notification, but voluntary filing is allowed and often sensible if you have ITC differences to explain)</li>
          <li><strong>Not required:</strong> composition taxpayers (they file GSTR-4 annually), casual taxable persons, non-resident taxable persons, input service distributors, and persons deducting TDS or collecting TCS under GST</li>
        </ul>
        <p>
          &quot;Aggregate turnover&quot; is PAN-level, all-India: taxable, exempt, export and
          interstate supplies of all GSTINs under the same PAN, counted together. A business with
          ₹1.5 crore in one state and ₹80 lakh in another crosses ₹2 crore and must file GSTR-9
          for <em>each</em> registration.
        </p>
      </section>

      <section>
        <h2>GSTR-9C: The Reconciliation Statement</h2>
        <p>
          If aggregate turnover exceeded <strong>₹5 crore</strong> in FY 2025-26, you must also
          file GSTR-9C — a self-certified reconciliation between the audited financial statements
          and the figures declared in GSTR-9. Since FY 2020-21 no CA/CMA certification is
          required; the taxpayer self-certifies. It is filed on the portal after GSTR-9, before
          the same 31 December deadline.
        </p>
      </section>

      <section>
        <h2>Due Date and Late Fees</h2>
        <p>
          The due date is <strong>31 December 2026</strong> for both GSTR-9 and GSTR-9C for
          FY 2025-26. Late filing of GSTR-9 attracts a fee based on turnover:
        </p>
        <table>
          <thead>
            <tr>
              <th>Aggregate turnover</th>
              <th>Late fee per day</th>
              <th>Maximum cap</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Up to ₹5 crore</td>
              <td>₹50 (₹25 CGST + ₹25 SGST)</td>
              <td>0.04% of turnover in the state/UT</td>
            </tr>
            <tr>
              <td>₹5 crore – ₹20 crore</td>
              <td>₹100 (₹50 + ₹50)</td>
              <td>0.04% of turnover in the state/UT</td>
            </tr>
            <tr>
              <td>Above ₹20 crore</td>
              <td>₹200 (₹100 + ₹100)</td>
              <td>0.5% of turnover in the state/UT</td>
            </tr>
          </tbody>
        </table>
        <p>
          There is no separate late fee for GSTR-9C, but GSTR-9 filed without a required GSTR-9C
          is treated as a defective filing and can draw a notice. Estimate what a delay costs
          with our <Link to="/late-fee-calculator">late fee calculator</Link>, and if any tax
          surfaces during reconciliation, interest applies — compute it with the{" "}
          <Link to="/interest-calculator">GST interest calculator</Link>.
        </p>
      </section>

      <section>
        <h2>What Goes in Each Part of GSTR-9</h2>
        <ul>
          <li><strong>Part I (Tables 1-3):</strong> basic details — auto-filled GSTIN, legal and trade name</li>
          <li><strong>Part II (Tables 4-5):</strong> outward supplies — taxable, exempt, nil-rated, exports and advances, consolidated from GSTR-1 filings of the year</li>
          <li><strong>Part III (Tables 6-8):</strong> ITC — credit availed from GSTR-3B, reversals, and the crucial Table 8 comparison against GSTR-2A/2B</li>
          <li><strong>Part IV (Table 9):</strong> tax paid as per returns filed</li>
          <li><strong>Part V (Tables 10-14):</strong> previous-year transactions reported in April–November of the current year</li>
          <li><strong>Part VI (Tables 15-19):</strong> demands, refunds, HSN summaries of inward and outward supplies, late fee payable</li>
        </ul>
      </section>

      <section>
        <h2>Reconciliations to Finish Before Filing</h2>
        <ol>
          <li><strong>GSTR-1 vs GSTR-3B:</strong> outward supplies declared vs tax actually paid. Mismatches here flow straight into Tables 4 and 9 — see our guide on <Link to="/blog/gstr-1-vs-gstr-3b-mismatch-how-to-fix">fixing GSTR-1 vs GSTR-3B mismatches</Link>.</li>
          <li><strong>Books vs GSTR-3B ITC:</strong> every credit availed during the year, including reversals under Rules 42/43 and Section 16(2) 180-day payment failures.</li>
          <li><strong>GSTR-2B vs ITC claimed:</strong> Table 8 exposes excess claims — run the <Link to="/gstr2b-reconciliation">GSTR-2B reconciliation tool</Link> on the full year.</li>
          <li><strong>HSN summary:</strong> Table 17 requires HSN-wise outward supplies (6-digit codes for turnover above ₹5 crore). Look up codes with the <Link to="/hsn">HSN finder</Link>.</li>
        </ol>
      </section>

      <section>
        <h2>Common Mistakes That Trigger Notices</h2>
        <ul>
          <li>Reporting current-year figures in Part V instead of previous-year spillover transactions</li>
          <li>Ignoring Table 8 differences instead of explaining ITC lapses or reclaiming eligible credit</li>
          <li>Skipping the HSN inward summary (Table 18) — mandatory and frequently left blank</li>
          <li>Paying additional liability through the electronic credit ledger instead of DRC-03 cash payment</li>
          <li>Waiting until the last week of December — the portal slows under load and digital signature issues surface at the worst time</li>
        </ul>
      </section>

      <section>
        <h2>FAQs</h2>
        <h3>What is the due date for GSTR-9 for FY 2025-26?</h3>
        <p>31 December 2026, unless extended by notification. Both GSTR-9 and GSTR-9C share this date.</p>
        <h3>Can GSTR-9 be revised?</h3>
        <p>No. Once filed it is final. Additional liability discovered later must be paid through DRC-03 with interest.</p>
        <h3>Is GSTR-9 required if the registration was cancelled during the year?</h3>
        <p>Yes — if you were registered for any part of FY 2025-26 and cross the threshold, the annual return for that period is still due.</p>
        <h3>Do I need a CA for GSTR-9C?</h3>
        <p>No. GSTR-9C is self-certified since FY 2020-21, though most businesses above ₹5 crore still have a professional prepare the reconciliation.</p>
      </section>

      <section>
        <h2>Related Tools and Guides</h2>
        <ul>
          <li><Link to="/gstr9-checklist">GSTR-9 Checklist</Link> — document-by-document preparation tracker</li>
          <li><Link to="/gstr9-helper">GSTR-9 Helper</Link> — annual return summary calculator</li>
          <li><Link to="/gstr2b-reconciliation">GSTR-2B Reconciliation</Link> — match purchases before Table 8</li>
          <li><Link to="/late-fee-calculator">Late Fee Calculator</Link> — cost of missing 31 December</li>
          <li><Link to="/blog/gst-return-filing-calendar-2026-27">GST Return Calendar 2026-27</Link> — every deadline in one place</li>
        </ul>
      </section>
    </article>
  );
}
