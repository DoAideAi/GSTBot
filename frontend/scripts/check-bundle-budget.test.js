import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import { describe, expect, it } from "vitest";
import { BUDGET_KB, measure, overBudget } from "./check-bundle-budget.mjs";

// P24 M15: the frontend had no performance budget at all.
function dist(files) {
  const dir = mkdtempSync(join(tmpdir(), "budget-"));
  mkdirSync(join(dir, "assets"));
  writeFileSync(
    join(dir, "index.html"),
    '<script src="/assets/index-a.js"></script><link href="/assets/index-a.css">',
  );
  for (const [name, bytes] of Object.entries(files)) writeFileSync(join(dir, "assets", name), bytes);
  return dir;
}

describe("the bundle budget", () => {
  it("measures what the page loads first, gzipped, and each lazy chunk", () => {
    const measured = measure(dist({ "index-a.js": "a".repeat(50_000), "index-a.css": "b", "page-x.js": "c" }));
    expect(measured.firstLoadAssets).toEqual(["/assets/index-a.js", "/assets/index-a.css"]);
    expect(measured.firstLoad).toBeLessThan(1_000); // 50 KB of one letter gzips to almost nothing
    // The entry is counted in the first load, not again as a chunk.
    expect(Object.keys(measured.chunks)).toEqual(["page-x.js"]);
    expect(overBudget(measured)).toEqual([]);
  });

  it("names a first load and a chunk that are over", () => {
    // Random bytes do not compress, so these are their gzipped size too.
    const big = randomBytes((BUDGET_KB.firstLoad + 5) * 1024);
    const chunk = randomBytes((BUDGET_KB.chunk + 5) * 1024);
    const problems = overBudget(measure(dist({ "index-a.js": big, "index-a.css": "x", "page-y.js": chunk })));
    expect(problems.some((p) => p.startsWith("first load is"))).toBe(true);
    expect(problems.some((p) => p.startsWith("page-y.js is"))).toBe(true);
  });
});
