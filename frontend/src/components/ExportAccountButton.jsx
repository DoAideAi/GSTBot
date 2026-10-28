import { useState } from "react";
import { useAuth } from "../hooks/useAuth";
import { api } from "../lib/api";

/**
 * The business's whole account, downloaded as one file.
 *
 * Only the owner sees it: the export holds every login's email and the whole
 * of the books, and the API refuses anyone else — offering a button that can
 * only answer 403 would be a dead end.
 */
export default function ExportAccountButton() {
  const { user } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (user?.active_role !== "owner") return null;

  async function handleClick() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const { blob, filename } = await api.exportAccount();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(`Export failed: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        className="btn btn-ghost"
        onClick={handleClick}
        disabled={busy}
        aria-busy={busy}
        title="Download everything held about this business as one JSON file"
      >
        {busy ? "Exporting…" : "Export data"}
      </button>
      {error && (
        <span className="small" role="alert">
          {error}
        </span>
      )}
    </>
  );
}
