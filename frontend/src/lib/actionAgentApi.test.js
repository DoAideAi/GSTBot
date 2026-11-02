import { afterEach, expect, it, vi } from "vitest";
import { api, setActiveBusinessId, setToken } from "./api";
afterEach(() => { setToken(null); setActiveBusinessId(null); vi.unstubAllGlobals(); });
it("sends the review using the current user's token and selected business", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, text: async () => '{"period":"2026-10"}' });
  vi.stubGlobal("fetch", fetch);
  setToken("local-test-token");setActiveBusinessId(42);
  const controller = new AbortController();
  await api.reviewActions({ period: "2026-10", focus: "itc" }, { signal: controller.signal });
  const [url, options] = fetch.mock.calls[0];
  expect(url).toBe("/api/v1/action-agent/review");
  expect(options.method).toBe("POST");
  expect(options.headers.Authorization).toBe("Bearer local-test-token");
  expect(options.headers["X-Business-Id"]).toBe("42");
  expect(JSON.parse(options.body)).toEqual({ period: "2026-10", focus: "itc" });
  expect(options.signal).toBe(controller.signal);
});
