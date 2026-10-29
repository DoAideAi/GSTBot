import { useCallback, useEffect, useState } from "react";
import ErrorBanner from "../components/ErrorBanner";
import { SkeletonPanel } from "../components/Skeleton";
import { usePageTitle } from "../hooks/usePageTitle";
import { api, isAbortError } from "../lib/api";

/**
 * What the two ops probes mean for the person reading them.
 *
 * `/health` and `/health/jobs` report dependencies and heartbeats, which is
 * the right shape for a monitor and the wrong one for a business. Nobody
 * running a trading company needs to know that a Celery broadcast ping went
 * unanswered; they need to know that the invoices they uploaded this morning
 * are not being read, and that the deadline alerts they rely on are not being
 * raised. So every row here is captioned by its consequence, with the raw
 * finding underneath it for whoever is actually debugging.
 *
 * The probes are public and untenanted — deliberately, because an operator
 * watching the queue has no token to send — so nothing on this page is scoped
 * to a business and nothing on it leaks one.
 */

// A degraded dependency costs something specific. Naming it here rather than
// in the markup keeps the two probes' vocabularies from drifting apart.
const DEPENDENCIES = {
  database: {
    label: "Your data",
    down: "Database unreachable — nothing will load.",
  },
  redis: {
    label: "Background queue",
    down: "Queue offline — uploads parse inline, sweeps paused.",
  },
  ai: {
    label: "Invoice reading",
    down: "AI extractor offline — using built-in patterns only.",
  },
  storage: {
    label: "Upload storage",
    down: "Disk full or read-only — new uploads will fail.",
  },
};

// Same idea for the scheduled jobs. Keyed on the names in
// `JOB_STALE_AFTER_SECONDS` in backend/app/services/job_health.py — a job
// added there and not here still renders, under its own name.
const JOBS = {
  "filing-deadline-sweep": {
    label: "Deadline alerts",
    stale: "Deadline alerts paused.",
  },
  "filing-deadline-alert-emails": {
    label: "Alert emails",
    stale: "Alert emails not sending.",
  },
  "stalled-parse-sweep": {
    label: "Stuck upload recovery",
    stale: "Stuck uploads won't auto-retry.",
  },
};

const OVERALL = {
  ok: { tone: "good", label: "Everything is running" },
  degraded: { tone: "warn", label: "Running, with something degraded" },
  unhealthy: { tone: "bad", label: "Not serving" },
};

function Chip({ tone, children }) {
  return <span className={`chip chip-${tone}`}>{children}</span>;
}

/**
 * An ISO timestamp as something readable, or a dash. Never "Invalid Date".
 *
 * Day first and in India time, as every other date in the app is (dateLabel).
 * A bare toLocaleString() followed the viewer's browser, so a US-locale one
 * read the sweep's last run as 10/29/2026 — month first — in whatever zone
 * the machine happened to be set to.
 */
export function whenLabel(iso) {
  if (!iso) return "Never";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "Unknown";
  return `${at.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })} IST`;
}

function DependencyRows({ checks }) {
  return (
    <dl className="kv">
      {Object.entries(DEPENDENCIES).map(([key, meta]) => {
        const check = checks?.[key];
        // `ai` reports `configured`/`unconfigured`; the other two report
        // `ok`/`unavailable`. Both healthy states are treated the same.
        const healthy = check?.status === "ok" || check?.status === "configured";
        return (
          <div key={key}>
            <span className="muted">{meta.label}</span>
            <strong>
              <Chip tone={healthy ? "good" : "warn"}>{check?.status ?? "unknown"}</Chip>
            </strong>
            {!healthy && <div className="stat-sub">{meta.down}</div>}
            {check?.latency_ms !== undefined && (
              <div className="stat-sub muted small">{check.latency_ms} ms</div>
            )}
          </div>
        );
      })}
    </dl>
  );
}

function JobRows({ jobs }) {
  if (!jobs?.length) return <p className="muted">No scheduled jobs are reporting.</p>;
  return (
    <dl className="kv">
      {jobs.map((job) => {
        const meta = JOBS[job.name];
        return (
          <div key={job.name}>
            <span className="muted">{meta?.label ?? job.name}</span>
            <strong>
              {/* `stale` is null when Redis itself is unreachable: "no
                  heartbeat" and "no way to check for one" are different
                  answers, and flattening them to "stale" would report an
                  outage of the queue as an outage of every job behind it. */}
              {job.stale === null ? (
                <Chip tone="neutral">Unknown</Chip>
              ) : job.stale ? (
                <Chip tone="warn">Overdue</Chip>
              ) : (
                <Chip tone="good">On time</Chip>
              )}
            </strong>
            <div className="stat-sub muted small">Last run: {whenLabel(job.last_run)}</div>
            {job.stale === true && meta && <div className="stat-sub">{meta.stale}</div>}
          </div>
        );
      })}
    </dl>
  );
}

