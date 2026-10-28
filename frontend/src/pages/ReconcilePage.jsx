import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import ErrorBanner from "../components/ErrorBanner";
import ReadOnlyNotice from "../components/ReadOnlyNotice";
import ReportPurchaseButton from "../components/ReportPurchaseButton";
import { SkeletonText } from "../components/Skeleton";
import StatCard from "../components/StatCard";
import TableScroll from "../components/TableScroll";
import ValidationIssues from "../components/ValidationIssues";
import { useAuth } from "../hooks/useAuth";
import { usePageTitle } from "../hooks/usePageTitle";
import { api, isAbortError } from "../lib/api";
import { currentPeriod, dateLabel, periodLabel, rupees } from "../lib/format";
import { GSTR2B_EXTENSIONS, fileError } from "../lib/validate";

const ACCEPT = GSTR2B_EXTENSIONS.join(",");

// A period is re-reconciled as suppliers file late, which is a handful of times
// over the life of a return rather than hundreds. Enough to cover that without
// putting a year of a busy tenant's runs into the header of the page.
const HISTORY_LIMIT = 12;

/** The last 12 filing periods, newest first. */
function recentPeriodOptions(now = new Date()) {
  const options = [];
  for (let i = 0; i < 12; i += 1) {
    const date = new Date(now.getFullYear(), now.getMonth() - i, 1);
    options.push(`${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`);
  }
  return options;
}

/**
 * The months this picker offers, newest first.
 *
 * The last twelve, plus every period that actually has a statement on file,
 * plus whichever one is selected. The three are different sets and each is
 * there for a reason:
 *
 * - A period with a 2B older than a year was unreachable. The runs are kept as
 *   evidence for a reversal raised months later — that is the whole reason
 *   they accumulate — and the screen that holds them could not be pointed at
 *   the period they belong to.
 * - The selected one, because the server decides an import's period from the
 *   file and may hand back a month neither list holds yet. A `<select>` whose
 *   value matches no option renders blank, so the month a user has just
 *   imported into would vanish from the control naming it.
 *
 * String sort, because `YYYY-MM` is zero-padded and so sorts in calendar order.
 */
function periodChoices(imported, selected, now = new Date()) {
  const all = new Set([...recentPeriodOptions(now), ...imported, selected]);
  return [...all].filter(Boolean).sort().reverse();
}

// Each outcome implies a different action, so they are labelled by what the
// user has to do about them rather than by the enum name.
const CATEGORIES = {
  matched: {
    label: "Matched",
    tone: "good",
    help: "Same invoice, same figures. Nothing to do.",
  },
  mismatched: {
    label: "Mismatched",
    tone: "warn",
    help: "Found in GSTR-2B, but the figures differ. Correct the books or ask the supplier to amend.",
  },
  missing_in_2b: {
    label: "Missing in 2B",
    tone: "bad",
    help: "In your books, not in the supplier's GSTR-1. This credit is at risk until they file.",
  },
  missing_in_books: {
    label: "Missing in books",
    tone: "warn",
    help: "The supplier declared it and you have not booked it. Credit you may be entitled to.",
  },
  duplicate: {
    label: "Duplicate",
    tone: "bad",
    help: "Booked more than once. Two claims off one document is what draws a notice.",
  },
};

const CATEGORY_ORDER = [
  "missing_in_2b",
  "mismatched",
  "duplicate",
  "missing_in_books",
  "matched",
];

/**
 * When a run happened, to the minute.
 *
 * The minute is what distinguishes them: a period is re-reconciled when a
 * supplier files, which is often twice in a day, and two rows both labelled
 * "14 May 2026" are two rows nobody can tell apart.
 *
 * `completed_at` is null on a run that queued or failed, and that run is still
 * listed — the row is the only place it can be seen at all — so it falls back
 * to when it was asked for.
 */
function runLabel(item) {
  const stamp = item?.completed_at || item?.created_at;
  if (!stamp) return "an unrecorded time";
  const at = new Date(stamp);
  return `${dateLabel(stamp.slice(0, 10))}, ${at.toTimeString().slice(0, 5)}`;
}

