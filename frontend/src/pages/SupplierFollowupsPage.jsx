import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ErrorBanner from "../components/ErrorBanner";
import { usePageTitle } from "../hooks/usePageTitle";
import { api, isAbortError } from "../lib/api";
import { saveBlob } from "../lib/download";
import { periodLabel, rupees } from "../lib/format";
import "./practice.css";
import "./supplier-followups.css";

const pretty = (value) => value.replaceAll("_", " ");

export default function SupplierFollowupsPage() {
  usePageTitle("Supplier follow-ups");
  const { runId } = useParams();
  const [data, setData] = useState(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const load = useCallback((signal) => api.supplierFollowups(runId, { signal }).then(setData), [runId]);
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).catch((e) => { if (!isAbortError(e)) setError(e.message); });
    return () => controller.abort();
  }, [load]);
  async function perform(fn) {
    setBusy(true); setError(""); setNotice("");
    try { await fn(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function prepare(gstin) {
    setDraft(null);
    await perform(async () => setDraft(await api.supplierDraft(runId, gstin)));
  }
  async function copyDraft() {
    await perform(async () => {
      if (!navigator.clipboard?.writeText) throw new Error("Select and copy the subject and message below. Clipboard access is unavailable in this browser.");
      try { await navigator.clipboard.writeText(`Subject: ${draft.subject}\n\n${draft.body}`); }
      catch { throw new Error("Clipboard access was refused. Select and copy the subject and message below."); }
      setNotice("Draft copied. Review the recipient and attach the downloaded invoice list in your email or messaging app.");
    });
  }
  const groups = (data?.suppliers || []).filter((g) => `${g.name} ${g.gstin}`.toLowerCase().includes(search.toLowerCase()));
  return <div className="practice-page followups-page">
    <div className="page-heading"><div><p className="eyebrow">From exception to action</p><h1>Supplier follow-ups</h1>
      <p className="muted">{data ? `${periodLabel(data.period)} · Run ${data.run_id}` : "Loading supplier queue…"}</p></div>
      <Link className="btn btn-ghost" to={`/review/${runId}`}>Back to report review</Link></div>
    <ErrorBanner message={error} onDismiss={() => setError("")} />
    {notice && <p className="practice-note" role="status">{notice}</p>}
    {data && <>
      <section className="panel"><h2>A clear invoice list for each supplier</h2>
        <p>Missing-in-2B and mismatched findings appear here until resolved. Other findings appear when an accountant marks them for follow-up.</p>
        <p className="muted">Tax differences help prioritize review; they are not confirmed recoverable credit. Drafts and downloads do not send messages or resolve findings.</p>
        <div className="practice-stats"><span><strong>{data.suppliers.length}</strong> suppliers</span><span><strong>{data.total}</strong> outstanding findings</span></div>
        {data.unassigned > 0 && <p className="practice-error">{data.unassigned} findings need a valid supplier GSTIN. Check their source data in report review.</p>}
        {data.stale && <p className="practice-error" role="alert">This run is historical or its source data changed. Reconcile again before preparing messages or invoice lists. <Link to={`/reconcile?period=${data.period}`}>Open Reconcile</Link></p>}
        <div className="practice-actions"><label>Find a supplier<input type="search" placeholder="Name or GSTIN" value={search} onChange={(e) => { setSearch(e.target.value); setPage(0); }} /></label>
          <button className="btn btn-ghost" disabled={busy} onClick={() => perform(async () => { setDraft(null); setPage(0); await load(); })}>Refresh findings</button></div>
      </section>
      {draft && <section className="panel followup-draft" aria-label="Supplier message draft">
        <div className="page-heading"><div><p className="eyebrow">Review before sharing</p><h2>Your message draft</h2></div><button className="btn btn-ghost" onClick={() => setDraft(null)} disabled={busy}>Close draft</button></div>
        <p>{draft.gstin} · {draft.count} findings. Add the correct recipient in your own messaging app.</p>
        <label htmlFor="supplier-subject">Subject</label>
        <input id="supplier-subject" autoFocus value={draft.subject} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} />
        <label htmlFor="supplier-message">Message</label>
        <textarea id="supplier-message" rows={12} value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
        <div className="practice-actions"><button className="btn btn-primary" disabled={busy || data.stale} onClick={copyDraft}>Copy draft</button>
          <button className="btn btn-ghost" disabled={busy || data.stale} onClick={() => perform(async () => {
            const file = await api.exportSupplierInvoices(runId, draft.gstin, draft.fingerprint); saveBlob(file.blob, file.filename);
            setNotice("Invoice list downloaded. Attach it yourself when sharing; no message has been sent.");
          })}>Download supplier invoice list</button></div>
        <p className="practice-footer">The invoice list includes only this supplier’s outstanding invoice facts. Internal review notes stay in your workspace.</p>
      </section>}
      {!groups.length && <section className="panel"><h2>{search ? "No matching suppliers" : "No supplier follow-ups ready"}</h2>
        <p>{search ? "Try a supplier name or GSTIN, or clear your search." : "Review any internal exceptions in the report. Completed supplier findings leave this queue."}</p></section>}
      {groups.slice(page * 20, (page + 1) * 20).map((group) => <section className="panel" key={group.gstin}>
        <div className="page-heading"><div><h2>{group.name}</h2><p className="muted">{group.gstin} · {group.count} findings</p></div>
          <div className="followup-amount"><span>Absolute tax difference</span><strong>{rupees(group.absolute_tax_difference)}</strong></div></div>
        <div className="followup-table-wrap"><table><caption>Outstanding invoices for {group.name}</caption><thead><tr><th>Invoice</th><th>Finding</th><th>Books tax</th><th>2B tax</th></tr></thead>
          <tbody>{group.items.slice(0, 8).map((item) => <tr key={item.finding_index}><td>{item.invoice_number}</td><td>{pretty(item.category)}{item.differences && <small>{item.differences}</small>}</td><td>{item.books_tax === null ? "Not present" : rupees(item.books_tax)}</td><td>{item.gstr2b_tax === null ? "Not present" : rupees(item.gstr2b_tax)}</td></tr>)}</tbody></table></div>
        {group.count > 8 && <p className="muted">Showing 8 of {group.count}. The invoice download includes all outstanding items for this supplier.</p>}
        <button className="btn btn-primary" disabled={busy || data.stale} onClick={() => prepare(group.gstin)}>Prepare message for {group.name}</button>
      </section>)}
      {groups.length > 20 && <nav className="practice-actions" aria-label="Supplier pages"><button className="btn btn-ghost" disabled={!page} onClick={() => setPage(page - 1)}>Previous suppliers</button><span>Page {page + 1} of {Math.ceil(groups.length / 20)}</span><button className="btn btn-ghost" disabled={(page + 1) * 20 >= groups.length} onClick={() => setPage(page + 1)}>Next suppliers</button></nav>}
    </>}
  </div>;
}
