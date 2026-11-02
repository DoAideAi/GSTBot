import BrandMark from "./BrandMark";
import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { SUBSCRIPTION_CHANGED, api } from "../lib/api";
import BusinessSwitcher from "./BusinessSwitcher";
import ExportAccountButton from "./ExportAccountButton";
import ThemeToggle from "./ThemeToggle";

const LINKS = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/invoices", label: "Invoices" },
  { to: "/upload", label: "Upload" },
  { to: "/reconcile", label: "Reconcile" },
  { to: "/itc", label: "ITC" },
  { to: "/filing", label: "Filing" },
  { to: "/suppliers", label: "Suppliers" },
  { to: "/bulk-gstin", label: "Bulk GSTIN" },
  { to: "/alerts", label: "Alerts", badge: true },
  { to: "/pricing", label: "Pricing" },
  { to: "/usage", label: "Usage" },
];

const TIER_BADGE = { pro: "PRO", enterprise: "CA" };

export default function Shell({ children }) {
  const { logout, user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [navOpen, setNavOpen] = useState(false);
  const [alertCount, setAlertCount] = useState(0);
  const [subTier, setSubTier] = useState(null);
  const toggleRef = useRef(null);

  const businessId = user?.business?.id;
  const fetchAlertCount = useCallback(() => {
    if (!businessId) return;
    const ctrl = new AbortController();
    api.listAlerts({ limit: 1 }, { signal: ctrl.signal })
      .then((res) => setAlertCount(res.open_total ?? 0))
      .catch(() => {});
    return () => ctrl.abort();
  }, [businessId]);

  useEffect(() => {
    if (!businessId) return;
    let stale = false;
    const load = () =>
      api.currentSubscription()
        // Only an active plan earns the badge: a paid period that ran out comes
        // back as status "expired" with its tier still set.
        .then((sub) => { if (!stale) setSubTier(sub?.status === "active" ? sub.tier : "free"); })
        .catch(() => {});
    load();
    // And again when the plan changes in this tab: fetched only per business,
    // the badge stayed off after a payment until the page was reloaded.
    window.addEventListener(SUBSCRIPTION_CHANGED, load);
    return () => {
      stale = true;
      window.removeEventListener(SUBSCRIPTION_CHANGED, load);
    };
  }, [businessId]);

  // On load, on a business switch, and on each move to another page — the
  // user may have dismissed some on the alerts list — but not on arriving at
  // that list, which loads its own. One effect: there were two, "on mount"
  // and "whenever the path is not /alerts", and the second ran on mount too,
  // so every page load asked GET /alerts twice for one number, and the second
  // request's abort was dropped.
  const lastPath = useRef(null);
  useEffect(() => {
    const arrivedAtAlerts =
      location.pathname === "/alerts" &&
      lastPath.current !== null &&
      lastPath.current !== location.pathname;
    lastPath.current = location.pathname;
    if (arrivedAtAlerts) return undefined;
    return fetchAlertCount();
  }, [location.pathname, fetchAlertCount]);

  // Eight links do not fit on a phone, so below 860px they collapse behind a
  // button. The menu stays in the DOM either way — CSS decides whether it is a
  // row or a drawer — so there is one nav for assistive tech rather than two
  // that can drift apart.
  useEffect(() => {
    setNavOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!navOpen) return undefined;
    function onKeyDown(event) {
      if (event.key === "Escape") {
        setNavOpen(false);
        // Focus goes back to the control that opened the drawer; leaving it on
        // a now-hidden link strands keyboard users at the top of the document.
        toggleRef.current?.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [navOpen]);

  function handleLogout() {
    logout();
    navigate("/login");
  }

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <header className="shell-header">
        <div className="brand">
          <BrandMark />
          <span className="brand-name">DoAide <span className="brand-accent">GST</span></span>
        </div>

        <button
          type="button"
          ref={toggleRef}
          className="nav-toggle"
          aria-expanded={navOpen}
          aria-controls="main-nav"
          onClick={() => setNavOpen((open) => !open)}
        >
          <span className="nav-toggle-bars" aria-hidden="true" />
          <span className="visually-hidden">{navOpen ? "Close menu" : "Open menu"}</span>
        </button>

        <nav
          id="main-nav"
          className={navOpen ? "shell-nav is-open" : "shell-nav"}
          aria-label="Main"
        >
          {LINKS.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end}
              className={({ isActive }) => (isActive ? "nav-link is-active" : "nav-link")}
            >
              {link.label}
              {link.badge && alertCount > 0 && (
                <>
                  <span className="nav-badge" aria-hidden="true">
                    {alertCount > 99 ? "99+" : alertCount}
                  </span>
                  <span className="visually-hidden">
                    {` (${alertCount} open)`}
                  </span>
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="shell-user">
          {TIER_BADGE[subTier] && (
            <NavLink to="/pricing" className="tier-badge" title="Premium plan active">
              {TIER_BADGE[subTier]}
            </NavLink>
          )}
          <BusinessSwitcher />
          <ThemeToggle />
          <ExportAccountButton />
          <button type="button" className="btn btn-ghost" onClick={handleLogout}>
            Sign out
          </button>
        </div>
      </header>

      {/* Tapping outside the drawer closes it. Hidden from assistive tech: the
          Escape handler above is the accessible equivalent. */}
      {navOpen && (
        <div className="nav-scrim" onClick={() => setNavOpen(false)} aria-hidden="true" />
      )}

      <main className="shell-main" id="main">
        {children}
      </main>
    </div>
  );
}
