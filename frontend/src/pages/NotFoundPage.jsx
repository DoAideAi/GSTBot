import { useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { usePageTitle } from "../hooks/usePageTitle";

// What an unknown URL renders. It used to be a silent <Navigate to="/">, which
// read as "the link worked and the homepage is what it pointed at": a mistyped
// tool URL or a stale bookmark dropped the visitor on a page with no mention
// of what they were looking for. Saying so, and offering the tools people
// actually come for, keeps them on the site.
//
// The static server already answers these paths with the noindex app shell;
// the robots tag here covers a client-side navigation into a dead link, where
// the head is whatever the previous page left behind.
const POPULAR = [
  { to: "/calculator", label: "GST Calculator" },
  { to: "/lookup", label: "GSTIN Verification" },
  { to: "/hsn", label: "HSN / SAC Code Finder" },
  { to: "/due-dates", label: "GST Due Dates" },
  { to: "/late-fee-calculator", label: "Late Fee Calculator" },
  { to: "/invoice-generator", label: "GST Invoice Generator" },
];

function useNoIndex() {
  useEffect(() => {
    let el = document.querySelector('meta[name="robots"]');
    const previous = el?.getAttribute("content") ?? null;
    if (!el) {
      el = document.createElement("meta");
      el.setAttribute("name", "robots");
      document.head.appendChild(el);
    }
    el.setAttribute("content", "noindex");
    return () => {
      if (previous === null) el.remove();
      else el.setAttribute("content", previous);
    };
  }, []);
}

export default function NotFoundPage() {
  usePageTitle("Page not found");
  useNoIndex();
  const { pathname } = useLocation();

  return (
    <main className="shell-main" style={{ maxWidth: 640, margin: "0 auto", padding: "48px 20px" }}>
      <h1 style={{ marginTop: 0 }}>Page not found</h1>
      <p className="muted" style={{ wordBreak: "break-all" }}>
        Nothing lives at <code>{pathname}</code>. The link may be old or mistyped.
      </p>
      <h2 style={{ fontSize: 18, marginTop: 32 }}>Free GST tools — no sign-up</h2>
      <ul style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 8, padding: 0, listStyle: "none" }}>
        {POPULAR.map((tool) => (
          <li key={tool.to}>
            <Link to={tool.to} className="btn" style={{ display: "block", textAlign: "center" }}>
              {tool.label}
            </Link>
          </li>
        ))}
      </ul>
      <p style={{ marginTop: 32 }}>
        <Link to="/" className="btn btn-primary">Go to the homepage</Link>
      </p>
    </main>
  );
}
