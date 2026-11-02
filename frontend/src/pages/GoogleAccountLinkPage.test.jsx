import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getActiveBusinessId, getToken, setActiveBusinessId, setToken } from "../lib/api";
import { rememberReturnTo } from "../lib/returnTo";
import { track } from "../lib/track";
import GoogleAccountLinkPage from "./GoogleAccountLinkPage";

vi.mock("../lib/track", () => ({ track: vi.fn() }));
const pending = { email: "owner@example.com", csrf_token: "browser-proof" };
let fetchMock;
let replace;

function response(body, status = 200) {
  return { ok: status < 400, status, text: async () => JSON.stringify(body) };
}

function land() {
  return render(<MemoryRouter><GoogleAccountLinkPage /></MemoryRouter>);
}

async function submit(password = "existing-gst-password") {
  fireEvent.change(await screen.findByLabelText("DoAide GST password"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Connect Google and sign in" }));
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  fetchMock = vi.fn().mockResolvedValueOnce(response(pending));
  replace = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("location", { ...window.location, replace });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

it("asks for the GST password and only signs in after both proofs are accepted", async () => {
  setToken("old-session");
  setActiveBusinessId(7);
  rememberReturnTo("/reconcile?period=2026-09");
  fetchMock.mockResolvedValueOnce(response({ access_token: "linked-session" }));
  land();
  expect(screen.getByRole("status")).toHaveTextContent("Checking");
  expect(await screen.findByLabelText("Google account")).toHaveValue(pending.email);
  expect(screen.getByLabelText("Google account")).toHaveAttribute("readonly");
  expect(screen.getByText(/not your Google password/)).toBeVisible();
  expect(getToken()).toBe("old-session");
  await submit();
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/reconcile?period=2026-09"));
  expect(fetchMock).toHaveBeenLastCalledWith("/api/v1/auth/google/link", expect.objectContaining({
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password: "existing-gst-password", csrf_token: pending.csrf_token }),
  }));
  expect(getToken()).toBe("linked-session");
  expect(getActiveBusinessId()).toBeNull();
  expect(track).toHaveBeenCalledWith("login", { method: "google" });
});

it("keeps a rejected password on the linking page for retry without a session", async () => {
  fetchMock.mockResolvedValueOnce(response({ detail: "Incorrect DoAide GST password. Try again." }, 400));
  fetchMock.mockResolvedValueOnce(response({ access_token: "linked-session" }));
  land();
  await submit("wrong");
  expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect DoAide GST password");
  expect(getToken()).toBeNull();
  expect(replace).not.toHaveBeenCalled();
  expect(screen.getByRole("link", { name: "Forgot your GST password?" })).toHaveAttribute("href", "/forgot-password");
  await submit();
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
});

it("offers a fresh Google sign-in when the browser proof has expired", async () => {
  fetchMock.mockReset().mockResolvedValue(response({ detail: "This Google sign-in link expired." }, 400));
  land();
  expect(await screen.findByRole("alert")).toHaveTextContent("expired");
  expect(screen.queryByLabelText("DoAide GST password")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Start again with Google" })).toHaveAttribute("href", "/api/v1/auth/google");
  expect(getToken()).toBeNull();
});

it("disables submission while connecting and ignores external return destinations", async () => {
  let finish;
  fetchMock.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  sessionStorage.setItem("gstbot_return_to", "//untrusted.example/");
  land();
  await submit();
  expect(screen.getByRole("button", { name: "Connecting…" })).toBeDisabled();
  expect(screen.getByLabelText("DoAide GST password")).toBeDisabled();
  finish(response({ access_token: "linked-session" }));
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
});
