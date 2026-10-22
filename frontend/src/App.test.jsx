import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

// Auth is mocked rather than driven through AuthProvider because the states
// that matter here are the three the provider passes through — loading, signed
// out, signed in — and reaching "loading" through the real provider means
// holding a fetch open, which makes the interesting assertions racy.
const auth = vi.hoisted(() => ({ current: { user: null, loading: false } }));
vi.mock("./hooks/useAuth", () => ({ useAuth: () => auth.current }));

// Every page is stubbed. This file is about which route renders what, not
// about what any page does with the API; stubbing keeps one routing test from
// needing a fetch mock for nine different endpoints. Shell and ErrorBoundary
// are deliberately left real — where the boundary sits *relative to* the shell
// is one of the things being asserted.
const crash = vi.hoisted(() => ({ current: false }));
vi.mock("./pages/DashboardPage", () => ({
  default: () => {
    if (crash.current) throw new Error("total is not a number");
    return <div>Dashboard page</div>;
  },
}));
vi.mock("./pages/LandingPage", () => ({ default: () => <div>Landing page</div> }));
vi.mock("./pages/LoginPage", () => ({ default: () => <div>Login page</div> }));
vi.mock("./pages/InvoicesPage", () => ({ default: () => <div>Invoices page</div> }));
vi.mock("./pages/InvoiceDetailPage", () => ({ default: () => <div>Invoice detail page</div> }));
vi.mock("./pages/UploadPage", () => ({ default: () => <div>Upload page</div> }));
vi.mock("./pages/ReconcilePage", () => ({ default: () => <div>Reconcile page</div> }));
vi.mock("./pages/ITCPage", () => ({ default: () => <div>ITC page</div> }));
vi.mock("./pages/FilingPage", () => ({ default: () => <div>Filing page</div> }));
vi.mock("./pages/SuppliersPage", () => ({ default: () => <div>Suppliers page</div> }));
vi.mock("./pages/AlertsPage", () => ({ default: () => <div>Alerts page</div> }));
vi.mock("./pages/CalculatorPage", () => ({ default: () => <div>Calculator page</div> }));
vi.mock("./pages/LookupPage", () => ({ default: () => <div>Lookup page</div> }));
vi.mock("./pages/HsnFinderPage", () => ({ default: () => <div>HSN page</div> }));
vi.mock("./pages/GstinPage", () => ({ default: () => <div>GSTIN page</div> }));
vi.mock("./pages/GstRatePage", () => ({ default: () => <div>GST rate page</div> }));
vi.mock("./pages/EmbedPage", () => ({ default: () => <div>Embed page</div> }));
vi.mock("./pages/ResourcesPage", () => ({ default: () => <div>Resources page</div> }));
vi.mock("./pages/BlogLayout", async () => {
  const { Outlet } = await import("react-router-dom");
  return {
    default: () => <div>Blog layout<Outlet /></div>,
    BlogIndex: () => <div>Blog index</div>,
    ARTICLES: [],
  };
});
vi.mock("./pages/blog/GstFilingGuide", () => ({ default: () => <div>Filing guide</div> }));
vi.mock("./pages/blog/HsnCodeLookup", () => ({ default: () => <div>HSN lookup article</div> }));
vi.mock("./pages/blog/GstComplianceChecklist", () => ({ default: () => <div>Compliance checklist</div> }));

const USER = { id: 1, email: "owner@acme.in", business: { legal_name: "Acme Traders" } };

function renderAt(route, state = { user: USER, loading: false }) {
  auth.current = state;
  return render(
    <MemoryRouter initialEntries={[route]}>
      <App />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  crash.current = false;
  auth.current = { user: null, loading: false };
});

afterEach(() => vi.restoreAllMocks());

