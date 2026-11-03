import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import BrandMark from "../components/BrandMark";
import ErrorBanner from "../components/ErrorBanner";
import { useAuth } from "../hooks/useAuth";
import { usePageTitle } from "../hooks/usePageTitle";
import { api } from "../lib/api";
import { rememberReturnTo } from "../lib/returnTo";
import "./practice.css";

export default function JoinClientPage() {
  usePageTitle("Accept client invitation");
  const { user, switchBusiness, logout } = useAuth();
  const { hash } = useLocation();
  const navigate = useNavigate();
  const token = hash.slice(1);
  const [invite, setInvite] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    setInvite(null);
    setError("");
    if (!/^[A-Za-z0-9_-]{40,128}$/.test(token)) {
      setError(
        "Open the complete invitation link shared by the business owner.",
      );
      return;
    }
    api
      .inspectInvitation(token)
      .then((d) => {
        if (live) setInvite(d);
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [token]);
  const returnHere = () => rememberReturnTo(`/join#${token}`);
  const accept = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api.acceptInvitation(token);
      await switchBusiness(result.business_id);
      navigate("/", { replace: true });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="practice-page join-client">
      <Link to="/" aria-label="DoAide GST home">
        <BrandMark />
      </Link>
      <section className="panel">
        <p className="eyebrow">Client invitation</p>
        <h1>Work together in DoAide GST</h1>
        <ErrorBanner message={error} />
        {invite && (
          <>
            <h2>{invite.business_name}</h2>
            <p>
              You have been invited as an <strong>{invite.role}</strong> using{" "}
              <strong>{invite.email}</strong>.
            </p>
            <p>
              No passwords need to be shared. The owner can revoke access at any
              time.
            </p>
            {!user ? (
              <div className="practice-actions">
                <Link
                  className="btn btn-primary"
                  to="/login"
                  onClick={returnHere}
                >
                  Sign in to accept
                </Link>
                <Link to="/login?mode=register" onClick={returnHere}>
                  Create an account
                </Link>
                <p className="muted">
                  Use the invited email. A GSTIN is optional when creating your
                  own account.
                </p>
              </div>
            ) : user.email.toLowerCase() !== invite.email.toLowerCase() ? (
              <>
                <p>
                  Signed in as {user.email}. Switch to the invited email to
                  continue.
                </p>
                <button
                  className="btn btn-primary"
                  onClick={() => {
                    returnHere();
                    logout();
                    navigate("/login");
                  }}
                >
                  Switch account
                </button>
              </>
            ) : (
              <button
                className="btn btn-primary"
                disabled={busy}
                onClick={accept}
              >
                {busy ? "Accepting…" : `Accept ${invite.role} access`}
              </button>
            )}
          </>
        )}
      </section>
    </main>
  );
}
