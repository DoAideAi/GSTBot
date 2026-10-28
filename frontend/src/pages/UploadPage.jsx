import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import ErrorBanner from "../components/ErrorBanner";
import ReadOnlyNotice from "../components/ReadOnlyNotice";
import { Spinner } from "../components/Skeleton";
import { useAuth } from "../hooks/useAuth";
import { usePageTitle } from "../hooks/usePageTitle";
import { api } from "../lib/api";
import { track } from "../lib/track";
import { dateLabel, rupees } from "../lib/format";
import { INVOICE_EXTENSIONS, MAX_UPLOAD_MB, partitionFiles } from "../lib/validate";

const ACCEPT = INVOICE_EXTENSIONS.join(",");

// How many files ride in one request.
//
// The server takes fifty. Ten is chosen against the progress line rather than
// against the server: it can only move between requests, and a batch of fifty
// is a long time for a page to say nothing while someone watches a folder of
// scans upload.
const BULK_CHUNK = 10;

/** One row per file, from the outcome the server reported for that file. */
function toRows(items) {
  return items.map((item) =>
    item.accepted
      ? { filename: item.filename, status: "ok", invoice: item.invoice }
      : { filename: item.filename, status: "error", error: item.error },
  );
}

// The refusals that stop a batch rather than being carried to the next file.
// Both are answers about the account rather than about the document, so every
// file after this one gets the same one — which makes carrying on thirty round
// trips that cannot succeed, burying the one thing the user needs to read under
// thirty identical copies of it.
//
// 402 is the monthly allowance, and it does not come back partway through a
// batch. 429 is the per-minute upload ceiling, where carrying on is worse than
// merely futile: the limiter counts every request it receives, including the
// ones it refuses, so the rest of the batch spends the budget that would have
// let it through and holds the window open while it does. The ceiling is 60 a
// minute and the loop below is a tight sequential one, so a drop of more than
// sixty invoices reliably failed its own tail — and those files are exactly the
// ones that would have gone through had the batch waited instead of hammering.
//
// Unlike the allowance, this one comes good on its own, which is why the banner
// says to drop them again rather than to go and buy something. The failing
// row already carries the server's own message, which names the seconds.
const HALTING = {
  402: {
    row: "Not uploaded — the monthly allowance ran out before this file.",
    banner: (count) =>
      `The monthly allowance ran out. ${count} file(s) were not uploaded. ` +
      "Upgrade the plan or try again next month.",
  },
  429: {
    row: "Not uploaded — the upload rate limit was reached before this file.",
    banner: (count) =>
      `The upload rate limit was reached. ${count} file(s) were not uploaded. ` +
      "Wait a moment, then drop them again.",
  },
};

