import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { usePageTitle } from "../hooks/usePageTitle";
import { api } from "../lib/api";
import { takeReturnTo } from "../lib/returnTo";

/**
 * Choose a new password with the emailed link.
 *
 * The token is in the fragment — `/reset-password#token=…` — for the same
 * reason the OAuth callback's is: it never reaches a server log or a Referer.
 */
export default function ResetPasswordPage() {
  usePageTitle("Choose a new password — DoAide GST");
  const { hash } = useLocation();
  const token = new URLSearchParams(hash.replace(/^#/, "")).get("token") || "";
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(
    token ? "" : "This page needs the link from the reset email. Ask for a new one.",
  );
  const [refused, setRefused] = useState(!token);

  async function submit(e) {
    e.preventDefault();
    setError("");
    if (next !== confirm) {
      setError("The new passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api.resetPassword(token, next);
      // A full load, so the auth provider starts from the new session, and
      // `replace` so the link does not stay in the back history.
      window.location.replace(takeReturnTo());
    } catch (err) {
      setError(err.message);
      setRefused(err.status === 400);
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>Choose a new password</h1>
        {token && (
          <form onSubmit={submit}>
            <label htmlFor="reset-new">New password</label>
            <input
              id="reset-new"
              type="password"
              autoComplete="new-password"
              minLength={8}
              required
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
            <label htmlFor="reset-confirm">Confirm new password</label>
            <input
              id="reset-confirm"
              type="password"
              autoComplete="new-password"
              minLength={8}
              required
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
            <button type="submit" className="auth-submit" disabled={busy}>
              Set new password
            </button>
          </form>
        )}
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
        {refused && (
          <p>
            <Link to="/forgot-password">Ask for a new link</Link>
          </p>
        )}
      </div>
    </div>
  );
}
