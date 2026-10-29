import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getToken } from "../lib/api";
import { rememberReturnTo } from "../lib/returnTo";
import { track } from "../lib/track";
import AuthCallbackPage from "./AuthCallbackPage";

vi.mock("../lib/track", () => ({ track: vi.fn() }));

function land(fragment) {
  render(
    <MemoryRouter initialEntries={[`/auth/callback#${fragment}`]}>
      <Routes>
        <Route path="/auth/callback" element={<AuthCallbackPage />} />
        <Route path="/login" element={<p>login</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AuthCallbackPage", () => {
  let replace;

  beforeEach(() => {
    localStorage.clear();
    replace = vi.fn();
    vi.stubGlobal("location", { ...window.location, replace });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    track.mockClear();
  });

  it("counts the sign-in that created the account as a sign-up", () => {
    land("token=tok-new&provider=google&new=1");

    expect(getToken()).toBe("tok-new");
    expect(track).toHaveBeenCalledWith("signup_complete", { method: "google" });
    expect(replace).toHaveBeenCalledWith("/");
  });

  it("counts a returning account as a sign-in", () => {
    land("token=tok-back&provider=github");

    expect(track).toHaveBeenCalledWith("login", { method: "github" });
    expect(track).not.toHaveBeenCalledWith("signup_complete", expect.anything());
  });

  it("still signs in from an older link that names no provider", () => {
    land("token=tok-old");

    expect(getToken()).toBe("tok-old");
    expect(track).toHaveBeenCalledWith("login", { method: "oauth" });
  });

  it("counts nothing when there is no token", () => {
    land("");

    expect(track).not.toHaveBeenCalled();
  });
});

describe("AuthCallbackPage returning to the page that was asked for", () => {
  let replace;

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    replace = vi.fn();
    vi.stubGlobal("location", { ...window.location, replace });
  });

  afterEach(() => vi.unstubAllGlobals());

  it("goes back to the deep link the sign-in interrupted", () => {
    rememberReturnTo("/reconcile?period=2026-09");
    land("token=tok&provider=google");
    expect(replace).toHaveBeenCalledWith("/reconcile?period=2026-09");
  });

  it("will not be sent off the site by what was stored", () => {
    sessionStorage.setItem("gstbot_return_to", "//evil.example/");
    land("token=tok&provider=google");
    expect(replace).toHaveBeenCalledWith("/");
  });
});
