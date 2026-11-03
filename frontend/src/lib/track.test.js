import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { amountBand, analyticsSafe, track } from "./track";

describe("track", () => {
  let originalUmami;

  beforeEach(() => {
    originalUmami = window.umami;
  });

  afterEach(() => {
    if (originalUmami === undefined) {
      delete window.umami;
    } else {
      window.umami = originalUmami;
    }
  });

  it("calls umami.track when umami is available", () => {
    window.umami = { track: vi.fn() };

    track("test_event", { key: "value" });

    expect(window.umami.track).toHaveBeenCalledWith("test_event", { key: "value" });
  });

  it("does nothing when umami is not available", () => {
    delete window.umami;

    expect(() => track("test_event")).not.toThrow();
  });

  it("passes event name without data", () => {
    window.umami = { track: vi.fn() };

    track("simple_event");

    expect(window.umami.track).toHaveBeenCalledWith("simple_event", undefined);
  });
});

// P24 M15: the calculators sent the taxable value, the ITC page the GST and
// net credit, the scheme comparison the turnover, and the HSN search box
// whatever was typed into it, all to a third-party analytics store.
describe("what reaches analytics", () => {
  it("sends a business's figures as a band, never the figure", () => {
    expect(
      analyticsSafe({ amount: 123456, turnover: 4_50_00_000, totalGst: 9500, netItc: 0, rate: 18 }),
    ).toEqual({ amount: "1L-10L", turnover: "1Cr+", totalGst: "<10K", netItc: "<10K", rate: 18 });
  });

  it("bands in lakh and crore at the edges", () => {
    expect([9_999, 10_000, 99_999, 1_00_000, 9_99_999, 10_00_000, 1_00_00_000].map(amountBand)).toEqual(
      ["<10K", "10K-1L", "10K-1L", "1L-10L", "1L-10L", "10L-1Cr", "1Cr+"],
    );
    expect(amountBand(NaN)).toBe("unknown");
  });

  it.each([
    ["a GSTIN", "27AAPFU0939F1ZV"],
    ["a PAN", "aapfu0939f"],
    ["an email", "owner@example.com"],
    ["a phone number", "+91 98765 43210"],
  ])("redacts %s typed into a search box", (_, typed) => {
    expect(analyticsSafe({ query: `rate for ${typed}` })).toEqual({ query: "[redacted]" });
  });

  it("keeps an ordinary search term, cut to a sane length", () => {
    expect(analyticsSafe({ query: "laptop" })).toEqual({ query: "laptop" });
    expect(analyticsSafe({ query: "x".repeat(100) }).query).toHaveLength(40);
  });

  it("applies on the way out of track()", () => {
    window.umami = { track: vi.fn() };
    track("gst_calculate", { amount: 250000, rate: 18 });
    expect(window.umami.track).toHaveBeenCalledWith("gst_calculate", { amount: "1L-10L", rate: 18 });
  });
});

describe("track never breaks the flow it measures", () => {
  afterEach(() => {
    delete window.umami;
  });

  it("swallows an analytics script that throws", () => {
    window.umami = { track: () => { throw new Error("blocked"); } };
    expect(() => track("checkout_open", { tier: "pro" })).not.toThrow();
  });

  it("ignores a stub without a track function", () => {
    window.umami = {};
    expect(() => track("checkout_open")).not.toThrow();
  });
});


describe("advertising conversion boundaries", () => {
  afterEach(() => { delete window.doaideAds; delete window.umami; });
  it("counts completed outcomes, not clicks, failed uploads or empty reconciliations", () => {
    window.doaideAds = { conversion: vi.fn() };
    for (const event of ["signup_click", "checkout_open", "upgrade_failed", "pricing_view"]) track(event);
    track("invoice_upload", { accepted: 0 });
    track("reconcile_run", { invoices: 0 });
    expect(window.doaideAds.conversion).not.toHaveBeenCalled();
    track("signup_complete", { method: "google", email: "private@example.com" });
    track("pilot_started", { tier: "enterprise" });
    track("invoice_upload", { accepted: 1, filename: "private.pdf" });
    track("reconcile_run", { invoices: 1 });
    expect(window.doaideAds.conversion.mock.calls).toEqual([
      ["signup_complete", undefined], ["pilot_started", undefined],
      ["product_used", undefined], ["product_used", undefined],
    ]);
  });
  it("sends the verified order amount separately from product data even if Umami fails", () => {
    window.umami = { track: () => { throw new Error("blocked"); } };
    window.doaideAds = { conversion: vi.fn() };
    const order = { value: 2999, transaction_id: "order_123" };
    track("subscribe_success", { tier: "enterprise" }, order);
    expect(window.doaideAds.conversion).toHaveBeenCalledWith("subscribe_success", order);
    window.doaideAds.conversion.mockImplementation(() => { throw new Error("blocked"); });
    expect(() => track("pilot_started")).not.toThrow();
  });
});
