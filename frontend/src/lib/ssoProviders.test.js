import { afterEach, describe, expect, it, vi } from "vitest";

// test/setup.js stubs this module for every other file; this one tests it.
vi.unmock("./ssoProviders");
const { fetchSsoProviders } = await import("./ssoProviders");

describe("fetchSsoProviders", () => {
  afterEach(() => vi.restoreAllMocks());

  it("returns what the deployment has configured", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ providers: ["google"] }) });
    expect(await fetchSsoProviders()).toEqual(["google"]);
    expect(global.fetch).toHaveBeenCalledWith("/api/v1/auth/providers");
  });

  it("offers none when the request fails or answers oddly", async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    expect(await fetchSsoProviders()).toEqual([]);
    global.fetch = vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) });
    expect(await fetchSsoProviders()).toEqual([]);
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ providers: "x" }) });
    expect(await fetchSsoProviders()).toEqual([]);
  });
});
