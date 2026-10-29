import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  api,
  getActiveBusinessId,
  getToken,
  setActiveBusinessId,
  setToken,
} from "../lib/api";
import { track } from "../lib/track";
import { AuthProvider, useAuth } from "./useAuth";

vi.mock("../lib/track", () => ({ track: vi.fn() }));

const USER = {
  id: 1,
  email: "owner@example.com",
  full_name: "Umang Shah",
  business: { id: 1, gstin: "27AAPFU0939F1ZV", legal_name: "Umang Traders Private Limited" },
};

/**
 * Route by path and method, because a login is two requests — the token call
 * and the /auth/me that confirms who it belongs to — and the tests care about
 * both happening in that order.
 */
function mockApi({ me = USER, meStatus = 200, loginStatus = 200 } = {}) {
  const calls = [];
  global.fetch = vi.fn(async (url, options = {}) => {
    const path = String(url);
    calls.push({ path, method: options.method ?? "GET" });

    const reply = (body, status) => ({
      ok: status < 400,
      status,
      statusText: status < 400 ? "OK" : "Error",
      text: async () => JSON.stringify(body),
    });

    if (path.endsWith("/auth/me")) {
      return meStatus >= 400
        ? reply({ detail: "Token has expired" }, meStatus)
        : reply(me, 200);
    }
    if (path.endsWith("/auth/login") || path.endsWith("/auth/register")) {
      return loginStatus >= 400
        ? reply({ detail: "Incorrect email or password" }, loginStatus)
        : reply({ access_token: "fresh-token", token_type: "bearer" }, 200);
    }
    return reply({}, 200);
  });
  return calls;
}

/**
 * A probe that renders the context so the tests can assert on the DOM.
 *
 * It catches and displays failures the way a real page does — the hook
 * rejects, and the caller is responsible for the message. Letting the
 * rejection escape an onClick handler would only produce an unhandled
 * promise, which no assertion can see.
 */
function Probe() {
  const { user, loading, login, register, logout } = useAuth();
  const [error, setError] = useState("");

  const attempt = (run) => async () => {
    setError("");
    try {
      await run();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="user">{user ? user.email : "anonymous"}</span>
      <span data-testid="error">{error}</span>
      <button type="button" onClick={attempt(() => login("owner@example.com", "supersecret123"))}>
        Sign in
      </button>
      <button type="button" onClick={attempt(() => register({ email: "new@example.com" }))}>
        Register
      </button>
      <button type="button" onClick={logout}>
        Sign out
      </button>
    </div>
  );
}

function renderWithProvider() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  track.mockClear();
});

describe("AuthProvider", () => {
  describe("on boot", () => {
    it("does not call the API when there is no stored token", async () => {
      const calls = mockApi();
      renderWithProvider();

      await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
      expect(calls).toHaveLength(0);
      expect(screen.getByTestId("user")).toHaveTextContent("anonymous");
    });

    it("confirms a stored token against the server rather than trusting it", async () => {
      // A token in localStorage proves nothing: it may be expired or belong to
      // a user who has since been deleted.
      setToken("stored-token");
      const calls = mockApi();
      renderWithProvider();

      await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent(USER.email));
      expect(calls).toEqual([{ path: "/api/v1/auth/me", method: "GET" }]);
    });

    it("discards a token the server rejects", async () => {
      setToken("expired-token");
      mockApi({ meStatus: 401 });
      renderWithProvider();

      await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
      expect(getToken()).toBeNull();
      expect(screen.getByTestId("user")).toHaveTextContent("anonymous");
    });

    it("stops loading even when the confirmation fails", async () => {
      // Otherwise a dead backend leaves the app on its boot spinner forever
      // with no way to reach the login form.
      setToken("stored-token");
      mockApi({ meStatus: 500 });
      renderWithProvider();

      await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
    });
  });

  describe("signing in", () => {
    it("stores the token and loads the user behind it", async () => {
      const calls = mockApi();
      renderWithProvider();
      await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));

      await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

      await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent(USER.email));
      expect(getToken()).toBe("fresh-token");
      expect(calls.map((c) => c.path)).toEqual(["/api/v1/auth/login", "/api/v1/auth/me"]);
      expect(track).toHaveBeenCalledWith("login", { method: "password" });
    });

    it("leaves the session anonymous when the credentials are wrong", async () => {
      mockApi({ loginStatus: 401 });
      renderWithProvider();
      await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));

      // The page component is what renders the message; the hook's job is to
      // let the rejection through rather than half-signing anyone in.
      await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

      await waitFor(() =>
        expect(screen.getByTestId("error")).toHaveTextContent("Incorrect email or password"),
      );
      expect(screen.getByTestId("user")).toHaveTextContent("anonymous");
      expect(getToken()).toBeNull();
      // A refused sign-in is not a sign-in; the funnel counts accepted ones.
      expect(track).not.toHaveBeenCalledWith("login", expect.anything());
    });
  });

  describe("registering", () => {
    it("signs the new user straight in without a second round trip", async () => {
      const calls = mockApi();
      renderWithProvider();
      await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));

      await userEvent.click(screen.getByRole("button", { name: "Register" }));

      await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent(USER.email));
      expect(calls.map((c) => c.path)).toEqual(["/api/v1/auth/register", "/api/v1/auth/me"]);
      expect(track).toHaveBeenCalledWith("signup_complete", { method: "password" });
    });
  });

  describe("signing out", () => {
    it("drops both the token and the user", async () => {
      setToken("stored-token");
      mockApi();
      renderWithProvider();
      await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent(USER.email));

      await userEvent.click(screen.getByRole("button", { name: "Sign out" }));

      expect(getToken()).toBeNull();
      expect(screen.getByTestId("user")).toHaveTextContent("anonymous");
    });

    it("does not need the server to agree", async () => {
      // Signing out must work with the backend down; the token is local.
      setToken("stored-token");
      mockApi();
      renderWithProvider();
      await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent(USER.email));

      global.fetch = vi.fn(async () => {
        throw new Error("network down");
      });
      await userEvent.click(screen.getByRole("button", { name: "Sign out" }));

      expect(getToken()).toBeNull();
    });
  });
});

