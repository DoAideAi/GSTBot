import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import PrintButton from "../components/PrintButton";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { ewayBillRequired, KM_PER_DAY, looksLikeVehicleNumber, validityDays, validUntil } from "../lib/ewayBill";
import { calculate, formatINR, GST_SLABS } from "../lib/gstCalc";
import { STATE_CODES, stateForGstin } from "../lib/stateCodes";
import { gstinShapeError } from "../lib/validate";

/*
 * Prepares the contents of Form GST EWB-01 — Part A (parties, document, goods)
 * and Part B (vehicle) — and says whether one is needed and for how long.
 *
 * It does not issue a bill. Only the NIC portal assigns an EWB number, and a
 * page that printed something resembling one would be a document a driver
 * might carry and have the goods detained over. The output is labelled a draft
 * to key into ewaybillgst.gov.in, which is what it is.
 */

const MODES = [
  { key: "road", label: "Road" },
  { key: "rail", label: "Rail" },
  { key: "air", label: "Air" },
  { key: "ship", label: "Ship" },
];

const DOC_TYPES = ["Tax Invoice", "Bill of Supply", "Delivery Challan", "Bill of Entry"];

const emptyParty = { name: "", gstin: "", address: "", state: "", unregistered: false };
const emptyItem = { description: "", hsn: "", qty: "1", unit: "NOS", value: "", gstRate: "18" };

const today = () => new Date().toISOString().slice(0, 10);

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "E-Way Bill Generator",
  url: "https://gst.doaide.com/eway-bill-generator",
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

export const FAQ_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "When is an e-way bill required?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "When goods are moved in a consignment whose value exceeds ₹50,000 — taxable value plus GST, excluding exempt goods. A consignment of exactly ₹50,000 does not need one. Job work and inter-state handicraft movements need one at any value.",
      },
    },
    {
      "@type": "Question",
      name: "How long is an e-way bill valid?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "One day for every 200 km or part of it for normal cargo, and one day for every 20 km for over-dimensional cargo. Each day ends at midnight of the day after generation, so a one-day bill made in the morning runs to the end of the next day.",
      },
    },
    {
      "@type": "Question",
      name: "What are Part A and Part B of an e-way bill?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Part A holds the supplier and recipient GSTINs, place of delivery, document number and date, HSN code, value of goods and reason for transport. Part B holds the vehicle number, or the transport document number for rail, air or ship.",
      },
    },
    {
      "@type": "Question",
      name: "Does this tool generate a valid e-way bill number?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "No. Only the government portal at ewaybillgst.gov.in issues an EWB number. This tool prepares and checks the Part A and Part B details so they can be entered there in one pass.",
      },
    },
    {
      "@type": "Question",
      name: "What do I enter for an unregistered recipient?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Enter URP (unregistered person) in place of the GSTIN, and choose the recipient's state, which decides whether the tax is IGST or CGST plus SGST.",
      },
    },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "E-Way Bill Generator" },
];

function PartyFields({ title, party, onChange, allowUrp }) {
  const error = !party.unregistered && gstinShapeError(party.gstin);
  return (
    <fieldset className="calc-card" style={{ border: "none", margin: 0 }}>
      <legend style={{ fontSize: "1.1rem", fontWeight: 600 }}>{title}</legend>
      <label className="calc-label">
        {title} name
        <input className="calc-input" value={party.name} onChange={(e) => onChange({ name: e.target.value })} />
      </label>
      <label className="calc-label">
        {title} GSTIN
        <input
          className="calc-input"
          value={party.unregistered ? "URP" : party.gstin}
          disabled={party.unregistered}
          maxLength={15}
          placeholder="e.g. 27AAPFU0939F1ZV"
          onChange={(e) => {
            const gstin = e.target.value.toUpperCase();
            const state = stateForGstin(gstin);
            onChange(state ? { gstin, state: state.code } : { gstin });
          }}
        />
        {error && <span role="alert" style={{ color: "#ef4444", fontSize: "0.85rem" }}>{error}</span>}
      </label>
      {allowUrp && (
        <label className="calc-checkbox-label">
          <input
            type="checkbox"
            checked={party.unregistered}
            onChange={(e) => onChange({ unregistered: e.target.checked, gstin: "" })}
          />
          Unregistered recipient (URP)
        </label>
      )}
      <label className="calc-label">
        {title} address
        <input className="calc-input" value={party.address} onChange={(e) => onChange({ address: e.target.value })} />
      </label>
      <label className="calc-label">
        {title} state
        <select className="calc-select" value={party.state} onChange={(e) => onChange({ state: e.target.value })}>
          <option value="">Select state</option>
          {STATE_CODES.map((s) => <option key={s.code} value={s.code}>{s.code} - {s.name}</option>)}
        </select>
      </label>
    </fieldset>
  );
}

