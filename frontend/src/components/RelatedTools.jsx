import { Link } from "react-router-dom";

const ALL_TOOLS = [
  { path: "/calculator", label: "GST Calculator", desc: "Calculate CGST, SGST, IGST instantly" },
  { path: "/lookup", label: "GSTIN Verification", desc: "Verify any GST number" },
  { path: "/hsn", label: "HSN Code Search", desc: "Find HSN/SAC codes & GST rates" },
  { path: "/gst-rates", label: "GST Rates List", desc: "Product-wise GST rates by slab" },
  { path: "/due-dates", label: "Due Dates Calendar", desc: "GST filing deadlines" },
  { path: "/penalty-calculator", label: "Penalty Calculator", desc: "Late filing penalties & interest" },
  { path: "/eway-bill", label: "E-Way Bill Checker", desc: "Check if e-way bill is needed" },
  { path: "/input-tax-credit", label: "ITC Eligibility", desc: "Check Input Tax Credit eligibility" },
  { path: "/composition-scheme", label: "Composition Scheme", desc: "Check eligibility & tax rates" },
  { path: "/invoice-generator", label: "Invoice Generator", desc: "Create & download GST invoices" },
  { path: "/reverse-charge", label: "Reverse Charge", desc: "Calculate RCM liability" },
  { path: "/itc-mismatch", label: "ITC Mismatch", desc: "GSTR-2A vs Books reconciliation" },
  { path: "/registration-checker", label: "Registration Checker", desc: "Do you need GST registration?" },
  { path: "/return-calendar", label: "Return Calendar", desc: "GST return due date calendar" },
  { path: "/interest-calculator", label: "Interest Calculator", desc: "Late payment interest under GST" },
  { path: "/reverse-gst-calculator", label: "Reverse GST Calculator", desc: "Remove GST from an inclusive price" },
  { path: "/gst-on-gold", label: "GST on Gold", desc: "3% on gold + 5% on making charges" },
  { path: "/gst-on-real-estate", label: "GST on Real Estate", desc: "Tax on flats, property & construction" },
  { path: "/hsn-sac-finder", label: "HSN/SAC Finder", desc: "Search HSN & SAC codes by name" },
  { path: "/turnover-limit", label: "Turnover Limit", desc: "Check if GST registration needed" },
  { path: "/resources", label: "All GST Tools", desc: "Complete tools & guides hub" },
  { path: "/best-gst-software", label: "Best GST Software", desc: "Top 10 GST tools compared" },
  { path: "/guides", label: "GST Guides", desc: "Step-by-step filing tutorials" },
  { path: "/gstin-validator", label: "GSTIN Validator", desc: "Validate GSTIN format & check digit" },
  { path: "/gst-state-codes", label: "GST State Codes", desc: "State code list & GSTIN state finder" },
  { path: "/scheme-comparison", label: "Scheme Comparison", desc: "Regular vs Composition scheme" },
  { path: "/composition-tax-calculator", label: "Composition Tax Calculator", desc: "Quarterly CMP-08 tax, RCM & limit tracker" },
  { path: "/payment-challan", label: "Payment Challan", desc: "GST PMT-06 challan helper" },
  { path: "/itc-calculator", label: "ITC Calculator", desc: "Calculate Input Tax Credit amount" },
  { path: "/registration-type-advisor", label: "Registration Advisor", desc: "Find the right GST registration type" },
  { path: "/rcm-calculator", label: "RCM Calculator", desc: "Reverse charge with ITC tracking" },
  { path: "/audit-checklist", label: "Audit Checklist", desc: "GST audit compliance tracker" },
  { path: "/late-fee-calculator", label: "Late Fee Calculator", desc: "Calculate late filing fees for GST returns" },
  { path: "/gst-late-fee-interest-calculator", label: "Late Fee + Interest", desc: "Total cost of a late return, with turnover caps" },
  { path: "/gstr9-checklist", label: "GSTR-9 Checklist", desc: "Annual return filing checklist" },
  { path: "/gstr2b-reconciliation", label: "GSTR-2B Reconciliation", desc: "Match purchase register with GSTR-2B" },
  { path: "/gstr3b-reconciliation", label: "GSTR-3B Reconciliation", desc: "Catch DRC-01B/01C risks before filing" },
  { path: "/filing-checklist", label: "Filing Checklist", desc: "Documents & steps tracker for GST returns" },
  { path: "/tds-calculator", label: "TDS Calculator", desc: "Calculate TDS under GST Section 51" },
  { path: "/ecommerce-tcs-calculator", label: "E-commerce TCS", desc: "0.5% GST TCS + 194-O TDS for online sellers" },
  { path: "/place-of-supply", label: "Place of Supply", desc: "Determine inter/intra-state supply" },
  { path: "/refund-calculator", label: "Refund Calculator", desc: "Export & inverted duty refund" },
  { path: "/e-invoice-generator", label: "E-Invoice Generator", desc: "Generate e-invoice JSON for IRP" },
  { path: "/gstr9-helper", label: "GSTR-9 Helper", desc: "Annual return summary calculator" },
  { path: "/gstr9-summary", label: "GSTR-9 Summary", desc: "GSTR-1 vs 3B for the year, DRC-03 amount" },
  { path: "/itc-reconciliation-dashboard", label: "ITC Dashboard", desc: "Books vs GSTR-2B vs 3B, month by month" },
  { path: "/itc-reversal-rule-42", label: "Rule 42 ITC Reversal", desc: "Common credit on exempt supplies" },
  { path: "/itc-180-day-rule", label: "180-Day ITC Reversal", desc: "Rule 37 reversal for unpaid suppliers" },
  { path: "/itc-time-limit", label: "ITC Time Limit", desc: "Last date to claim ITC under 16(4)" },
];

