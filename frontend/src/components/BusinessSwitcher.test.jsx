import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../hooks/useAuth";
import { getActiveBusinessId, setToken } from "../lib/api";
import BusinessSwitcher from "./BusinessSwitcher";

const HOME = { id: 1, gstin: "27AAPFU0939F1ZV", legal_name: "Umang Traders", plan: "free" };
const LINKED = { id: 2, gstin: "29AAPFU0939F1ZW", legal_name: "Umang Exports", plan: "free" };

/** The header control, which is also the menu toggle. */
function currentControl() {
  return screen.getByRole("button", { name: /switch business/i });
}

/**
 * A row in the open menu. Scoped to the list because the control above carries
 * the current business's name too, so an unscoped query matches both.
 */
function option(name) {
  return within(screen.getByRole("list")).getByRole("button", { name });
}

function reply(body, status = 200) {
  return {
    ok: status < 400,
    status,
    statusText: "",
    text: async () => JSON.stringify(body),
  };
}

/**
 * Route by path, and answer /auth/me according to the `X-Business-Id` actually
 * sent — the switcher's whole contract is that the header decides who the
 * server says we are, so a mock that ignored it could not tell a switch that
 * worked from one that was never sent.
 */
function mockApi({ mine, mineStatus = 200, allow = [String(LINKED.id)] } = {}) {
  const calls = [];
  global.fetch = vi.fn(async (url, options = {}) => {
    const path = String(url);
    const method = options.method ?? "GET";
    const header = options.headers?.["X-Business-Id"];
    calls.push({ path, method, header });

    if (path.endsWith("/auth/me")) {
      if (header === undefined) return reply({ id: 1, email: "a@b.in", business: HOME });
      if (!allow.includes(String(header))) {
        return reply({ detail: "You do not have access to that business" }, 403);
      }
      return reply({ id: 1, email: "a@b.in", business: LINKED });
    }
    if (path.endsWith("/businesses/mine") && method === "GET") {
      // A tick before answering, because a mock that answers within the one it
      // was called in is not a network and hid a real fault here. `load` sets
      // `loading` true and, on the same tick, false again; React coalesced the
      // pair into no change at all, no re-render followed, and the retry loop
      // this endpoint was stuck in stopped after two requests under test while
      // running unbounded in a browser. See `attempted` in the component.
      await new Promise((resolve) => setTimeout(resolve, 0));
      if (mineStatus >= 400) return reply({ detail: "Server error" }, mineStatus);
      return reply(
        mine ?? {
          items: [
            { ...HOME, role: "owner", is_home: true },
            { ...LINKED, role: "member", is_home: false },
          ],
        },
      );
    }
    if (path.endsWith("/businesses/mine/link")) {
      return reply({ ...LINKED, role: "member", is_home: false });
    }
    if (path.includes("/businesses/mine/") && method === "DELETE") {
      return { ok: true, status: 204, statusText: "", text: async () => "" };
    }
    return reply({});
  });
  return calls;
}

async function renderSwitcher(options) {
  const calls = mockApi(options);
  setToken("a-token");
  render(
    <AuthProvider>
      <BusinessSwitcher />
    </AuthProvider>,
  );
  // The control only exists once /auth/me has said which business is current.
  await screen.findByText(HOME.legal_name);
  return calls;
}

