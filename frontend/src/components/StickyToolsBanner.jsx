import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useBottomBar } from "../lib/floatingLayout";
import { track } from "../lib/track";

const DISMISS_KEY = "gstbot_tools_banner_dismissed";

function isDismissed() {
  try {
    const ts = localStorage.getItem(DISMISS_KEY);
    if (!ts) return false;
    return Date.now() - parseInt(ts, 10) < 3 * 24 * 60 * 60 * 1000;
  } catch {
    return false;
  }
}

export default function StickyToolsBanner() {
  const [visible, setVisible] = useState(false);
  const [dismissed, setDismissed] = useState(() => isDismissed());
  const bar = useRef(null);
  useBottomBar(bar, visible && !dismissed);

  useEffect(() => {
    if (dismissed) return;
    const onScroll = () => setVisible(window.scrollY > 400);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [dismissed]);

  if (dismissed || !visible) return null;

  const handleDismiss = () => {
    setDismissed(true);
    try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch { /* localStorage unavailable */ }
  };

  return (
    <div ref={bar} className="sticky-tools-banner" role="complementary" aria-label="Free tools banner">
      <div className="sticky-tools-banner-inner">
        <span className="sticky-tools-banner-text">
          <strong>25+ free GST tools</strong> — no login needed. Calculate, verify, and file GST instantly.
        </span>
        <Link
          to="/resources"
          className="btn btn-primary btn-sm sticky-tools-banner-btn"
          onClick={() => track("sticky_tools_banner_click")}
        >
          Explore All Tools
        </Link>
        <button
          className="sticky-tools-banner-close"
          onClick={handleDismiss}
          aria-label="Dismiss banner"
        >
          ×
        </button>
      </div>
    </div>
  );
}
