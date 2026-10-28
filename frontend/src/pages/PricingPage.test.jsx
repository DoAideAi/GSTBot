import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthContext } from "../hooks/useAuth";
import { StubAuth } from "../test/auth";
import PricingPage from "./PricingPage";

const mockTrack = vi.fn();
vi.mock("../lib/track", () => ({ track: (...args) => mockTrack(...args) }));

const PRICING_RESPONSE = {
  tiers: {
    free: {
      name: "Free Tools",
      price_display: "Free forever",
      price_monthly: 0,
      price_annual: 0,
      features: ["GST calculator", "GSTIN lookup & verification", "HSN/SAC code search"],
    },
    pro: {
      name: "SMB",
      price_display: "₹499/month",
      price_monthly: 49900,
      price_annual: 499900,
      features: ["GST filing assistance", "Bulk GSTIN lookup", "Saved calculations & history", "Email reports"],
    },
    enterprise: {
      name: "CA",
      price_display: "₹2,999/month",
      price_monthly: 299900,
      price_annual: 2999000,
      features: ["Everything in SMB", "Multi-client management", "Bulk filing", "API access"],
    },
  },
};

const SUBSCRIPTION_RESPONSE = {
  id: 1,
  tier: "free",
  status: "active",
  razorpay_subscription_id: null,
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

function renderPage({ authenticated = true } = {}) {
  if (authenticated) {
    return render(
      <MemoryRouter>
        <StubAuth>
          <PricingPage />
        </StubAuth>
      </MemoryRouter>,
    );
  }
  return render(
    <MemoryRouter>
      <PricingPage />
    </MemoryRouter>,
  );
}

describe("PricingPage", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("shows all three tiers", async () => {
    mockFetch(PRICING_RESPONSE, SUBSCRIPTION_RESPONSE);
    renderPage();

    expect(await screen.findByText("Free Tools")).toBeInTheDocument();
    expect(screen.getByText("SMB")).toBeInTheDocument();
    expect(screen.getByText("CA")).toBeInTheDocument();
  });

  it("shows prices for each tier", async () => {
    mockFetch(PRICING_RESPONSE, SUBSCRIPTION_RESPONSE);
    renderPage();

    expect(await screen.findByText("Free forever")).toBeInTheDocument();
    expect(screen.getByText("₹499")).toBeInTheDocument();
    expect(screen.getByText("₹2,999")).toBeInTheDocument();
    expect(screen.getAllByText("/month")).toHaveLength(2);
  });

  it("switches to annual pricing when the toggle is clicked", async () => {
    mockFetch(PRICING_RESPONSE, SUBSCRIPTION_RESPONSE);
    renderPage();

    await screen.findByText("Free forever");
    fireEvent.click(screen.getByRole("radio", { name: /Annual/ }));

    expect(screen.getByText("₹417")).toBeInTheDocument();
    expect(screen.getByText(/Billed ₹4,999\/year/)).toBeInTheDocument();
  });

  it("lists features for each tier", async () => {
    mockFetch(PRICING_RESPONSE, SUBSCRIPTION_RESPONSE);
    renderPage();

    expect(await screen.findByText("GST calculator")).toBeInTheDocument();
    expect(screen.getByText("GST filing assistance")).toBeInTheDocument();
    expect(screen.getByText("Multi-client management")).toBeInTheDocument();
  });

  it("highlights the Pro tier as most popular", async () => {
    mockFetch(PRICING_RESPONSE, SUBSCRIPTION_RESPONSE);
    renderPage();

    expect(await screen.findByText("Most Popular")).toBeInTheDocument();
  });

  it("marks the current plan", async () => {
    mockFetch(PRICING_RESPONSE, SUBSCRIPTION_RESPONSE);
    renderPage();

    expect(await screen.findByRole("button", { name: "Current plan" })).toBeDisabled();
  });

  it("offers subscribe buttons for non-current tiers", async () => {
    mockFetch(PRICING_RESPONSE, SUBSCRIPTION_RESPONSE);
    renderPage();

    expect(await screen.findAllByRole("button", { name: "Subscribe" })).toHaveLength(2);
  });

  it("offers cancel when on a paid plan", async () => {
    mockFetch(PRICING_RESPONSE, { ...SUBSCRIPTION_RESPONSE, tier: "pro" });
    renderPage();

    expect(await screen.findByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("asks before cancelling, and sends nothing when the answer is no", async () => {
    mockFetch(PRICING_RESPONSE, { ...SUBSCRIPTION_RESPONSE, tier: "pro" });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    try {
      renderPage();
      fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
      expect(confirm).toHaveBeenCalledTimes(1);
      const urls = global.fetch.mock.calls.map(([url]) => String(url));
      expect(urls.some((u) => u.includes("/subscriptions/cancel"))).toBe(false);
    } finally {
      confirm.mockRestore();
    }
  });

  it("offers the plans again once a paid period has run out", async () => {
    // An expired PRO row is not the plan the business is on: no Cancel, and
    // PRO is something to buy again rather than "Current plan".
    mockFetch(PRICING_RESPONSE, { ...SUBSCRIPTION_RESPONSE, tier: "pro", status: "expired" });
    renderPage();

    expect(await screen.findAllByRole("button", { name: "Subscribe" })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("offers downgrade to free when on a paid plan", async () => {
    mockFetch(PRICING_RESPONSE, { ...SUBSCRIPTION_RESPONSE, tier: "pro" });
    renderPage();

    expect(await screen.findByRole("button", { name: "Downgrade" })).toBeInTheDocument();
  });

  it("shows loading state", () => {
    global.fetch = vi.fn(() => new Promise(() => {}));
    renderPage();

    expect(screen.getByText("Loading pricing...")).toBeInTheDocument();
  });

  it("shows error when pricing fails to load", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "",
      text: async () => JSON.stringify({ detail: "Server error" }),
    });
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent(/Server error/);
  });

  it("fires pricing_view tracking event on mount", async () => {
    mockFetch(PRICING_RESPONSE, SUBSCRIPTION_RESPONSE);
    renderPage();

    await screen.findByText("Free Tools");

    expect(mockTrack).toHaveBeenCalledWith("pricing_view");
  });

  it("sends a signed-out visitor to sign in instead of a dead button", async () => {
    mockFetch(PRICING_RESPONSE);
    const noAuth = {
      user: null,
      loading: false,
      canWrite: false,
      login: () => {},
      register: () => {},
      logout: () => {},
      switchBusiness: () => {},
    };

    render(
      <MemoryRouter>
        <AuthContext.Provider value={noAuth}>
          <PricingPage />
        </AuthContext.Provider>
      </MemoryRouter>,
    );

    const links = await screen.findAllByRole("link", { name: "Sign in to subscribe" });
    expect(links.length).toBeGreaterThan(0);
    links.forEach((link) => expect(link).toHaveAttribute("href", "/login"));
    expect(screen.queryByRole("button", { name: "Sign in to subscribe" })).toBeNull();
  });
});
