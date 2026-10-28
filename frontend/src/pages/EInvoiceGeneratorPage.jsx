import { useCallback, useMemo, useState } from "react";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import ExitIntentPopup from "../components/ExitIntentPopup";
import RelatedTools from "../components/RelatedTools";
import SaveResultsCTA from "../components/SaveResultsCTA";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { formatINR } from "../lib/gstCalc";
import { track } from "../lib/track";

const SUPPLY_TYPES = [
  { code: "B2B", label: "B2B — Regular" },
  { code: "SEZWP", label: "SEZ — With Payment" },
  { code: "SEZWOP", label: "SEZ — Without Payment" },
  { code: "EXPWP", label: "Export — With Payment" },
  { code: "EXPWOP", label: "Export — Without Payment" },
  { code: "DEXP", label: "Deemed Export" },
];

const DOC_TYPES = [
  { code: "INV", label: "Invoice" },
  { code: "CRN", label: "Credit Note" },
  { code: "DBN", label: "Debit Note" },
];

const STATE_CODES = [
  { code: "01", name: "Jammu & Kashmir" }, { code: "02", name: "Himachal Pradesh" },
  { code: "03", name: "Punjab" }, { code: "04", name: "Chandigarh" },
  { code: "05", name: "Uttarakhand" }, { code: "06", name: "Haryana" },
  { code: "07", name: "Delhi" }, { code: "08", name: "Rajasthan" },
  { code: "09", name: "Uttar Pradesh" }, { code: "10", name: "Bihar" },
  { code: "11", name: "Sikkim" }, { code: "12", name: "Arunachal Pradesh" },
  { code: "13", name: "Nagaland" }, { code: "14", name: "Manipur" },
  { code: "15", name: "Mizoram" }, { code: "16", name: "Tripura" },
  { code: "17", name: "Meghalaya" }, { code: "18", name: "Assam" },
  { code: "19", name: "West Bengal" }, { code: "20", name: "Jharkhand" },
  { code: "21", name: "Odisha" }, { code: "22", name: "Chhattisgarh" },
  { code: "23", name: "Madhya Pradesh" }, { code: "24", name: "Gujarat" },
  { code: "27", name: "Maharashtra" }, { code: "29", name: "Karnataka" },
  { code: "30", name: "Goa" }, { code: "32", name: "Kerala" },
  { code: "33", name: "Tamil Nadu" }, { code: "36", name: "Telangana" },
  { code: "37", name: "Andhra Pradesh" },
];

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST E-Invoice JSON Generator",
  url: "https://gst.doaide.com/e-invoice-generator",
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const FAQ_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "What is e-invoice under GST?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "E-invoicing requires businesses above the turnover threshold to generate an IRN for every B2B invoice via the Invoice Registration Portal (IRP). The IRP validates the data and returns a signed QR code.",
      },
    },
    {
      "@type": "Question",
      name: "Who needs to generate e-invoices?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Businesses with aggregate turnover above ₹5 crore in any year from 2017-18 onwards must generate e-invoices for all B2B, export, and SEZ supplies. The threshold has been lowered progressively since introduction.",
      },
    },
    {
      "@type": "Question",
      name: "What data format does e-invoice use?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "The e-invoice schema (version 1.1 by GSTN) includes sections for transaction details, document details, seller, buyer, item list with HSN and tax breakdown, and value details including assessable value and total tax.",
      },
    },
    {
      "@type": "Question",
      name: "What happens if e-invoice is not generated?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Non-compliance attracts a penalty of 100% of tax due or ₹10,000 (whichever is higher) under Section 122 of the CGST Act. The buyer also cannot claim ITC on invoices that required an IRN but lack one.",
      },
    },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "E-Invoice JSON Generator" },
];

