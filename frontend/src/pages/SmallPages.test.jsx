import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AuthCallbackPage from "./AuthCallbackPage";
import HsnCodePage from "./HsnCodePage";
import HsnWidgetPage from "./HsnWidgetPage";
import ReferralPage from "./ReferralPage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));

const auth = vi.hoisted(() => ({ current: { user: null } }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => auth.current }));

const setToken = vi.hoisted(() => vi.fn());
vi.mock("../lib/api", () => ({
  setToken,
  api: {
    subscribe: vi.fn().mockResolvedValue({ subscribed: true, new: true, message: "Done" }),
    myReferralCode: vi.fn().mockResolvedValue({ referral_code: "CA-TEST1" }),
    myReferralStats: vi.fn().mockResolvedValue({ total_visits: 4, conversions: 2 }),
    referralLeaderboard: vi.fn().mockResolvedValue({ leaders: [{ name: "A. Shah", referrals: 9 }] }),
  },
}));
vi.mock("../lib/share", () => ({
  fullUrl: (p) => `http://localhost${p}`,
  whatsappUrl: () => "https://wa.me/",
  twitterUrl: () => "https://twitter.com/",
  copyToClipboard: vi.fn().mockResolvedValue(true),
}));
vi.mock("../lib/track", () => ({ track: vi.fn() }));

describe("AuthCallbackPage", () => {
  function renderAt(search) {
    return render(
      <MemoryRouter initialEntries={[`/auth/callback${search}`]}>
        <Routes>
          <Route path="/auth/callback" element={<AuthCallbackPage />} />
          <Route path="/login" element={<div>Login probe</div>} />
        </Routes>
      </MemoryRouter>,
    );
  }

  beforeEach(() => {
    setToken.mockClear();
    // jsdom refuses real navigation; the page only assigns href, so a plain
    // object is enough to observe the hand-off.
    Object.defineProperty(window, "location", { value: { href: "" }, writable: true });
  });

  it("bounces a provider error back to the sign-in page with the reason", () => {
    renderAt("?error=denied");
    expect(screen.getByText("Login probe")).toBeInTheDocument();
    expect(setToken).not.toHaveBeenCalled();
  });

  it("stores the token and hands the browser to the dashboard", () => {
    renderAt("?token=tok123");
    expect(setToken).toHaveBeenCalledWith("tok123");
    expect(window.location.href).toBe("/");
  });

  it("sends a callback with neither token nor error back to sign-in", () => {
    renderAt("");
    expect(screen.getByText("Login probe")).toBeInTheDocument();
    expect(setToken).not.toHaveBeenCalled();
  });
});

describe("HsnWidgetPage", () => {
  function renderAt(search = "") {
    return render(
      <MemoryRouter initialEntries={[`/widget/hsn${search}`]}>
        <HsnWidgetPage />
      </MemoryRouter>,
    );
  }

  it("lists matching codes with their rates", () => {
    renderAt();
    fireEvent.change(screen.getByPlaceholderText(/e.g. rice/), { target: { value: "rice" } });
    expect(screen.getByText("Code")).toBeInTheDocument();
    expect(screen.getAllByText(/%$/).length).toBeGreaterThanOrEqual(1);
  });

  it("says so when nothing matches", () => {
    renderAt();
    fireEvent.change(screen.getByPlaceholderText(/e.g. rice/), { target: { value: "zzzzqqq" } });
    expect(screen.getByText(/No HSN\/SAC codes found/)).toBeInTheDocument();
  });

  it("adopts the embedding site's theme from the query string", () => {
    renderAt("?theme=dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});

describe("HsnCodePage", () => {
  function renderAt(code) {
    return render(
      <MemoryRouter initialEntries={[`/hsn/${code}`]}>
        <Routes>
          <Route path="/hsn/:code" element={<HsnCodePage />} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("renders a known HSN code's landing page", () => {
    renderAt("8471");
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.textContent).toContain("8471");
  });

  it("tells the visitor when the code has no page", () => {
    renderAt("000000");
    expect(screen.getByText("HSN Code Not Found")).toBeInTheDocument();
  });
});

describe("ReferralPage", () => {
  it("asks an anonymous visitor to sign in for a link", async () => {
    auth.current = { user: null };
    render(
      <MemoryRouter>
        <ReferralPage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "CA Referral Program" })).toBeInTheDocument();
    expect(screen.getByText(/Sign up or log in to get your unique referral link/)).toBeInTheDocument();
    expect(await screen.findByText(/A\. Shah/)).toBeInTheDocument();
  });

  it("shows a signed-in user their code and stats", async () => {
    auth.current = { user: { id: 1, email: "ca@example.com" } };
    render(
      <MemoryRouter>
        <ReferralPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/CA-TEST1/)).toBeInTheDocument();
  });
});