// Contextual cross-links: which tools are most relevant to which page.
// Each key maps a tool path to an array of 3-4 related tool paths.
const RECOMMENDED = {
  "/calculator": ["/reverse-gst-calculator", "/hsn", "/invoice-generator", "/itc-calculator"],
  "/reverse-gst-calculator": ["/calculator", "/hsn", "/invoice-generator", "/itc-calculator"],
  "/gst-on-gold": ["/calculator", "/reverse-gst-calculator", "/hsn", "/invoice-generator"],
  "/gst-on-real-estate": ["/calculator", "/itc-calculator", "/place-of-supply", "/hsn-sac-finder"],
  "/lookup": ["/gstin-validator", "/registration-checker", "/hsn", "/calculator"],
  "/hsn": ["/gst-rates", "/hsn-sac-finder", "/calculator", "/invoice-generator"],
  "/gst-rates": ["/hsn", "/calculator", "/reverse-gst-calculator", "/invoice-generator"],
  "/due-dates": ["/return-calendar", "/penalty-calculator", "/late-fee-calculator", "/interest-calculator"],
  "/penalty-calculator": ["/late-fee-calculator", "/interest-calculator", "/due-dates", "/return-calendar"],
  "/eway-bill": ["/invoice-generator", "/hsn", "/reverse-charge", "/calculator"],
  "/input-tax-credit": ["/itc-calculator", "/itc-time-limit", "/itc-180-day-rule", "/itc-reversal-rule-42"],
  "/composition-scheme": ["/composition-tax-calculator", "/scheme-comparison", "/registration-checker", "/turnover-limit"],
  "/invoice-generator": ["/calculator", "/hsn", "/payment-challan", "/eway-bill"],
  "/reverse-charge": ["/rcm-calculator", "/itc-calculator", "/input-tax-credit", "/calculator"],
  "/itc-mismatch": ["/input-tax-credit", "/itc-calculator", "/audit-checklist", "/calculator"],
  "/registration-checker": ["/registration-type-advisor", "/turnover-limit", "/composition-scheme", "/lookup"],
  "/return-calendar": ["/due-dates", "/penalty-calculator", "/late-fee-calculator", "/interest-calculator"],
  "/interest-calculator": ["/penalty-calculator", "/late-fee-calculator", "/due-dates", "/payment-challan"],
  "/hsn-sac-finder": ["/hsn", "/calculator", "/invoice-generator", "/lookup"],
  "/turnover-limit": ["/registration-checker", "/registration-type-advisor", "/composition-scheme", "/scheme-comparison"],
  "/gstin-validator": ["/lookup", "/gst-state-codes", "/registration-checker", "/calculator"],
  "/gst-state-codes": ["/gstin-validator", "/lookup", "/place-of-supply", "/invoice-generator"],
  "/scheme-comparison": ["/composition-tax-calculator", "/composition-scheme", "/turnover-limit", "/registration-checker"],
  "/composition-tax-calculator": ["/scheme-comparison", "/composition-scheme", "/interest-calculator", "/rcm-calculator"],
  "/payment-challan": ["/calculator", "/interest-calculator", "/penalty-calculator", "/invoice-generator"],
  "/itc-calculator": ["/input-tax-credit", "/itc-reversal-rule-42", "/itc-180-day-rule", "/itc-mismatch"],
  "/registration-type-advisor": ["/registration-checker", "/turnover-limit", "/composition-scheme", "/lookup"],
  "/rcm-calculator": ["/reverse-charge", "/itc-calculator", "/input-tax-credit", "/calculator"],
  "/audit-checklist": ["/gstr9-checklist", "/itc-mismatch", "/itc-calculator", "/due-dates"],
  "/late-fee-calculator": ["/gst-late-fee-interest-calculator", "/interest-calculator", "/due-dates", "/return-calendar"],
  "/gst-late-fee-interest-calculator": ["/late-fee-calculator", "/interest-calculator", "/due-dates", "/payment-challan"],
  "/gstr9-checklist": ["/gstr9-summary", "/audit-checklist", "/due-dates", "/itc-reconciliation-dashboard"],
  "/gstr2b-reconciliation": ["/itc-reconciliation-dashboard", "/itc-mismatch", "/itc-calculator", "/input-tax-credit"],
  "/tds-calculator": ["/ecommerce-tcs-calculator", "/calculator", "/reverse-charge", "/payment-challan"],
  "/itc-reversal-rule-42": ["/itc-180-day-rule", "/input-tax-credit", "/itc-calculator", "/gstr9-summary"],
  "/itc-180-day-rule": ["/itc-reversal-rule-42", "/itc-time-limit", "/interest-calculator", "/input-tax-credit"],
  "/itc-time-limit": ["/itc-reconciliation-dashboard", "/gstr2b-reconciliation", "/itc-180-day-rule", "/gstr9-helper"],
  "/ecommerce-tcs-calculator": ["/tds-calculator", "/payment-challan", "/invoice-generator", "/calculator"],
  "/place-of-supply": ["/gst-state-codes", "/calculator", "/invoice-generator", "/e-invoice-generator"],
  "/refund-calculator": ["/itc-calculator", "/input-tax-credit", "/calculator", "/e-invoice-generator"],
  "/e-invoice-generator": ["/invoice-generator", "/hsn-sac-finder", "/place-of-supply", "/calculator"],
  "/gstr9-helper": ["/gstr9-summary", "/gstr9-checklist", "/audit-checklist", "/itc-reconciliation-dashboard"],
  "/gstr9-summary": ["/gstr9-checklist", "/itc-reconciliation-dashboard", "/gst-late-fee-interest-calculator", "/audit-checklist"],
  "/itc-reconciliation-dashboard": ["/itc-time-limit", "/gstr2b-reconciliation", "/itc-180-day-rule", "/gstr9-summary"],
};

