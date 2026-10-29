import { useState } from "react";
import { api } from "../lib/api";
import { track } from "../lib/track";

export default function EmailCapture({
  source = "landing",
  heading = "Get GST filing reminders",
  subtext = "Never miss a deadline — free email reminders before each due date.",
  successMessage = "You'll receive reminders before each filing deadline.",
  buttonLabel = "Subscribe",
  compact = false,
}) {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState("idle");
  const [message, setMessage] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    const trimmed = email.trim();
    if (!trimmed) return;
    setStatus("sending");
    setMessage("");
    try {
      const res = await api.subscribe(trimmed, source);
      setStatus("done");
      setMessage(res.message || successMessage);
      track("email_subscribe", { source });
    } catch (err) {
      setStatus("idle");
      setMessage(err.message || "Something went wrong. Please try again.");
    }
  };

  if (status === "done") {
    return (
      <div className={`email-capture${compact ? " email-capture--compact" : ""}`} role="status">
        <div className="email-capture-success">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="var(--good)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
            <polyline points="22 4 12 14.01 9 11.01" />
          </svg>
          <p>{message}</p>
        </div>
      </div>
    );
  }

  return (
    <div className={`email-capture${compact ? " email-capture--compact" : ""}`}>
      {!compact && heading && <h3 className="email-capture-heading">{heading}</h3>}
      {!compact && subtext && <p className="email-capture-subtext">{subtext}</p>}
      <form onSubmit={handleSubmit} className="email-capture-form">
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="your@email.com"
          className="email-capture-input"
          required
          disabled={status === "sending"}
          // Named on every form, not only the compact one: the full form's
          // heading is an <h3> nothing ties to the field, and a placeholder is
          // not a label, so a screen reader announced an unnamed edit box.
          aria-label="Email address"
        />
        <button type="submit" className="btn btn-primary email-capture-btn" disabled={status === "sending"}>
          {status === "sending" ? "Subscribing…" : buttonLabel}
        </button>
      </form>
      {message && <p className="email-capture-error">{message}</p>}
    </div>
  );
}
