import { useMemo, useState } from "react";
import Breadcrumb from "../components/Breadcrumb";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import FaqSection, { faqSchema } from "../components/FaqSection";
import EmailCapture from "../components/EmailCapture";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { formatINR } from "../lib/gstCalc";

const CONTRACT_TYPES = [
  { key: "supply_12", label: "Supply contract at old 12% rate", oldRate: 12, newRate: 18, action: "Rate increased to 18%. Renegotiate or add price adjustment clause." },
  { key: "supply_28", label: "Supply contract at old 28% rate", oldRate: 28, newRate: 18, action: "Rate decreased to 18%. Buyer should request price reduction for anti-profiteering." },
  { key: "supply_28_luxury", label: "Supply contract at old 28% rate (luxury/tobacco)", oldRate: 28, newRate: 40, action: "Rate increased to 40%. Major price impact — renegotiate urgently." },
  { key: "insurance_18", label: "Insurance premium contract at 18%", oldRate: 18, newRate: 0, action: "Insurance is now GST-free. Insurer must pass on full 18% savings." },
  { key: "construction_12", label: "Construction contract at old 12%", oldRate: 12, newRate: 18, action: "Rate increased to 18%. Check if contract has rate escalation clause." },
  { key: "gta_12", label: "GTA forward charge at old 12%", oldRate: 12, newRate: 18, action: "GTA forward charge rate now 18%. Update billing arrangement." },
  { key: "medicine_12", label: "Pharmaceutical supply at 12%", oldRate: 12, newRate: 5, action: "Cancer drugs reduced to 5%. Life-saving medicines may be Nil. Verify per HSN." },
  { key: "cement_28", label: "Cement supply at 28%", oldRate: 28, newRate: 18, action: "Cement reduced to 18%. Buyer should claim anti-profiteering benefit." },
];

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GST 2.0 Migration Checker",
  url: "https://gst.doaide.com/migration-checker",
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "GST 2.0 Migration Checker" },
];

const FAQS = [
  {
    q: "When did GST 2.0 rates come into effect?",
    a: "The rationalised GST rates approved by the 56th GST Council meeting took effect on 22 September 2025. The 12% and 28% slabs were folded into 5% and 18%, with a new 40% rate for luxury and sin goods.",
  },
  {
    q: "Which rate applies to a contract signed before 22 September 2025?",
    a: "The rate follows the time of supply, not the contract date. Supplies on or after 22 September 2025 are taxed at the new rate even under an older contract, so price and tax clauses need review.",
  },
  {
    q: "What if the invoice and payment fall on different sides of the change?",
    a: "Section 14 of the CGST Act decides it: if two of the three events (supply, invoice and payment) happen after the change, the new rate applies; if two happen before it, the old rate applies.",
  },
  {
    q: "Must a supplier pass on a GST rate cut?",
    a: "Suppliers are expected to pass rate reductions on to buyers through lower prices. Buyers on long-term contracts should check that invoices issued after the change carry the new rate.",
  },
];

