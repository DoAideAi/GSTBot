import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  FORM_STALL_MS,
  featureArea,
  installSessionTracker,
  noteError,
  routeChanged,
  snapshot,
} from "./sessionTracker";

let now;
let uninstall;

function click(el) {
  el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
}

beforeEach(() => {
  now = 1_000_000;
  document.body.innerHTML = `
    <button id="validate" class="btn btn-primary">Validate</button>
    <button id="other">Other</button>
    <form id="lookup"><input id="gstin" /></form>
    <div data-feedback-widget><button id="fb">Feedback</button><form id="fbform"><textarea id="fbtext"></textarea></form></div>`;
  window.history.replaceState(null, "", "/gstin-validator");
  uninstall = installSessionTracker(window, () => now);
});

afterEach(() => {
  uninstall?.();
});

describe("featureArea", () => {
  it.each([
    ["/gstin-validator", "GSTIN Lookup"],
    ["/gstin/27AAPFU0939F1ZV", "GSTIN Lookup"],
    ["/reconcile", "Reconciliation"],
    ["/itc-mismatch", "Reconciliation"],
    ["/itc", "Input Tax Credit"],
    ["/pricing", "Premium"],
    ["/hsn/8471", "HSN & Rates"],
    ["/interest-calculator", "Calculators"],
    ["/", "Home"],
    ["/something-new", "Other"],
  ])("%s is %s", (path, area) => {
    expect(featureArea(path)).toBe(area);
  });
});

describe("the session tracker", () => {
  it("keeps the trail of pages and times the current one from its arrival", () => {
    now += 5_000;
    routeChanged("/hsn");
    now += 192_000;
    const meta = snapshot();
    expect(meta.pages).toEqual(["/gstin-validator", "/hsn"]);
    expect(meta.feature_area).toBe("HSN & Rates");
    expect(meta.time_on_page_ms).toBe(192_000);
    expect(meta.session_ms).toBe(197_000);
  });

  it("does not restart the clock for the page it is already on", () => {
    now += 10_000;
    routeChanged("/gstin-validator");
    expect(snapshot().time_on_page_ms).toBe(10_000);
    expect(snapshot().pages).toEqual(["/gstin-validator"]);
  });

  it("counts clicks and starts them from zero on a new page", () => {
    click(document.getElementById("other"));
    click(document.getElementById("validate"));
    expect(snapshot().click_count).toBe(2);
    routeChanged("/hsn");
    expect(snapshot().click_count).toBe(0);
  });

  it("calls three quick clicks on one element a rage click, once per burst", () => {
    const button = document.getElementById("validate");
    for (let i = 0; i < 5; i += 1) {
      click(button);
      now += 300;
    }
    const meta = snapshot();
    expect(meta.rage_clicks).toBe(1);
    expect(meta.rage_click_targets).toEqual(["button#validate.btn"]);
  });

  it("does not call slow or scattered clicks rage clicks", () => {
    const button = document.getElementById("validate");
    click(button);
    now += 2_000;
    click(button);
    now += 2_000;
    click(button);
    click(document.getElementById("other"));
    click(button);
    expect(snapshot().rage_clicks).toBe(0);
  });

  it("flags a form worked on for over two minutes without being submitted", () => {
    document.getElementById("gstin").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    now += FORM_STALL_MS - 1;
    expect(snapshot().form_abandoned).toBe(false);
    now += 2;
    expect(snapshot()).toMatchObject({ form_abandoned: true, form_time_ms: FORM_STALL_MS + 1 });
  });

  it("clears the form clock when the form is submitted", () => {
    document.getElementById("gstin").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    now += FORM_STALL_MS * 2;
    document.getElementById("lookup").dispatchEvent(new Event("submit", { bubbles: true }));
    const meta = snapshot();
    expect(meta.form_abandoned).toBe(false);
    expect(meta).not.toHaveProperty("form_time_ms");
  });

  it("ignores the feedback widget's own clicks and form", () => {
    const fb = document.getElementById("fb");
    for (let i = 0; i < 4; i += 1) click(fb);
    document.getElementById("fbtext").dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    now += FORM_STALL_MS * 2;
    expect(snapshot()).toMatchObject({ click_count: 0, rage_clicks: 0, form_abandoned: false });
  });

  it("counts errors on the page and keeps the first few messages", () => {
    window.dispatchEvent(new ErrorEvent("error", { message: "TypeError: x is undefined" }));
    noteError("Render failed");
    expect(snapshot()).toMatchObject({
      js_errors: 2,
      js_error_messages: ["TypeError: x is undefined", "Render failed"],
    });
  });

  it("captures nothing that was typed or shown", () => {
    const input = document.getElementById("gstin");
    input.value = "27AAPFU0939F1ZV";
    click(input);
    expect(JSON.stringify(snapshot())).not.toContain("27AAPFU0939F1ZV");
  });
});
