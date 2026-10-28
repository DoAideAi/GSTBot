import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../hooks/useAuth";
import { getToken, setToken } from "../lib/api";
import Shell from "./Shell";

function jsonResponse(body, { status = 200 } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    text: async () => JSON.stringify(body),
  };
}

function renderShell({ route = "/" } = {}) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AuthProvider>
        <Routes>
          <Route path="*" element={<Shell><p>Page body</p></Shell>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("Shell", () => {
  beforeEach(() => {
    localStorage.clear();
    global.fetch = vi.fn().mockResolvedValue(
      jsonResponse({ id: 1, email: "owner@acme.in", business: { legal_name: "Acme" } }),
    );
  });

  afterEach(() => vi.restoreAllMocks());

  it("renders the page it wraps", () => {
    renderShell();
    expect(screen.getByText("Page body")).toBeInTheDocument();
  });

  it("puts a skip link first, before the navigation", () => {
    renderShell();
    const skip = screen.getByRole("link", { name: "Skip to content" });
    expect(skip).toHaveAttribute("href", "#main");
    // It has to target something, or it silently does nothing.
    expect(document.querySelector("#main")).not.toBeNull();
  });

  it("keeps one navigation in the DOM at both sizes", () => {
    renderShell();
    // The drawer and the desktop row are the same element with different CSS.
    // Two navs would be two things for assistive tech to read, and two lists
    // to keep in step.
    expect(screen.getAllByRole("navigation", { name: "Main" })).toHaveLength(1);
  });

  it("starts with the mobile menu closed", () => {
    renderShell();
    expect(screen.getByRole("button", { name: "Open menu" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("opens and closes the menu on click", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: "Open menu" }));
    expect(screen.getByRole("button", { name: "Close menu" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );

    await user.click(screen.getByRole("button", { name: "Close menu" }));
    expect(screen.getByRole("button", { name: "Open menu" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("points the toggle at the nav it controls", () => {
    renderShell();
    const toggle = screen.getByRole("button", { name: "Open menu" });
    const controls = toggle.getAttribute("aria-controls");
    expect(document.getElementById(controls)).toHaveAttribute("aria-label", "Main");
  });

  it("closes the menu on Escape and returns focus to the toggle", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: "Open menu" }));
    await user.keyboard("{Escape}");

    const toggle = screen.getByRole("button", { name: "Open menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // Leaving focus on a now-hidden link strands keyboard users at the top of
    // the document with no idea where they are.
    expect(toggle).toHaveFocus();
  });

  it("closes the menu when a link is followed", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: "Open menu" }));
    await user.click(screen.getByRole("link", { name: "Invoices" }));

    // Otherwise the drawer covers the page the user just asked for.
    expect(screen.getByRole("button", { name: "Open menu" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("closes the menu when the scrim is tapped", async () => {
    const user = userEvent.setup();
    const { container } = renderShell();

    await user.click(screen.getByRole("button", { name: "Open menu" }));
    const scrim = container.querySelector(".nav-scrim");
    expect(scrim).not.toBeNull();

    await user.click(scrim);
    expect(screen.getByRole("button", { name: "Open menu" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("hides the scrim from assistive tech, since Escape is the equivalent", async () => {
    const user = userEvent.setup();
    const { container } = renderShell();

    await user.click(screen.getByRole("button", { name: "Open menu" }));
    expect(container.querySelector(".nav-scrim")).toHaveAttribute("aria-hidden", "true");
  });

  it("offers a way to reach the alerts", () => {
    renderShell();

    expect(screen.getByRole("link", { name: "Alerts" })).toHaveAttribute("href", "/alerts");
  });

  it("shows a badge when there are open alerts", async () => {
    setToken("stored-token");
    global.fetch = vi.fn((url) => {
      if (String(url).includes("/alerts")) {
        return Promise.resolve(jsonResponse({ items: [], total: 0, open_total: 5, limit: 1, offset: 0 }));
      }
      return Promise.resolve(
        jsonResponse({ id: 1, email: "owner@acme.in", business: { id: 1, legal_name: "Acme" } }),
      );
    });
    renderShell();

    expect(await screen.findByText("5")).toBeInTheDocument();
  });

  it("keeps the alerts link name stable when the badge is shown", async () => {
    setToken("stored-token");
    global.fetch = vi.fn((url) => {
      if (String(url).includes("/alerts")) {
        return Promise.resolve(jsonResponse({ items: [], total: 0, open_total: 5, limit: 1, offset: 0 }));
      }
      return Promise.resolve(
        jsonResponse({ id: 1, email: "owner@acme.in", business: { id: 1, legal_name: "Acme" } }),
      );
    });
    renderShell();

    await screen.findByText("5");
    expect(screen.getByRole("link", { name: /Alerts.*5 open/ })).toBeInTheDocument();
  });

  it("hides the badge when there are no open alerts", async () => {
    setToken("stored-token");
    global.fetch = vi.fn((url) => {
      if (String(url).includes("/alerts")) {
        return Promise.resolve(jsonResponse({ items: [], total: 0, open_total: 0, limit: 1, offset: 0 }));
      }
      return Promise.resolve(
        jsonResponse({ id: 1, email: "owner@acme.in", business: { id: 1, legal_name: "Acme" } }),
      );
    });
    renderShell();

    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(screen.queryByText(/nav-badge/)).not.toBeInTheDocument();
  });

  it("caps the badge at 99+ for large counts", async () => {
    setToken("stored-token");
    global.fetch = vi.fn((url) => {
      if (String(url).includes("/alerts")) {
        return Promise.resolve(jsonResponse({ items: [], total: 0, open_total: 150, limit: 1, offset: 0 }));
      }
      return Promise.resolve(
        jsonResponse({ id: 1, email: "owner@acme.in", business: { id: 1, legal_name: "Acme" } }),
      );
    });
    renderShell();

    expect(await screen.findByText("99+")).toBeInTheDocument();
  });

  it("marks the current route as current", () => {
    renderShell({ route: "/invoices" });
    // NavLink sets aria-current on the active route; without it the only
    // signal of where you are is a colour.
    expect(screen.getByRole("link", { name: "Invoices" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  describe("the business it says you are signed in as", () => {
    // A stored token is what makes AuthProvider fetch /auth/me at all; without
    // one it settles on anonymous and the identity block never renders.
    function signedInAs(business) {
      setToken("stored-token");
      global.fetch = vi
        .fn()
        .mockResolvedValue(jsonResponse({ id: 1, email: "owner@acme.in", business }));
    }

    it("prefers the trade name over the legal name", async () => {
      // A business is known by the name on its signboard, not the one on its
      // registration certificate. Showing "Private Limited" to someone who
      // has three firms reads as the wrong account being open.
      signedInAs({
        gstin: "27AAPFU0939F1ZV",
        legal_name: "Umang Traders Private Limited",
        trade_name: "Umang Traders",
      });
      renderShell();

      expect(await screen.findByText("Umang Traders")).toBeInTheDocument();
      expect(screen.queryByText("Umang Traders Private Limited")).not.toBeInTheDocument();
    });

    it("falls back to the legal name when no trade name is registered", async () => {
      signedInAs({ gstin: "27AAPFU0939F1ZV", legal_name: "Umang Traders Private Limited" });
      renderShell();

      expect(await screen.findByText("Umang Traders Private Limited")).toBeInTheDocument();
    });

    it("shows the GSTIN alongside it", async () => {
      // One login can hold several registrations, and the state code is the
      // only thing that tells two of them apart.
      signedInAs({ gstin: "27AAPFU0939F1ZV", legal_name: "Umang Traders Private Limited" });
      renderShell();

      expect(await screen.findByText("27AAPFU0939F1ZV")).toBeInTheDocument();
    });

    it("shows nothing at all for a user with no business yet", async () => {
      // Registration creates the user before the GSTIN is verified, so this
      // is a real state and not just a defensive guard.
      signedInAs(null);
      const { container } = renderShell();

      await screen.findByRole("button", { name: "Sign out" });
      expect(container.querySelector(".shell-business")).toBeNull();
    });
  });

  describe("the premium badge", () => {
    function signedInWithTier(tier, status = "active") {
      setToken("stored-token");
      global.fetch = vi.fn((url) => {
        const u = String(url);
        if (u.includes("/subscriptions/current")) {
          return Promise.resolve(
            jsonResponse({ id: 1, tier, status }),
          );
        }
        if (u.includes("/alerts")) {
          return Promise.resolve(
            jsonResponse({ items: [], total: 0, open_total: 0, limit: 1, offset: 0 }),
          );
        }
        return Promise.resolve(
          jsonResponse({ id: 1, email: "owner@acme.in", business: { id: 1, legal_name: "Acme" } }),
        );
      });
    }

    it("shows PRO when the user has a pro subscription", async () => {
      signedInWithTier("pro");
      renderShell();

      expect(await screen.findByText("PRO")).toBeInTheDocument();
      expect(screen.getByText("PRO").closest("a")).toHaveAttribute("href", "/pricing");
    });

    it("shows CA when the user has an enterprise subscription", async () => {
      signedInWithTier("enterprise");
      renderShell();

      expect(await screen.findByText("CA")).toBeInTheDocument();
    });

    it("shows no badge once the paid period has run out", async () => {
      // The row keeps its tier; the API reports the lapse as status "expired".
      signedInWithTier("pro", "expired");
      renderShell();

      await screen.findByRole("button", { name: "Sign out" });
      await waitFor(() => expect(global.fetch).toHaveBeenCalled());
      expect(screen.queryByText("PRO")).not.toBeInTheDocument();
    });

    it("shows no badge for free users", async () => {
      signedInWithTier("free");
      renderShell();

      await screen.findByRole("button", { name: "Sign out" });
      expect(screen.queryByText("PRO")).not.toBeInTheDocument();
      expect(screen.queryByText("CA")).not.toBeInTheDocument();
    });
  });

  describe("signing out", () => {
    it("drops the token and leaves for the login page", async () => {
      setToken("stored-token");
      const user = userEvent.setup();
      render(
        <MemoryRouter initialEntries={["/invoices"]}>
          <AuthProvider>
            <Routes>
              <Route path="/login" element={<p>Login screen</p>} />
              <Route path="*" element={<Shell><p>Page body</p></Shell>} />
            </Routes>
          </AuthProvider>
        </MemoryRouter>,
      );

      await user.click(screen.getByRole("button", { name: "Sign out" }));

      // Both halves matter: clearing the token without navigating leaves the
      // signed-out user staring at a page they can no longer load, and
      // navigating without clearing it puts them back in on the next refresh.
      await waitFor(() => expect(screen.getByText("Login screen")).toBeInTheDocument());
      expect(getToken()).toBeNull();
    });
  });
});
