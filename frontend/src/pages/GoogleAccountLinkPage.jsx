import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import BrandMark from "../components/BrandMark";
import { usePageTitle } from "../hooks/usePageTitle";
import { api } from "../lib/api";
import { takeReturnTo } from "../lib/returnTo";
import { track } from "../lib/track";

export default function GoogleAccountLinkPage() {
  usePageTitle("Connect Google sign-in");
  const [pending, setPending] = useState(null);
  const [loading, setLoading] = useState(true);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api.googleLinkStatus().then(
      (data) => { if (active) { setPending(data); setLoading(false); } },
      (err) => { if (active) { setError(err.message); setLoading(false); } },
    );
    return () => { active = false; };
  }, []);

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await api.linkGoogle(password, pending.csrf_token);
      track("login", { method: "google" });
      // Reload so AuthProvider starts from the newly confirmed account.
      window.location.replace(takeReturnTo());
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-container">
        <a className="auth-home" href="/" aria-label="DoAide GST home"><BrandMark size={40} /></a>
        <h1 className="auth-title">Connect Google sign-in</h1>
        <p className="auth-subtitle">One account. All your GST work.</p>
        <div className="auth-card">
          {loading && <p role="status">Checking your Google sign-in…</p>}
          {pending && (
            <>
              <p>You already have a DoAide GST account with this email. Confirm its password once to connect Google and keep your existing business data.</p>
              <form className="auth-form" onSubmit={submit}>
                <label htmlFor="link-email">Google account</label>
                <input id="link-email" type="email" name="username" autoComplete="username" value={pending.email} readOnly />
                <label htmlFor="link-password">DoAide GST password</label>
                <input id="link-password" type="password" name="password" autoComplete="current-password" required maxLength={128} value={password} onChange={(e) => setPassword(e.target.value)} aria-describedby="link-password-hint" disabled={busy} />
                <p id="link-password-hint" className="field-hint">Use your existing GST password, not your Google password. Next time, you can sign in directly with Google.</p>
                <button className="auth-submit" type="submit" disabled={busy}>{busy ? "Connecting…" : "Connect Google and sign in"}</button>
              </form>
              <p><Link to="/forgot-password">Forgot your GST password?</Link></p>
            </>
          )}
          {error && <p className="field-error" role="alert">{error}</p>}
          {!loading && <p><a href="/api/v1/auth/google">Start again with Google</a> · <Link to="/login">Back to sign in</Link></p>}
        </div>
      </div>
    </div>
  );
}
