import { describe, expect, it } from "vitest";
import { computeEcommerceTcs } from "./ecommerceTcs";

describe("computeEcommerceTcs", () => {
  it("charges 0.5% on net sales, split CGST/SGST within the state", () => {
    const r = computeEcommerceTcs({ grossSales: 1_000_000, returns: 100_000 });
    expect(r.net).toBe(900_000);
    expect(r.tcs).toBe(4500);
    expect(r.cgst).toBe(2250);
    expect(r.sgst).toBe(2250);
    expect(r.igst).toBe(0);
  });

  it("takes 194-O TDS at 0.1% of gross sales", () => {
    const r = computeEcommerceTcs({ grossSales: 1_000_000, returns: 100_000 });
    expect(r.tds194O).toBe(1000);
    expect(r.totalWithheld).toBe(5500);
  });

  it("charges IGST on the inter-state share", () => {
    const r = computeEcommerceTcs({ grossSales: 200_000, interstatePct: 25 });
    expect(r.tcs).toBe(1000);
    expect(r.igst).toBe(250);
    expect(r.cgst).toBe(375);
    expect(r.sgst).toBe(375);
  });

  it("keeps the split summing to the total when halving leaves a paisa", () => {
    const r = computeEcommerceTcs({ grossSales: 1234.57 });
    expect(r.cgst + r.sgst + r.igst).toBeCloseTo(r.tcs, 2);
  });

  it("clamps the inter-state share to 0–100%", () => {
    expect(computeEcommerceTcs({ grossSales: 100_000, interstatePct: 150 }).igst).toBe(500);
    expect(computeEcommerceTcs({ grossSales: 100_000, interstatePct: -5 }).igst).toBe(0);
  });

  it("charges no TCS when returns exceed sales, and reports the excess", () => {
    const r = computeEcommerceTcs({ grossSales: 50_000, returns: 80_000 });
    expect(r.tcs).toBe(0);
    expect(r.excessReturns).toBe(30_000);
    expect(r.tds194O).toBe(50);
  });

  it("rejects negative or non-numeric input", () => {
    expect(computeEcommerceTcs({ grossSales: -1 })).toBeNull();
    expect(computeEcommerceTcs({ grossSales: "abc" })).toBeNull();
    expect(computeEcommerceTcs({ grossSales: 100, returns: -5 })).toBeNull();
  });
});