/** One row per file, so a 40-file batch reports per document rather than as a whole. */
function ResultRow({ result }) {
  const { filename, status, invoice, error } = result;

  if (status === "error") {
    return (
      <li className="result-row is-error">
        <span className="result-name">{filename}</span>
        <span className="result-detail">{error}</span>
      </li>
    );
  }

  const warnings = invoice.warnings ?? [];
  return (
    <li className={warnings.length ? "result-row is-warn" : "result-row is-ok"}>
      <span className="result-name">{filename}</span>
      <span className="result-detail">
        {invoice.invoice_number ? <strong>{invoice.invoice_number}</strong> : "No number found"}
        {invoice.counterparty_gstin ? ` · ${invoice.counterparty_gstin}` : ""}
        {invoice.invoice_date ? ` · ${dateLabel(invoice.invoice_date)}` : ""}
        {/* The derived value, not the raw column — an invoice whose total was
            printed as a bare "Total:" leaves that column at zero, and this row
            is the first thing anyone sees after an upload. */}
        {` · ${rupees(invoice.invoice_value)}`}
      </span>
      {warnings.length > 0 && (
        <ul className="result-warnings">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
      <Link to={`/invoices/${invoice.id}`} className="result-link">
        Review
      </Link>
    </li>
  );
}

export default function UploadPage() {
  usePageTitle("Upload");
  const { canWrite } = useAuth();
  const [invoiceType, setInvoiceType] = useState(() => {
    try { return localStorage.getItem("upload_type") || "purchase"; }
    catch { return "purchase"; }
  });
  const [results, setResults] = useState([]);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  // {done, total, count} while a batch is in flight, null otherwise.
  const [progress, setProgress] = useState(null);
  const inputRef = useRef(null);

  // Derived rather than a second flag kept in step by hand. The two were
  // separate state, set and cleared together on the same line every time, and
  // "extracting, but with nothing to say about how far" was a fourth state the
  // pair could spell but the loop below could never produce — so the spinner
  // carried a caption no run of this page could ever show.
  const busy = progress !== null;

  async function uploadFiles(files) {
    const list = Array.from(files ?? []);
    if (list.length === 0) return;

    // One batch at a time. The file picker says so by being `disabled` while a
    // batch runs; the dropzone had no such guard, so a second drop started a
    // second loop alongside the first.
    //
    // That breaks the thing the loop below is deliberately sequential for:
    // each upload costs a model call and the free tier rate-limits a burst, so
    // two batches running at once is how forty invoices become forty
    // heuristic-only extractions — the exact outcome the sequencing exists to
    // avoid. It also left the page lying about itself, because whichever loop
    // finished first cleared `busy` and took the spinner down while the other
    // was still uploading.
    //
    // Refused out loud rather than ignored: a dropped batch that simply does
    // nothing is indistinguishable from a broken dropzone.
    if (busy) {
      setError("Still extracting the last batch. Wait for it to finish, then drop these.");
      return;
    }

    // Checked here rather than left to the server so an oversized scan is
    // refused before it is read off disk and pushed over a phone connection.
    // A rejected file is reported in the same result list as a failed one:
    // dropping it silently is how a 40-file batch quietly becomes 38.
    const { accepted, rejected } = partitionFiles(list);
    if (rejected.length > 0) {
      setResults((prev) => [
        ...rejected.map(({ file, error: reason }) => ({
          filename: file.name,
          status: "error",
          error: reason,
        })),
        ...prev,
      ]);
    }
    if (accepted.length === 0) {
      if (inputRef.current) inputRef.current.value = "";
      return;
    }

    setError("");

    // Sent as batches rather than one request per file.
    //
    // The server runs the same checks on each file and answers with one
    // outcome per file, so nothing about the per-document reporting changes.
    // What changes is the arithmetic against the upload ceiling, which counts
    // requests: a 90-file drop is nine of them instead of ninety. Ninety
    // sequential uploads reliably spent the ceiling partway through and then
    // refused their own tail — and the files that hit the refusal were exactly
    // the ones that would have gone through had the batch not spent the budget
    // hammering the limiter with the first sixty.
    const groups = [];
    for (let start = 0; start < accepted.length; start += BULK_CHUNK) {
      groups.push(accepted.slice(start, start + BULK_CHUNK));
    }

    let done = 0;
    for (const group of groups) {
      setProgress({ done, total: accepted.length, count: group.length });
      try {
        const response = await api.bulkUploadInvoices(group, invoiceType);
        // Counts, never filenames: a file is named for the supplier on it.
        track("invoice_upload", {
          invoice_type: invoiceType,
          files: group.length,
          accepted: (response.items ?? []).filter((item) => item.accepted).length,
        });
        // Reversed on the way in, because the list reads newest-first and the
        // server answers in the order the files were sent.
        setResults((prev) => [...toRows(response.items ?? []).reverse(), ...prev]);
      } catch (err) {
        track("invoice_upload_failed", { files: group.length, status: err.status ?? 0 });
        // The whole request failed, so no file in it has an outcome of its own.
        setResults((prev) => [
          ...group
            .map((file) => ({ filename: file.name, status: "error", error: err.message }))
            .reverse(),
          ...prev,
        ]);

        // An allowance that is spent, or a rate limit that is reached, is an
        // answer about the account rather than about these documents — so every
        // remaining file gets the same one. See HALTING above for why each of
        // the two stops the batch.
        //
        // Stopped rather than silently skipped: the files that were not
        // attempted are listed as such, because a batch that quietly shrinks
        // from forty to twelve is how an invoice goes missing from a return.
        const halt = HALTING[err.status];
        if (halt) {
          const remaining = accepted.slice(done + group.length);
          // The banner says only what the rows cannot: how much of the batch
          // never went. Repeating the server's message here as well would put
          // it on screen twice for a single-file upload, where the row already
          // carries it in full.
          if (remaining.length > 0) {
            setResults((prev) => [
              ...remaining.map((skipped) => ({
                filename: skipped.name,
                status: "error",
                error: halt.row,
              })),
              ...prev,
            ]);
            setError(halt.banner(remaining.length));
          }
          break;
        }
      }
      done += group.length;
    }
    setProgress(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  function handleDrop(event) {
    event.preventDefault();
    setDragging(false);
    uploadFiles(event.dataTransfer.files);
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Upload invoices</h1>
          <p className="muted">
            PDF, photo, CSV or Excel. Fields are extracted automatically; anything unclear is
            flagged for review rather than dropped.
          </p>
        </div>
      </div>

      <ErrorBanner message={error} onDismiss={() => setError("")} />

      {/* Everything below this line is the write. A viewer gets the notice in
          place of the whole form rather than a dropzone that answers 403 on
          drop — the page's only purpose is uploading, so there is no read-only
          version of it to fall back to. */}
      <ReadOnlyNotice>Ask an owner or an accountant to upload invoices.</ReadOnlyNotice>

      {!canWrite ? null : (
        <>
          {/* Locked while a batch runs, like the file picker beside it.
              `uploadFiles` reads the type once, at the top, and the loop under it
              is deliberately sequential — so a batch is uploaded under the type it
              was started with, and forty invoices take minutes to get through.
              Left live, the radio moved while the loop went on sending the old
              value: the screen said Sales and the remaining thirty files were still
              being booked as purchases.

              Which is the direction that costs money. A sales invoice booked as a
              purchase claims input credit on the business's own output tax — an
              over-claim with interest and a penalty on it — and nothing downstream
              re-reads the document to catch it, because every screen shows the type
              that was stored.

              Disabled rather than made to take effect mid-batch: splitting one drop
              across two types by how fast the user clicked is not a thing anyone
              can predict, and the honest unit here is the batch. The legend says so
              while it is held. */}
          <fieldset className="type-toggle" disabled={busy}>
            <legend>
              Invoice type
              {busy && <span className="muted small"> · locked until the batch finishes</span>}
            </legend>
            {[
              { value: "purchase", label: "Purchase (claim ITC)" },
              { value: "sales", label: "Sales (feeds GSTR-1)" },
            ].map((option) => (
              <label key={option.value}>
                <input
                  type="radio"
                  name="invoice_type"
                  value={option.value}
                  checked={invoiceType === option.value}
                  onChange={(e) => {
                    setInvoiceType(e.target.value);
                    try { localStorage.setItem("upload_type", e.target.value); }
                    catch { /* quota or private browsing */ }
                  }}
                />
                {option.label}
              </label>
            ))}
          </fieldset>

          <div
            className={dragging ? "dropzone is-dragging" : "dropzone"}
            onDragOver={(e) => {
              e.preventDefault();
              // Not while a batch is running: highlighting invites a drop that is
              // about to be refused.
              if (!busy) setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
          >
            <p>Drag invoices here, or</p>
            <label htmlFor="invoice-file" className="btn btn-primary">
              Choose files
            </label>
            <input
              id="invoice-file"
              ref={inputRef}
              type="file"
              multiple
              accept={ACCEPT}
              className="visually-hidden"
              disabled={busy}
              onChange={(e) => uploadFiles(e.target.files)}
            />
            <p className="muted small">
              Up to {MAX_UPLOAD_MB} MB per file · {INVOICE_EXTENSIONS.join(" ")}
            </p>
          </div>
        </>
      )}

      {progress && (
        <p className="muted upload-progress" role="status">
          <Spinner label="Extracting" />
          {/* A range, because a request now carries several files and the line
              can only move between requests — naming one file of the ten in
              flight would be picking one at random and calling it the slow one. */}
          {progress.count === 1
            ? `Extracting ${progress.done + 1} of ${progress.total}`
            : `Extracting ${progress.done + 1}–${progress.done + progress.count} of ${progress.total}`}
        </p>
      )}

      {results.length > 0 && (
        <section className="panel">
          <h2>Results</h2>
          <ul className="result-list">
            {results.map((result, index) => (
              <ResultRow key={`${result.filename}-${index}`} result={result} />
            ))}
          </ul>
          {!busy && (
            <div className="button-row" style={{ marginTop: "1rem" }}>
              <Link to="/invoices?status=parsed" className="btn btn-primary">
                Review uploaded invoices
              </Link>
              {invoiceType === "purchase" && (
                <Link to="/reconcile" className="btn btn-ghost">
                  Reconcile with GSTR-2B
                </Link>
              )}
              {invoiceType === "sales" && (
                <Link to="/filing" className="btn btn-ghost">
                  Prepare GSTR-1
                </Link>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
