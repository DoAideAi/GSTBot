import { useState } from "react";
import { Link } from "react-router-dom";
import SeoHead from "../../components/SeoHead";
import ShareButtons from "../../components/ShareButtons";
import DoAideFooter from "../../components/DoAideFooter";
import RelatedTools from "../../components/RelatedTools";
import ToolsNav from "../../components/ToolsNav";
import { usePageTitle } from "../../hooks/usePageTitle";

const FAQ_ITEMS = [
  {
    q: "What is Input Tax Credit (ITC) under GST?",
    a: "ITC is the credit a business receives for GST paid on purchases used for business purposes. It reduces your output tax liability by the GST already paid on inputs, lowering the overall tax burden.",
  },
  {
    q: "Who can claim ITC under GST?",
    a: "Any registered taxpayer except those under the composition scheme. You must be registered, use goods/services for business purposes, and meet all conditions under Section 16(2) of the CGST Act.",
  },
  {
    q: "Can I claim ITC on capital goods?",
    a: "Yes. ITC on capital goods can be claimed in full in the tax period when the goods are received. There is no requirement to claim it in instalments (the earlier rule of claiming over 2 years was removed).",
  },
  {
    q: "What happens if I don't pay the supplier within 180 days?",
    a: "If payment is not made to the supplier within 180 days from the date of the invoice, the ITC claimed must be reversed along with interest. The ITC can be re-claimed when the payment is eventually made.",
  },
  {
    q: "Can I claim ITC on rent for office premises?",
    a: "Yes, GST paid on rent for commercial premises used for business is eligible for ITC. However, ITC is blocked on construction of immovable property (except plant and machinery).",
  },
  {
    q: "Is ITC available on GST paid on insurance premiums?",
    a: "ITC is blocked on life and health insurance unless the employer is legally obligated to provide it. Motor insurance ITC follows the same rules as motor vehicles — blocked with exceptions for specified categories.",
  },
  {
    q: "What is the time limit for claiming ITC?",
    a: "ITC for any invoice must be claimed by the earlier of: (a) 30th November of the following financial year, or (b) the date of filing the annual return (GSTR-9) for that financial year.",
  },
  {
    q: "How does ITC reversal work for exempt and taxable supplies?",
    a: "If you make both exempt and taxable supplies, ITC must be proportionally reversed for the exempt portion under Rule 42 (inputs and input services) and Rule 43 (capital goods). Calculated monthly, finalized annually.",
  },
];

const HOWTO_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "HowTo",
  name: "How to Claim Input Tax Credit Under GST",
  description: "Step-by-step guide to claiming ITC under GST for Indian businesses",
  step: [
    { "@type": "HowToStep", name: "Ensure GST Registration", text: "You must be a registered taxpayer (not under composition scheme) to claim ITC." },
    { "@type": "HowToStep", name: "Obtain Valid Tax Invoice", text: "Get a proper tax invoice or debit note from the supplier with correct GSTIN, HSN code, and tax breakup." },
    { "@type": "HowToStep", name: "Receive Goods or Services", text: "ITC can only be claimed after the goods have been received or services have been rendered." },
    { "@type": "HowToStep", name: "Check GSTR-2B", text: "Verify that the supplier's invoice appears in your auto-populated GSTR-2B before claiming the credit." },
    { "@type": "HowToStep", name: "Claim in GSTR-3B", text: "Report the eligible ITC in Table 4 of your GSTR-3B return for the relevant tax period." },
    { "@type": "HowToStep", name: "Pay Supplier Within 180 Days", text: "Ensure payment to the supplier within 180 days of invoice date, or the ITC must be reversed." },
  ],
};

const FAQ_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: FAQ_ITEMS.map((item) => ({
    "@type": "Question",
    name: item.q,
    acceptedAnswer: { "@type": "Answer", text: item.a },
  })),
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "Guides", url: "https://gst.doaide.com/guides" },
  { name: "Input Tax Credit Guide" },
];

function FaqSection() {
  const [openIndex, setOpenIndex] = useState(null);
  return (
    <section aria-labelledby="faq-heading">
      <h2 id="faq-heading">Frequently Asked Questions</h2>
      <dl className="compare-faq-list">
        {FAQ_ITEMS.map((item, i) => (
          <div key={i} className="compare-faq-item">
            <dt>
              <button
                className="compare-faq-q"
                aria-expanded={openIndex === i}
                onClick={() => setOpenIndex(openIndex === i ? null : i)}
              >
                {item.q}
                <span aria-hidden="true">{openIndex === i ? "−" : "+"}</span>
              </button>
            </dt>
            {openIndex === i && <dd className="compare-faq-a">{item.a}</dd>}
          </div>
        ))}
      </dl>
    </section>
  );
}