export default function StatusPage() {
  usePageTitle("System status");
  const [health, setHealth] = useState(null);
  const [jobs, setJobs] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [reloadToken, setReloadToken] = useState(0);

  const load = useCallback(async ({ signal } = {}) => {
    setLoading(true);
    setError("");
    // Both at once. They are independent probes of independent things, and
    // running them in series would put the Celery ping's held second — up to
    // a full second by design — behind the database round-trip for no reason.
    const [healthResult, jobsResult] = await Promise.allSettled([
      api.health({ signal }),
      api.jobHealth({ signal }),
    ]);
    if (signal?.aborted) return;

    // Reported separately rather than as one failure. `/health` answers 503
    // when the database is unreachable — which is a *result*, the most
    // important one this page has — while `/health/jobs` answering nothing is
    // a different outage. Collapsing them would let a dead database render as
    // "could not load the status page".
    const failures = [];
    if (healthResult.status === "fulfilled") setHealth(healthResult.value);
    else if (!isAbortError(healthResult.reason)) {
      setHealth(null);
      failures.push(`Dependencies: ${healthResult.reason.message}`);
    }
    if (jobsResult.status === "fulfilled") setJobs(jobsResult.value);
    else if (!isAbortError(jobsResult.reason)) {
      setJobs(null);
      failures.push(`Background jobs: ${jobsResult.reason.message}`);
    }

    setError(failures.join(" "));
    setLoading(false);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    load({ signal: controller.signal });
    return () => controller.abort();
  }, [load, reloadToken]);

  const overall = OVERALL[health?.health] ?? null;
  // The queue is unreachable, or a worker pool is empty, or a job is overdue.
  // The endpoint has already decided this — `health` on the jobs probe — and
  // re-deriving it here would let the two disagree.
  const jobsDegraded = jobs?.health === "degraded";

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>System status</h1>
          <p className="muted">Live service health</p>
        </div>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => setReloadToken((token) => token + 1)}
          disabled={loading}
        >
          {loading ? "Checking…" : "Check again"}
        </button>
      </div>

      <ErrorBanner message={error} onDismiss={() => setError("")} />

      {loading && !health && !jobs ? (
        <SkeletonPanel lines={6} label="Checking system status" />
      ) : (
        <>
          <section className="panel">
            <div className="page-head">
              <h2>The API and what it depends on</h2>
              {overall && <Chip tone={overall.tone}>{overall.label}</Chip>}
            </div>
            {health ? (
              <>
                <DependencyRows checks={health.checks} />
                <p className="muted small">
                  {health.app} {health.version} · {health.environment}
                </p>
              </>
            ) : (
              <p className="muted">The API did not answer its health check.</p>
            )}
          </section>

          <section className="panel">
            <div className="page-head">
              <h2>Work that runs on a schedule</h2>
              {jobs && (
                <Chip tone={jobsDegraded ? "warn" : "good"}>
                  {jobsDegraded ? "Something is behind" : "On schedule"}
                </Chip>
              )}
            </div>
            {jobs ? (
              <>
                <JobRows jobs={jobs.jobs} />
                <dl className="kv">
                  <div>
                    <span className="muted">Workers</span>
                    <strong>
                      {/* Celery being switched off is a deployment choice, not
                          a fault. Reporting "no workers" for it would have
                          every single-process install permanently red. */}
                      {!jobs.celery_enabled ? (
                        <Chip tone="neutral">Not in use</Chip>
                      ) : jobs.workers?.reachable ? (
                        <Chip tone="good">{jobs.workers.names?.length ?? 0} running</Chip>
                      ) : (
                        <Chip tone="warn">None answering</Chip>
                      )}
                    </strong>
                    {jobs.celery_enabled && !jobs.workers?.reachable && (
                      <div className="stat-sub">
                        Uploads parse inline — large batches will be slow.
                      </div>
                    )}
                  </div>
                  <div>
                    <span className="muted">Queue</span>
                    <strong>
                      {jobs.queue?.reachable ? (
                        <Chip tone={jobs.queue.depth > 0 ? "warn" : "good"}>
                          {jobs.queue.depth} waiting
                        </Chip>
                      ) : (
                        <Chip tone="warn">Unreachable</Chip>
                      )}
                    </strong>
                  </div>
                </dl>
              </>
            ) : (
              <p className="muted">The background-job check did not answer.</p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
