import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { track } from "../lib/track";
import {
  api,
  getActiveBusinessId,
  getToken,
  onUnauthorized,
  setActiveBusinessId,
  setToken,
  ACTIVE_BUSINESS_KEY,
  TOKEN_KEY,
} from "../lib/api";

// Exported for tests, which mount one page at a time and need to say what role
// it is being viewed with. The alternative is a real `AuthProvider` around
// every page test, which would put a `/auth/me` fetch in front of the request
// each test is actually about — so the stub is the honest seam, and
// `src/test/auth.jsx` is the only thing that uses it.
export const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);

  // Which /auth/me answer may set the session: the one asked last. Answers
  // were applied as they landed, and more than one can be in flight — boot,
  // a business switch, and every sign-in or sign-out another tab makes — so
  // the one asked first could be the one that stuck: a tab naming a login
  // whose token it no longer held, or a sign-out made elsewhere undone by an
  // answer already on its way. Ending the session takes a ticket too, which
  // is what voids anything still in flight from before it.
  const latest = useRef(0);
  const confirm = useCallback(async () => {
    const ticket = ++latest.current;
    const me = await api.me();
    if (ticket === latest.current) setUser(me);
    return me;
  }, []);
  const endSession = useCallback(() => {
    latest.current += 1;
    setUser(null);
  }, []);
  const [loading, setLoading] = useState(true);

  // The token expires after 24 hours and there is no refresh flow, so every
  // user meets this: a request goes out mid-session and comes back 401.
  //
  // The client drops the dead token; without this the session in React outlived
  // it. `Protected` kept rendering because `user` was still set, every request
  // after that went out unauthenticated and failed the same way, and `/login`
  // bounced straight back to `/` — which is gated on `user`, not on the token.
  // The one screen that could fix it was the one screen unreachable. Clearing
  // the user here is what turns an expired token into a redirect to sign in.
  useEffect(() => onUnauthorized(endSession), [endSession]);

  // The token is shared by every tab and `user` is not. Signing out in one tab
  // left the others showing the books, their next request sent with no token
  // and its 401 — carrying no credential — not read as the session ending.
  // Signing in as another login was worse: this tab went on naming the old one
  // while every request it made acted on the new one's books. So a change made
  // elsewhere is followed here: no token ends the session, a different one is
  // asked who it belongs to. `key` is null when another tab clears storage.
  //
  // The business being acted for is shared the same way, and was not
  // followed: switching to client B in one tab left the others naming client A
  // in their header while every request they sent carried B's id — an invoice
  // uploaded "to A" landed in B's books. A switch elsewhere is asked about the
  // same way, so the screen names the business its requests act for (and the
  // pages, keyed on it, remount and refetch).
  useEffect(() => {
    const onStorage = (e) => {
      if (e.key !== TOKEN_KEY && e.key !== ACTIVE_BUSINESS_KEY && e.key !== null) return;
      if (!getToken()) {
        endSession();
        return;
      }
      // A refused token ends the session through `onUnauthorized` above.
      confirm().catch(() => {});
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [confirm, endSession]);

  // A stored token proves nothing on its own — it may be expired or belong to
  // a deleted user — so the session is confirmed against /auth/me on boot.
  //
  // The stored *business* proves nothing either, and it is the one that outlives
  // its own validity: `setActiveBusinessId` survives in localStorage across
  // sessions, while the membership behind it can be revoked, or the business
  // deactivated, at any time from the other side. `/auth/me` resolves through
  // `get_current_business`, so a selection that is no longer granted answers 403
  // — and treating that like any other failed session check signs the user out
  // of an account that is perfectly fine, on a browser that then does it again
  // on every reload, because the selection causing it is never cleared. Drop the
  // selection and ask once more as the login's own tenant, which is the tenant
  // they would have been switched back to anyway.
  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        await confirm();
      } catch (err) {
        if (err?.status === 403 && getActiveBusinessId()) {
          setActiveBusinessId(null);
          try {
            await confirm();
            return;
          } catch {
            // Fall through: the session itself is what is wrong, not the
            // business it was pointed at.
          }
        }
        setToken(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [confirm]);

  // Counted after the server has accepted them, so the funnel's sign-ups are
  // accounts that exist rather than forms that were submitted.
  const login = useCallback(async (email, password) => {
    await api.login(email, password);
    track("login", { method: "password" });
    await confirm();
  }, [confirm]);

  const register = useCallback(async (payload) => {
    await api.register(payload);
    track("signup_complete", { method: "password" });
    await confirm();
  }, [confirm]);

  const logout = useCallback(() => {
    api.logout();
    endSession();
  }, [endSession]);

  /**
   * Act for another of the businesses this login holds.
   *
   * The switch is only real once the server has agreed to it. `X-Business-Id`
   * is sent on every subsequent request, so writing it before confirming would
   * point the whole app at a business the backend may refuse — and the refusal
   * arrives per page, as each one fails on its own, rather than here where
   * there is something to say about it. So: select, ask `/auth/me` who that
   * makes us, and put the previous selection back if the answer is no.
   *
   * `user.business.id` is what the rest of the app keys off afterwards, because
   * it is the tenant the server says the request acted for, rather than the
   * tenant this browser last asked for.
   */
  const switchBusiness = useCallback(async (businessId) => {
    const previous = getActiveBusinessId();
    setActiveBusinessId(businessId);
    try {
      await confirm();
    } catch (err) {
      setActiveBusinessId(previous);
      throw err;
    }
  }, [confirm]);

  // May this session change the books it is currently looking at?
  //
  // `active_role`, not `role`. The two differ exactly when it matters: `role`
  // is the role on the login's own business, while a session switched to a
  // linked business is enforced against that membership's role. An owner
  // linked into a client as a viewer has `role: "owner"` and
  // `active_role: "viewer"`, and gating on the former would show a full set of
  // buttons for the one business where every one of them is refused.
  //
  // Derived from the server's answer rather than tracked separately, so it
  // changes with the business the moment `/auth/me` says it has — see
  // `switchBusiness`, which sets `user` from that response.
  //
  // This hides controls; it does not enforce anything. `require_writer` on the
  // route is the enforcement, and it stays the only thing standing between a
  // viewer and a write — a client can always call the API directly. What this
  // buys is that a viewer is not invited to try.
  const canWrite = user ? user.active_role !== "viewer" : false;

  return (
    <AuthContext.Provider
      value={{ user, loading, canWrite, login, register, logout, switchBusiness }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
