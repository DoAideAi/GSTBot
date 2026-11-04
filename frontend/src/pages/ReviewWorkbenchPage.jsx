import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ErrorBanner from "../components/ErrorBanner";
import ReadOnlyNotice from "../components/ReadOnlyNotice";
import { useAuth } from "../hooks/useAuth";
import { usePageTitle } from "../hooks/usePageTitle";
import { api, isAbortError } from "../lib/api";
import { saveBlob } from "../lib/download";
import { periodLabel, rupees } from "../lib/format";
import "./practice.css";

const pretty = (s) => (s || "").replaceAll("_", " ");
function FindingEditor({ finding, index, review, reviewers, disabled, save }) {
  const [form, setForm] = useState({
    status: review?.status || "open",
    decision: review?.decision || "none",
    assignee_id: review?.assignee_id || "",
    note: review?.note || "",
  });
  return (
    <details className="practice-row">
      <summary>
        {finding.invoice_number || "Unnumbered invoice"} ·{" "}
        {pretty(finding.category)} · {pretty(review?.status || "open")}
      </summary>
      <small>
        {finding.supplier_name || "Supplier"} · {finding.supplier_gstin}
      </small>
      <div className="practice-grid">
        <p>
          Books tax:{" "}
          <strong>
            {finding.books ? rupees(finding.books.total_tax) : "Not in books"}
          </strong>
        </p>
        <p>
          2B tax:{" "}
          <strong>
            {finding.gstr2b ? rupees(finding.gstr2b.total_tax) : "Not in 2B"}
          </strong>
        </p>
      </div>
      {finding.note && <p>{finding.note}</p>}
      {finding.differences?.length > 0 && (
        <ul>
          {finding.differences.map((d) => (
            <li key={d.field}>
              {pretty(d.field)}: books {rupees(d.books)}; 2B {rupees(d.gstr2b)}
            </li>
          ))}
        </ul>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save(index, {
            ...form,
            assignee_id: form.assignee_id ? Number(form.assignee_id) : null,
            version: review?.version || 0,
          });
        }}
      >
        <div className="practice-grid">
          <label>
            Review status
            <select
              value={form.status}
              disabled={disabled}
              onChange={(e) => setForm({ ...form, status: e.target.value })}
            >
              <option value="open">Open</option>
              <option value="in_review">In review</option>
              <option value="resolved">Resolved</option>
            </select>
          </label>
          <label>
            Decision
            <select
              value={form.decision}
              disabled={disabled}
              onChange={(e) => setForm({ ...form, decision: e.target.value })}
            >
              <option value="none">Not decided</option>
              <option value="accept_match">Accept the recorded finding</option>
              <option value="reject_match">
                Disagree with the recorded finding
              </option>
              <option value="follow_up">Follow-up required</option>
            </select>
          </label>
          <label>
            Assigned reviewer
            <select
              value={form.assignee_id}
              disabled={disabled}
              onChange={(e) =>
                setForm({ ...form, assignee_id: e.target.value })
              }
            >
              <option value="">Unassigned</option>
              {reviewers.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label>
          Evidence and resolution note
          <textarea
            maxLength={2000}
            required={form.status === "resolved"}
            value={form.note}
            disabled={disabled}
            onChange={(e) => setForm({ ...form, note: e.target.value })}
          />
        </label>
        <div className="practice-actions">
          <button className="btn btn-primary" disabled={disabled}>
            Save review
          </button>
          {finding.invoice_id && (
            <Link to={`/invoices/${finding.invoice_id}`}>
              Open source invoice
            </Link>
          )}
        </div>
      </form>
    </details>
  );
}

export default function ReviewWorkbenchPage() {
  usePageTitle("Review reconciliation");
  const { runId } = useParams();
  const { canWrite } = useAuth();
  const [data, setData] = useState(null);
  const [filter, setFilter] = useState("exceptions");
  const [page, setPage] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const load = useCallback(
    (signal) => api.reviewWorkbench(runId, { signal }).then(setData),
    [runId],
  );
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).catch((e) => {
      if (!isAbortError(e)) setError(e.message);
    });
    return () => controller.abort();
  }, [load]);
  const perform = async (fn, text) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await fn();
      await load();
      setMessage(text);
      setConfirmed(false);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const reviews = new Map(data?.reviews.map((r) => [r.finding_index, r]));
  const findings = (data?.findings || [])
    .map((finding, index) => ({ finding, index }))
    .filter(
      ({ finding, index }) =>
        filter === "all" ||
        (filter === "unresolved"
          ? (finding.category !== "matched" || reviews.has(index)) &&
            reviews.get(index)?.status !== "resolved"
          : finding.category !== "matched" || reviews.has(index)),
    );
  return (
    <div className="practice-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Accountant review</p>
          <h1>Resolve the exceptions</h1>
          <p className="muted">
            {data
              ? `${periodLabel(data.period)} · Run ${data.run_id}`
              : "Loading reconciliation…"}
          </p>
        </div>
        {data && (
          <Link
            className="btn btn-ghost"
            to={`/reconcile?period=${data.period}`}
          >
            Back to Reconcile
          </Link>
        )}
      </div>
      <ReadOnlyNotice />
      <ErrorBanner message={error} onDismiss={() => setError("")} />
      {message && (
        <p className="practice-note" role="status">
          {message}
        </p>
      )}
      {data && (
        <>
          <p className="practice-note">
            Review decisions record your assessment. They do not change invoice
            amounts, tax eligibility or the original matching result. Correct
            the source invoice and reconcile again when the figures or match are
            wrong.
          </p>
          <p><Link className="btn btn-ghost" to={`/review/${runId}/suppliers`}>Prepare supplier follow-ups</Link></p>
          {data.stale && (
            <p className="practice-error" role="alert">
              This run is historical or its source data changed. Reconcile again
              before saving reviews or exporting a current report.
            </p>
          )}
          <section className="panel">
            <div className="page-heading">
              <h2>{data.unresolved} unresolved exceptions</h2>
              <label>
                Show
                <select
                  value={filter}
                  onChange={(e) => {
                    setFilter(e.target.value);
                    setPage(0);
                  }}
                >
                  <option value="exceptions">All exceptions</option>
                  <option value="unresolved">Unresolved exceptions</option>
                  <option value="all">Every finding, including matched</option>
                </select>
              </label>
            </div>
            {!findings.length && (
              <p>
                No findings in this view. Review the complete report before
                marking it complete.
              </p>
            )}
            {findings
              .slice(page * 25, (page + 1) * 25)
              .map(({ finding, index }) => (
                <FindingEditor
                  key={`${index}-${reviews.get(index)?.version || 0}`}
                  finding={finding}
                  index={index}
                  review={reviews.get(index)}
                  reviewers={data.reviewers}
                  disabled={!canWrite || busy || data.stale}
                  save={(i, payload) =>
                    perform(
                      () => api.saveFindingReview(runId, i, payload),
                      "Review saved with an audit entry.",
                    )
                  }
                />
              ))}
            {findings.length > 25 && (
              <div className="practice-actions">
                <button
                  className="btn btn-ghost"
                  disabled={!page}
                  onClick={() => setPage(page - 1)}
                >
                  Previous findings
                </button>
                <span>
                  Page {page + 1} of {Math.ceil(findings.length / 25)}
                </span>
                <button
                  className="btn btn-ghost"
                  disabled={(page + 1) * 25 >= findings.length}
                  onClick={() => setPage(page + 1)}
                >
                  Next findings
                </button>
              </div>
            )}
          </section>
          <section className="panel">
            <h2>Complete the report review</h2>
            <p>
              Confirm the full report is usable for your records. This is not a
              return submission or confirmation of tax-credit eligibility.
            </p>
            <label className="practice-check">
              <input
                type="checkbox"
                checked={confirmed}
                disabled={
                  !canWrite || busy || data.stale || data.unresolved > 0
                }
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              I have reviewed this run, including matched invoices and the
              recorded resolutions.
            </label>
            <div className="practice-actions">
              <button
                className="btn btn-primary"
                disabled={
                  !confirmed ||
                  !canWrite ||
                  busy ||
                  data.stale ||
                  data.unresolved > 0
                }
                onClick={() =>
                  perform(
                    () => api.approveReviewedReport(runId),
                    "Report review complete. You can now export it.",
                  )
                }
              >
                Mark report reviewed
              </button>
              <button
                className="btn btn-ghost"
                disabled={busy || data.stale || !data.approved}
                onClick={() =>
                  perform(async () => {
                    const file = await api.exportReviewedReport(runId);
                    saveBlob(file.blob, file.filename);
                  }, "Reviewed report exported.")
                }
              >
                Export reviewed CSV
              </button>
              <button className="btn btn-ghost" disabled={busy || data.stale || !data.approved}
                onClick={() => perform(async () => {
                  const file = await api.exportReviewWorkbook(runId);
                  saveBlob(file.blob, file.filename);
                }, "Excel workbook exported with summary, supplier totals, findings and review history.")}>Export reviewed Excel</button>
            </div>
            <p className="practice-footer">
              Export follows the existing pilot/report entitlement. New source
              data or review changes require a fresh review.
            </p>
          </section>
          <section className="panel">
            <h2>Review history</h2>
            <p className="muted">
              Latest 200 recorded changes. Saved decisions are retained with
              this run.
            </p>
            <div className="practice-history">
              {!data.events.length ? (
                <p>No review changes recorded yet.</p>
              ) : (
                data.events.map((event) => (
                  <div className="practice-row" key={event.id}>
                    <strong>
                      {data.reviewers.find((r) => r.id === event.actor_id)
                        ?.name || `Reviewer ${event.actor_id}`}
                    </strong>{" "}
                    · {pretty(event.current.status)} ·{" "}
                    {pretty(event.current.decision)}
                    <small>
                      {new Date(event.at).toLocaleString()} · Finding{" "}
                      {event.current.finding_index + 1}
                    </small>
                    <p>{event.current.note}</p>
                  </div>
                ))
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
