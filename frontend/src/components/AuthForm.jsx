import { useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import ErrorBanner from "./ErrorBanner";
import SsoButtons from "./SsoButtons";
import { useAuth } from "../hooks/useAuth";
import { api } from "../lib/api";
import { gstinShapeError, normalizeGstin, registrationErrors } from "../lib/validate";
import { takeReturnTo } from "../lib/returnTo";
import { track } from "../lib/track";

const EMPTY = {
  email: "",
  password: "",
  gstin: "",
  legal_name: "",
  trade_name: "",
  full_name: "",
};

const PROVIDER_NAMES = { google: "Google", github: "GitHub", microsoft: "Microsoft" };

/**
 * What a failed single sign-on comes back to /login saying.
 *
 * The OAuth callbacks send every failure to `/login?error=<code>`, and
 * nothing read it: cancelling at Google, a provider that could not be
 * reached, an account refused for an unverified email, all landed on a blank
 * form, as though the button had done nothing.
 */
export function ssoErrorMessage(code) {
  if (!code) return "";
  const unavailable = PROVIDER_NAMES[code.replace(/_unavailable$/, "")];
  if (unavailable && code.endsWith("_unavailable")) {
    return `Sign-in with ${unavailable} is not available right now. Use another option below, or sign in with your email and password.`;
  }
  const provider = PROVIDER_NAMES[code.replace(/_auth_failed$/, "")];
  if (provider) {
    return (
      `Signing in with ${provider} did not complete — it was cancelled, or ${provider} ` +
      "could not be reached. Try again, or sign in with your email and password."
    );
  }
  if (code === "no_email") {
    return (
      "That account did not share an email address with us, so we cannot sign you in " +
      "with it. Use an account with a verified email, or sign in with your email and password."
    );
  }
  if (code === "account_deactivated") {
    return (
      "That account could not be signed in this way. If you already have a DoAide GST " +
      "account with this email, sign in with your email and password; if it has been " +
      "deactivated, contact support."
    );
  }
  if (code === "account_link_required") {
    return "This Google account is not connected to your existing GST account. Sign in using the password or provider you originally used.";
  }
  return "Single sign-on did not complete. Try again, or sign in with your email and password.";
}

export default function AuthForm() {
  const { search } = useLocation();
  const [ssoError] = useState(() => ssoErrorMessage(new URLSearchParams(search).get("error")));
  // Someone coming back from a failed SSO attempt was signing in, not signing up.
  const [mode, setMode] = useState(() => (
    !ssoError && new URLSearchParams(search).get("mode") === "register" ? "register" : "login"
  ));
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState(ssoError);
  const [busy, setBusy] = useState(false);
  const [fieldErrors, setFieldErrors] = useState({});
  const [gstinCheck, setGstinCheck] = useState(null);
  const [showGstin, setShowGstin] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const asked = useRef("");

  const { login, register } = useAuth();
  const navigate = useNavigate();
  const registering = mode === "register";

  function switchTo(next) {
    if (next === "register") track("signup_click");
    setMode(next);
    setError("");
    setFieldErrors({});
    setGstinCheck(null);
    setShowGstin(false);
    asked.current = "";
  }

  function update(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function checkGstin(value) {
    const cleaned = normalizeGstin(value);
    asked.current = cleaned;
    if (cleaned.length !== 15) {
      setGstinCheck(null);
      return;
    }
    const shape = gstinShapeError(cleaned);
    if (shape) {
      setGstinCheck({ valid: false, error: shape });
      return;
    }
    try {
      const verdict = await api.validateGstin(cleaned);
      if (asked.current !== cleaned) return;
      setGstinCheck(verdict);
    } catch {
      if (asked.current !== cleaned) return;
      setGstinCheck(null);
    }
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setFieldErrors({});

    if (!registering) {
      const problems = {};
      if (!form.email.trim()) problems.email = "Enter your email.";
      if (!form.password) problems.password = "Enter your password.";
      if (Object.keys(problems).length > 0) {
        setFieldErrors(problems);
        return;
      }
    }

    if (registering) {
      const problems = registrationErrors(form);
      if (!problems.gstin && form.gstin.trim() && gstinCheck && !gstinCheck.valid) {
        problems.gstin = gstinCheck.error || "That GSTIN is not valid.";
      }
      if (Object.keys(problems).length > 0) {
        setFieldErrors(problems);
        return;
      }
    }

    setBusy(true);
    try {
      if (registering) {
        await register({
          email: form.email,
          password: form.password,
          gstin: form.gstin.trim() ? form.gstin.replace(/\s/g, "").toUpperCase() : null,
          legal_name: form.legal_name || null,
          trade_name: form.trade_name || null,
          full_name: form.full_name || null,
        });
      } else {
        await login(form.email, form.password);
      }
      navigate(takeReturnTo());
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-card">
      <div className="auth-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          className={`auth-tab ${!registering ? "is-active" : ""}`}
          aria-selected={!registering}
          onClick={() => switchTo("login")}
        >
          Sign in
        </button>
        <button
          type="button"
          role="tab"
          className={`auth-tab ${registering ? "is-active" : ""}`}
          aria-selected={registering}
          onClick={() => switchTo("register")}
        >
          Create account
        </button>
      </div>

      <div className="auth-card-heading">
        <h1>{registering ? "Create your account" : "Welcome back"}</h1>
        <p>{registering ? "A simpler way to stay on top of GST." : "Sign in to your DoAide GST workspace."}</p>
      </div>
      <SsoButtons />
      <ErrorBanner message={error} onDismiss={() => setError("")} />

      <form onSubmit={handleSubmit} className="auth-form" noValidate>
        <label htmlFor="email">Email</label>
        <input
          id="email"
          name="email"
          type="email"
          required
          autoComplete="email"
          placeholder="you@company.com"
          value={form.email}
          aria-invalid={fieldErrors.email ? true : undefined}
          aria-describedby={fieldErrors.email ? "email-error" : undefined}
          onChange={(e) => update("email", e.target.value)}
        />
        {fieldErrors.email && (
          <p className="field-error" id="email-error" role="alert">
            {fieldErrors.email}
          </p>
        )}

        <label htmlFor="password">Password</label>
        <div className="auth-password-field">
          <input
            id="password"
            name="password"
            type={showPassword ? "text" : "password"}
            required
            minLength={registering ? 8 : undefined}
            autoComplete={registering ? "new-password" : "current-password"}
            value={form.password}
            aria-invalid={fieldErrors.password ? true : undefined}
            aria-describedby={fieldErrors.password ? "password-error" : undefined}
            onChange={(e) => update("password", e.target.value)}
          />
          <button
            type="button"
            className="auth-password-toggle"
            aria-label={showPassword ? "Hide password" : "Show password"}
            aria-pressed={showPassword}
            onClick={() => setShowPassword((value) => !value)}
          >
            {showPassword ? "Hide" : "Show"}
          </button>
        </div>
        {fieldErrors.password ? (
          <p className="field-error" id="password-error" role="alert">
            {fieldErrors.password}
          </p>
        ) : (
          registering && <p className="field-hint">At least 8 characters.</p>
        )}

        {registering && (
          <>
            <label htmlFor="full_name">Your name (optional)</label>
            <input
              id="full_name"
              name="full_name"
              autoComplete="name"
              value={form.full_name}
              onChange={(e) => update("full_name", e.target.value)}
            />

            {!showGstin ? (
              <button
                type="button"
                className="auth-gstin-toggle"
                onClick={() => setShowGstin(true)}
              >
                Have a GSTIN? Add it now
              </button>
            ) : (
              <>
                <label htmlFor="gstin">GSTIN (optional)</label>
                <input
                  id="gstin"
                  name="gstin"
                  autoComplete="off"
                  spellCheck="false"
                  placeholder="27AAPFU0939F1ZV"
                  value={form.gstin}
                  aria-invalid={fieldErrors.gstin ? true : undefined}
                  aria-describedby={fieldErrors.gstin ? "gstin-error" : undefined}
                  onChange={(e) => {
                    update("gstin", e.target.value);
                    checkGstin(e.target.value);
                  }}
                />
                {fieldErrors.gstin ? (
                  <p className="field-error" id="gstin-error" role="alert">
                    {fieldErrors.gstin}
                  </p>
                ) : (
                  gstinCheck && (
                    <p className={gstinCheck.valid ? "field-hint is-good" : "field-hint is-bad"}>
                      {gstinCheck.valid
                        ? `Valid — ${gstinCheck.state_name} (PAN ${gstinCheck.pan})`
                        : gstinCheck.error}
                    </p>
                  )
                )}

                <label htmlFor="legal_name">Legal name (optional)</label>
                <input
                  id="legal_name"
                  name="legal_name"
                  value={form.legal_name}
                  aria-invalid={fieldErrors.legal_name ? true : undefined}
                  aria-describedby={fieldErrors.legal_name ? "legal_name-error" : undefined}
                  onChange={(e) => update("legal_name", e.target.value)}
                />
                {fieldErrors.legal_name && (
                  <p className="field-error" id="legal_name-error" role="alert">
                    {fieldErrors.legal_name}
                  </p>
                )}
                <p className="field-hint">Skip this to explore first — you can register your GSTIN anytime.</p>
              </>
            )}
          </>
        )}

        <button type="submit" className="auth-submit" disabled={busy}>
          {busy ? "Please wait…" : registering ? "Create account" : "Sign in"}
        </button>
        {/* There was no way back from a forgotten password. */}
        {!registering && (
          <p className="auth-forgot">
            <Link to="/forgot-password">Forgot your password?</Link>
          </p>
        )}
      </form>
    </div>
  );
}
