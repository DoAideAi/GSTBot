import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import StatusPage from "./StatusPage";

function health(overrides = {}) {
  return {
    status: "ok",
    app: "DoAide GST",
    version: "0.1.0",
    environment: "production",
    database: "ok",
    redis: "ok",
    ai: "configured",
    storage: "ok",
    health: "ok",
    checks: {
      database: { status: "ok", latency_ms: 1.2, pool: {} },
      redis: {
        status: "ok",
        latency_ms: 0.4,
        required_for: ["distributed rate limiting", "celery broker"],
      },
      ai: { status: "configured", provider: "openrouter", model: "openai/gpt-oss-20b:free" },
      storage: {
        status: "ok",
        latency_ms: 0.2,
        path: "/var/lib/gstbot/uploads",
        required_for: ["invoice uploads"],
      },
    },
    ...overrides,
  };
}

function jobs(overrides = {}) {
  return {
    health: "ok",
    celery_enabled: true,
    workers: { reachable: true, names: ["celery@box"] },
    queue: { name: "celery", reachable: true, depth: 0 },
    jobs: [
      { name: "filing-deadline-sweep", last_run: "2026-08-10T01:30:00Z", stale: false },
      {
        name: "filing-deadline-alert-emails",
        last_run: "2026-08-10T01:35:00Z",
        stale: false,
      },
      { name: "stalled-parse-sweep", last_run: "2026-08-10T09:00:00Z", stale: false },
    ],
    ...overrides,
  };
}

function jsonResponse(body, { status = 200 } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    text: async () => JSON.stringify(body),
  };
}

/** Route each probe to its own body, whatever order they are requested in. */
function respond({ healthBody = health(), jobsBody = jobs() } = {}) {
  return vi.fn(async (url) => {
    if (String(url).includes("/health/jobs")) {
      return typeof jobsBody === "function" ? jobsBody() : jsonResponse(jobsBody);
    }
    return typeof healthBody === "function" ? healthBody() : jsonResponse(healthBody);
  });
}

function renderPage() {
  return render(
    <MemoryRouter>
      <StatusPage />
    </MemoryRouter>,
  );
}

