import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getToken } from "../lib/api";
import ForgotPasswordPage from "./ForgotPasswordPage";
import ResetPasswordPage from "./ResetPasswordPage";

// There was no way back from a forgotten password: no link, no page, no reset.

function respond(status, body) {
  return Promise.resolve({
    ok: status < 400,
    status,
    statusText: "",
    text: () => Promise.resolve(JSON.stringify(body)),
  });
}

describe("ForgotPasswordPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("asks for the link and says what happens next, whoever the address is", async () => {
    global.fetch = vi.fn(() =>
      respond(202, { detail: "If an account signs in with that email and a password, a link to reset it is on its way." }),
    );
    render(
      <MemoryRouter>
        <ForgotPasswordPage />
      </MemoryRouter>,
    );
    await userEvent.type(screen.getByLabelText("Email"), "owner@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Email me a link" }));

    expect(await screen.findByRole("status")).toHaveTextContent("a link to reset it is on its way");
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe("/api/v1/auth/forgot-password");
    expect(JSON.parse(init.body)).toEqual({ email: "owner@example.com" });
  });
});

describe("ResetPasswordPage", () => {
  let replace;

  beforeEach(() => {
    localStorage.clear();
    replace = vi.fn();
    vi.stubGlobal("location", { ...window.location, replace });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function land(hash = "#token=reset-tok") {
    render(
      <MemoryRouter initialEntries={[`/reset-password${hash}`]}>
        <ResetPasswordPage />
      </MemoryRouter>,
    );
  }

  async function choose(next, confirm = next) {
    await userEvent.type(screen.getByLabelText("New password"), next);
    await userEvent.type(screen.getByLabelText("Confirm new password"), confirm);
    await userEvent.click(screen.getByRole("button", { name: "Set new password" }));
  }

  it("sets the password with the link's token and signs in", async () => {
    global.fetch = vi.fn(() => respond(200, { access_token: "fresh", token_type: "bearer" }));
    land();
    await choose("a-fresh-long-passphrase");

    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe("/api/v1/auth/reset-password");
    expect(JSON.parse(init.body)).toEqual({ token: "reset-tok", new_password: "a-fresh-long-passphrase" });
    await vi.waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
    expect(getToken()).toBe("fresh");
  });

  it("shows why a used or expired link was refused", async () => {
    global.fetch = vi.fn(() =>
      respond(400, { detail: "This reset link has expired or has already been used. Ask for a new one." }),
    );
    land();
    await choose("a-fresh-long-passphrase");

    expect(await screen.findByRole("alert")).toHaveTextContent("already been used");
    expect(screen.getByRole("link", { name: /new link/i })).toHaveAttribute("href", "/forgot-password");
  });

  it("catches a mistyped confirmation before asking the server", async () => {
    global.fetch = vi.fn();
    land();
    await choose("a-fresh-long-passphrase", "a-fresh-long-passphrasf");

    expect(await screen.findByRole("alert")).toHaveTextContent("do not match");
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("says so when it was opened without a link", () => {
    land("");
    expect(screen.getByRole("alert")).toHaveTextContent("link");
  });
});

describe("the sign-in form", () => {
  it("offers a way back from a forgotten password", async () => {
    const { default: AuthForm } = await import("../components/AuthForm");
    const { StubAuth } = await import("../test/auth");
    render(
      <MemoryRouter>
        <StubAuth>
          <AuthForm />
        </StubAuth>
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("tab", { name: /sign in/i }));
    expect(screen.getByRole("link", { name: "Forgot your password?" })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
  });
});