describe("a token that expires mid-session", () => {
  // The access token lasts 24 hours and there is no refresh flow, so this is
  // not an edge case — it is what happens to every user who leaves a tab open
  // overnight.

  it("ends the session when a request comes back 401", async () => {
    setToken("stored-token");
    mockApi();
    renderWithProvider();
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent(USER.email));

    // A later request finds the token expired. Dropping it is not enough on
    // its own: `user` stayed set, so `Protected` kept rendering, every request
    // after this went out with no Authorization header, and `/login` — which
    // is gated on `user`, not on the token — redirected straight back. The one
    // screen that could fix it was the one screen unreachable.
    global.fetch = vi.fn(async () => ({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      text: async () => JSON.stringify({ detail: "Token has expired" }),
    }));
    await expect(api.dashboard()).rejects.toThrow();

    await waitFor(() =>
      expect(screen.getByTestId("user")).toHaveTextContent("anonymous"),
    );
    expect(getToken()).toBeNull();
  });

  it("leaves a signed-in session alone when a request merely fails", async () => {
    // Only a refused credential ends the session. A 500 or a dropped
    // connection is a request to retry, not a reason to sign someone out
    // mid-upload.
    setToken("stored-token");
    mockApi();
    renderWithProvider();
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent(USER.email));

    global.fetch = vi.fn(async () => ({
      ok: false,
      status: 503,
      statusText: "Service Unavailable",
      text: async () => JSON.stringify({ detail: "The database is temporarily unavailable." }),
    }));
    await expect(api.dashboard()).rejects.toThrow();

    expect(screen.getByTestId("user")).toHaveTextContent(USER.email);
    expect(getToken()).toBe("stored-token");
  });
});

describe("useAuth", () => {
  it("fails loudly when used outside the provider", () => {
    // A silent null context turns into "cannot read property user of null"
    // several components away from the mistake.
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(/within AuthProvider/);
    quiet.mockRestore();
  });
});

describe("a business selection that outlives the membership behind it", () => {
  // `setActiveBusinessId` writes to localStorage, so it survives the tab that
  // set it. The membership it names does not have to: the other side can revoke
  // it, or the business can be deactivated, at any time. `/auth/me` resolves
  // through `get_current_business`, so the next boot asks as a business this
  // login no longer holds and is answered 403.
  function mockApi({ allow = [] } = {}) {
    const calls = [];
    global.fetch = vi.fn(async (url, options = {}) => {
      const header = options.headers?.["X-Business-Id"];
      calls.push({ path: String(url), header });
      const reply = (body, status) => ({
        ok: status < 400,
        status,
        statusText: "",
        text: async () => JSON.stringify(body),
      });
      if (header !== undefined && !allow.includes(String(header))) {
        return reply({ detail: "You do not have access to that business" }, 403);
      }
      return reply(USER, 200);
    });
    return calls;
  }

  afterEach(() => localStorage.clear());

  it("falls back to the login's own tenant rather than ending the session", async () => {
    // The session is fine and the login's own business is still there. Signing
    // the user out of an account they still hold — and doing it again on every
    // reload, because nothing clears the selection that causes it — makes a
    // revoked link look like a broken password.
    setToken("stored-token");
    setActiveBusinessId(7);
    const calls = mockApi();
    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent(USER.email));
    expect(getToken()).toBe("stored-token");
    expect(getActiveBusinessId()).toBeNull();
    // Asked twice: once as the stale business, then once as the login itself.
    expect(calls.map((c) => c.header)).toEqual(["7", undefined]);
  });

  it("ends the session when the token is what the server is refusing", async () => {
    // A 403 while a business is selected is ambiguous on its own. Retrying
    // without the header is what tells the two apart, and a second refusal
    // means the credential is the problem, not the selection.
    setToken("stored-token");
    setActiveBusinessId(7);
    global.fetch = vi.fn(async () => ({
      ok: false,
      status: 403,
      statusText: "",
      text: async () => JSON.stringify({ detail: "This business has been deactivated. Contact support to reactivate it." }),
    }));
    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
    expect(screen.getByTestId("user")).toHaveTextContent("anonymous");
    expect(getToken()).toBeNull();
  });

  it("does not retry a 403 that no business selection could have caused", async () => {
    // With nothing selected there is no header to drop, so a retry would be the
    // same request a second time.
    setToken("stored-token");
    const calls = mockApi({ allow: [] });
    global.fetch = vi.fn(async (url) => {
      calls.push({ path: String(url) });
      return {
        ok: false,
        status: 403,
        statusText: "",
        text: async () => JSON.stringify({ detail: "This business has been deactivated. Contact support to reactivate it." }),
      };
    });
    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
    expect(calls).toHaveLength(1);
    expect(getToken()).toBeNull();
  });
});

