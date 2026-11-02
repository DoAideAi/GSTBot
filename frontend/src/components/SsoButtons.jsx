import { useEffect, useState } from "react";
import { api } from "../lib/api";

export default function SsoButtons() {
  const [providers, setProviders] = useState([]);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setFailed(false);
    api.authProviders().then((data) => {
      if (active) setProviders(Array.isArray(data.providers) ? data.providers : []);
    }).catch(() => {
      if (active) setFailed(true);
    });
    return () => { active = false; };
  }, [attempt]);

  if (failed) return (
    <p className="auth-sso-notice" role="status">
      Other sign-in options could not be loaded. You can use your email below.{' '}
      <button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry</button>
    </p>
  );
  if (!providers.some((name) => ["google", "github", "microsoft"].includes(name))) return null;

  return (
    <>
      <div className="auth-sso-buttons">
        {providers.includes("google") && (
          <a href="/api/v1/auth/google" className="auth-sso-btn auth-sso-google">
            <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
              <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.7 2.4 30.2 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.2C12.4 13.5 17.7 9.5 24 9.5z" />
              <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.7 6c4.5-4.2 6.9-10.4 6.9-17.7z" />
              <path fill="#FBBC05" d="M10.5 28.6a14.5 14.5 0 0 1 0-9.2l-7.9-6.2a24 24 0 0 0 0 21.6l7.9-6.2z" />
              <path fill="#34A853" d="M24 48c6.2 0 11.4-2 15.2-5.6l-7.7-6c-2.1 1.4-4.8 2.3-7.5 2.3-6.3 0-11.6-4-13.5-9.6l-7.9 6.2C6.5 42.6 14.6 48 24 48z" />
            </svg>
            Continue with Google
          </a>
        )}
        {providers.includes("github") && (
          <a href="/api/v1/auth/github" className="auth-sso-btn auth-sso-github">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
            </svg>
            Continue with GitHub
          </a>
        )}
        {providers.includes("microsoft") && (
          <a href="/api/v1/auth/microsoft" className="auth-sso-btn auth-sso-microsoft">
            <svg width="18" height="18" viewBox="0 0 23 23" aria-hidden="true">
              <rect fill="#f25022" x="1" y="1" width="10" height="10" />
              <rect fill="#00a4ef" x="1" y="12" width="10" height="10" />
              <rect fill="#7fba00" x="12" y="1" width="10" height="10" />
              <rect fill="#ffb900" x="12" y="12" width="10" height="10" />
            </svg>
            Continue with Microsoft
          </a>
        )}
      </div>
      <div className="auth-divider"><span>or use your email</span></div>
    </>
  );
}
