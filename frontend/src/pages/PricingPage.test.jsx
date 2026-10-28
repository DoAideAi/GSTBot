import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

  it("says when a paid plan ends, and that it does not renew on its own", async () => {
    const end = new Date(Date.now() + 30 * 24 * 3600 * 1000).toISOString();
    mockFetch(PRICING_RESPONSE, { ...SUBSCRIPTION_RESPONSE, tier: "pro", current_period_end: end });
    renderPage();

    expect(await screen.findByText(/Paid until/)).toHaveTextContent("It does not renew on its own.");
    expect(screen.getByRole("button", { name: "Extend by a month" })).toHaveClass("btn-ghost");
  });

  it("calls out the renewal in the last week", async () => {
    const end = new Date(Date.now() + 3 * 24 * 3600 * 1000).toISOString();
    mockFetch(PRICING_RESPONSE, { ...SUBSCRIPTION_RESPONSE, tier: "pro", current_period_end: end });
    renderPage();

    expect(await screen.findByText(/Paid until/)).toHaveTextContent(/extend it to keep your paid features/);
    expect(screen.getByRole("button", { name: "Extend by a month" })).toHaveClass("btn-primary");
  });

  it("says nothing about an end date for a plan sold without one", async () => {
    mockFetch(PRICING_RESPONSE, { ...SUBSCRIPTION_RESPONSE, tier: "pro" });
    renderPage();
    await screen.findByRole("button", { name: "Cancel" });
    expect(screen.queryByText(/Paid until/)).not.toBeInTheDocument();
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

describe("the upgrade funnel", () => {
  const ORDER = {
    order_id: "order_sub",
    amount: 49900,
    currency: "INR",
    razorpay_key_id: "rzp_test_publishable",
    tier: "pro",
  };
  const PAYMENT = {
    razorpay_order_id: "order_sub",
    razorpay_payment_id: "pay_sub",
    razorpay_signature: "sig",
  };
  let checkout;

  function json(body, status = 200) {
    return { ok: status < 400, status, statusText: "", text: async () => JSON.stringify(body) };
  }

  beforeEach(() => {
    localStorage.clear();
    mockTrack.mockClear();
    checkout = null;
    window.Razorpay = vi.fn(function Razorpay(options) {
      checkout = options;
      return { open: vi.fn() };
    });
    // Already on the page, so the loader resolves at once.
    const script = document.createElement("script");
    script.id = "razorpay-script";
    document.body.appendChild(script);
  });

  afterEach(() => {
    delete window.Razorpay;
    document.getElementById("razorpay-script")?.remove();
  });

  async function chooseSmb(...responses) {
    const fetch = vi.fn();
    [PRICING_RESPONSE, SUBSCRIPTION_RESPONSE, ...responses].forEach((r) =>
      fetch.mockResolvedValueOnce(r.ok === undefined ? json(r) : r),
    );
    global.fetch = fetch;
    renderPage();
    fireEvent.click((await screen.findAllByRole("button", { name: "Subscribe" }))[0]);
  }

  const events = () => mockTrack.mock.calls.map(([name]) => name);

  it("records choosing a plan, opening checkout and paying", async () => {
    await chooseSmb(ORDER, { id: 1 }, { ...SUBSCRIPTION_RESPONSE, tier: "pro" });
    await waitFor(() => expect(checkout).not.toBeNull());

    await checkout.handler(PAYMENT);

    await waitFor(() => expect(events()).toContain("subscribe_success"));
    expect(mockTrack).toHaveBeenCalledWith("upgrade_click", { tier: "pro", billing: "monthly" });
    expect(mockTrack).toHaveBeenCalledWith("checkout_open", { tier: "pro", billing: "monthly" });
    expect(events()).not.toContain("upgrade_failed");
  });

  it("records walking away from checkout", async () => {
    await chooseSmb(ORDER);
    await waitFor(() => expect(checkout).not.toBeNull());

    checkout.modal.ondismiss();

    expect(mockTrack).toHaveBeenCalledWith("checkout_dismissed", { tier: "pro", billing: "monthly" });
  });

  it("records a payment that would not verify as a failure at the verify stage", async () => {
    await chooseSmb(ORDER, json({ detail: "Payment verification failed." }, 400));
    await waitFor(() => expect(checkout).not.toBeNull());

    await checkout.handler(PAYMENT);

    await waitFor(() =>
      expect(mockTrack).toHaveBeenCalledWith("upgrade_failed", {
        tier: "pro",
        billing: "monthly",
        stage: "verify",
      }),
    );
    expect(events()).not.toContain("subscribe_success");
  });

  it("records an order that could not be created as a failure at the order stage", async () => {
    await chooseSmb(json({ detail: "Payment processing is not configured." }, 503));

    await waitFor(() =>
      expect(mockTrack).toHaveBeenCalledWith("upgrade_failed", {
        tier: "pro",
        billing: "monthly",
        stage: "order",
      }),
    );
    expect(events()).not.toContain("checkout_open");
  });

  it("records a payment window that would not load as a failure at the gateway stage", async () => {
    document.getElementById("razorpay-script").remove();
    await chooseSmb();
    const script = await waitFor(() => {
      const found = document.getElementById("razorpay-script");
      expect(found).not.toBeNull();
      return found;
    });

    script.onerror();

    await waitFor(() =>
      expect(mockTrack).toHaveBeenCalledWith("upgrade_failed", {
        tier: "pro",
        billing: "monthly",
        stage: "gateway",
      }),
    );
  });
});
