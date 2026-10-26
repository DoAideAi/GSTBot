import { Link, useParams } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import DoAideFooter from "../components/DoAideFooter";
import RelatedTools from "../components/RelatedTools";
import SeoHead, { BASE_URL } from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { findProductRate, getByCode, productSlug, relatedProducts, searchHSN } from "../lib/hsnData";

function capitalize(str) {
  return str.replace(/\b\w/g, (c) => c.toUpperCase());
}

function exampleAmount(rate) {
  if (rate === 0) return null;
  const base = 10000;
  const tax = (base * rate) / 100;
  return { base, rate, tax, total: base + tax };
}

function buildFaqSchema(display, match) {
  const questions = [
    {
      "@type": "Question",
      name: `What is the GST rate on ${display}?`,
      acceptedAnswer: {
        "@type": "Answer",
        text: `The GST rate on ${display} is ${match.rate}% under HSN code ${match.hsn}. ${match.rate > 0 && !match.interstate ? `For intra-state supply: CGST ${match.rate / 2}% + SGST ${match.rate / 2}%. For inter-state supply: IGST ${match.rate}%.` : ""}`,
      },
    },
    {
      "@type": "Question",
      name: `What is the HSN code for ${display}?`,
      acceptedAnswer: {
        "@type": "Answer",
        text: `The HSN code for ${display} is ${match.hsn}. This code is used on GST invoices to classify ${display.toLowerCase()} for tax purposes.`,
      },
    },
  ];
  if (match.rate > 0) {
    const ex = exampleAmount(match.rate);
    questions.push({
      "@type": "Question",
      name: `How to calculate GST on ${display}?`,
      acceptedAnswer: {
        "@type": "Answer",
        text: `GST on ${display} is calculated at ${match.rate}%. For example, on a taxable value of ₹${ex.base.toLocaleString("en-IN")}, GST = ₹${ex.tax.toLocaleString("en-IN")}, making the total ₹${ex.total.toLocaleString("en-IN")}.`,
      },
    });
  }
  return { "@context": "https://schema.org", "@type": "FAQPage", mainEntity: questions };
}

