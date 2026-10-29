import { beforeEach, describe, expect, it, vi } from "vitest";
import { rememberReturnTo, takeReturnTo } from "./returnTo";

// A deep link opened while signed out — an emailed /invoices/42, a bookmark,
// a session that expired mid-task — landed on the home page after signing in,
// by password or by a provider, and the page asked for was lost.
describe("where a sign-in returns to", () => {
  beforeEach(() => sessionStorage.clear());

  it("is the page that was asked for, once", () => {
    rememberReturnTo("/invoices?status=failed");
    expect(takeReturnTo()).toBe("/invoices?status=failed");
    expect(takeReturnTo()).toBe("/");
  });

  it("is home when nothing was asked for", () => {
    expect(takeReturnTo()).toBe("/");
  });

  it.each([
    "//evil.example/steal",
    "/\\evil.example",
    "https://evil.example/",
    "javascript:alert(1)",
    "invoices",
    "/auth/callback#token=x",
    "/login",
    "",
  ])("never leaves the site or loops back into signing in: %s", (target) => {
    rememberReturnTo(target);
    expect(takeReturnTo()).toBe("/");
  });

  it("survives a browser that will not store anything", () => {
    const refuse = () => {
      throw new DOMException("blocked", "SecurityError");
    };
    vi.stubGlobal("sessionStorage", { getItem: refuse, setItem: refuse, removeItem: refuse });
    try {
      expect(() => rememberReturnTo("/invoices")).not.toThrow();
      expect(takeReturnTo()).toBe("/");
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("the password pages are not destinations either", () => {
  beforeEach(() => sessionStorage.clear());

  it.each(["/forgot-password", "/reset-password#token=x"])("%s", (target) => {
    rememberReturnTo(target);
    expect(takeReturnTo()).toBe("/");
  });
});
