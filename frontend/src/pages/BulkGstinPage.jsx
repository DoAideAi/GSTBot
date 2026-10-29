import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import ErrorBanner from "../components/ErrorBanner";
import TableScroll from "../components/TableScroll";
import { api } from "../lib/api";
import { track } from "../lib/track";
import { saveBlob } from "../lib/download";

export const MAX_GSTINS = 100;

/**
 * The GSTINs pasted into the box: split on lines, commas, semicolons, tabs or
 * spaces (a column copied from a spreadsheet, a comma list from an email),
 * upper-cased, with repeats dropped so a supplier listed twice is checked once.
 */
export function parseGstins(text) {
  const seen = new Set();
  const out = [];
  for (const raw of text.split(/[\s,;]+/)) {
    const gstin = raw.trim().toUpperCase();
    if (gstin && !seen.has(gstin)) {
      seen.add(gstin);
      out.push(gstin);
    }
  }
  return out;
}

function csvCell(value) {
  const text = value == null ? "" : String(value);
  // Quoted when it has to be, and a leading = + - @ is neutralised: these
  // results are opened in a spreadsheet, and an echoed input is the visitor's.
  const safe = /^[=+\-@]/.test(text) ? `'${text}` : text;
  return /[",\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

export function resultsCsv(results) {
  const rows = [["GSTIN", "Valid", "State", "State code", "PAN", "Reason"]];
  for (const r of results) {
    rows.push([r.gstin, r.valid ? "Yes" : "No", r.state_name, r.state_code, r.pan, r.error]);
  }
  return rows.map((row) => row.map(csvCell).join(",")).join("\r\n") + "\r\n";
}

/**
 * Bulk GSTIN validation — the paid feature the pricing page sells, which had
 * an API (`POST /meta/gstin/bulk`) and no screen, so a subscriber could only
 * use it by calling the API by hand.
 */
export default function BulkGstinPage() {
  const [text, setText] = useState("");
  const [response, setResponse] = useState(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [needsPlan, setNeedsPlan] = useState(false);
  const [filter, setFilter] = useState("all");

  const gstins = useMemo(() => parseGstins(text), [text]);
  const tooMany = gstins.length > MAX_GSTINS;

  const submit = async (e) => {
    e.preventDefault();
    if (gstins.length === 0 || tooMany || checking) return;
    setChecking(true);
    setError("");
    setResponse(null);
    try {
      setResponse(await api.validateGstinBulk(gstins));
      track("bulk_gstin_check", { count: gstins.length });
      setFilter("all");
    } catch (err) {
      if (err?.status === 403) setNeedsPlan(true);
      else setError(err?.message || "The GSTINs could not be checked. Try again.");
    } finally {
      setChecking(false);
    }
  };

  const shown =
    response?.results.filter((r) =>
      filter === "all" ? true : filter === "valid" ? r.valid : !r.valid,
    ) ?? [];

  const download = () => {
    saveBlob(
      new Blob([resultsCsv(response.results)], { type: "text/csv;charset=utf-8" }),
      "gstin-validation.csv",
    );
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Bulk GSTIN validation</h1>
          <p className="muted">
            Check up to {MAX_GSTINS} supplier GSTINs at once — paste a column from a spreadsheet,
            or a list separated by commas or new lines.
          </p>
        </div>
      </div>

      <ErrorBanner message={error} onDismiss={() => setError("")} />

      {needsPlan ? (
        <section className="panel">
          <h2>Bulk validation is part of the paid plans</h2>
          <p>
            Checking one GSTIN at a time stays free on the{" "}
            <Link to="/gstin-validator">GSTIN validator</Link>. Validating a whole supplier list in
            one go is included from ₹499 a month.
          </p>
          <Link className="btn btn-primary" to="/pricing">
            See plans
          </Link>
        </section>
      ) : (
        <form className="panel" onSubmit={submit} aria-busy={checking}>
          <label htmlFor="bulk-gstins" className="calc-label">
            GSTINs
          </label>
          <textarea
            id="bulk-gstins"
            className="calc-input bulk-gstin-input"
            rows={8}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={"27AAPFU0939F1ZV\n29AAACB1234C1Z5"}
            spellCheck={false}
            aria-describedby="bulk-gstin-count"
            aria-invalid={tooMany || undefined}
          />
          <p
            id="bulk-gstin-count"
            className={tooMany ? "field-error" : "muted"}
            role={tooMany ? "alert" : undefined}
          >
            {tooMany
              ? `${gstins.length} GSTINs — at most ${MAX_GSTINS} at a time. Split the list and check the rest next.`
              : `${gstins.length} of ${MAX_GSTINS}${gstins.length ? " (repeats counted once)" : ""}`}
          </p>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={gstins.length === 0 || tooMany || checking}
          >
            {checking
              ? "Checking…"
              : gstins.length
                ? `Validate ${gstins.length} GSTIN${gstins.length === 1 ? "" : "s"}`
                : "Validate GSTINs"}
          </button>
        </form>
      )}

      <div aria-live="polite">
        {response && (
          <section className="panel">
            <div className="bulk-gstin-summary">
              <p>
                <strong>{response.valid_count}</strong> valid,{" "}
                <strong>{response.invalid_count}</strong> invalid, of {response.total} checked.
              </p>
              <div className="filter-row">
                {[
                  ["all", "All"],
                  ["invalid", "Invalid only"],
                  ["valid", "Valid only"],
                ].map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    className={filter === value ? "chip chip-neutral is-active" : "chip chip-neutral"}
                    aria-pressed={filter === value}
                    onClick={() => setFilter(value)}
                  >
                    {label}
                  </button>
                ))}
                <button type="button" className="btn btn-ghost" onClick={download}>
                  Download CSV
                </button>
              </div>
            </div>

            <TableScroll label="Validation results">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">GSTIN</th>
                    <th scope="col">Result</th>
                    <th scope="col">State</th>
                    <th scope="col">PAN</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r) => (
                    <tr key={r.gstin}>
                      <td className="mono">{r.gstin}</td>
                      <td>
                        {r.valid ? (
                          <span className="lookup-badge lookup-valid">Valid</span>
                        ) : (
                          <>
                            <span className="lookup-badge lookup-invalid">Invalid</span>
                            {r.error && <div className="muted">{r.error}</div>}
                          </>
                        )}
                      </td>
                      <td>{r.state_name ? `${r.state_name} (${r.state_code})` : "—"}</td>
                      <td className="mono">{r.pan ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
            {shown.length === 0 && <p className="muted">None in this view.</p>}
          </section>
        )}
      </div>
    </div>
  );
}
