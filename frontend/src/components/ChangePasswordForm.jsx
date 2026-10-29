import { useState } from "react";
import { api } from "../lib/api";

/**
 * Rotate this login's password.
 *
 * `POST /auth/change-password` existed with nothing in the app calling it, so a
 * password that leaked could not be changed by the person it belongs to. A
 * login that signs in with Google or Microsoft has no password here; the
 * server says so in its 400, which this shows as it is.
 */
export default function ChangePasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setDone(false);
    // Checked here, since a typo in a password nobody can see would otherwise
    // become the password.
    if (next !== confirm) {
      setError("The new passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      setDone(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="change-password" aria-labelledby="change-password-heading">
      <h2 id="change-password-heading">Password</h2>
      <p>Changing it signs out every other device using the old one.</p>
      <form onSubmit={submit}>
        <label htmlFor="current-password">Current password</label>
        <input
          id="current-password"
          type="password"
          autoComplete="current-password"
          required
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
        <label htmlFor="new-password">New password</label>
        <input
          id="new-password"
          type="password"
          autoComplete="new-password"
          minLength={8}
          required
          value={next}
          onChange={(e) => setNext(e.target.value)}
        />
        <label htmlFor="confirm-password">Confirm new password</label>
        <input
          id="confirm-password"
          type="password"
          autoComplete="new-password"
          minLength={8}
          required
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
        {/* There from the start and empty, so "Password changed." is a change to
            a live region — which is announced — rather than one inserted
            already full, which often is not. */}
        <p role="status">{done ? "Password changed." : ""}</p>
        <button type="submit" disabled={busy}>
          Change password
        </button>
      </form>
    </section>
  );
}
