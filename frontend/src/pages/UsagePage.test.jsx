import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StubAuth } from "../test/auth";
import UsagePage from "./UsagePage";

const USAGE_RESPONSE = {
  tier: "pro",
  period: "2026-10",
  usage: [
    { endpoint: "gst_lookup", call_count: 42, limit: 0 },
    { endpoint: "hsn_search", call_count: 10, limit: 100 },
    { endpoint: "bulk_operation", call_count: 3, limit: 50 },
  ],
};

function mockFetch(...bodies) {
  const fetch = vi.fn();
  bodies.forEach((body) => {
    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: "",
      text: async () => JSON.stringify(body),
    });
  });
  global.fetch = fetch;
  return fetch;
}

function renderPage() {
  return render(
    <MemoryRouter>
      <StubAuth>
        <UsagePage />
      </StubAuth>
    </MemoryRouter>,
  );
}

describe("UsagePage", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("shows the current tier", async () => {
    mockFetch(USAGE_RESPONSE);
    renderPage();

    expect(await screen.findByText("Pro")).toBeInTheDocument();
  });

  it("shows the current period", async () => {
    mockFetch(USAGE_RESPONSE);
    renderPage();

    expect(await screen.findByText(/2026-10/)).toBeInTheDocument();
  });

  it("shows usage counts for each endpoint", async () => {
    mockFetch(USAGE_RESPONSE);
    renderPage();

    expect(await screen.findByText("GST Lookups")).toBeInTheDocument();
    expect(screen.getByText("HSN/SAC Search")).toBeInTheDocument();
    expect(screen.getByText("Bulk Operations")).toBeInTheDocument();
  });

  it("shows unlimited label for endpoints with no limit", async () => {
    mockFetch(USAGE_RESPONSE);
    renderPage();

    expect(await screen.findByText("(unlimited)")).toBeInTheDocument();
  });

  it("shows limit for endpoints with a cap", async () => {
    mockFetch(USAGE_RESPONSE);
    renderPage();

    expect(await screen.findByText("/ 100")).toBeInTheDocument();
    expect(screen.getByText("/ 50")).toBeInTheDocument();
  });

  it("shows empty state when no calls recorded", async () => {
    mockFetch({ tier: "free", period: "2026-10", usage: [] });
    renderPage();

    expect(await screen.findByText(/No API calls recorded/)).toBeInTheDocument();
  });

  it("shows loading state", () => {
    global.fetch = vi.fn(() => new Promise(() => {}));
    renderPage();

    expect(screen.getByText("Loading usage data...")).toBeInTheDocument();
  });

  it("shows error when usage fails to load", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "",
      text: async () => JSON.stringify({ detail: "Server error" }),
    });
    renderPage();

    expect(await screen.findByText(/Server error/)).toBeInTheDocument();
  });

  it("shows human-readable endpoint labels", async () => {
    mockFetch({
      tier: "enterprise",
      period: "2026-10",
      usage: [{ endpoint: "api_access", call_count: 5, limit: 0 }],
    });
    renderPage();

    expect(await screen.findByText("API Calls")).toBeInTheDocument();
  });

  it("labels the invoice allowance", async () => {
    mockFetch({
      tier: "free",
      period: "2026-10",
      usage: [{ endpoint: "invoice_uploads", call_count: 12, limit: 50, period: "2026-10" }],
    });
    renderPage();
    expect(await screen.findByText("Invoices processed")).toBeInTheDocument();
    expect(screen.getByText("/ 50", { exact: false })).toBeInTheDocument();
  });

  it("falls back to raw endpoint name for unknown endpoints", async () => {
    mockFetch({
      tier: "pro",
      period: "2026-10",
      usage: [{ endpoint: "some_new_endpoint", call_count: 1, limit: 10 }],
    });
    renderPage();

    expect(await screen.findByText("some_new_endpoint")).toBeInTheDocument();
  });
});

describe("changing the password from the account page", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  function respond(fetch, body, status = 200) {
    fetch.mockResolvedValueOnce({
      ok: status >= 200 && status < 300,
      status,
      statusText: "",
      text: async () => JSON.stringify(body),
    });
  }

  async function fill(current, next, confirm = next) {
    fireEvent.change(await screen.findByLabelText("Current password"), {
      target: { value: current },
    });
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: next } });
    fireEvent.change(screen.getByLabelText("Confirm new password"), {
      target: { value: confirm },
    });
    fireEvent.click(screen.getByRole("button", { name: "Change password" }));
  }

  it("changes it and says so", async () => {
    const fetch = mockFetch(USAGE_RESPONSE);
    respond(fetch, { access_token: "tok-new" });
    renderPage();
    await fill("old-secret-1", "new-secret-2");

    expect(await screen.findByRole("status")).toHaveTextContent("Password changed");
    const [url, init] = fetch.mock.calls[1];
    expect(url).toBe("/api/v1/auth/change-password");
    expect(JSON.parse(init.body)).toEqual({
      current_password: "old-secret-1",
      new_password: "new-secret-2",
    });
    expect(localStorage.getItem("gstbot_token")).toBe("tok-new");
  });

  it("shows the server's reason when the change is refused", async () => {
    const fetch = mockFetch(USAGE_RESPONSE);
    respond(fetch, { detail: "The current password is not correct." }, 400);
    renderPage();
    await fill("wrong-one", "new-secret-2");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The current password is not correct.",
    );
  });

  it("catches a mistyped confirmation before asking the server", async () => {
    const fetch = mockFetch(USAGE_RESPONSE);
    renderPage();
    await fill("old-secret-1", "new-secret-2", "new-secret-3");

    expect(await screen.findByRole("alert")).toHaveTextContent("do not match");
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
