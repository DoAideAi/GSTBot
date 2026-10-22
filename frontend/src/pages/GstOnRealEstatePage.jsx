import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import PrintButton from "../components/PrintButton";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { formatINR } from "../lib/gstCalc";

// Effective rates on the agreement value. The residential 1%/5% are the
// notified effective rates (ITC forgone); commercial is 18% on the value less
// the one-third land abatement, which works out to 12% of the agreement value.
const PROPERTY_TYPES = [
  { key: "affordable", label: "Affordable housing (under construction)", rate: 1, itc: false, note: "Value up to ₹45 lakh, carpet area ≤60 sqm metro / ≤90 sqm non-metro. ITC not available to the builder." },
  { key: "other", label: "Other residential (under construction)", rate: 5, itc: false, note: "All under-construction homes that do not qualify as affordable. ITC not available to the builder." },
  { key: "commercial", label: "Commercial (under construction)", rate: 12, itc: true, note: "18% on the construction value after the one-third land abatement — effectively 12% of the agreement value. Builder can claim ITC." },
  { key: "ready", label: "Ready-to-move / resale", rate: 0, itc: false, note: "A completed property with a completion certificate is neither goods nor services — no GST. Only stamp duty and registration apply." },
];

export function calculateRealEstateGst(value, typeKey) {
  if (!Number.isFinite(value) || value <= 0) return null;
  const type = PROPERTY_TYPES.find((t) => t.key === typeKey);
  const gst = Math.round(value * type.rate) / 100;
  return {
    value: Math.round(value * 100) / 100,
    rate: type.rate,
    itc: type.itc,
    note: type.note,
    gst,
    total: Math.round((value + gst) * 100) / 100,
  };
}

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST on Real Estate Calculator",
  url: "https://gst.doaide.com/gst-on-real-estate",
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const FAQ_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    { "@type": "Question", name: "What is the GST rate on under-construction flats?", acceptedAnswer: { "@type": "Answer", text: "1% of the agreement value for affordable housing (up to ₹45 lakh, carpet area ≤60 sqm in metros / ≤90 sqm elsewhere) and 5% for other residential property. Both rates are without input tax credit to the builder." } },
    { "@type": "Question", name: "Is there GST on ready-to-move or resale property?", acceptedAnswer: { "@type": "Answer", text: "No. A property sold after the completion certificate is issued, and any resale property, is outside GST. You pay only stamp duty and registration charges." } },
    { "@type": "Question", name: "Is GST charged on the land portion of a property?", acceptedAnswer: { "@type": "Answer", text: "No. Land is neither goods nor services under GST. For construction, one-third of the total value is deemed to be land and excluded — the published 1%, 5% and effective 12% commercial rates already account for this." } },
    { "@type": "Question", name: "What is the GST rate on commercial property?", acceptedAnswer: { "@type": "Answer", text: "Under-construction commercial property attracts 18% GST on the construction value after the one-third land abatement — effectively 12% of the agreement value — and the builder can claim input tax credit." } },
    { "@type": "Question", name: "Do I pay both GST and stamp duty on a new flat?", acceptedAnswer: { "@type": "Answer", text: "Yes, for an under-construction property. GST (1% or 5%) is charged by the builder on instalments, while stamp duty and registration are state levies paid at registration. They are separate and both apply." } },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "GST on Real Estate Calculator" },
];

