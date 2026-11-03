import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import ErrorBanner from "../components/ErrorBanner";
import ReadOnlyNotice from "../components/ReadOnlyNotice";
import { useAuth } from "../hooks/useAuth";
import { usePageTitle } from "../hooks/usePageTitle";
import { api } from "../lib/api";
import { saveBlob } from "../lib/download";
import "./practice.css";

const label = (name) => name.replaceAll("_", " ");
export default function PurchaseImportPage() {
  usePageTitle("Import purchase register");
  const { canWrite } = useAuth();
  const [file, setFile] = useState(null);
  const [mapping, setMapping] = useState({});
  const [dateFormat, setDateFormat] = useState("DMY");
  const [templates, setTemplates] = useState([]);
  const [preview, setPreview] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [skipInvalid, setSkipInvalid] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState(0);
  useEffect(() => {
    let live = true;
    api
      .registerMappings()
      .then((data) => {
        if (live) setTemplates(data.items);
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, []);
  const change = () => {
    setDirty(true);
    setResult(null);
  };
  const inspect = async () => {
    if (!file) return;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const data = await api.previewRegister(file, mapping, dateFormat);
      setPreview(data);
      setMapping(data.mapping);
      setDirty(false);
      setSkipInvalid(false);
      setPage(0);
    } catch (e) {
      setError(e.message);
      setDirty(true);
    } finally {
      setBusy(false);
    }
  };
  const commit = async () => {
    setBusy(true);
    setError("");
    try {
      setResult(
        await api.commitRegister(preview.id, {
          skip_invalid: skipInvalid,
          save_mapping_name: saveName.trim() || null,
        }),
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const downloadTemplate = () =>
    saveBlob(
      new Blob(
        [
          "Invoice Number,Invoice Date,Supplier GSTIN,Supplier Name,Taxable Value,CGST,SGST,IGST,Cess,Total Value,Place of Supply,ITC Eligible,Reverse Charge\r\n",
        ],
        { type: "text/csv" },
      ),
      "purchase-register-template.csv",
    );
  return (
    <div className="practice-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Purchase data</p>
          <h1>Import a purchase register</h1>
          <p className="muted">
            Map your columns once. Check every invoice before it enters your
            books.
          </p>
        </div>
        <button className="btn btn-ghost" onClick={downloadTemplate}>
          Download CSV template
        </button>
      </div>
      <ReadOnlyNotice />
      <ErrorBanner message={error} onDismiss={() => setError("")} />
      <section className="panel">
        <h2>1. Choose your file</h2>
        <p>
          Use an invoice-level CSV or a single-sheet XLSX, up to 5 MB and 2,000
          rows. Combine multiple line items into one row per invoice. Credit
          notes and formulas need separate handling.
        </p>
        <div className="practice-grid">
          <label>
            Purchase register
            <input
              type="file"
              accept=".csv,.xlsx"
              disabled={!canWrite || busy}
              onChange={(e) => {
                setFile(e.target.files?.[0] || null);
                setPreview(null);
                setMapping({});
                setResult(null);
                setDirty(true);
              }}
            />
          </label>
          <label>
            Date order
            <select
              value={dateFormat}
              disabled={busy}
              onChange={(e) => {
                setDateFormat(e.target.value);
                change();
              }}
            >
              <option value="DMY">Day / month / year</option>
              <option value="MDY">Month / day / year</option>
              <option value="YMD">Year / month / day</option>
            </select>
          </label>
          {templates.length > 0 && (
            <label>
              Saved mapping
              <select
                defaultValue=""
                disabled={busy || !file}
                onChange={(e) => {
                  const t = templates.find(
                    (x) => x.id === Number(e.target.value),
                  );
                  if (t) {
                    setMapping(t.mapping);
                    setDateFormat(t.date_format);
                    change();
                  }
                }}
              >
                <option value="">Choose a saved mapping</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        <p className="practice-note">
          Invoice numbers and GSTINs should be text cells. Blank ITC eligibility
          defaults to “No”; mark eligibility only after checking it. Imports
          preserve the existing monthly invoice allowance.
        </p>
        <button
          className="btn btn-primary"
          disabled={!canWrite || !file || busy}
          onClick={inspect}
        >
          {busy ? "Working…" : preview ? "Refresh preview" : "Preview register"}
        </button>
      </section>
      {preview && (
        <>
          <section className="panel">
            <h2>2. Match your columns</h2>
            <div className="practice-grid">
              {preview.fields.map((field) => (
                <label key={field}>
                  {label(field)}
                  {preview.required.includes(field) ? " *" : ""}
                  <select
                    value={mapping[field] || ""}
                    disabled={busy || Boolean(result)}
                    onChange={(e) => {
                      setMapping({ ...mapping, [field]: e.target.value });
                      change();
                    }}
                  >
                    <option value="">Not mapped</option>
                    {preview.headers.map((header) => (
                      <option key={header} value={header}>
                        {header}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
            {dirty && (
              <p role="status" className="practice-note">
                Mapping changed. Refresh the preview before importing.
              </p>
            )}
          </section>
          <section className="panel">
            <h2>3. Check and import</h2>
            <div className="practice-stats">
              <div className="practice-stat">
                <strong>{preview.ready}</strong>ready to import
              </div>
              <div className="practice-stat">
                <strong>{preview.invalid}</strong>rows to correct
              </div>
              <div className="practice-stat">
                <strong>{preview.duplicates}</strong>already in your books
              </div>
            </div>
            <div className="practice-table">
              <table>
                <thead>
                  <tr>
                    <th>Row</th>
                    <th>Invoice</th>
                    <th>Supplier GSTIN</th>
                    <th>Total</th>
                    <th>Preview result</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.slice(page * 50, (page + 1) * 50).map((row) => (
                    <tr key={row.row}>
                      <td>{row.row}</td>
                      <td>{row.data.invoice_number || "—"}</td>
                      <td>{row.data.supplier_gstin || "—"}</td>
                      <td>{row.data.total_value || "—"}</td>
                      <td className={row.errors.length ? "practice-error" : ""}>
                        {row.errors.length
                          ? row.errors.join(" ")
                          : row.duplicate
                            ? "Duplicate — will be skipped"
                            : "Ready"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {preview.rows.length > 50 && (
              <div className="practice-actions">
                <button
                  className="btn btn-ghost"
                  disabled={!page}
                  onClick={() => setPage(page - 1)}
                >
                  Previous rows
                </button>
                <span>
                  Page {page + 1} of {Math.ceil(preview.rows.length / 50)}
                </span>
                <button
                  className="btn btn-ghost"
                  disabled={(page + 1) * 50 >= preview.rows.length}
                  onClick={() => setPage(page + 1)}
                >
                  Next rows
                </button>
              </div>
            )}
            {!result && (
              <>
                <label className="practice-check">
                  <input
                    type="checkbox"
                    checked={skipInvalid}
                    disabled={busy || !preview.invalid}
                    onChange={(e) => setSkipInvalid(e.target.checked)}
                  />
                  Import valid rows only; I will correct the {preview.invalid}{" "}
                  invalid rows separately.
                </label>
                <label>
                  Save this mapping as (optional)
                  <input
                    value={saveName}
                    maxLength={80}
                    disabled={busy}
                    placeholder="For example, monthly Tally purchase export"
                    onChange={(e) => setSaveName(e.target.value)}
                  />
                </label>
                <div className="practice-actions">
                  <button
                    className="btn btn-primary"
                    disabled={
                      !canWrite ||
                      busy ||
                      dirty ||
                      !preview.ready ||
                      (preview.invalid > 0 && !skipInvalid)
                    }
                    onClick={commit}
                  >
                    Import {preview.ready} invoices
                  </button>
                  <span className="muted">
                    Previews expire after 30 minutes. Duplicate checks run again
                    on import.
                  </span>
                </div>
              </>
            )}
            {result && (
              <div className="practice-note" role="status">
                <strong>{result.imported} invoices imported.</strong>{" "}
                {result.duplicates_skipped} duplicates skipped;{" "}
                {result.invalid_skipped} invalid rows skipped.
                <div className="practice-actions">
                  <Link className="btn btn-primary" to="/reconcile">
                    Import GSTR-2B and reconcile
                  </Link>
                  <Link to="/invoices">Review invoices</Link>
                </div>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
