import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ItcReconciliationDashboardPage from "./ItcReconciliationDashboardPage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("../lib/share", () => ({
  fullUrl: (p) => `http://localhost${p}`,
  whatsappUrl: (text, url) => `https://wa.me/?text=${encodeURIComponent(`${text} ${url}`)}`,
  twitterUrl: (text, url) => `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`,
  copyToClipboard: vi.fn().mockResolvedValue(true),
}));
vi.mock("../lib/api", () => ({
  api: { subscribe: vi.fn().mockResolvedValue({ subscribed: true, new: true, message: "Done" }) },
}));
vi.mock("../lib/track", () => ({ track: vi.fn() }));

const DRAFT_KEY = "gst.itc-dashboard.draft";

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/itc-reconciliation-dashboard"]}>
      <ItcReconciliationDashboardPage />
    </MemoryRouter>,
  );
}

function statValue(label) {
  return screen.getByText(label).parentElement.querySelector(".stat-value").textContent;
}

describe("ItcReconciliationDashboardPage", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-31T06:00:00Z"));
    window.localStorage.clear();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the input grid and no dashboard before data", () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "ITC Reconciliation Dashboard" })).toBeInTheDocument();
    expect(screen.getByLabelText("April ITC in GSTR-2B")).toBeInTheDocument();
    expect(screen.queryByText(/at a glance/)).not.toBeInTheDocument();
  });

  it("shows a low-risk dashboard with the deadline countdown when everything matches", () => {
    renderPage();
    for (const col of ["ITC as per books", "ITC in GSTR-2B", "ITC claimed in 3B"]) {
      fireEvent.change(screen.getByLabelText(`April ${col}`), { target: { value: "50000" } });
    }
    expect(screen.getByText("FY 2025-26 at a glance")).toBeInTheDocument();
    expect(statValue("Overall risk")).toBe("Low");
    expect(statValue("Claimed backed by GSTR-2B")).toBe("100%");
    expect(statValue("Section 16(4) deadline")).toBe("30 days");
    const table = screen.getByRole("region", { name: "Month-wise reconciliation" });
    expect(within(table).getByText("Matched")).toBeInTheDocument();
  });

  it("classifies the sample year's three kinds of gap and lists suppliers to chase", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Load sample year" }));
    expect(statValue("Overall risk")).toBe("High");
    expect(statValue("Excess ITC claimed")).toBe("₹18,000.00");
    expect(statValue("Unclaimed eligible ITC")).toBe("₹25,000.00");
    expect(statValue("Awaiting suppliers")).toBe("₹42,000.00");
    const table = screen.getByRole("region", { name: "Month-wise reconciliation" });
    expect(within(table).getByText("Excess claim")).toBeInTheDocument();
    expect(within(table).getAllByText("Action needed")).toHaveLength(2);
    const chase = screen.getByRole("list", { name: "Suppliers to chase" });
    expect(within(chase).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Shree Packaging — ₹42,000.00 not yet in your GSTR-2B",
      "Kaveri Chemicals — ₹18,000.00 not yet in your GSTR-2B",
    ]);
  });

  it("warns that unclaimed credit lapsed once the deadline has passed", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Financial year"), { target: { value: "2024-25" } });
    fireEvent.change(screen.getByLabelText("May ITC as per books"), { target: { value: "10000" } });
    fireEvent.change(screen.getByLabelText("May ITC in GSTR-2B"), { target: { value: "10000" } });
    expect(statValue("Section 16(4) deadline")).toBe("Passed");
    expect(screen.getByRole("alert")).toHaveTextContent(/₹10,000.00 of unclaimed credit has lapsed/);
  });

  it("adds supplier rows and persists the draft", () => {
    const { unmount } = renderPage();
    fireEvent.click(screen.getByRole("button", { name: "+ Add supplier" }));
    fireEvent.change(screen.getByLabelText("Supplier 2 name"), { target: { value: "Delta Ltd" } });
    fireEvent.change(screen.getByLabelText("June ITC as per books"), { target: { value: "777" } });
    expect(JSON.parse(window.localStorage.getItem(DRAFT_KEY)).suppliers[1].name).toBe("Delta Ltd");
    unmount();
    renderPage();
    expect(screen.getByLabelText("Supplier 2 name")).toHaveValue("Delta Ltd");
    expect(screen.getByLabelText("June ITC as per books")).toHaveValue(777);
  });

  it("recovers from a corrupt draft and clears on demand", () => {
    window.localStorage.setItem(DRAFT_KEY, "oops");
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Load sample year" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(screen.queryByText(/at a glance/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Supplier 1 name")).toHaveValue("");
  });
});