export default function RelatedTools({ current }) {
  const others = ALL_TOOLS.filter((t) => t.path !== current);
  const recommendedPaths = RECOMMENDED[current] || [];
  const recommended = recommendedPaths
    .map((p) => ALL_TOOLS.find((t) => t.path === p))
    .filter(Boolean);
  const rest = others.filter((t) => !recommendedPaths.includes(t.path));

  return (
    <nav className="related-tools" aria-label="Related GST tools">
      {recommended.length > 0 && (
        <>
          <h2 className="related-tools-heading">People Also Use</h2>
          <div className="related-tools-recommended">
            {recommended.map((t) => (
              <Link key={t.path} to={t.path} className="related-tools-link related-tools-highlight">
                <strong>{t.label}</strong>
                <span>{t.desc}</span>
                <span className="related-tools-arrow" aria-hidden="true">→</span>
              </Link>
            ))}
          </div>
        </>
      )}
      <h2 className="related-tools-heading">More Free GST Tools</h2>
      <div className="related-tools-grid">
        {rest.map((t) => (
          <Link key={t.path} to={t.path} className="related-tools-link">
            <strong>{t.label}</strong>
            <span>{t.desc}</span>
          </Link>
        ))}
      </div>
    </nav>
  );
}

export { ALL_TOOLS, RECOMMENDED };
