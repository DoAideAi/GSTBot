import { useEffect, useState } from "react";
import DoAideFooter from "../components/DoAideFooter";
import SeoHead from "../components/SeoHead";
import ToolsNav from "../components/ToolsNav";
import { useAuth } from "../hooks/useAuth";
import { usePageTitle } from "../hooks/usePageTitle";
import { api } from "../lib/api";
import { copyToClipboard, whatsappUrl } from "../lib/share";
import { track } from "../lib/track";

const SITE_URL = "https://gst.doaide.com";

function LeaderboardTable({ leaders }) {
  if (!leaders.length) {
    return (
      <p style={{ color: "var(--muted)", textAlign: "center", padding: "2rem 0" }}>
        Be the first CA to refer clients and top the leaderboard!
      </p>
    );
  }
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Name</th>
            <th>Referrals</th>
          </tr>
        </thead>
        <tbody>
          {leaders.map((l, i) => (
            <tr key={i}>
              <td>{i === 0 ? "\u{1F947}" : i === 1 ? "\u{1F948}" : i === 2 ? "\u{1F949}" : i + 1}</td>
              <td>{l.name}</td>
              <td><strong>{l.referral_count}</strong></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MyReferralPanel() {
  const [code, setCode] = useState(null);
  const [stats, setStats] = useState(null);
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [codeData, statsData] = await Promise.all([
          api.myReferralCode(),
          api.myReferralStats(),
        ]);
        if (!cancelled) {
          setCode(codeData.referral_code);
          setStats(statsData);
        }
      } catch {
        // Silently degrade — the panel just won't show data.
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (loading) return <p style={{ color: "var(--muted)" }}>Loading your referral info...</p>;

  const referralUrl = `${SITE_URL}?ref=${code}`;

  const handleCopy = async () => {
    const ok = await copyToClipboard(referralUrl);
    if (ok) {
      track("referral_copy_link");
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const shareText = `I use DoAide GSTIndia for free GST calculations, GSTIN verification & filing prep. Try it:`;

  return (
    <div className="calc-card">
      <h3 style={{ margin: "0 0 0.5rem" }}>Your Referral Link</h3>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <code style={{
          flex: 1,
          padding: "0.5rem 0.75rem",
          background: "var(--surface)",
          border: "1px solid var(--line)",
          borderRadius: "6px",
          fontSize: "0.85rem",
          wordBreak: "break-all",
          minWidth: "200px",
        }}>
          {referralUrl}
        </code>
        <button onClick={handleCopy} className="btn btn-primary" style={{ whiteSpace: "nowrap" }}>
          {copied ? "Copied!" : "Copy Link"}
        </button>
      </div>

      <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem", flexWrap: "wrap" }}>
        <a
          href={whatsappUrl(shareText, referralUrl)}
          target="_blank"
          rel="noopener noreferrer"
          className="share-btn share-whatsapp"
          onClick={() => track("referral_share_whatsapp")}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z" />
          </svg>
          Share on WhatsApp
        </a>
      </div>

      {stats && (
        <div style={{
          display: "flex",
          gap: "1.5rem",
          marginTop: "1rem",
          padding: "0.75rem",
          background: "var(--surface)",
          borderRadius: "8px",
        }}>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "var(--accent)" }}>
              {stats.total_visits}
            </div>
            <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>Total Visits</div>
          </div>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "var(--accent)" }}>
              {stats.conversions}
            </div>
            <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>Signups</div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function ReferralPage() {
  usePageTitle("CA Referral Program — Refer & Earn with DoAide GST");
  const { user } = useAuth();
  const [leaders, setLeaders] = useState([]);

  useEffect(() => {
    api.referralLeaderboard()
      .then((data) => setLeaders(data.leaders || []))
      .catch(() => {});
  }, []);

  return (
    <div className="tool-page">
      <SeoHead
        title="CA Referral Program — Refer Clients & Top the Leaderboard"
        description="Refer your clients to DoAide GSTIndia and earn recognition. Get a unique referral link, track visits, and compete on the CA leaderboard."
        path="/referrals"
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <h1 className="tool-title">CA Referral Program</h1>
          <p className="tool-subtitle">
            Share DoAide GST with your clients. Get a unique referral link, track how many
            people use it, and compete on the leaderboard.
          </p>

          {user ? (
            <MyReferralPanel />
          ) : (
            <div className="calc-card" style={{ textAlign: "center" }}>
              <h3 style={{ margin: "0 0 0.5rem" }}>Get Your Referral Link</h3>
              <p style={{ color: "var(--muted)", margin: "0 0 1rem" }}>
                Sign up or log in to get your unique referral link and start tracking referrals.
              </p>
              <a href="/" className="btn btn-primary">
                Sign Up Free
              </a>
            </div>
          )}

          <section style={{ marginTop: "2rem" }}>
            <h2>How It Works</h2>
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: "1rem",
              margin: "1rem 0",
            }}>
              {[
                { step: "1", title: "Get Your Link", desc: "Sign up and grab your unique referral link from this page." },
                { step: "2", title: "Share With Clients", desc: "Send the link to clients via WhatsApp, email, or your website." },
                { step: "3", title: "Track & Compete", desc: "See how many clients visit via your link. Top referrers appear on the leaderboard." },
              ].map((item) => (
                <div key={item.step} className="calc-card" style={{ textAlign: "center" }}>
                  <div style={{
                    width: "2.5rem",
                    height: "2.5rem",
                    borderRadius: "50%",
                    background: "var(--accent)",
                    color: "#fff",
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontWeight: 700,
                    fontSize: "1.1rem",
                    marginBottom: "0.5rem",
                  }}>
                    {item.step}
                  </div>
                  <h3 style={{ margin: "0 0 0.25rem", fontSize: "1rem" }}>{item.title}</h3>
                  <p style={{ color: "var(--muted)", fontSize: "0.85rem", margin: 0 }}>{item.desc}</p>
                </div>
              ))}
            </div>
          </section>

          <section style={{ marginTop: "2rem" }}>
            <h2>Top Referring CAs</h2>
            <LeaderboardTable leaders={leaders} />
          </section>
        </div>
      </main>
      <DoAideFooter />
    </div>
  );
}
