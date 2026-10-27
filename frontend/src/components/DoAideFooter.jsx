const DOAIDE_TOOLS = [
  {
    icon: "\u{1F4C4}",
    name: "Docs",
    url: "https://docs.doaide.com",
    desc: "Free document generator — rent receipts, agreements & more",
  },
  {
    icon: "\u{1F4DD}",
    name: "Resume",
    url: "https://resume.doaide.com",
    desc: "AI resume builder with ATS optimization",
  },
  {
    icon: "\u{1F4CA}",
    name: "409A Valuations",
    url: "https://409.doaide.com",
    desc: "Independent startup valuations",
  },
  {
    icon: "\u{1F6E1}️",
    name: "InsureKit",
    url: "https://insure.doaide.com",
    desc: "LIC insurance calculators & tools",
  },
  {
    icon: "\u{1F4B0}",
    name: "TaxFile",
    url: "https://tax.doaide.com",
    desc: "Income tax & financial calculators",
  },
  {
    icon: "\u{1F4C8}",
    name: "Pulse",
    url: "https://pulse.doaide.com",
    desc: "Newsletter growth & email tools",
  },
  {
    icon: "\u{1F9FE}",
    name: "Invoicer",
    url: "https://invoicer.doaide.com",
    desc: "Create GST invoices in seconds",
  },
  {
    icon: "\u{1F4DD}",
    name: "Contracts",
    url: "https://contracts.doaide.com",
    desc: "Draft & manage business contracts",
  },
  {
    icon: "\u{1F3E0}",
    name: "HomeNex",
    url: "https://homenex.aiknol.com",
    desc: "AI CRM for real estate agents",
  },
];

export default function DoAideFooter() {
  return (
    <footer className="doaide-footer" aria-label="More free tools from DoAide">
      <div className="doaide-footer-inner">
        <p className="doaide-footer-heading">More free tools from DoAide</p>
        <div className="doaide-footer-grid">
          {DOAIDE_TOOLS.map((tool) => (
            <a
              key={tool.url}
              href={tool.url}
              className="doaide-footer-link"
              target="_blank"
              rel="noopener noreferrer"
            >
              <span className="doaide-footer-icon">{tool.icon}</span>
              <span>
                <strong>{tool.name}</strong>
                <span>{tool.desc}</span>
              </span>
            </a>
          ))}
        </div>
        <p className="doaide-footer-viewall">
          <a href="https://doaide.com" target="_blank" rel="noopener noreferrer">
            View all 40+ tools &rarr;
          </a>
        </p>
      </div>
    </footer>
  );
}
