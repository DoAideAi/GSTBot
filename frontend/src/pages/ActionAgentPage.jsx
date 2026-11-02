import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import BrandMark from "../components/BrandMark";
import ErrorBanner from "../components/ErrorBanner";
import { usePageTitle } from "../hooks/usePageTitle";
import { api, isAbortError } from "../lib/api";
import { linkedPeriod, currentPeriod, periodLabel, rupees } from "../lib/format";
import "./action-agent.css";

const DESTINATIONS = {
  invoices: ["/invoices", "Review invoices"],
  upload: ["/upload", "Upload invoices"],
  reconcile: ["/reconcile", "Open reconciliation"],
  itc: ["/itc", "Review ITC"],
  filing: ["/filing", "Open filing"],
  alerts: ["/alerts", "View alerts"],
};
const SOURCES = { overview: "Period overview", reconciliation: "GSTR-2B reconciliation", invoice_checks: "Invoice checks" };
const FOCUSES = [
  ["all", "Review my month", "Find the next steps across your records."],
  ["itc", "Find ITC risks", "Check missing matches and differences."],
  ["filing", "Check filing readiness", "Look for invoice issues before filing."],
];

export default function ActionAgentPage() {
  usePageTitle("GST Action Agent");
  const location = useLocation();
  const [period, setPeriod] = useState(() => linkedPeriod(location.search, currentPeriod()));
  const [focus, setFocus] = useState("all");
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const pending = useRef(null);

  useEffect(() => () => {
    pending.current?.abort();
    pending.current = null;
  }, []);

  function reset() {
    pending.current?.abort();
    pending.current = null;
    setLoading(false);
    setReport(null);
    setError(null);
  }

  async function review(event) {
    event.preventDefault();
    if (pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true);
    setReport(null);
    setError(null);
    try {
      const result = await api.reviewActions({ period, focus }, { signal: controller.signal });
      if (pending.current === controller) setReport(result);
    } catch (err) {
      if (pending.current === controller && !isAbortError(err)) setError(err);
    } finally {
      if (pending.current === controller) {
        pending.current = null;
        setLoading(false);
      }
    }
  }

  return (
    <div className="action-agent-page">
      <header className="agent-heading">
        <div><p className="agent-eyebrow">YOUR NEXT STEPS</p><h1>GST Action Agent</h1>
          <p className="muted">Turn this month’s records into a clear plan of action.</p></div>
        <BrandMark size={44} />
      </header>
      <form className="panel agent-setup" onSubmit={review}>
        <div className="agent-setup-heading">
          <div><h2>What should we review?</h2><p className="muted small">Choose a focus and filing period.</p></div>
          <label className="agent-period">Filing period
            <input type="month" required min="2017-07" max="2099-12" value={period}
              onChange={e => { reset(); setPeriod(e.target.value); }} />
          </label>
        </div>
        <fieldset className="agent-focuses"><legend className="visually-hidden">Review focus</legend>
          {FOCUSES.map(([value, title, description]) => (
            <label key={value} className={focus === value ? "agent-focus is-selected" : "agent-focus"}>
              <input type="radio" name="focus" value={value} checked={focus === value}
                onChange={() => { reset(); setFocus(value); }} />
              <span><strong>{title}</strong><span className="muted small">{description}</span></span>
            </label>
          ))}
        </fieldset>
        <div className="agent-start">
          <p className="muted small">Uses OpenAI to review summaries from your active business. Your records stay unchanged; you choose which steps to take.</p>
          <button className="btn btn-primary" type="submit" disabled={loading || !period}>
            {loading ? "Reviewing records…" : "Create action plan"}
          </button>
        </div>
      </form>
      <ErrorBanner message={error?.message} />
      {loading && <section className="panel agent-progress" role="status" aria-live="polite">
        <span className="agent-pulse" aria-hidden="true" />
        <div><strong>Reviewing {periodLabel(period)}</strong><p className="muted small">Checking the relevant records and prioritising your next steps. This may take up to a minute.</p></div>
        <button type="button" className="btn btn-ghost" onClick={reset}>Cancel</button>
      </section>}
      {report && <section className="agent-result" aria-label="Your action plan" aria-live="polite">
        <div className="panel agent-summary">
          <p className="agent-eyebrow">{periodLabel(report.period)} · ACTION PLAN</p>
          <h2>Here’s where to focus</h2><p>{report.plan.summary}</p>
          <div className="agent-evidence" aria-label="Records checked">
            {report.checked.map(source => <span key={source}>{SOURCES[source]}</span>)}
          </div>
          <div className="agent-facts">
            <div><span>Invoices this period</span><strong>{report.facts.invoice_count}</strong></div>
            <div><span>Output tax in books</span><strong>{rupees(report.facts.output_tax)}</strong></div>
            <div><span>Book credit before reconciliation</span><strong>{rupees(report.facts.book_credit_before_reconciliation)}</strong></div>
          </div>
        </div>
        <ol className="agent-actions">
          {report.plan.actions.map((action, index) => {
            const destination = DESTINATIONS[action.destination];
            return <li className="panel agent-action" key={`${index}-${action.title}`}>
              <span className="agent-step" aria-hidden="true">{index + 1}</span>
              <div className="agent-action-body">
                <span className={`agent-priority agent-priority-${action.priority}`}>{action.priority} priority</span>
                <h3>{action.title}</h3><p>{action.reason}</p>
                <p><strong>Next step:</strong> {action.next_step}</p>
                <p className="muted small">Based on: {action.sources.map(source => SOURCES[source]).join(" · ")}</p>
                {destination && <Link className="btn btn-ghost" to={["reconcile", "itc", "filing"].includes(action.destination)
                  ? `${destination[0]}?period=${report.period}` : destination[0]}>{destination[1]}</Link>}
              </div>
            </li>;
          })}
        </ol>
        <aside className="panel agent-review-note">
          <h3>Before you act</h3>
          <p className="muted small">AI suggestions can be mistaken. Review the source records and confirm filing decisions with your accountant. The filing, ITC and reconciliation links keep this period selected.</p>
          {report.plan.caveats.length > 0 && <ul>{report.plan.caveats.map((text, index) => <li key={index}>{text}</li>)}</ul>}
          <p className="muted small">Generated {new Date(report.generated_at).toLocaleString("en-IN")}. Run a fresh review after changing your records.</p>
        </aside>
      </section>}
      {!report && !loading && !error && <section className="agent-empty" aria-label="How the review works">
        <BrandMark size={32} /><h2>A useful starting point for your month</h2>
        <p className="muted">The agent checks your period overview, investigates relevant invoice and reconciliation issues, and brings the most useful next steps together.</p>
        <p className="muted small">No invoices yet? Start by <Link to="/upload">uploading your records</Link>.</p>
      </section>}
    </div>
  );
}