export default function InputTaxCreditGuide() {
  usePageTitle("Complete Guide to Input Tax Credit (ITC) Under GST");

  return (
    <div className="tool-page">
      <SeoHead
        title="Complete Guide to Input Tax Credit (ITC) Under GST — Rules, Conditions & Examples"
        description="Comprehensive guide to Input Tax Credit under GST. Learn ITC eligibility, conditions under Section 16, blocked credits under Section 17(5), reversal rules, and how to claim ITC in GSTR-3B."
        path="/guides/input-tax-credit"
        jsonLd={[HOWTO_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container" style={{ maxWidth: 800 }}>
          <h1 className="tool-title">Complete Guide to Input Tax Credit (ITC) Under GST</h1>
          <p className="tool-subtitle">
            Everything you need to know about claiming ITC — eligibility, conditions,
            blocked credits, and reversal rules. Updated for 2026.
          </p>

          <ShareButtons path="/guides/input-tax-credit" text="Complete guide to Input Tax Credit under GST — DoAide GST" />

          <nav className="blog-toc" aria-label="Table of contents">
            <h2>Contents</h2>
            <ol>
              <li><a href="#what-is-itc">What is Input Tax Credit?</a></li>
              <li><a href="#who-can-claim">Who Can Claim ITC?</a></li>
              <li><a href="#conditions">Conditions for Claiming ITC</a></li>
              <li><a href="#blocked-credits">Blocked Credits (Section 17(5))</a></li>
              <li><a href="#how-to-claim">How to Claim ITC in GSTR-3B</a></li>
              <li><a href="#reversal">ITC Reversal Rules</a></li>
              <li><a href="#time-limit">Time Limit for Claiming ITC</a></li>
              <li><a href="#examples">Practical Examples</a></li>
              <li><a href="#faq-heading">FAQs</a></li>
            </ol>
          </nav>

          <article className="blog-content">
            <section id="what-is-itc">
              <h2>What is Input Tax Credit?</h2>
              <p>
                Input Tax Credit (ITC) is the mechanism that allows a registered taxpayer
                to reduce the GST payable on output (sales) by the amount of GST already
                paid on inputs (purchases). This eliminates the cascading effect of tax — you
                pay tax only on the value you add, not on the entire selling price.
              </p>
              <p>
                For example, if you purchase raw materials worth ₹1,00,000 and pay ₹18,000
                as GST (18%), and sell the finished goods for ₹1,50,000 with ₹27,000 GST,
                your actual GST liability is only ₹27,000 − ₹18,000 = <strong>₹9,000</strong>.
              </p>
            </section>

            <section id="who-can-claim">
              <h2>Who Can Claim ITC?</h2>
              <p>ITC can be claimed by any person who is:</p>
              <ul>
                <li>Registered under GST (not under the composition scheme)</li>
                <li>Using the goods or services for business purposes</li>
                <li>Using inputs for making taxable supplies (including zero-rated)</li>
              </ul>
              <p>
                <strong>ITC is NOT available to:</strong> composition scheme dealers, persons
                making only exempt supplies, and unregistered persons.
              </p>
            </section>

            <section id="conditions">
              <h2>Conditions for Claiming ITC (Section 16(2))</h2>
              <p>All four conditions must be satisfied simultaneously:</p>
              <ol>
                <li>
                  <strong>Possession of tax invoice or debit note</strong> — the document
                  must contain a valid GSTIN, correct HSN/SAC code, and proper tax breakup.
                </li>
                <li>
                  <strong>Receipt of goods or services</strong> — ITC cannot be claimed
                  on advance payments before delivery. For goods received in lots, ITC
                  is available only when the last lot is received.
                </li>
                <li>
                  <strong>Tax actually paid by supplier</strong> — the supplier must have
                  deposited the GST with the government by filing their return.
                </li>
                <li>
                  <strong>Filing of return by the buyer</strong> — you must have filed
                  the GST return (GSTR-3B) for the relevant period.
                </li>
              </ol>
              <p>
                Additionally, the invoice must appear in your <strong>GSTR-2B</strong> (auto-populated
                from supplier&apos;s GSTR-1), and payment must be made within <strong>180 days</strong>.
              </p>
            </section>

            <section id="blocked-credits">
              <h2>Blocked Credits — Section 17(5)</h2>
              <p>ITC is specifically denied for the following:</p>
              <ul>
                <li><strong>Motor vehicles</strong> — except for transport of goods, passengers (13+ seats), driving training, or further supply</li>
                <li><strong>Food, beverages, outdoor catering</strong> — unless used for providing the same category of supply</li>
                <li><strong>Beauty treatment, health services, cosmetic surgery</strong></li>
                <li><strong>Club membership, health and fitness centre</strong></li>
                <li><strong>Life and health insurance</strong> — unless obligatory for employees</li>
                <li><strong>Travel (air, rail, bus)</strong> — unless used for supply of similar services or as part of a composite supply</li>
                <li><strong>Works contract for immovable property</strong> — except plant and machinery</li>
                <li><strong>Construction of immovable property on own account</strong></li>
                <li><strong>Goods/services for personal consumption</strong></li>
                <li><strong>Gifts and free samples</strong></li>
                <li><strong>Tax paid under composition scheme, Section 9(3), or Section 9(4)</strong></li>
              </ul>
            </section>

            <section id="how-to-claim">
              <h2>How to Claim ITC in GSTR-3B</h2>
              <p>ITC is claimed in <strong>Table 4</strong> of GSTR-3B:</p>
              <ol>
                <li>Log in to the GST portal → Returns → GSTR-3B</li>
                <li>Go to Table 4 — Eligible ITC</li>
                <li>
                  <strong>4(A):</strong> Report ITC from invoices, debit notes, and import
                  bills. Cross-check with your GSTR-2B auto-populated data.
                </li>
                <li>
                  <strong>4(B):</strong> Report reversals — for exempt supplies (Rule 42/43),
                  blocked credits (Section 17(5)), and others.
                </li>
                <li>Net ITC (4A − 4B) reduces your output tax liability</li>
              </ol>
            </section>

            <section id="reversal">
              <h2>ITC Reversal Rules</h2>
              <p>ITC already claimed must be reversed in these situations:</p>
              <ul>
                <li><strong>Non-payment within 180 days:</strong> ITC + 18% interest must be reversed</li>
                <li><strong>Credit note from supplier:</strong> proportional ITC reversal</li>
                <li><strong>Exempt + taxable supplies:</strong> proportional reversal under Rule 42 (inputs) and Rule 43 (capital goods)</li>
                <li><strong>Capital goods put to non-business use:</strong> ITC reversed on a straight-line basis for remaining useful life (5 years)</li>
                <li><strong>Buyer fails to pay:</strong> reversed with interest within 180 days</li>
              </ul>
            </section>

            <section id="time-limit">
              <h2>Time Limit for Claiming ITC</h2>
              <p>
                ITC for any financial year must be claimed by the <strong>earlier of</strong>:
              </p>
              <ul>
                <li>30th November of the following financial year, or</li>
                <li>Date of filing the annual return (GSTR-9) for that financial year</li>
              </ul>
              <p>
                For example, ITC for FY 2025-26 must be claimed by 30th November 2026 or
                the date of filing GSTR-9 for 2025-26, whichever is earlier.
              </p>
            </section>

            <section id="examples">
              <h2>Practical Examples</h2>
              <h3>Example 1: Eligible ITC</h3>
              <p>
                ABC Ltd buys office furniture for ₹2,00,000 + 18% GST (₹36,000). The furniture
                is used for business, supplier has filed GSTR-1, and the invoice appears in
                ABC&apos;s GSTR-2B. ABC can claim the full ₹36,000 as ITC.
              </p>
              <h3>Example 2: Blocked Credit</h3>
              <p>
                XYZ Corp buys a car for ₹15,00,000 + 40% GST (₹6,00,000) for the MD&apos;s
                personal use. Even though the company is registered and has a valid invoice,
                ITC on motor vehicles for personal use is blocked under Section 17(5). No ITC
                can be claimed.
              </p>
              <h3>Example 3: Partial Reversal</h3>
              <p>
                PQR Services makes both taxable (80%) and exempt (20%) supplies. Total ITC on
                common inputs is ₹5,00,000. PQR must reverse 20% (₹1,00,000) of the ITC
                attributable to exempt supplies under Rule 42.
              </p>
            </section>

            <FaqSection />

            <section className="compare-cta" style={{ marginTop: "2rem" }}>
              <h2>Check Your ITC Eligibility Instantly</h2>
              <p>
                Use our free ITC Eligibility Checker to verify if your purchase qualifies
                for Input Tax Credit. No sign-up needed.
              </p>
              <div className="compare-cta-buttons">
                <Link to="/input-tax-credit" className="btn btn-primary">Check ITC Eligibility</Link>
                <Link to="/calculator" className="btn compare-cta-secondary">GST Calculator</Link>
              </div>
            </section>
          </article>

          <RelatedTools current="/guides/input-tax-credit" />
        </div>
      </main>
      <DoAideFooter />
    </div>
  );
}
