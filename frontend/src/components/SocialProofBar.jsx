import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { TOOL_MAP } from "../lib/doaideViral";
import { formatStat, getUsageStats } from "../lib/usageStats";

const bar = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  gap: "1.5rem",
  padding: "0.5rem 1rem",
  fontSize: "0.8rem",
  color: "var(--text-muted, #888)",
  flexWrap: "wrap",
};

// Real aggregates from /meta/stats, or nothing. This bar used to show a
// seeded pseudo-random "N people used this today" with an invented star
// rating; a visitor who reloads and watches the rating drift is lost for
// good, and fabricated review counts are the kind of structured lie
// crawlers eventually penalise too.
export default function SocialProofBar() {
  const { pathname } = useLocation();
  const onToolPage = Boolean(TOOL_MAP[pathname]);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    if (!onToolPage) return undefined;
    let mounted = true;
    getUsageStats().then((s) => {
      if (mounted) setStats(s);
    });
    return () => {
      mounted = false;
    };
  }, [onToolPage]);

  if (!onToolPage || !stats) return null;

  const lines = [
    [formatStat(stats.gstin_lookups), "GSTIN lookups served"],
    [formatStat(stats.invoices), "invoices processed"],
  ].filter(([figure]) => figure !== null);

  if (lines.length === 0) return null;

  return (
    <div style={bar}>
      {lines.map(([figure, label]) => (
        <span key={label}>
          <strong>{figure}</strong> {label}
        </span>
      ))}
      <span>Free &bull; No login required</span>
    </div>
  );
}
