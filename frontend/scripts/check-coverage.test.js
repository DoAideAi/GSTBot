import { describe, expect, it } from "vitest";
import { shortfalls } from "./check-coverage.mjs";
import { COVERAGE_THRESHOLDS } from "./coverage-thresholds.mjs";

const summary = (pct) => ({
  total: Object.fromEntries(
    ["statements", "branches", "functions", "lines"].map((metric) => [metric, { pct }]),
  ),
});

describe("check-coverage", () => {
  it("passes coverage that meets every threshold", () => {
    expect(shortfalls(summary(100))).toEqual([]);
  });

  it("names each metric under its threshold", () => {
    const found = shortfalls(summary(95));
    expect(found).toHaveLength(4);
    expect(found.join("\n")).toContain("branches: 95% is under the 99.5% threshold");
  });

  it("treats exactly the threshold as met", () => {
    expect(shortfalls(summary(99), { lines: 99 })).toEqual([]);
  });

  it("fails a summary that does not carry a metric", () => {
    expect(shortfalls({ total: {} })).toHaveLength(Object.keys(COVERAGE_THRESHOLDS).length);
  });
});
