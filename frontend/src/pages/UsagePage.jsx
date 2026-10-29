import { useEffect, useState } from "react";
import { usePageTitle } from "../hooks/usePageTitle";
import { api } from "../lib/api";
import Meter from "../components/Meter";
import ChangePasswordForm from "../components/ChangePasswordForm";

export default function UsagePage() {
  usePageTitle("Usage — DoAide GST");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const usage = await api.usage();
        if (!cancelled) setData(usage);
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // The password form is the only place a login can rotate its password, so
  // it stays reachable when the usage figures fail to load.
  if (loading) return <p>Loading usage data...</p>;
  if (error || !data) {
    return (
      <div className="usage-page">
        {error && <p className="text-error">{error}</p>}
        <ChangePasswordForm />
      </div>
    );
  }

  const ENDPOINT_LABELS = {
    invoice_uploads: "Invoices processed",
    gst_lookup: "GST Lookups",
    hsn_search: "HSN/SAC Search",
    bulk_operation: "Bulk Operations",
    api_access: "API Calls",
  };

  const TIER_LABELS = {
    free: "Free",
    pro: "Pro",
    enterprise: "Enterprise",
  };

  return (
    <div className="usage-page">
      <div className="usage-header">
        <h1>Usage</h1>
        <p className="usage-tier">
          Current plan: <strong>{TIER_LABELS[data.tier] || data.tier}</strong>
        </p>
        <p className="usage-period">Period: {data.period}</p>
      </div>

      {data.usage.length === 0 ? (
        <p className="usage-empty">No API calls recorded this month.</p>
      ) : (
        <div className="usage-grid">
          {data.usage.map((item) => (
            <div key={item.endpoint} className="usage-card">
              <h3>{ENDPOINT_LABELS[item.endpoint] || item.endpoint}</h3>
              <div className="usage-count">
                {item.call_count}
                {item.limit > 0 && <span className="usage-limit"> / {item.limit}</span>}
                {item.limit === 0 && <span className="usage-unlimited"> (unlimited)</span>}
              </div>
              {item.limit > 0 && (
                <Meter
                  value={item.call_count}
                  max={item.limit}
                  label={ENDPOINT_LABELS[item.endpoint] || item.endpoint}
                />
              )}
            </div>
          ))}
        </div>
      )}

      <ChangePasswordForm />
    </div>
  );
}