describe("BusinessSwitcher", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("shows the business the request is currently acting for", async () => {
    await renderSwitcher();
    expect(screen.getByText(HOME.legal_name)).toBeInTheDocument();
    expect(screen.getByText(HOME.gstin)).toBeInTheDocument();
  });

  it("does not ask for the business list until the menu is opened", async () => {
    // Most logins hold one registration and never open this. The header is on
    // every page, so an eager fetch is a request per page load that nobody reads.
    const calls = await renderSwitcher();
    expect(calls.some((c) => c.path.endsWith("/businesses/mine"))).toBe(false);

    await userEvent.click(currentControl());
    await waitFor(() =>
      expect(calls.some((c) => c.path.endsWith("/businesses/mine"))).toBe(true),
    );
  });

  it("sends X-Business-Id on every request once another registration is chosen", async () => {
    const calls = await renderSwitcher();
    await userEvent.click(currentControl());
    await userEvent.click(await screen.findByRole("button", { name: /^Umang Exports/ }));

    await waitFor(() => expect(screen.getByText(LINKED.gstin)).toBeInTheDocument());
    expect(getActiveBusinessId()).toBe(String(LINKED.id));
    // Confirmed against the server before it was believed, not just written.
    expect(
      calls.some((c) => c.path.endsWith("/auth/me") && c.header === String(LINKED.id)),
    ).toBe(true);
  });

  it("keeps acting for the current business when the switch is refused", async () => {
    // Written-then-confirmed: the selection is sent on every later request, so
    // a refused switch that left it in place would point the whole app at a
    // business the backend answers 403 for, one page at a time.
    await renderSwitcher({ allow: [] });
    await userEvent.click(currentControl());
    await userEvent.click(await screen.findByRole("button", { name: /^Umang Exports/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/do not have access/i);
    expect(getActiveBusinessId()).toBeNull();
    // Scoped to the control, not the page: the menu is deliberately still open
    // behind it, so the home GSTIN is on screen twice.
    expect(within(currentControl()).getByText(HOME.gstin)).toBeInTheDocument();
  });

  it("says the list could not be loaded rather than showing no registrations", async () => {
    // "You hold one business" and "we never found out" are different answers,
    // and only one of them means the link you just made did not save.
    await renderSwitcher({ mineStatus: 500 });
    await userEvent.click(currentControl());
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Umang Exports/ })).not.toBeInTheDocument();
  });

  it("asks once for a list that fails, however long the menu is left open", async () => {
    // The failure used to re-arm the fetch that produced it: the effect fired
    // on `businesses === null`, and a refusal is recorded by leaving it null.
    // Every refusal therefore asked again immediately — 149 requests a second
    // against a 5ms reply, on an endpoint metered by identity, for as long as
    // the menu stayed open.
    const calls = await renderSwitcher({ mineStatus: 500 });
    await userEvent.click(currentControl());
    await screen.findByRole("alert");
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(calls.filter((c) => c.path.endsWith("/businesses/mine")).length).toBe(1);
  });

  it("asks again when the menu is closed and reopened after a failure", async () => {
    // Which is why the attempt is forgotten on close rather than held for the
    // session: a panel saying it could not load has to have some gesture that
    // tries again, and closing and reopening it is the one people make.
    const calls = await renderSwitcher({ mineStatus: 500 });
    await userEvent.click(currentControl());
    await screen.findByRole("alert");

    await userEvent.click(currentControl());
    await userEvent.click(currentControl());
    await waitFor(() =>
      expect(calls.filter((c) => c.path.endsWith("/businesses/mine")).length).toBe(2),
    );
  });

  it("does not ask again when a list it already holds is reopened", async () => {
    // The counterpart: forgetting the attempt must not throw away the answer.
    const calls = await renderSwitcher();
    await userEvent.click(currentControl());
    await screen.findByRole("button", { name: /^Umang Exports/ });

    await userEvent.click(currentControl());
    await userEvent.click(currentControl());
    await screen.findByRole("button", { name: /^Umang Exports/ });
    expect(calls.filter((c) => c.path.endsWith("/businesses/mine")).length).toBe(1);
  });

  it("offers no unlink for the login's own tenant", async () => {
    // There is no membership row behind it to revoke and the server refuses;
    // a button whose only outcome is an error is worse than no button.
    await renderSwitcher();
    await userEvent.click(currentControl());
    await screen.findByRole("button", { name: /^Umang Exports/ });
    expect(
      screen.queryByRole("button", { name: /Unlink Umang Traders/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Unlink Umang Exports/ })).toBeInTheDocument();
  });

  it("steps back to the home tenant when the business being acted for is unlinked", async () => {
    // Otherwise every later request carries a header the server has just
    // stopped honouring, and the app 403s a page at a time with nothing on
    // screen explaining why.
    await renderSwitcher();
    await userEvent.click(currentControl());
    await userEvent.click(await screen.findByRole("button", { name: /^Umang Exports/ }));
    await waitFor(() => expect(getActiveBusinessId()).toBe(String(LINKED.id)));

    await userEvent.click(currentControl());
    await userEvent.click(await screen.findByRole("button", { name: /Unlink Umang Exports/ }));

    await waitFor(() => expect(getActiveBusinessId()).toBeNull());
    await waitFor(() =>
      expect(within(currentControl()).getByText(HOME.gstin)).toBeInTheDocument(),
    );
  });

  it("closes on Escape and puts focus back on the control that opened it", async () => {
    await renderSwitcher();
    const toggle = currentControl();
    await userEvent.click(toggle);
    await screen.findByText("Your registrations");

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByText("Your registrations")).not.toBeInTheDocument();
    expect(toggle).toHaveFocus();
  });
  it("closes when the click lands outside the menu", async () => {
    await renderSwitcher();
    await userEvent.click(currentControl());
    await screen.findByText("Your registrations");

    await userEvent.click(document.body);
    await waitFor(() =>
      expect(screen.queryByText("Your registrations")).not.toBeInTheDocument(),
    );
  });

  it("just closes when the business already being acted for is chosen again", async () => {
    // No request, and above all no write: re-selecting the home tenant through
    // `switchBusiness` would store an explicit `X-Business-Id` for the business
    // that is the default anyway, which then has to survive being revoked.
    const calls = await renderSwitcher();
    await userEvent.click(currentControl());
    await screen.findByRole("list");
    await userEvent.click(option(/^Umang Traders/));

    await waitFor(() =>
      expect(screen.queryByText("Your registrations")).not.toBeInTheDocument(),
    );
    expect(getActiveBusinessId()).toBeNull();
    expect(calls.filter((c) => c.path.endsWith("/auth/me"))).toHaveLength(1);
  });

  it("says why an unlink was refused rather than dropping the row silently", async () => {
    await renderSwitcher();
    await userEvent.click(currentControl());
    await screen.findByRole("button", { name: /^Umang Exports/ });

    global.fetch.mockResolvedValueOnce(reply({ detail: "Not linked." }, 404));
    await userEvent.click(screen.getByRole("button", { name: /Unlink Umang Exports/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Not linked.");
    expect(screen.getByRole("button", { name: /^Umang Exports/ })).toBeInTheDocument();
  });

  it("directs client access through invitations without collecting another password", async () => {
    await renderSwitcher();
    await userEvent.click(currentControl());
    expect(await screen.findByRole("link", { name: "Manage client invitations" })).toHaveAttribute("href", "/client-access");
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(screen.getByText(/Keep passwords private/)).toBeInTheDocument();
  });

  it("keeps invitation management reachable when the client list is empty", async () => {
    await renderSwitcher({ mine: {} });
    await userEvent.click(currentControl());
    expect(await screen.findByRole("link", { name: "Manage client invitations" })).toBeInTheDocument();
  });

});
