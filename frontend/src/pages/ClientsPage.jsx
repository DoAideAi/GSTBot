import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import ErrorBanner from "../components/ErrorBanner";
import { useAuth } from "../hooks/useAuth";
import { usePageTitle } from "../hooks/usePageTitle";
import { api, isAbortError } from "../lib/api";
import { currentPeriod, periodLabel } from "../lib/format";
import "./practice.css";

export default function ClientsPage() {
  usePageTitle("Client work queue");
  const { switchBusiness } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedPeriod = searchParams.get("period");
  const period = /^20\d{2}-(0[1-9]|1[0-2])$/.test(requestedPeriod || "")
    ? requestedPeriod : currentPeriod();
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    api
      .practiceClients(period, offset, { signal: controller.signal })
      .then(setData)
      .catch((e) => {
        if (!isAbortError(e)) setError(e.message);
      });
    return () => controller.abort();
  }, [period, offset, refresh]);
  const open = async (item) => {
    setBusy(true);
    setError("");
    try {
      await switchBusiness(item.id);
      const target = !item.purchase_count
        ? "/purchase-import"
        : !item.has_2b || !item.run_id || item.stale
          ? `/reconcile?period=${period}`
          : `/review/${item.run_id}`;
      navigate(target);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="practice-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">CA workspace</p>
          <h1>Client work queue</h1>
          <p className="muted">
            See the next step for each registration you can access.
          </p>
        </div>
        <label>
          Filing period
          <input
            type="month"
            value={period}
            onChange={(e) => {
              if (e.target.value) {
                setSearchParams({ period: e.target.value });
                setOffset(0);
              }
            }}
          />
        </label>
      </div>
      <ErrorBanner message={error} onDismiss={() => setError("")} />
      <div className="practice-actions">
        <button
          className="btn btn-ghost"
          disabled={busy}
          onClick={() => setRefresh(refresh + 1)}
        >
          Refresh queue
        </button>
        <Link to="/client-access">Manage invitations and access</Link>
      </div>
      <section className="panel">
        <h2>{periodLabel(period)}</h2>
        <p>
          Access and pilot coverage are separate. Ask each client’s owner to
          invite your email, then manage covered registrations from Pricing if
          applicable.
        </p>
        {!data ? (
          <p role="status">
            {error
              ? "The client queue could not be loaded."
              : "Loading client work…"}
          </p>
        ) : (
          <>
            <div className="practice-table client-queue">
              <table>
                <thead>
                  <tr>
                    <th>Client</th>
                    <th>Purchases</th>
                    <th>GSTR-2B</th>
                    <th>Exceptions</th>
                    <th>Next step</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <tr key={item.id}>
                      <td data-label="Client">
                        <strong>{item.name}</strong>
                        <div className="muted">
                          {item.gstin || "GSTIN not added"}
                        </div>
                      </td>
                      <td data-label="Purchases">{item.purchase_count}</td>
                      <td data-label="GSTR-2B">{item.has_2b ? "Imported" : "Missing"}</td>
                      <td data-label="Exceptions">
                        {item.unresolved === null
                          ? "Not reconciled"
                          : item.stale
                            ? "Re-run needed"
                            : `${item.unresolved} unresolved`}
                      </td>
                      <td data-label="Next step">
                        <button
                          className="btn btn-ghost"
                          disabled={busy}
                          onClick={() => open(item)}
                        >
                          {item.next_action}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!data.items.length && <p>No accessible clients on this page.</p>}
            <div className="practice-actions">
              <button
                className="btn btn-ghost"
                disabled={!offset || busy}
                onClick={() => setOffset(Math.max(0, offset - 25))}
              >
                Previous clients
              </button>
              <span>{data.total} accessible registrations</span>
              <button
                className="btn btn-ghost"
                disabled={offset + data.items.length >= data.total || busy}
                onClick={() => setOffset(offset + 25)}
              >
                Next clients
              </button>
            </div>
          </>
        )}
      </section>
      <p className="practice-footer">
        “Reviewed and exported” records an accountant’s workflow completion. It
        does not mean a return was filed or tax credit is legally eligible.
      </p>
    </div>
  );
}
