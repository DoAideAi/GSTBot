import { afterEach, describe, expect, it, vi } from "vitest";
import { loadRazorpay, payWithRazorpay } from "./razorpay";

afterEach(() => {
  delete window.Razorpay;
  document.getElementById("razorpay-script")?.remove();
});

describe("loadRazorpay", () => {
  it("resolves at once when Checkout is already on the page", async () => {
    window.Razorpay = vi.fn();
    await expect(loadRazorpay()).resolves.toBe(true);
    expect(document.getElementById("razorpay-script")).toBeNull();
  });

  it("adds the Checkout script and resolves once it has loaded", async () => {
    const loading = loadRazorpay();
    const script = document.getElementById("razorpay-script");
    expect(script.src).toBe("https://checkout.razorpay.com/v1/checkout.js");
    window.Razorpay = vi.fn();
    script.onload();
    await expect(loading).resolves.toBe(true);
  });

  it("resolves false when the script fails, instead of hanging", async () => {
    const loading = loadRazorpay();
    document.getElementById("razorpay-script").onerror();
    await expect(loading).resolves.toBe(false);
  });

  it("replaces a tag left behind by an earlier failure rather than waiting on it", async () => {
    const stale = document.createElement("script");
    stale.id = "razorpay-script";
    document.body.appendChild(stale);

    const loading = loadRazorpay();
    const fresh = document.getElementById("razorpay-script");
    expect(fresh).not.toBe(stale);
    fresh.onerror();
    await expect(loading).resolves.toBe(false);
  });
});

describe("payWithRazorpay", () => {
  function checkout() {
    const instance = { open: vi.fn() };
    window.Razorpay = vi.fn(function Razorpay(options) {
      instance.options = options;
      return instance;
    });
    return instance;
  }

  it("resolves with Razorpay's response when the payment succeeds", async () => {
    const instance = checkout();
    const paying = payWithRazorpay({ order_id: "order_rpt" });
    expect(instance.open).toHaveBeenCalled();
    expect(instance.options.order_id).toBe("order_rpt");
    instance.options.handler({ razorpay_payment_id: "pay_rpt" });
    await expect(paying).resolves.toEqual({ razorpay_payment_id: "pay_rpt" });
  });

  it("resolves null when the window is closed without paying", async () => {
    const instance = checkout();
    const paying = payWithRazorpay({});
    instance.options.modal.ondismiss();
    await expect(paying).resolves.toBeNull();
  });
});
