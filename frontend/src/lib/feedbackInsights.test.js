import { describe, expect, it } from "vitest";
import { duration, summarize } from "./feedbackInsights";

describe("duration", () => {
  it.each([
    [0, "0s"],
    [45_000, "45s"],
    [192_000, "3m 12s"],
    [3_725_000, "1h 2m"],
    [-1, null],
  ])("%s ms reads %s", (ms, text) => {
    expect(duration(ms)).toBe(text);
  });
});

describe("summarize", () => {
  it("reads a struggling visit as one sentence and its flags", () => {
    const { sentence, flags } = summarize({
      feature_area: "GSTIN Lookup",
      time_on_page_ms: 192_000,
      scroll_depth_pct: 80,
      click_count: 14,
      rage_clicks: 5,
      rage_click_targets: ["button#validate"],
      js_errors: 1,
      js_error_messages: ["TypeError: x is undefined"],
      form_abandoned: true,
      form_time_ms: 150_000,
      reloaded: true,
      pages: ["/", "/gstin-validator"],
    });
    expect(sentence).toBe(
      "Was on GSTIN Lookup for 3m 12s, scrolled 80%, 14 clicks, 5 rage clicks, 1 JS error, 2 pages this session.",
    );
    expect(flags.map((f) => f.label)).toEqual([
      "Rage clicks on button#validate",
      "Stuck on a form for 2m 30s without submitting",
      "JS error: TypeError: x is undefined",
      "Reloaded the page",
    ]);
  });

  it("raises no flags for a calm visit", () => {
    const { flags } = summarize({ feature_area: "Home", time_on_page_ms: 4000, rage_clicks: 0, js_errors: 0 });
    expect(flags).toEqual([]);
  });

  it("says nothing for feedback sent without a visit", () => {
    expect(summarize(null)).toEqual({ sentence: "", flags: [] });
  });
});
