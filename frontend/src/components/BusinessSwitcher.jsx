import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "../hooks/useAuth";
import { api } from "../lib/api";

// The owner grants client access through an expiring invitation link.
export default function BusinessSwitcher() {
  const { user, switchBusiness } = useAuth();
  const [open, setOpen] = useState(false);
  // null until the menu has been opened once; the list is kept afterwards so
  // reopening is instant, and refetched only when something has changed it.
  const [businesses, setBusinesses] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const toggleRef = useRef(null);
  const menuRef = useRef(null);
  // Whether *this* opening of the menu has already asked. The list cannot
  // record that, because a failure deliberately leaves it null — see `load`
  // below — and null is also the condition to fetch on. Inferring the attempt
  // from the data meant a failure re-entered the effect the moment it landed
  // and asked again, as fast as the server could refuse, for as long as the
  // menu stayed open: measured at 149 requests a second against a 5ms reply.
  // Metered by identity, so the user spends their own bucket on it.
  //
  // Reset on close rather than kept for the session, so closing the menu and
  // reopening it is the retry — the one gesture someone makes when a panel
  // says it could not load.
  const attempted = useRef(false);

  const current = user?.business;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.myBusinesses();
      setBusinesses(data.items ?? []);
    } catch (err) {
      // The list failing is not the same as holding one business: saying
      // "no other registrations" on the strength of never having found out
      // is how someone concludes the link they made did not save.
      setBusinesses(null);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) {
      attempted.current = false;
      return;
    }
    if (attempted.current || businesses !== null) return;
    attempted.current = true;
    load();
  }, [open, businesses, load]);

  // Escape closes and returns focus to the control that opened it, matching the
  // nav drawer beside it — a menu that closes while focus stays on one of its
  // now-hidden buttons strands keyboard users.
  useEffect(() => {
    if (!open) return undefined;
    function onKeyDown(event) {
      if (event.key === "Escape") {
        setOpen(false);
        toggleRef.current?.focus();
      }
    }
    function onPointerDown(event) {
      if (
        !menuRef.current?.contains(event.target) &&
        !toggleRef.current?.contains(event.target)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("mousedown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("mousedown", onPointerDown);
    };
  }, [open]);

  async function handleSwitch(id) {
    if (id === current?.id) {
      setOpen(false);
      return;
    }
    setBusy(true);
    setError("");
    try {
      await switchBusiness(id);
      // Only closed on success. A failed switch leaves the menu open with the
      // reason in it, still showing which business is actually current — the
      // alternative is a closed menu and a header that never changed, which
      // reads as a click that did nothing.
      setOpen(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleUnlink(business) {
    setBusy(true);
    setError("");
    try {
      await api.unlinkBusiness(business.id);
      // Unlinking the business currently being acted for would leave every
      // request carrying a header the server now refuses, so step home first.
      // `switchBusiness` confirms against /auth/me, so the header and the
      // session agree again before anything else is fetched.
      if (business.id === current?.id) await switchBusiness(null);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!current) return null;

  return (
    <div className="business-switcher">
      <button
        type="button"
        ref={toggleRef}
        className="business-current"
        aria-expanded={open}
        aria-haspopup="true"
        aria-controls="business-menu"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="shell-business-name">
          {current.trade_name || current.legal_name}
        </span>
        {current.gstin && <span className="shell-gstin">{current.gstin}</span>}
        {/* Constant, because `aria-expanded` above is what announces open and
            closed. A label that changed with the state said it twice, and left
            the control with no stable name to refer to it by. */}
        <span className="visually-hidden">Switch business</span>
      </button>

      {open && (
        <div className="business-menu" id="business-menu" ref={menuRef}>
          <h2 className="business-menu-title">Your registrations</h2>

          {error && (
            <p className="business-menu-error" role="alert">
              {error}
            </p>
          )}

          {loading && <p className="muted small">Loading…</p>}

          {businesses?.length > 0 && (
            <ul className="business-list">
              {businesses.map((business) => (
                <li key={business.id}>
                  <button
                    type="button"
                    className={
                      business.id === current.id
                        ? "business-option is-current"
                        : "business-option"
                    }
                    disabled={busy}
                    aria-current={business.id === current.id}
                    onClick={() => handleSwitch(business.id)}
                  >
                    <span className="business-option-name">
                      {business.trade_name || business.legal_name}
                      {business.is_home && <span className="muted small"> · your own</span>}
                    </span>
                    {business.gstin && <span className="shell-gstin">{business.gstin}</span>}
                  </button>
                  {/* Never offered for the login's own tenant: there is no
                      membership behind it to revoke, and the server refuses it.
                      Offering a button whose only outcome is an error is worse
                      than not offering it. */}
                  {!business.is_home && (
                    <button
                      type="button"
                      className="btn btn-ghost business-unlink"
                      disabled={busy}
                      onClick={() => handleUnlink(business)}
                    >
                      Unlink
                      <span className="visually-hidden">
                        {" "}
                        {business.trade_name || business.legal_name}
                      </span>
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}

          <a className="btn btn-ghost business-link-open" href="/client-access">Manage client invitations</a>
          <p className="muted small">Ask each client’s owner to invite your email. Keep passwords private.</p>
        </div>
      )}
    </div>
  );
}
