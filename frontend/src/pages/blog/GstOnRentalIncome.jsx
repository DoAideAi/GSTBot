import { useEffect } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";

export default function GstOnRentalIncome() {
  usePageTitle("GST on Rental Income in India 2026: Rates, Exemptions & RCM");

  useEffect(() => {
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.content = "When rental income attracts GST in India — 18% on commercial rent, the residential exemption, reverse charge on renting to registered businesses, the ₹20 lakh threshold, and how to report rent in GSTR-1 and GSTR-3B.";

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
        headline: "GST on Rental Income in India 2026: Rates, Exemptions & RCM",
        description: "When rent attracts GST — 18% on commercial property, the residential exemption, reverse charge on renting to registered persons, registration thresholds and return reporting.",
        url: "https://gst.doaide.com/blog/gst-on-rental-income",
        datePublished: "2026-10-22",
        dateModified: "2026-10-22",
        publisher: { "@type": "Organization", name: "DoAide" },
      },
      {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: [
          { "@type": "Question", name: "Is GST applicable on residential rent?", acceptedAnswer: { "@type": "Answer", text: "Renting a residential dwelling to an individual for personal residence is exempt. If a GST-registered business rents a residential property, the tenant pays 18% under reverse charge — the landlord charges nothing." } },
          { "@type": "Question", name: "What is the GST rate on commercial rent?", acceptedAnswer: { "@type": "Answer", text: "18% (SAC 997212). A landlord whose total taxable turnover, including rent, exceeds ₹20 lakh (₹10 lakh in special category states) must register and charge 18% GST on commercial rent." } },
          { "@type": "Question", name: "Do I need GST registration if my only income is rent?", acceptedAnswer: { "@type": "Answer", text: "Only when taxable rental income crosses ₹20 lakh a year (₹10 lakh in special category states). Exempt residential rent does not count toward the threshold; commercial rent does." } },
          { "@type": "Question", name: "Can a tenant claim ITC on GST paid on rent?", acceptedAnswer: { "@type": "Answer", text: "A registered tenant can claim ITC on GST paid on commercial rent used for business, including tax paid under reverse charge on residential property taken for business, subject to the normal ITC conditions." } },
          { "@type": "Question", name: "How is rental income shown in GST returns?", acceptedAnswer: { "@type": "Answer", text: "A registered landlord reports taxable rent invoices in GSTR-1 and pays the tax through GSTR-3B. A tenant paying under reverse charge reports it in Table 3.1(d) of GSTR-3B and claims any eligible ITC in Table 4." } },
        ],
      },
    ]);
    return () => { if (script.parentNode) script.parentNode.removeChild(script); };
  }, []);

  return (
    <article className="blog-article">
      <h1>GST on Rental Income in India 2026: Rates, Exemptions & RCM</h1>
      <p className="blog-meta">Updated October 2026 · 7 min read</p>

      <section>
        <p>
          Whether rent attracts GST comes down to two questions: <strong>what kind of
          property</strong> is being rented, and <strong>who is renting it</strong>.
          Commercial rent is a taxable service at 18%. Residential rent is exempt — until a
          GST-registered business is the tenant, at which point the tax shifts onto the
          tenant under <Link to="/rcm-calculator">reverse charge</Link>. This guide walks
          through every case, the registration threshold, and how rent lands in your returns.
        </p>
      </section>

      <section>
        <h2>The Four Scenarios</h2>
        <table className="comparison-table">
          <thead>
            <tr><th>Property</th><th>Tenant</th><th>GST</th><th>Who pays</th></tr>
          </thead>
          <tbody>
            <tr><td>Residential</td><td>Individual, for personal residence</td><td>Exempt</td><td>—</td></tr>
            <tr><td>Residential</td><td>GST-registered person or business</td><td>18%</td><td>Tenant, under reverse charge</td></tr>
            <tr><td>Commercial (shop, office, warehouse)</td><td>Anyone</td><td>18%</td><td>Landlord, if registered</td></tr>
            <tr><td>Any property</td><td>—, landlord below ₹20 lakh turnover</td><td>None charged</td><td>— (unless tenant&apos;s RCM applies)</td></tr>
          </tbody>
        </table>
        <p>
          The SAC code for renting immovable property is <strong>997212</strong> (commercial)
          and the service sits in the 18% slab — use the{" "}
          <Link to="/calculator">GST calculator</Link> to work out the tax on any rent amount.
        </p>
      </section>

      <section>
        <h2>Residential Rent: Exempt, With One Big Exception</h2>
        <p>
          Renting a <strong>residential dwelling for use as a residence</strong> to an
          unregistered individual is exempt. A salaried tenant never pays GST on house rent,
          and the landlord charges none regardless of how much rent is collected.
        </p>
        <p>
          The exception: when the tenant is <strong>registered under GST</strong> — a company
          taking a flat for an employee, a proprietor renting a house that doubles as a
          registered place of business — the tenant must pay 18% GST under the reverse charge
          mechanism. The landlord still issues a plain rent receipt with no tax; the tenant
          self-invoices, pays the tax in cash through GSTR-3B, and claims ITC where the
          property is used for business.
        </p>
      </section>

      <section>
        <h2>Commercial Rent: 18% Once You Cross the Threshold</h2>
        <p>
          Rent from shops, offices, godowns, co-working desks and any other commercial
          letting is a taxable supply at <strong>18%</strong>. The landlord must register and
          charge GST once <strong>aggregate taxable turnover crosses ₹20 lakh</strong> a year
          (₹10 lakh in special category states). Below the threshold no GST is charged at all.
        </p>
        <ul>
          <li>Exempt residential rent does <strong>not</strong> count toward the ₹20 lakh threshold</li>
          <li>Commercial rent, professional fees and any other taxable income all add up</li>
          <li>Interstate rental of immovable property still takes the property&apos;s state — check with the <Link to="/place-of-supply">place of supply tool</Link></li>
          <li>Not sure whether you must register? Run the <Link to="/registration-checker">registration checker</Link></li>
        </ul>
      </section>

      <section>
        <h2>ITC on Rent</h2>
        <p>
          A registered tenant paying 18% on commercial rent can claim it as input tax credit
          against output liability, provided the premises are used for business and the
          normal conditions — a valid invoice, the supplier having filed, the invoice
          appearing in GSTR-2B — are met. GST paid under reverse charge on residential
          property taken for business is likewise creditable. Estimate your eligible credit
          with the <Link to="/itc-calculator">ITC calculator</Link>.
        </p>
      </section>

      <section>
        <h2>Reporting Rent in GST Returns</h2>
        <ul>
          <li><strong>Landlord:</strong> taxable rent invoices go in GSTR-1 (B2B with the tenant&apos;s GSTIN, or B2C), and the liability is paid in GSTR-3B Table 3.1(a)</li>
          <li><strong>Tenant under RCM:</strong> liability in GSTR-3B Table 3.1(d), paid in cash (RCM cannot be set off against ITC), credit claimed in Table 4</li>
          <li><strong>TDS under income tax</strong> (Section 194-I) is separate from GST and applies on the rent excluding GST when GST is shown separately</li>
        </ul>
        <p>
          Filing deadlines for GSTR-1 and GSTR-3B are in the{" "}
          <Link to="/due-dates">due dates calendar</Link>.
        </p>
      </section>

      <section>
        <h2>Common Mistakes</h2>
        <ul>
          <li>A registered business paying residential rent and forgetting the reverse-charge liability entirely</li>
          <li>Counting exempt residential rent toward the ₹20 lakh threshold and registering needlessly</li>
          <li>Setting off RCM liability against ITC instead of paying it in cash</li>
          <li>Charging GST on commercial rent without being registered — tax collected without registration must be paid over with penalty</li>
        </ul>
      </section>
    </article>
  );
}
