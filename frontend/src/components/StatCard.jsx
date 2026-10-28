import { Link } from "react-router-dom";

export default function StatCard({ label, value, sub, tone = "neutral", to }) {
  const content = (
    <>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </>
  );
  if (to) {
    return (
      <Link to={to} className={`stat-card tone-${tone} stat-card-link`}>
        {content}
      </Link>
    );
  }
  return <div className={`stat-card tone-${tone}`}>{content}</div>;
}
