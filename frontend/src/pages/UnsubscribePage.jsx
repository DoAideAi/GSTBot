import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { usePageTitle } from "../hooks/usePageTitle";
import { api } from "../lib/api";

/**
 * Where a filing reminder's "Unsubscribe" link lands.
 *
 * The link opened the API itself, which answered a person with a raw JSON
 * object. This page asks for a click before it does anything: mail scanners
 * follow every link in a message, and a page that unsubscribed on arrival
 * would unsubscribe people who never opened the email.
 */
export default function UnsubscribePage() {
  usePageTitle("Unsubscribe — DoAide GST");
  const { search } = useLocation();
  const params = new URLSearchParams(search);
  const email = params.get("email") || "";
  const token = params.get("token") || "";
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState("");
  const [error, setError] = useState(
    email && token ? "" : "This page needs the unsubscribe link from a reminder email.",
  );

  async function unsubscribe() {
    setBusy(true);
    setError("");
    try {
      const result = await api.unsubscribe(email, token);
      if (result.unsubscribed) setDone(result.message || "You've been unsubscribed.");
      else setError(result.error || "That link could not be used.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>Filing reminders</h1>
        {done ? (
          <p role="status">{done}</p>
        ) : (
          email && token && (
            <>
              <p>
                Stop the GSTR-1 and GSTR-3B deadline reminders sent to <strong>{email}</strong>?
              </p>
              <button type="button" className="auth-submit" disabled={busy} onClick={unsubscribe}>
                Unsubscribe
              </button>
            </>
          )
        )}
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
        <p>
          <Link to="/">DoAide GST</Link>
        </p>
      </div>
    </div>
  );
}
