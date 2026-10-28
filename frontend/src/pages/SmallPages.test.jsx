import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AuthCallbackPage from "./AuthCallbackPage";
import HsnCodePage from "./HsnCodePage";
import HsnWidgetPage from "./HsnWidgetPage";
import ReferralPage from "./ReferralPage";

// A real hook, not a no-op: a page that calls it conditionally only fails when
// the call registers with React, which a plain function never does.
const titles = vi.hoisted(() => []);
vi.mock("../hooks/usePageTitle", async () => {
  const { useEffect } = await import("react");
  return {
    usePageTitle: (title) => {
      useEffect(() => {
        titles.push(title);
      }, [title]);
    },
  };
});

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
    // jsdom refuses real navigation; the page only calls replace, so a plain
    // object is enough to observe the hand-off.
    Object.defineProperty(window, "location", { value: { replace: vi.fn() }, writable: true });
  });

  it("bounces a provider error back to the sign-in page with the reason", () => {
    renderAt("?error=denied");
    expect(screen.getByText("Login probe")).toBeInTheDocument();
    expect(setToken).not.toHaveBeenCalled();
  });

  it("reads the token from the fragment the backend puts it in", () => {
    // oauth.py redirects to /auth/callback#token=… — never a query string,
    // so the token stays out of server logs and Referer headers.
    renderAt("#token=tok123");
    expect(setToken).toHaveBeenCalledWith("tok123");
    expect(window.location.replace).toHaveBeenCalledWith("/");
  });

  it("does not take a token from the query string", () => {
    renderAt("?token=tok123");
    expect(setToken).not.toHaveBeenCalled();
    expect(screen.getByText("Login probe")).toBeInTheDocument();
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

  it("survives moving from an unknown code to a known one on the same route", () => {
    function GoTo({ code }) {
      const navigate = useNavigate();
      return <button onClick={() => navigate(`/hsn/${code}`)}>go {code}</button>;
    }
    render(
      <MemoryRouter initialEntries={["/hsn/0000"]}>
        <GoTo code="8471" />
        <Routes>
          <Route path="/hsn/:code" element={<HsnCodePage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { level: 1 }).textContent).toMatch(/Not Found/);

    fireEvent.click(screen.getByRole("button", { name: "go 8471" }));

    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("8471");
    expect(titles.at(-2)).toBe("HSN Code 0000 Not Found");
    expect(titles.at(-1)).toMatch(/8471.*\| GST Rate \d+%$/);
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
