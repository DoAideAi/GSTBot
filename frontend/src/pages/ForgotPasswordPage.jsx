import { useState } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../hooks/usePageTitle";
import { api } from "../lib/api";

/**
 * Ask for a link to reset a forgotten password.
 *
 * There was no way back from a forgotten password at all. The server answers
 * the same whatever the address, so this shows its sentence and nothing more.
 */
export default function ForgotPasswordPage() {
  usePageTitle("Reset your password — DoAide GST");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState("");
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = await api.forgotPassword(email.trim());
      setSent(body?.detail || "If that email has an account, a reset link is on its way.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>Reset your password</h1>
        {sent ? (
          <p role="status">{sent}</p>
        ) : (
          <form onSubmit={submit}>
            <p className="muted">We will email you a link to choose a new one.</p>
            <label htmlFor="forgot-email">Email</label>
            <input
              id="forgot-email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            {error && (
              <p className="field-error" role="alert">
                {error}
              </p>
            )}
            <button type="submit" className="auth-submit" disabled={busy}>
              Email me a link
            </button>
          </form>
        )}
        <p>
          <Link to="/login">Back to sign in</Link>
        </p>
      </div>
    </div>
  );
}