describe("StatusPage", () => {
  beforeEach(() => {
    localStorage.clear();
    global.fetch = respond();
  });

  it("reads both probes, and reads them at the same time", async () => {
    // In parallel rather than in series: the jobs probe holds the server
    // thread for up to a second on a Celery ping, and there is no reason for
    // the database round-trip to wait behind it.
    renderPage();

    await screen.findByText("Everything is running");
    const paths = global.fetch.mock.calls.map(([url]) => String(url));
    expect(paths.some((p) => p.endsWith("/health"))).toBe(true);
    expect(paths.some((p) => p.includes("/health/jobs"))).toBe(true);
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  it("sends no bearer token to either probe", async () => {
    // Both are public and untenanted on purpose — an operator watching the
    // queue has no account. Nothing here is scoped to a business, and a token
    // sent anyway would be the only thing on the page that was.
    localStorage.setItem("gstbot_token", "t");
    renderPage();

    await screen.findByText("Everything is running");
    for (const [, options] of global.fetch.mock.calls) {
      expect(options?.headers?.Authorization).toBeUndefined();
    }
  });

  describe("what a degraded dependency is said to cost", () => {
    it("names what stops working when Redis is down rather than reporting the status alone", async () => {
      global.fetch = respond({
        healthBody: health({
          health: "degraded",
          redis: "unavailable",
          checks: {
            ...health().checks,
            redis: { status: "unavailable", latency_ms: 0.1, required_for: [] },
          },
        }),
      });
      renderPage();

      expect(await screen.findByText(/Running, with something degraded/)).toBeInTheDocument();
      expect(
        screen.getByText(/Queue offline/),
      ).toBeInTheDocument();
    });

    it("names the upload disk when it is the thing that is down", async () => {
      // The one dependency that was probed once at boot and never again; the
      // page has to render it or the check exists only for curl.
      global.fetch = respond({
        healthBody: health({
          health: "degraded",
          storage: "unavailable",
          checks: {
            ...health().checks,
            storage: {
              status: "unavailable",
              latency_ms: 0.2,
              error: "ReadOnly",
              path: "/var/lib/gstbot/uploads",
              required_for: ["invoice uploads"],
            },
          },
        }),
      });
      renderPage();

      expect(await screen.findByText(/Running, with something degraded/)).toBeInTheDocument();
      expect(screen.getByText("Upload storage")).toBeInTheDocument();
      expect(
        screen.getByText(/Disk full or read-only/),
      ).toBeInTheDocument();
    });

    it("treats an unconfigured extractor as healthy-but-degraded, not as down", async () => {
      // No OpenRouter key is a supported deployment, not a fault: the parser
      // falls back to its own patterns. Saying so is the point.
      global.fetch = respond({
        healthBody: health({
          health: "degraded",
          ai: "unconfigured",
          checks: { ...health().checks, ai: { status: "unconfigured", provider: "openrouter" } },
        }),
      });
      renderPage();

      expect(
        await screen.findByText(/AI extractor offline/),
      ).toBeInTheDocument();
    });

    it("does not invent a status for a dependency the probe did not report", async () => {
      // The probe's `checks` are built server-side and a key can be missing —
      // a version skew, or a dependency dropped from the report. Rendering
      // `undefined` beside "Your data" would read as an outage.
      global.fetch = respond({
        healthBody: health({ checks: { database: { status: "ok", latency_ms: 1.2 } } }),
      });
      renderPage();

      // Every dependency the page knows about except the one that answered.
      expect(await screen.findAllByText("unknown")).toHaveLength(3);
    });

    it("shows the database as the reason when the API answers 503", async () => {
      // The probe's *failure* is this page's most important result. Reported
      // as a dependency outage, not as "the status page could not load".
      global.fetch = respond({
        healthBody: () =>
          jsonResponse({ detail: "Database unreachable" }, { status: 503 }),
      });
      renderPage();

      expect(await screen.findByText(/Dependencies: Database unreachable/)).toBeInTheDocument();
      // The other probe answered, so its panel is still there.
      expect(screen.getByText("Deadline alerts")).toBeInTheDocument();
    });
  });

  describe("scheduled jobs", () => {
    it("says what an overdue job means rather than printing its name", async () => {
      global.fetch = respond({
        jobsBody: jobs({
          health: "degraded",
          jobs: [
            {
              name: "filing-deadline-sweep",
              last_run: "2026-08-01T01:30:00Z",
              stale: true,
            },
          ],
        }),
      });
      renderPage();

      expect(await screen.findByText("Deadline alerts")).toBeInTheDocument();
      expect(
        screen.getByText("Deadline alerts paused."),
      ).toBeInTheDocument();
      expect(screen.getByText("Something is behind")).toBeInTheDocument();
    });

    it("does not call a job overdue when there was no way to check", async () => {
      // `stale: null` is Redis being unreachable — "no heartbeat" and "no way
      // to look for one" are different answers, and reporting the second as
      // the first turns one outage of the queue into three failed jobs.
      global.fetch = respond({
        jobsBody: jobs({
          health: "degraded",
          queue: { name: "celery", reachable: false, depth: 0, error: "ConnectionError" },
          jobs: [{ name: "stalled-parse-sweep", last_run: null, stale: null }],
        }),
      });
      renderPage();

      expect(await screen.findByText("Unknown")).toBeInTheDocument();
      expect(screen.queryByText("Overdue")).not.toBeInTheDocument();
      expect(
        screen.queryByText(/will stay stuck rather than being retried/),
      ).not.toBeInTheDocument();
    });

    it("renders a job the page has no caption for under its own name", async () => {
      // The backend's JOB_STALE_AFTER_SECONDS is where jobs are added. One
      // added there and not here must still appear, rather than vanishing.
      global.fetch = respond({
        jobsBody: jobs({
          jobs: [{ name: "some-new-sweep", last_run: "2026-08-10T01:00:00Z", stale: false }],
        }),
      });
      renderPage();

      expect(await screen.findByText("some-new-sweep")).toBeInTheDocument();
    });

    it("says so when nothing is scheduled at all", async () => {
      global.fetch = respond({ jobsBody: jobs({ jobs: [] }) });
      renderPage();

      expect(await screen.findByText("No scheduled jobs are reporting.")).toBeInTheDocument();
    });

    it("does not render a heartbeat it cannot parse as a date", async () => {
      // `last_run` is whatever came back out of Redis. A truncated or
      // hand-edited key would otherwise render the string "Invalid Date".
      global.fetch = respond({
        jobsBody: jobs({
          jobs: [{ name: "stalled-parse-sweep", last_run: "not-a-timestamp", stale: false }],
        }),
      });
      renderPage();

      expect(await screen.findByText(/Last run: Unknown/)).toBeInTheDocument();
    });

    it("shows a job that has never run as never having run", async () => {
      global.fetch = respond({
        jobsBody: jobs({
          health: "degraded",
          jobs: [{ name: "stalled-parse-sweep", last_run: null, stale: true }],
        }),
      });
      renderPage();

      expect(await screen.findByText(/Last run: Never/)).toBeInTheDocument();
    });
  });

  describe("workers", () => {
    it("does not report a single-process install as having no workers", async () => {
      // Celery switched off is a deployment choice. Calling it "None
      // answering" would have every such install permanently showing a fault.
      global.fetch = respond({
        jobsBody: jobs({
          celery_enabled: false,
          workers: { reachable: false, names: [] },
        }),
      });
      renderPage();

      expect(await screen.findByText("Not in use")).toBeInTheDocument();
      expect(
        screen.queryByText(/Uploads parse inline/),
      ).not.toBeInTheDocument();
    });

    it("says what an empty worker pool costs when Celery is meant to be on", async () => {
      global.fetch = respond({
        jobsBody: jobs({
          health: "degraded",
          workers: { reachable: false, names: [], error: "ConnectionError" },
        }),
      });
      renderPage();

      expect(await screen.findByText("None answering")).toBeInTheDocument();
      expect(
        screen.getByText(/Uploads parse inline/),
      ).toBeInTheDocument();
    });

    it("counts a reachable pool that reported no names as none", async () => {
      // `names` is absent rather than empty on some broker replies, and
      // `undefined running` is not a thing to put on a screen.
      global.fetch = respond({
        jobsBody: jobs({ workers: { reachable: true } }),
      });
      renderPage();

      expect(await screen.findByText("0 running")).toBeInTheDocument();
    });

    it("flags a queue that is backing up", async () => {
      global.fetch = respond({
        jobsBody: jobs({ queue: { name: "celery", reachable: true, depth: 42 } }),
      });
      renderPage();

      expect(await screen.findByText("42 waiting")).toBeInTheDocument();
    });
  });

  describe("failure and refresh", () => {
    it("keeps the two probes' failures apart", async () => {
      global.fetch = respond({
        jobsBody: () => jsonResponse({ detail: "nope" }, { status: 500 }),
      });
      renderPage();

      expect(await screen.findByText(/Background jobs:/)).toBeInTheDocument();
      // The dependency panel answered and is unaffected.
      expect(screen.getByText("Everything is running")).toBeInTheDocument();
      expect(screen.getByText(/The background-job check did not answer./)).toBeInTheDocument();
    });

    it("reports a network failure in the words the app chose", async () => {
      global.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
      renderPage();

      const banner = await screen.findByRole("alert");
      expect(banner).toHaveTextContent(/Could not reach the server/);
      expect(banner).not.toHaveTextContent(/Failed to fetch/);
    });

    it("re-reads both probes when asked to check again", async () => {
      renderPage();
      await screen.findByText("Everything is running");

      await userEvent.click(screen.getByRole("button", { name: "Check again" }));

      await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(4));
    });

    it("lets the banner be dismissed", async () => {
      global.fetch = respond({
        jobsBody: () => jsonResponse({ detail: "nope" }, { status: 500 }),
      });
      renderPage();
      await screen.findByRole("alert");

      await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));

      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("applies nothing after the page has gone away", async () => {
      // `Promise.allSettled` resolves whatever happens, including when both
      // probes were aborted — so the abort alone does not stop the handler
      // from running. Without the guard after it, this sets state on an
      // unmounted component every time a user navigates away mid-check.
      let release;
      const held = new Promise((resolve) => {
        release = resolve;
      });
      global.fetch = vi.fn(async () => {
        await held;
        return jsonResponse(health());
      });
      const errors = vi.spyOn(console, "error").mockImplementation(() => {});
      const { unmount } = renderPage();

      unmount();
      release();
      await held;

      expect(errors).not.toHaveBeenCalled();
      errors.mockRestore();
    });

    it("aborts both probes when the page goes away", async () => {
      // The jobs probe holds a server thread for up to a second. A user who
      // navigates away should not leave that in flight.
      const { unmount } = renderPage();
      await screen.findByText("Everything is running");
      const signals = global.fetch.mock.calls.map(([, options]) => options?.signal);

      unmount();

      expect(signals).toHaveLength(2);
      for (const signal of signals) expect(signal?.aborted).toBe(true);
    });
  });
});

describe("whenLabel", () => {
  it("reads day first and in India time, whatever the viewer's locale and zone", async () => {
    const { whenLabel } = await import("./StatusPage");
    // 04:15 UTC is 09:45 in India. A bare toLocaleString() followed the
    // browser: month first on a US-locale machine, in the machine's zone.
    expect(whenLabel("2026-10-29T04:15:48Z")).toMatch(/^29 Oct 2026, 9:45\s?[ap]m IST$/i);
    expect(whenLabel(null)).toBe("Never");
    expect(whenLabel("not a date")).toBe("Unknown");
  });
});
