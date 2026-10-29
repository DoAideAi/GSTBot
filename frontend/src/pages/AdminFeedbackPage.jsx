import { useCallback, useEffect, useState } from "react";
import ErrorBanner from "../components/ErrorBanner";
import { SkeletonPanel } from "../components/Skeleton";
import TableScroll from "../components/TableScroll";
import { CATEGORIES } from "../components/FeedbackWidget";
import { api } from "../lib/api";
import { summarize } from "../lib/feedbackInsights";

const PAGE_SIZE = 50;
const LABELS = Object.fromEntries(CATEGORIES);

/**
 * Where to go when a page came back empty although rows remain: the last page
 * there is. Rows deleted from here, or by another admin, can leave the page
 * being looked at past the end, and an empty page under a count of rows read
 * as "nothing matches" with no pager left to leave it by.
 */
function lastPageOffset(total) {
  return Math.max(0, Math.ceil(total / PAGE_SIZE) - 1) * PAGE_SIZE;
}

function Pager({ offset, total, setOffset }) {
  return (
    <div className="pager">
      <button
        type="button"
        className="btn btn-ghost"
        disabled={offset === 0}
        onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
      >
        Previous
      </button>
      <span className="muted" role="status">
        {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
      </span>
      <button
        type="button"
        className="btn btn-ghost"
        disabled={offset + PAGE_SIZE >= total}
        onClick={() => setOffset(offset + PAGE_SIZE)}
      >
        Next
      </button>
    </div>
  );
}

function when(iso) {
  return new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

function Insights({ meta }) {
  const { sentence, flags } = summarize(meta);
  if (!sentence && flags.length === 0) return null;
  return (
    <div className="feedback-insights">
      {sentence && <p className="feedback-insight-line">{sentence}</p>}
      {flags.length > 0 && (
        <ul className="feedback-flags" aria-label="Struggle signals">
          {flags.map((flag) => (
            <li key={flag.kind} className={`feedback-flag feedback-flag-${flag.kind}`}>
              {flag.label}
            </li>
          ))}
        </ul>
      )}
      {meta?.pages?.length > 1 && (
        <p className="feedback-admin-meta">Path: {meta.pages.join(" → ")}</p>
      )}
    </div>
  );
}

/** Uncaught browser errors, one per page and message, with how often each happened. */
function ErrorLog({ onForbidden }) {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // Paged, where it used to ask for the first fifty and stop: everything past
  // them could not be reached, and clearing the ones shown brought none in.
  const [offset, setOffset] = useState(0);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .listClientErrors({ limit: PAGE_SIZE, offset }, { signal: controller.signal })
      .then((body) => {
        if (body.items.length === 0 && body.total > 0 && offset > 0) {
          setOffset(lastPageOffset(body.total));
          return;
        }
        setItems(body.items);
        setTotal(body.total);
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        if (err?.status === 403) onForbidden();
        else setError(err?.message || "The error log could not be loaded.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [onForbidden, offset, reload]);

  const markFixed = async (row) => {
    if (!window.confirm(`Clear "${row.message.slice(0, 80)}"? If it happens again it is logged afresh.`)) return;
    try {
      await api.deleteClientError(row.id);
      setItems((all) => all.filter((r) => r.id !== row.id));
      setTotal((t) => t - 1);
      // Asked again, for the reason the feedback list gives.
      setReload((n) => n + 1);
    } catch (err) {
      setError(err?.message || "That error could not be cleared.");
    }
  };

  return (
    <section className="panel">
      <ErrorBanner message={error} onDismiss={() => setError("")} />
      {loading ? (
        <SkeletonPanel lines={4} label="Loading errors" />
      ) : items.length === 0 ? (
        error ? null : <p className="muted">No browser errors have been reported.</p>
      ) : (
        <>
          <p className="muted">
            {total} distinct error{total === 1 ? "" : "s"}, most recently seen first.
          </p>
          <TableScroll label="Browser errors">
            <table className="table feedback-admin-table">
              <thead>
                <tr>
                  <th scope="col">Last seen</th>
                  <th scope="col">Times</th>
                  <th scope="col">Error</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id}>
                    <td>{when(row.last_seen_at)}</td>
                    <td>{row.occurrences}</td>
                    <td>
                      <div className="feedback-admin-message">{row.message}</div>
                      <div className="feedback-admin-meta">
                        {row.page} · first seen {when(row.first_seen_at)}
                      </div>
                      {row.stack && (
                        <details>
                          <summary className="feedback-admin-meta">Stack</summary>
                          <pre className="feedback-admin-stack">{row.stack}</pre>
                        </details>
                      )}
                    </td>
                    <td>
                      <button type="button" className="btn btn-ghost" onClick={() => markFixed(row)}>
                        Mark fixed
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
          {total > PAGE_SIZE && <Pager offset={offset} total={total} setOffset={setOffset} />}
        </>
      )}
    </section>
  );
}

/**
 * The feedback inbox. Readable only by the sign-in emails in the server's
 * ADMIN_EMAILS; for anyone else the API answers 403 and this page says so
 * rather than showing an empty inbox, which would read as "nobody wrote in".
 */
export default function AdminFeedbackPage() {
  const [filters, setFilters] = useState({ category: "", since: "", until: "" });
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [forbidden, setForbidden] = useState(false);
  const [view, setView] = useState("feedback");
  const [reload, setReload] = useState(0);
  const onForbidden = useCallback(() => setForbidden(true), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api
      .listFeedback({ ...filters, limit: PAGE_SIZE, offset }, { signal: controller.signal })
      .then((body) => {
        if (body.items.length === 0 && body.total > 0 && offset > 0) {
          setOffset(lastPageOffset(body.total));
          return;
        }
        setItems(body.items);
        setTotal(body.total);
        setForbidden(false);
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        if (err?.status === 403) setForbidden(true);
        else setError(err?.message || "The feedback could not be loaded.");
        setItems([]);
        setTotal(0);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [filters, offset, reload]);

  const remove = async (f) => {
    if (!window.confirm("Delete this feedback? This cannot be undone.")) return;
    try {
      await api.deleteFeedback(f.id);
      setItems((all) => all.filter((x) => x.id !== f.id));
      setTotal((t) => t - 1);
      // Asked again rather than trusted locally. The server's next page now
      // starts one row further on, so the row that moves up onto this page
      // was shown on neither; and a page emptied this way is stepped back
      // from above rather than left saying nothing matches.
      setReload((n) => n + 1);
    } catch (err) {
      setError(err?.message || "That feedback could not be deleted.");
    }
  };

  const setFilter = (key) => (e) => {
    setOffset(0);
    setFilters((f) => ({ ...f, [key]: e.target.value }));
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Feedback</h1>
          <p className="muted">
            What visitors sent from the feedback button, and the errors their browsers reported.
          </p>
        </div>
      </div>

      {!forbidden && (
        <div className="filter-row" role="group" aria-label="View">
          {[
            ["feedback", "Feedback"],
            ["errors", "Browser errors"],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={view === value ? "chip chip-neutral is-active" : "chip chip-neutral"}
              aria-pressed={view === value}
              onClick={() => setView(value)}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      <ErrorBanner message={error} onDismiss={() => setError("")} />

      {forbidden ? (
        <section className="panel">
          <p>
            This inbox is for site administrators. Your account is not on the server&apos;s{" "}
            <code>ADMIN_EMAILS</code> list.
          </p>
        </section>
      ) : view === "errors" ? (
        <ErrorLog onForbidden={onForbidden} />
      ) : (
        <>
          <div className="filters">
            <div className="filter-row">
              <label>
                Category{" "}
                <select value={filters.category} onChange={setFilter("category")}>
                  <option value="">All</option>
                  {CATEGORIES.map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                From <input type="date" value={filters.since} onChange={setFilter("since")} />
              </label>
              <label>
                To <input type="date" value={filters.until} onChange={setFilter("until")} />
              </label>
            </div>
          </div>

          <section className="panel">
            {loading ? (
              <SkeletonPanel lines={5} label="Loading feedback" />
            ) : error ? null : items.length === 0 ? (
              <p className="muted">No feedback matches these filters.</p>
            ) : (
              <>
                <TableScroll label="Feedback">
                  <table className="table feedback-admin-table">
                    <thead>
                      <tr>
                        <th scope="col">Received</th>
                        <th scope="col">Category</th>
                        <th scope="col">Message</th>
                        <th scope="col">From</th>
                        <th scope="col">
                          <span className="visually-hidden">Actions</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((f) => (
                        <tr key={f.id}>
                          <td>{when(f.created_at)}</td>
                          <td>{LABELS[f.category] ?? f.category}</td>
                          <td>
                            <div className="feedback-admin-message">{f.message}</div>
                            <Insights meta={f.metadata} />
                          </td>
                          <td className="feedback-admin-meta">
                            {f.email ? <a href={`mailto:${f.email}`}>{f.email}</a> : "No email"}
                            {f.page_url && <div>{f.page_url}</div>}
                            {f.ip_address && <div>{f.ip_address}</div>}
                            {f.user_agent && <div title={f.user_agent}>{f.user_agent.slice(0, 60)}</div>}
                          </td>
                          <td>
                            <button type="button" className="btn btn-ghost" onClick={() => remove(f)}>
                              Delete
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableScroll>

                <Pager offset={offset} total={total} setOffset={setOffset} />
              </>
            )}
          </section>
        </>
      )}
    </div>
  );
}
