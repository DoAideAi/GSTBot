import { useEffect } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";

export default function HowToFileNilGstReturn() {
  usePageTitle("How to File a Nil GST Return Online (and by SMS) in 2026");

  useEffect(() => {
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.content = "Step-by-step guide to filing nil GSTR-3B and nil GSTR-1 online on the GST portal or by SMS to 14409 in 2026 — who can file nil, SMS formats, due dates, late fees and common mistakes.";

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
        headline: "How to File a Nil GST Return Online (and by SMS) in 2026",
        description: "File nil GSTR-3B and GSTR-1 on the GST portal or by SMS — eligibility, step-by-step process, SMS formats, late fees and mistakes to avoid.",
        url: "https://gst.doaide.com/blog/how-to-file-nil-gst-return-online-sms",
        datePublished: "2026-10-22",
        dateModified: "2026-10-22",
        publisher: { "@type": "Organization", name: "DoAide" },
      },
      {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: [
          { "@type": "Question", name: "Is it mandatory to file a nil GST return?", acceptedAnswer: { "@type": "Answer", text: "Yes. Every regular GST-registered taxpayer must file GSTR-1 and GSTR-3B for each period even if there were no sales or purchases. Not filing attracts late fees and can lead to cancellation of registration." } },
          { "@type": "Question", name: "How do I file a nil GSTR-3B by SMS?", acceptedAnswer: { "@type": "Answer", text: "From the mobile number registered on the GST portal, send NIL<space>3B<space>GSTIN<space>Tax period (MMYYYY) to 14409. You will receive a 6-digit code; reply CNF<space>3B<space>Code within 30 minutes to file." } },
          { "@type": "Question", name: "What is the late fee for a nil GST return?", acceptedAnswer: { "@type": "Answer", text: "₹20 per day (₹10 CGST + ₹10 SGST) per return, capped at ₹500 per return. There is no interest because no tax is payable." } },
          { "@type": "Question", name: "Can I file a nil return if I bought goods but made no sales?", acceptedAnswer: { "@type": "Answer", text: "Not if you want to claim the input tax credit on those purchases, or if any purchase attracts reverse charge. In those cases you must file a regular GSTR-3B reporting the ITC or RCM liability." } },
          { "@type": "Question", name: "Can a nil return be filed after three years?", acceptedAnswer: { "@type": "Answer", text: "No. GST returns can no longer be filed after three years from their original due date, so pending nil returns should be cleared as early as possible." } },
        ],
      },
    ]);
    return () => { if (script.parentNode) script.parentNode.removeChild(script); };
  }, []);

  return (
    <article className="blog-article">
      <h1>How to File a Nil GST Return Online (and by SMS) in 2026</h1>
      <p className="blog-meta">Updated October 2026 · 8 min read</p>

      <section>
        <p>
          A surprising number of GST-registered businesses have months with no sales at all: a new business
          that registered before starting operations, a seasonal trader in the off-season, or a freelancer
          between projects. GST still expects a return for every one of those months. The good news is that a
          nil return takes under two minutes, and you can file it from your phone by SMS without logging in to
          the GST portal.
        </p>
        <p>
          This guide covers who qualifies for a nil return, how to file nil GSTR-3B and GSTR-1 online and by
          SMS, the late fee if you miss the date, and the mistakes that turn a &quot;nil&quot; month into a notice.
          For returns with actual sales, see our{" "}
          <Link to="/blog/how-to-file-gst-returns-online">complete guide to filing GST returns online</Link>.
        </p>
      </section>

      <section>
        <h2>What Is a Nil GST Return?</h2>
        <p>
          A nil return is a GSTR-3B or GSTR-1 with nothing to report for the tax period. You can file nil
          GSTR-3B only if, for that month or quarter, <strong>all</strong> of the following are true:
        </p>
        <ul>
          <li>No outward supplies — no taxable, exempt, nil-rated or zero-rated sales</li>
          <li>No inward supplies on which you must pay tax under reverse charge</li>
          <li>No input tax credit to claim or reverse</li>
          <li>No tax liability from earlier periods to declare, and no late fee or interest pending</li>
        </ul>
        <p>
          A nil GSTR-1 simply means there are no outward supplies to report, including no credit or debit notes
          and no amendments. Composition taxpayers file a nil CMP-08 on the same principle.
        </p>
        <p>
          If you made even one small sale or bought anything on which you want to claim ITC, it is not a nil
          month. File a regular return instead — our <Link to="/calculator">GST calculator</Link> helps you work
          out the tax on that sale.
        </p>
      </section>

      <section>
        <h2>Method 1: File a Nil Return on the GST Portal</h2>

        <h3>Nil GSTR-1</h3>
        <ol>
          <li>Log in at gst.gov.in and go to <strong>Services → Returns → Returns Dashboard</strong>.</li>
          <li>Select the financial year and tax period, then click <strong>Prepare Online</strong> under GSTR-1.</li>
          <li>Tick the <strong>File Nil GSTR-1</strong> option.</li>
          <li>Click <strong>Generate Summary</strong>, then <strong>File Statement</strong>.</li>
          <li>File with EVC (OTP on your registered mobile) or DSC.</li>
        </ol>

        <h3>Nil GSTR-3B</h3>
        <ol>
          <li>On the same Returns Dashboard, click <strong>Prepare Online</strong> under GSTR-3B.</li>
          <li>Answer the first question, &quot;Do you want to file Nil return?&quot;, with <strong>Yes</strong>.</li>
          <li>Click <strong>Next</strong>; the portal shows a summary with all tables at zero.</li>
          <li>Click <strong>File GSTR-3B with EVC</strong> (or DSC) and enter the OTP.</li>
          <li>Download the filed return and note the ARN for your records.</li>
        </ol>
        <p>
          File GSTR-1 first, then GSTR-3B, as you would in a normal month. The portal may refuse a nil GSTR-3B
          if GSTR-1, IFF or e-invoices show sales for that period — a useful check that you have not missed
          anything.
        </p>
      </section>

      <section>
        <h2>Method 2: File a Nil Return by SMS to 14409</h2>
        <p>
          SMS filing is the fastest option and works from any basic phone. Send the message from the mobile
          number registered with the authorised signatory on the GST portal.
        </p>
        <table>
          <thead>
            <tr><th>Return</th><th>Step 1: send to 14409</th><th>Step 2: confirm with code</th></tr>
          </thead>
          <tbody>
            <tr><td>Nil GSTR-3B</td><td>NIL 3B GSTIN MMYYYY</td><td>CNF 3B Code</td></tr>
            <tr><td>Nil GSTR-1</td><td>NIL R1 GSTIN MMYYYY</td><td>CNF R1 Code</td></tr>
            <tr><td>Nil CMP-08 (composition)</td><td>NIL C8 GSTIN MMYYYY</td><td>CNF C8 Code</td></tr>
          </tbody>
        </table>
        <p>
          For example, a business with GSTIN 07ABCDE1234F1Z5 filing nil GSTR-3B for September 2026 sends{" "}
          <code>NIL 3B 07ABCDE1234F1Z5 092026</code>. The portal replies with a six-digit verification code,
          valid for 30 minutes. Reply <code>CNF 3B 123456</code> (using the code you received) and you will get
          an ARN by SMS once the return is filed. Quarterly (QRMP) filers use the last month of the quarter as the
          tax period, such as <code>092026</code> for July–September.
        </p>
        <p>
          Before your first SMS filing, check that the authorised signatory&apos;s mobile number is correct on the
          portal. If you are not sure your GSTIN is active, verify it with our{" "}
          <Link to="/gstin-validator">GSTIN validator</Link>.
        </p>
      </section>

      <section>
        <h2>Due Dates for Nil Returns</h2>
        <p>
          Nil returns have the same due dates as normal ones: GSTR-1 by the 11th of the following month (13th
          of the month after the quarter for QRMP filers) and GSTR-3B by the 20th (22nd or 24th for QRMP
          filers, depending on your state). See every date for this year in our{" "}
          <Link to="/return-calendar">GST return calendar</Link> or the{" "}
          <Link to="/due-dates">due dates page</Link>.
        </p>
      </section>

      <section>
        <h2>Late Fee for a Missed Nil Return</h2>
        <p>
          Missing a nil return costs ₹20 per day (₹10 CGST + ₹10 SGST) per return, capped at ₹500 per return.
          There is no interest, because there is no tax due. That sounds small, but a business that forgets for
          a year owes the fee on both GSTR-1 and GSTR-3B for every month, and the portal will not let you file a
          later return until earlier ones are filed. Estimate what you owe with our{" "}
          <Link to="/late-fee-calculator">GST late fee calculator</Link>.
        </p>
        <p>
          Two more reasons not to let nil returns pile up: registration can be cancelled for continuous
          non-filing, and returns can no longer be filed once three years have passed from the due date. For
          the full picture, read our <Link to="/blog/gst-penalties-interest-late-filing">guide to GST penalties
          and interest</Link>.
        </p>
      </section>

      <section>
        <h2>Common Nil Return Mistakes</h2>
        <ul>
          <li>
            <strong>Filing nil when you had purchases with ITC.</strong> A nil GSTR-3B claims no ITC. You can
            still claim it in a later month, but only within the time limit, so it is better to file a regular
            return with the credit. See <Link to="/blog/how-to-claim-input-tax-credit-gst">how to claim ITC</Link>.
          </li>
          <li>
            <strong>Forgetting reverse charge.</strong> Paying rent to an unregistered landlord or hiring a goods
            transport agency can create RCM liability even without sales. Check with the{" "}
            <Link to="/rcm-calculator">RCM calculator</Link>.
          </li>
          <li>
            <strong>Filing GSTR-3B nil when GSTR-1 shows sales.</strong> This mismatch triggers a notice. Read{" "}
            <Link to="/blog/gstr-1-vs-gstr-3b-mismatch-how-to-fix">how to fix GSTR-1 vs GSTR-3B mismatches</Link>.
          </li>
          <li>
            <strong>Staying registered when you have stopped trading.</strong> If you do not expect sales again,
            consider applying for cancellation instead of filing nil returns indefinitely.
          </li>
        </ul>
      </section>

      <section>
        <h2>Frequently Asked Questions</h2>

        <h3>Is it mandatory to file a nil GST return?</h3>
        <p>
          Yes. Every regular taxpayer must file GSTR-1 and GSTR-3B for each period, even with no activity.
        </p>

        <h3>Can I file a nil return if I bought goods but made no sales?</h3>
        <p>
          Not if you want to claim ITC on those purchases, or if any purchase attracts reverse charge. File a
          regular GSTR-3B in that case.
        </p>

        <h3>Do I need a CA to file a nil return?</h3>
        <p>
          No. A nil return by SMS or on the portal takes a couple of minutes and needs only your GSTIN and
          registered mobile number.
        </p>

        <h3>What if the SMS code expires?</h3>
        <p>
          The code is valid for 30 minutes. If it expires, simply send the first SMS again to get a new code.
        </p>
      </section>

      <section>
        <h2>Free Tools for GST Filing</h2>
        <ul>
          <li><Link to="/return-calendar">GST Return Calendar</Link> — every due date for FY 2026-27</li>
          <li><Link to="/late-fee-calculator">Late Fee Calculator</Link> — work out fees for missed returns</li>
          <li><Link to="/gstin-validator">GSTIN Validator</Link> — check a GSTIN&apos;s format and status</li>
          <li><Link to="/rcm-calculator">RCM Calculator</Link> — check if you owe reverse charge</li>
          <li><Link to="/calculator">GST Calculator</Link> — tax on any sale</li>
        </ul>
        <p>
          <Link to="/">Start using DoAide GST free →</Link>
        </p>
      </section>
    </article>
  );
}