describe("a browser that will not store anything", () => {
  // The boot effect calls `getToken()` synchronously, so a `localStorage` that
  // throws used to take the provider down during commit — into the outer
  // ErrorBoundary in main.jsx, which sits above the router. Every reload hit
  // it again, and the crash screen was the entire app for a user whose browser
  // is set to block site data. This is that case, at the seam where it broke.
  afterEach(() => {
    vi.restoreAllMocks();
    setToken(null);
    setActiveBusinessId(null);
  });

  function blockStorage() {
    const real = globalThis.localStorage;
    const refuse = () => {
      throw new DOMException("The operation is insecure.", "SecurityError");
    };
    Object.defineProperty(globalThis, "localStorage", {
      value: { getItem: refuse, setItem: refuse, removeItem: refuse, clear: refuse },
      configurable: true,
      writable: true,
    });
    return () =>
      Object.defineProperty(globalThis, "localStorage", {
        value: real,
        configurable: true,
        writable: true,
      });
  }

  it("boots to the sign-in screen instead of the crash screen", async () => {
    const restore = blockStorage();
    try {
      const calls = mockApi();
      renderWithProvider();

      await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
      expect(screen.getByTestId("user")).toHaveTextContent("anonymous");
      // And no session check: there is no stored token to confirm, which is a
      // different thing from a token that could not be read.
      expect(calls).toHaveLength(0);
    } finally {
      restore();
    }
  });

  it("signs in, and holds the session for as long as the tab lives", async () => {
    const restore = blockStorage();
    try {
      mockApi();
      renderWithProvider();
      await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));

      await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

      await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent(USER.email));
      expect(screen.getByTestId("error")).toHaveTextContent("");
      expect(getToken()).toBe("fresh-token");
    } finally {
      restore();
    }
  });

  it("still signs out, on a browser that cannot forget the token either", async () => {
    const restore = blockStorage();
    try {
      mockApi();
      renderWithProvider();
      await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
      await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
      await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent(USER.email));

      await userEvent.click(screen.getByRole("button", { name: "Sign out" }));

      expect(screen.getByTestId("user")).toHaveTextContent("anonymous");
      expect(getToken()).toBeNull();
    } finally {
      restore();
    }
  });
});

describe("a session changed in another tab", () => {
  // The token lives in localStorage, which every tab shares, while `user`
  // lives in each tab's React state. Signing out in one tab left the others
  // showing the books, and their next request went out with no token — a 401
  // that, carrying no credential, was not read as the session ending. Signing
  // in as someone else was worse: this tab went on naming the old login while
  // every request it made acted on the new one's books.
  function otherTabWrites(newValue) {
    const oldValue = localStorage.getItem("gstbot_token");
    if (newValue === null) localStorage.removeItem("gstbot_token");
    else localStorage.setItem("gstbot_token", newValue);
    window.dispatchEvent(
      new StorageEvent("storage", { key: "gstbot_token", oldValue, newValue }),
    );
  }

  it("ends this tab's session when another tab signs out", async () => {
    setToken("stored-token");
    mockApi();
    renderWithProvider();
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent(USER.email));

    otherTabWrites(null);

    await waitFor(() =>
      expect(screen.getByTestId("user")).toHaveTextContent("anonymous"),
    );
  });

  it("asks who the new token belongs to when another tab signs in as someone else", async () => {
    setToken("stored-token");
    mockApi();
    renderWithProvider();
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent(USER.email));

    const calls = mockApi({ me: { ...USER, id: 2, email: "clerk@example.com" } });
    otherTabWrites("someone-elses-token");

    await waitFor(() =>
      expect(screen.getByTestId("user")).toHaveTextContent("clerk@example.com"),
    );
    expect(calls).toEqual([{ path: "/api/v1/auth/me", method: "GET" }]);
  });

  it("ignores the other keys a tab writes", async () => {
    setToken("stored-token");
    mockApi();
    renderWithProvider();
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent(USER.email));

    const calls = mockApi();
    window.dispatchEvent(new StorageEvent("storage", { key: "something_else", newValue: "x" }));
    await new Promise((r) => setTimeout(r, 0));

    expect(calls).toHaveLength(0);
    expect(screen.getByTestId("user")).toHaveTextContent(USER.email);
  });
});
