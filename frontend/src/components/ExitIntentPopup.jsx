import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { track } from "../lib/track";

const DISMISS_KEY = "gstbot_exit_popup_dismissed";

function wasDismissed() {
  try {
    const ts = localStorage.getItem(DISMISS_KEY);
    if (!ts) return false;
    return Date.now() - parseInt(ts, 10) < 3 * 24 * 60 * 60 * 1000;
  } catch {
    return false;
  }
}

export default function ExitIntentPopup() {
  const { user } = useAuth();
  const [visible, setVisible] = useState(false);
  const closeRef = useRef(null);
  const dialogRef = useRef(null);

  useEffect(() => {
    if (user || wasDismissed()) return;
    let shown = false;

    const onMouseLeave = (e) => {
      if (shown) return;
      if (e.clientY <= 0) {
        shown = true;
        setVisible(true);
        track("exit_intent_shown");
      }
    };

    document.addEventListener("mouseout", onMouseLeave);
    return () => document.removeEventListener("mouseout", onMouseLeave);
  }, [user]);

  // A modal dialog has to be reachable and escapable from the keyboard. It
  // declared aria-modal but took no focus and ignored Escape, so a keyboard
  // user was left behind it with no way to close it but tabbing to the ×.
  //
  // aria-modal also tells a screen reader the page behind is inert, so Tab has
  // to stay inside: it walked out of the last control into that page. And
  // closing it left focus on <body>, so focus goes back where it came from.
  useEffect(() => {
    if (!visible) return undefined;
    const opener = document.activeElement;
    closeRef.current?.focus();
    const onKeyDown = (e) => {
      if (e.key === "Escape") {
        dismiss();
        return;
      }
      if (e.key !== "Tab" || !dialogRef.current) return;
      const controls = dialogRef.current.querySelectorAll("a[href], button");
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (opener instanceof HTMLElement && opener !== document.body) opener.focus();
    };
  }, [visible]);

  if (!visible) return null;

  const dismiss = () => {
    setVisible(false);
    try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch { /* localStorage unavailable */ }
  };

  return (
    <div className="exit-popup-overlay" onClick={dismiss} role="dialog" aria-modal="true" aria-label="Filing reminder signup">
      <div className="exit-popup" ref={dialogRef} onClick={(e) => e.stopPropagation()}>
        <button ref={closeRef} className="exit-popup-close" onClick={dismiss} aria-label="Close">×</button>
        <div className="exit-popup-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="#D4AF37" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 8A6 6 0 106 8c0 7-3 9-3 9h18s-3-2-3-9" />
            <path d="M13.73 21a2 2 0 01-3.46 0" />
          </svg>
        </div>
        <h2 className="exit-popup-title">Never Miss a GST Filing Deadline</h2>
        <p className="exit-popup-desc">
          Get free email reminders before GSTR-1 and GSTR-3B due dates.
          No account required — just your email.
        </p>
        <Link
          to="/due-dates"
          className="btn btn-primary exit-popup-btn"
          onClick={() => { track("exit_intent_signup"); dismiss(); }}
        >
          Get Free Filing Reminders
        </Link>
        <button className="exit-popup-skip" onClick={dismiss}>
          No thanks, I&apos;ll remember on my own
        </button>
      </div>
    </div>
  );
}
