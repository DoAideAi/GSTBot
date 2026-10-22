import { useEffect } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";

export default function GstRateFinderGuide() {
  usePageTitle("GST Rate Finder: How to Find the Correct GST Rate for Any Product in 2026");

  useEffect(() => {
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.content = "How to find the correct GST rate for any product or service in 2026 — the 0%, 5%, 18% and 40% slabs, finding the HSN or SAC code, checking the rate notification, and a free GST rate finder for Indian businesses.";

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
        headline: "GST Rate Finder: How to Find the Correct GST Rate for Any Product in 2026",
        description: "Find the right GST rate for goods and services in 2026 — the new slab structure, HSN and SAC codes, rate notifications, and common classification mistakes.",
        url: "https://gst.doaide.com/blog/gst-rate-finder-find-gst-rate-for-any-product",
        datePublished: "2026-10-22",
        dateModified: "2026-10-22",
        publisher: { "@type": "Organization", name: "DoAide" },
      },
      {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: [
          { "@type": "Question", name: "What are the GST slabs in 2026?", acceptedAnswer: { "@type": "Answer", text: "Since 22 September 2025 the main slabs are 5%, 18% and 40%. Essentials are exempt or nil-rated, and special rates of 3% on gold and jewellery and 0.25% on rough diamonds continue." } },
          { "@type": "Question", name: "How do I find the GST rate of a product?", acceptedAnswer: { "@type": "Answer", text: "Identify the product's HSN code (or SAC code for a service), then look up the rate notified for that code. A GST rate finder such as DoAide GST lets you search by product name or HSN code and shows the current rate." } },
          { "@type": "Question", name: "How many HSN digits must I show on an invoice?", acceptedAnswer: { "@type": "Answer", text: "Businesses with aggregate turnover up to ₹5 crore must mention at least a 4-digit HSN code on B2B invoices. Businesses above ₹5 crore must mention a 6-digit HSN code on all tax invoices." } },
          { "@type": "Question", name: "What happens if I charge the wrong GST rate?", acceptedAnswer: { "@type": "Answer", text: "If you charge less than the correct rate you must pay the shortfall from your own pocket with 18% interest, and may face a penalty. If you charge more, the excess collected must still be deposited with the government." } },
          { "@type": "Question", name: "Is the GST rate the same across all states?", acceptedAnswer: { "@type": "Answer", text: "Yes. The rate is set by the GST Council and is the same nationwide. Only the split differs: intra-state sales are taxed as CGST plus SGST (half each), and inter-state sales as IGST at the full rate." } },
        ],
      },
    ]);
    return () => { if (script.parentNode) script.parentNode.removeChild(script); };
  }, []);

  return (
    <article className="blog-article">
      <h1>GST Rate Finder: How to Find the Correct GST Rate for Any Product in 2026</h1>
      <p className="blog-meta">Updated October 2026 · 9 min read</p>

      <section>
        <p>
          &quot;What is the GST rate on this?&quot; is the most common question an Indian business owner asks,
          and since the GST rate overhaul of September 2025 it has become even more common. Many items moved
          from 12% to 5%, most 28% items moved to 18%, and a new 40% slab was created for luxury and sin
          goods. If your billing software or price list still uses old rates, you are either over-charging
          customers or under-paying tax, and both cause trouble.
        </p>
        <p>
          This guide explains how GST rates are decided, the step-by-step method to find the correct rate for
          any product or service, and the mistakes that lead to wrong rates on invoices. If you just want the
          answer for one item, search it in our free <Link to="/hsn">GST rate and HSN code finder</Link>.
        </p>
      </section>

      <section>
        <h2>The GST Rate Structure in 2026</h2>
        <p>
          From 22 September 2025, the GST Council replaced the old four-slab structure (5%, 12%, 18%, 28%)
          with a simpler one. Here is how rates look for FY 2026-27:
        </p>
        <table>
          <thead>
            <tr><th>Rate</th><th>What it covers</th><th>Typical examples</th></tr>
          </thead>
          <tbody>
            <tr><td>Nil / exempt</td><td>Unprocessed essentials and some services</td><td>Fresh fruit and vegetables, fresh milk, curd, unbranded atta, individual life and health insurance</td></tr>
            <tr><td>5%</td><td>Merit rate for everyday goods</td><td>Packaged food staples, soap, toothpaste, hair oil, most medicines, restaurant service (without ITC)</td></tr>
            <tr><td>18%</td><td>Standard rate for most goods and services</td><td>Electronics, cement, small cars, two-wheelers up to 350cc, most professional and IT services</td></tr>
            <tr><td>40%</td><td>Luxury and sin goods</td><td>Aerated and caffeinated drinks, large cars and bikes above 350cc, tobacco products</td></tr>
            <tr><td>3% / 0.25%</td><td>Special rates</td><td>Gold, silver and jewellery (3%); rough diamonds (0.25%)</td></tr>
          </tbody>
        </table>
        <p>
          The examples are indicative. The rate that applies to your item depends on its exact HSN code and
          description in the rate notification, so never rely on the category alone. Compare old and new rates
          for any item with our <Link to="/rate-comparison">GST rate comparison tool</Link>.
        </p>
      </section>

      <section>
        <h2>How to Find the GST Rate for a Product: 5 Steps</h2>

        <h3>Step 1: Describe the product precisely</h3>
        <p>
          Rates depend on details. &quot;Biscuits&quot; and &quot;chocolate-coated biscuits&quot; can fall under
          different entries, as can &quot;paneer&quot; and &quot;processed cheese&quot;. Write down what the item is
          made of, whether it is packaged and labelled, and what it is used for.
        </p>

        <h3>Step 2: Find the HSN code (goods) or SAC code (services)</h3>
        <p>
          Every product is classified under the Harmonised System of Nomenclature (HSN). The first two digits
          give the chapter (for example, chapter 30 is pharmaceutical products), and each further pair of digits
          narrows it down. Services use a Services Accounting Code (SAC) beginning with 99. Search by product
          name in the <Link to="/hsn-sac-finder">HSN/SAC finder</Link>, or read our{" "}
          <Link to="/blog/hsn-code-list-2026-complete-guide">HSN code list guide</Link> to understand how
          chapters and headings work.
        </p>

        <h3>Step 3: Check the rate for that exact code</h3>
        <p>
          Once you have the code, look up the rate notified against it. Our{" "}
          <Link to="/hsn">HSN finder</Link> shows the current rate for each code, and each code has its own page
          (for example <Link to="/hsn/3004">HSN 3004 — medicines</Link>) with the description and rate. For a
          specific product you can also open a page like <Link to="/gst-rate/mobile-phone">GST rate on mobile
          phones</Link>.
        </p>

        <h3>Step 4: Check conditions and exceptions</h3>
        <p>
          Some entries carry conditions: the 5% rate on restaurant service comes without input tax credit;
          certain textiles and footwear are taxed by price band; some items are rated differently when sold
          loose versus pre-packaged and labelled. Read the full entry, not just the rate column.
        </p>

        <h3>Step 5: Apply the right tax type</h3>
        <p>
          The rate is the same across India, but the split depends on where the buyer is. Within your state you
          charge CGST and SGST at half the rate each; to another state you charge IGST at the full rate. Use the{" "}
          <Link to="/place-of-supply">place of supply tool</Link> if you are unsure, then the{" "}
          <Link to="/calculator">GST calculator</Link> to work out the tax amount.
        </p>
      </section>

      <section>
        <h2>Finding GST Rates for Services</h2>
        <p>
          Services follow the same logic using SAC codes. Most professional, IT, consulting, repair and
          marketing services are at 18%. Notable exceptions include restaurant service (5% without ITC), hotel
          rooms up to ₹7,500 per night (5%), passenger transport by non-AC bus or economy air travel (5%), and
          exempt services such as healthcare by clinical establishments and most education. For a full
          list, see our <Link to="/blog/gst-rates-services-2026">GST rates for services guide</Link>.
        </p>
      </section>

      <section>
        <h2>How Many HSN Digits to Show on Your Invoice</h2>
        <table>
          <thead>
            <tr><th>Aggregate turnover (previous FY)</th><th>HSN digits required</th></tr>
          </thead>
          <tbody>
            <tr><td>Up to ₹5 crore</td><td>4 digits on B2B invoices (optional on B2C)</td></tr>
            <tr><td>Above ₹5 crore</td><td>6 digits on all tax invoices</td></tr>
          </tbody>
        </table>
        <p>
          The same HSN codes must appear in the HSN summary of your GSTR-1, so getting them right at the invoice
          stage saves work at filing time. Our <Link to="/invoice-generator">free GST invoice generator</Link>{" "}
          adds the HSN code and rate to each line for you.
        </p>
      </section>

      <section>
        <h2>Common GST Rate Mistakes</h2>
        <ul>
          <li>
            <strong>Using pre-September 2025 rates.</strong> Old billing templates still showing 12% or 28% are
            the most common error in 2026. Run your product list through the{" "}
            <Link to="/migration-checker">GST 2.0 migration checker</Link>.
          </li>
          <li>
            <strong>Picking a code by name match alone.</strong> Two products with similar names can sit in
            different chapters. Check the description, not just the keyword.
          </li>
          <li>
            <strong>Copying a supplier&apos;s rate blindly.</strong> Your supplier may be wrong too. If the rate on
            a purchase invoice looks odd, verify it before you claim ITC on it.
          </li>
          <li>
            <strong>Ignoring composite supplies.</strong> When goods and services are sold together, the rate of
            the principal supply usually applies to the whole bundle.
          </li>
          <li>
            <strong>Charging GST on exempt items.</strong> Tax wrongly collected still has to be paid to the
            government, and it annoys customers.
          </li>
        </ul>
        <p>
          A wrong rate on an invoice cannot simply be ignored. If you under-charged, you owe the difference with
          interest; if you over-charged, issue a credit note. Check the cost of fixing late payments with our{" "}
          <Link to="/interest-calculator">GST interest calculator</Link>.
        </p>
      </section>

      <section>
        <h2>When to Ask for an Official Answer</h2>
        <p>
          For most products a careful HSN search settles the rate. If classification is genuinely unclear and
          the amount is significant, you can apply for an Advance Ruling from your state&apos;s Authority for
          Advance Ruling, which binds you and the tax department. A chartered accountant can help you frame the
          question.
        </p>
      </section>

      <section>
        <h2>Frequently Asked Questions</h2>

        <h3>What are the GST slabs in 2026?</h3>
        <p>
          The main slabs are 5%, 18% and 40%, with essentials exempt or nil-rated, and special rates of 3% for
          gold, silver and jewellery and 0.25% for rough diamonds.
        </p>

        <h3>How do I find the GST rate of a product?</h3>
        <p>
          Find its HSN code (or SAC code for a service) and look up the rate notified for that code. Search by
          product name or code in our <Link to="/hsn">GST rate finder</Link>.
        </p>

        <h3>Is the GST rate the same across all states?</h3>
        <p>
          Yes. Only the split changes: CGST plus SGST for sales within your state, IGST for sales to another
          state.
        </p>

        <h3>What happens if I charge the wrong GST rate?</h3>
        <p>
          If you charged too little, you pay the shortfall yourself with 18% interest and may face a penalty. If
          you charged too much, the excess must still be deposited, or refunded to the buyer via a credit note.
        </p>
      </section>

      <section>
        <h2>Free GST Rate Tools</h2>
        <ul>
          <li><Link to="/hsn">GST Rate &amp; HSN Finder</Link> — search any product by name or code</li>
          <li><Link to="/hsn-sac-finder">HSN/SAC Finder</Link> — codes for goods and services</li>
          <li><Link to="/rate-comparison">GST Rate Comparison</Link> — old vs new rates after GST 2.0</li>
          <li><Link to="/migration-checker">GST 2.0 Migration Checker</Link> — check your product list for outdated rates</li>
          <li><Link to="/calculator">GST Calculator</Link> — add or remove GST from any amount</li>
          <li><Link to="/invoice-generator">GST Invoice Generator</Link> — create invoices with the right HSN and rate</li>
        </ul>
        <p>
          <Link to="/">Start using DoAide GST free →</Link>
        </p>
      </section>
    </article>
  );
}