export default function GstRatePage() {
  const { product } = useParams();
  const match = findProductRate(product);
  const display = capitalize(match ? match.product : (product || "").replace(/-/g, " "));
  usePageTitle(`GST Rate on ${display} — HSN Code & Tax Breakdown`);

  const related = match ? searchHSN(match.product, { limit: 5 }) : searchHSN(display, { limit: 5 });
  const linked = relatedProducts(product, { limit: 5 });
  const hsnEntry = match ? getByCode(match.hsn) : null;
  const example = match ? exampleAmount(match.rate) : null;

  const path = `/gst-rate/${product}`;
  const seoTitle = match
    ? `GST Rate for ${display} - HSN Code ${match.hsn} | DoAide`
    : `GST Rate for ${display} | DoAide`;
  const seoDesc = match
    ? `GST on ${display} is ${match.rate}% (HSN ${match.hsn}). CGST ${match.rate / 2}%, SGST ${match.rate / 2}%, IGST ${match.rate}%. Calculate GST, find related HSN codes.`
    : `Find the GST rate and HSN code for ${display}. Use our free GST calculator and HSN code search.`;

  const jsonLd = match ? [
    {
      "@context": "https://schema.org",
      "@type": "Product",
      name: display,
      description: hsnEntry ? hsnEntry.desc : display,
      category: hsnEntry ? hsnEntry.category : undefined,
      additionalProperty: [
        { "@type": "PropertyValue", name: "HSN Code", value: match.hsn },
        { "@type": "PropertyValue", name: "GST Rate", value: `${match.rate}%` },
      ],
    },
    buildFaqSchema(display, match),
  ] : [];

  const breadcrumbs = [
    { name: "Home", url: BASE_URL },
    { name: "HSN Code Finder", url: `${BASE_URL}/hsn` },
    { name: `GST on ${display}` },
  ];

  return (
    <div className="tool-page">
      <SeoHead
        title={seoTitle}
        description={seoDesc}
        path={path}
        jsonLd={jsonLd}
        breadcrumbs={breadcrumbs}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb items={[
            { label: "Home", to: "/" },
            { label: "HSN Code Finder", to: "/hsn" },
            { label: `GST on ${display}` },
          ]} />
          <h1 className="tool-title">GST Rate on {display}</h1>

          {match ? (
            <div className="calc-card">
              <div className="rate-hero">
                <div className="rate-big">{match.rate}%</div>
                <p className="rate-label">GST Rate</p>
              </div>
              <dl className="lookup-details">
                <dt>Product</dt>
                <dd>{display}</dd>
                <dt>HSN/SAC Code</dt>
                <dd className="lookup-gstin-value">{match.hsn}</dd>
                <dt>GST Rate</dt>
                <dd>{match.rate}%</dd>
                {!match.interstate && match.rate > 0 && (
                  <>
                    <dt>CGST</dt>
                    <dd>{match.rate / 2}%</dd>
                    <dt>SGST</dt>
                    <dd>{match.rate / 2}%</dd>
                    <dt>IGST</dt>
                    <dd>{match.rate}%</dd>
                  </>
                )}
                {hsnEntry && (
                  <>
                    <dt>Category</dt>
                    <dd>{hsnEntry.category}</dd>
                  </>
                )}
              </dl>

              {example && (
                <section className="rate-example">
                  <h2>Example GST Calculation</h2>
                  <table className="hsn-table">
                    <tbody>
                      <tr>
                        <td>Taxable Value</td>
                        <td className="hsn-rate">₹{example.base.toLocaleString("en-IN")}</td>
                      </tr>
                      <tr>
                        <td>GST @ {example.rate}%</td>
                        <td className="hsn-rate">₹{example.tax.toLocaleString("en-IN")}</td>
                      </tr>
                      {!match.interstate && (
                        <>
                          <tr>
                            <td>  ↳ CGST @ {example.rate / 2}%</td>
                            <td className="hsn-rate">₹{(example.tax / 2).toLocaleString("en-IN")}</td>
                          </tr>
                          <tr>
                            <td>  ↳ SGST @ {example.rate / 2}%</td>
                            <td className="hsn-rate">₹{(example.tax / 2).toLocaleString("en-IN")}</td>
                          </tr>
                        </>
                      )}
                      <tr>
                        <td><strong>Total</strong></td>
                        <td className="hsn-rate"><strong>₹{example.total.toLocaleString("en-IN")}</strong></td>
                      </tr>
                    </tbody>
                  </table>
                </section>
              )}

              <p className="rate-calc-link">
                <Link to={`/calculator?rate=${match.rate}`}>
                  Calculate GST on {display} →
                </Link>
              </p>
              <ShareButtons
                path={`/gst-rate/${product}`}
                text={`GST on ${display} is ${match.rate}% (HSN ${match.hsn}). Check any product's GST rate on DoAide GST`}
              />
            </div>
          ) : (
            <div className="calc-card">
              <p>We don't have a specific rate listing for "{display}" yet.</p>
              <p>
                <Link to="/hsn">Search the HSN code directory →</Link>
              </p>
              <p>
                <Link to="/calculator">Use the GST calculator →</Link>
              </p>
            </div>
          )}

          {related.length > 0 && (
            <section className="tool-info">
              <h2>Related HSN Codes</h2>
              <table className="hsn-table">
                <thead>
                  <tr>
                    <th>HSN Code</th>
                    <th>Description</th>
                    <th>GST Rate</th>
                  </tr>
                </thead>
                <tbody>
                  {related.map((item) => (
                    <tr key={item.code}>
                      <td className="hsn-code">{item.code}</td>
                      <td>{item.desc}</td>
                      <td className="hsn-rate">{item.rate}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {linked.length > 0 && (
            <section className="tool-info">
              <h2>Check GST Rates for Similar Products</h2>
              <ul className="seo-links">
                {linked.map((p) => (
                  <li key={p.product}>
                    <Link to={`/gst-rate/${productSlug(p.product)}`}>
                      GST on {capitalize(p.product)} — {p.rate}%
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <RelatedTools current={`/gst-rate/${product}`} />
        </div>
      </main>
      <DoAideFooter />
    </div>
  );
}
