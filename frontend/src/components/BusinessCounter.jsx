import { useEffect, useState } from "react";
import { formatStat, getUsageStats } from "../lib/usageStats";

// The figure is the real business count from /meta/stats — this used to be a
// date-seeded invention that drifted by the day. Until the count clears the
// floor in lib/usageStats the line stays non-numeric: honest and vague beats
// precise and false.
export default function BusinessCounter() {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    let mounted = true;
    getUsageStats().then((s) => {
      if (mounted) setStats(s);
    });
    return () => {
      mounted = false;
    };
  }, []);

  const figure = stats ? formatStat(stats.businesses) : null;

  return (
    <div className="business-counter" role="status" aria-label="Business usage count">
      <div className="business-counter-inner">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4-4v2" />
          <circle cx="9" cy="7" r="4" />
          <path d="M23 21v-2a4 4 0 00-3-3.87" />
          <path d="M16 3.13a4 4 0 010 7.75" />
        </svg>
        <span className="business-counter-text">
          {figure ? (
            <>Used by <strong>{figure}+</strong> Indian businesses</>
          ) : (
            <>Built for Indian businesses</>
          )}
        </span>
        <span className="business-counter-badge">Free &bull; No signup</span>
      </div>
    </div>
  );
}
