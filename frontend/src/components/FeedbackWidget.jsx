import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../lib/api";
import { routeChanged, snapshot } from "../lib/sessionTracker";

export const CATEGORIES = [
  ["bug", "Bug Report"],
  ["feature", "Feature Request"],
  ["general", "General Feedback"],
  ["other", "Other"],
];

const MAX_MESSAGE = 5000;

// The page the visitor was on, without its query string or fragment. Those
// can carry a sign-in callback's code or a reset link's token, and a feedback
// note is no place to keep either.
function currentPageUrl() {
  const { origin, pathname } = window.location;
  return `${origin}${pathname}`;
}

export default function FeedbackWidget() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState("general");
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const messageRef = useRef(null);
  const buttonRef = useRef(null);
  const ids = useId();

  // A new page is a new context: close anything half-written about the last
  // one, and start the page's time, scroll and clicks from zero.
  useEffect(() => {
    setOpen(false);
    routeChanged(location.pathname);
  }, [location.pathname]);

  useEffect(() => {
    if (open && !sent) messageRef.current?.focus();
  }, [open, sent]);

  const close = useCallback(() => {
    setOpen(false);
    setError("");
    if (sent) {
      setSent(false);
      setMessage("");
      setEmail("");
      setCategory("general");
    }
    buttonRef.current?.focus();
  }, [sent]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, close]);

  const submit = async (e) => {
    e.preventDefault();
    if (!message.trim() || sending) return;
    setSending(true);
    setError("");
    try {
      await api.feedback({
        category,
        message: message.trim(),
        email: email.trim() || null,
        page_url: currentPageUrl(),
        metadata: snapshot(),
      });
      setSent(true);
    } catch (err) {
      // Said, not swallowed: a visitor told "thanks" for a note that never
      // arrived has no reason to send it again.
      setError(err?.message || "Your feedback could not be sent. Please try again.");
    } finally {
      setSending(false);
    }
  };

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className="feedback-float"
        data-feedback-widget
        onClick={() => (open ? close() : setOpen(true))}
        aria-expanded={open}
        aria-controls={`${ids}-dialog`}
      >
        Feedback
      </button>

      {open && (
        <div
          id={`${ids}-dialog`}
          className="feedback-modal"
          data-feedback-widget
          role="dialog"
          aria-labelledby={`${ids}-title`}
        >
          <div className="feedback-header">
            <h2 id={`${ids}-title`} className="feedback-title">
              Send feedback
            </h2>
            <button type="button" className="feedback-close" onClick={close} aria-label="Close feedback">
              ×
            </button>
          </div>

          {sent ? (
            <div className="feedback-thanks" role="status">
              <p>Thanks — we read every message.</p>
              {email.trim() && <p className="muted">We&apos;ll reply to {email.trim()} if we need to.</p>}
              <button type="button" className="feedback-submit" onClick={close}>
                Close
              </button>
            </div>
          ) : (
            <form onSubmit={submit} noValidate>
              <label className="feedback-label" htmlFor={`${ids}-category`}>
                Category
              </label>
              <select
                id={`${ids}-category`}
                className="feedback-input"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                {CATEGORIES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>

              <label className="feedback-label" htmlFor={`${ids}-message`}>
                Your feedback <span aria-hidden="true">*</span>
              </label>
              <textarea
                ref={messageRef}
                id={`${ids}-message`}
                className="feedback-input feedback-message"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                maxLength={MAX_MESSAGE}
                rows={4}
                required
                placeholder="What worked, what didn't, what's missing?"
              />

              <label className="feedback-label" htmlFor={`${ids}-email`}>
                Email <span className="muted">(optional, for a reply)</span>
              </label>
              <input
                id={`${ids}-email`}
                className="feedback-input"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                maxLength={320}
                placeholder="you@company.com"
              />

              <p className="feedback-note muted">
                Sent with it: the pages you visited this session, time on this page, scroll and
                clicks, and any errors it showed — never what you typed or read.
              </p>

              {error && (
                <p className="feedback-error" role="alert">
                  {error}
                </p>
              )}

              <button type="submit" className="feedback-submit" disabled={!message.trim() || sending}>
                {sending ? "Sending…" : "Submit"}
              </button>
            </form>
          )}
        </div>
      )}
    </>
  );
}
