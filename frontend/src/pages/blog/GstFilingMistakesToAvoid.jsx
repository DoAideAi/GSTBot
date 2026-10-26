import { useEffect } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";

const TITLE = "GST Filing Mistakes to Avoid in 2026: 15 Errors That Trigger Notices";
const DESCRIPTION =
  "The GST filing mistakes that cost Indian businesses money in 2026 — GSTR-1 vs 3B gaps, ITC beyond GSTR-2B, missed RCM, the 30 November deadline, the three-year filing bar — and how to fix each one.";

const FAQS = [
  { q: "What is the most common GST filing mistake?", a: "Declaring less tax in GSTR-3B than in GSTR-1 for the same month. The portal compares them, and a large gap triggers a DRC-01B notice that must be answered or paid before the next GSTR-1." },
  { q: "Can a filed GSTR-3B be revised?", a: "No. Errors are corrected in a later month's GSTR-3B, or through DRC-03 for tax that was short-paid, with 18% interest. Liability errors in GSTR-1 should be fixed through GSTR-1A before GSTR-3B is filed." },
  { q: "Can I claim ITC that does not appear in GSTR-2B?", a: "No. Since January 2022 Rule 36(4) allows credit only for invoices reflected in GSTR-2B; the old provisional margin no longer exists. Claiming beyond GSTR-2B produces a DRC-01C intimation." },
  { q: "Is there a time limit for filing old GST returns?", a: "Yes. From July 2025 the GST portal blocks GSTR-1, GSTR-3B, GSTR-4 and GSTR-9 returns filed more than three years after their due date, so very old non-filed returns can no longer be filed at all." },
  { q: "Can late fee and interest be paid from input tax credit?", a: "No. Late fee, interest and penalty must be paid in cash from the electronic cash ledger. ITC can be used only against output tax." },
];