function FindingRow({ finding }) {
  const meta = CATEGORIES[finding.category] ?? { label: finding.category, tone: "neutral" };
  return (
    <tr>
      <td>
        <span className={`chip chip-${meta.tone}`}>{meta.label}</span>
        {/* An invoice booked in another month that this statement declares —
            the supplier catching up on a late filing. It is shown because the
            statement names it, and it moves none of this period's figures,
            because the month that booked it has already counted it. Without a
            marker it was an unexplained extra row: the ITC totals and the
            matched count beside them are the period's own, so a user counting
            rows found one more than every number on the screen. */}
        {finding.carried && (
          <span className="chip chip-neutral" title={finding.note ?? ""}>
            Late filing
          </span>
        )}
      </td>
      <td>
        {finding.invoice_id ? (
          <Link to={`/invoices/${finding.invoice_id}`}>
            {finding.invoice_number || "(no number)"}
          </Link>
        ) : (
          finding.invoice_number || "(no number)"
        )}
      </td>
      <td>
        <div>{finding.supplier_name || "—"}</div>
        <div className="muted small">{finding.supplier_gstin || ""}</div>
      </td>
      <td>{dateLabel(finding.invoice_date)}</td>
      <td className="numeric">{finding.books ? rupees(finding.books.total_tax) : "—"}</td>
      <td className="numeric">{finding.gstr2b ? rupees(finding.gstr2b.total_tax) : "—"}</td>
      <td>
        {finding.differences?.length > 0 ? (
          <ul className="diff-list">
            {finding.differences.map((diff) => (
              <li key={diff.field}>
                <strong>{diff.field.replace(/_/g, " ")}</strong>: {rupees(diff.books)} vs{" "}
                {rupees(diff.gstr2b)}{" "}
                <span className="muted">({rupees(diff.delta)})</span>
              </li>
            ))}
          </ul>
        ) : (
          <span className="muted">{finding.note || ""}</span>
        )}
      </td>
    </tr>
  );
}

