import { useEffect } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";

const TITLE = "Last Date to Claim ITC for FY 2025-26: 30 November 2026 Deadline Explained";

const FAQ = [
  ["What is the last date to claim ITC for FY 2025-26?", "30 November 2026, or the date you file GSTR-9 for 2025-26 if that is earlier. The credit has to be in a GSTR-3B filed by that date."],
  ["Can I claim missed ITC of FY 2025-26 in the November 2026 GSTR-3B?", "No. The November return is filed in December, after the window closes. The last return that can carry it is the October 2026 GSTR-3B, filed on or before 30 November."],
  ["Does filing GSTR-9 early reduce the time to claim ITC?", "Yes. Section 16(4) ends the window on 30 November or the date the annual return is filed, whichever is earlier. File GSTR-9 after your final claim."],
  ["What if my supplier uploads the invoice after 30 November?", "The credit is lost, because it cannot be in a return filed by the deadline. Chase suppliers missing from GSTR-2B well before November."],
  ["Is the deadline different for debit notes?", "A debit note counts from its own date. One issued in FY 2026-27 against a 2025-26 invoice can be claimed until 30 November 2027."],
];

export default function LastDateToClaimItc() {
  usePageTitle(TITLE);

  useEffect(() => {
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.content = "The last date to claim input tax credit for FY 2025-26 is 30 November 2026 under Section 16(4). What counts, how GSTR-9 shortens it, and a checklist to recover missed ITC in time.";

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
        headline: TITLE,
        description: "Section 16(4) time limit for FY 2025-26 input tax credit, how an early GSTR-9 closes it, and how to recover missed credit before 30 November 2026.",
        url: "https://gst.doaide.com/blog/last-date-to-claim-itc-fy-2025-26",
        datePublished: "2026-10-26",
        dateModified: "2026-10-26",
        publisher: { "@type": "Organization", name: "DoAide" },
      },
      {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: FAQ.map(([q, a]) => ({ "@type": "Question", name: q, acceptedAnswer: { "@type": "Answer", text: a } })),
      },
    ]);
    return () => { if (script.parentNode) script.parentNode.removeChild(script); };
  }, []);

  return (
    <article className="blog-article">
      <h1>{TITLE}</h1>
      <p className="blog-meta">Updated October 2026 · 7 min read</p>

      <section>
        <p>
          Every year a share of perfectly valid input tax credit is lost for one reason: it was
          claimed too late. For purchases made in FY 2025-26 (April 2025 to March 2026), the last
          day is <strong>30 November 2026</strong>. After that, the credit cannot be claimed in any
          return, however genuine the invoice.
        </p>
        <p>
          Not sure about a particular invoice? The{" "}
          <Link to="/itc-time-limit">ITC time limit checker</Link> gives the last date for any
          invoice or debit note date.
        </p>
      </section>

      <section>
        <h2>What Section 16(4) says</h2>
        <p>
          A registered person cannot take credit on an invoice or debit note after{" "}
          <strong>30 November following the end of the financial year</strong> it relates to, or
          after filing the annual return for that year, <em>whichever is earlier</em>. The 30
          November date came in through the Finance Act 2022. Before that, the window closed with
          the September return.
        </p>
        <p>Three details catch people out:</p>
        <ul>
          <li><strong>The return has to be filed, not just due.</strong> Credit counts only if the GSTR-3B carrying it is filed by 30 November.</li>
          <li><strong>The invoice date decides the year.</strong> An invoice dated 28 March 2026 belongs to FY 2025-26, even if the goods arrived in April.</li>
          <li><strong>Debit notes stand alone.</strong> Since January 2021 a debit note counts from its own date, not the original invoice&apos;s.</li>
        </ul>
      </section>

      <section>
        <h2>How an early GSTR-9 shortens the window</h2>
        <p>
          The deadline is the earlier of 30 November and the date you file GSTR-9. A business that
          files its 2025-26 annual return in September 2026 loses the October return as a vehicle
          for missed credit. Unless you are certain every rupee is claimed, file GSTR-9 after the
          October GSTR-3B. The <Link to="/gstr9-helper">GSTR-9 helper</Link> and{" "}
          <Link to="/gstr9-checklist">checklist</Link> help you prepare it in parallel.
        </p>
      </section>

      <section>
        <h2>A four-week checklist to recover missed ITC</h2>
        <ol>
          <li><strong>Reconcile the year.</strong> Compare your purchase register, GSTR-2B and the credit claimed in GSTR-3B for all twelve months. The <Link to="/itc-reconciliation-dashboard">ITC reconciliation dashboard</Link> does this month by month.</li>
          <li><strong>List unclaimed eligible credit.</strong> Invoices in books and in GSTR-2B but not yet claimed can go straight into the October return.</li>
          <li><strong>Chase missing suppliers.</strong> Invoices in your books but not in GSTR-2B need the supplier to report them first, in a GSTR-1 filed by early November.</li>
          <li><strong>Check eligibility before claiming.</strong> Blocked credit under section 17(5) does not become claimable because it was missed. Use the <Link to="/input-tax-credit">ITC eligibility checker</Link>.</li>
          <li><strong>Settle reversals too.</strong> Unpaid suppliers past 180 days need a <Link to="/itc-180-day-rule">Rule 37 reversal</Link>, and mixed taxable-exempt businesses a year-end <Link to="/itc-reversal-rule-42">Rule 42 true-up</Link>.</li>
          <li><strong>File the October GSTR-3B by 30 November.</strong> It is due on 20 November. Filing late costs a <Link to="/late-fee-calculator">late fee</Link> but still preserves the credit.</li>
        </ol>
      </section>

      <section>
        <h2>Older years: Section 16(5) and 16(6)</h2>
        <p>
          For FY 2017-18 to 2020-21, section 16(5) (Finance (No. 2) Act 2024, with retrospective
          effect) lets credit stand if it was claimed in any return filed by 30 November 2021.
          Section 16(6) helps businesses whose registration was cancelled and later restored: credit
          for the cancelled period can be claimed in returns filed within 30 days of the revocation
          order.
        </p>
      </section>

      <section>
        <h2>Frequently Asked Questions</h2>
        {FAQ.map(([q, a]) => (
          <div key={q}>
            <h3>{q}</h3>
            <p>{a}</p>
          </div>
        ))}
      </section>
    </article>
  );
}
