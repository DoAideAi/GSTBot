import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Node 22+ defines its own `globalThis.localStorage`: a getter returning
// undefined unless node was started with --localstorage-file. Vitest's jsdom
// environment only copies a window key onto the global when the key is not
// already there, so Node's dead stub survives and shadows jsdom's working
// Storage -- and because vitest makes `globalThis === window`, there is no
// unshadowed window to read it back from. Borrow the real implementation off a
// standalone JSDOM instance instead.
if (globalThis.localStorage === undefined) {
  const { JSDOM } = await import("jsdom");
  const donor = new JSDOM("", { url: "http://localhost" });
  for (const key of ["localStorage", "sessionStorage"]) {
    Object.defineProperty(globalThis, key, {
      value: donor.window[key],
      configurable: true,
      writable: true,
    });
  }
}

// Unmount and clear the DOM between tests so component trees don't leak.
afterEach(() => {
  cleanup();
  localStorage.clear();
});

// The login form asks which SSO providers exist when it mounts. Answered
// here, as "none", so the many tests that queue fetch responses in order are
// not short one. lib/ssoProviders.test.js unmocks it to test the real call.
vi.mock("../lib/ssoProviders", () => ({
  fetchSsoProviders: vi.fn(() => Promise.resolve([])),
}));
