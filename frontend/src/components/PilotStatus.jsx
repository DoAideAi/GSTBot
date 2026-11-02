import { useState } from "react";
import { Link } from "react-router-dom";

export function pilotDate(value) {
  // API dates without an offset come only from SQLite; they still represent UTC.
  const date = new Date(/Z$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
  return date.toLocaleDateString("en-IN", { dateStyle: "medium", timeZone: "Asia/Kolkata" });
}

export default function PilotStatus({ state, busy, onCover }) {
  const [chosen, setChosen] = useState("");
  const enrollment = state?.enrollment;
  if (!enrollment) return null;
  const available = (state.businesses || []).filter((b) => !enrollment.business_ids.includes(b.id));
  const canAdd = state.can_manage && enrollment.active && enrollment.business_ids.length < enrollment.business_limit;
  return (
    <section className="pilot-status" aria-label="Your introductory pilot">
      <h2>{enrollment.active ? "Your free pilot is active" : "Your free pilot has ended"}</h2>
      <p>{enrollment.active ? "Free access ends" : "Free access ended"} <strong>{pilotDate(enrollment.ends_at)}</strong> (India time). No automatic charge.</p>
      <p>Your existing data and included reports remain available to view and export. A paid upgrade is your choice.</p>
      <p>{enrollment.business_ids.length} of {enrollment.business_limit} registrations covered. Each registration uses a place for the full pilot.</p>
      {canAdd && (
        <div className="pilot-cover">
          <label htmlFor="pilot-business">Add a linked registration</label>
          <select id="pilot-business" value={chosen} onChange={(event) => setChosen(event.target.value)} disabled={busy}>
            <option value="">Choose a registration</option>
            {available.map((b) => <option key={b.id} value={b.id}>{b.name}{b.gstin ? ` — ${b.gstin}` : ""}</option>)}
          </select>
          <button className="btn btn-primary" disabled={busy || !chosen} onClick={async () => { await onCover(Number(chosen)); setChosen(""); }}>Include in pilot</button>
          <p>Open your <Link to="/">dashboard</Link> and use the business selector to link another client account, then return to Pricing.</p>
        </div>
      )}
      {!state.is_home && <p>Switch to your own business to manage pilot coverage.</p>}
    </section>
  );
}
