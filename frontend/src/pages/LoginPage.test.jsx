import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../hooks/useAuth";
import LoginPage from "./LoginPage";

function jsonResponse(body, { status = 200 } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    text: async () => JSON.stringify(body),
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <LoginPage />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    localStorage.clear();
    global.fetch = vi.fn();
  });

  afterEach(() => vi.restoreAllMocks());

  it("signs in and stores the session", async () => {
    const user = userEvent.setup();
    global.fetch
      .mockResolvedValueOnce(jsonResponse({ access_token: "tok-1" }))
      .mockResolvedValueOnce(jsonResponse({ email: "owner@example.com", business: {} }));

    renderPage();
    await user.click(screen.getByRole("tab", { name: "Sign in" }));
    await user.type(screen.getByLabelText("Email"), "owner@example.com");
    await user.type(screen.getByLabelText("Password"), "supersecret123");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(localStorage.getItem("gstbot_token")).toBe("tok-1"));
  });

  it("shows the server's message when sign-in fails", async () => {
    const user = userEvent.setup();
    global.fetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Incorrect email or password" }, { status: 401 }),
    );

    renderPage();
    await user.click(screen.getByRole("tab", { name: "Sign in" }));
    await user.type(screen.getByLabelText("Email"), "owner@example.com");
    await user.type(screen.getByLabelText("Password"), "wrongpassword");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password");
  });

  it("hides GSTIN behind a toggle in register mode", () => {
    renderPage();

    expect(screen.getByText(/Have a GSTIN/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/GSTIN/)).not.toBeInTheDocument();
  });

  it("reveals GSTIN fields when the toggle is clicked", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText(/Have a GSTIN/));

    expect(screen.getByLabelText(/GSTIN/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Legal name/)).toBeInTheDocument();
  });

  it("confirms a valid GSTIN against the server", async () => {
    const user = userEvent.setup();
    global.fetch.mockResolvedValue(
      jsonResponse({ valid: true, state_name: "Maharashtra", pan: "AAPFU0939F" }),
    );

    renderPage();
    await user.click(screen.getByText(/Have a GSTIN/));
    await user.type(screen.getByLabelText(/GSTIN/), "27AAPFU0939F1ZV");

    expect(await screen.findByText(/Valid — Maharashtra/)).toBeInTheDocument();
  });

  it("reports a bad check digit before the form is submitted", async () => {
    const user = userEvent.setup();
    global.fetch.mockResolvedValue(
      jsonResponse({ valid: false, error: "GSTIN check digit does not match" }),
    );

    renderPage();
    await user.click(screen.getByText(/Have a GSTIN/));
    await user.type(screen.getByLabelText(/GSTIN/), "27AAPFU0939F1ZW");

    expect(await screen.findByText(/check digit does not match/)).toBeInTheDocument();
  });

  describe("a GSTIN the user is still correcting", () => {
    function deferredChecks() {
      const pending = [];
      global.fetch = vi.fn(
        (url) =>
          new Promise((resolve) => {
            pending.push({
              url: String(url),
              answer: (body) => resolve(jsonResponse(body)),
            });
          }),
      );
      return pending;
    }

    const VALID = { valid: true, state_name: "Maharashtra", pan: "AAPFU0939F" };
    const BAD = { valid: false, error: "GSTIN check digit does not match" };

    it("ignores a verdict about a GSTIN that has since been retyped", async () => {
      const user = userEvent.setup();
      const pending = deferredChecks();

      renderPage();
      await user.click(screen.getByText(/Have a GSTIN/));
      const field = screen.getByLabelText(/GSTIN/);

      await user.type(field, "27AAPFU0939F1ZW");
      await waitFor(() => expect(pending).toHaveLength(1));

      await user.type(field, "{backspace}V");
      await waitFor(() => expect(pending).toHaveLength(2));

      expect(pending[1].url).toContain("27AAPFU0939F1ZV");
      pending[1].answer(VALID);
      expect(await screen.findByText(/Valid — Maharashtra/)).toBeInTheDocument();

      pending[0].answer(BAD);

      await waitFor(() =>
        expect(screen.getByText(/Valid — Maharashtra/)).toBeInTheDocument(),
      );
      expect(screen.queryByText(/check digit does not match/)).not.toBeInTheDocument();
    });

    it("does not clear a live verdict because a superseded check failed", async () => {
      const user = userEvent.setup();
      const pending = [];
      global.fetch = vi.fn(
        (url) =>
          new Promise((resolve) => {
            pending.push({
              url: String(url),
              answer: (body) => resolve(jsonResponse(body)),
              refuse: () => resolve(jsonResponse({ detail: "Too many requests" }, { status: 429 })),
            });
          }),
      );

      renderPage();
      await user.click(screen.getByText(/Have a GSTIN/));
      const field = screen.getByLabelText(/GSTIN/);

      await user.type(field, "27AAPFU0939F1ZW");
      await waitFor(() => expect(pending).toHaveLength(1));

      await user.type(field, "{backspace}V");
      await waitFor(() => expect(pending).toHaveLength(2));

      pending[1].answer(VALID);
      expect(await screen.findByText(/Valid — Maharashtra/)).toBeInTheDocument();

      pending[0].refuse();

      await waitFor(() =>
        expect(screen.getByText(/Valid — Maharashtra/)).toBeInTheDocument(),
      );
    });

    it("does not put a verdict back under an incomplete GSTIN", async () => {
      const user = userEvent.setup();
      const pending = deferredChecks();

      renderPage();
      await user.click(screen.getByText(/Have a GSTIN/));
      const field = screen.getByLabelText(/GSTIN/);

      await user.type(field, "27AAPFU0939F1ZV");
      await waitFor(() => expect(pending).toHaveLength(1));

      await user.type(field, "{backspace}");
      pending[0].answer(VALID);

      await waitFor(() => expect(field).toHaveValue("27AAPFU0939F1Z"));
      expect(screen.queryByText(/Valid — Maharashtra/)).not.toBeInTheDocument();
    });
  });

  it("registers with the normalized GSTIN", async () => {
    const user = userEvent.setup();
    global.fetch
      .mockResolvedValueOnce(jsonResponse({ valid: true, state_name: "Maharashtra" }))
      .mockResolvedValueOnce(jsonResponse({ access_token: "tok-2" }))
      .mockResolvedValueOnce(jsonResponse({ email: "new@example.com", business: {} }));

    renderPage();
    await user.click(screen.getByText(/Have a GSTIN/));
    await user.type(screen.getByLabelText(/GSTIN/), "27aapfu0939f1zv");
    await user.type(screen.getByLabelText(/Legal name/), "Umang Traders Private Limited");
    await user.type(screen.getByLabelText("Email"), "new@example.com");
    await user.type(screen.getByLabelText("Password"), "supersecret123");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => {
      const registerCall = global.fetch.mock.calls.find(
        ([url]) => url === "/api/v1/auth/register",
      );
      expect(registerCall).toBeDefined();
      expect(JSON.parse(registerCall[1].body).gstin).toBe("27AAPFU0939F1ZV");
    });
  });

  it("sends null for optional fields left empty", async () => {
    const user = userEvent.setup();
    global.fetch
      .mockResolvedValueOnce(jsonResponse({ valid: true, state_name: "Maharashtra" }))
      .mockResolvedValueOnce(jsonResponse({ access_token: "tok-4" }))
      .mockResolvedValueOnce(jsonResponse({ email: "new@example.com", business: {} }));

    renderPage();
    await user.click(screen.getByText(/Have a GSTIN/));
    await user.type(screen.getByLabelText(/GSTIN/), "27aapfu0939f1zv");
    await user.type(screen.getByLabelText(/Legal name/), "Umang Traders Private Limited");
    await user.type(screen.getByLabelText("Email"), "new@example.com");
    await user.type(screen.getByLabelText("Password"), "supersecret123");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => {
      const registerCall = global.fetch.mock.calls.find(
        ([url]) => url === "/api/v1/auth/register",
      );
      expect(registerCall).toBeDefined();
      expect(JSON.parse(registerCall[1].body)).toMatchObject({
        trade_name: null,
        full_name: null,
      });
    });
  });

  describe("validation", () => {
    async function goToSignIn(user) {
      await user.click(screen.getByRole("tab", { name: "Sign in" }));
    }

    function registered() {
      return global.fetch.mock.calls.some(([url]) => String(url).includes("/auth/register"));
    }

    it("blocks a GSTIN the server refused without saying why", async () => {
      const user = userEvent.setup();
      global.fetch.mockResolvedValueOnce(jsonResponse({ valid: false }));

      renderPage();
      await user.click(screen.getByText(/Have a GSTIN/));
      await user.type(screen.getByLabelText(/GSTIN/), "27AAPFU0939F1ZV");
      await user.type(screen.getByLabelText(/Legal name/), "Umang Traders Private Limited");
      await user.type(screen.getByLabelText("Email"), "new@example.com");
      await user.type(screen.getByLabelText("Password"), "supersecret123");
      await user.click(screen.getByRole("button", { name: "Create account" }));

      expect(await screen.findByText("That GSTIN is not valid.")).toBeInTheDocument();
      expect(registered()).toBe(false);
    });

    it("asks for the email rather than sending a doomed request", async () => {
      const user = userEvent.setup();
      renderPage();

      await goToSignIn(user);
      await user.click(screen.getByRole("button", { name: "Sign in" }));

      expect(await screen.findByText("Enter your email.")).toBeInTheDocument();
      expect(global.fetch).not.toHaveBeenCalled();
    });

    it("asks for the password too", async () => {
      const user = userEvent.setup();
      renderPage();

      await goToSignIn(user);
      await user.type(screen.getByLabelText("Email"), "owner@example.com");
      await user.click(screen.getByRole("button", { name: "Sign in" }));

      expect(await screen.findByText("Enter your password.")).toBeInTheDocument();
      expect(global.fetch).not.toHaveBeenCalled();
    });

    it("registers without a GSTIN", async () => {
      const user = userEvent.setup();
      global.fetch
        .mockResolvedValueOnce(jsonResponse({ access_token: "tok-no-gstin" }))
        .mockResolvedValueOnce(jsonResponse({ email: "owner@example.com", business: {} }));

      renderPage();

      await user.type(screen.getByLabelText("Email"), "owner@example.com");
      await user.type(screen.getByLabelText("Password"), "supersecret123");
      await user.click(screen.getByRole("button", { name: "Create account" }));

      await waitFor(() => {
        const registerCall = global.fetch.mock.calls.find(
          ([url]) => url === "/api/v1/auth/register",
        );
        expect(registerCall).toBeDefined();
        expect(JSON.parse(registerCall[1].body).gstin).toBeNull();
      });
    });

    it("refuses a short password before the server does", async () => {
      const user = userEvent.setup();
      renderPage();

      await user.type(screen.getByLabelText("Email"), "owner@example.com");
      await user.type(screen.getByLabelText("Password"), "short");
      await user.click(screen.getByRole("button", { name: "Create account" }));

      expect(await screen.findByText("Use at least 8 characters.")).toBeInTheDocument();
      expect(registered()).toBe(false);
    });

    it("requires a legal name when a GSTIN is provided", async () => {
      const user = userEvent.setup();
      renderPage();

      await user.click(screen.getByText(/Have a GSTIN/));
      await user.type(screen.getByLabelText(/GSTIN/), "27AAPFU0939F1ZV");
      await user.type(screen.getByLabelText("Email"), "owner@example.com");
      await user.type(screen.getByLabelText("Password"), "supersecret123");
      await user.click(screen.getByRole("button", { name: "Create account" }));

      expect(await screen.findByText(/Legal name is required/)).toBeInTheDocument();
      expect(registered()).toBe(false);
    });

    it("rejects a misshapen GSTIN without asking the server", async () => {
      const user = userEvent.setup();
      renderPage();

      await user.click(screen.getByText(/Have a GSTIN/));
      await user.type(screen.getByLabelText(/GSTIN/), "27AAPF00939F1ZV");

      expect(await screen.findByText(/does not look like a GSTIN/)).toBeInTheDocument();
      expect(global.fetch).not.toHaveBeenCalled();
    });

    it("marks the invalid field for assistive tech", async () => {
      const user = userEvent.setup();
      renderPage();

      await goToSignIn(user);
      await user.click(screen.getByRole("button", { name: "Sign in" }));

      const email = screen.getByLabelText("Email");
      await waitFor(() => expect(email).toHaveAttribute("aria-invalid", "true"));
      const describedBy = email.getAttribute("aria-describedby");
      expect(document.getElementById(describedBy)).toHaveTextContent("Enter your email.");
    });

    it("still asks the server about a well-shaped GSTIN", async () => {
      const user = userEvent.setup();
      global.fetch.mockResolvedValueOnce(
        jsonResponse({ valid: true, state_name: "Maharashtra", pan: "AAPFU0939F" }),
      );

      renderPage();
      await user.click(screen.getByText(/Have a GSTIN/));
      await user.type(screen.getByLabelText(/GSTIN/), "27AAPFU0939F1ZV");

      expect(await screen.findByText(/Maharashtra/)).toBeInTheDocument();
    });

    it("blocks registration when the server said the GSTIN is invalid", async () => {
      const user = userEvent.setup();
      global.fetch.mockResolvedValueOnce(
        jsonResponse({ valid: false, error: "Checksum does not match" }),
      );

      renderPage();
      await user.click(screen.getByText(/Have a GSTIN/));
      await user.type(screen.getByLabelText(/GSTIN/), "27AAPFU0939F1ZZ");
      await screen.findByText("Checksum does not match");

      await user.type(screen.getByLabelText(/Legal name/), "Acme Supplies");
      await user.type(screen.getByLabelText("Email"), "owner@example.com");
      await user.type(screen.getByLabelText("Password"), "supersecret123");
      await user.click(screen.getByRole("button", { name: "Create account" }));

      expect(registered()).toBe(false);
      expect(await screen.findByText("Checksum does not match")).toBeInTheDocument();
    });

    it("asks for the email when registering, not just when signing in", async () => {
      const user = userEvent.setup();
      renderPage();

      await user.type(screen.getByLabelText("Password"), "supersecret123");
      await user.click(screen.getByRole("button", { name: "Create account" }));

      expect(await screen.findByText("Enter your email.")).toBeInTheDocument();
      expect(registered()).toBe(false);
    });

    it("says so when the email is not shaped like one", async () => {
      const user = userEvent.setup();
      renderPage();

      await user.type(screen.getByLabelText("Email"), "owner@acme");
      await user.type(screen.getByLabelText("Password"), "supersecret123");
      await user.click(screen.getByRole("button", { name: "Create account" }));

      expect(await screen.findByText(/does not look like an email/)).toBeInTheDocument();
      expect(registered()).toBe(false);
    });
  });

  describe("switching between the two tabs", () => {
    it("does not leave a registration complaint on the sign-in form", async () => {
      const user = userEvent.setup();
      renderPage();

      await user.type(screen.getByLabelText("Password"), "short");
      await user.click(screen.getByRole("button", { name: "Create account" }));
      expect(await screen.findByText("Use at least 8 characters.")).toBeInTheDocument();

      await user.click(screen.getByRole("tab", { name: "Sign in" }));

      expect(screen.queryByText("Use at least 8 characters.")).not.toBeInTheDocument();
    });

    it("does not leave a sign-in complaint on the registration form", async () => {
      const user = userEvent.setup();
      renderPage();

      await user.click(screen.getByRole("tab", { name: "Sign in" }));
      await user.click(screen.getByRole("button", { name: "Sign in" }));
      expect(await screen.findByText("Enter your email.")).toBeInTheDocument();

      await user.click(screen.getByRole("tab", { name: "Create account" }));
      expect(screen.queryByText("Enter your email.")).not.toBeInTheDocument();
    });

    it("drops a GSTIN verdict about a value the user has moved on from", async () => {
      const user = userEvent.setup();
      global.fetch.mockResolvedValueOnce(
        jsonResponse({ valid: true, state_name: "Maharashtra", pan: "AAPFU0939F" }),
      );

      renderPage();
      await user.click(screen.getByText(/Have a GSTIN/));
      await user.type(screen.getByLabelText(/GSTIN/), "27AAPFU0939F1ZV");
      expect(await screen.findByText(/Maharashtra/)).toBeInTheDocument();

      await user.click(screen.getByRole("tab", { name: "Sign in" }));
      await user.click(screen.getByRole("tab", { name: "Create account" }));

      expect(screen.queryByText(/Maharashtra/)).not.toBeInTheDocument();
    });

    it("resets GSTIN toggle when switching tabs", async () => {
      const user = userEvent.setup();
      renderPage();

      await user.click(screen.getByText(/Have a GSTIN/));
      expect(screen.getByLabelText(/GSTIN/)).toBeInTheDocument();

      await user.click(screen.getByRole("tab", { name: "Sign in" }));
      await user.click(screen.getByRole("tab", { name: "Create account" }));

      expect(screen.queryByLabelText(/GSTIN/)).not.toBeInTheDocument();
      expect(screen.getByText(/Have a GSTIN/)).toBeInTheDocument();
    });
  });
});
