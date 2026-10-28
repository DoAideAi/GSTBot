import { describe, expect, it } from "vitest";
import {
  GST_SLABS,
  calcUrl,
  calculate,
  formatINR,
  parseCalcParams,
  reverseCalculate,
} from "./gstCalc";

describe("GST_SLABS", () => {
  it("contains the eleven GST 2.0 slab rates", () => {
    expect(GST_SLABS).toEqual([0, 0.1, 0.25, 1, 1.5, 3, 5, 6, 7.5, 18, 40]);
  });
});

describe("calculate", () => {
  it("splits intrastate tax into equal CGST and SGST", () => {
    const r = calculate(1000, 18);
    expect(r.taxable).toBe(1000);
    expect(r.cgst).toBe(90);
    expect(r.sgst).toBe(90);
    expect(r.igst).toBe(0);
    expect(r.total).toBe(1180);
    expect(r.interstate).toBe(false);
  });

  it("applies full IGST for interstate supply", () => {
    const r = calculate(1000, 18, { interstate: true });
    expect(r.cgst).toBe(0);
    expect(r.sgst).toBe(0);
    expect(r.igst).toBe(180);
    expect(r.total).toBe(1180);
    expect(r.interstate).toBe(true);
  });

  it("returns zero tax for a zero rate", () => {
    const r = calculate(500, 0);
    expect(r.total).toBe(500);
    expect(r.cgst).toBe(0);
    expect(r.sgst).toBe(0);
  });

  it("returns null for a negative amount", () => {
    expect(calculate(-100, 18)).toBeNull();
  });

  it("returns null for NaN amount", () => {
    expect(calculate(NaN, 18)).toBeNull();
  });

  it("returns null for Infinity", () => {
    expect(calculate(Infinity, 18)).toBeNull();
  });

  it("returns null when rate exceeds 100", () => {
    expect(calculate(1000, 101)).toBeNull();
  });

  it("returns null for a negative rate", () => {
    expect(calculate(1000, -5)).toBeNull();
  });

  it("returns null when rate is NaN", () => {
    expect(calculate(1000, NaN)).toBeNull();
  });

  it("handles a zero amount", () => {
    const r = calculate(0, 18);
    expect(r.taxable).toBe(0);
    expect(r.total).toBe(0);
  });

  it("rounds to two decimal places", () => {
    const r = calculate(100, 7.5);
    expect(r.cgst).toBe(3.75);
    expect(r.sgst).toBe(3.75);
    expect(r.total).toBe(107.5);
  });

  it("sets cess to zero", () => {
    expect(calculate(1000, 18).cess).toBe(0);
  });
});

describe("reverseCalculate", () => {
  it("backs out the correct taxable value from inclusive amount", () => {
    const r = reverseCalculate(1180, 18);
    expect(r.taxable).toBe(1000);
    expect(r.total).toBe(1180);
  });

  it("returns null for a negative total", () => {
    expect(reverseCalculate(-500, 18)).toBeNull();
  });

  it("returns null for NaN total", () => {
    expect(reverseCalculate(NaN, 18)).toBeNull();
  });

  it("returns null for a rate over 100", () => {
    expect(reverseCalculate(1000, 150)).toBeNull();
  });

  it("supports interstate mode", () => {
    const r = reverseCalculate(1180, 18, { interstate: true });
    expect(r.igst).toBe(180);
    expect(r.cgst).toBe(0);
  });
});

describe("formatINR", () => {
  it("formats a number as Indian rupee currency", () => {
    const formatted = formatINR(123456.78);
    expect(formatted).toContain("1,23,456.78");
  });

  it("returns a dash for NaN", () => {
    expect(formatINR(NaN)).toBe("—");
  });

  it("returns a dash for Infinity", () => {
    expect(formatINR(Infinity)).toBe("—");
  });

  it("formats zero", () => {
    expect(formatINR(0)).toContain("0.00");
  });
});

