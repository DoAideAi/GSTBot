import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";
import SeoHead from "../../components/SeoHead";

export default function CompositionSchemeGuide() {
  usePageTitle("GST Composition Scheme: Eligibility, Tax Rates & Benefits for Small Businesses");

  return (
    <article className="blog-article">
      <SeoHead title="GST Composition Scheme: Eligibility, Rates & Benefits" description="Complete guide to GST composition scheme — eligibility criteria, tax rates (1-6%), quarterly filing, benefits for small businesses, and how to opt in." path="/blog/gst-composition-scheme-guide" />
      <h1>GST Composition Scheme: Eligibility, Tax Rates, and Benefits for Small Businesses</h1>
      <p className="blog-meta">Updated October 2026 · 9 min read</p>

      <section>
        <h2>What is the Composition Scheme Under GST?</h2>
        <p>
          The Composition Scheme under GST (Section 10 of the CGST Act) is a simplified tax
          compliance option for small businesses. Instead of filing monthly returns and charging
          GST on each invoice, composition taxpayers pay tax at a flat rate on their turnover and
          file returns quarterly. It is designed to reduce the compliance burden for micro and
          small enterprises.
        </p>
      </section>

      <section>
        <h2>Eligibility Criteria</h2>
        <p>
          Not every business can opt for the Composition Scheme. The key eligibility conditions are:
        </p>
        <ul className="blog-checklist">
          <li>Aggregate turnover in the preceding financial year must not exceed <strong>₹1.5 crore</strong> for goods manufacturers and traders (₹75 lakhs for special category states)</li>
          <li>Service providers can opt in if turnover does not exceed <strong>₹50 lakhs</strong></li>
          <li>Must not be engaged in inter-state outward supplies (sales outside your state)</li>
          <li>Must not supply goods through an e-commerce operator</li>
          <li>Must not be a manufacturer of ice cream, pan masala, tobacco, or aerated water</li>
          <li>Must not be a casual taxable person or non-resident taxable person</li>
          <li>All businesses registered under the same PAN must opt for composition if any one does</li>
        </ul>
      </section>

      <section>
        <h2>Tax Rates Under the Composition Scheme</h2>
        <table className="blog-table">
          <thead>
            <tr>
              <th>Category</th>
              <th>CGST Rate</th>
              <th>SGST Rate</th>
              <th>Total Rate</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Manufacturers (other than excluded goods)</td>
              <td>0.5%</td>
              <td>0.5%</td>
              <td>1% of turnover</td>
            </tr>
            <tr>
              <td>Traders (suppliers of goods)</td>
              <td>0.5%</td>
              <td>0.5%</td>
              <td>1% of turnover</td>
            </tr>
            <tr>
              <td>Restaurants (not serving alcohol)</td>
              <td>2.5%</td>
              <td>2.5%</td>
              <td>5% of turnover</td>
            </tr>
            <tr>
              <td>Service providers (Section 10(2A))</td>
              <td>3%</td>
              <td>3%</td>
              <td>6% of turnover</td>
            </tr>
          </tbody>
        </table>
        <p>
          These rates are applied on the total turnover — not on individual invoices. The tax is
          paid out of the taxpayer&apos;s margin, since composition dealers cannot charge GST to their
          customers.
        </p>
      </section>

      <section>
        <h2>Benefits of the Composition Scheme</h2>
        <ul className="blog-checklist">
          <li><strong>Lower tax rates:</strong> 1-6% compared to standard GST rates of 5-40%</li>
          <li><strong>Simplified compliance:</strong> file CMP-08 quarterly and GSTR-4 annually, instead of monthly GSTR-1 and GSTR-3B</li>
          <li><strong>Reduced record-keeping:</strong> no need to maintain detailed invoice-level records for GST purposes</li>
          <li><strong>Lower working capital requirements:</strong> the lower tax rate means less cash locked up in tax payments</li>
          <li><strong>No e-invoicing requirement:</strong> composition dealers are exempt from the e-invoice mandate</li>
        </ul>
      </section>

      <section>
        <h2>Restrictions and Limitations</h2>
        <p>
          The Composition Scheme comes with significant trade-offs that businesses must consider:
        </p>
        <ul>
          <li><strong>No Input Tax Credit (ITC):</strong> you cannot claim ITC on purchases — the tax paid on inputs is a cost</li>
          <li><strong>No inter-state supply:</strong> you can only sell within your state; inter-state sales disqualify you</li>
          <li><strong>Cannot collect GST:</strong> invoices must state &quot;composition taxable person, not eligible to collect tax on supplies&quot;</li>
          <li><strong>No e-commerce sales:</strong> you cannot sell through platforms like Amazon or Flipkart</li>
          <li><strong>Bill of supply:</strong> you must issue a bill of supply instead of a tax invoice</li>
          <li><strong>Limited to B2C:</strong> since you cannot issue tax invoices, B2B customers cannot claim ITC on purchases from you</li>
        </ul>
      </section>

      <section>
        <h2>Filing Requirements</h2>
        <table className="blog-table">
          <thead>
            <tr>
              <th>Return</th>
              <th>Frequency</th>
              <th>Due Date</th>
              <th>Purpose</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>CMP-08</td>
              <td>Quarterly</td>
              <td>18th of the month following the quarter</td>
              <td>Self-assessed tax payment statement</td>
            </tr>
            <tr>
              <td>GSTR-4</td>
              <td>Annual</td>
              <td>30th April of the following financial year</td>
              <td>Annual return with turnover and tax details</td>
            </tr>
          </tbody>
        </table>
        <p>
          This means just 5 filings per year (4 quarterly CMP-08 + 1 annual GSTR-4), compared to
          at least 25 for regular taxpayers (12 GSTR-1 + 12 GSTR-3B + 1 GSTR-9).
        </p>
      </section>

      <section>
        <h2>How to Opt In and Opt Out</h2>
        <h3>Opting In</h3>
        <ul>
          <li>Existing taxpayers: file GST CMP-02 on the portal before 31st March for the next financial year</li>
          <li>New registrations: opt in at the time of registration using Part B of GST REG-01</li>
          <li>The composition levy becomes effective from the beginning of the financial year</li>
          <li>You must reverse any ITC held in stock on the date of opting in</li>
        </ul>
        <h3>Opting Out</h3>
        <ul>
          <li>File GST CMP-04 within 7 days of becoming ineligible or choosing to leave</li>
          <li>File ITC-01 within 30 days to claim ITC on stock held on the date of exit</li>
          <li>Begin filing regular returns (GSTR-1, GSTR-3B) from the effective date of withdrawal</li>
        </ul>
      </section>

      <section>
        <h2>Composition Scheme vs Regular GST: Comparison</h2>
        <table className="blog-table">
          <thead>
            <tr>
              <th>Feature</th>
              <th>Composition Scheme</th>
              <th>Regular GST</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Tax rate</td>
              <td>1-6% of turnover</td>
              <td>5-40% on value of supply</td>
            </tr>
            <tr>
              <td>Input Tax Credit</td>
              <td>Not available</td>
              <td>Available on all eligible inputs</td>
            </tr>
            <tr>
              <td>Invoice type</td>
              <td>Bill of supply</td>
              <td>Tax invoice</td>
            </tr>
            <tr>
              <td>Filing frequency</td>
              <td>Quarterly + annual (5/year)</td>
              <td>Monthly + annual (25/year)</td>
            </tr>
            <tr>
              <td>Inter-state sales</td>
              <td>Not permitted</td>
              <td>Permitted</td>
            </tr>
            <tr>
              <td>E-commerce sales</td>
              <td>Not permitted</td>
              <td>Permitted</td>
            </tr>
            <tr>
              <td>Collect GST from buyer</td>
              <td>Cannot collect</td>
              <td>Must collect and remit</td>
            </tr>
            <tr>
              <td>E-invoicing</td>
              <td>Exempt</td>
              <td>Required above ₹5 crore turnover</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>When to Choose the Composition Scheme</h2>
        <p>
          The Composition Scheme is ideal when:
        </p>
        <ul className="blog-checklist">
          <li>Your customers are mostly end consumers (B2C) who do not need ITC</li>
          <li>Your input purchases have low GST components (raw materials at 5% or nil-rated)</li>
          <li>You operate within a single state with no plans for inter-state expansion</li>
          <li>You want to minimise compliance effort and costs</li>
          <li>Your turnover is well within the limits and unlikely to cross them mid-year</li>
        </ul>
        <p>
          It is <strong>not</strong> ideal when your customers are businesses that need ITC, when
          you have significant input tax to recover, or when you plan to sell across state borders.
          Use our <Link to="/composition-scheme">Composition Scheme comparison tool</Link> to model
          the tax impact for your specific business.
        </p>
      </section>

      <section className="blog-cta">
        <h2>Simplify Your GST Compliance</h2>
        <p>
          Whether you are on the Composition Scheme or regular GST, DoAide GST helps you stay
          compliant with automated reconciliation, deadline tracking, and ITC calculations.{" "}
          <Link to="/">Get started with DoAide GST</Link> — it is free for basic use.
        </p>
      </section>
    </article>
  );
}
