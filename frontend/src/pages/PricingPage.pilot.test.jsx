import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { StubAuth } from "../test/auth";
import { AuthContext } from "../hooks/useAuth";
import { takeReturnTo } from "../lib/returnTo";
import PricingPage from "./PricingPage";
vi.mock("../lib/track", () => ({ track: vi.fn() }));
let state, subscription, pricing, posts, reject;
const enrollment = { tier: "enterprise", starts_at: "2026-11-02T12:00:00Z", ends_at: "2027-01-01T12:00:00Z", active: true, business_limit: 5, business_ids: [1] };
function response(body, status = 200) { return { ok: status < 400, status, text: async () => JSON.stringify(body) }; }
function land(authenticated = true) {
  return render(<MemoryRouter>{authenticated ? <StubAuth><PricingPage /></StubAuth> : <AuthContext.Provider value={{ user: null }}><PricingPage /></AuthContext.Provider>}</MemoryRouter>);
}
beforeEach(() => {
  sessionStorage.clear(); subscription = null; posts = []; reject = false;
  state = { can_start: true, can_manage: false, is_home: true, enrollment: null, businesses: [{ id: 1, name: "Our firm" }, { id: 2, name: "Client A" }] };
  pricing = { razorpay_key_id: "", tiers: {
    free: { name: "Free Tools", price_monthly: 0, features: [] },
    pro: { name: "SMB", price_monthly: 49900, features: ["Reconciliation"] },
    enterprise: { name: "CA", price_monthly: 299900, features: ["Multi-client management"] },
  }, pilot: { days: 60, capacity: { pro: 20, enterprise: 10 }, remaining: { pro: 20, enterprise: 10 }, business_limits: { pro: 1, enterprise: 5 }, monthly_invoice_limit: 500 } };
  vi.stubGlobal("fetch", vi.fn(async (url, options) => {
    if (options.method === "POST") {
      posts.push({ url, body: JSON.parse(options.body) });
      if (reject) return response({ detail: "This pilot cohort is full." }, 409);
      if (url.endsWith("/pilot/businesses")) state.enrollment = { ...state.enrollment, business_ids: [1, 2] };
      else if (url.endsWith("/pilot")) {
        state = { ...state, enrollment, can_start: false, can_manage: true };
        subscription = { source: "pilot", tier: "enterprise", status: "active", current_period_end: enrollment.ends_at };
      } else throw new Error("Unexpected payment request");
      return response(state);
    }
    if (url.endsWith("/pricing")) return response(pricing);
    if (url.endsWith("/current")) return response(subscription);
    if (url.endsWith("/pilot")) return response(state);
    throw new Error(`Unexpected URL ${url}`);
  }));
});
afterEach(() => vi.unstubAllGlobals());

it("shows regular prices and remembers pricing after sign-in", async () => {
  land(false);
  expect(await screen.findByText("Try DoAide GST free for 60 days")).toBeVisible();
  expect(screen.getByText("₹499")).toBeVisible();
  expect(screen.getByText("₹2,999")).toBeVisible();
  expect(screen.getByText(/500 invoice uploads/)).toBeVisible();
  fireEvent.click(screen.getByRole("link", { name: "Start CA free pilot" }));
  expect(takeReturnTo()).toBe("/pricing");
  expect(posts).toEqual([]);
});
it("starts without Razorpay and shows the end date without paid cancellation controls", async () => {
  land();
  fireEvent.click(await screen.findByRole("button", { name: "Start CA free pilot" }));
  expect(await screen.findByText("Your free pilot is active")).toBeVisible();
  expect(screen.getAllByText(/1 Jan 2027/).length).toBeGreaterThan(0);
  expect(posts).toEqual([{ url: "/api/v1/subscriptions/pilot", body: { tier: "enterprise" } }]);
  expect(document.querySelector('script[src*="razorpay"]')).toBeNull();
  expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Extend by/ })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Pilot active" })).toBeDisabled();
});
it("adds an authorized client and updates the covered count", async () => {
  land();
  fireEvent.click(await screen.findByRole("button", { name: "Start CA free pilot" }));
  fireEvent.change(await screen.findByLabelText("Add a linked registration"), { target: { value: "2" } });
  fireEvent.click(screen.getByRole("button", { name: "Include in pilot" }));
  expect(await screen.findByText(/2 of 5 registrations covered/)).toBeVisible();
  expect(posts[1]).toEqual({ url: "/api/v1/subscriptions/pilot/businesses", body: { business_id: 2 } });
});
it("explains expiry and leaves a deliberate paid choice", async () => {
  state = { ...state, can_start: false, enrollment: { ...enrollment, active: false } };
  subscription = { source: "pilot", tier: "enterprise", status: "expired", current_period_end: enrollment.ends_at };
  land();
  expect(await screen.findByText("Your free pilot has ended")).toBeVisible();
  expect(screen.getByText(/existing data and included reports remain available/)).toBeVisible();
  expect(screen.getAllByRole("link", { name: "Contact us about a paid plan" })).toHaveLength(2);
  expect(posts).toEqual([]);
});
it("does not advertise a full cohort as available", async () => {
  pricing.pilot.remaining.enterprise = 0;
  land(false);
  expect(await screen.findByRole("link", { name: "Ask about the next pilot" })).toBeVisible();
  expect(screen.queryByRole("link", { name: "Start CA free pilot" })).not.toBeInTheDocument();
});
it("shows admission errors without claiming success", async () => {
  reject = true; land();
  fireEvent.click(await screen.findByRole("button", { name: "Start SMB free pilot" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("cohort is full");
  expect(screen.queryByText("Your free pilot is active")).not.toBeInTheDocument();
});
