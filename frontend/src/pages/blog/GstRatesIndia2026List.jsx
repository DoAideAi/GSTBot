import { useEffect } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";

export default function GstRatesIndia2026List() {
  usePageTitle("GST Rates in India 2026: Complete List of All Slabs");

  useEffect(() => {
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.content = "Complete list of GST rates in India for 2026 under GST 2.0 — every slab from nil to 40% with goods and services in each, special rates for gold and diamonds, and what moved when the 12% and 28% slabs were abolished.";

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
        headline: "GST Rates in India 2026: Complete List of All Slabs",
        description: "Every GST slab in force in 2026 — 0%, 5%, 18% and 40%, plus the special rates for bullion and precious stones — with the goods and services under each.",
        url: "https://gst.doaide.com/blog/gst-rates-india-2026-complete-list",
        datePublished: "2026-10-22",
        dateModified: "2026-10-22",
        publisher: { "@type": "Organization", name: "DoAide" },
      },
      {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: [
          { "@type": "Question", name: "What are the GST slabs in India in 2026?", acceptedAnswer: { "@type": "Answer", text: "Under GST 2.0 there are three slabs plus nil: 5% for necessities, 18% for most goods and services, and 40% for luxury and demerit goods. Special rates continue for rough diamonds (0.25%) and gold and jewellery (3%)." } },
          { "@type": "Question", name: "What happened to the 12% and 28% GST slabs?", acceptedAnswer: { "@type": "Answer", text: "Both were abolished in the GST 2.0 rate rationalization. Items at 12% moved to 5% or 18%; items at 28% moved to 18% or 40% depending on whether they are mass-market or luxury/demerit goods." } },
          { "@type": "Question", name: "What is the GST rate on everyday food items?", acceptedAnswer: { "@type": "Answer", text: "Unbranded and fresh food — milk, vegetables, fruits, bread, eggs — is nil-rated. Packed and branded staples such as sugar, tea, edible oils and spices are at 5%. Most processed and packaged foods are at 18%." } },
          { "@type": "Question", name: "What attracts the 40% GST rate?", acceptedAnswer: { "@type": "Answer", text: "The 40% slab covers demerit and luxury goods: tobacco and pan masala, aerated and caffeinated drinks, cars above ₹20 lakh, motorcycles above 350cc, yachts and private aircraft." } },
          { "@type": "Question", name: "How do I find the GST rate for a specific product?", acceptedAnswer: { "@type": "Answer", text: "Look the product up by name or HSN code. DoAide's free HSN finder returns the code and current GST rate for thousands of goods and services, no login needed." } },
        ],
      },
    ]);
    return () => { if (script.parentNode) script.parentNode.removeChild(script); };
  }, []);

  return (
    <article className="blog-article">
      <h1>GST Rates in India 2026: Complete List of All Slabs</h1>
      <p className="blog-meta">Updated October 2026 · 9 min read</p>

      <section>
        <p>
          GST 2.0 collapsed India&apos;s five-slab structure into three working rates plus
          nil. This is the complete 2026 picture — every slab, what sits in it, the special
          rates that survive outside the slabs, and where the old 12% and 28% goods went.
          To check one specific product, the fastest route is the{" "}
          <Link to="/hsn">HSN code finder</Link>; to compute tax on an amount, the{" "}
          <Link to="/calculator">GST calculator</Link>.
        </p>
      </section>

      <section>
        <h2>All GST Slabs at a Glance</h2>
        <table className="comparison-table">
          <thead>
            <tr><th>Rate</th><th>Category</th><th>Typical items</th></tr>
          </thead>
          <tbody>
            <tr><td><strong>0% (Nil)</strong></td><td>Essentials</td><td>Fresh food, milk, bread, eggs, books, healthcare, education, health &amp; life insurance</td></tr>
            <tr><td><strong>0.25%</strong></td><td>Special</td><td>Rough diamonds and unworked precious stones</td></tr>
            <tr><td><strong>3%</strong></td><td>Special</td><td>Gold, silver, platinum and jewellery</td></tr>
            <tr><td><strong>5%</strong></td><td>Necessities</td><td>Packed staples, tea, sugar, spices, footwear &amp; apparel (mass-market), public transport, economy air travel, restaurants, jewellery making charges</td></tr>
            <tr><td><strong>18%</strong></td><td>Standard</td><td>Electronics, smartphones, cement, furniture, IT &amp; professional services, telecom, financial services, commercial rent, most processed food</td></tr>
            <tr><td><strong>40%</strong></td><td>Luxury &amp; demerit</td><td>Tobacco, pan masala, aerated drinks, cars above ₹20 lakh, bikes above 350cc, yachts</td></tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>0% — Nil-Rated and Exempt</h2>
        <ul>
          <li>Fresh fruits, vegetables, milk, curd, eggs, unbranded cereals and flour</li>
          <li>Bread, salt, jaggery</li>
          <li>Printed books, newspapers, children&apos;s drawing books</li>
          <li>Healthcare by clinical establishments; education up to higher secondary</li>
          <li>Health insurance and life insurance premiums</li>
          <li>Residential rent to individuals (see the <Link to="/blog/gst-on-rental-income">rental income guide</Link>)</li>
        </ul>
      </section>

      <section>
        <h2>5% — Common Necessities</h2>
        <ul>
          <li>Packed and branded food staples: sugar, tea, coffee, edible oils, spices, paneer</li>
          <li>Mass-market apparel and footwear</li>
          <li>Domestic LPG, agricultural implements, fertilizers</li>
          <li>Public transport, rail tickets, economy-class air travel, metered cabs</li>
          <li>Restaurants (standalone, without ITC)</li>
          <li>Life-saving drugs, cancer medicines, medical devices (most)</li>
          <li>Under-construction homes effectively 1% (affordable) and 5% (other) — see the <Link to="/gst-on-real-estate">real estate calculator</Link></li>
        </ul>
      </section>

      <section>
        <h2>18% — The Standard Rate</h2>
        <p>Most of the economy sits here. Highlights:</p>
        <ul>
          <li>Electronics: smartphones, laptops, TVs, cameras, appliances</li>
          <li>Construction inputs: cement, paints, tiles, steel products</li>
          <li>All standard services: IT, consulting, legal, accounting, telecom, banking and financial services, advertising</li>
          <li>Commercial property rent and co-working</li>
          <li>Processed and packaged foods, chocolates, ice cream</li>
          <li>Hotels (most tariffs), outdoor catering</li>
          <li>Two-wheelers up to 350cc and cars below the luxury threshold</li>
        </ul>
      </section>

      <section>
        <h2>40% — Luxury and Demerit Goods</h2>
        <ul>
          <li>Tobacco products, cigarettes, pan masala, gutkha</li>
          <li>Aerated and caffeinated beverages</li>
          <li>Cars above ₹20 lakh; motorcycles above 350cc</li>
          <li>Yachts, private aircraft, betting and casinos</li>
        </ul>
        <p>
          The compensation cess that used to ride on top of 28% was phased out when the slab
          was abolished — the 40% rate is now the whole tax.
        </p>
      </section>

      <section>
        <h2>Special Rates Outside the Slabs</h2>
        <ul>
          <li><strong>0.25%</strong> — rough diamonds and unworked precious stones</li>
          <li><strong>3%</strong> — gold, silver, platinum, jewellery (making charges at 5% — the <Link to="/gst-on-gold">GST on gold calculator</Link> handles both legs)</li>
          <li><strong>Effective 1% / 5%</strong> — under-construction residential property, after the one-third land abatement</li>
        </ul>
      </section>

      <section>
        <h2>Where the Old 12% and 28% Goods Went</h2>
        <table className="comparison-table">
          <thead>
            <tr><th>Previously</th><th>Now</th><th>Examples</th></tr>
          </thead>
          <tbody>
            <tr><td>12%</td><td>5%</td><td>Butter, ghee, packaged dry fruits, umbrellas, bicycles</td></tr>
            <tr><td>12%</td><td>18%</td><td>Business-class air travel, branded garments above ₹2,500</td></tr>
            <tr><td>28%</td><td>18%</td><td>ACs, dishwashers, small cars, cement</td></tr>
            <tr><td>28% + cess</td><td>40%</td><td>Tobacco, aerated drinks, luxury cars</td></tr>
          </tbody>
        </table>
        <p>
          Migrating prices or contracts across the change? The{" "}
          <Link to="/rate-comparison">rate comparison tool</Link> shows old vs new side by
          side, and the <Link to="/guides/gst-rates-list-2026">rates list guide</Link> breaks
          the slabs down category by category.
        </p>
      </section>
    </article>
  );
}
