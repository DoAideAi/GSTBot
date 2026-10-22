import { useEffect } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";

export default function HsnCodeList2026() {
  usePageTitle("HSN Code List 2026 - Complete Guide to HSN Classification");

  useEffect(() => {
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.content = "Complete HSN code list 2026 with search. Understand HSN classification system, find codes for your products, GST rates by HSN, and mandatory HSN requirements on invoices.";

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
        headline: "HSN Code List 2026 - Complete Guide to HSN Classification",
        description: "Complete HSN code list for 2026 with GST rates. Learn the classification system, find codes for your products, and understand mandatory HSN requirements.",
        url: "https://gst.doaide.com/blog/hsn-code-list-2026-complete-guide",
        datePublished: "2026-10-08",
        dateModified: "2026-10-08",
        publisher: { "@type": "Organization", name: "DoAide" },
      },
      {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: [
          { "@type": "Question", name: "How many digits of HSN code are mandatory?", acceptedAnswer: { "@type": "Answer", text: "Businesses with turnover up to ₹5 crore must show 4-digit HSN codes on B2B invoices; above ₹5 crore, 6-digit codes on all invoices. For GSTR-1 filing, 6-digit codes are mandatory for everyone." } },
          { "@type": "Question", name: "What is the difference between HSN and SAC codes?", acceptedAnswer: { "@type": "Answer", text: "HSN (Harmonized System of Nomenclature) codes classify goods and run 4-8 digits. SAC (Services Accounting Codes) classify services and are 6 digits starting with 99. Both determine the GST rate." } },
          { "@type": "Question", name: "Where can I find the HSN code for my product?", acceptedAnswer: { "@type": "Answer", text: "You can search HSN codes on the CBIC website, the GST portal, or use free tools like DoAide GST's HSN/SAC Finder. The code is based on the nature of the product — material, function, and end use." } },
          { "@type": "Question", name: "What happens if I use the wrong HSN code?", acceptedAnswer: { "@type": "Answer", text: "Using incorrect HSN codes can lead to wrong GST rate application, ITC mismatches, show-cause notices from the department, and penalties. It can also cause issues during GST audits and assessments." } },
          { "@type": "Question", name: "Are HSN codes the same worldwide?", acceptedAnswer: { "@type": "Answer", text: "The first 6 digits are standardized worldwide by the World Customs Organization. India adds 2 more for finer classification, making 8. Over 200 countries use HSN for customs and trade." } },
        ],
      },
    ]);
    return () => { if (script.parentNode) script.parentNode.removeChild(script); };
  }, []);

  return (
    <article className="blog-article">
      <h1>HSN Code List 2026 — Complete Guide to HSN Classification</h1>
      <p className="blog-meta">Updated October 2026 · 14 min read</p>

      <section>
        <p>
          HSN codes (Harmonized System of Nomenclature) are the backbone of GST classification in India.
          Every product you sell, manufacture, or trade needs a correct HSN code to determine the
          applicable GST rate. With over 21 sections and 5,000+ codes, finding the right one can be
          challenging. This guide explains the HSN system, lists the major code categories with GST rates,
          and shows you how to find the exact code for your products.
        </p>
        <p>
          Use our <Link to="/hsn-sac-finder">HSN/SAC Finder</Link> to instantly search and find the
          correct code for any product or service.
        </p>
      </section>

      <section>
        <h2>What Is the HSN Code System?</h2>
        <p>
          The Harmonized System of Nomenclature was developed by the World Customs Organization (WCO)
          in 1988 for classifying goods traded internationally. Over 200 countries use this system.
          In India, HSN codes are used under GST to classify goods for tax purposes. The system uses
          a hierarchical structure:
        </p>
        <ul>
          <li><strong>2-digit code:</strong> Chapter — broad category (e.g., 01 = Live animals)</li>
          <li><strong>4-digit code:</strong> Heading — more specific group (e.g., 0101 = Horses, donkeys)</li>
          <li><strong>6-digit code:</strong> Subheading — internationally standard (e.g., 010121 = Pure-bred horses)</li>
          <li><strong>8-digit code:</strong> India-specific tariff item (e.g., 01012100 = Pure-bred breeding horses)</li>
        </ul>
        <p>
          Similarly, services are classified using SAC (Services Accounting Codes) — 6-digit codes
          starting with &quot;99&quot;. For example, 998311 = Management consulting services.
        </p>
      </section>

      <section>
        <h2>HSN Code Requirements on Invoices</h2>
        <p>
          The number of HSN digits required depends on your annual turnover:
        </p>
        <ul>
          <li><strong>Turnover up to ₹5 crore:</strong> 4-digit HSN code on B2B invoices (optional on B2C)</li>
          <li><strong>Turnover above ₹5 crore:</strong> 6-digit HSN code on all invoices (B2B and B2C)</li>
          <li><strong>For GSTR-1 filing:</strong> 6-digit HSN codes are mandatory for all taxpayers in HSN Summary</li>
          <li><strong>For E-invoicing:</strong> 4-digit minimum; 6-digit recommended</li>
          <li><strong>For E-Way Bills:</strong> 4-digit minimum for goods movement</li>
        </ul>
        <p>
          Generate compliant invoices with the correct HSN codes using our{" "}
          <Link to="/invoice-generator">Invoice Generator</Link>.
        </p>
      </section>

      <section>
        <h2>Major HSN Code Sections and GST Rates</h2>
        <p>
          The HSN system is divided into 21 sections. Here are the key sections with common
          chapters and GST rates:
        </p>

        <h3>Section I — Live Animals and Animal Products (Chapters 01–05)</h3>
        <ul>
          <li><strong>0401-0406:</strong> Milk and dairy products — 0% (fresh milk), 5% (condensed/flavoured)</li>
          <li><strong>0501-0511:</strong> Animal products (hair, bones, etc.) — 5–18%</li>
        </ul>

        <h3>Section II — Vegetable Products (Chapters 06–14)</h3>
        <ul>
          <li><strong>0701-0714:</strong> Vegetables — 0% (fresh), 5% (dried/preserved)</li>
          <li><strong>0801-0814:</strong> Fruits and nuts — 0% (fresh), 12% (preserved)</li>
          <li><strong>1001-1008:</strong> Cereals — 0% (unbranded), 5% (branded/packaged)</li>
          <li><strong>1006:</strong> Rice — 0% (unbranded), 5% (branded)</li>
        </ul>

        <h3>Section IV — Food Products (Chapters 16–24)</h3>
        <ul>
          <li><strong>1701:</strong> Sugar — 5%</li>
          <li><strong>1905:</strong> Bread, biscuits, cakes — 0% (bread), 18% (biscuits &gt;₹100/kg)</li>
          <li><strong>2106:</strong> Food preparations — 18%</li>
          <li><strong>2202:</strong> Aerated drinks — 28% + cess</li>
          <li><strong>2402:</strong> Cigarettes and tobacco — 28% + cess</li>
        </ul>

        <h3>Section VI — Chemical Products (Chapters 28–38)</h3>
        <ul>
          <li><strong>3003-3004:</strong> Medicines — 5% (formulations), 12% (Ayurvedic)</li>
          <li><strong>3304:</strong> Cosmetics and beauty products — 18–28%</li>
          <li><strong>3401:</strong> Soap — 18%</li>
        </ul>

        <h3>Section XI — Textiles (Chapters 50–63)</h3>
        <ul>
          <li><strong>5208-5212:</strong> Cotton fabrics — 5%</li>
          <li><strong>6101-6117:</strong> Knitted garments — 5% (up to ₹1,000), 12% (above ₹1,000)</li>
          <li><strong>6201-6217:</strong> Woven garments — 5% (up to ₹1,000), 12% (above ₹1,000)</li>
        </ul>

        <h3>Section XV — Base Metals (Chapters 72–83)</h3>
        <ul>
          <li><strong>7204:</strong> Iron and steel scrap — 18%</li>
          <li><strong>7308:</strong> Steel structures — 18%</li>
          <li><strong>7318:</strong> Screws, bolts, nuts — 18%</li>
        </ul>

        <h3>Section XVI — Machinery and Electronics (Chapters 84–85)</h3>
        <ul>
          <li><strong>8471:</strong> Computers and laptops — 18%</li>
          <li><strong>8517:</strong> Mobile phones — 18%</li>
          <li><strong>8528:</strong> Television sets — 18–28%</li>
        </ul>

        <h3>Section XVII — Vehicles (Chapters 86–89)</h3>
        <ul>
          <li><strong>8703:</strong> Cars — 28% + cess (1–22% depending on type)</li>
          <li><strong>8711:</strong> Motorcycles — 28% (above 350cc + 3% cess)</li>
          <li><strong>8712:</strong> Bicycles — 12%</li>
        </ul>

        <p>
          Check the exact GST rate for any product using our <Link to="/calculator">GST Calculator</Link> or
          search by product name on our <Link to="/hsn-sac-finder">HSN/SAC Finder</Link>.
        </p>
      </section>

      <section>
        <h2>SAC Codes for Services</h2>
        <p>
          Services are classified under SAC codes — 6-digit codes starting with 99. Here are the
          common service categories:
        </p>
        <ul>
          <li><strong>9954:</strong> Construction services — 12–18%</li>
          <li><strong>9963:</strong> Restaurant and food services — 5% (without ITC)</li>
          <li><strong>9964:</strong> Transport services — 5–18%</li>
          <li><strong>9971:</strong> Financial services (banking, insurance) — 18%</li>
          <li><strong>9972:</strong> Real estate services — 5–18%</li>
          <li><strong>9973:</strong> Rental/leasing services — 18%</li>
          <li><strong>9983:</strong> IT and software services — 18%</li>
          <li><strong>9985:</strong> Telecom services — 18%</li>
          <li><strong>9988:</strong> Manufacturing services — 18%</li>
          <li><strong>9992:</strong> Education services — exempt (formal education), 18% (coaching)</li>
          <li><strong>9993:</strong> Health services — exempt (hospital), 18% (cosmetic)</li>
          <li><strong>9995:</strong> Entertainment services — 18–28%</li>
          <li><strong>9996:</strong> Hotel accommodation — 12% (≤₹7,500/night), 18% (&gt;₹7,500/night)</li>
        </ul>
      </section>

      <section>
        <h2>How to Find the Correct HSN Code</h2>
        <ol>
          <li><strong>Identify your product category:</strong> Start with the broad section (e.g., textiles, machinery, food)</li>
          <li><strong>Narrow to the chapter:</strong> Each section has chapters — find the 2-digit chapter code</li>
          <li><strong>Find the heading:</strong> Within the chapter, find the 4-digit heading that best describes your product</li>
          <li><strong>Get the subheading:</strong> Extend to 6 digits for the specific product variant</li>
          <li><strong>India-specific tariff:</strong> If needed, use the 8-digit code from the Customs Tariff</li>
          <li><strong>Verify the GST rate:</strong> Cross-check the rate notification for your HSN code</li>
        </ol>
        <p>
          Skip the manual search — use our <Link to="/hsn-sac-finder">HSN/SAC Finder</Link> to find
          the correct code by product name in seconds.
        </p>
      </section>

      <section>
        <h2>Common HSN Classification Mistakes</h2>
        <ul>
          <li><strong>Using generic codes:</strong> Applying a chapter-level (2-digit) code when a specific heading is available</li>
          <li><strong>Classifying by end use:</strong> HSN classifies by nature and material, not always by end use. A cotton garment is textile (Chapter 61/62), not fashion</li>
          <li><strong>Mixing HSN and SAC:</strong> If you supply both goods and services, use HSN for goods and SAC for services on the same invoice</li>
          <li><strong>Ignoring amendments:</strong> GST Council periodically reclassifies items — stay updated with <Link to="/blog">our blog</Link></li>
          <li><strong>Wrong rate bracket:</strong> The same product can have different rates based on value (e.g., garments above/below ₹1,000)</li>
        </ul>
      </section>

      <section>
        <h2>HSN Code Changes Under GST 2.0</h2>
        <p>
          With the upcoming GST 2.0 reforms, the classification system is expected to undergo changes:
        </p>
        <ul>
          <li><strong>Rate rationalization:</strong> The 4-slab structure (5%, 12%, 18%, 28%) may be simplified to 3 slabs</li>
          <li><strong>Reclassification:</strong> Several items may move between rate brackets</li>
          <li><strong>Cess changes:</strong> Compensation cess may be reformed or replaced</li>
          <li><strong>8-digit mandatory:</strong> Proposals to make 8-digit HSN codes mandatory for larger businesses</li>
        </ul>
        <p>
          Read our detailed analysis on <Link to="/blog/gst-2-changes-explained-india">GST 2.0 Changes Explained</Link> and
          check your readiness with our <Link to="/migration-checker">GST 2.0 Migration Checker</Link>.
        </p>
      </section>

      <section>
        <h2>Frequently Asked Questions</h2>

        <h3>How many digits of HSN code are mandatory?</h3>
        <p>
          Businesses with turnover up to ₹5 crore need 4-digit HSN codes on B2B invoices. Above ₹5 crore,
          6-digit codes are mandatory on all invoices. For GSTR-1 filing, 6-digit codes are required for
          the HSN Summary section regardless of turnover.
        </p>

        <h3>What is the difference between HSN and SAC codes?</h3>
        <p>
          HSN codes classify goods and have 4–8 digits (e.g., 8517 for telephones). SAC codes classify
          services and have 6 digits starting with 99 (e.g., 998311 for management consulting). Both
          determine the applicable GST rate.
        </p>

        <h3>Where can I find the HSN code for my product?</h3>
        <p>
          Search on the CBIC website, the GST portal&apos;s HSN search tool, or use our free{" "}
          <Link to="/hsn-sac-finder">HSN/SAC Finder</Link>. You can also check your supplier&apos;s
          invoices or customs import documents for the HSN code.
        </p>

        <h3>What happens if I use the wrong HSN code?</h3>
        <p>
          Wrong HSN codes can lead to incorrect tax rates, ITC mismatches between buyer and seller,
          show-cause notices from the tax department, and penalties during audits. If you discover an
          error, file an amendment in the next return period.
        </p>

        <h3>Are HSN codes the same worldwide?</h3>
        <p>
          The first 6 digits are internationally standardized by the World Customs Organization (WCO)
          and used by 200+ countries. India adds 2 more digits for domestic classification, making
          it an 8-digit tariff code. The international portion helps in import/export classification.
        </p>
      </section>

      <section>
        <h2>Free HSN Code Tools</h2>
        <ul>
          <li><Link to="/hsn-sac-finder">HSN/SAC Finder</Link> — search codes by product name or description</li>
          <li><Link to="/calculator">GST Calculator</Link> — calculate GST with HSN-based rates</li>
          <li><Link to="/invoice-generator">Invoice Generator</Link> — create invoices with correct HSN codes</li>
          <li><Link to="/rate-comparison">Rate Comparison Tool</Link> — compare current vs proposed rates</li>
        </ul>
        <p>
          <Link to="/">Start using DoAide GST free →</Link>
        </p>
      </section>
    </article>
  );
}
