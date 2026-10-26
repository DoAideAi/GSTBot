import { useEffect } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";

export default function GstInvoiceFormatGuide2026() {
  usePageTitle("GST Invoice Format Guide 2026: Mandatory Fields, Rules & Free Template");

  useEffect(() => {
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.content = "GST invoice format guide for 2026 — all 16 mandatory fields under Rule 46, tax invoice vs bill of supply, numbering rules, copies required, time limits, e-invoicing applicability, and common mistakes.";

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
        headline: "GST Invoice Format Guide 2026: Mandatory Fields, Rules & Free Template",
        description: "Every field a GST invoice must carry under Rule 46, the difference between a tax invoice and a bill of supply, numbering rules, copies, time limits and e-invoicing in 2026.",
        url: "https://gst.doaide.com/blog/gst-invoice-format-guide-2026",
        datePublished: "2026-10-23",
        dateModified: "2026-10-23",
        publisher: { "@type": "Organization", name: "DoAide" },
      },
      {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: [
          { "@type": "Question", name: "What fields are mandatory on a GST invoice?", acceptedAnswer: { "@type": "Answer", text: "Rule 46 requires both parties' details with GSTINs, a unique serial number, date, HSN or SAC codes, taxable value, the tax shown separately per head, place of supply, a reverse-charge declaration, and a signature." } },
          { "@type": "Question", name: "What is the difference between a tax invoice and a bill of supply?", acceptedAnswer: { "@type": "Answer", text: "A tax invoice charges GST and lets a registered buyer claim ITC. A bill of supply is issued where no GST can be charged — by composition scheme dealers and for exempt supplies — and carries no tax column." } },
          { "@type": "Question", name: "How should GST invoices be numbered?", acceptedAnswer: { "@type": "Answer", text: "A consecutive serial number up to 16 characters, unique per financial year, using letters, numerals, hyphen or slash. Gaps have to be explainable — the series is reported in GSTR-1 Table 13 every period." } },
          { "@type": "Question", name: "Is e-invoicing mandatory in 2026?", acceptedAnswer: { "@type": "Answer", text: "E-invoicing is mandatory for businesses with aggregate turnover above ₹5 crore for B2B supplies. The invoice is registered on the IRP, which returns an IRN and a signed QR code that must appear on the invoice." } },
          { "@type": "Question", name: "What is the time limit for issuing a GST invoice?", acceptedAnswer: { "@type": "Answer", text: "For goods: on or before removal or delivery. For services: within 30 days of supply (45 days for banks, NBFCs and insurers)." } },
          { "@type": "Question", name: "How many digits of HSN code must an invoice show?", acceptedAnswer: { "@type": "Answer", text: "Turnover up to ₹5 crore: 4-digit HSN on B2B invoices. Above ₹5 crore: 6-digit HSN on every invoice. Getting this wrong attracts a penalty of ₹25,000 under Section 125." } },
        ],
      },
    ]);
    return () => { if (script.parentNode) script.parentNode.removeChild(script); };
  }, []);

  return (
    <article className="blog-article">
      <h1>GST Invoice Format Guide 2026: Mandatory Fields, Rules &amp; Free Template</h1>
      <p className="blog-meta">Updated October 2026 · 12 min read</p>

      <section>
        <p>
          A GST invoice is not just a bill — it is the document your buyer&apos;s input
          tax credit stands on, the row your GSTR-1 reports, and the first thing an
          officer reads in an audit. An invoice missing a mandatory field can cost the
          buyer their credit and cost you a penalty under Section 122 (₹10,000 or the
          tax involved, whichever is higher, for incorrect invoicing).
        </p>
        <p>
          This guide covers the format rules as they stand in 2026. If you just want a
          correct invoice now, the{" "}
          <Link to="/invoice-generator">free GST invoice generator</Link> produces a
          compliant PDF with every field below.
        </p>
      </section>

      <section>
        <h2>The 16 Mandatory Fields Under Rule 46</h2>
        <p>Rule 46 of the CGST Rules lists what every tax invoice must carry:</p>
        <ol>
          <li>Supplier&apos;s legal name, address and <strong>GSTIN</strong></li>
          <li>A consecutive <strong>serial number</strong>, unique for the financial year (max 16 characters; letters, numerals, hyphen and slash allowed)</li>
          <li><strong>Date</strong> of issue</li>
          <li>Buyer&apos;s name, address and GSTIN <em>if registered</em></li>
          <li>For unregistered buyers and invoice value ≥ ₹50,000 — buyer&apos;s name, address and state (the delivery address decides place of supply)</li>
          <li><strong>HSN code</strong> for goods / <strong>SAC</strong> for services (4 digits up to ₹5 crore turnover, 6 digits above)</li>
          <li><strong>Description</strong> of goods or services</li>
          <li><strong>Quantity</strong> and unit for goods</li>
          <li>Total <strong>value</strong> of supply</li>
          <li><strong>Taxable value</strong> after discounts</li>
          <li><strong>Rate of tax</strong> — CGST and SGST/UTGST shown separately for intra-state, IGST for inter-state</li>
          <li><strong>Amount of tax</strong> for each component</li>
          <li><strong>Place of supply</strong> with state name, for inter-state supplies</li>
          <li>Delivery address where it differs from the place of supply</li>
          <li>Whether tax is payable on <strong>reverse charge</strong></li>
          <li><strong>Signature</strong> or digital signature of the supplier or an authorised representative (not required on an e-invoice with IRN)</li>
        </ol>
        <p>
          Amounts should also be stated in words — not strictly a Rule 46 field, but
          universal practice and expected by buyers&apos; accounts teams.
        </p>
      </section>

      <section>
        <h2>Tax Invoice, Bill of Supply, or Something Else?</h2>
        <ul>
          <li><strong>Tax invoice</strong> — the default for registered dealers charging GST. The buyer&apos;s ITC depends on it.</li>
          <li><strong>Bill of supply</strong> — for composition scheme dealers and exempt supplies. No tax column; a composition dealer must print &quot;composition taxable person, not eligible to collect tax on supplies&quot;.</li>
          <li><strong>Receipt voucher</strong> — for advances received before supply.</li>
          <li><strong>Credit / debit note</strong> — to correct an issued invoice&apos;s value or tax; reported in GSTR-1 against the original.</li>
          <li><strong>Revised invoice</strong> — for supplies made between the registration effective date and certificate issue.</li>
          <li><strong>Consolidated invoice</strong> — allowed for B2C supplies under ₹200 per sale where the buyer does not ask for one, issued daily.</li>
        </ul>
      </section>

      <section>
        <h2>Tax Columns: CGST+SGST or IGST — Never Both</h2>
        <p>
          The split is decided by comparing the supplier&apos;s state code (the first
          two digits of the GSTIN) with the place of supply — not by what feels right
          on the invoice. Same state → CGST + SGST, each at half the rate. Different
          states → IGST at the full rate. Charging CGST+SGST on an inter-state sale is
          a real mistake with a painful fix: pay IGST, then claim a refund of the
          wrongly paid tax. The{" "}
          <Link to="/place-of-supply">place of supply checker</Link> settles doubtful
          cases.
        </p>
      </section>

      <section>
        <h2>Copies Required</h2>
        <ul>
          <li><strong>Goods</strong> — triplicate: original for the recipient, duplicate for the transporter, triplicate for the supplier.</li>
          <li><strong>Services</strong> — duplicate: original for the recipient, duplicate for the supplier.</li>
        </ul>
        <p>
          With e-invoicing the IRN-registered copy with QR code serves the purpose; the
          transporter can carry it electronically alongside the{" "}
          <Link to="/eway-bill">e-way bill</Link>.
        </p>
      </section>

      <section>
        <h2>Time Limits for Issuing an Invoice</h2>
        <ul>
          <li><strong>Goods</strong> — on or before removal (where movement is involved) or delivery.</li>
          <li><strong>Services</strong> — within 30 days of the supply; 45 days for banks, NBFCs and insurers.</li>
          <li><strong>Continuous supply</strong> — on or before each due date of payment or statement.</li>
        </ul>
      </section>

      <section>
        <h2>E-Invoicing in 2026</h2>
        <p>
          Businesses with aggregate turnover above <strong>₹5 crore</strong> must
          register every B2B invoice on the Invoice Registration Portal (IRP). The IRP
          returns an <strong>IRN</strong> (invoice reference number) and a signed{" "}
          <strong>QR code</strong>, both of which must appear on the invoice. Reporting
          must happen within 30 days of the invoice date for taxpayers above ₹10 crore.
          An e-invoice without an IRN is, legally, not an invoice at all — the buyer&apos;s
          ITC fails with it. The{" "}
          <Link to="/e-invoice-generator">e-invoice JSON generator</Link> produces the
          IRP payload from invoice fields.
        </p>
      </section>

      <section>
        <h2>Common Invoice Mistakes That Cost Real Money</h2>
        <ul>
          <li><strong>Wrong tax split</strong> — CGST+SGST charged inter-state (or IGST intra-state); fix is pay-then-refund.</li>
          <li><strong>Missing or 2-digit HSN</strong> — ₹25,000 penalty under Section 125, and GSTR-1 Table 12 will not reconcile.</li>
          <li><strong>Broken serial series</strong> — unexplained gaps show up in GSTR-1 Table 13 and read as suppressed sales in an audit.</li>
          <li><strong>No reverse-charge declaration</strong> — the field is mandatory even when the answer is &quot;No&quot;.</li>
          <li><strong>Rounding per line instead of per invoice</strong> — Section 170 rounds the final tax, not every row.</li>
          <li><strong>Buyer GSTIN typo</strong> — the credit lands in a stranger&apos;s GSTR-2B; validate it with the <Link to="/gstin-validator">GSTIN validator</Link> before issuing.</li>
        </ul>
      </section>

      <section>
        <h2>Frequently Asked Questions</h2>
        <h3>Can I issue an invoice without the buyer&apos;s GSTIN?</h3>
        <p>
          To an unregistered buyer, yes. To a registered buyer, their GSTIN is
          mandatory — without it the sale reports as B2C and the buyer gets no credit.
        </p>
        <h3>Is a digital signature required?</h3>
        <p>
          A physical, digital or electronic signature of the supplier or authorised
          representative is required — except on e-invoices carrying an IRN, where the
          IRP&apos;s signed QR code stands in for it.
        </p>
        <h3>Can invoice numbers restart every year?</h3>
        <p>
          Yes — uniqueness is required within a financial year. Most businesses prefix
          the year (e.g. 2026-27/001) so the restart is self-evident.
        </p>
        <h3>What about export invoices?</h3>
        <p>
          Add the endorsement &quot;Supply meant for export on payment of IGST&quot; or
          &quot;…under bond or LUT without payment of IGST&quot;, plus the buyer&apos;s
          country and, where applicable, shipping bill details.
        </p>
      </section>

      <section>
        <h2>Generate a Compliant Invoice Now</h2>
        <p>
          The <Link to="/invoice-generator">DoAide GST invoice generator</Link> builds
          an invoice with every Rule 46 field — correct tax split from the two GSTINs,
          HSN per line, amount in words — and downloads it as a PDF. Free, no sign-up.
          Check the right rate first with the{" "}
          <Link to="/hsn">HSN code finder</Link> and verify your buyer with the{" "}
          <Link to="/lookup">GSTIN lookup</Link>.
        </p>
      </section>
    </article>
  );
}
