import { describe, expect, it } from "vitest";
import { buildItcDashboard, daysUntil, emptyItcMonths, itcClaimDeadline, monthStatus } from "./itcDashboard";

function year(overrides = {}) {
  return emptyItcMonths().map((m, i) => ({ ...m, books: 100000, gstr2b: 100000, claimed: 100000, ...(overrides[i] || {}) }));
}

describe("deadline helpers", () => {
  it("puts the Section 16(4) deadline on 30 November after the year", () => {
    expect(itcClaimDeadline("2025-26")).toBe("2026-11-30");
    expect(itcClaimDeadline("bad")).toBeNull();
  });

  it("counts days left, negative once passed", () => {
    expect(daysUntil("2026-11-30", "2026-10-31")).toBe(30);
    expect(daysUntil("2026-11-30", "2026-11-30")).toBe(0);
    expect(daysUntil("2026-11-30", "2026-12-05")).toBe(-5);
    expect(daysUntil(null, "2026-01-01")).toBeNull();
  });
});

describe("monthStatus", () => {
  it("ranks excess above pending above matched, ignoring rounding", () => {
    expect(monthStatus({ excess: 500, unclaimed: 500, supplierGap: 0 })).toBe("excess");
    expect(monthStatus({ excess: 50, unclaimed: 500, supplierGap: 0 })).toBe("pending");
    expect(monthStatus({ excess: 0, unclaimed: 0, supplierGap: 900 })).toBe("pending");
    expect(monthStatus({ excess: 99, unclaimed: 99, supplierGap: 99 })).toBe("matched");
  });
});

describe("buildItcDashboard", () => {
  it("returns null for an empty year", () => {
    expect(buildItcDashboard({ months: emptyItcMonths() })).toBeNull();
    expect(buildItcDashboard()).toBeNull();
  });

  it("is low risk with full coverage when all three agree", () => {
    const d = buildItcDashboard({ months: year(), today: "2026-10-31" });
    expect(d.filledMonths).toBe(12);
    expect(d.matchedMonths).toBe(12);
    expect(d.totals).toMatchObject({ books: 1200000, gstr2b: 1200000, claimed: 1200000, excess: 0, unclaimed: 0 });
    expect(d.coverage).toBe(100);
    expect(d.risk).toBe("low");
    expect(d.daysLeft).toBe(30);
    expect(d.deadlinePassed).toBe(false);
  });

  it("flags excess claims with 50(3) interest from the month's 3B due date", () => {
    // April: claimed 1,10,000 against 2B 1,00,000; due 20 May 2025, viewed 20 May 2026 → 365 days.
    const d = buildItcDashboard({ months: year({ 0: { claimed: 110000 } }), today: "2026-05-20" });
    const april = d.months[0];
    expect(april).toMatchObject({ status: "excess", excess: 10000, interestExposure: 1800 });
    expect(d.totals.excess).toBe(10000);
    expect(d.risk).toBe("high");
    expect(d.coverage).toBe(99.2);
  });

  it("separates unclaimed eligible credit from supplier-side gaps", () => {
    const d = buildItcDashboard({
      months: year({ 1: { claimed: 80000 }, 2: { books: 130000, gstr2b: 100000 } }),
      today: "2026-01-01",
    });
    expect(d.months[1]).toMatchObject({ status: "pending", unclaimed: 20000, supplierGap: 0 });
    expect(d.months[2]).toMatchObject({ status: "pending", unclaimed: 0, supplierGap: 30000 });
    expect(d.risk).toBe("medium");
    expect(d.totals.interestExposure).toBe(0);
  });

  it("caps unclaimed at what GSTR-2B supports", () => {
    const d = buildItcDashboard({ months: year({ 0: { books: 100000, gstr2b: 60000, claimed: 50000 } }) });
    expect(d.months[0]).toMatchObject({ unclaimed: 10000, supplierGap: 40000, excess: 0 });
  });

  it("marks the deadline passed and leaves unfilled months empty", () => {
    const months = emptyItcMonths();
    months[5] = { ...months[5], books: "5000", claimed: "5000", gstr2b: "5000" };
    const d = buildItcDashboard({ months, today: "2026-12-10" });
    expect(d.filledMonths).toBe(1);
    expect(d.months[0].status).toBe("empty");
    expect(d.deadlinePassed).toBe(true);
    expect(d.daysLeft).toBe(-10);
  });

  it("lists suppliers whose GSTR-2B trails your books, largest gap first", () => {
    const d = buildItcDashboard({
      months: year(),
      suppliers: [
        { name: "Alpha Traders", books: "50000", gstr2b: "50000" },
        { name: "Beta Steel", books: "90000", gstr2b: "30000" },
        { name: "  ", books: "999999", gstr2b: "0" },
        { name: "Gamma Logistics", books: "20000", gstr2b: "5000" },
      ],
    });
    expect(d.followUps.map((s) => s.name)).toEqual(["Beta Steel", "Gamma Logistics"]);
    expect(d.followUps[0].gap).toBe(60000);
  });

  it("reports full coverage when nothing has been claimed yet", () => {
    const d = buildItcDashboard({ months: year({}).map((m) => ({ ...m, claimed: 0 })) });
    expect(d.coverage).toBe(100);
    expect(d.totals.unclaimed).toBe(1200000);
  });
});
