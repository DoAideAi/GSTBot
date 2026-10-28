import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { api } from "../lib/api";
import BusinessSwitcher from "./BusinessSwitcher";
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
    api.currentSubscription()
      // Only an active plan earns the badge: a paid period that ran out comes
      // back as status "expired" with its tier still set.
      .then((sub) => { if (!stale) setSubTier(sub?.status === "active" ? sub.tier : "free"); })
      .catch(() => {});
    return () => { stale = true; };
  }, [businessId]);

  useEffect(() => fetchAlertCount(), [fetchAlertCount]);
  // Re-fetch when navigating away from alerts (user may have dismissed some).
  useEffect(() => {
    if (location.pathname !== "/alerts") fetchAlertCount();
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
          <svg viewBox="0 0 400 320" className="brand-robot" aria-hidden="true">
            <defs><linearGradient id="hg-nav" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#F0B429" /><stop offset="100%" stopColor="#D4A017" /></linearGradient></defs>
            <line x1="200" y1="45" x2="200" y2="20" stroke="#F0B429" strokeWidth="6" strokeLinecap="round" />
            <circle cx="200" cy="14" r="10" fill="#F0B429" /><circle cx="200" cy="14" r="5" fill="#F7CC5F" />
            <rect x="110" y="50" width="180" height="140" rx="35" fill="url(#hg-nav)" />
            <rect x="130" y="68" width="140" height="105" rx="25" fill="#D4A017" opacity="0.4" />
            <ellipse cx="165" cy="115" rx="18" ry="20" fill="#0A0A0B" /><ellipse cx="235" cy="115" rx="18" ry="20" fill="#0A0A0B" />
            <circle cx="170" cy="113" r="8" fill="#F7CC5F" /><circle cx="240" cy="113" r="8" fill="#F7CC5F" />
            <circle cx="174" cy="109" r="3" fill="white" opacity="0.7" /><circle cx="244" cy="109" r="3" fill="white" opacity="0.7" />
            <path d="M170 155Q200 178 230 155" stroke="#0A0A0B" strokeWidth="4" fill="none" strokeLinecap="round" />
            <rect x="92" y="95" width="22" height="45" rx="8" fill="#D4A017" /><rect x="286" y="95" width="22" height="45" rx="8" fill="#D4A017" />
            <rect x="175" y="190" width="50" height="14" rx="5" fill="#D4A017" />
            <rect x="145" y="204" width="110" height="55" rx="18" fill="url(#hg-nav)" />
            <circle cx="200" cy="228" r="7" fill="#0A0A0B" /><circle cx="200" cy="228" r="3.5" fill="#0A0A0B" />
            <path d="M145 218Q118 223 113 240Q108 257 120 262" stroke="#D4A017" strokeWidth="9" fill="none" strokeLinecap="round" /><circle cx="120" cy="265" r="7" fill="#D4A017" />
            <path d="M255 218Q282 223 287 240Q292 257 280 262" stroke="#D4A017" strokeWidth="9" fill="none" strokeLinecap="round" /><circle cx="280" cy="265" r="7" fill="#D4A017" />
          </svg>
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