export default function GstFilingMistakesToAvoid() {
  usePageTitle(TITLE);

  useEffect(() => {
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.content = DESCRIPTION;

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
        description: DESCRIPTION,
        url: "https://gst.doaide.com/blog/gst-filing-mistakes-to-avoid",
        datePublished: "2026-10-23",
        dateModified: "2026-10-23",
        publisher: { "@type": "Organization", name: "DoAide" },
      },
      {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: FAQS.map((f) => ({ "@type": "Question", name: f.q, acceptedAnswer: { "@type": "Answer", text: f.a } })),
      },
    ]);
    return () => { if (script.parentNode) script.parentNode.removeChild(script); };
  }, []);

  return (
    <article className="blog-article">
      <h1>{TITLE}</h1>
      <p className="blog-meta">Updated 23 October 2026 · 12 min read</p>

      <section>
        <p>
          Most GST notices are not about fraud. They come from small, repeatable filing errors that the
          portal now catches on its own. GSTR-1, GSTR-2B, GSTR-3B, e-invoices and e-way bills are matched
          by machine every month, and gaps go straight out as DRC-01B or DRC-01C intimations, ASMT-10
          scrutiny notices, or a blocked e-way bill. Each one costs interest, a late fee, or an
          afternoon spent replying.
        </p>
        <p>
          These are the fifteen mistakes we see most often in 2026, grouped by where they happen, with
          the fix for each. Every figure here can be checked with a free tool, linked as we go.
        </p>
      </section>

      <section>
        <h2>Outward supplies and GSTR-1</h2>

        <h3>1. Paying less tax in GSTR-3B than GSTR-1 shows</h3>
        <p>
          GSTR-1 says what you sold and GSTR-3B says what you paid tax on. When the GSTR-3B liability is
          lower, Rule 88C sends a <strong>DRC-01B</strong> intimation. You must pay the gap or explain it
          before your next GSTR-1 can be filed. Since the July 2025 tax period, the liability auto-filled
          into GSTR-3B from GSTR-1/1A can no longer be edited downwards in GSTR-3B. Fix GSTR-1 through
          <strong> GSTR-1A</strong> before you file 3B, not after.
        </p>
        <p>
          <em>Fix:</em> reconcile the two every month, not every March. Our{" "}
          <Link to="/gstr9-summary">GSTR-9 summary tool</Link> puts all twelve months side by side and works
          out the DRC-03 amount and interest for any month that was short-paid.
        </p>

        <h3>2. Reporting a B2B sale as B2C</h3>
        <p>
          If you leave out the buyer&apos;s GSTIN, the invoice goes into the B2C tables and never reaches
          your customer&apos;s GSTR-2B. They lose the credit and you lose the customer&apos;s trust. Check
          the GSTIN when you raise the invoice. Amend wrong entries in the next GSTR-1, and do it before
          30 November after the year ends.
        </p>

        <h3>3. Wrong HSN codes or too few digits</h3>
        <p>
          Table 12 of GSTR-1 needs 4-digit HSN codes up to ₹5 crore turnover and 6-digit codes above that,
          reported separately for B2B and B2C. A wrong code usually means a wrong rate, and that is
          especially likely now that many goods moved slabs after GST 2.0. Look the code up rather than
          copying last year&apos;s. The <Link to="/hsn">HSN code finder</Link> shows the current rate.
        </p>

        <h3>4. E-invoices and e-way bills that don&apos;t match GSTR-1</h3>
        <p>
          E-invoice data from the IRP fills GSTR-1 automatically. If you then add the same invoice by hand,
          or cancel it on the IRP but not in your books, the totals drift apart. Treat the IRP as the
          source of truth, and reconcile e-way bill values against GSTR-1 for every month with heavy movement.
        </p>
      </section>

      <section>
        <h2>Input tax credit</h2>

        <h3>5. Claiming credit that isn&apos;t in GSTR-2B</h3>
        <p>
          Since January 2022 you can claim only what appears in GSTR-2B. The old provisional margin is gone.
          A claim above GSTR-2B triggers a <strong>DRC-01C</strong> under Rule 88D. If the excess was used
          to pay tax, it also carries 18% interest under Section 50(3). See exactly where you stand month
          by month on the <Link to="/itc-reconciliation-dashboard">ITC reconciliation dashboard</Link>.
        </p>

        <h3>6. Ignoring the Invoice Management System</h3>
        <p>
          Invoices you neither accept nor reject in IMS are treated as accepted when GSTR-2B is generated.
          If an invoice is wrong (a duplicate, a wrong amount, a purchase that never happened), reject it
          before 2B is generated. Otherwise the credit flows in and you will have to reverse it later. Our{" "}
          <Link to="/blog/gst-invoice-management-system-ims-guide">IMS guide</Link> walks through the
          month-end routine.
        </p>

        <h3>7. Forgetting the reversals</h3>
        <ul>
          <li><strong>Rule 37</strong>: credit on any invoice not paid to the supplier within 180 days must be reversed, and can be reclaimed once you pay.</li>
          <li><strong>Rule 37A</strong>: credit must be reversed if the supplier has not filed GSTR-3B for that period by 30 September of the following year.</li>
          <li><strong>Rules 42 and 43</strong>: common credit must be split when you also make exempt supplies.</li>
          <li><strong>Section 17(5)</strong>: blocked credits such as most motor vehicles, food and beverages, and personal-use items must never be claimed.</li>
        </ul>

        <h3>8. Missing the Section 16(4) deadline</h3>
        <p>
          Credit for FY 2025-26 can be claimed only until <strong>30 November 2026</strong>, or the date
          you file the annual return if that comes first. After that, any invoice your supplier uploaded
          late, or that you simply forgot, is lost for good. Look for unclaimed GSTR-2B credit in October,
          not December.
        </p>

        <h3>9. Mishandling reverse charge</h3>
        <p>
          Goods transport, legal services, renting by an unregistered person to a registered business and
          the other notified supplies put the tax on you. Two errors are common: not paying the RCM
          liability at all, and claiming the matching ITC before paying it in cash. The order matters. You
          pay RCM through the cash ledger, then claim the credit. The{" "}
          <Link to="/rcm-calculator">RCM calculator</Link> keeps both sides straight.
        </p>
      </section>

      <section>
        <h2>Payments, deadlines and late fees</h2>

        <h3>10. Paying under the wrong tax head</h3>
        <p>
          Charging CGST + SGST on an interstate sale (or IGST on an intrastate one) is not fixed by moving
          money between heads. You pay the correct tax and claim a refund of the wrong one under Section 77.
          Decide the place of supply before you invoice. The <Link to="/place-of-supply">place of supply
          tool</Link> settles the tricky cases.
        </p>

        <h3>11. Assuming late fee is capped at ₹10,000</h3>
        <p>
          The real GSTR-3B and GSTR-1 caps depend on last year&apos;s turnover: ₹2,000 up to ₹1.5 crore,
          ₹5,000 up to ₹5 crore and ₹10,000 above. Nil returns pay ₹20 a day, capped at ₹500. GSTR-9 has
          its own slabs. Late fee and interest must be paid in <strong>cash</strong>, never from ITC. Work out
          both in one step with the{" "}
          <Link to="/gst-late-fee-interest-calculator">late fee and interest calculator</Link>.
        </p>

        <h3>12. Skipping nil returns</h3>
        <p>
          No sales this month still means a return. A missed nil GSTR-3B costs a late fee. Two missed
          periods also block your e-way bills under Rule 138E, and six months of non-filing can lead to
          cancellation. A nil return takes two minutes by SMS. See{" "}
          <Link to="/blog/how-to-file-nil-gst-return-online-sms">how to file a nil return</Link>.
        </p>

        <h3>13. Leaving old returns for &quot;later&quot;</h3>
        <p>
          From July 2025 the portal will not accept GSTR-1, GSTR-3B, GSTR-4 or GSTR-9 returns more than
          <strong> three years</strong> after their due date. A business that stops filing and plans to catch
          up eventually may find the window closed for good. Old gaps then become a matter for assessment
          rather than something you can fix yourself.
        </p>
      </section>

      <section>
        <h2>Annual return and scheme choice</h2>

        <h3>14. Treating GSTR-9 as a copy-paste of the monthly returns</h3>
        <p>
          GSTR-9 reports outward supplies on the GSTR-1 basis (Table 4) and tax paid on the GSTR-3B basis
          (Table 9), and it compares claimed ITC with GSTR-2B (Table 8). Officers read those
          differences first. Any short payment you find while preparing it goes through DRC-03 with
          interest. It cannot be paid inside GSTR-9. Use the{" "}
          <Link to="/gstr9-checklist">GSTR-9 checklist</Link> before the 31 December due date.
        </p>

        <h3>15. Getting the composition scheme base wrong</h3>
        <p>
          Composition dealers make their own version of these mistakes. Manufacturers pay 1% on total
          turnover, exempt supplies included, while traders pay 1% only on taxable supplies. Reverse-charge
          purchases are still taxed at the full rate. And crossing ₹1.5 crore mid-year (₹50 lakh for
          service providers) takes you out of the scheme on that day, not at year end. The{" "}
          <Link to="/composition-tax-calculator">composition tax calculator</Link> handles all three.
        </p>
      </section>

      <section>
        <h2>A monthly routine that prevents most of these</h2>
        <ol>
          <li>Before the 11th: reconcile sales books with e-invoices and file GSTR-1. Use GSTR-1A for anything missed.</li>
          <li>On the 14th: act on every invoice in IMS (accept, reject or keep pending), then check GSTR-2B against your purchase register.</li>
          <li>Before the 20th: file GSTR-3B with liability matching GSTR-1, ITC no higher than GSTR-2B, and RCM paid in cash.</li>
          <li>Each quarter: review Rule 37 and Rule 37A reversals and chase suppliers who have not filed.</li>
          <li>Each October: sweep for unclaimed credit and pending credit notes before 30 November.</li>
        </ol>
        <p>
          Put the dates in your calendar from the <Link to="/due-dates">GST due dates page</Link>.
        </p>
      </section>

      <section>
        <h2>Frequently Asked Questions</h2>
        {FAQS.map((f) => (
          <div key={f.q}>
            <h3>{f.q}</h3>
            <p>{f.a}</p>
          </div>
        ))}
      </section>

      <section>
        <h2>Related free tools</h2>
        <ul>
          <li><Link to="/gst-late-fee-interest-calculator">Late Fee &amp; Interest Calculator</Link>: what a late return really costs</li>
          <li><Link to="/itc-reconciliation-dashboard">ITC Reconciliation Dashboard</Link>: books vs GSTR-2B vs GSTR-3B</li>
          <li><Link to="/gstr9-summary">GSTR-9 Summary Generator</Link>: annual GSTR-1 vs 3B check</li>
          <li><Link to="/gstr2b-reconciliation">GSTR-2B Reconciliation</Link>: invoice-level matching</li>
          <li><Link to="/composition-tax-calculator">Composition Tax Calculator</Link>: CMP-08 by quarter</li>
        </ul>
      </section>
    </article>
  );
}
