import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import ErrorBanner from "../components/ErrorBanner";
import Pager from "../components/Pager";
import { SkeletonPanel } from "../components/Skeleton";
import { useAuth } from "../hooks/useAuth";
import { usePageTitle } from "../hooks/usePageTitle";
import { api, isAbortError } from "../lib/api";
import { dateLabel, periodLabel } from "../lib/format";

const SEVERITY = {
  critical: { label: "Overdue", tone: "bad" },
  warning: { label: "Due soon", tone: "warn" },
  info: { label: "Upcoming", tone: "neutral" },
};

// The API's own page size; see Pager.
const ALERT_PAGE_SIZE = 50;

const SCOPES = [
  ["open", "Open"],
  ["closed", "Closed"],
  ["all", "All"],
];

// What a closed alert closed *for*. The two are not the same event and the
// difference is the only thing that says whether these alerts do anything:
// resolved means the return was actually filed, dismissed means the business
// made the reminder go away. Collapsing them into "closed" on screen would
// throw that away at the one place a person can see it.
const CLOSED_LABEL = {
  resolved: "Filed",
  dismissed: "Dismissed",
};

function SeverityChip({ severity }) {
  const meta = SEVERITY[severity] ?? SEVERITY.info;
  return <span className={`chip chip-${meta.tone}`}>{meta.label}</span>;
}

/**
 * One alert, with the two things a business can do to it.
 *
 * "Mark as read" and "Dismiss" are separate buttons rather than one because the
 * API keeps them separate on purpose: reading a filing deadline leaves it every
 * bit as unmet, so it stays in the badge, while dismissing it says "I know" and
 * stops the sweep raising it again tomorrow.
 */
function AlertRow({ alert, busy, canWrite, onRead, onDismiss }) {
  const closed = CLOSED_LABEL[alert.status];
  const unread = alert.status === "pending" || alert.status === "sent";
  // Read and dismiss are both writes, and "Record filing" leads to the one
  // control on the filing screen a viewer also does not have. With all three
  // gone the row has no actions left, so the container goes too rather than
  // leaving an empty flex row's padding under every alert.
  const actions = canWrite && (unread || !closed || alert.alert_type === "filing_deadline");

  return (
    <li className={`alert-row is-${SEVERITY[alert.severity]?.tone ?? "neutral"}`}>
      <div className="alert-head">
        <SeverityChip severity={alert.severity} />
        <h3 className={unread ? "alert-title is-unread" : "alert-title"}>{alert.title}</h3>
        {closed && <span className="chip chip-neutral">{closed}</span>}
      </div>

      <p className="alert-message">{alert.message}</p>

      <p className="muted small alert-meta">
        {alert.period && <>{periodLabel(alert.period)} · </>}
        {alert.due_date && <>Due {dateLabel(alert.due_date)} · </>}
        Raised {dateLabel(alert.created_at)}
      </p>

      {actions && (
        <div className="alert-actions">
          {/* The alert asks for a filing, and this is where a filing gets
              recorded — so the way to make a deadline alert close *properly* is
              one click away rather than something to go and find. Recording the
              filing resolves it on the next sweep; dismissing only silences it. */}
          {alert.alert_type === "filing_deadline" && !closed && (
            <Link to="/filing" className="btn btn-primary">
              Record filing
            </Link>
          )}
          {unread && (
            <button
              type="button"
              className="btn btn-ghost"
              disabled={busy}
              onClick={onRead}
            >
              Mark as read
            </button>
          )}
          {!closed && (
            <button
              type="button"
              className="btn btn-ghost"
              disabled={busy}
              onClick={onDismiss}
            >
              Dismiss
            </button>
          )}
        </div>
      )}
    </li>
  );
}

