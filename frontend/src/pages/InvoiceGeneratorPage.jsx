import { useCallback, useMemo, useRef, useState } from "react";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { formatINR } from "../lib/gstCalc";
import { gstinShapeError } from "../lib/validate";
import { todayInIndia } from "../lib/returnDueDates";

const GST_RATES = [0, 0.25, 3, 5, 12, 18, 28];

const STATE_CODES = [
  "01-Jammu & Kashmir", "02-Himachal Pradesh", "03-Punjab", "04-Chandigarh",
  "05-Uttarakhand", "06-Haryana", "07-Delhi", "08-Rajasthan", "09-Uttar Pradesh",
  "10-Bihar", "11-Sikkim", "12-Arunachal Pradesh", "13-Nagaland", "14-Manipur",
  "15-Mizoram", "16-Tripura", "17-Meghalaya", "18-Assam", "19-West Bengal",
  "20-Jharkhand", "21-Odisha", "22-Chhattisgarh", "23-Madhya Pradesh",
  "24-Gujarat", "25-Daman & Diu", "26-Dadra & Nagar Haveli", "27-Maharashtra",
  "29-Karnataka", "30-Goa", "32-Kerala", "33-Tamil Nadu", "34-Puducherry",
  "35-Andaman & Nicobar", "36-Telangana", "37-Andhra Pradesh", "38-Ladakh",
];

function stateCodeFromGstin(gstin) {
  if (!gstin || gstin.length < 2) return "";
  return gstin.substring(0, 2);
}

function numberToWords(num) {
  if (num === 0) return "Zero";
  const ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen"];
  const tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"];

  function convert(n) {
    if (n < 20) return ones[n];
    if (n < 100) return tens[Math.floor(n / 10)] + (n % 10 ? " " + ones[n % 10] : "");
    if (n < 1000) return ones[Math.floor(n / 100)] + " Hundred" + (n % 100 ? " and " + convert(n % 100) : "");
    if (n < 100000) return convert(Math.floor(n / 1000)) + " Thousand" + (n % 1000 ? " " + convert(n % 1000) : "");
    if (n < 10000000) return convert(Math.floor(n / 100000)) + " Lakh" + (n % 100000 ? " " + convert(n % 100000) : "");
    return convert(Math.floor(n / 10000000)) + " Crore" + (n % 10000000 ? " " + convert(n % 10000000) : "");
  }

  const rupees = Math.floor(num);
  const paise = Math.round((num - rupees) * 100);
  let result = convert(rupees) + " Rupees";
  if (paise > 0) result += " and " + convert(paise) + " Paise";
  return result + " Only";
}

const emptyItem = { description: "", hsn: "", qty: "1", rate: "", gstRate: "18" };

function generateInvoiceNo() {
  const d = new Date();
  const yy = String(d.getFullYear()).slice(-2);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const seq = String(Math.floor(Math.random() * 900) + 100);
  return `INV-${yy}${mm}-${seq}`;
}

const fieldHint = { fontSize: "0.8rem", marginTop: "4px", minHeight: "1.2em" };
const fieldError = { ...fieldHint, color: "#ef4444" };
const fieldOk = { ...fieldHint, color: "#34d399" };

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "Free GST Invoice Generator",
  url: "https://gst.doaide.com/invoice-generator",
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
      name: "What is a GST invoice?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "A GST invoice is issued by a registered supplier with details of goods/services, GST charged (CGST, SGST or IGST), supplier and buyer GSTIN, HSN/SAC codes, and other fields per Rule 46 of CGST Rules.",
      },
    },
    {
      "@type": "Question",
      name: "What are mandatory fields in a GST invoice?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Supplier name, address, GSTIN; invoice number and date; buyer details; HSN/SAC code; description, quantity, value; GST rate and amount; place of supply; total in words.",
      },
    },
    {
      "@type": "Question",
      name: "When is IGST charged vs CGST+SGST?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "IGST is charged on interstate supplies (supplier and buyer in different states). CGST+SGST is charged on intrastate supplies (same state). This is determined by the state codes in each party's GSTIN.",
      },
    },
    {
      "@type": "Question",
      name: "Is this GST invoice legally valid?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "This tool generates invoices with all mandatory fields under GST law. The accuracy of information entered is your responsibility. Ensure all details are correct and maintain proper records.",
      },
    },
    {
      "@type": "Question",
      name: "Can I download the invoice as PDF?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes, click the 'Download PDF' button to open the print dialog. Select 'Save as PDF' as the destination to download your GST invoice as a PDF file. The invoice is formatted for A4 paper size.",
      },
    },
  ],
};

