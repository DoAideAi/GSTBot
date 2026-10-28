import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { setToken } from "../lib/api";

/**
 * Where the OAuth providers' callback lands the browser.
 *
 * The backend sends the token in the URL *fragment* —
 * `/auth/callback#token=…`, see `_complete_oauth_login` in
 * `backend/app/routers/oauth.py` — so it never reaches a server log or a
 * Referer header. This page read it from the query string instead, found
 * nothing, and sent every Google, GitHub and Microsoft sign-in back to /login.
 */
export default function AuthCallbackPage() {
  const { hash, search } = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    const token = new URLSearchParams(hash.replace(/^#/, "")).get("token");
    const error = new URLSearchParams(search).get("error");

    if (error) {
      navigate(`/login?error=${encodeURIComponent(error)}`, { replace: true });
      return;
    }

    if (token) {
      setToken(token);
      // A full load so the auth provider starts from the stored token, and
      // `replace` so the URL carrying it does not stay in the back history.
      window.location.replace("/");
    } else {
      navigate("/login", { replace: true });
    }
  }, [hash, search, navigate]);

  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "100vh" }}>
      <p>Signing you in…</p>
    </div>
  );
}
