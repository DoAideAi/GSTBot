import { useCallback, useEffect, useState } from "react";
import ErrorBanner from "../components/ErrorBanner";
import { useAuth } from "../hooks/useAuth";
import { usePageTitle } from "../hooks/usePageTitle";
import { api } from "../lib/api";
import "./practice.css";

export default function ClientAccessPage() {
  usePageTitle("Client access");
  const { user } = useAuth();
  const owner = user?.active_role === "owner";
  const [data, setData] = useState(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("accountant");
  const [link, setLink] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const load = useCallback(async () => {
    const [invites, members] = await Promise.all([
      api.invitations(),
      api.clientMembers(),
    ]);
    setData({ invites: invites.items, members: members.items });
  }, []);
  useEffect(() => {
    if (owner) load().catch((e) => setError(e.message));
  }, [owner, load]);
  const perform = async (fn) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const create = (e) => {
    e.preventDefault();
    perform(async () => {
      const invite = await api.createInvitation({ email, role });
      setLink(`${window.location.origin}/join#${invite.token}`);
      setEmail("");
      setMessage(
        "Invitation created. Copy the link and share it privately with the invited person. No email has been sent.",
      );
    });
  };
  return (
    <div className="practice-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Your team</p>
          <h1>Client access</h1>
          <p className="muted">
            Invite an accountant or reviewer to{" "}
            {user?.business?.trade_name ||
              user?.business?.legal_name ||
              "this business"}
            .
          </p>
        </div>
      </div>
      <ErrorBanner message={error} onDismiss={() => setError("")} />
      {!owner ? (
        <section className="panel">
          <h2>Ask the business owner</h2>
          <p>
            Only an owner can invite people or change their access. Each client
            can invite your own account as an accountant; passwords stay
            private.
          </p>
        </section>
      ) : (
        <>
          <form className="panel" onSubmit={create}>
            <h2>Invite someone</h2>
            <div className="practice-grid">
              <label>
                Email address
                <input
                  type="email"
                  required
                  maxLength={255}
                  value={email}
                  disabled={busy}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </label>
              <label>
                Role
                <select
                  value={role}
                  disabled={busy}
                  onChange={(e) => setRole(e.target.value)}
                >
                  <option value="accountant">
                    Accountant — import, correct and review
                  </option>
                  <option value="viewer">Viewer — read and download</option>
                </select>
              </label>
            </div>
            <p>
              Links expire after seven days and can be accepted once, while
              signed in with the invited email. Invitation access does not start
              a pilot or add pilot-covered registrations.
            </p>
            <button className="btn btn-primary" disabled={busy}>
              Create invitation link
            </button>
            {message && <p role="status">{message}</p>}
            {link && (
              <div className="practice-note">
                <label>
                  Invitation link
                  <input
                    readOnly
                    value={link}
                    onFocus={(e) => e.target.select()}
                  />
                </label>
                <div className="practice-actions">
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={async () => {
                      try {
                        await navigator.clipboard.writeText(link);
                        setMessage("Invitation link copied.");
                      } catch {
                        setMessage(
                          "Select and copy the invitation link above.",
                        );
                      }
                    }}
                  >
                    Copy link
                  </button>
                </div>
              </div>
            )}
          </form>
          <section className="panel">
            <h2>People with access</h2>
            <p className="muted">
              Your business’s original owner account is retained. Revoking
              access takes effect on the next request.
            </p>
            {!data ? (
              <p>Loading access…</p>
            ) : !data.members.length ? (
              <p>No linked accounts yet.</p>
            ) : (
              data.members.map((m) => (
                <div className="practice-row" key={m.id}>
                  <strong>{m.email}</strong>
                  <div className="practice-actions">
                    <label>
                      Role for {m.email}
                      <select
                        value={m.role}
                        disabled={busy || m.role === "owner"}
                        onChange={(e) =>
                          perform(() =>
                            api.changeMemberRole(m.id, e.target.value),
                          )
                        }
                      >
                        {m.role === "owner" && (
                          <option value="owner">Owner</option>
                        )}
                        <option value="accountant">Accountant</option>
                        <option value="viewer">Viewer</option>
                      </select>
                    </label>
                    {m.role !== "owner" && (
                      <button
                        className="btn btn-ghost"
                        disabled={busy}
                        onClick={() => {
                          if (
                            window.confirm(
                              `Revoke ${m.email}'s access to this business?`,
                            )
                          )
                            perform(() => api.revokeClientMember(m.id));
                        }}
                      >
                        Revoke access
                      </button>
                    )}
                  </div>
                </div>
              ))
            )}
          </section>
          <section className="panel">
            <h2>Invitations</h2>
            {data && !data.invites.length && <p>No invitations created yet.</p>}
            {data?.invites.map((i) => (
              <div className="practice-row" key={i.id}>
                <strong>{i.email}</strong> · {i.role}
                <small>
                  {i.accepted_at
                    ? "Accepted"
                    : i.revoked_at
                      ? "Revoked"
                      : new Date(i.expires_at) <= new Date()
                        ? "Expired"
                        : `Expires ${new Date(i.expires_at).toLocaleDateString()}`}
                </small>
                {!i.accepted_at &&
                  !i.revoked_at &&
                  new Date(i.expires_at) > new Date() && (
                    <button
                      className="btn btn-ghost"
                      disabled={busy}
                      onClick={() =>
                        perform(async () => {
                          await api.revokeInvitation(i.id);
                          setLink("");
                        })
                      }
                    >
                      Revoke invitation
                    </button>
                  )}
              </div>
            ))}
          </section>
        </>
      )}
    </div>
  );
}
