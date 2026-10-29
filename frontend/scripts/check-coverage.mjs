// Fails when the suite's coverage is under the ratchet. Run after the tests
// (CI's "Coverage threshold" step):
//
//   node scripts/check-coverage.mjs [coverage/coverage-summary.json]
//
// A step of its own rather than vitest's thresholds, which failed the Test step
// itself. The thresholds have been missed on every run since they were set, so
// Test was red every time and a real failing test was the same red. Here the
// tests and the threshold each say their own thing.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { COVERAGE_THRESHOLDS } from "./coverage-thresholds.mjs";

/** One line per metric under its threshold; empty when every one is met. */
export function shortfalls(summary, thresholds = COVERAGE_THRESHOLDS) {
  const total = summary?.total ?? {};
  return Object.entries(thresholds).flatMap(([metric, required]) => {
    const pct = total[metric]?.pct;
    if (typeof pct !== "number") return [`${metric}: not in the coverage summary`];
    return pct < required ? [`${metric}: ${pct}% is under the ${required}% threshold`] : [];
  });
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const path = resolve(process.argv[2] ?? "coverage/coverage-summary.json");
  const found = shortfalls(JSON.parse(readFileSync(path, "utf8")));
  if (found.length) {
    for (const line of found) console.error(line);
    process.exit(1);
  }
  console.log("Coverage meets every threshold");
}
