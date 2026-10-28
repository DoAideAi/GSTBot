import { useEffect, useState } from "react";
import ErrorBanner from "../components/ErrorBanner";
import { SkeletonPanel } from "../components/Skeleton";
import TableScroll from "../components/TableScroll";
import { CATEGORIES } from "../components/FeedbackWidget";
import { api } from "../lib/api";
import { summarize } from "../lib/feedbackInsights";

const PAGE_SIZE = 50;
const LABELS = Object.fromEntries(CATEGORIES);

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

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api
      .listFeedback({ ...filters, limit: PAGE_SIZE, offset }, { signal: controller.signal })
      .then((body) => {
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
  }, [filters, offset]);

  const setFilter = (key) => (e) => {
    setOffset(0);
    setFilters((f) => ({ ...f, [key]: e.target.value }));
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Feedback</h1>
          <p className="muted">What visitors sent from the feedback button, newest first.</p>
        </div>
      </div>

      <ErrorBanner message={error} onDismiss={() => setError("")} />

      {forbidden ? (
        <section className="panel">
          <p>
            This inbox is for site administrators. Your account is not on the server&apos;s{" "}
            <code>ADMIN_EMAILS</code> list.
          </p>
        </section>
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
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableScroll>

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
              </>
            )}
          </section>
        </>
      )}
    </div>
  );
}