const HOWTO_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "HowTo",
  name: "How to create a GST invoice",
  description: "Build a Rule 46-compliant tax invoice and download it as a PDF, free.",
  step: [
    { "@type": "HowToStep", name: "Fill in seller and buyer", text: "Names, addresses and GSTINs — the two state codes decide whether the invoice carries CGST+SGST or IGST." },
    { "@type": "HowToStep", name: "Add the line items", text: "Description, HSN code, quantity, rate and GST slab per line." },
    { "@type": "HowToStep", name: "Preview the invoice", text: "Totals, tax split and amount in words are computed for you." },
    { "@type": "HowToStep", name: "Download the PDF", text: "The print dialog saves an A4 PDF ready to send." },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "Invoice Generator" },
];

export default function InvoiceGeneratorPage() {
  usePageTitle("Free GST Invoice Generator — Create & Download PDF");

  const invoiceRef = useRef(null);

  const [seller, setSeller] = useState({
    name: "", address: "", gstin: "", state: "", phone: "", email: "",
  });
  const [buyer, setBuyer] = useState({
    name: "", address: "", gstin: "", state: "", phone: "", email: "", unregistered: false,
  });
  const [invoiceNo, setInvoiceNo] = useState(generateInvoiceNo);
  const [invoiceDate, setInvoiceDate] = useState(todayInIndia);
  const [dueDate, setDueDate] = useState("");
  const [items, setItems] = useState([{ ...emptyItem }]);
  const [notes, setNotes] = useState("");
  const [showPreview, setShowPreview] = useState(false);

  function updateSeller(field, value) {
    setSeller((prev) => {
      const next = { ...prev, [field]: value };
      if (field === "gstin" && value.length >= 2) {
        next.state = stateCodeFromGstin(value);
      }
      return next;
    });
  }

  function updateBuyer(field, value) {
    setBuyer((prev) => {
      const next = { ...prev, [field]: value };
      if (field === "gstin" && value.length >= 2) {
        next.state = stateCodeFromGstin(value);
      }
      return next;
    });
  }

  function updateItem(index, field, value) {
    setItems((prev) => prev.map((item, i) => i === index ? { ...item, [field]: value } : item));
  }

  function addItem() {
    setItems((prev) => [...prev, { ...emptyItem }]);
  }

  function removeItem(index) {
    if (items.length <= 1) return;
    setItems((prev) => prev.filter((_, i) => i !== index));
  }

  const isInterstate = useMemo(() => {
    if (!seller.state || !buyer.state) return false;
    return seller.state !== buyer.state;
  }, [seller.state, buyer.state]);

  const computedItems = useMemo(() => {
    return items.map((item) => {
      const qty = parseFloat(item.qty) || 0;
      const rate = parseFloat(item.rate) || 0;
      const gstRate = parseFloat(item.gstRate) || 0;
      const taxableAmount = Math.round(qty * rate * 100) / 100;
      const totalTax = Math.round(taxableAmount * gstRate) / 100;
      const cgst = isInterstate ? 0 : Math.round((totalTax / 2) * 100) / 100;
      const sgst = isInterstate ? 0 : Math.round((totalTax - cgst) * 100) / 100;
      const igst = isInterstate ? totalTax : 0;
      return { ...item, taxableAmount, cgst, sgst, igst, totalTax, total: taxableAmount + totalTax };
    });
  }, [items, isInterstate]);

  const totals = useMemo(() => {
    let taxable = 0, cgst = 0, sgst = 0, igst = 0, total = 0;
    for (const item of computedItems) {
      taxable += item.taxableAmount;
      cgst += item.cgst;
      sgst += item.sgst;
      igst += item.igst;
      total += item.total;
    }
    return {
      taxable: Math.round(taxable * 100) / 100,
      cgst: Math.round(cgst * 100) / 100,
      sgst: Math.round(sgst * 100) / 100,
      igst: Math.round(igst * 100) / 100,
      total: Math.round(total * 100) / 100,
    };
  }, [computedItems]);

  const canPreview = seller.name && buyer.name && invoiceNo && items.some((i) => i.description && i.rate);

  const handleDownloadPdf = useCallback(() => {
    if (!invoiceRef.current) return;
    const printWindow = window.open("", "_blank");
    if (!printWindow) return;
    const html = `<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Invoice ${invoiceNo}</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#1a1a1a;padding:24px;max-width:800px;margin:0 auto}
.inv-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:24px;padding-bottom:16px;border-bottom:3px solid #2563eb}
.inv-title{font-size:28px;font-weight:700;color:#2563eb}
.inv-meta{text-align:right;font-size:13px;line-height:1.6}
.inv-meta strong{display:block;font-size:14px}
.inv-parties{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:24px}
.inv-party h3{font-size:12px;text-transform:uppercase;color:#6b7280;margin-bottom:6px;letter-spacing:0.5px}
.inv-party p{font-size:13px;line-height:1.5}
.inv-party strong{font-size:15px;display:block;margin-bottom:2px}
table{width:100%;border-collapse:collapse;margin-bottom:16px;font-size:13px}
th{background:#f3f4f6;padding:8px 10px;text-align:left;font-size:11px;text-transform:uppercase;color:#6b7280;border-bottom:2px solid #e5e7eb}
td{padding:8px 10px;border-bottom:1px solid #f3f4f6}
.right{text-align:right}
.inv-totals{margin-left:auto;width:300px;margin-bottom:24px}
.inv-totals .row{display:flex;justify-content:space-between;padding:4px 0;font-size:13px}
.inv-totals .grand{border-top:2px solid #2563eb;padding-top:8px;margin-top:4px;font-size:15px;font-weight:700;color:#2563eb}
.inv-words{background:#f8fafc;padding:12px 16px;border-radius:6px;font-size:13px;margin-bottom:24px}
.inv-words strong{font-size:11px;text-transform:uppercase;color:#6b7280;display:block;margin-bottom:4px}
.inv-footer{display:flex;justify-content:space-between;margin-top:40px;padding-top:16px;border-top:1px solid #e5e7eb;font-size:12px;color:#9ca3af}
.inv-notes{font-size:12px;color:#6b7280;margin-bottom:24px}
.inv-notes strong{display:block;margin-bottom:4px;color:#374151}
@media print{body{padding:12px}@page{size:A4;margin:12mm}}
</style></head><body>
${invoiceRef.current.innerHTML}
<script>window.onload=function(){window.print()}<\/script>
</body></html>`;
    printWindow.document.write(html);
    printWindow.document.close();
  }, [invoiceNo]);

  return (
    <div className="tool-page">
      <SeoHead
        title="Free GST Invoice Generator — Create & Download PDF"
        description="Generate GST-compliant invoices for free. Fill in seller, buyer, and item details to create professional tax invoices with CGST, SGST, IGST breakdown. Download as PDF instantly."
        path="/invoice-generator"
        jsonLd={[TOOL_SCHEMA, HOWTO_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">GST Invoice Generator</h1>
          <p className="tool-subtitle">
            Create GST-compliant tax invoices and download as PDF. Free, no sign-up required.
          </p>

          {!showPreview ? (
            <div className="calc-card">
              <h2 style={{ fontSize: "1.1rem", fontWeight: 600, marginBottom: "1rem" }}>Invoice Details</h2>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0.75rem" }}>
                <label className="calc-label">
                  Invoice Number
                  <input className="calc-input" value={invoiceNo} onChange={(e) => setInvoiceNo(e.target.value)} placeholder="Auto-generated" />
                </label>
                <label className="calc-label">
                  Invoice Date
                  <input type="date" className="calc-input" value={invoiceDate} onChange={(e) => setInvoiceDate(e.target.value)} />
                </label>
                <label className="calc-label">
                  Due Date
                  <input type="date" className="calc-input" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
                </label>
              </div>

              <h2 style={{ fontSize: "1.1rem", fontWeight: 600, margin: "1.25rem 0 0.75rem" }}>Seller Details</h2>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
                <label className="calc-label">
                  Business Name *
                  <input className="calc-input" value={seller.name} onChange={(e) => updateSeller("name", e.target.value)} placeholder="Your business name" />
                </label>
                <label className="calc-label">
                  GSTIN
                  <input className="calc-input" value={seller.gstin} onChange={(e) => updateSeller("gstin", e.target.value.toUpperCase())} placeholder="e.g. 27AAPFU0939F1ZV" maxLength={15} style={seller.gstin && gstinShapeError(seller.gstin) ? { borderColor: "#ef4444" } : undefined} />
                  {seller.gstin && (
                    <div style={gstinShapeError(seller.gstin) ? fieldError : fieldOk}>
                      {gstinShapeError(seller.gstin) || "✓ Valid format"}
                    </div>
                  )}
                </label>
                <label className="calc-label" style={{ gridColumn: "1 / -1" }}>
                  Address
                  <input className="calc-input" value={seller.address} onChange={(e) => updateSeller("address", e.target.value)} placeholder="Full business address" />
                </label>
                <label className="calc-label">
                  State Code
                  <select className="calc-select" value={seller.state} onChange={(e) => updateSeller("state", e.target.value)}>
                    <option value="">Select state</option>
                    {STATE_CODES.map((s) => <option key={s} value={s.split("-")[0]}>{s}</option>)}
                  </select>
                </label>
                <label className="calc-label">
                  Phone / Email
                  <input className="calc-input" value={seller.phone} onChange={(e) => updateSeller("phone", e.target.value)} placeholder="Optional" />
                </label>
              </div>

              <h2 style={{ fontSize: "1.1rem", fontWeight: 600, margin: "1.25rem 0 0.75rem" }}>Buyer Details</h2>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
                <label className="calc-label">
                  Business Name *
                  <input className="calc-input" value={buyer.name} onChange={(e) => updateBuyer("name", e.target.value)} placeholder="Buyer business name" />
                </label>
                <label className="calc-label">
                  GSTIN
                  {/* An unregistered buyer has no GSTIN to take the state from, so
                      the state below becomes the place of supply and decides the
                      tax split on its own. The invoice prints "URP", the term the
                      GST portal itself uses, rather than leaving the field blank. */}
                  <input className="calc-input" value={buyer.unregistered ? "URP" : buyer.gstin} disabled={buyer.unregistered} onChange={(e) => updateBuyer("gstin", e.target.value.toUpperCase())} placeholder="e.g. 29AABCU9603R1ZM" maxLength={15} style={buyer.gstin && gstinShapeError(buyer.gstin) ? { borderColor: "#ef4444" } : undefined} />
                  {buyer.gstin && (
                    <div style={gstinShapeError(buyer.gstin) ? fieldError : fieldOk}>
                      {gstinShapeError(buyer.gstin) || "✓ Valid format"}
                    </div>
                  )}
                </label>
                <label className="calc-label" style={{ flexDirection: "row", alignItems: "center", gap: "0.4rem", fontWeight: 400 }}>
                  <input type="checkbox" checked={buyer.unregistered} onChange={(e) => setBuyer((prev) => ({ ...prev, unregistered: e.target.checked, gstin: "" }))} />
                  Unregistered buyer (URP)
                </label>
                <label className="calc-label" style={{ gridColumn: "1 / -1" }}>
                  Address
                  <input className="calc-input" value={buyer.address} onChange={(e) => updateBuyer("address", e.target.value)} placeholder="Full buyer address" />
                </label>
                <label className="calc-label">
                  {buyer.unregistered ? "Place of Supply (State)" : "State Code"}
                  <select className="calc-select" value={buyer.state} onChange={(e) => updateBuyer("state", e.target.value)}>
                    <option value="">Select state</option>
                    {STATE_CODES.map((s) => <option key={s} value={s.split("-")[0]}>{s}</option>)}
                  </select>
                </label>
                <label className="calc-label">
                  Phone / Email
                  <input className="calc-input" value={buyer.phone} onChange={(e) => updateBuyer("phone", e.target.value)} placeholder="Optional" />
                </label>
              </div>

              <h2 style={{ fontSize: "1.1rem", fontWeight: 600, margin: "1.25rem 0 0.75rem" }}>
                Items
                {isInterstate && <span style={{ fontSize: "0.8rem", fontWeight: 400, color: "#f59e42", marginLeft: "0.5rem" }}>(Interstate — IGST)</span>}
                {!isInterstate && seller.state && buyer.state && <span style={{ fontSize: "0.8rem", fontWeight: 400, color: "#34d399", marginLeft: "0.5rem" }}>(Intrastate — CGST+SGST)</span>}
              </h2>
              {items.map((item, i) => (
                <div key={i} style={{ display: "grid", gridTemplateColumns: "2fr 1fr 0.7fr 1fr 1fr auto", gap: "0.5rem", alignItems: "end", marginBottom: "0.5rem" }}>
                  <label className="calc-label" style={{ margin: 0 }}>
                    {i === 0 && "Description *"}
                    <input className="calc-input" value={item.description} onChange={(e) => updateItem(i, "description", e.target.value)} placeholder="Item description" />
                  </label>
                  <label className="calc-label" style={{ margin: 0 }}>
                    {i === 0 && "HSN/SAC"}
                    <input className="calc-input" value={item.hsn} onChange={(e) => updateItem(i, "hsn", e.target.value)} placeholder="Code" />
                  </label>
                  <label className="calc-label" style={{ margin: 0 }}>
                    {i === 0 && "Qty"}
                    <input type="number" className="calc-input" value={item.qty} onChange={(e) => updateItem(i, "qty", e.target.value)} min="0" step="1" inputMode="numeric" />
                  </label>
                  <label className="calc-label" style={{ margin: 0 }}>
                    {i === 0 && "Rate (₹)"}
                    <input type="number" className="calc-input" value={item.rate} onChange={(e) => updateItem(i, "rate", e.target.value)} placeholder="0.00" min="0" step="0.01" inputMode="decimal" />
                  </label>
                  <label className="calc-label" style={{ margin: 0 }}>
                    {i === 0 && "GST %"}
                    <select className="calc-select" value={item.gstRate} onChange={(e) => updateItem(i, "gstRate", e.target.value)}>
                      {GST_RATES.map((r) => <option key={r} value={r}>{r}%</option>)}
                    </select>
                  </label>
                  <button
                    onClick={() => removeItem(i)}
                    style={{ padding: "0.5rem", background: "none", border: "none", color: "#f87171", cursor: "pointer", fontSize: "1.2rem" }}
                    aria-label="Remove item"
                    disabled={items.length <= 1}
                  >
                    ×
                  </button>
                </div>
              ))}
              <button onClick={addItem} style={{ marginTop: "0.5rem", padding: "0.5rem 1rem", background: "var(--brand)", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer", fontSize: "0.9rem" }}>
                + Add Item
              </button>

              <label className="calc-label" style={{ marginTop: "1rem" }}>
                Notes / Terms
                <textarea className="calc-input" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Payment terms, bank details, etc." rows={3} style={{ resize: "vertical" }} />
              </label>

              {totals.total > 0 && (
                <div className="calc-result" aria-live="polite">
                  <div className="calc-result-row">
                    <span>Taxable Amount</span>
                    <strong>{formatINR(totals.taxable)}</strong>
                  </div>
                  {isInterstate ? (
                    <div className="calc-result-row">
                      <span>IGST</span>
                      <strong>{formatINR(totals.igst)}</strong>
                    </div>
                  ) : (
                    <>
                      <div className="calc-result-row">
                        <span>CGST</span>
                        <strong>{formatINR(totals.cgst)}</strong>
                      </div>
                      <div className="calc-result-row">
                        <span>SGST</span>
                        <strong>{formatINR(totals.sgst)}</strong>
                      </div>
                    </>
                  )}
                  <div className="calc-result-row calc-total">
                    <span>Total Amount</span>
                    <strong>{formatINR(totals.total)}</strong>
                  </div>
                </div>
              )}

              <div style={{ display: "flex", gap: "0.75rem", marginTop: "1rem" }}>
                <button
                  onClick={() => setShowPreview(true)}
                  disabled={!canPreview}
                  style={{
                    padding: "0.75rem 1.5rem", background: canPreview ? "var(--brand)" : "#6b7280",
                    color: "#fff", border: "none", borderRadius: "6px", cursor: canPreview ? "pointer" : "not-allowed",
                    fontSize: "1rem", fontWeight: 600,
                  }}
                >
                  Preview Invoice
                </button>
              </div>
            </div>
          ) : (
            <div className="calc-card">
              <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem" }}>
                <button
                  onClick={() => setShowPreview(false)}
                  style={{ padding: "0.5rem 1rem", background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: "6px", cursor: "pointer", fontSize: "0.9rem", color: "var(--ink)" }}
                >
                  ← Edit
                </button>
                <button
                  onClick={handleDownloadPdf}
                  style={{ padding: "0.5rem 1rem", background: "var(--brand)", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer", fontSize: "0.9rem", fontWeight: 600 }}
                >
                  Download PDF
                </button>
              </div>

              <div ref={invoiceRef} style={{ background: "#fff", color: "#1a1a1a", padding: "24px", borderRadius: "8px" }}>
                <div className="inv-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "24px", paddingBottom: "16px", borderBottom: "3px solid #2563eb" }}>
                  <div>
                    <div style={{ fontSize: "28px", fontWeight: 700, color: "#2563eb" }}>TAX INVOICE</div>
                  </div>
                  <div style={{ textAlign: "right", fontSize: "13px", lineHeight: 1.6 }}>
                    <strong style={{ display: "block", fontSize: "14px" }}>Invoice # {invoiceNo}</strong>
                    <span>Date: {invoiceDate}</span>
                    {dueDate && <><br /><span>Due: {dueDate}</span></>}
                  </div>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px", marginBottom: "24px" }}>
                  <div>
                    <h3 style={{ fontSize: "12px", textTransform: "uppercase", color: "#6b7280", marginBottom: "6px" }}>From</h3>
                    <strong style={{ fontSize: "15px", display: "block", marginBottom: "2px" }}>{seller.name}</strong>
                    {seller.address && <p style={{ fontSize: "13px", lineHeight: 1.5 }}>{seller.address}</p>}
                    {seller.gstin && <p style={{ fontSize: "13px" }}>GSTIN: {seller.gstin}</p>}
                    {seller.phone && <p style={{ fontSize: "13px" }}>{seller.phone}</p>}
                  </div>
                  <div>
                    <h3 style={{ fontSize: "12px", textTransform: "uppercase", color: "#6b7280", marginBottom: "6px" }}>To</h3>
                    <strong style={{ fontSize: "15px", display: "block", marginBottom: "2px" }}>{buyer.name}</strong>
                    {buyer.address && <p style={{ fontSize: "13px", lineHeight: 1.5 }}>{buyer.address}</p>}
                    {buyer.unregistered
                      ? <p style={{ fontSize: "13px" }}>GSTIN: URP (Unregistered){buyer.state && ` · Place of supply: ${STATE_CODES.find((c) => c.startsWith(`${buyer.state}-`)) || buyer.state}`}</p>
                      : buyer.gstin && <p style={{ fontSize: "13px" }}>GSTIN: {buyer.gstin}</p>}
                    {buyer.phone && <p style={{ fontSize: "13px" }}>{buyer.phone}</p>}
                  </div>
                </div>

                <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: "16px", fontSize: "13px" }}>
                  <thead>
                    <tr style={{ background: "#f3f4f6" }}>
                      <th style={{ padding: "8px 10px", textAlign: "left", fontSize: "11px", textTransform: "uppercase", color: "#6b7280", borderBottom: "2px solid #e5e7eb" }}>#</th>
                      <th style={{ padding: "8px 10px", textAlign: "left", fontSize: "11px", textTransform: "uppercase", color: "#6b7280", borderBottom: "2px solid #e5e7eb" }}>Description</th>
                      <th style={{ padding: "8px 10px", textAlign: "left", fontSize: "11px", textTransform: "uppercase", color: "#6b7280", borderBottom: "2px solid #e5e7eb" }}>HSN</th>
                      <th style={{ padding: "8px 10px", textAlign: "right", fontSize: "11px", textTransform: "uppercase", color: "#6b7280", borderBottom: "2px solid #e5e7eb" }}>Qty</th>
                      <th style={{ padding: "8px 10px", textAlign: "right", fontSize: "11px", textTransform: "uppercase", color: "#6b7280", borderBottom: "2px solid #e5e7eb" }}>Rate</th>
                      <th style={{ padding: "8px 10px", textAlign: "right", fontSize: "11px", textTransform: "uppercase", color: "#6b7280", borderBottom: "2px solid #e5e7eb" }}>GST%</th>
                      <th style={{ padding: "8px 10px", textAlign: "right", fontSize: "11px", textTransform: "uppercase", color: "#6b7280", borderBottom: "2px solid #e5e7eb" }}>Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {computedItems.filter((i) => i.description).map((item, idx) => (
                      <tr key={idx}>
                        <td style={{ padding: "8px 10px", borderBottom: "1px solid #f3f4f6" }}>{idx + 1}</td>
                        <td style={{ padding: "8px 10px", borderBottom: "1px solid #f3f4f6" }}>{item.description}</td>
                        <td style={{ padding: "8px 10px", borderBottom: "1px solid #f3f4f6" }}>{item.hsn}</td>
                        <td style={{ padding: "8px 10px", borderBottom: "1px solid #f3f4f6", textAlign: "right" }}>{item.qty}</td>
                        <td style={{ padding: "8px 10px", borderBottom: "1px solid #f3f4f6", textAlign: "right" }}>{formatINR(parseFloat(item.rate) || 0)}</td>
                        <td style={{ padding: "8px 10px", borderBottom: "1px solid #f3f4f6", textAlign: "right" }}>{item.gstRate}%</td>
                        <td style={{ padding: "8px 10px", borderBottom: "1px solid #f3f4f6", textAlign: "right" }}>{formatINR(item.total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                <div style={{ marginLeft: "auto", width: "300px", marginBottom: "24px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: "13px" }}>
                    <span>Taxable Amount</span><span>{formatINR(totals.taxable)}</span>
                  </div>
                  {isInterstate ? (
                    <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: "13px" }}>
                      <span>IGST</span><span>{formatINR(totals.igst)}</span>
                    </div>
                  ) : (
                    <>
                      <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: "13px" }}>
                        <span>CGST</span><span>{formatINR(totals.cgst)}</span>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: "13px" }}>
                        <span>SGST</span><span>{formatINR(totals.sgst)}</span>
                      </div>
                    </>
                  )}
                  <div style={{ display: "flex", justifyContent: "space-between", borderTop: "2px solid #2563eb", paddingTop: "8px", marginTop: "4px", fontSize: "15px", fontWeight: 700, color: "#2563eb" }}>
                    <span>Total</span><span>{formatINR(totals.total)}</span>
                  </div>
                </div>

                <div style={{ background: "#f8fafc", padding: "12px 16px", borderRadius: "6px", fontSize: "13px", marginBottom: "24px" }}>
                  <strong style={{ fontSize: "11px", textTransform: "uppercase", color: "#6b7280", display: "block", marginBottom: "4px" }}>Amount in Words</strong>
                  {numberToWords(totals.total)}
                </div>

                {notes && (
                  <div style={{ fontSize: "12px", color: "#6b7280", marginBottom: "24px" }}>
                    <strong style={{ display: "block", marginBottom: "4px", color: "#374151" }}>Notes / Terms</strong>
                    <p style={{ whiteSpace: "pre-wrap" }}>{notes}</p>
                  </div>
                )}

                <div style={{ display: "flex", justifyContent: "space-between", marginTop: "40px", paddingTop: "16px", borderTop: "1px solid #e5e7eb", fontSize: "12px", color: "#9ca3af" }}>
                  <span>Generated on gst.doaide.com</span>
                  <span>Authorised Signatory</span>
                </div>
              </div>

              <div className="calc-result-actions" style={{ marginTop: "1rem" }}>
                <ShareButtons
                  path="/invoice-generator"
                  text="Create free GST invoices with automatic CGST/SGST/IGST calculation — DoAide GST"
                />
              </div>
            </div>
          )}

          <EmailCapture
            source="invoice-generator"
            heading="Get GST filing reminders"
            subtext="Never miss a filing deadline — free email alerts before every due date."
            buttonLabel="Remind Me"
            compact
          />

          <section className="tool-info">
            <h2>How to Create a GST Invoice</h2>
            <p>
              A GST tax invoice is a mandatory document for every registered taxpayer making
              taxable supplies. This tool helps you create compliant invoices with automatic
              CGST/SGST/IGST calculation based on the supplier and buyer locations.
            </p>
            <h3>Mandatory Invoice Fields (Rule 46, CGST Rules)</h3>
            <ul>
              <li>Supplier name, address, and GSTIN</li>
              <li>Consecutive serial number (invoice number)</li>
              <li>Date of issue</li>
              <li>Recipient name, address, and GSTIN (if registered)</li>
              <li>HSN/SAC code for each item</li>
              <li>Description, quantity, unit, and value of goods/services</li>
              <li>Taxable value and applicable GST rate</li>
              <li>Amount of CGST, SGST, or IGST</li>
              <li>Place of supply (for interstate)</li>
              <li>Total invoice value in figures and words</li>
            </ul>
            <h3>IGST vs CGST+SGST</h3>
            <p>
              The tool automatically determines whether to charge IGST or CGST+SGST based on
              the state codes of the seller and buyer. Interstate supplies attract IGST, while
              intrastate supplies attract CGST+SGST at equal halves.
            </p>
          </section>

          <section className="tool-info">
            <h2>Frequently Asked Questions</h2>

            <h3>What is a GST invoice?</h3>
            <p>
              A GST invoice is a document issued by a registered supplier detailing the goods
              or services supplied, the GST charged (CGST, SGST, or IGST), and other mandatory
              fields as prescribed under Rule 46 of CGST Rules.
            </p>

            <h3>What are the mandatory fields in a GST invoice?</h3>
            <p>
              Mandatory fields include: supplier name, address and GSTIN; sequential invoice
              number and date; buyer details; HSN/SAC codes; item description, quantity and
              value; GST rate and amount; place of supply; and total value in figures and words.
            </p>

            <h3>When is IGST charged vs CGST+SGST?</h3>
            <p>
              IGST is charged on interstate supplies (supplier and buyer in different states).
              CGST+SGST is charged on intrastate supplies (same state). This tool auto-detects
              based on the state codes in the GSTINs entered.
            </p>

            <h3>Can I download the invoice as PDF?</h3>
            <p>
              Yes — click &quot;Preview Invoice&quot; then &quot;Download PDF&quot;. In the print dialog,
              select &quot;Save as PDF&quot; to save your invoice. The invoice is formatted for A4 paper.
            </p>

            <h3>Is this invoice legally valid?</h3>
            <p>
              This tool generates invoices with all mandatory GST fields. However, you are
              responsible for ensuring the accuracy of the information entered. For legal
              compliance, maintain proper records and consult your CA if needed.
            </p>

            <h3>Do I need to generate e-invoices separately?</h3>
            <p>
              E-invoicing (via the IRP portal) is mandatory for businesses with turnover above
              ₹5 crore. This tool creates the physical invoice format. For e-invoicing, you
              need to generate an IRN through the GST portal or your accounting software.
            </p>
          </section>

          <InlineCTA variant="invoice" />
          <RelatedTools current="/invoice-generator" />
          <CrossProductLinks page="invoice-generator" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}
