import { useEffect } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";

const TITLE = "ITC Reversal Under GST: Rule 37, 42 and 43 Explained With Examples";

const FAQ = [
  ["What is ITC reversal under GST?", "Paying back input tax credit already taken, by reporting it in Table 4(B) of GSTR-3B. Some reversals are permanent, such as Rule 42 and 43. Others, such as Rule 37, are re-claimed later."],
  ["What is the difference between Table 4(B)(1) and 4(B)(2)?", "4(B)(1) holds permanent reversals: Rules 38, 42 and 43 and section 17(5). 4(B)(2) holds reversals you may re-claim later, such as Rule 37 for unpaid suppliers."],
  ["Is interest payable on ITC reversal?", "Only when the credit was wrongly availed and also used to pay tax. Section 50(3) then charges 18% a year from the date of use to the date of reversal."],
  ["Does Rule 42 apply if I make only exports?", "No. Exports are zero-rated, which counts as taxable for Rule 42. Credit used for exports is T4 and kept in full."],
];

export default function ItcReversalRules() {
  usePageTitle(TITLE);

  useEffect(() => {
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.content = "When GST input tax credit has to be reversed: Rule 37 for unpaid suppliers, Rule 42 for common inputs, Rule 43 for capital goods. Worked examples, GSTR-3B tables and interest.";

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
        description: "Rule 37, Rule 42 and Rule 43 ITC reversals under GST, with worked examples, where each goes in GSTR-3B and when interest applies.",
        url: "https://gst.doaide.com/blog/itc-reversal-rules-37-42-43",
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
      <p className="blog-meta">Updated October 2026 · 9 min read</p>

      <section>
        <p>
          Claiming input tax credit is only half the job. The CGST Rules also say when credit
          already taken has to be given back, and GST notices often start with a reversal that
          never happened. The three rules small businesses meet most are Rule 37, Rule 42 and
          Rule 43.
        </p>
      </section>

      <section>
        <h2>Rule 37: supplier not paid within 180 days</h2>
        <p>
          If you have not paid a supplier, value plus tax, within 180 days of the invoice date, the
          credit on the unpaid part has to be reversed. It goes in the GSTR-3B for the period after
          the one in which day 180 falls, in Table 4(B)(2).
        </p>
        <p>
          <strong>Example:</strong> an invoice dated 10 January 2026 for ₹1,18,000 (₹18,000 GST),
          half paid. Day 180 is 9 July 2026, so ₹9,000 is reversed in the August 2026 return, due
          20 September. Once you pay the balance, you re-claim the ₹9,000. The section 16(4) time
          limit does not apply to that re-claim.
        </p>
        <p>
          Work out any invoice with the <Link to="/itc-180-day-rule">180-day ITC reversal calculator</Link>.
        </p>
      </section>

      <section>
        <h2>Rule 42: common inputs for taxable and exempt supplies</h2>
        <p>
          A business that makes both taxable and exempt supplies cannot keep all the credit on
          shared inputs, such as rent, audit fees and software. Rule 42 sets the exempt share by
          turnover:
        </p>
        <ul>
          <li><strong>C2</strong>, the common credit, is what is left after removing exclusively non-business, exempt, blocked and taxable credit.</li>
          <li><strong>D1</strong> = exempt turnover ÷ total turnover × C2 is reversed.</li>
          <li><strong>D2</strong> = 5% of C2 is also reversed if common inputs serve non-business use too.</li>
        </ul>
        <p>
          <strong>Example:</strong> common credit of ₹50,000 in a month with ₹20 lakh exempt out of
          ₹1 crore turnover. D1 = 20% × 50,000 = ₹10,000, reported in Table 4(B)(1). After 31
          March, the whole year is recalculated on annual turnover. A shortfall is paid with
          interest by the September return, and an excess is claimed back.
        </p>
        <p>
          The <Link to="/itc-reversal-rule-42">Rule 42 ITC reversal calculator</Link> shows every
          step from C1 to C3.
        </p>
      </section>

      <section>
        <h2>Rule 43: common capital goods</h2>
        <p>
          Capital goods used for both taxable and exempt supplies follow the same idea, spread over
          a five-year life. The credit on each asset is divided into 60 monthly parts. Each month,
          the exempt-turnover share of that month&apos;s part is reversed. Capital goods used only
          for exempt supplies get no credit at all, and those used only for taxable supplies keep
          it in full.
        </p>
      </section>

      <section>
        <h2>The other reversals worth knowing</h2>
        <ul>
          <li><strong>Section 17(5) blocked credit</strong>, such as most motor vehicles, food and personal-use items. Never claimable, so reverse it if it was claimed. Check with the <Link to="/input-tax-credit">ITC eligibility checker</Link>.</li>
          <li><strong>Credit notes from suppliers</strong> reduce the credit you can keep on the original invoice.</li>
          <li><strong>Switching to composition</strong> or exempt-only supplies requires reversing credit on stock and capital goods held that day.</li>
        </ul>
      </section>

      <section>
        <h2>Interest on reversals</h2>
        <p>
          Section 50(3) charges 18% a year only on credit that was wrongly availed <em>and</em>{" "}
          utilised, from the date of use to the date of reversal. If your electronic credit ledger
          never fell below the amount, no interest arises. The{" "}
          <Link to="/interest-calculator">GST interest calculator</Link> handles the day count.
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
