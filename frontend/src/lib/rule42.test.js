import { describe, expect, it } from "vitest";
import { computeRule42 } from "./rule42";

const BASE = {
  total: 100_000,
  nonBusiness: 5_000,
  exemptOnly: 10_000,
  blocked: 5_000,
  taxableOnly: 30_000,
  exemptTurnover: 2_000_000,
  totalTurnover: 10_000_000,
};

describe("computeRule42", () => {
  it("reverses the exempt-turnover share of the common credit", () => {
    const r = computeRule42(BASE);
    expect(r.C1).toBe(80_000);
    expect(r.C2).toBe(50_000);
    expect(r.D1).toBe(10_000);
    expect(r.D2).toBe(0);
    expect(r.C3).toBe(40_000);
    expect(r.reversal).toBe(10_000);
    expect(r.eligible).toBe(70_000);
    expect(r.notCredited).toBe(20_000);
  });

  it("adds 5% of common credit when common inputs are also used outside the business", () => {
    const r = computeRule42({ ...BASE, commonUsedForNonBusiness: true });
    expect(r.D2).toBe(2_500);
    expect(r.reversal).toBe(12_500);
    expect(r.C3).toBe(37_500);
  });

  it("keeps all common credit when nothing is exempt", () => {
    const r = computeRule42({ ...BASE, exemptTurnover: 0 });
    expect(r.D1).toBe(0);
    expect(r.eligible).toBe(80_000);
  });

  it("treats blank optional fields as zero", () => {
    const r = computeRule42({ total: 1000, nonBusiness: "", exemptTurnover: "", totalTurnover: 10 });
    expect(r.C2).toBe(1000);
    expect(r.reversal).toBe(0);
  });

  it("refuses parts that add up to more than the total credit", () => {
    expect(computeRule42({ ...BASE, taxableOnly: 90_000 })).toEqual({ error: "parts-exceed-total" });
  });

  it("asks for turnover instead of dividing by a period that had none", () => {
    expect(computeRule42({ ...BASE, totalTurnover: 0 })).toEqual({ error: "no-turnover" });
  });

  it("refuses exempt turnover larger than total turnover", () => {
    expect(computeRule42({ ...BASE, exemptTurnover: 20_000_000 })).toEqual({ error: "exempt-exceeds-total" });
  });

  it("refuses negative and non-numeric amounts", () => {
    expect(computeRule42({ ...BASE, blocked: -1 })).toEqual({ error: "negative" });
    expect(computeRule42({ ...BASE, total: "abc" })).toEqual({ error: "negative" });
  });
});