function today() {
  const d = new Date();
  return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}/${d.getFullYear()}`;
}

export default function EInvoiceGeneratorPage() {
  usePageTitle("GST E-Invoice JSON Generator — Free Tool");

  const [sellerGstin, setSellerGstin] = useState("");
  const [sellerName, setSellerName] = useState("");
  const [sellerState, setSellerState] = useState("");
  const [sellerPin, setSellerPin] = useState("");

  const [buyerGstin, setBuyerGstin] = useState("");
  const [buyerName, setBuyerName] = useState("");
  const [buyerState, setBuyerState] = useState("");
  const [buyerPin, setBuyerPin] = useState("");

  const [supplyType, setSupplyType] = useState("B2B");
  const [docType, setDocType] = useState("INV");
  const [docNo, setDocNo] = useState("");
  const [docDate, setDocDate] = useState(today());

  const [itemDesc, setItemDesc] = useState("");
  const [hsnCode, setHsnCode] = useState("");
  const [qty, setQty] = useState("");
  const [unitPrice, setUnitPrice] = useState("");
  const [gstRate, setGstRate] = useState("18");

  const isInterstate = useMemo(
    () => sellerState && buyerState && sellerState !== buyerState,
    [sellerState, buyerState],
  );

  const lineItem = useMemo(() => {
    const q = parseFloat(qty);
    const price = parseFloat(unitPrice);
    const rate = parseFloat(gstRate);
    if (!Number.isFinite(q) || q <= 0) return null;
    if (!Number.isFinite(price) || price < 0) return null;
    if (!Number.isFinite(rate) || rate < 0) return null;

    const assessableValue = Math.round(q * price * 100) / 100;
    const totalTax = Math.round(assessableValue * rate) / 100;
    const half = Math.round((totalTax / 2) * 100) / 100;

    return {
      assessableValue,
      cgstAmt: isInterstate ? 0 : half,
      sgstAmt: isInterstate ? 0 : Math.round((totalTax - half) * 100) / 100,
      igstAmt: isInterstate ? totalTax : 0,
      totalItemValue: Math.round((assessableValue + totalTax) * 100) / 100,
    };
  }, [qty, unitPrice, gstRate, isInterstate]);

  const jsonPayload = useMemo(() => {
    if (!sellerGstin || !buyerGstin || !docNo || !lineItem || !itemDesc || !hsnCode) return null;

    const rate = parseFloat(gstRate);

    return {
      Version: "1.1",
      TranDtls: {
        TaxSch: "GST",
        SupTyp: supplyType,
        RegRev: "N",
        IgstOnIntra: "N",
      },
      DocDtls: {
        Typ: docType,
        No: docNo,
        Dt: docDate,
      },
      SellerDtls: {
        Gstin: sellerGstin.toUpperCase(),
        LglNm: sellerName,
        Addr1: "Address Line 1",
        Loc: "City",
        Pin: Number(sellerPin) || 100001,
        Stcd: sellerState,
      },
      BuyerDtls: {
        Gstin: buyerGstin.toUpperCase(),
        LglNm: buyerName,
        Addr1: "Address Line 1",
        Loc: "City",
        Pin: Number(buyerPin) || 100001,
        Stcd: buyerState,
        Pos: buyerState,
      },
      ItemList: [
        {
          SlNo: "1",
          PrdDesc: itemDesc,
          IsServc: "N",
          HsnCd: hsnCode,
          Qty: parseFloat(qty),
          Unit: "NOS",
          UnitPrice: parseFloat(unitPrice),
          TotAmt: lineItem.assessableValue,
          Discount: 0,
          AssAmt: lineItem.assessableValue,
          GstRt: rate,
          IgstAmt: lineItem.igstAmt,
          CgstAmt: lineItem.cgstAmt,
          SgstAmt: lineItem.sgstAmt,
          CesRt: 0,
          CesAmt: 0,
          TotItemVal: lineItem.totalItemValue,
        },
      ],
      ValDtls: {
        AssVal: lineItem.assessableValue,
        CgstVal: lineItem.cgstAmt,
        SgstVal: lineItem.sgstAmt,
        IgstVal: lineItem.igstAmt,
        CesVal: 0,
        Discount: 0,
        OthChrg: 0,
        TotInvVal: lineItem.totalItemValue,
      },
    };
  }, [
    sellerGstin, sellerName, sellerState, sellerPin,
    buyerGstin, buyerName, buyerState, buyerPin,
    supplyType, docType, docNo, docDate,
    itemDesc, hsnCode, gstRate, qty, unitPrice, lineItem,
  ]);

  const jsonText = useMemo(
    () => (jsonPayload ? JSON.stringify(jsonPayload, null, 2) : ""),
    [jsonPayload],
  );

  const handleCopy = useCallback(async () => {
    if (!jsonText) return;
    try {
      await navigator.clipboard.writeText(jsonText);
      track("einvoice_copy_json");
    } catch {
      const ta = document.createElement("textarea");
      ta.value = jsonText;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
  }, [jsonText]);

  const handleDownload = useCallback(() => {
    if (!jsonText) return;
    const blob = new Blob([jsonText], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `einvoice-${docNo || "draft"}.json`;
    a.click();
    URL.revokeObjectURL(url);
    track("einvoice_download_json");
  }, [jsonText, docNo]);

  return (
    <div className="tool-page">
      <SeoHead
        title="GST E-Invoice JSON Generator — Free Online Tool"
        description="Generate e-invoice data in the GSTN-specified schema format. Fill in seller, buyer, and item details to create IRN-ready structured data. Copy or download. Free, no login required."
        path="/e-invoice-generator"
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">E-Invoice JSON Generator</h1>
          <p className="tool-subtitle">
            Generate e-invoice JSON in the GSTN schema format. Fill details and download the JSON for IRP submission. No sign-up required.
          </p>

          <div className="calc-card">
            <h3 style={{ margin: "0 0 0.75rem", fontSize: "1rem" }}>Transaction Details</h3>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
              <label className="calc-label">
                Supply Type
                <select className="calc-select" value={supplyType} onChange={(e) => setSupplyType(e.target.value)}>
                  {SUPPLY_TYPES.map((s) => <option key={s.code} value={s.code}>{s.label}</option>)}
                </select>
              </label>
              <label className="calc-label">
                Document Type
                <select className="calc-select" value={docType} onChange={(e) => setDocType(e.target.value)}>
                  {DOC_TYPES.map((d) => <option key={d.code} value={d.code}>{d.label}</option>)}
                </select>
              </label>
              <label className="calc-label">
                Document Number
                <input className="calc-input" value={docNo} onChange={(e) => setDocNo(e.target.value)} placeholder="e.g. INV-2026-001" />
              </label>
              <label className="calc-label">
                Document Date
                <input className="calc-input" value={docDate} onChange={(e) => setDocDate(e.target.value)} placeholder="DD/MM/YYYY" />
              </label>
            </div>

            <h3 style={{ margin: "1.25rem 0 0.75rem", fontSize: "1rem" }}>Seller Details</h3>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
              <label className="calc-label">
                Seller GSTIN
                <input className="calc-input" value={sellerGstin} onChange={(e) => setSellerGstin(e.target.value.toUpperCase())} placeholder="15-digit GSTIN" maxLength={15} spellCheck={false} />
              </label>
              <label className="calc-label">
                Legal Name
                <input className="calc-input" value={sellerName} onChange={(e) => setSellerName(e.target.value)} placeholder="Business legal name" />
              </label>
              <label className="calc-label">
                State
                <select className="calc-select" value={sellerState} onChange={(e) => setSellerState(e.target.value)}>
                  <option value="">— Select —</option>
                  {STATE_CODES.map((s) => <option key={s.code} value={s.code}>{s.code} — {s.name}</option>)}
                </select>
              </label>
              <label className="calc-label">
                PIN Code
                <input className="calc-input" type="number" value={sellerPin} onChange={(e) => setSellerPin(e.target.value)} placeholder="6-digit PIN" maxLength={6} />
              </label>
            </div>

            <h3 style={{ margin: "1.25rem 0 0.75rem", fontSize: "1rem" }}>Buyer Details</h3>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
              <label className="calc-label">
                Buyer GSTIN
                <input className="calc-input" value={buyerGstin} onChange={(e) => setBuyerGstin(e.target.value.toUpperCase())} placeholder="15-digit GSTIN" maxLength={15} spellCheck={false} />
              </label>
              <label className="calc-label">
                Legal Name
                <input className="calc-input" value={buyerName} onChange={(e) => setBuyerName(e.target.value)} placeholder="Business legal name" />
              </label>
              <label className="calc-label">
                State
                <select className="calc-select" value={buyerState} onChange={(e) => setBuyerState(e.target.value)}>
                  <option value="">— Select —</option>
                  {STATE_CODES.map((s) => <option key={s.code} value={s.code}>{s.code} — {s.name}</option>)}
                </select>
              </label>
              <label className="calc-label">
                PIN Code
                <input className="calc-input" type="number" value={buyerPin} onChange={(e) => setBuyerPin(e.target.value)} placeholder="6-digit PIN" maxLength={6} />
              </label>
            </div>

            <h3 style={{ margin: "1.25rem 0 0.75rem", fontSize: "1rem" }}>Item Details</h3>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
              <label className="calc-label">
                Description
                <input className="calc-input" value={itemDesc} onChange={(e) => setItemDesc(e.target.value)} placeholder="Item/service description" />
              </label>
              <label className="calc-label">
                HSN/SAC Code
                <input className="calc-input" value={hsnCode} onChange={(e) => setHsnCode(e.target.value)} placeholder="e.g. 84713010" maxLength={8} />
              </label>
              <label className="calc-label">
                Quantity
                <input className="calc-input" type="number" value={qty} onChange={(e) => setQty(e.target.value)} placeholder="1" min="0" step="1" inputMode="numeric" />
              </label>
              <label className="calc-label">
                Unit Price (₹)
                <input className="calc-input" type="number" value={unitPrice} onChange={(e) => setUnitPrice(e.target.value)} placeholder="Per unit price" min="0" step="0.01" inputMode="decimal" />
              </label>
              <label className="calc-label">
                GST Rate (%)
                <select className="calc-select" value={gstRate} onChange={(e) => setGstRate(e.target.value)}>
                  {[0, 0.25, 3, 5, 12, 18, 28].map((r) => <option key={r} value={r}>{r}%</option>)}
                </select>
              </label>
            </div>

            {lineItem && (
              <div className="calc-result" aria-live="polite" style={{ marginTop: "1rem" }}>
                <div className="calc-result-row">
                  <span>Assessable Value</span>
                  <strong>{formatINR(lineItem.assessableValue)}</strong>
                </div>
                {isInterstate ? (
                  <div className="calc-result-row">
                    <span>IGST ({gstRate}%)</span>
                    <strong>{formatINR(lineItem.igstAmt)}</strong>
                  </div>
                ) : (
                  <>
                    <div className="calc-result-row">
                      <span>CGST ({parseFloat(gstRate) / 2}%)</span>
                      <strong>{formatINR(lineItem.cgstAmt)}</strong>
                    </div>
                    <div className="calc-result-row">
                      <span>SGST ({parseFloat(gstRate) / 2}%)</span>
                      <strong>{formatINR(lineItem.sgstAmt)}</strong>
                    </div>
                  </>
                )}
                <div className="calc-result-row calc-total">
                  <span>Total Invoice Value</span>
                  <strong>{formatINR(lineItem.totalItemValue)}</strong>
                </div>
              </div>
            )}

            {jsonPayload && (
              <div style={{ marginTop: "1rem" }}>
                <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.5rem" }}>
                  <button className="btn btn-primary" onClick={handleCopy}>Copy JSON</button>
                  <button className="btn btn-secondary" onClick={handleDownload}>Download JSON</button>
                </div>
                <pre
                  style={{
                    background: "var(--bg-secondary, #1a1a2e)",
                    color: "var(--text-primary, #e0e0e0)",
                    padding: "1rem",
                    borderRadius: "0.5rem",
                    fontSize: "0.8rem",
                    lineHeight: 1.4,
                    overflowX: "auto",
                    maxHeight: "400px",
                  }}
                >{jsonText}</pre>
                <div className="calc-result-actions" style={{ marginTop: "0.75rem" }}>
                  <ShareButtons
                    path="/e-invoice-generator"
                    text="Generated e-invoice data for free on DoAide GST — no signup needed!"
                    toolName="E-Invoice Generator"
                  />
                </div>
              </div>
            )}
          </div>

          {jsonPayload && (
            <SaveResultsCTA resultSummary={`E-Invoice JSON generated for ${docNo || "draft"}`} />
          )}
          <EmailCapture
            source="e-invoice-generator"
            heading="Automate your e-invoicing"
            subtext="Generate e-invoices in bulk, track IRN status, and auto-report to IRP — sign up free."
            buttonLabel="Start Free"
            compact
          />

          <section className="tool-info">
            <h2>E-Invoicing Under GST — Complete Guide</h2>
            <p>
              E-invoicing under GST requires businesses above the prescribed turnover threshold
              to report B2B invoices to the Invoice Registration Portal (IRP) in a standard JSON format.
              The IRP validates the data, generates a unique Invoice Reference Number (IRN), digitally
              signs the invoice, and returns a QR code.
            </p>
            <h3>Who Needs E-Invoicing?</h3>
            <ul>
              <li>Businesses with aggregate turnover exceeding ₹5 crore (FY 2017-18 onwards)</li>
              <li>Applicable for all B2B supplies, exports, and SEZ supplies</li>
              <li>Not required for B2C supplies, nil-rated/exempt supplies, or non-GST supplies</li>
              <li>Insurance, banking, financial institutions, NBFCs, and GTA are exempt</li>
            </ul>
            <h3>E-Invoice JSON Schema</h3>
            <ul>
              <li><strong>Version:</strong> Schema version (currently 1.1)</li>
              <li><strong>TranDtls:</strong> Tax scheme, supply type, reverse charge flag</li>
              <li><strong>DocDtls:</strong> Document type (INV/CRN/DBN), number, and date</li>
              <li><strong>SellerDtls:</strong> Seller GSTIN, legal name, address, state code</li>
              <li><strong>BuyerDtls:</strong> Buyer GSTIN, legal name, address, state code, POS</li>
              <li><strong>ItemList:</strong> Line items with HSN, qty, rates, and tax amounts</li>
              <li><strong>ValDtls:</strong> Aggregate values — assessable, taxes, total</li>
            </ul>
            <h3>Penalties for Non-Compliance</h3>
            <ul>
              <li>100% of tax due or ₹10,000 — whichever is higher</li>
              <li>Buyer cannot claim ITC on invoices missing IRN</li>
              <li>E-way bill cannot be generated without a valid IRN</li>
            </ul>
          </section>

          <section className="tool-info">
            <h2>Frequently Asked Questions</h2>

            <h3>What is e-invoice under GST?</h3>
            <p>
              E-invoicing requires businesses above the turnover threshold to report B2B invoices
              to the IRP in JSON format. The IRP returns a unique IRN and signed QR code for each
              invoice.
            </p>

            <h3>Who needs to generate e-invoices?</h3>
            <p>
              Businesses with aggregate turnover exceeding ₹5 crore in any FY from 2017-18 onwards.
              The threshold has been progressively lowered from ₹500 crore.
            </p>

            <h3>What is the JSON format for e-invoice?</h3>
            <p>
              The e-invoice JSON follows GSTN Schema v1.1 with sections: Version, TranDtls,
              DocDtls, SellerDtls, BuyerDtls, ItemList, and ValDtls.
            </p>

            <h3>What happens if e-invoice is not generated?</h3>
            <p>
              Penalty of 100% of tax due or ₹10,000 (whichever is higher). The buyer loses ITC,
              and e-way bills cannot be generated without a valid IRN.
            </p>
          </section>

          <InlineCTA variant="save" />
          <RelatedTools current="/e-invoice-generator" />
          <CrossProductLinks page="e-invoice-generator" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
      <ExitIntentPopup />
    </div>
  );
}
