import { useEffect, useState } from "react";
import { api } from "../lib/api";

export default function RecentLookups() {
  const [lookups, setLookups] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api.recentLookups()
      .then((data) => {
        if (!cancelled) setLookups(data.lookups || []);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  if (loading || lookups.length === 0) return null;

  return (
    <section className="recent-lookups" aria-labelledby="recent-lookups-heading">
      <h2 id="recent-lookups-heading" className="recent-lookups-title">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--brand)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
        Recently Verified Businesses
      </h2>
      <div className="recent-lookups-list">
        {/* Not links: the API masks the PAN inside each GSTIN so the feed does
            not publish who was looked up, and a masked GSTIN has no page. Keyed
            by position because two masked GSTINs can read the same. */}
        {lookups.map((l, i) => (
          <div key={i} className="recent-lookup-item">
            <div className="recent-lookup-gstin">
              <code>{l.gstin}</code>
              <span className={`recent-lookup-status ${l.valid ? "lookup-valid" : "lookup-invalid"}`}>
                {l.valid ? "Active" : "Invalid"}
              </span>
            </div>
            <div className="recent-lookup-details">
              {l.state_name && <span>{l.state_name}</span>}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
