import { useEffect } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";

export default function Gstr1Gstr3bMismatchFix() {
  usePageTitle("GSTR-1 vs GSTR-3B Mismatch: Why It Happens and How to Fix It");

  useEffect(() => {
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.content = "Why GSTR-1 and GSTR-3B figures don't match, how to reconcile them, how to correct errors using GSTR-1A and the next return, and how to reply to a DRC-01B notice — with a monthly checklist.";

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
        headline: "GSTR-1 vs GSTR-3B Mismatch: Why It Happens and How to Fix It",
        description: "Common causes of GSTR-1 and GSTR-3B mismatches, step-by-step reconciliation, correcting errors with GSTR-1A, and replying to DRC-01B notices.",
        url: "https://gst.doaide.com/blog/gstr-1-vs-gstr-3b-mismatch-how-to-fix",
        datePublished: "2026-10-22",
        dateModified: "2026-10-22",
        publisher: { "@type": "Organization", name: "DoAide" },
      },
      {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: [
          { "@type": "Question", name: "Why do GSTR-1 and GSTR-3B not match?", acceptedAnswer: { "@type": "Answer", text: "Usually because invoices, credit notes or amendments were reported in one return but not the other, were reported in different tax periods, or because advances and rounding were treated differently." } },
          { "@type": "Question", name: "What is a DRC-01B notice?", acceptedAnswer: { "@type": "Answer", text: "DRC-01B is an intimation sent when GSTR-1 shows more tax than was paid through GSTR-3B beyond a notified limit. Pay the difference or explain it in Part B, usually within 7 days." } },
          { "@type": "Question", name: "What happens if I ignore a DRC-01B notice?", acceptedAnswer: { "@type": "Answer", text: "The portal can block filing of your next GSTR-1 or IFF until you pay the difference or file a reply. The officer may also start proceedings to recover the short-paid tax with interest." } },
          { "@type": "Question", name: "How do I correct a mistake in GSTR-1 before filing GSTR-3B?", acceptedAnswer: { "@type": "Answer", text: "Use GSTR-1A, an optional form available after filing GSTR-1 and before filing GSTR-3B for the same period. Corrections made there flow into the auto-populated GSTR-3B." } },
          { "@type": "Question", name: "Can GSTR-3B be revised?", acceptedAnswer: { "@type": "Answer", text: "No. GSTR-3B cannot be revised once filed. Short-reported tax is added in the next period's GSTR-3B and paid with interest; excess-reported tax is adjusted in later returns." } },
        ],
      },
    ]);
    return () => { if (script.parentNode) script.parentNode.removeChild(script); };
  }, []);

  return (
    <article className="blog-article">
      <h1>GSTR-1 vs GSTR-3B Mismatch: Why It Happens and How to Fix It</h1>
      <p className="blog-meta">Updated October 2026 · 10 min read</p>

      <section>
        <p>
          GSTR-1 reports your sales invoice by invoice. GSTR-3B reports the totals and pays the tax. In a
          perfect world the outward tax in both would be identical every month. In practice, a missed invoice,
          a credit note entered late or an amendment made in only one return is enough to create a gap — and
          the GST system now spots that gap automatically.
        </p>
        <p>
          If you are new to the two returns, start with our{" "}
          <Link to="/blog/gstr-1-vs-gstr-3b-difference">explainer on the difference between GSTR-1 and
          GSTR-3B</Link>. This guide is for the next step: finding out why your numbers don&apos;t match, fixing
          them, and responding if the department has already noticed.
        </p>
      </section>

      <section>
        <h2>Why the Mismatch Matters More in 2026</h2>
        <p>
          Since 2023 the GST portal compares the liability in GSTR-1 (and IFF) with the tax paid in GSTR-3B for
          every taxpayer. When GSTR-1 shows more tax than GSTR-3B beyond a notified limit, the system issues an
          intimation in <strong>Form DRC-01B</strong>. And from mid-2025, the outward liability auto-populated
          into GSTR-3B from GSTR-1, GSTR-1A and IFF is locked, so the old habit of quietly editing GSTR-3B no
          longer works — corrections must go through GSTR-1A or a later GSTR-1.
        </p>
        <p>
          A mismatch in the other direction (GSTR-3B higher than GSTR-1) usually means you overpaid or did not
          report invoices in GSTR-1, which hurts your buyers because their ITC depends on your GSTR-1.
        </p>
      </section>

      <section>
        <h2>The 8 Most Common Causes</h2>
        <table>
          <thead>
            <tr><th>Cause</th><th>Which return is higher</th><th>Typical fix</th></tr>
          </thead>
          <tbody>
            <tr><td>Invoices left out of GSTR-1</td><td>GSTR-3B</td><td>Report them in the next GSTR-1</td></tr>
            <tr><td>Sales left out of GSTR-3B</td><td>GSTR-1</td><td>Add and pay in the next GSTR-3B with interest</td></tr>
            <tr><td>Credit notes in GSTR-1 only</td><td>GSTR-3B</td><td>Adjust liability in the next GSTR-3B</td></tr>
            <tr><td>Invoice reported in different months</td><td>Either</td><td>Usually resolves next month; document it</td></tr>
            <tr><td>Amendments made in GSTR-1 only</td><td>Either</td><td>Mirror the change in GSTR-3B</td></tr>
            <tr><td>Advances received and later adjusted</td><td>Either</td><td>Report advances and adjustments consistently</td></tr>
            <tr><td>Wrong tax head (IGST vs CGST+SGST)</td><td>Head-wise mismatch</td><td>Correct the place of supply in GSTR-1A or amendments</td></tr>
            <tr><td>E-invoices auto-populated but cancelled in books</td><td>GSTR-1</td><td>Cancel on the IRP within 24 hours, or amend in GSTR-1</td></tr>
          </tbody>
        </table>
        <p>
          Wrong tax heads are common with inter-state sales. If you are unsure whether a sale is IGST or
          CGST+SGST, check it with our <Link to="/place-of-supply">place of supply tool</Link> and read{" "}
          <Link to="/blog/difference-between-cgst-sgst-igst">CGST vs SGST vs IGST</Link>.
        </p>
      </section>

      <section>
        <h2>How to Reconcile GSTR-1 and GSTR-3B: Step by Step</h2>
        <ol>
          <li>
            <strong>Pull both summaries for the same period.</strong> Download the GSTR-1 summary and the filed
            GSTR-3B (or the auto-populated draft) for each month of the year.
          </li>
          <li>
            <strong>Compare tax head by tax head.</strong> Put IGST, CGST, SGST and cess side by side for taxable
            value and tax. Compare Table 3.1(a) of GSTR-3B with B2B + B2CL + B2CS + exports + credit/debit notes
            in GSTR-1.
          </li>
          <li>
            <strong>Compare cumulatively, not just monthly.</strong> A gap in July that reverses in August is a
            timing difference. A gap that keeps growing is a real error.
          </li>
          <li>
            <strong>Trace each difference to invoices.</strong> Match your sales register against GSTR-1 invoice
            by invoice to find what is missing, duplicated or in the wrong month.
          </li>
          <li>
            <strong>Record the explanation.</strong> Keep a short note for every difference; you will need it for
            a DRC-01B reply or at GSTR-9 time.
          </li>
        </ol>
        <p>
          If the gap is on the purchase side instead — your ITC in GSTR-3B does not match GSTR-2B — use our{" "}
          <Link to="/gstr2b-reconciliation">GSTR-2B reconciliation tool</Link> and the{" "}
          <Link to="/itc-mismatch">ITC mismatch resolver</Link>.
        </p>
      </section>

      <section>
        <h2>How to Fix the Mismatch</h2>

        <h3>Before filing GSTR-3B: use GSTR-1A</h3>
        <p>
          GSTR-1A lets you add missed invoices or correct details in a GSTR-1 you have already filed, as long as
          you do it before filing GSTR-3B for that period. The corrected figures then flow into GSTR-3B
          automatically. This is the cleanest fix, so make reviewing the GSTR-3B draft a monthly habit.
        </p>

        <h3>After filing: correct in the next period</h3>
        <p>
          Neither return can be revised once filed. If GSTR-3B under-reported tax, add the missing liability in
          the next GSTR-3B and pay interest at 18% per year from the original due date — calculate it with the{" "}
          <Link to="/interest-calculator">GST interest calculator</Link>. If GSTR-1 missed invoices, report them
          in the next GSTR-1 so your buyers get their ITC. Amendments to earlier invoices go in the amendment
          tables of GSTR-1.
        </p>

        <h3>The year-end deadline</h3>
        <p>
          Corrections for a financial year can be made until 30 November of the following year or the date of
          filing the annual return, whichever is earlier. After that, differences can
          only be shown and paid through GSTR-9 and DRC-03. Our{" "}
          <Link to="/gstr9-helper">GSTR-9 helper</Link> walks you through the annual reconciliation.
        </p>
      </section>

      <section>
        <h2>Got a DRC-01B? How to Respond</h2>
        <p>
          The intimation shows the difference by tax head. You normally have <strong>7 days</strong> to respond
          in <strong>Part B</strong> of DRC-01B on the portal, choosing one of these:
        </p>
        <ul>
          <li><strong>Paid the difference</strong> — pay through DRC-03 and quote the reference number.</li>
          <li><strong>Explain the difference</strong> — for example, a timing difference already corrected in a later return, or an amendment. Attach your reconciliation.</li>
          <li><strong>A combination</strong> — pay part and explain the rest.</li>
        </ul>
        <p>
          Ignoring the intimation can block filing of your next GSTR-1 or IFF until you reply, which then delays
          your buyers&apos; ITC and can cost you customers. If the officer does not accept your explanation, they
          may issue a show cause notice, so keep the explanation factual and backed by invoice-level data.
        </p>
      </section>

      <section>
        <h2>A Monthly Checklist to Prevent Mismatches</h2>
        <ul>
          <li>Close your sales register before preparing GSTR-1; don&apos;t file from a half-updated book.</li>
          <li>Reconcile e-invoices on the IRP with your books and GSTR-1.</li>
          <li>File GSTR-1 first, then review the auto-populated GSTR-3B against your sales register.</li>
          <li>Use GSTR-1A for any correction found at this stage.</li>
          <li>Record credit notes in the same period in both returns.</li>
          <li>Run a cumulative GSTR-1 vs GSTR-3B comparison every quarter, not just at year end.</li>
        </ul>
        <p>
          Avoid the related errors covered in{" "}
          <Link to="/blog/gstr-3b-common-mistakes-how-to-avoid">GSTR-3B common mistakes</Link>, and track every
          deadline on the <Link to="/return-calendar">GST return calendar</Link>.
        </p>
      </section>

      <section>
        <h2>Frequently Asked Questions</h2>

        <h3>Why do GSTR-1 and GSTR-3B not match?</h3>
        <p>
          Usually because invoices, credit notes or amendments were reported in one return but not the other,
          or in different periods.
        </p>

        <h3>What happens if I ignore a DRC-01B notice?</h3>
        <p>
          Filing of your next GSTR-1 or IFF can be blocked until you pay or reply, and the officer may start
          recovery proceedings.
        </p>

        <h3>Can GSTR-3B be revised?</h3>
        <p>
          No. Corrections are made in the next period&apos;s GSTR-3B, with interest on any tax paid late.
        </p>

        <h3>Is a small mismatch a problem?</h3>
        <p>
          Small timing differences that reverse in the next month are normal. Keep a note of them so you can
          explain them in your annual return.
        </p>
      </section>

      <section>
        <h2>Free Tools for Reconciliation</h2>
        <ul>
          <li><Link to="/gstr2b-reconciliation">GSTR-2B Reconciliation</Link> — match purchases with GSTR-2B</li>
          <li><Link to="/itc-mismatch">ITC Mismatch Resolver</Link> — fix ITC differences</li>
          <li><Link to="/interest-calculator">GST Interest Calculator</Link> — interest on late-paid tax</li>
          <li><Link to="/gstr9-helper">GSTR-9 Helper</Link> — annual return reconciliation</li>
          <li><Link to="/place-of-supply">Place of Supply Tool</Link> — IGST or CGST+SGST</li>
        </ul>
        <p>
          <Link to="/">Start using DoAide GST free →</Link>
        </p>
      </section>
    </article>
  );
}