export default function EwayBillGeneratorPage() {
  usePageTitle("E-Way Bill Generator — Prepare Part A & Part B Online, Free");

  const [supplier, setSupplier] = useState(emptyParty);
  const [recipient, setRecipient] = useState(emptyParty);
  const [docType, setDocType] = useState(DOC_TYPES[0]);
  const [docNo, setDocNo] = useState("");
  const [docDate, setDocDate] = useState(today);
  const [items, setItems] = useState([emptyItem]);
  const [mode, setMode] = useState("road");
  const [vehicleNo, setVehicleNo] = useState("");
  const [transportDocNo, setTransportDocNo] = useState("");
  const [transporterId, setTransporterId] = useState("");
  const [distance, setDistance] = useState("");
  const [overDimensional, setOverDimensional] = useState(false);
  const [generatedOn, setGeneratedOn] = useState(today);

  const updateItem = (i, patch) => setItems((prev) => prev.map((it, j) => (j === i ? { ...it, ...patch } : it)));

  // Without both states the split is unknown, and guessing intra-state would
  // put CGST+SGST on a draft that the portal will then reject as IGST.
  const interstate = supplier.state && recipient.state ? supplier.state !== recipient.state : null;

  const totals = useMemo(() => {
    // A negative value is the only input calculate() refuses; it counts as nil
    // rather than knocking the whole consignment total out.
    const lines = items.map((it) => calculate(Math.max(0, parseFloat(it.value) || 0), parseFloat(it.gstRate), { interstate: interstate === true }));
    const sum = (k) => Math.round(lines.reduce((a, l) => a + l[k], 0) * 100) / 100;
    return { lines, taxable: sum("taxable"), cgst: sum("cgst"), sgst: sum("sgst"), igst: sum("igst"), total: sum("total") };
  }, [items, interstate]);

  const km = parseFloat(distance);
  const required = totals.total > 0 ? ewayBillRequired(totals.total) : null;
  const days = validityDays(km, overDimensional);
  const until = validUntil(generatedOn, days);
  const vehicleWarning = mode === "road" && vehicleNo && !looksLikeVehicleNumber(vehicleNo);
  const transporterError = transporterId && gstinShapeError(transporterId);

  const ready = supplier.name && recipient.name && docNo && totals.total > 0;

  return (
    <div className="tool-page">
      <SeoHead
        title="E-Way Bill Generator — Prepare Part A & Part B Online, Free"
        description="Prepare a GST e-way bill: supplier and recipient GSTINs, goods with HSN and tax, vehicle and transporter details. Checks the ₹50,000 threshold and works out validity from distance."
        path="/eway-bill-generator"
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">E-Way Bill Generator</h1>
          <p className="tool-subtitle">
            Prepare Part A and Part B of an e-way bill, check whether one is needed, and see how
            long it stays valid. Free, no sign-up.
          </p>

          <PartyFields title="Supplier" party={supplier} onChange={(p) => setSupplier((s) => ({ ...s, ...p }))} />
          <PartyFields title="Recipient" party={recipient} allowUrp onChange={(p) => setRecipient((s) => ({ ...s, ...p }))} />

          <div className="calc-card">
            <h2 style={{ fontSize: "1.1rem", fontWeight: 600 }}>Document</h2>
            <label className="calc-label">
              Document type
              <select className="calc-select" value={docType} onChange={(e) => setDocType(e.target.value)}>
                {DOC_TYPES.map((d) => <option key={d}>{d}</option>)}
              </select>
            </label>
            <label className="calc-label">
              Document number
              <input className="calc-input" value={docNo} onChange={(e) => setDocNo(e.target.value)} maxLength={16} />
            </label>
            <label className="calc-label">
              Document date
              <input type="date" className="calc-input" value={docDate} onChange={(e) => setDocDate(e.target.value)} />
            </label>
          </div>

          <div className="calc-card">
            <h2 style={{ fontSize: "1.1rem", fontWeight: 600 }}>
              Goods
              {interstate === true && <span style={{ fontSize: "0.8rem", fontWeight: 400, marginLeft: "0.5rem" }}>(Inter-state — IGST)</span>}
              {interstate === false && <span style={{ fontSize: "0.8rem", fontWeight: 400, marginLeft: "0.5rem" }}>(Intra-state — CGST+SGST)</span>}
            </h2>
            {items.map((it, i) => (
              <div key={i} role="group" aria-label={`Item ${i + 1}`} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: "0.5rem", marginBottom: "0.75rem" }}>
                <label className="calc-label">Description<input className="calc-input" value={it.description} onChange={(e) => updateItem(i, { description: e.target.value })} /></label>
                <label className="calc-label">HSN<input className="calc-input" value={it.hsn} inputMode="numeric" maxLength={8} onChange={(e) => updateItem(i, { hsn: e.target.value.replace(/\D/g, "") })} /></label>
                <label className="calc-label">Quantity<input type="number" className="calc-input" value={it.qty} min="0" onChange={(e) => updateItem(i, { qty: e.target.value })} /></label>
                <label className="calc-label">Taxable value (₹)<input type="number" className="calc-input" value={it.value} min="0" step="0.01" onChange={(e) => updateItem(i, { value: e.target.value })} /></label>
                <label className="calc-label">
                  GST rate
                  <select className="calc-select" value={it.gstRate} onChange={(e) => updateItem(i, { gstRate: e.target.value })}>
                    {GST_SLABS.map((r) => <option key={r} value={String(r)}>{r}%</option>)}
                  </select>
                </label>
                {items.length > 1 && (
                  <button type="button" className="calc-mode-btn" onClick={() => setItems((prev) => prev.filter((_, j) => j !== i))}>Remove</button>
                )}
              </div>
            ))}
            <button type="button" className="calc-mode-btn" onClick={() => setItems((prev) => [...prev, emptyItem])}>+ Add item</button>
            {items.some((it) => it.hsn && it.hsn.length < 4) && (
              <p className="calc-note">The portal needs at least 4 HSN digits, or 6 above ₹5 crore turnover.</p>
            )}
          </div>

          <div className="calc-card">
            <h2 style={{ fontSize: "1.1rem", fontWeight: 600 }}>Transport (Part B)</h2>
            <label className="calc-label">
              Mode
              <select className="calc-select" value={mode} onChange={(e) => setMode(e.target.value)}>
                {MODES.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
              </select>
            </label>
            {mode === "road" ? (
              <label className="calc-label">
                Vehicle number
                <input className="calc-input" value={vehicleNo} placeholder="e.g. MH12AB1234" onChange={(e) => setVehicleNo(e.target.value.toUpperCase())} />
                {vehicleWarning && <span style={{ color: "#f59e42", fontSize: "0.85rem" }}>That does not look like a registration number — check it before entering it on the portal.</span>}
              </label>
            ) : (
              <label className="calc-label">
                Transport document number (RR / airway bill / bill of lading)
                <input className="calc-input" value={transportDocNo} onChange={(e) => setTransportDocNo(e.target.value)} />
              </label>
            )}
            <label className="calc-label">
              Transporter ID (GSTIN or TRANSIN, optional)
              <input className="calc-input" value={transporterId} maxLength={15} onChange={(e) => setTransporterId(e.target.value.toUpperCase())} />
              {transporterError && <span role="alert" style={{ color: "#ef4444", fontSize: "0.85rem" }}>{transporterError}</span>}
            </label>
            <label className="calc-label">
              Approximate distance (km)
              <input type="number" className="calc-input" value={distance} min="0" onChange={(e) => setDistance(e.target.value)} />
            </label>
            <label className="calc-checkbox-label">
              <input type="checkbox" checked={overDimensional} onChange={(e) => setOverDimensional(e.target.checked)} />
              Over-dimensional cargo ({KM_PER_DAY.odc} km a day instead of {KM_PER_DAY.normal})
            </label>
            <label className="calc-label">
              Generation date
              <input type="date" className="calc-input" value={generatedOn} onChange={(e) => setGeneratedOn(e.target.value)} />
            </label>
          </div>

          {required !== null && (
            <div className="calc-result" aria-live="polite">
              <div className="calc-result-row calc-total" style={{ color: required ? "#f59e42" : "#34d399" }}>
                <span>E-Way Bill</span>
                <strong>{required ? "Required" : "Not required"}</strong>
              </div>
              <p className="calc-note">
                Consignment value {formatINR(totals.total)} {required ? "exceeds" : "does not exceed"} ₹50,000.
                {!required && " Job work and inter-state handicraft movements still need one at any value — see the "}
                {!required && <Link to="/eway-bill">e-way bill checker</Link>}
                {!required && "."}
              </p>
              {days && (
                <div className="calc-result-row">
                  <span>Validity ({km} km{overDimensional ? ", over-dimensional" : ""})</span>
                  <strong>{days} day{days > 1 ? "s" : ""}{until && `, until midnight ${until}`}</strong>
                </div>
              )}
            </div>
          )}

          {ready && (
            <section className="calc-card" aria-label="E-way bill draft">
              <h2 style={{ fontSize: "1.1rem", fontWeight: 600 }}>Draft — Form GST EWB-01</h2>
              <p className="calc-note">
                Not an e-way bill. Enter these details at ewaybillgst.gov.in to get the EWB number
                the transporter must carry.
              </p>
              <h3>Part A</h3>
              <ul>
                <li>Supplier: {supplier.name}, GSTIN {supplier.gstin || "—"}{supplier.address && `, ${supplier.address}`}</li>
                <li>Recipient: {recipient.name}, GSTIN {recipient.unregistered ? "URP" : recipient.gstin || "—"}{recipient.address && `, ${recipient.address}`}</li>
                <li>Document: {docType} {docNo} dated {docDate}</li>
              </ul>
              <div style={{ overflowX: "auto" }}>
                <table className="due-dates-table">
                  <thead>
                    <tr><th>Description</th><th>HSN</th><th>Qty</th><th>Taxable</th><th>Rate</th><th>CGST</th><th>SGST</th><th>IGST</th></tr>
                  </thead>
                  <tbody>
                    {items.map((it, i) => (
                      <tr key={i}>
                        <td>{it.description}</td><td>{it.hsn}</td><td>{it.qty}</td>
                        <td>{formatINR(totals.lines[i].taxable)}</td><td>{it.gstRate}%</td>
                        <td>{formatINR(totals.lines[i].cgst)}</td><td>{formatINR(totals.lines[i].sgst)}</td><td>{formatINR(totals.lines[i].igst)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <ul>
                <li>Taxable value: {formatINR(totals.taxable)}</li>
                <li>CGST {formatINR(totals.cgst)} · SGST {formatINR(totals.sgst)} · IGST {formatINR(totals.igst)}</li>
                <li><strong>Total consignment value: {formatINR(totals.total)}</strong></li>
              </ul>
              <h3>Part B</h3>
              <ul>
                <li>Mode: {MODES.find((m) => m.key === mode).label}</li>
                <li>{mode === "road" ? `Vehicle number: ${vehicleNo || "—"}` : `Transport document: ${transportDocNo || "—"}`}</li>
                <li>Transporter ID: {transporterId || "—"}</li>
                <li>Distance: {km > 0 ? `${km} km` : "—"}</li>
              </ul>
              <div className="calc-result-actions">
                <PrintButton label="Print Draft" />
              </div>
            </section>
          )}

          <ShareButtons path="/eway-bill-generator" text="Prepare a GST e-way bill free on DoAide GST" />

          <section className="tool-info">
            <h2>Frequently Asked Questions</h2>
            {FAQ_SCHEMA.mainEntity.map((q) => (
              <div key={q.name}>
                <h3>{q.name}</h3>
                <p>{q.acceptedAnswer.text}</p>
              </div>
            ))}
            <p>
              Building the invoice first? Use the <Link to="/invoice-generator">GST invoice generator</Link>,
              then copy its number and items here.
            </p>
          </section>

          <InlineCTA variant="save" />
          <RelatedTools current="/eway-bill-generator" />
          <CrossProductLinks page="eway-bill" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}