describe("App routing", () => {
  describe("while the session is still being confirmed", () => {
    const LOADING = { user: null, loading: true };

    it("holds a protected route instead of redirecting to login", () => {
      // The regression this guards: /auth/me has not answered yet, so `user`
      // is null but the visitor may well be signed in. Redirecting on that
      // null bounces a signed-in user to the login page on every refresh.
      renderAt("/", LOADING);

      expect(screen.getByText(/checking your session/i)).toBeInTheDocument();
      expect(screen.queryByText("Login page")).not.toBeInTheDocument();
      expect(screen.queryByText("Dashboard page")).not.toBeInTheDocument();
    });

    it("holds /login behind the loading check too", () => {
      renderAt("/login", LOADING);

      expect(screen.getByText(/checking your session/i)).toBeInTheDocument();
      expect(screen.queryByText("Landing page")).not.toBeInTheDocument();
    });
  });

  describe("when signed out", () => {
    it("sends a protected route to the landing page", () => {
      renderAt("/invoices", { user: null, loading: false });

      expect(screen.getByText("Landing page")).toBeInTheDocument();
      expect(screen.queryByText("Invoices page")).not.toBeInTheDocument();
    });

    it("keeps alerts behind the landing page, since they name a tenant's returns", () => {
      renderAt("/alerts", { user: null, loading: false });

      expect(screen.getByText("Landing page")).toBeInTheDocument();
      expect(screen.queryByText("Alerts page")).not.toBeInTheDocument();
    });

    it("shows the sign-in page at /login", async () => {
      renderAt("/login", { user: null, loading: false });

      expect(await screen.findByText("Login page")).toBeInTheDocument();
    });

    it("shows the landing page to an anonymous visitor, not the shell", () => {
      renderAt("/", { user: null, loading: false });

      expect(screen.getByText("Landing page")).toBeInTheDocument();
      expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
    });

    it("tells an anonymous visitor an unknown path does not exist, instead of silently showing the homepage", async () => {
      renderAt("/nope/not/a/page", { user: null, loading: false });

      expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
      expect(screen.queryByText("Landing page")).not.toBeInTheDocument();
    });
  });

  describe("public tool routes (no auth needed)", () => {
    it.each([
      ["/calculator", "Calculator page"],
      ["/lookup", "Lookup page"],
      ["/hsn", "HSN page"],
      ["/gstin/27AAPFU0939F1ZV", "GSTIN page"],
      ["/gst-rate/laptop", "GST rate page"],
      ["/embed", "Embed page"],
      ["/resources", "Resources page"],
    ])("renders %s without auth", async (route, expected) => {
      renderAt(route, { user: null, loading: false });

      expect(await screen.findByText(expected)).toBeInTheDocument();
    });
  });

  describe("blog routes (no auth needed)", () => {
    it("renders the blog index at /blog", async () => {
      renderAt("/blog", { user: null, loading: false });

      expect(await screen.findByText("Blog index")).toBeInTheDocument();
    });

    it("renders a blog article at /blog/:slug", async () => {
      renderAt("/blog/gst-filing-guide-india-2026", { user: null, loading: false });

      expect(await screen.findByText("Filing guide")).toBeInTheDocument();
    });

    it("does not redirect /blog to the homepage", async () => {
      renderAt("/blog", { user: null, loading: false });

      expect(await screen.findByText("Blog index")).toBeInTheDocument();
      expect(screen.queryByText("Landing page")).not.toBeInTheDocument();
    });

    it("does not redirect /blog/:slug to the homepage", async () => {
      renderAt("/blog/hsn-code-lookup", { user: null, loading: false });

      expect(await screen.findByText("HSN lookup article")).toBeInTheDocument();
      expect(screen.queryByText("Landing page")).not.toBeInTheDocument();
    });
  });

  describe("when signed in", () => {
    it.each([
      ["/", "Dashboard page"],
      ["/invoices", "Invoices page"],
      ["/invoices/42", "Invoice detail page"],
      ["/upload", "Upload page"],
      ["/reconcile", "Reconcile page"],
      ["/itc", "ITC page"],
      ["/filing", "Filing page"],
      ["/suppliers", "Suppliers page"],
      ["/alerts", "Alerts page"],
    ])("renders %s", async (route, expected) => {
      renderAt(route);

      expect(await screen.findByText(expected)).toBeInTheDocument();
    });

    it("wraps protected pages in the shell", async () => {
      renderAt("/invoices");

      expect(await screen.findByRole("navigation", { name: "Main" })).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Skip to content" })).toBeInTheDocument();
    });

    it("keeps /invoices/:id distinct from the list", async () => {
      renderAt("/invoices/42");

      expect(await screen.findByText("Invoice detail page")).toBeInTheDocument();
      expect(screen.queryByText("Invoices page")).not.toBeInTheDocument();
    });

    it("redirects away from /login", async () => {
      renderAt("/login");

      expect(await screen.findByText("Dashboard page")).toBeInTheDocument();
      expect(screen.queryByText("Login page")).not.toBeInTheDocument();
    });

    it("tells a signed-in user an unknown path does not exist and links them home", async () => {
      renderAt("/nope/not/a/page");

      expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /homepage/i })).toHaveAttribute("href", "/");
    });
  });

  describe("when a page crashes", () => {
    it("keeps the navigation usable so the user can leave the broken screen", async () => {
      const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
      crash.current = true;
      renderAt("/");

      expect(await screen.findByRole("alert")).toHaveTextContent(/this screen hit an error/i);
      expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();

      crash.current = false;
      await userEvent.click(screen.getByRole("link", { name: "Invoices" }));

      expect(await screen.findByText("Invoices page")).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      quiet.mockRestore();
    });

    it("reports the underlying message rather than a bare apology", async () => {
      const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
      crash.current = true;
      renderAt("/");

      expect(await screen.findByText("total is not a number")).toBeInTheDocument();
      quiet.mockRestore();
    });
  });
});

describe("switching to another GSTIN", () => {
  // Every page loads on mount and holds what it loaded in state, and none of
  // them watch the business — until the switcher shipped, it could not change
  // while they were mounted. So the page is thrown away and rebuilt rather than
  // re-rendered, which is also what re-runs each page's own fetch.
  function renderFor(businessId) {
    auth.current = {
      user: { ...USER, business: { id: businessId, legal_name: "Acme Traders" } },
      loading: false,
    };
    return render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
  }

  it("rebuilds the page so its data cannot outlive the tenant it was fetched for", async () => {
    const { rerender } = renderFor(1);
    const before = await screen.findByText("Dashboard page");

    auth.current = {
      user: { ...USER, business: { id: 2, legal_name: "Acme Exports" } },
      loading: false,
    };
    rerender(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    const after = await screen.findByText("Dashboard page");
    expect(after).not.toBe(before);
  });

  it("keeps the page alive across a re-render that does not change tenant", async () => {
    const { rerender } = renderFor(1);
    const before = await screen.findByText("Dashboard page");

    rerender(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByText("Dashboard page")).toBe(before);
  });
});
