import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({ api: { stats: vi.fn() } }));

// The module keeps its one in-flight promise in module state, so each test
// gets a fresh copy of the module rather than the previous test's cache.
async function freshModule() {
  vi.resetModules();
  const mod = await import("./usageStats");
  const { api } = await import("./api");
  return { ...mod, api };
}

describe("getUsageStats", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // P38 M4: a failure was cached for the rest of the session. This is a
  // single-page app, so one unreachable moment (a visitor landing during a
  // deploy's restart) hid the figures on every page until a full reload.
  it("asks again after a failure instead of keeping it", async () => {
    const { getUsageStats, api } = await freshModule();
    api.stats.mockRejectedValueOnce(new Error("down"));
    api.stats.mockResolvedValueOnce({ businesses: 120, invoices: 500, gstin_lookups: 9000 });

    await expect(getUsageStats()).resolves.toBeNull();
    await expect(getUsageStats()).resolves.toEqual({
      businesses: 120,
      invoices: 500,
      gstin_lookups: 9000,
    });
    expect(api.stats).toHaveBeenCalledTimes(2);
  });

  it("asks again after a body that was not stats", async () => {
    const { getUsageStats, api } = await freshModule();
    api.stats.mockResolvedValueOnce("<html>edge error page</html>");
    api.stats.mockResolvedValueOnce({ businesses: 120, invoices: 500, gstin_lookups: 9000 });

    await expect(getUsageStats()).resolves.toBeNull();
    await expect(getUsageStats()).resolves.toMatchObject({ businesses: 120 });
  });

  it("still shares one success for the rest of the page load", async () => {
    const { getUsageStats, api } = await freshModule();
    api.stats.mockResolvedValue({ businesses: 120, invoices: 500, gstin_lookups: 9000 });

    await getUsageStats();
    await getUsageStats();
    expect(api.stats).toHaveBeenCalledTimes(1);
  });

  it("fetches once and shares the result across callers", async () => {
    const { getUsageStats, api } = await freshModule();
    api.stats.mockResolvedValue({ businesses: 120, invoices: 500, gstin_lookups: 9000 });

    const [a, b] = await Promise.all([getUsageStats(), getUsageStats()]);

    expect(a).toEqual({ businesses: 120, invoices: 500, gstin_lookups: 9000 });
    expect(b).toBe(a);
    expect(api.stats).toHaveBeenCalledTimes(1);
  });

  it("resolves to null when the API is unreachable", async () => {
    const { getUsageStats, api } = await freshModule();
    api.stats.mockRejectedValue(new Error("down"));

    await expect(getUsageStats()).resolves.toBeNull();
  });

  it("treats a non-object body as no stats", async () => {
    const { getUsageStats, api } = await freshModule();
    api.stats.mockResolvedValue("<html>edge error page</html>");

    await expect(getUsageStats()).resolves.toBeNull();
  });
});

describe("formatStat", () => {
  it("formats a figure at or above the floor in Indian digit grouping", async () => {
    const { formatStat, STAT_FLOOR } = await freshModule();
    expect(formatStat(STAT_FLOOR)).toBe("100");
    expect(formatStat(123456)).toBe("1,23,456");
  });

  it("refuses to show a figure below the floor rather than round it up", async () => {
    const { formatStat } = await freshModule();
    expect(formatStat(99)).toBeNull();
    expect(formatStat(0)).toBeNull();
  });

  it("refuses a missing or malformed figure", async () => {
    const { formatStat } = await freshModule();
    expect(formatStat(undefined)).toBeNull();
    expect(formatStat(NaN)).toBeNull();
    expect(formatStat("12000")).toBeNull();
  });
});
