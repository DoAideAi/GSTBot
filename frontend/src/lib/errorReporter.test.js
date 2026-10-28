import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installErrorReporter, reportError } from "./errorReporter";

let uninstall;

beforeEach(() => {
  window.history.replaceState(null, "", "/gstin-validator?gstin=secret#x");
  window.fetch = vi.fn(() => Promise.resolve({ ok: true }));
  uninstall = installErrorReporter(window);
});

afterEach(() => {
  uninstall?.();
  vi.restoreAllMocks();
});

function sent() {
  return window.fetch.mock.calls.map(([url, init]) => [url, JSON.parse(init.body)]);
}

describe("the error reporter", () => {
  it("sends an uncaught error with its page (no query) and stack", () => {
    const error = new TypeError("x is undefined");
    window.dispatchEvent(new ErrorEvent("error", { error, message: error.message }));
    expect(sent()).toEqual([
      [
        "/api/v1/feedback/error",
        { page: `${window.location.origin}/gstin-validator`, message: "x is undefined", stack: error.stack },
      ],
    ]);
  });

  it("sends the same error on the same page once per page load", () => {
    for (let i = 0; i < 3; i += 1) {
      window.dispatchEvent(new ErrorEvent("error", { message: "boom" }));
    }
    expect(window.fetch).toHaveBeenCalledTimes(1);
  });

  it("reports an unhandled rejection", () => {
    const event = new Event("unhandledrejection");
    event.reason = new Error("fetch failed");
    window.dispatchEvent(event);
    expect(sent()[0][1].message).toBe("fetch failed");
  });

  it("ignores the browser's opaque cross-origin 'Script error.'", () => {
    window.dispatchEvent(new ErrorEvent("error", { message: "Script error." }));
    expect(window.fetch).not.toHaveBeenCalled();
  });

  it("never throws, even when sending does", () => {
    window.fetch = vi.fn(() => {
      throw new Error("offline");
    });
    expect(() => reportError(new Error("another"), { win: window })).not.toThrow();
  });
});