export default function ReconcilePage() {
  usePageTitle("Reconcile");
  const { canWrite } = useAuth();
  const [period, setPeriod] = useState(currentPeriod());
  const [imported, setImported] = useState(null);
  const [run, setRun] = useState(null);
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  // Which of the two halves came back unknown rather than empty. A 404 says
  // the period really has no 2B, or really has no run; anything else says only
  // that we did not find out. Both render as a null `imported` / `run`, and
  // the sentences under them are findings about the period rather than
  // captions on the banner — so they need telling apart. Tracked per endpoint
  // because the two fail independently.
  const [unknown, setUnknown] = useState({ imported: false, run: false });
  // Bumped to refetch the period already selected. An import that lands on the
  // month on screen changes no state the load effect depends on, so without
  // this there is nothing for it to react to.
  const [reloadToken, setReloadToken] = useState(0);
  // Past runs for the period, and which one is being read instead of the
  // latest. A period is reconciled again every time a supplier files late and
  // the 2B is regenerated, so "what did this look like in June, before they
  // filed" is the question an ITC reversal turns on months later — and until
  // now every run but the newest was stored and unreachable.
  const [history, setHistory] = useState([]);
  const [historyUnknown, setHistoryUnknown] = useState(false);
  // {id, run} while an earlier run is on screen, null while the latest is.
  const [viewed, setViewed] = useState(null);
  const [historyToken, setHistoryToken] = useState(0);
  // What is wrong with the purchase register itself, before it is matched
  // against anything. Null while it is unknown — which is not the same as a
  // clean register, and is why this is not just an empty issue list. See the
  // panel below for why the difference matters here more than most.
  const [register, setRegister] = useState(null);
  // Which months have a statement at all. The picker offers twelve, of which a
  // new tenant has imported one — and nothing on the control said which.
  const [importedPeriods, setImportedPeriods] = useState([]);
  const inputRef = useRef(null);
  // The month the picker is showing, readable from a callback that has been
  // waiting on the network. `period` closed over at click time is the month the
  // action was *started* from, which is the one thing an in-flight action must
  // not assume is still selected.
  const shownPeriod = useRef(period);

  // The 2B and the last run are independent: a period can have an import and
  // no run, or a run from before the latest import.
  const load = useCallback(async (target, { signal } = {}) => {
    setLoading(true);
    setError("");
    const [importResult, runResult] = await Promise.allSettled([
      api.getImported2b(target, { signal }),
      api.latestReconciliation(target, { signal }),
    ]);

    // A superseded load writes nothing. Both answers describe a period that is
    // no longer the one on screen, and every figure below — ITC eligible, ITC
    // at risk, the findings themselves — is captioned by the period picker
    // rather than by anything in the payload, so applying them puts one
    // month's exposure under another month's name.
    if (signal?.aborted) return;

    setImported(importResult.status === "fulfilled" ? importResult.value : null);
    setRun(runResult.status === "fulfilled" ? runResult.value : null);

    // A 404 from either is the normal empty state — nothing imported yet, or
    // nothing reconciled yet — and neither is worth a banner. Everything else
    // is, and treating the whole rejected branch as the empty state meant a
    // 500, a 503 or an edge that never reached the API rendered as a clean
    // "no GSTR-2B imported for this period", inviting the user to import one
    // they had already imported. The page said the period was empty on the
    // strength of never having found out.
    const unanswered = (result) =>
      result.status === "rejected" && result.reason?.status !== 404;
    // Which is only half of it. The banner says something went wrong; it does
    // not stop the panels below saying the period is empty, and those two
    // sentences are the ones a user acts on — "No GSTR-2B imported yet" comes
    // with instructions to go and fetch one that may already be imported, and
    // "Run the reconciliation" invites a re-run of a run that may exist.
    setUnknown({ imported: unanswered(importResult), run: unanswered(runResult) });

    const failure = [importResult, runResult].find(unanswered);
    // The `||` never fires, and proving it does would mean rejecting with an
    // error this app cannot construct. Every throw in `lib/api.js` carries a
    // written sentence: `refusal` is handed `errorMessage`, which falls back to
    // a non-empty string by its own `|| fallback`; the unreadable-body and
    // unreachable-server throws are literals; and the one rejection with a
    // message we did not write — `AbortError` — is returned on at the
    // `signal?.aborted` check above before it can get here. It stays because
    // the failure it guards against is the one this whole block exists to
    // prevent: a banner that is visibly *there* with nothing written in it says
    // the page broke without saying what to do, and reads as a frozen app
    // rather than a period that could not be loaded.
    if (failure) setError(failure.reason?.message || "Could not load this period.");
    setLoading(false);
  }, []);

  // Responses do not come back in the order they were sent, and stepping
  // through months is how this screen is read. Two requests go out per period,
  // so a single change puts four answers in flight with no guarantee of order.
  // Aborting the superseded pair on the way out of the effect is what keeps
  // the month in the picker and the month in the findings the same month.
  useEffect(() => {
    const controller = new AbortController();
    shownPeriod.current = period;
    // An earlier run of the month being left has nothing to say about the month
    // being arrived at, and every figure it fills in is captioned by the picker.
    setViewed(null);
    load(period, { signal: controller.signal });
    return () => controller.abort();
  }, [load, period, reloadToken]);

  // Its own read, so its own effect: the list is a third thing that can fail on
  // its own, and it is refetched after a run without disturbing the two panels
  // above — reusing the load effect for that would put the whole page back into
  // skeletons a moment after the findings appeared.
  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      try {
        const data = await api.listReconciliations(
          { period, limit: HISTORY_LIMIT },
          { signal: controller.signal },
        );
        setHistory(data.items ?? []);
        setHistoryUnknown(false);
      } catch (err) {
        // A superseded list writes nothing, for the same reason the pair above
        // does not: it is captioned by the picker.
        if (isAbortError(err)) return;
        // Empty and unknown are different answers, and only one of them means
        // "this period has never been reconciled".
        setHistory([]);
        setHistoryUnknown(true);
      }
    })();
    return () => controller.abort();
  }, [period, reloadToken, historyToken]);

  // The purchase register's own problems, which are the ones the matcher
  // cannot tell you about. A supplier GSTIN that does not checksum, or is
  // missing altogether, comes back from the reconciliation as "missing in 2B"
  // — indistinguishable from a supplier who genuinely has not filed, and the
  // two have opposite remedies: one is a field to retype, the other is a
  // phone call. So it is read before the run rather than explained after it.
  //
  // Refetched on `reloadToken` along with the panels above, because an import
  // is not the only thing that bumps it: the invoice list changes under this
  // page as uploads are parsed, and a register checked once on arrival would
  // go on reporting a GSTIN that has since been fixed.
  //
  // Its failure is swallowed, like the history list's. This is a warning about
  // work still to do, not the work itself — a banner saying the register could
  // not be checked would sit above an import and a run that both work.
  useEffect(() => {
    const controller = new AbortController();
    api
      .validateFiling(period, "purchase", { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setRegister(data);
      })
      .catch(() => {
        // Back to unknown rather than to an empty report. "Nothing wrong with
        // your register" is a claim, and this is the branch where we did not
        // find out — asserting it here would send someone chasing a supplier
        // over a GSTIN they had mistyped themselves.
        if (!controller.signal.aborted) setRegister(null);
      });
    return () => controller.abort();
  }, [period, reloadToken]);

  // Marks the picker, and reaches back past its twelve months. A 2B imported
  // more than a year ago had no option to select and so no way back to the
  // runs stored against it — which is precisely the period a reversal raised
  // this November is about.
  //
  // Refetched on `reloadToken` so an import marks its own month straight away.
  // Its failure leaves the picker exactly as it was before this existed: the
  // last twelve months, unmarked, all still selectable.
  useEffect(() => {
    const controller = new AbortController();
    api
      .importedPeriods({ signal: controller.signal })
      .then((data) => {
        // Guarded rather than trusted. Everything this list does is decorate
        // the picker and reach past its twelve months, and it renders through
        // a spread and a `Set` — so a payload that is not an array would take
        // the whole screen down over a marker, on the page where the import
        // and the run live.
        if (!controller.signal.aborted) {
          setImportedPeriods(Array.isArray(data) ? data : []);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setImportedPeriods([]);
      });
    return () => controller.abort();
  }, [reloadToken]);

  async function handleView(item) {
    // The row already carries the counts; what it does not carry is the report,
    // which is the whole reason for opening one.
    setBusy(true);
    setError("");
    try {
      const detail = await api.getReconciliation(item.id);
      if (shownPeriod.current === item.period) setViewed({ id: item.id, run: detail });
    } catch (err) {
      setError(`Could not open the run from ${dateLabel(item.created_at?.slice(0, 10))}: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function handleImport(files) {
    const file = Array.from(files ?? [])[0];
    if (!file) return;

    // The portal hands out the 2B as a zip containing the JSON, and uploading
    // the zip is the single most common mistake here. Catching it in the
    // browser makes the message about the zip rather than a generic 400.
    const invalid = fileError(file, { extensions: GSTR2B_EXTENSIONS });
    if (invalid) {
      setError(invalid);
      if (inputRef.current) inputRef.current.value = "";
      return;
    }

    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api.importGstr2b(file, period);
      setNotice(result.message);
      // The server decides the period from the file, which may not be the one
      // on screen. Follow it rather than showing a stale month — and follow it
      // to whatever the picker says *now*, not to the month the upload was
      // started from. A 2B is a few megabytes over a phone connection and the
      // picker stays live throughout, so stepping to another month mid-upload
      // used to reload the month left behind and caption it with the month in
      // the picker.
      setPeriod(result.period);
      // A no-op `setPeriod` schedules no work, so the refetch is asked for
      // separately. Both land in one render, so the effect still runs once.
      setReloadToken((token) => token + 1);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function handleReconcile() {
    const target = period;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api.reconcile(target);
      // Reconciling is the slowest thing this page does — it walks the whole
      // purchase register against the statement — so it is the request most
      // likely to still be running when someone moves on to another month.
      // The findings, the matched count and both ITC figures are captioned by
      // the picker alone, so a run for a month that is no longer selected has
      // nowhere honest to go: showing it would report one month's credit at
      // risk under another month's name, on the screen whose whole job is
      // deciding which credit is safe to claim.
      //
      // Dropped rather than aborted. The run is already stored by the time it
      // answers, so it is waiting on the period when the user returns to it —
      // the confirmation below names its own month for that reason.
      if (shownPeriod.current === target) {
        setRun(result);
        // The new run is the latest, so an earlier one being read is no longer
        // what the user asked to see.
        setViewed(null);
      }
      // The run just stored is a new row in the list, whichever month is on
      // screen now — so the list is refetched rather than left a run short.
      setHistoryToken((token) => token + 1);
      setNotice(`Reconciled ${periodLabel(target)}`);
    } catch (err) {
      // Named for the same reason the confirmation above names itself. The
      // picker stays live for the whole run, so a failure landing after the
      // user has moved to another month would otherwise read as that month's
      // reconciliation — the one now on screen — refusing to run.
      setError(`Could not reconcile ${periodLabel(target)}: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  // Everything below reads the run being *shown*, which is the latest unless an
  // earlier one has been opened. Named once here rather than at each use: the
  // stat cards, the chips and the findings table have to agree about which run
  // they are describing, and three separate `viewed ?? run` expressions is how
  // one of them ends up describing the other.
  const shown = viewed?.run ?? run;
  const findings = shown?.report?.findings ?? [];
  const visible =
    filter === "all" ? findings : findings.filter((f) => f.category === filter);

  // Counted off the findings themselves rather than read from the run's
  // columns, because these numbers label the list the filter is about to show
  // and the two were counting different things. The server's counters
  // deliberately exclude carried findings — an invoice booked in another month
  // belongs to that month's tally — while the report carries them, so a May
  // statement holding one late-filed April invoice showed "Matched (3)" over a
  // list of four matched rows, and "All" over a total that no category chip
  // added up to. A count beside a filter has to be the number of rows that
  // filter yields; the period's own tally is what the stat cards above report.
  const counts = findings.reduce(
    (tally, finding) => {
      if (finding.category in tally) tally[finding.category] += 1;
      return tally;
    },
    {
      matched: 0,
      mismatched: 0,
      missing_in_2b: 0,
      missing_in_books: 0,
      duplicate: 0,
    },
  );

  // Errors first, then warnings, each keeping the order the server sent — the
  // report comes back in invoice order, which mixes a missing supplier GSTIN
  // in among a dozen missing HSN codes and buries the one row that has to be
  // fixed before anything will match. `sort` is stable, so within a severity
  // the register's own order survives.
  const registerProblems = [...(register?.issues ?? [])].sort(
    (a, b) => (a.severity === "error" ? 0 : 1) - (b.severity === "error" ? 0 : 1),
  );
  const registerErrorCount = register?.error_count ?? 0;
  const onFile = new Set(importedPeriods);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Reconciliation</h1>
          <p className="muted">
            Match your purchase register against GSTR-2B — the statement of what your
            suppliers actually declared.
          </p>
        </div>
        <label className="period-picker">
          <span>Period</span>
          <select value={period} onChange={(e) => setPeriod(e.target.value)}>
            {periodChoices(importedPeriods, period).map((option) => (
              <option key={option} value={option}>
                {periodLabel(option)}
                {/* Said in the option itself rather than as a separate hint.
                    The picker is how someone finds the month their statement
                    is in, and stepping through twelve to look for it is the
                    thing this screen made people do. */}
                {onFile.has(option) ? " · 2B on file" : ""}
              </option>
            ))}
          </select>
        </label>
      </div>

      <ErrorBanner message={error} onDismiss={() => setError("")} />
      {notice && (
        <div className="banner banner-good" role="status">
          {notice}
        </div>
      )}

      <section className="panel">
        <h2>GSTR-2B for {periodLabel(period)}</h2>
        {loading ? (
          <SkeletonText lines={2} label="Loading the GSTR-2B" />
        ) : imported ? (
          <p>
            <strong>{imported.invoice_count}</strong> invoices imported{" "}
            {dateLabel(imported.created_at?.slice(0, 10))} · taxable{" "}
            {rupees(imported.total_taxable_value)} · tax{" "}
            {rupees(
              Number(imported.total_cgst) +
                Number(imported.total_sgst) +
                Number(imported.total_igst) +
                Number(imported.total_cess),
            )}
          </p>
        ) : unknown.imported ? (
          // Nothing. The banner above has said the period could not be loaded,
          // and this sentence is not a caption on it — it is a finding that the
          // period holds no statement, followed by instructions to go to the
          // portal and fetch one. On a period whose 2B is already imported that
          // is a wasted download and a re-import, prompted by a page that never
          // found out either way.
          null
        ) : (
          <p className="muted">
            No GSTR-2B yet — upload the JSON or CSV from the GST portal.
          </p>
        )}

        {/* The only two writes on the screen. Everything below — the findings,
            the run history, the View buttons — is reading, and a viewer keeps
            all of it: what a reconciliation found is exactly what someone
            without the authority to re-run it is here to look at. */}
        <ReadOnlyNotice>
          Ask an owner or an accountant to import GSTR-2B or run a reconciliation.
        </ReadOnlyNotice>

        {canWrite && (
          <div className="button-row">
            <label htmlFor="gstr2b-file" className="btn btn-ghost">
              {imported ? "Replace GSTR-2B" : "Import GSTR-2B"}
            </label>
            <input
              id="gstr2b-file"
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              className="visually-hidden"
              disabled={busy}
              onChange={(e) => handleImport(e.target.files)}
            />
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy || !imported}
              onClick={handleReconcile}
            >
              {busy ? "Working…" : "Run reconciliation"}
            </button>
          </div>
        )}
      </section>

      {/* Guarded on the period as well as on there being a report, so the
          figure on screen is never the last selection's answer arriving late —
          the abort handles the common case, a resolved-then-superseded
          response is what this catches. `register` stays null when the check
          could not be run, and the whole panel is then absent: silence is the
          only honest thing to say about a register nobody managed to read. */}
      {register?.period === period && (
        <section className="panel">
          <h2>Your purchase register</h2>
          {registerProblems.length === 0 ? (
            <p className="muted">
              {register.invoice_count === 0
                ? `No purchase invoices booked for ${periodLabel(period)} yet. Upload them before reconciling — GSTR-2B is matched against your books, so an empty register matches nothing.`
                : `All ${register.invoice_count} purchase invoices carry a supplier GSTIN that checks out and an invoice number. Anything unmatched below is the supplier's side, not yours.`}
            </p>
          ) : (
            <>
              <p className="muted small">
                {/* The count is of errors alone, because an error is by
                    definition a field the portal could not accept — and 2B is
                    generated from what suppliers filed on that same portal.
                    Warnings are listed too, below the errors, but they are not
                    what this sentence is about. */}
                {registerErrorCount > 0 ? (
                  <>
                    <strong>{registerErrorCount}</strong>{" "}
                    {registerErrorCount === 1 ? "problem" : "problems"} in your own books
                    will stop an invoice matching, however diligently the supplier filed.
                    GSTR-2B is matched on the supplier&rsquo;s GSTIN and the invoice
                    number, so a row missing either comes back &ldquo;missing in 2B&rdquo;
                    — which reads as the supplier&rsquo;s fault and is not. Fix these
                    first, then run the reconciliation.
                  </>
                ) : (
                  <>
                    Nothing here will stop an invoice matching, but these are worth a look
                    before you file the credit.
                  </>
                )}
              </p>
              <ValidationIssues
                issues={registerProblems}
                label={`Purchase register problems for ${periodLabel(period)}`}
              />
            </>
          )}
        </section>
      )}

      {shown && (
        <>
          {/* Said plainly, and above the figures rather than beside them. Every
              number under this heading is a past state of the period — an ITC
              at risk that has since been resolved reads exactly like one that
              has not, and it is a figure people act on. */}
          {viewed && (
            <div className="banner banner-neutral" role="status">
              <span>
                Showing the run from{" "}
                <strong>{runLabel(viewed.run)}</strong>, not the latest.
              </span>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setViewed(null)}
              >
                Back to the latest run
              </button>
            </div>
          )}

          <section className="stat-grid">
            <StatCard
              label="ITC eligible"
              value={rupees(shown.itc_eligible)}
              sub="Safe to claim"
              tone="good"
            />
            <StatCard
              label="ITC at risk"
              value={rupees(shown.itc_at_risk)}
              sub="Unfiled or over-claimed"
              tone={Number(shown.itc_at_risk) > 0 ? "bad" : "good"}
            />
            <StatCard
              label="ITC claimed"
              value={rupees(shown.itc_claimed)}
              sub={`${shown.total_invoices} purchase invoices`}
            />
            {/* The run's own counter, not the chip tally below. Both are
                right about different questions: this card is "how much of
                *this period* matched", and its denominator excludes carried
                invoices, so its numerator has to as well — a May run that
                picked up one late-filed April invoice would otherwise read
                "4 / 3". */}
            <StatCard
              label="Matched"
              value={`${shown.matched_count ?? 0} / ${shown.total_invoices}`}
              /* "Last run" is a claim about which run this is, and it stops
                 being true the moment an earlier one is opened. */
              sub={`${viewed ? "Run" : "Last run"} ${dateLabel(shown.completed_at?.slice(0, 10))}`}
              tone={(shown.matched_count ?? 0) === shown.total_invoices ? "good" : "warn"}
            />
          </section>

          {/* Bought per run, so it follows the run on screen — an earlier run
              opened from the history gets its own report. Keyed on the run so
              one run's "already bought" never labels another's button. A
              viewer is not offered it: buying is a write, and the backend
              refuses one from them. */}
          {canWrite && shown.status === "completed" && (
            <ReportPurchaseButton key={shown.id} runId={shown.id} />
          )}

          <section className="panel">
            <h2>Findings</h2>
            <div className="filter-row">
              <button
                type="button"
                className={filter === "all" ? "chip chip-neutral is-active" : "chip chip-neutral"}
                onClick={() => setFilter("all")}
              >
                All ({findings.length})
              </button>
              {CATEGORY_ORDER.map((key) => (
                <button
                  key={key}
                  type="button"
                  className={
                    filter === key
                      ? `chip chip-${CATEGORIES[key].tone} is-active`
                      : `chip chip-${CATEGORIES[key].tone}`
                  }
                  onClick={() => setFilter(key)}
                >
                  {CATEGORIES[key].label} ({counts[key]})
                </button>
              ))}
            </div>

            {filter !== "all" && (
              <p className="muted small">{CATEGORIES[filter]?.help}</p>
            )}

            {visible.length === 0 ? (
              <p className="muted">Nothing in this category.</p>
            ) : (
              <TableScroll label="Reconciliation findings">
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col">Outcome</th>
                      <th scope="col">Invoice</th>
                      <th scope="col">Supplier</th>
                      <th scope="col">Date</th>
                      <th scope="col">Tax (books)</th>
                      <th scope="col">Tax (2B)</th>
                      <th scope="col">Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((finding, index) => (
                      <FindingRow
                        key={`${finding.category}-${finding.invoice_id ?? "x"}-${index}`}
                        finding={finding}
                      />
                    ))}
                  </tbody>
                </table>
              </TableScroll>
            )}
          </section>
        </>
      )}

      {/* `!unknown.run` for the same reason as the panel above: this says the
          period has never been reconciled, and it says so to invite a run. A
          run endpoint that answered 500 leaves that unestablished, and the
          findings, both ITC figures and the matched count all come from the
          run this sentence claims does not exist. */}
      {!run && !unknown.run && !loading && imported && (
        <p className="muted">
          GSTR-2B is loaded. Run the reconciliation to see what matches.
        </p>
      )}

      {/* Runs accumulate rather than overwrite each other, and every one but
          the newest was stored and unreachable. What makes the older ones worth
          keeping is that they are evidence: a credit claimed in June on a
          supplier who had not filed, and the run that said so at the time, is
          the answer to a reversal raised in November.

          Shown only once there is more than one, because a single entry is the
          run already on screen, listed again under a heading calling it
          history. */}
      {(history.length > 1 || historyUnknown) && (
        <section className="panel">
          <h2>Earlier runs</h2>
          {historyUnknown ? (
            <p className="muted">
              Could not load the earlier runs for {periodLabel(period)}.
            </p>
          ) : (
            <>
              <p className="muted small">
                Each run is what GSTR-2B said at the time. Suppliers file late and
                the statement is regenerated, so a period is reconciled more than
                once and the figures move.
              </p>
              <TableScroll label="Earlier reconciliation runs">
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col">Run</th>
                      <th scope="col">Matched</th>
                      <th scope="col">ITC at risk</th>
                      <th scope="col">ITC eligible</th>
                      <th scope="col" />
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((item, index) => {
                      // The newest row is the one the page shows by default, so
                      // it is marked rather than offered as something to open.
                      const isLatest = index === 0;
                      const isShown = viewed ? viewed.id === item.id : isLatest;
                      return (
                        <tr key={item.id}>
                          <td>
                            {runLabel(item)}
                            {isLatest && (
                              <span className="chip chip-neutral"> Latest</span>
                            )}
                          </td>
                          <td>
                            {item.matched_count ?? 0} / {item.total_invoices}
                          </td>
                          <td className="numeric">{rupees(item.itc_at_risk)}</td>
                          <td className="numeric">{rupees(item.itc_eligible)}</td>
                          <td>
                            {isShown ? (
                              <span className="muted small">Showing</span>
                            ) : (
                              <button
                                type="button"
                                className="btn btn-ghost"
                                disabled={busy}
                                onClick={() =>
                                  isLatest ? setViewed(null) : handleView(item)
                                }
                              >
                                View
                                <span className="visually-hidden">
                                  {" "}
                                  the run from {runLabel(item)}
                                </span>
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </TableScroll>
            </>
          )}
        </section>
      )}
    </div>
  );
}
