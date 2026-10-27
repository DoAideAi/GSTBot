const CROSS_LINKS = {
  calculator: [
    {
      href: "https://invoicer.doaide.com",
      label: "Free Invoice Generator",
      text: "Need to generate a GST invoice? Try our free Invoice Generator",
    },
    {
      href: "https://calc.doaide.com",
      label: "Financial Calculators",
      text: "Explore more financial calculators — EMI, SIP, FD & more",
    },
  ],
  gstin: [
    {
      href: "https://comply.doaide.com",
      label: "Compliance Tracker",
      text: "Track your GST compliance status with automated deadline alerts",
    },
    {
      href: "https://contracts.doaide.com",
      label: "Contract Generator",
      text: "Generate vendor & supplier contracts with built-in GST clauses",
    },
  ],
  "due-dates": [
    {
      href: "https://comply.doaide.com",
      label: "Compliance Tracker",
      text: "Never miss a deadline — set up automated compliance reminders",
    },
    {
      href: "https://invoicer.doaide.com",
      label: "Invoice Generator",
      text: "Generate GST-compliant invoices before your filing deadline",
    },
  ],
  hsn: [
    {
      href: "/calculator",
      label: "GST Calculator",
      text: "Calculate GST for this product — get instant CGST, SGST, IGST breakdown",
      internal: true,
    },
    {
      href: "https://invoicer.doaide.com",
      label: "Invoice Generator",
      text: "Create invoices with the correct HSN code and GST rate applied",
    },
  ],
  lookup: [
    {
      href: "https://comply.doaide.com",
      label: "Compliance Tracker",
      text: "Monitor GST compliance status for all your suppliers",
    },
    {
      href: "https://contracts.doaide.com",
      label: "Contract Generator",
      text: "Draft vendor agreements with verified GSTIN details",
    },
  ],
  "composition-scheme": [
    {
      href: "/calculator",
      label: "GST Calculator",
      text: "Calculate GST at composition scheme rates or regular rates",
      internal: true,
    },
    {
      href: "https://comply.doaide.com",
      label: "Compliance Tracker",
      text: "Track CMP-08 quarterly filings and GSTR-4 annual return deadlines",
    },
  ],
  "invoice-generator": [
    {
      href: "https://invoicer.doaide.com",
      label: "Advanced Invoice Generator",
      text: "Need recurring invoices, templates, and client management? Try our full invoicing platform",
    },
    {
      href: "/calculator",
      label: "GST Calculator",
      text: "Calculate GST breakdown before creating your invoice",
      internal: true,
    },
  ],
  "reverse-charge": [
    {
      href: "/input-tax-credit",
      label: "ITC Eligibility Checker",
      text: "Check if you can claim ITC on GST paid under reverse charge",
      internal: true,
    },
    {
      href: "https://comply.doaide.com",
      label: "Compliance Tracker",
      text: "Track RCM payment deadlines and GSTR-3B filing dates",
    },
  ],
  "itc-mismatch": [
    {
      href: "/input-tax-credit",
      label: "ITC Eligibility Checker",
      text: "Verify which purchases qualify for Input Tax Credit",
      internal: true,
    },
    {
      href: "https://comply.doaide.com",
      label: "Compliance Tracker",
      text: "Automate monthly ITC reconciliation with GSTR-2B data",
    },
  ],
  "penalty-calculator": [
    {
      href: "/due-dates",
      label: "Due Dates Calendar",
      text: "View all GST filing deadlines to avoid late penalties",
      internal: true,
    },
    {
      href: "https://comply.doaide.com",
      label: "Compliance Tracker",
      text: "Set up automated reminders before every GST filing deadline",
    },
  ],
  "eway-bill": [
    {
      href: "/invoice-generator",
      label: "GST Invoice Generator",
      text: "Generate GST invoices with correct HSN codes and tax calculation",
      internal: true,
    },
    {
      href: "https://comply.doaide.com",
      label: "Compliance Tracker",
      text: "Track e-way bill expiry and renewal deadlines",
    },
  ],
  "input-tax-credit": [
    {
      href: "/itc-mismatch",
      label: "ITC Mismatch Calculator",
      text: "Compare GSTR-2A/2B with your books to find ITC discrepancies",
      internal: true,
    },
    {
      href: "/reverse-charge",
      label: "Reverse Charge Calculator",
      text: "Calculate RCM liability — GST paid under RCM is eligible for ITC",
      internal: true,
    },
  ],
};

export default function CrossProductLinks({ page }) {
  const links = CROSS_LINKS[page];
  if (!links) return null;

  return (
    <aside className="cross-product-links" aria-label="Explore more DoAide tools">
      <h3 className="cross-product-heading">Explore More Tools</h3>
      <div className="cross-product-grid">
        {links.map((link) =>
          link.internal ? (
            <a key={link.href} href={link.href} className="cross-product-card">
              <strong>{link.label}</strong>
              <span>{link.text}</span>
            </a>
          ) : (
            <a
              key={link.href}
              href={link.href}
              className="cross-product-card"
              target="_blank"
              rel="noopener noreferrer"
            >
              <strong>{link.label}</strong>
              <span>{link.text}</span>
              <span className="cross-product-external" aria-hidden="true">↗</span>
            </a>
          )
        )}
      </div>
    </aside>
  );
}
