import { useEffect } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";

export default function ItcRules2026() {
  usePageTitle("Input Tax Credit (ITC) Rules 2026: What Every Business Must Know");

  useEffect(() => {
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.content = "Complete guide to Input Tax Credit (ITC) rules in 2026. Eligibility conditions under Section 16, blocked credits under Section 17(5), time limits, reversal rules, GSTR-2B matching, and ITC on capital goods.";

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
        headline: "Input Tax Credit (ITC) Rules 2026: What Every Business Must Know",
        description: "Complete guide to ITC rules in 2026 — eligibility under Section 16, blocked credits under Section 17(5), time limits, reversal rules, GSTR-2B matching, and best practices.",
        url: "https://gst.doaide.com/blog/itc-rules-2026-what-every-business-must-know",
        datePublished: "2026-10-10",
        dateModified: "2026-10-10",
        publisher: { "@type": "Organization", name: "DoAide" },
      },
      {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: [
          { "@type": "Question", name: "What is the time limit for claiming ITC under GST?", acceptedAnswer: { "@type": "Answer", text: "Claim ITC by the due date of filing the return for September of the following financial year, or the date of filing GSTR-9, whichever is earlier." } },
          { "@type": "Question", name: "Can I claim ITC on food and beverages?", acceptedAnswer: { "@type": "Answer", text: "No. ITC on food and beverages, outdoor catering, beauty treatment, and health services is blocked under Section 17(5) unless you supply those same services." } },
          { "@type": "Question", name: "What happens if I claim ITC that is not in GSTR-2B?", acceptedAnswer: { "@type": "Answer", text: "ITC is restricted to amounts in GSTR-2B plus 5% provisional credit. Excess claims trigger a DRC-01C notice requiring reversal or explanation." } },
          { "@type": "Question", name: "Is ITC available under the Composition Scheme?", acceptedAnswer: { "@type": "Answer", text: "No. Businesses registered under the Composition Scheme cannot claim ITC on any purchases. They also cannot issue tax invoices. If ITC is important for your business, consider switching to the regular scheme." } },
          { "@type": "Question", name: "Can I claim ITC on capital goods?", acceptedAnswer: { "@type": "Answer", text: "Yes. Full ITC on capital goods can be claimed in the month of purchase if the goods are received and the invoice appears in GSTR-2B." } },
          { "@type": "Question", name: "When must ITC be reversed under GST?", acceptedAnswer: { "@type": "Answer", text: "Reverse ITC when payment is not made within 180 days, goods are used for exempt supplies, capital goods are sold, or goods are lost, stolen, or destroyed." } },
        ],
      },
    ]);
    return () => { if (script.parentNode) script.parentNode.removeChild(script); };
  }, []);

  return (
    <article className="blog-article">
      <h1>Input Tax Credit (ITC) Rules 2026: What Every Business Must Know</h1>
      <p className="blog-meta">Updated October 2026 · 15 min read</p>

      <section>
        <p>
          Input Tax Credit (ITC) is one of the most significant benefits of the GST system. It allows businesses
          to reduce their tax liability by claiming credit for the GST already paid on purchases of goods and
          services used for business purposes. However, ITC rules are complex — there are strict eligibility
          conditions, a long list of blocked credits, time limits, and reversal requirements that every business
          must understand to avoid losing legitimate credits or facing penalties for wrong claims.
        </p>
        <p>
          This comprehensive guide covers all ITC rules applicable in 2026, including recent changes. For a
          step-by-step claiming process, also read our{" "}
          <Link to="/blog/how-to-claim-input-tax-credit-gst">How to Claim ITC guide</Link>.
        </p>
      </section>

      <section>
        <h2>What Is Input Tax Credit (ITC)?</h2>
        <p>
          Input Tax Credit is the credit a registered business receives for the GST paid on purchases (inputs)
          that are used in the course of business. When you buy raw materials, services, or capital goods for
          your business and pay GST on them, you can set off this tax against the GST you collect on your sales
          (output tax). You only need to pay the difference to the government.
        </p>
        <p>
          <strong>Example:</strong> You buy goods worth ₹1,00,000 and pay 18% GST = ₹18,000. You sell goods
          worth ₹1,50,000 and collect 18% GST = ₹27,000. Your net tax liability = ₹27,000 − ₹18,000 = ₹9,000.
          The ₹18,000 is your Input Tax Credit. Use our{" "}
          <Link to="/itc-calculator">ITC Calculator</Link> to compute your eligible credit.
        </p>
      </section>

      <section>
        <h2>Eligibility Conditions for Claiming ITC (Section 16)</h2>
        <p>
          Section 16 of the CGST Act lays down four mandatory conditions that must all be satisfied to claim ITC:
        </p>
        <ol>
          <li>
            <strong>Possession of a valid tax invoice or debit note:</strong> You must hold a tax invoice issued
            by the supplier containing the supplier&apos;s GSTIN, invoice number, date, HSN/SAC code, taxable
            value, and tax amount breakup. Without a valid invoice, ITC cannot be claimed
          </li>
          <li>
            <strong>Receipt of goods or services:</strong> The goods must be physically received by you (or
            delivered to a third party on your direction). For services, the service must be provided to you.
            ITC on goods in transit or services not yet rendered cannot be claimed
          </li>
          <li>
            <strong>Tax has been paid to the government:</strong> The supplier must have actually deposited the
            tax with the government. If the supplier collects GST from you but defaults on payment, your ITC
            can be reversed. This is verified through GSTR-2B matching
          </li>
          <li>
            <strong>Return filed by the recipient:</strong> You must have filed your GSTR-3B for the tax period
            in which you are claiming the credit. ITC is claimed through Table 4 of GSTR-3B
          </li>
        </ol>
        <p>
          Additionally, ITC must reflect in your GSTR-2B. The credit available is limited to the amount shown
          in GSTR-2B plus 5% provisional credit. Reconcile every month with our{" "}
          <Link to="/gstr2b-reconciliation">GSTR-2B Reconciliation</Link> tool.
        </p>
      </section>

      <section>
        <h2>Blocked Credits Under Section 17(5) — What You Cannot Claim</h2>
        <p>
          Section 17(5) of the CGST Act lists specific goods and services on which ITC is permanently blocked,
          regardless of whether they are used for business purposes. Check your eligibility with our{" "}
          <Link to="/input-tax-credit">ITC Eligibility Checker</Link>.
        </p>

        <h3>Complete List of Blocked ITC Items</h3>
        <ol>
          <li>
            <strong>Motor vehicles and conveyances:</strong> ITC on purchase, lease, or hire of motor vehicles
            is blocked. <em>Exceptions:</em> vehicles used for transportation of goods, passenger transport
            (bus, taxi service), driving training, or vehicles for further supply (dealers)
          </li>
          <li>
            <strong>Food and beverages, outdoor catering:</strong> All ITC blocked unless you are in the
            business of supplying such services or it forms part of a taxable composite/mixed supply
          </li>
          <li>
            <strong>Beauty treatment, health services, cosmetic and plastic surgery:</strong> Completely
            blocked unless provided as part of your business output
          </li>
          <li>
            <strong>Club or fitness centre membership:</strong> Gym, club, or sports facility memberships
            are blocked regardless of business purpose
          </li>
          <li>
            <strong>Rent-a-cab, life insurance, health insurance:</strong> Blocked except when provided to
            employees and mandated by law (e.g., accident insurance for factory workers under the Factories Act)
          </li>
          <li>
            <strong>Travel benefits to employees (LTC/LTA):</strong> ITC on leave or home travel concession
            is blocked
          </li>
          <li>
            <strong>Works contract services for construction of immovable property:</strong> Blocked when
            used for self-construction (not for further supply). ITC is available if you are a builder or
            developer constructing for sale
          </li>
          <li>
            <strong>Construction of immovable property on own account:</strong> ITC on materials and services
            used for building your own office, warehouse, or factory is blocked. Plant and machinery is
            the exception — ITC is available on plant and machinery
          </li>
          <li>
            <strong>Goods or services used for personal consumption:</strong> Any purchase used for personal
            (non-business) purposes is ineligible for ITC
          </li>
          <li>
            <strong>Goods lost, stolen, destroyed, or disposed of by way of gift/free samples:</strong> ITC
            previously claimed on such goods must be reversed
          </li>
          <li>
            <strong>Tax paid under Section 74 (fraud/suppression):</strong> Any tax paid on account of fraud,
            suppression, or misstatement cannot be claimed as ITC
          </li>
        </ol>
      </section>

      <section>
        <h2>Time Limit for Claiming ITC</h2>
        <p>
          ITC is not available indefinitely. You must claim it within the following deadline:
        </p>
        <ul>
          <li>
            <strong>Deadline:</strong> The earlier of the due date of filing GSTR-3B for September of the
            following financial year, or the date of filing the annual return (GSTR-9)
          </li>
          <li>
            <strong>Example:</strong> For purchases made in FY 2025-26, ITC must be claimed by November 30,
            2026 (in a GSTR-3B filed by then, in practice the October 2026 return) or the date you file GSTR-9
            for FY 2025-26, whichever comes first. Check any invoice with the{" "}
            <Link to="/itc-time-limit">ITC time limit checker</Link>
          </li>
          <li>
            <strong>Section 16(4) amendment:</strong> The Finance Act 2022 amendment allows ITC to be claimed until
            November 30th of the year following the financial year, giving businesses additional time
          </li>
        </ul>
        <p>
          Missing this deadline means losing the ITC permanently. There is no mechanism to claim ITC for a
          past period once the deadline has passed. Track all deadlines on our{" "}
          <Link to="/return-calendar">Return Calendar</Link>.
        </p>
      </section>

      <section>
        <h2>ITC Reversal Rules (Rule 42 and Rule 43)</h2>
        <p>
          When goods or services are used partly for business and partly for non-business purposes, or partly
          for taxable and partly for exempt supplies, ITC must be proportionately reversed.
        </p>

        <h3>Rule 42: Reversal for Inputs and Input Services</h3>
        <p>
          When common inputs or input services are used for both taxable and exempt supplies, ITC must be
          apportioned. The formula:
        </p>
        <ul>
          <li><strong>Common credit (C):</strong> Total ITC on inputs/services used for both taxable and exempt supplies</li>
          <li><strong>Exempt turnover ratio (D1):</strong> (Exempt turnover ÷ Total turnover) × Common credit</li>
          <li><strong>Amount to reverse:</strong> D1 must be added back to output tax liability</li>
          <li><strong>Eligible credit:</strong> C − D1 = ITC you can retain</li>
        </ul>
        <p>This calculation must be done every month, with an annual adjustment in the return for September.</p>

        <h3>Rule 43: Reversal for Capital Goods</h3>
        <p>
          For capital goods used for both taxable and exempt supplies, ITC must be spread over 60 months
          (5 years) and reversed proportionately each month based on the exempt-to-total turnover ratio.
          When capital goods are sold or written off, the remaining ITC must be reversed based on the
          useful life consumed.
        </p>
      </section>

      <section>
        <h2>GSTR-2B Matching and ITC Restriction</h2>
        <p>
          Since 2022, ITC claims in GSTR-3B are tightly linked to GSTR-2B. Here is how the matching works:
        </p>
        <ul>
          <li><strong>GSTR-2B is auto-generated:</strong> It is a static statement generated on the 14th of each month based on the supplier&apos;s GSTR-1, GSTR-5, and GSTR-6</li>
          <li><strong>ITC cap:</strong> You can claim ITC only up to the amount reflected in GSTR-2B plus 5% of the eligible ITC in GSTR-2B</li>
          <li><strong>Missing invoices:</strong> If a supplier has not filed GSTR-1, their invoices won&apos;t appear in your GSTR-2B, and you cannot claim ITC on those purchases</li>
          <li><strong>DRC-01C notice:</strong> If your ITC claim exceeds the GSTR-2B limit, the system auto-generates a notice asking for reversal or explanation</li>
        </ul>
        <p>
          Use our <Link to="/gstr2b-reconciliation">GSTR-2B Reconciliation</Link> tool every month before
          filing GSTR-3B. Also read our detailed <Link to="/blog/itc-reconciliation-gstr-2a-guide">ITC
          Reconciliation Guide</Link>.
        </p>
      </section>

      <section>
        <h2>ITC on Capital Goods</h2>
        <p>
          Capital goods under GST include plant, machinery, equipment, and other fixed assets used for business.
          Key rules for capital goods ITC:
        </p>
        <ul>
          <li><strong>Full credit in one go:</strong> Unlike the earlier regime, GST allows you to claim the entire ITC on capital goods in the month of receipt (no 50% restriction)</li>
          <li><strong>GSTR-2B condition:</strong> The supplier&apos;s invoice must appear in your GSTR-2B</li>
          <li><strong>Mixed use:</strong> If capital goods are used for both taxable and exempt supplies, ITC must be apportioned under Rule 43 (see above)</li>
          <li><strong>Sale of capital goods:</strong> If you sell capital goods, you must pay GST on the higher of the transaction value or the ITC remaining on the goods (calculated on a 5-year straight-line basis). The remaining ITC attributable to the useful life left must be reversed</li>
          <li><strong>Exclusion:</strong> &quot;Plant and machinery&quot; does not include land, buildings, or civil structures (except for telecommunication towers, pipelines, and equipment fixed to earth by foundation). ITC on construction of buildings remains blocked</li>
        </ul>
      </section>

      <section>
        <h2>Situations Where ITC Must Be Reversed</h2>
        <p>ITC already claimed must be reversed (paid back) in these situations:</p>
        <ol>
          <li><strong>Non-payment to supplier within 180 days:</strong> If you do not pay the supplier (including GST) within 180 days of the invoice date, the ITC must be reversed. It can be re-claimed when payment is made. Use the <Link to="/itc-180-day-rule">180-day ITC reversal calculator</Link></li>
          <li><strong>Goods used for exempt supplies:</strong> Proportionate reversal under Rule 42, worked out by the <Link to="/itc-reversal-rule-42">Rule 42 calculator</Link></li>
          <li><strong>Goods lost, stolen, destroyed, or written off:</strong> Full ITC reversal required</li>
          <li><strong>Goods given as free samples or gifts:</strong> ITC must be reversed</li>
          <li><strong>Capital goods sold:</strong> Reversal based on remaining useful life (Rule 43)</li>
          <li><strong>Recipient fails to file returns:</strong> If GSTR-3B is not filed for a consecutive period, ITC may be restricted until returns are filed</li>
          <li><strong>Supplier defaults on tax payment:</strong> If the supplier does not deposit the GST collected from you, your ITC may be reversed after the department issues a notice</li>
        </ol>
      </section>

      <section>
        <h2>ITC Set-Off Order Under GST</h2>
        <p>
          When setting off ITC against output tax liability, the following order must be followed:
        </p>
        <ol>
          <li><strong>IGST credit:</strong> First set off against IGST liability, then against CGST, then against SGST</li>
          <li><strong>CGST credit:</strong> Set off against CGST liability first, then against IGST (cannot be set off against SGST)</li>
          <li><strong>SGST credit:</strong> Set off against SGST liability first, then against IGST (cannot be set off against CGST)</li>
        </ol>
        <p>
          This order is automatically applied by the GST portal when you file GSTR-3B. Use our{" "}
          <Link to="/calculator">GST Calculator</Link> to estimate your net liability after ITC set-off.
        </p>
      </section>

      <section>
        <h2>Key ITC Changes in 2026</h2>
        <ul>
          <li><strong>Stricter GSTR-2B matching:</strong> The 5% provisional ITC tolerance continues, but the department has increased automated scrutiny of mismatches</li>
          <li><strong>ISD mandatory for multi-location businesses:</strong> Input Service Distributor registration is now mandatory for distributing ITC across branches</li>
          <li><strong>Enhanced DRC-01C notices:</strong> The system now issues notices for any ITC discrepancy above ₹25,000, down from the earlier ₹50,000 threshold</li>
          <li><strong>E-invoice linkage:</strong> ITC on B2B purchases above ₹5 crore turnover threshold is linked to valid e-invoice IRN numbers</li>
          <li><strong>Interest on wrong ITC:</strong> Interest rate remains at 24% per annum for wrongly availed and utilized ITC, vs 18% for other tax defaults</li>
        </ul>
      </section>

      <section>
        <h2>ITC Best Practices for Businesses</h2>
        <ul>
          <li><strong>Reconcile GSTR-2B every month:</strong> Before filing GSTR-3B, match your purchase register with GSTR-2B using our <Link to="/gstr2b-reconciliation">GSTR-2B Reconciliation</Link> tool</li>
          <li><strong>Follow up with suppliers:</strong> If invoices are missing from GSTR-2B, contact your suppliers immediately — they may have missed filing GSTR-1</li>
          <li><strong>Maintain blocked credit checklist:</strong> Keep a reference list of Section 17(5) items and check every ITC claim against it — use our <Link to="/input-tax-credit">ITC Eligibility Checker</Link></li>
          <li><strong>Track 180-day payment rule:</strong> Set alerts for invoices approaching the 180-day payment deadline to avoid automatic ITC reversal</li>
          <li><strong>Claim within the time limit:</strong> Do not let ITC accumulate beyond a financial year — claim it before the September return deadline of the following year</li>
          <li><strong>Maintain proper documentation:</strong> Keep all tax invoices, debit notes, and payment proofs for at least 72 months for audit purposes</li>
          <li><strong>Consider scheme comparison:</strong> If your ITC claims are minimal, the <Link to="/scheme-comparison">Composition Scheme</Link> (no ITC but lower compliance) might suit your business better</li>
        </ul>
      </section>

      <section>
        <h2>Frequently Asked Questions</h2>

        <h3>What is the time limit for claiming ITC under GST?</h3>
        <p>
          ITC must be claimed by the earlier of: the due date of filing GSTR-3B for September of the following
          financial year, or the date of filing the annual return (GSTR-9). For FY 2026-27 purchases, the
          deadline is November 30, 2027 (September 2027 GSTR-3B) or the GSTR-9 filing date, whichever is earlier.
        </p>

        <h3>Can I claim ITC on food and beverages?</h3>
        <p>
          No. ITC on food and beverages, outdoor catering, beauty treatment, health services, cosmetic and
          plastic surgery is blocked under Section 17(5). The only exception is when you are in the business
          of providing such services or they form part of a taxable composite/mixed supply.
        </p>

        <h3>What happens if I claim ITC that is not in GSTR-2B?</h3>
        <p>
          Your claim is restricted to GSTR-2B amounts plus 5%. Excess claims trigger a DRC-01C notice requiring
          reversal or explanation. Persistent over-claims increase the risk of departmental audit.
        </p>

        <h3>Is ITC available under the Composition Scheme?</h3>
        <p>
          No. Composition Scheme dealers cannot claim ITC on any purchases. They also cannot issue tax invoices.
          If ITC is critical for your business, the regular scheme is more beneficial despite higher compliance.
          Compare both with our <Link to="/scheme-comparison">Scheme Comparison</Link> tool.
        </p>

        <h3>Can I claim ITC on capital goods?</h3>
        <p>
          Yes. Full ITC on capital goods (plant, machinery, equipment) can be claimed in the month of receipt.
          For mixed-use capital goods, ITC must be proportionately apportioned under Rule 43. When selling
          capital goods, the remaining ITC based on useful life must be reversed.
        </p>

        <h3>When must ITC be reversed under GST?</h3>
        <p>
          ITC must be reversed when: payment is not made to the supplier within 180 days, goods/services
          are used for exempt supplies, goods are lost/stolen/destroyed/gifted, capital goods are sold or
          written off, or the supplier defaults on tax payment. Use our{" "}
          <Link to="/itc-mismatch">ITC Mismatch Resolver</Link> for guidance on reversals.
        </p>
      </section>

      <section>
        <h2>Free ITC Tools for Your Business</h2>
        <p>Manage your Input Tax Credit efficiently with these DoAide GST tools:</p>
        <ul>
          <li><Link to="/input-tax-credit">ITC Eligibility Checker</Link> — verify if a specific expense qualifies for ITC</li>
          <li><Link to="/itc-calculator">ITC Calculator</Link> — compute eligible ITC amounts</li>
          <li><Link to="/itc-mismatch">ITC Mismatch Resolver</Link> — identify and fix ITC discrepancies</li>
          <li><Link to="/gstr2b-reconciliation">GSTR-2B Reconciliation</Link> — match purchase data with GSTR-2B</li>
          <li><Link to="/calculator">GST Calculator</Link> — calculate GST and net liability</li>
          <li><Link to="/reverse-charge">Reverse Charge Calculator</Link> — check RCM applicability and ITC</li>
          <li><Link to="/return-calendar">Return Calendar</Link> — track ITC claim deadlines</li>
          <li><Link to="/scheme-comparison">Scheme Comparison</Link> — compare Regular (ITC) vs Composition (no ITC)</li>
        </ul>
        <p>
          <Link to="/">Start using DoAide GST free →</Link>
        </p>
      </section>
    </article>
  );
}
