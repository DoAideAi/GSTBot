import { useEffect } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";
import SeoHead from "../../components/SeoHead";

export default function HowToClaimItc() {
  usePageTitle("How to Claim Input Tax Credit Under GST");

  useEffect(() => {
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.content = "Learn how to claim Input Tax Credit (ITC) under GST. Eligibility conditions, blocked credits, time limits, reversal rules, and GSTR-2B reconciliation explained.";

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
        headline: "How to Claim Input Tax Credit Under GST",
        description: "Step-by-step guide to claiming ITC under GST — conditions, blocked credits, and reconciliation.",
        url: "https://gst.doaide.com/blog/how-to-claim-input-tax-credit-gst",
        datePublished: "2026-10-07",
        dateModified: "2026-10-07",
        publisher: { "@type": "Organization", name: "DoAide" },
      },
      {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: [
          { "@type": "Question", name: "What is Input Tax Credit (ITC)?", acceptedAnswer: { "@type": "Answer", text: "ITC is the tax paid on purchases that can be set off against output tax liability. It prevents cascading taxes in the supply chain." } },
          { "@type": "Question", name: "What are the conditions to claim ITC?", acceptedAnswer: { "@type": "Answer", text: "You need a valid tax invoice, goods/services received, tax paid by supplier, return filed, and invoice in your GSTR-2B." } },
          { "@type": "Question", name: "What is the time limit for claiming ITC?", acceptedAnswer: { "@type": "Answer", text: "ITC must be claimed by 30th November of the year following the financial year, or the date of filing annual return — whichever is earlier." } },
          { "@type": "Question", name: "Can ITC be claimed on food and beverages?", acceptedAnswer: { "@type": "Answer", text: "No. Food, beverages, outdoor catering, and health/fitness club memberships are blocked credits under Section 17(5)." } },
          { "@type": "Question", name: "What is ITC reversal under Rule 42 and 43?", acceptedAnswer: { "@type": "Answer", text: "When inputs are used partly for taxable and partly for exempt supplies, ITC must be proportionally reversed for the exempt portion." } },
        ],
      },
    ]);
    return () => { script?.remove(); };
  }, []);

  return (
    <article className="blog-article">
      <SeoHead title="How to Claim Input Tax Credit Under GST" description="Step-by-step guide to claiming ITC under GST — eligibility conditions, blocked credits under Section 17(5), documentation needed, and reversal rules." path="/blog/how-to-claim-input-tax-credit-gst" />
      <h1>How to Claim Input Tax Credit Under GST</h1>
      <p className="blog-meta">Updated October 2026 · 11 min read</p>

      <section>
        <h2>What is Input Tax Credit?</h2>
        <p>
          Input Tax Credit (ITC) is the mechanism that allows businesses to reduce their GST output
          liability by the amount of GST already paid on inputs (purchases). It eliminates tax cascading —
          you pay tax only on the value you add, not on the entire sale price. ITC is the backbone of
          GST&apos;s value-added tax structure and can significantly reduce your effective tax cost.
        </p>
      </section>

      <section>
        <h2>Conditions for Claiming ITC (Section 16)</h2>
        <p>All four conditions must be satisfied to claim ITC:</p>
        <ol>
          <li><strong>Possession of tax invoice</strong> — a valid invoice, debit note, or other prescribed document</li>
          <li><strong>Receipt of goods/services</strong> — you must have actually received the supply (or your agent received it on your behalf)</li>
          <li><strong>Tax paid to government</strong> — your supplier must have actually deposited the tax with the government</li>
          <li><strong>Return filed</strong> — you must have filed your GSTR-3B for the period in which ITC is claimed</li>
        </ol>
        <p>
          Additionally, the invoice must appear in your <strong>GSTR-2B</strong>. The system auto-populates
          GSTR-2B from your supplier&apos;s GSTR-1. If a supplier hasn&apos;t filed their GSTR-1, you
          won&apos;t see the invoice in GSTR-2B, and claiming ITC on it becomes risky.
        </p>
      </section>

      <section>
        <h2>Step-by-Step: How to Claim ITC</h2>
        <ol>
          <li>Collect all purchase invoices for the tax period</li>
          <li>Verify each invoice has valid GSTIN, HSN/SAC code, and correct tax amount</li>
          <li>Check your GSTR-2B on the GST portal — only invoices reported by suppliers appear here</li>
          <li>Reconcile your purchase register with GSTR-2B data</li>
          <li>Identify eligible ITC (exclude blocked credits under Section 17(5))</li>
          <li>Report eligible ITC in GSTR-3B Table 4 — split into IGST, CGST, SGST, and Cess</li>
          <li>Set off ITC against output liability in the order: IGST first, then CGST, then SGST</li>
        </ol>
        <p>
          Use our <Link to="/itc-calculator">ITC Eligibility Calculator</Link> to quickly check
          whether a specific purchase qualifies for credit.
        </p>
      </section>

      <section>
        <h2>Blocked Credits — Section 17(5)</h2>
        <p>ITC is <strong>not available</strong> on the following, regardless of business use:</p>
        <ul>
          <li>Motor vehicles and conveyances (except for resale, transport of passengers, driving training)</li>
          <li>Food and beverages, outdoor catering, beauty treatment, health and fitness</li>
          <li>Membership of club, health, or fitness centre</li>
          <li>Rent-a-cab, life insurance, health insurance (unless for employees as per law)</li>
          <li>Travel benefits for employees on vacation (LTC)</li>
          <li>Works contract services for construction of immovable property</li>
          <li>Goods or services used for personal consumption</li>
          <li>Goods lost, stolen, destroyed, written off, or given as free samples</li>
          <li>Tax paid under composition scheme or Section 10</li>
        </ul>
      </section>

      <section>
        <h2>ITC Set-Off Order</h2>
        <p>
          When setting off ITC against output tax, follow the prescribed order mandated by the CGST
          Rules:
        </p>
        <ol>
          <li><strong>IGST credit</strong> → set off against IGST first, then CGST, then SGST</li>
          <li><strong>CGST credit</strong> → set off against CGST first, then IGST (cannot use for SGST)</li>
          <li><strong>SGST credit</strong> → set off against SGST first, then IGST (cannot use for CGST)</li>
        </ol>
        <p>
          The strategy is to use IGST credit fully first, as it can offset all three heads.
          Use our <Link to="/calculator">GST Calculator</Link> to compute your net liability after ITC.
        </p>
      </section>

      <section>
        <h2>Time Limit for Claiming ITC</h2>
        <p>
          You must claim ITC by the <strong>earlier of</strong>:
        </p>
        <ul>
          <li>30th November of the year following the financial year to which the invoice relates, OR</li>
          <li>The date of filing the annual return (GSTR-9) for that year</li>
        </ul>
        <p>
          For example, for an invoice dated 15 August 2025, ITC must be claimed by 30 November 2026
          or the GSTR-9 filing date for FY 2025-26 — whichever is earlier. After this deadline, the
          credit is permanently lost.
        </p>
      </section>

      <section>
        <h2>ITC Reversal — Rules 42 and 43</h2>
        <p>
          If you use inputs for both taxable and exempt supplies, you must reverse ITC proportionally
          for the exempt portion:
        </p>
        <ul>
          <li><strong>Rule 42:</strong> For inputs and input services used partly for taxable, partly for exempt supplies</li>
          <li><strong>Rule 43:</strong> For capital goods used partly for taxable, partly for exempt supplies</li>
        </ul>
        <p>
          ITC must also be reversed if payment is not made to the supplier within 180 days of the
          invoice date (Section 16(2)(d)). The reversed credit is added back to output liability with
          interest. The <Link to="/itc-180-day-rule">180-day ITC reversal calculator</Link> and{" "}
          <Link to="/itc-reversal-rule-42">Rule 42 calculator</Link> work out both amounts, and{" "}
          <Link to="/blog/itc-reversal-rules-37-42-43">this guide</Link> explains each rule with examples.
        </p>
      </section>

      <section>
        <h2>GSTR-2B Reconciliation Tips</h2>
        <ul>
          <li>Download GSTR-2B every month and compare with your purchase register</li>
          <li>Follow up with suppliers whose invoices are missing from GSTR-2B</li>
          <li>Do not claim ITC on invoices not appearing in GSTR-2B — it&apos;s the auto-drafted ITC statement</li>
          <li>Watch for duplicate invoices that might inflate your ITC</li>
          <li>Check the &quot;ineligible&quot; tab in GSTR-2B for credits from non-compliant suppliers</li>
        </ul>
      </section>

      <section>
        <h2>Frequently Asked Questions</h2>
        <dl className="blog-faq">
          <dt>What is Input Tax Credit (ITC)?</dt>
          <dd>Tax paid on purchases that offsets your output tax liability, preventing cascading taxes in the supply chain.</dd>
          <dt>What are the conditions to claim ITC?</dt>
          <dd>Valid invoice, goods received, tax paid by supplier, return filed, and invoice in your GSTR-2B.</dd>
          <dt>What is the time limit for claiming ITC?</dt>
          <dd>30th November of the next financial year, or GSTR-9 filing date — whichever is earlier.</dd>
          <dt>Can ITC be claimed on food and beverages?</dt>
          <dd>No. Food, beverages, outdoor catering, and health/fitness are blocked credits under Section 17(5).</dd>
          <dt>What is ITC reversal under Rules 42 and 43?</dt>
          <dd>Proportional reversal of ITC when inputs serve both taxable and exempt supplies.</dd>
        </dl>
      </section>

      <section className="blog-cta">
        <p>
          <Link to="/">Try DoAide GST free</Link> — check ITC eligibility, reconcile with
          GSTR-2B, and optimise your credit claims. No credit card required.
        </p>
      </section>
    </article>
  );
}
