import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import ErrorBanner from "./ErrorBanner";
import { useAuth } from "../hooks/useAuth";
import { api } from "../lib/api";
import { gstinShapeError, normalizeGstin, registrationErrors } from "../lib/validate";
import { track } from "../lib/track";

const EMPTY = {
  email: "",
  password: "",
  gstin: "",
  legal_name: "",
  trade_name: "",
  full_name: "",
};

export default function AuthForm() {
  const [mode, setMode] = useState("register");
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [fieldErrors, setFieldErrors] = useState({});
  const [gstinCheck, setGstinCheck] = useState(null);
  const [showGstin, setShowGstin] = useState(false);
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
      navigate("/");
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

      <ErrorBanner message={error} onDismiss={() => setError("")} />

      <form onSubmit={handleSubmit} className="auth-form" noValidate>
        <label htmlFor="email">Email</label>
        <input
          id="email"
          name="email"
          type="email"
          required
          autoComplete="email"
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
        <input
          id="password"
          name="password"
          type="password"
          required
          minLength={registering ? 8 : undefined}
          autoComplete={registering ? "new-password" : "current-password"}
          value={form.password}
          aria-invalid={fieldErrors.password ? true : undefined}
          aria-describedby={fieldErrors.password ? "password-error" : undefined}
          onChange={(e) => update("password", e.target.value)}
        />
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
      </form>

      <div className="auth-divider">
        <span>or continue with</span>
      </div>

      <div className="auth-sso-buttons">
        <a href="/api/v1/auth/google" className="auth-sso-btn auth-sso-google">
          <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
            <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.7 2.4 30.2 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.2C12.4 13.5 17.7 9.5 24 9.5z" />
            <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.7 6c4.5-4.2 6.9-10.4 6.9-17.7z" />
            <path fill="#FBBC05" d="M10.5 28.6a14.5 14.5 0 0 1 0-9.2l-7.9-6.2a24 24 0 0 0 0 21.6l7.9-6.2z" />
            <path fill="#34A853" d="M24 48c6.2 0 11.4-2 15.2-5.6l-7.7-6c-2.1 1.4-4.8 2.3-7.5 2.3-6.3 0-11.6-4-13.5-9.6l-7.9 6.2C6.5 42.6 14.6 48 24 48z" />
          </svg>
          Google
        </a>
        <a href="/api/v1/auth/github" className="auth-sso-btn auth-sso-github">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
          </svg>
          GitHub
        </a>
        <a href="/api/v1/auth/microsoft" className="auth-sso-btn auth-sso-microsoft">
          <svg width="18" height="18" viewBox="0 0 23 23" aria-hidden="true">
            <rect fill="#f25022" x="1" y="1" width="10" height="10" />
            <rect fill="#00a4ef" x="1" y="12" width="10" height="10" />
            <rect fill="#7fba00" x="12" y="1" width="10" height="10" />
            <rect fill="#ffb900" x="12" y="12" width="10" height="10" />
          </svg>
          Microsoft
        </a>
      </div>
    </div>
  );
}
