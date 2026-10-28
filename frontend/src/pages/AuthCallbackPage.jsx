import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { setToken } from "../lib/api";
import { track } from "../lib/track";

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
    const fragment = new URLSearchParams(hash.replace(/^#/, ""));
    const token = fragment.get("token");
    const error = new URLSearchParams(search).get("error");

    if (error) {
      navigate(`/login?error=${encodeURIComponent(error)}`, { replace: true });
      return;
    }

    if (token) {
      setToken(token);
      // The backend marks the sign-in that created the account, which is the
      // only place a new OAuth account and a returning one can be told apart.
      const method = fragment.get("provider") || "oauth";
      track(fragment.get("new") === "1" ? "signup_complete" : "login", { method });
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
