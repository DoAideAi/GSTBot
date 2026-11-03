import BrandMark from "./BrandMark";
import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { SUBSCRIPTION_CHANGED, api } from "../lib/api";
import BusinessSwitcher from "./BusinessSwitcher";
import ExportAccountButton from "./ExportAccountButton";
import ThemeToggle from "./ThemeToggle";

const LINKS = [
  { to: "/", label: "Dashboard", end: true, group: "Workspace", icon: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z" },
  { to: "/action-agent", label: "AI action plan", group: "Workspace", icon: "M12 3v4m0 10v4M3 12h4m10 0h4M7 7l2 2m6 6 2 2M7 17l2-2m6-6 2-2M12 8l4 4-4 4-4-4z" },
  { to: "/invoices", label: "Invoices", group: "Workspace", icon: "M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h5" },
  { to: "/upload", label: "Upload", group: "Workspace", icon: "M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6" },
  { to: "/reconcile", label: "Reconcile", group: "Workspace", icon: "M4 7h16m-4-4 4 4-4 4M20 17H4m4-4-4 4 4 4" },
  { to: "/itc", label: "ITC", group: "Workspace", icon: "M4 3h16v18H4zM8 7h8M8 11h5m-5 5 2 2 5-5" },
  { to: "/filing", label: "Filing", group: "Workspace", icon: "M6 3h9l4 4v14H6zM14 3v5h5m-10 7 2 2 4-4" },
  { to: "/clients", label: "Client work queue", group: "Management", icon: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z" },
  { to: "/client-access", label: "Client access", group: "Management", icon: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8M20 8v6m-3-3h6" },
  { to: "/purchase-import", label: "Import register", group: "Workspace", icon: "M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5" },
  { to: "/suppliers", label: "Suppliers", group: "Management", icon: "M4 21V7l8-4 8 4v14M9 21v-5h6v5M8 9h1m6 0h1m-8 3h1m6 0h1" },
  { to: "/bulk-gstin", label: "Bulk GSTIN", group: "Management", icon: "M8 3h12v14H8zM4 7v14h12M11 7h6m-6 4h6" },
  { to: "/alerts", label: "Alerts", badge: true, group: "Management", icon: "M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" },
  { to: "/pricing", label: "Pricing", group: "Account", icon: "M3 5h18v14H3zM3 10h18M7 15h4" },
  { to: "/usage", label: "Usage", group: "Account", icon: "M4 3v18h17M8 16v-4m5 4V7m5 9V4" },
];

const NAV_GROUPS = ["Workspace", "Management", "Account"];

const TIER_BADGE = { pro: "PRO", enterprise: "CA" };

export default function Shell({ children }) {
  const { logout, user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [navOpen, setNavOpen] = useState(false);
  const [alertCount, setAlertCount] = useState(0);
  const [subTier, setSubTier] = useState(null);
  const [pilotEnd, setPilotEnd] = useState(null);
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
        .then((sub) => { if (!stale) {
          setSubTier(sub?.status === "active" ? sub.tier : "free");
          setPilotEnd(sub?.source === "pilot" && sub.status === "active" ? sub.current_period_end : null);
        } })
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

  // The same navigation serves the desktop sidebar and mobile drawer.
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
        <NavLink to="/" className="brand" aria-label="DoAide GST dashboard">
          <BrandMark />
          <span className="brand-name">DoAide <span className="brand-accent">GST</span></span>
        </NavLink>
        <span className="shell-label">Workspace</span>
        <div className="shell-business-controls">
          <BusinessSwitcher />
          {TIER_BADGE[subTier] && (
            <NavLink to="/pricing" className="tier-badge" title={pilotEnd ? "Free pilot active — see pricing for the end date" : "Premium plan active"}>
              {TIER_BADGE[subTier]}{pilotEnd ? " PILOT" : ""}
            </NavLink>
          )}
        </div>
        <div className="shell-header-actions">
          <ThemeToggle />
          <button
            type="button"
            ref={toggleRef}
            className="nav-toggle"
            aria-expanded={navOpen}
            aria-controls="main-nav"
            onClick={() => setNavOpen((open) => !open)}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d={navOpen ? "M6 6l12 12M6 18 18 6" : "M4 6h16M4 12h16M4 18h16"} /></svg>
            <span className="visually-hidden">{navOpen ? "Close menu" : "Open menu"}</span>
          </button>
        </div>
      </header>

      <aside className={navOpen ? "workspace-sidebar is-open" : "workspace-sidebar"}>
        <nav
          id="main-nav"
          className={navOpen ? "shell-nav is-open" : "shell-nav"}
          aria-label="Main"
        >
          {NAV_GROUPS.map((group) => (
            <div className="workspace-nav-group" key={group}>
              <h2>{group}</h2>
              {LINKS.filter((link) => link.group === group).map((link) => (
                <NavLink
                  key={link.to}
                  to={link.to}
                  end={link.end}
                  onClick={() => setNavOpen(false)}
                  className={({ isActive }) => (isActive ? "nav-link is-active" : "nav-link")}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={link.icon} /></svg>
                  <span>{link.label}</span>
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
            </div>
          ))}
        </nav>

        <div className="workspace-account">
          <p className="workspace-account-label">Signed in as</p>
          <p className="workspace-account-email" title={user?.email}>{user?.email}</p>
          <div className="workspace-account-actions">
            <ExportAccountButton />
            <button type="button" className="btn btn-ghost" onClick={handleLogout}>
              Sign out
            </button>
          </div>
        </div>
      </aside>

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
