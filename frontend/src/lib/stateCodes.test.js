import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { STATE_CODES, stateForGstin } from "./stateCodes";

// The backend's list is authoritative; this copy must not drift from it.
function backendStateCodes() {
  const src = readFileSync(resolve(__dirname, "../../../backend/app/services/gstin.py"), "utf8");
  const block = src.slice(src.indexOf("STATE_CODES: dict[str, str] = {"));
  const body = block.slice(0, block.indexOf("\n}"));
  return Object.fromEntries([...body.matchAll(/"(\d{2})": "([^"]+)"/g)].map((m) => [m[1], m[2]]));
}

describe("STATE_CODES", () => {
  it("matches the backend list exactly", () => {
    const backend = backendStateCodes();
    expect(Object.keys(backend).length).toBeGreaterThan(35);
    expect(Object.fromEntries(STATE_CODES.map((s) => [s.code, s.name]))).toEqual(backend);
  });
});

describe("stateForGstin", () => {
  it("reads the state from the first two characters of a GSTIN", () => {
    expect(stateForGstin("27AAPFU0939F1ZV").name).toBe("Maharashtra");
    expect(stateForGstin(" 07 ").name).toBe("Delhi");
  });

  it("returns null for anything that is not a known 2-digit code", () => {
    expect(stateForGstin("")).toBeNull();
    expect(stateForGstin("A7")).toBeNull();
    expect(stateForGstin("50ABC")).toBeNull();
    expect(stateForGstin(undefined)).toBeNull();
  });
});