export default function Gst2MigrationCheckerPage() {
  usePageTitle("GST 2.0 Migration Checker — Contract Rate Update Tool");

  const [selected, setSelected] = useState("supply_12");
  const [contractValue, setContractValue] = useState("");

  const contract = CONTRACT_TYPES.find((c) => c.key === selected);

  const result = useMemo(() => {
    if (!contract) return null;
    const value = parseFloat(contractValue);
    if (!Number.isFinite(value) || value <= 0) return null;

    const oldGst = Math.round(value * contract.oldRate) / 100;
    const newGst = Math.round(value * contract.newRate) / 100;
    const diff = Math.round((newGst - oldGst) * 100) / 100;

    return {
      oldGst,
      newGst,
      diff,
      oldTotal: Math.round((value + oldGst) * 100) / 100,
      newTotal: Math.round((value + newGst) * 100) / 100,
    };
  }, [contract, contractValue]);

  return (
    <div className="tool-page">
      <SeoHead
        title="GST 2.0 Migration Checker — Do Your Contracts Need Rate Updates?"
        description="Check if your existing contracts need GST rate updates under GST 2.0. Calculate the financial impact of rate changes on your agreements and get action recommendations."
        path="/migration-checker"
        jsonLd={[TOOL_SCHEMA, faqSchema(FAQS)]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">GST 2.0 Migration Checker</h1>
          <p className="tool-subtitle">
            Check if your existing contracts need rate updates under GST 2.0. Get financial impact and action items.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Contract Type
              <select
                className="calc-select"
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
              >
                {CONTRACT_TYPES.map((c) => (
                  <option key={c.key} value={c.key}>{c.label}</option>
                ))}
              </select>
            </label>

            <label className="calc-label">
              Contract Value (₹) — excluding GST
              <input
                type="number"
                className="calc-input"
                value={contractValue}
                onChange={(e) => setContractValue(e.target.value)}
                placeholder="Enter base contract value"
                min="0"
                step="0.01"
                inputMode="decimal"
              />
            </label>

            {contract && (
              <div style={{ padding: "0.75rem", background: "rgba(245,158,66,0.08)", borderRadius: "0.5rem", marginTop: "0.5rem", fontSize: "0.9rem", lineHeight: 1.6 }}>
                <strong>Rate Change:</strong> {contract.oldRate}% → {contract.newRate}%
                <br />
                <strong>Action:</strong> {contract.action}
              </div>
            )}

            {result && (
              <div className="calc-result" aria-live="polite">
                <div className="calc-result-row">
                  <span>Old GST ({contract.oldRate}%)</span>
                  <strong>{formatINR(result.oldGst)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>New GST ({contract.newRate}%)</span>
                  <strong>{formatINR(result.newGst)}</strong>
                </div>
                <div className="calc-result-row calc-total" style={{ color: result.diff < 0 ? "#34d399" : result.diff > 0 ? "#f87171" : "var(--ink)" }}>
                  <span>GST Impact</span>
                  <strong>{result.diff >= 0 ? "+" : ""}{formatINR(result.diff)}</strong>
                </div>
                <div className="calc-result-row">
                  <span>Old Total (incl. GST)</span>
                  <strong>{formatINR(result.oldTotal)}</strong>
                </div>
                <div className="calc-result-row calc-total">
                  <span>New Total (incl. GST)</span>
                  <strong>{formatINR(result.newTotal)}</strong>
                </div>
                <div className="calc-result-actions">
                  <ShareButtons
                    path="/migration-checker"
                    text={`GST 2.0 impact on ${contract.label}: ${result.diff >= 0 ? "+" : ""}${formatINR(result.diff)} — check your contracts free on DoAide GST`}
                    toolName="GST 2.0 Migration Checker"
                  />
                </div>
              </div>
            )}
          </div>

          <section className="tool-info">
            <h2>GST 2.0 Contract Migration Checklist</h2>
            <ul>
              <li><strong>Review all long-term supply contracts</strong> — identify which ones reference 12% or 28% rates</li>
              <li><strong>Check rate escalation clauses</strong> — does the contract allow for GST rate changes?</li>
              <li><strong>Anti-profiteering compliance</strong> — if rates decreased, pass the benefit to buyers</li>
              <li><strong>Update invoicing systems</strong> — ensure billing software uses new rates</li>
              <li><strong>Insurance policies</strong> — demand full 18% savings on premiums</li>
              <li><strong>Update purchase orders</strong> — revise POs with the correct GST 2.0 rates</li>
              <li><strong>Communicate with suppliers</strong> — notify all suppliers of rate changes</li>
            </ul>
          </section>

          <EmailCapture
            source="migration-checker"
            heading="Get GST 2.0 migration help"
            subtext="Free email guide on updating your contracts for GST 2.0."
            buttonLabel="Send Guide"
            compact
          />

          <FaqSection faqs={FAQS} />

          <RelatedTools current="/migration-checker" />
          <CrossProductLinks page="migration-checker" />
        </div>
      </main>
      <DoAideFooter />
    </div>
  );
}
