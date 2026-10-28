import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { useBottomBar } from "../lib/floatingLayout";
import { track } from "../lib/track";

const DISMISS_KEY = "gstbot_cta_dismissed";
const REMIND_KEY = "gstbot_remind_dismissed";

function isDismissed(key) {
  try {
    const ts = localStorage.getItem(key);
    if (!ts) return false;
    // Resurface after 7 days
    return Date.now() - parseInt(ts, 10) < 7 * 24 * 60 * 60 * 1000;
  } catch {
    return false;
  }
}

function dismiss(key) {
  try {
    localStorage.setItem(key, String(Date.now()));
  } catch {
    // localStorage unavailable, that's fine
  }
}

/**
 * Inline CTA banner shown on tool pages to encourage sign-up or filing reminders.
 * Renders nothing if the user is logged in.
 */
export function InlineCTA({ variant = "save" }) {
  const { user } = useAuth();
  const [dismissed, setDismissed] = useState(false);

  if (user || dismissed) return null;

  const configs = {
    save: {
      icon: (
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z" />
          <polyline points="17 21 17 13 7 13 7 21" />
          <polyline points="7 3 7 8 15 8" />
        </svg>
      ),
      title: "Save your calculations",
      desc: "Create a free account to keep your calculation history and access it from any device.",
      cta: "Create Free Account",
      link: "/login",
      trackEvent: "cta_inline_save",
    },
    remind: {
      icon: (
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M18 8A6 6 0 106 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 01-3.46 0" />
        </svg>
      ),
      title: "Never miss a GST deadline",
      desc: "Get email reminders before GSTR-1 and GSTR-3B due dates — free, no account needed.",
      cta: "Get Filing Reminders",
      link: "/due-dates",
      trackEvent: "cta_inline_remind",
    },
    invoice: {
      icon: (
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
        </svg>
      ),
      title: "Automate your GST filing",
      desc: "Upload invoices, auto-reconcile GSTR-2B, and prepare returns in minutes. Free for 50 invoices/month.",
      cta: "Start Free",
      link: "/login",
      trackEvent: "cta_inline_invoice",
    },
  };

  const cfg = configs[variant] || configs.save;

  return (
    <div className="conversion-cta-inline" role="complementary" aria-label="Sign up prompt">
      <div className="conversion-cta-inline-content">
        <div className="conversion-cta-inline-icon">{cfg.icon}</div>
        <div className="conversion-cta-inline-text">
          <strong>{cfg.title}</strong>
          <span>{cfg.desc}</span>
        </div>
      </div>
      <div className="conversion-cta-inline-actions">
        <Link
          to={cfg.link}
          className="btn btn-primary btn-sm"
          onClick={() => track(cfg.trackEvent)}
        >
          {cfg.cta}
        </Link>
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => { setDismissed(true); dismiss(DISMISS_KEY); }}
          aria-label="Dismiss"
        >
          Not now
        </button>
      </div>
    </div>
  );
}

/**
 * Sticky mobile bottom bar with primary CTA. Shown on tool pages for non-logged-in users.
 * Hidden on desktop. Disappears once the user scrolls to the existing CTA or dismisses.
 */
export function StickyMobileCTA() {
  const { user } = useAuth();
  const [visible, setVisible] = useState(false);
  const [dismissed, setDismissed] = useState(() => isDismissed(REMIND_KEY));
  const bar = useRef(null);
  useBottomBar(bar, Boolean(!user && !dismissed && visible));

  useEffect(() => {
    if (user || dismissed) return;
    // Show after a short scroll
    const onScroll = () => {
      setVisible(window.scrollY > 300);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [user, dismissed]);

  if (user || dismissed || !visible) return null;

  return (
    <div ref={bar} className="sticky-mobile-cta" role="complementary" aria-label="Sign up">
      <Link
        to="/login"
        className="btn btn-primary sticky-mobile-cta-btn"
        onClick={() => track("cta_sticky_mobile")}
      >
        Start Free — No Credit Card
      </Link>
      <button
        className="sticky-mobile-cta-close"
        onClick={() => { setDismissed(true); dismiss(REMIND_KEY); }}
        aria-label="Close"
      >
        ×
      </button>
    </div>
  );
}