export default function GstOnRealEstatePage() {
  usePageTitle("GST on Real Estate Calculator — Flats, Property & Construction");

  const [amount, setAmount] = useState("");
  const [typeKey, setTypeKey] = useState("other");

  const result = useMemo(
    () => calculateRealEstateGst(parseFloat(amount), typeKey),
    [amount, typeKey],
  );

  const comparison = useMemo(() => {
    const value = parseFloat(amount);
    if (!Number.isFinite(value) || value <= 0) return null;
    return PROPERTY_TYPES.map((t) => ({ type: t, calc: calculateRealEstateGst(value, t.key) }));
  }, [amount]);

  return (
    <div className="tool-page">
      <SeoHead
        title="GST on Real Estate Calculator — Flats, Property & Construction"
        description="Calculate GST on under-construction flats, affordable housing, commercial property and ready-to-move homes. 1%, 5% and effective 12% rates with the land abatement built in. Free, no login."
        path="/gst-on-real-estate"
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb items={[{ label: "Home", to: "/" }, { label: "GST on Real Estate Calculator" }]} />
          <h1 className="tool-title">GST on Real Estate Calculator</h1>
          <p className="tool-subtitle">
            GST on property depends on one thing above all: whether it is still under
            construction. Pick the property type and get the exact tax. No sign-up required.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Agreement value (₹)
              <input
                type="number"
                className="calc-input"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="e.g. 6000000"
                min="0"
                step="0.01"
                inputMode="decimal"
                autoFocus
              />
            </label>

            <label className="calc-label">
              Property type
              <select
                className="calc-select"
                value={typeKey}
                onChange={(e) => setTypeKey(e.target.value)}
              >
                {PROPERTY_TYPES.map((t) => (
                  <option key={t.key} value={t.key}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>

            {result && (
              <div className="calc-result" aria-live="polite">
                <div className="calc-result-row">
                  <span>Agreement value</span>
                  <strong>{formatINR(result.value)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>GST ({result.rate}% effective)</span>
                  <strong>{formatINR(result.gst)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>Builder&apos;s input tax credit</span>
                  <strong>{result.itc ? "Available" : "Not available"}</strong>
                </div>
                <div className="calc-result-row calc-total">
                  <span>Total cost (incl. GST)</span>
                  <strong>{formatINR(result.total)}</strong>
                </div>
                <p className="calc-note">{result.note}</p>

                <div className="calc-result-actions">
                  <ShareButtons
                    path="/gst-on-real-estate"
                    text={`✅ GST on a ${formatINR(result.value)} property: ${formatINR(result.gst)} at ${result.rate}% — total ${formatINR(result.total)}, calculated free on DoAide GST`}
                  />
                  <PrintButton label="Print Result" />
                </div>
              </div>
            )}
          </div>

          {comparison && (
            <section className="tool-info">
              <h2>Same Property Across Categories</h2>
              <table className="calendar-table">
                <thead>
                  <tr>
                    <th>Property type</th>
                    <th>Rate</th>
                    <th>GST</th>
                  </tr>
                </thead>
                <tbody>
                  {comparison.map(({ type, calc }) => (
                    <tr key={type.key}>
                      <td>{type.label}</td>
                      <td>{type.rate}%</td>
                      <td>{formatINR(calc.gst)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          <EmailCapture
            source="gst-on-real-estate"
            heading="Never miss a GST deadline"
            subtext="Get free email reminders before every GST filing deadline."
            buttonLabel="Remind Me"
            compact
          />

          <section className="tool-info">
            <h2>How GST on Property Works</h2>
            <p>
              GST applies only while a property is <strong>under construction</strong> — the
              builder is supplying a construction service. Once the completion certificate is
              issued, the sale is a transfer of immovable property, which is outside GST
              entirely. That is why ready-to-move and resale homes carry no GST at all.
            </p>
            <h3>The Rates</h3>
            <ul>
              <li><strong>Affordable housing:</strong> 1% of the agreement value, builder cannot claim ITC</li>
              <li><strong>Other residential:</strong> 5% of the agreement value, builder cannot claim ITC</li>
              <li><strong>Commercial:</strong> 18% after the one-third land abatement — effectively 12% of the agreement value, with ITC</li>
              <li><strong>Ready-to-move / resale:</strong> nil</li>
            </ul>
            <p>
              The land portion is never taxed: one-third of the value is deemed land and
              excluded by abatement, which the effective rates above already build in. Stamp
              duty and registration are separate state levies and apply either way.
            </p>
            <h3>What Buyers Should Check</h3>
            <ul>
              <li>GST charged on each instalment at the correct rate for the category</li>
              <li>No GST on any instalment billed after the completion certificate</li>
              <li>Affordable-housing eligibility — ₹45 lakh cap and the carpet-area limits</li>
              <li>GST shown separately from stamp duty in the cost sheet</li>
            </ul>
            <p>
              Buying commercial property for a registered business? Check what credit you can
              take with the <Link to="/itc-calculator">ITC calculator</Link>, or work out the
              tax on anything else with the <Link to="/calculator">GST calculator</Link>.
            </p>
          </section>

          <InlineCTA variant="save" />
          <RelatedTools current="/gst-on-real-estate" />
          <CrossProductLinks page="gst-on-real-estate" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}