export default function AlertsPage() {
  usePageTitle("Alerts");
  const { canWrite } = useAuth();
  const [items, setItems] = useState([]);
  const [openTotal, setOpenTotal] = useState(0);
  const [scope, setScope] = useState("open");
  // Paged: the list showed the API's first fifty, so a backlog past that was
  // in the badge's count and nowhere on screen. Another tab starts at page one.
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  // Bumped to ask for the page again after a row leaves it; see `apply`.
  const [reloadToken, setReloadToken] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  // Whether the list on screen failed to load, as opposed to loading and
  // coming back empty. `error` cannot answer that: a row action that fails
  // fills the same banner while the list behind it is perfectly good, so
  // reading the banner would blank a list that has nothing wrong with it.
  const [loadFailed, setLoadFailed] = useState(false);
  // Which alerts have an action in flight. Per-id rather than one page-wide
  // flag so dismissing the third alert does not disable the buttons on the
  // other nine — clearing a backlog is one row at a time, and that is the whole
  // interaction this screen exists for.
  //
  // A set rather than a single id, because "one row at a time" is how it is
  // clicked, not how it is answered: the clicks run ahead of the network and
  // several are in the air together. Holding one id, the second row clicked
  // took the flag off the first, re-enabling a button whose own request had not
  // come back — and a second click on it decremented `openTotal` twice for one
  // alert, which the server cannot correct because dismissing an already
  // dismissed alert honestly answers "dismissed" both times. The badge then
  // under-reported the backlog until the next load.
  const [pending, setPending] = useState(() => new Set());
  // Which scope the list on screen is showing, readable from a callback that
  // has been waiting on the network. The tabs stay live while an action is in
  // flight, so `scope` closed over at click time is the tab the action was
  // *started* from — the one thing the answer must not assume is still up.
  const shownScope = useRef(scope);

  const load = useCallback(async (target, from, { signal } = {}) => {
    setLoading(true);
    setError("");
    try {
      const data = await api.listAlerts(
        { scope: target, limit: ALERT_PAGE_SIZE, offset: from },
        { signal },
      );
      // A page left empty behind the user — the last rows on it closed, here
      // or by the sweep — steps back to the last page there is.
      if (data.items.length === 0 && data.total > 0 && from > 0) {
        setOffset(Math.max(0, Math.ceil(data.total / ALERT_PAGE_SIZE) - 1) * ALERT_PAGE_SIZE);
        return;
      }
      setItems(data.items);
      setTotal(data.total ?? data.items.length);
      setOpenTotal(data.open_total);
      setLoadFailed(false);
    } catch (err) {
      // A superseded request has been replaced by a newer one that owns the
      // list, the banner and the spinner from here on.
      if (isAbortError(err)) return;
      setError(err.message);
      // The rows on screen belong to the scope that was up before this one was
      // asked for, and no answer is coming to replace them. That is the fault
      // the abort guard above exists to stop — closed alerts under an "Open"
      // tab — reached by the other road, and the worse way round: the tab a
      // failed load leaves showing is the one the user navigated *away* from,
      // with its Dismiss buttons live under a heading that disowns them.
      //
      // `open_total` is deliberately kept. It counts open alerts whatever tab
      // is up, so it is not a figure this scope captions, and the badge going
      // to zero would read as a cleared backlog.
      setItems([]);
      setLoadFailed(true);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  // Aborted on the way out, like every other list in the product: switching
  // scope twice quickly would otherwise let the first answer land last and
  // leave closed alerts under an "Open" tab.
  useEffect(() => {
    const controller = new AbortController();
    shownScope.current = scope;
    load(scope, offset, { signal: controller.signal });
    return () => controller.abort();
  }, [load, scope, offset, reloadToken]);

  /**
   * Apply one action and fold the server's answer back into the row.
   *
   * The updated alert is taken from the response rather than assumed, because
   * both endpoints are deliberately non-committal: marking read never reopens a
   * dismissed alert, and dismissing one the sweep already resolved leaves it
   * resolved. Guessing the new status here would show a filed return as
   * "Dismissed" — losing exactly the distinction the two statuses exist for.
   */
  async function apply(alert, action) {
    const id = alert.id;
    const target = scope;
    setPending((prev) => new Set(prev).add(id));
    setError("");
    try {
      const updated = await action(id);

      // Both edits below describe the list this action was started over. If
      // the user has since changed tab, that list is gone and a fresh one has
      // been fetched — so neither edit has anywhere honest to land.
      //
      // The row edit would land on the wrong list: dismissing under "Open"
      // and stepping to "Closed" mid-flight removed the alert from the closed
      // list, which is the one tab it now belongs on. And the count edit
      // would land twice, because the reload already set `open_total` from
      // the server — so the badge lost one it had already lost and went on
      // under-reporting the backlog until the next load.
      //
      // Dropped rather than reconciled. The action itself has been applied
      // server-side and the freshly loaded list is what the server says, so
      // what is on screen is merely a moment stale rather than wrong — and a
      // stale list corrects itself on the next load, where a wrong count does
      // not announce itself at all.
      if (shownScope.current !== target) return;

      setItems((prev) =>
        // Under the open scope an alert that just closed no longer belongs in
        // the list it is sitting in, so it leaves rather than lingering as a
        // row the filters say should not be there.
        target === "open" && !["pending", "sent", "read", "failed"].includes(updated.status)
          ? prev.filter((alert) => alert.id !== id)
          : prev.map((alert) => (alert.id === id ? updated : alert)),
      );
      // A row that left the page is replaced by asking for the page again
      // when there is anything beyond it: the server's next page now starts
      // one row further on, so the alert that moves up onto this one would
      // otherwise be on neither. A list that fits on one page has nothing to
      // bring up, and drops the row as before.
      if (target === "open" && !["pending", "sent", "read", "failed"].includes(updated.status)) {
        setTotal((t) => Math.max(0, t - 1));
        if (offset > 0 || total > ALERT_PAGE_SIZE) setReloadToken((n) => n + 1);
      }
      // Recomputed from the same response set rather than decremented blindly:
      // marking an alert read does not change the open count, and dismissing
      // one that was already closed does not either.
      setOpenTotal((total) =>
        ["pending", "sent", "read", "failed"].includes(updated.status)
          ? total
          : Math.max(0, total - 1),
      );
    } catch (err) {
      // Kept whatever tab is up, unlike the two edits above. This is not a
      // superseded load whose view has gone — the user asked for this action
      // and it failed, and that is worth saying wherever they are standing.
      //
      // Named by the alert's own title rather than left as the bare server
      // message: `pending` is a set because several rows can be in flight at
      // once, and a banner that just says "failed to dismiss" over a list of
      // ten gives no way to tell which one needs a retry. The failed row's
      // buttons re-enable too, but that only helps someone already looking at
      // that exact row.
      setError(`"${alert.title}": ${err.message}`);
    } finally {
      // Only this row's flag. Clearing the whole set here would re-enable the
      // rows still waiting, which is the bug a set exists to stop.
      setPending((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Alerts</h1>
          <p className="muted">
            Returns that are due, and returns that are late. Dismissing one stops it coming
            back tomorrow; recording the filing is what closes it for good.
          </p>
        </div>
      </div>

      <ErrorBanner message={error} onDismiss={() => setError("")} />

      <div className="filters">
        <div className="filter-row">
          {SCOPES.map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={scope === value ? "chip chip-neutral is-active" : "chip chip-neutral"}
              aria-pressed={scope === value}
              onClick={() => {
                setOffset(0);
                setScope(value);
              }}
            >
              {label}
              {value === "open" && openTotal > 0 ? ` (${openTotal})` : ""}
            </button>
          ))}
        </div>
      </div>

      <section className="panel">
        {loading ? (
          <SkeletonPanel lines={5} label="Loading alerts" />
        ) : loadFailed ? (
          // Nothing, rather than the empty state below it. Every one of those
          // sentences asserts something about the backlog — that there is none
          // outstanding, that nothing has been closed — and a load that failed
          // establishes none of them. "Nothing outstanding" over a list that
          // could not be fetched is the one wrong answer this screen can give,
          // because it is the answer a business acts on by doing nothing. The
          // banner above says what happened.
          null
        ) : items.length === 0 ? (
          <p className="muted">
            {scope === "open"
              ? "Nothing outstanding. Alerts appear here a week before each return is due."
              : scope === "closed"
                ? "Nothing closed yet."
                : "No alerts yet. They appear a week before each return is due."}
          </p>
        ) : (
          <ul className="alert-list">
            {items.map((alert) => (
              <AlertRow
                key={alert.id}
                alert={alert}
                busy={pending.has(alert.id)}
                canWrite={canWrite}
                onRead={() => apply(alert, api.markAlertRead)}
                onDismiss={() => apply(alert, api.dismissAlert)}
              />
            ))}
          </ul>
        )}
        {!loading && !loadFailed && (
          <Pager offset={offset} total={total} pageSize={ALERT_PAGE_SIZE} onPage={setOffset} />
        )}
      </section>
    </div>
  );
}
