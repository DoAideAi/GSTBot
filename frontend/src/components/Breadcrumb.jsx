import { Link, useLocation } from "react-router-dom";

const ROUTE_LABELS = {
  "/calculator": "GST Calculator",
  "/lookup": "GSTIN Lookup",
  "/hsn": "HSN Code Finder",
  "/due-dates": "Due Dates Calendar",
  "/resources": "Resources",
  "/embed": "Embed Widget",
  "/pricing": "Pricing",
  "/blog": "Blog",
  "/penalty-calculator": "Penalty Calculator",
  "/eway-bill": "E-Way Bill Checker",
  "/input-tax-credit": "ITC Eligibility",
  "/registration-checker": "Registration Checker",
  "/return-calendar": "Return Due Date Calendar",
  "/interest-calculator": "Interest Calculator",
  "/reverse-gst-calculator": "Reverse GST Calculator",
  "/hsn-sac-finder": "HSN/SAC Code Finder",
  "/late-fee-calculator": "Late Fee Calculator",
  "/gstr9-checklist": "GSTR-9 Annual Return Checklist",
};

export default function Breadcrumb({ items }) {
  const { pathname } = useLocation();

  const crumbs = items || [
    { label: "Home", to: "/" },
    ...(ROUTE_LABELS[pathname]
      ? [{ label: ROUTE_LABELS[pathname] }]
      : []),
  ];

  if (crumbs.length < 2) return null;

  return (
    <nav className="breadcrumb" aria-label="Breadcrumb">
      <ol className="breadcrumb-list">
        {crumbs.map((crumb, i) => {
          const isLast = i === crumbs.length - 1;
          return (
            <li key={crumb.label} className="breadcrumb-item">
              {isLast || !crumb.to ? (
                <span aria-current="page">{crumb.label}</span>
              ) : (
                <>
                  <Link to={crumb.to}>{crumb.label}</Link>
                  <span className="breadcrumb-sep" aria-hidden="true">/</span>
                </>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
