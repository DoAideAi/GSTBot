import { Link, useLocation } from "react-router-dom";

const TOOLS = [
  { path: "/calculator", label: "GST Calculator" },
  { path: "/lookup", label: "GSTIN Lookup" },
  { path: "/hsn", label: "HSN Finder" },
  { path: "/due-dates", label: "Due Dates" },
  { path: "/tools/composition-scheme-checker", label: "Composition Checker" },
  { path: "/resources", label: "All Tools" },
];

export default function ToolsNav() {
  const { pathname } = useLocation();

  return (
    <nav className="tools-nav" aria-label="GST tools">
      <a href="https://gst.doaide.com" className="tools-nav-brand">
        DoAide <em>GST</em>
      </a>
      <div className="tools-nav-links">
        {TOOLS.map((t) => (
          <Link
            key={t.path}
            to={t.path}
            className={`tools-nav-link${pathname === t.path ? " active" : ""}`}
          >
            {t.label}
          </Link>
        ))}
      </div>
      <Link to="/login" className="tools-nav-cta">Sign up free</Link>
    </nav>
  );
}
