import { describe, expect, it } from "vitest";
import { metricoolPageUrl } from "./metricool";

const browser = { origin: "https://gst.doaide.com", referrer: "", width: 1440, height: 900 };

describe("Metricool public page beacons", () => {
  it("uses the supplied brand and the same page-view endpoint as the vendor tag", async () => {
    const url = new URL(await metricoolPageUrl("/calculator", browser));
    expect(url.origin + url.pathname).toBe("https://tracker.metricool.com/c3po.jpg");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      hash: "36195e51b9aa7f88d328d9d285bb8be", u: "https://gst.doaide.com/calculator", bw: "1440", bh: "900",
    });
  });

  it.each(["/login", "/auth/callback", "/auth/link-google", "/forgot-password", "/reset-password", "/unsubscribe", "/invoices", "/invoices/42", "/upload", "/itc", "/reconcile", "/filing", "/suppliers", "/bulk-gstin", "/alerts", "/usage", "/status", "/admin/feedback", "/gstin/27AAPFU0939F1ZV", "/unknown-private-page"])("does not report %s", async (path) => {
    expect(await metricoolPageUrl(path, browser)).toBeNull();
  });

  it.each(["http://localhost:5187", "https://preview.example.com"])("does not count development visits on %s", async (origin) => {
    expect(await metricoolPageUrl("/", { ...browser, origin })).toBeNull();
  });

  it("keeps only the external referrer's origin", async () => {
    const url = await metricoolPageUrl("/", { ...browser, referrer: "https://example.com/reset?token=secret#private" });
    expect(new URL(url).searchParams.get("ref")).toBe("https://example.com/");
    expect(url).not.toMatch(/token|secret|private|reset/);
  });

  it.each(["", "not a URL", "javascript:alert(1)", "https://gst.doaide.com/reset-password?token=secret"])("omits an unsafe or internal referrer: %s", async (referrer) => {
    expect(new URL(await metricoolPageUrl("/", { ...browser, referrer })).searchParams.has("ref")).toBe(false);
  });

  it("normalises a public trailing slash", async () => {
    expect(new URL(await metricoolPageUrl("/calculator/", browser)).searchParams.get("u")).toBe("https://gst.doaide.com/calculator");
  });

  it.each(["/hsn/1006", "/gst-rate/rice"])("includes a real programmatic public page: %s", async (path) => {
    expect(new URL(await metricoolPageUrl(path, browser)).searchParams.get("u")).toBe(browser.origin + path);
  });

  it.each(["/hsn/secret", "/gst-rate/private-company", "/calculator?amount=12345", "/#token=secret"])("refuses unrecognised data in a path: %s", async (path) => {
    expect(await metricoolPageUrl(path, browser)).toBeNull();
  });
});