describe("calcUrl", () => {
  it("builds a URL with all parameters for interstate", () => {
    const url = calcUrl(1000, 18, true);
    expect(url).toBe("/calculator?amount=1000&rate=18&type=igst");
  });

  it("omits type param for intrastate", () => {
    const url = calcUrl(1000, 18, false);
    expect(url).toBe("/calculator?amount=1000&rate=18");
  });

  it("returns bare path when no amount given", () => {
    const url = calcUrl(null, undefined, false);
    expect(url).toBe("/calculator");
  });
});

describe("parseCalcParams", () => {
  it("parses valid parameters", () => {
    const p = parseCalcParams("?amount=1000&rate=18&type=igst");
    expect(p.amount).toBe(1000);
    expect(p.rate).toBe(18);
    expect(p.interstate).toBe(true);
  });

  it("returns null amount for missing param", () => {
    const p = parseCalcParams("");
    expect(p.amount).toBeNull();
    expect(p.rate).toBeNull();
    expect(p.interstate).toBe(false);
  });

  it("returns null for negative amount", () => {
    const p = parseCalcParams("?amount=-100&rate=18");
    expect(p.amount).toBeNull();
  });

  it("returns null for rate over 100", () => {
    const p = parseCalcParams("?amount=100&rate=200");
    expect(p.rate).toBeNull();
  });

  it("defaults interstate to false when type is not igst", () => {
    const p = parseCalcParams("?amount=100&rate=18&type=cgst");
    expect(p.interstate).toBe(false);
  });
});

// Expected figures are the backend's own: app.services.gst_calculator's
// on_taxable and from_inclusive, run on the same inputs. The calculator page
// and the invoice the backend builds must agree to the paisa.
describe("parity with the backend calculator", () => {
  it.each([
    [0.5, 18, 0.5, 0.05, 0.6],
    [1.005, 18, 1.01, 0.09, 1.19],
    [12.35, 5, 12.35, 0.31, 12.97],
    [99.99, 28, 99.99, 14, 127.99],
    [0.1, 0.25, 0.1, 0, 0.1],
    [10.03, 7.5, 10.03, 0.38, 10.79],
    [1, 3, 1, 0.02, 1.04],
  ])("taxes %s at %s%% as taxable %s, each head %s, total %s", (amount, rate, taxable, head, total) => {
    const r = calculate(amount, rate);
    expect(r.taxable).toBe(taxable);
    expect(r.cgst).toBe(head);
    expect(r.sgst).toBe(head);
    expect(r.total).toBe(total);
  });

  it("never splits a rounded total into unequal heads", () => {
    // 18% of ₹0.50 is ₹0.09; halving that gave CGST ₹0.05 and SGST ₹0.04.
    for (let paise = 1; paise <= 2000; paise += 1) {
      for (const rate of [0.25, 3, 5, 7.5, 18, 28, 40]) {
        const r = calculate(paise / 100, rate);
        expect(r.cgst).toBe(r.sgst);
      }
    }
  });

  it.each([
    [100, 18, 84.74, 7.63, 84.75, 15.25],
    [99.99, 5, 95.23, 2.38, 95.23, 4.76],
    [1, 18, 0.84, 0.08, 0.85, 0.15],
    [10.01, 12, 8.93, 0.54, 8.94, 1.07],
    [1234.56, 28, 964.5, 135.03, 964.5, 270.06],
  ])("backs %s at %s%% out to the amount typed", (gross, rate, taxable, head, igstTaxable, igst) => {
    const intra = reverseCalculate(gross, rate);
    expect(intra.taxable).toBe(taxable);
    expect(intra.cgst).toBe(head);
    expect(intra.sgst).toBe(head);
    expect(intra.total).toBe(gross);

    const inter = reverseCalculate(gross, rate, { interstate: true });
    expect(inter.taxable).toBe(igstTaxable);
    expect(inter.igst).toBe(igst);
    expect(inter.total).toBe(gross);
  });
});
