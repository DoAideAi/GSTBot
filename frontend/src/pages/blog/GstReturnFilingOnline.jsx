import { useEffect } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";

export default function GstReturnFilingOnline() {
  usePageTitle("How to File GST Returns Online — Complete Step-by-Step Guide 2026");

  useEffect(() => {
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.content = "Step-by-step guide to file GST returns online in 2026. Learn GSTR-1, GSTR-3B, and GSTR-9 filing process, due dates, late fees, and common mistakes to avoid.";

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
        headline: "How to File GST Returns Online — Complete Step-by-Step Guide 2026",
        description: "Complete guide to filing GST returns online. Step-by-step process for GSTR-1, GSTR-3B, and GSTR-9 with due dates, late fees, and common filing mistakes.",
        url: "https://gst.doaide.com/blog/how-to-file-gst-returns-online",
        datePublished: "2026-10-08",
        dateModified: "2026-10-08",
        publisher: { "@type": "Organization", name: "DoAide" },
      },
      {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: [
          { "@type": "Question", name: "Can I file GST returns myself without a CA?", acceptedAnswer: { "@type": "Answer", text: "Yes — any registered taxpayer can file through the GST portal, entirely online. Free tools like DoAide GST help with calculations and reconciliation; for complex businesses or audits, professional help is worth it." } },
          { "@type": "Question", name: "What is the penalty for late GST return filing?", acceptedAnswer: { "@type": "Answer", text: "Late GSTR-3B filing attracts ₹50/day (₹25 CGST + ₹25 SGST), or ₹20/day for nil returns, capped at ₹5,000 per return. Interest at 18% per annum applies on the outstanding tax." } },
          { "@type": "Question", name: "What happens if I don't file GST returns?", acceptedAnswer: { "@type": "Answer", text: "Non-filing leads to late fees, interest on unpaid tax, inability to file subsequent returns, blocking of e-way bill generation, and eventual cancellation of GST registration after continuous non-filing for 6 months." } },
          { "@type": "Question", name: "Can I file GST returns after the due date?", acceptedAnswer: { "@type": "Answer", text: "Yes, late filing is possible but attracts late fees (₹50/day or ₹20/day for nil returns) and interest (18% per annum). Returns for a particular tax period must be filed before filing the next period's return." } },
          { "@type": "Question", name: "How many GST returns do I need to file in a year?", acceptedAnswer: { "@type": "Answer", text: "Regular taxpayers file GSTR-1 and GSTR-3B (monthly or quarterly) plus the annual GSTR-9 — 25 or 9 returns a year. Composition dealers file four quarterly CMP-08s and one annual GSTR-4 — 5 returns a year." } },
        ],
      },
    ]);
    return () => { if (script.parentNode) script.parentNode.removeChild(script); };
  }, []);

  return (
    <article className="blog-article">
      <h1>How to File GST Returns Online — Complete Step-by-Step Guide 2026</h1>
      <p className="blog-meta">Updated October 2026 · 16 min read</p>

      <section>
        <p>
          Filing GST returns is a mandatory compliance requirement for every registered taxpayer in India.
          Whether you&apos;re a small business owner, a freelancer, or a large enterprise, understanding
          the return filing process is essential to avoid penalties and maintain good compliance standing.
          This comprehensive guide walks you through every type of GST return, the step-by-step online
          filing process, due dates, late fees, and common mistakes.
        </p>
        <p>
          Never miss a filing deadline — use our <Link to="/return-calendar">GST Return Calendar</Link> to
          track all due dates for FY 2026-27.
        </p>
      </section>

      <section>
        <h2>Types of GST Returns</h2>
        <p>
          The GST system requires different returns based on your registration type and turnover:
        </p>

        <h3>GSTR-1 — Outward Supply Details</h3>
        <ul>
          <li><strong>Who files:</strong> All regular registered taxpayers</li>
          <li><strong>What it contains:</strong> Details of all sales/outward supplies — B2B invoices, B2C sales, credit/debit notes, exports, and nil-rated supplies</li>
          <li><strong>Frequency:</strong> Monthly (by 11th of next month) or quarterly under QRMP scheme (by 13th of the month following the quarter)</li>
          <li><strong>Key point:</strong> GSTR-1 data flows into your buyer&apos;s GSTR-2B for their ITC claim. Delayed filing blocks your buyer&apos;s ITC</li>
        </ul>

        <h3>GSTR-3B — Summary Return with Tax Payment</h3>
        <ul>
          <li><strong>Who files:</strong> All regular registered taxpayers</li>
          <li><strong>What it contains:</strong> Summary of outward supplies, ITC claimed, tax liability, and tax payment</li>
          <li><strong>Frequency:</strong> Monthly (by 20th) or quarterly under QRMP. Monthly payment via challan for QRMP taxpayers</li>
          <li><strong>Key point:</strong> This is where you actually pay the GST. Tax payment must be made before or at the time of filing</li>
        </ul>

        <h3>GSTR-2B — Auto-Generated ITC Statement</h3>
        <ul>
          <li><strong>Who files:</strong> No filing needed — auto-generated by GSTN based on supplier&apos;s GSTR-1 data</li>
          <li><strong>What it contains:</strong> Eligible ITC from suppliers, ITC from imports, ITC reversal requirements</li>
          <li><strong>Available on:</strong> 14th of every month</li>
          <li><strong>Key point:</strong> Reconcile GSTR-2B with your purchase register before filing GSTR-3B</li>
        </ul>

        <h3>GSTR-9 — Annual Return</h3>
        <ul>
          <li><strong>Who files:</strong> Regular taxpayers with turnover above ₹2 crore</li>
          <li><strong>What it contains:</strong> Consolidated summary of all monthly/quarterly returns for the financial year</li>
          <li><strong>Due date:</strong> December 31st of the following year</li>
          <li><strong>Key point:</strong> Optional for businesses up to ₹2 crore turnover. No amendment possible after filing</li>
        </ul>

        <h3>CMP-08 — Composition Scheme Return</h3>
        <ul>
          <li><strong>Who files:</strong> Taxpayers under the Composition Scheme</li>
          <li><strong>What it contains:</strong> Summary of turnover and tax payment at the flat rate</li>
          <li><strong>Frequency:</strong> Quarterly (by 18th of month after quarter)</li>
          <li><strong>Key point:</strong> Plus annual GSTR-4 by April 30th</li>
        </ul>
      </section>

      <section>
        <h2>Step-by-Step: How to File GSTR-1 Online</h2>

        <h3>Step 1: Log In to the GST Portal</h3>
        <p>
          Go to <strong>gst.gov.in</strong> and log in with your GSTIN/username and password.
          Navigate to Services → Returns → Returns Dashboard. Select the financial year and
          return filing period (month or quarter).
        </p>

        <h3>Step 2: Prepare Invoice Data</h3>
        <p>
          Before starting, gather all sales invoices for the period. Organize them into:
        </p>
        <ul>
          <li><strong>B2B invoices:</strong> Sales to registered businesses (invoice-level details needed — GSTIN, invoice number, date, value, HSN, tax amount)</li>
          <li><strong>B2C large:</strong> Sales to unregistered persons exceeding ₹2.5 lakh (state-wise summary)</li>
          <li><strong>B2C small:</strong> Sales to unregistered persons under ₹2.5 lakh (rate-wise summary)</li>
          <li><strong>Credit/Debit notes:</strong> Any adjustments issued during the period</li>
          <li><strong>Export invoices:</strong> With or without payment of IGST</li>
          <li><strong>Nil-rated and exempt:</strong> Supplies not attracting GST</li>
        </ul>

        <h3>Step 3: Add Invoices</h3>
        <p>
          Click on each section (B2B, B2C Large, etc.) and enter invoice details. For B2B:
        </p>
        <ol>
          <li>Click &quot;Add Invoice&quot;</li>
          <li>Enter receiver&apos;s GSTIN (auto-fetches trade name)</li>
          <li>Enter invoice number, date, and total value</li>
          <li>Select Place of Supply (determines IGST or CGST+SGST)</li>
          <li>Add line items with HSN code, taxable value, and GST rate</li>
          <li>Save the invoice</li>
        </ol>
        <p>
          Use our <Link to="/hsn-sac-finder">HSN/SAC Finder</Link> to verify codes before entry.
        </p>

        <h3>Step 4: Review and Submit</h3>
        <p>
          After entering all invoices, click &quot;Generate Summary&quot; in the HSN Summary section. Review
          all sections for accuracy. Compare totals with your accounting records. Submit the return
          (you can still make changes after submit but before filing).
        </p>

        <h3>Step 5: File GSTR-1</h3>
        <p>
          After review, file using EVC (OTP to Aadhaar-linked mobile) or DSC. Once filed, GSTR-1
          cannot be amended — corrections must be made in the next period&apos;s return.
        </p>
      </section>

      <section>
        <h2>Step-by-Step: How to File GSTR-3B Online</h2>

        <h3>Step 1: Reconcile ITC with GSTR-2B</h3>
        <p>
          Before filing GSTR-3B, download your GSTR-2B statement and reconcile it with your purchase
          register. Identify mismatches — invoices present in your books but missing from GSTR-2B
          (supplier hasn&apos;t uploaded) and vice versa. Claim ITC only for invoices reflected in GSTR-2B.
        </p>
        <p>
          Use our <Link to="/itc-calculator">ITC Calculator</Link> for reconciliation.
        </p>

        <h3>Step 2: Access GSTR-3B</h3>
        <p>
          Log in → Returns Dashboard → Select period → Click &quot;Prepare Online&quot; under GSTR-3B.
          Some values are auto-populated from GSTR-1 and GSTR-2B. Review and modify if needed.
        </p>

        <h3>Step 3: Fill Return Sections</h3>
        <ul>
          <li><strong>Table 3.1:</strong> Outward supplies — taxable, zero-rated, nil-rated, exempt, and non-GST (auto-populated from GSTR-1)</li>
          <li><strong>Table 3.2:</strong> Inter-state supplies to unregistered persons and composition dealers</li>
          <li><strong>Table 4:</strong> Eligible ITC — from GSTR-2B (imports, domestic supplies, ISD), ITC reversed, net ITC available</li>
          <li><strong>Table 5:</strong> Exempt, nil-rated, and non-GST inward supplies (for information only)</li>
          <li><strong>Table 6:</strong> Payment of tax — auto-calculated based on Tables 3 and 4. Shows IGST, CGST, SGST/UTGST, and cess liability separately</li>
        </ul>

        <h3>Step 4: Pay Tax</h3>
        <p>
          Tax is paid from the Electronic Cash Ledger (deposited via challan) and Electronic Credit
          Ledger (ITC). First utilize ITC, then pay the balance via challan. The payment order is:
          IGST credit → CGST credit → SGST credit → cash payment.
        </p>
        <p>
          Create your payment challan on the GST portal under Services → Payments → Create Challan.
          Pay via net banking, UPI, NEFT/RTGS, or over-the-counter at authorized banks.
        </p>

        <h3>Step 5: File GSTR-3B</h3>
        <p>
          Review the summary, check the &quot;Offset Liability&quot; section to verify tax computation, and
          file using EVC or DSC. The return is filed once the &quot;File Return&quot; button is clicked
          and verification is complete.
        </p>
      </section>

      <section>
        <h2>GST Return Due Dates 2026-27</h2>

        <h3>Monthly Filers</h3>
        <ul>
          <li><strong>GSTR-1:</strong> 11th of the following month</li>
          <li><strong>GSTR-3B:</strong> 20th of the following month</li>
        </ul>

        <h3>Quarterly Filers (QRMP Scheme)</h3>
        <ul>
          <li><strong>GSTR-1 (quarterly):</strong> 13th of the month following the quarter</li>
          <li><strong>IFF (Invoice Furnishing Facility):</strong> 13th of first two months of the quarter (optional, for B2B invoices only)</li>
          <li><strong>GSTR-3B (quarterly):</strong> 22nd or 24th of the month following the quarter (staggered by state)</li>
          <li><strong>Monthly tax payment:</strong> 25th of each month via PMT-06 challan</li>
        </ul>

        <h3>Annual Returns</h3>
        <ul>
          <li><strong>GSTR-9:</strong> December 31, 2027 (for FY 2026-27)</li>
          <li><strong>GSTR-9C (reconciliation):</strong> December 31, 2027 (for turnover above ₹5 crore)</li>
          <li><strong>GSTR-4 (composition):</strong> April 30, 2027 (for FY 2026-27)</li>
        </ul>
        <p>
          Get all dates with state-specific staggering in our{" "}
          <Link to="/return-calendar">Return Calendar</Link>.
        </p>
      </section>

      <section>
        <h2>Late Fees and Penalties</h2>
        <ul>
          <li><strong>GSTR-1 late fee:</strong> ₹50/day (₹25 CGST + ₹25 SGST), max ₹5,000 per return</li>
          <li><strong>GSTR-3B late fee:</strong> ₹50/day (₹25 CGST + ₹25 SGST), max ₹5,000. For nil returns: ₹20/day, max ₹500</li>
          <li><strong>Interest:</strong> 18% per annum on the unpaid tax amount, calculated from the due date</li>
          <li><strong>GSTR-9 late fee:</strong> ₹200/day (₹100 CGST + ₹100 SGST), max 0.5% of state turnover</li>
          <li><strong>Excess ITC claimed:</strong> Interest of 24% per annum on the wrongly claimed ITC</li>
        </ul>
        <p>
          Calculate exact penalties with our <Link to="/penalty-calculator">Penalty Calculator</Link> and{" "}
          <Link to="/late-fee-calculator">Late Fee Calculator</Link>.
        </p>
      </section>

      <section>
        <h2>Common Mistakes in GST Return Filing</h2>
        <ol>
          <li><strong>GSTR-1 and GSTR-3B mismatch:</strong> The turnover reported in GSTR-1 (invoice-level) must match GSTR-3B (summary). Discrepancies trigger notices</li>
          <li><strong>Claiming ineligible ITC:</strong> Blocked credits under Section 17(5) — motor vehicles, food and beverages, personal consumption — cannot be claimed</li>
          <li><strong>Wrong place of supply:</strong> Incorrect place of supply leads to IGST vs CGST+SGST errors, causing ITC mismatches</li>
          <li><strong>Not reconciling GSTR-2B:</strong> Filing GSTR-3B without matching GSTR-2B leads to ITC excess/shortfall</li>
          <li><strong>Forgetting credit/debit notes:</strong> Unrecorded credit notes inflate reported sales, while missing debit notes understate purchases</li>
          <li><strong>Late filing order:</strong> GSTR-1 must be filed before GSTR-3B. Filing GSTR-3B first is not possible on the portal, but preparing GSTR-3B without filing GSTR-1 leads to auto-population errors</li>
          <li><strong>Ignoring nil returns:</strong> Even if there are no transactions, nil returns must be filed to avoid late fees</li>
          <li><strong>Incorrect HSN in GSTR-1:</strong> HSN Summary in GSTR-1 must match the HSN-wise breakup of your sales. Errors cause filing rejections</li>
        </ol>
      </section>

      <section>
        <h2>QRMP Scheme: Simplified Filing for Small Businesses</h2>
        <p>
          The Quarterly Return Monthly Payment (QRMP) scheme is available for businesses with
          aggregate turnover up to ₹5 crore:
        </p>
        <ul>
          <li><strong>Quarterly filing:</strong> File GSTR-1 and GSTR-3B quarterly instead of monthly</li>
          <li><strong>Monthly payment:</strong> Pay tax monthly via PMT-06 challan (35% of net tax of last quarter as fixed sum method, or actual tax as self-assessment method)</li>
          <li><strong>Invoice Furnishing Facility (IFF):</strong> Optionally upload B2B invoices in months 1 and 2 of the quarter so your buyers can claim ITC without waiting for quarterly GSTR-1</li>
          <li><strong>How to opt in:</strong> Go to Services → Returns → Opt-in for QRMP on the GST portal. Opt-in window: 1st to last day of the first month of each quarter</li>
        </ul>
      </section>

      <section>
        <h2>Tips for Smooth GST Return Filing</h2>
        <ul>
          <li><strong>Maintain digital records:</strong> Keep organized digital copies of all invoices, bills, and purchase records</li>
          <li><strong>Reconcile monthly:</strong> Don&apos;t wait until the due date — reconcile GSTR-2B with your purchase register as soon as it&apos;s available (14th of each month)</li>
          <li><strong>File early:</strong> Avoid portal congestion by filing at least 3–5 days before the due date</li>
          <li><strong>Use offline tools:</strong> For large numbers of invoices, use the GST offline tool or JSON upload instead of entering invoices one by one</li>
          <li><strong>Set reminders:</strong> Track all due dates with our <Link to="/return-calendar">Return Calendar</Link></li>
          <li><strong>Review before filing:</strong> Once filed, returns cannot be revised (only corrected in next period). Double-check all figures</li>
          <li><strong>Keep challan copies:</strong> Save payment challan receipts for 72 months as required by GST law</li>
        </ul>
      </section>

      <section>
        <h2>Frequently Asked Questions</h2>

        <h3>Can I file GST returns myself without a CA?</h3>
        <p>
          Yes, the entire process is online and can be done by any authorized person. Free tools
          like <Link to="/">DoAide GST</Link> help with calculations, HSN lookup, and reconciliation.
          For complex businesses or GST audits, professional guidance is recommended.
        </p>

        <h3>What is the penalty for late GST return filing?</h3>
        <p>
          GSTR-3B: ₹50/day (₹25 CGST + ₹25 SGST), capped at ₹5,000 per return. Nil returns: ₹20/day,
          max ₹500. Plus 18% interest per annum on unpaid tax. Calculate exact amounts with our{" "}
          <Link to="/late-fee-calculator">Late Fee Calculator</Link>.
        </p>

        <h3>What happens if I don&apos;t file GST returns?</h3>
        <p>
          Consequences include late fees, interest, blocking of e-way bill generation, inability to
          file subsequent returns, and eventual cancellation of registration after 6 consecutive
          months of non-filing. Your buyers also lose ITC on invoices you issued.
        </p>

        <h3>Can I file GST returns after the due date?</h3>
        <p>
          Yes, late filing is accepted but attracts penalties and interest. You must file returns
          sequentially — you cannot file a later period&apos;s return without filing all previous
          pending returns first.
        </p>

        <h3>How many GST returns do I need to file in a year?</h3>
        <p>
          Regular monthly filers: 25 returns (12 GSTR-1 + 12 GSTR-3B + 1 GSTR-9). QRMP quarterly
          filers: 9 returns (4 GSTR-1 + 4 GSTR-3B + 1 GSTR-9). Composition dealers: 5 returns
          (4 CMP-08 + 1 GSTR-4).
        </p>
      </section>

      <section>
        <h2>Free GST Filing Tools</h2>
        <ul>
          <li><Link to="/return-calendar">GST Return Calendar</Link> — all due dates for FY 2026-27</li>
          <li><Link to="/calculator">GST Calculator</Link> — calculate tax on your sales</li>
          <li><Link to="/itc-calculator">ITC Calculator</Link> — reconcile input tax credits</li>
          <li><Link to="/penalty-calculator">Penalty Calculator</Link> — estimate late filing penalties</li>
          <li><Link to="/late-fee-calculator">Late Fee Calculator</Link> — calculate exact late fees</li>
          <li><Link to="/invoice-generator">Invoice Generator</Link> — create GST-compliant invoices</li>
        </ul>
        <p>
          <Link to="/">Start filing with DoAide GST free →</Link>
        </p>
      </section>
    </article>
  );
}
