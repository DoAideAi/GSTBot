// Fails the build when the first page load, or any one lazy chunk, outgrows
// its budget. Run after `npm run build` (CI's Build step):
//
//   node scripts/check-bundle-budget.mjs [distDir]
//
// The backend has per-route time budgets (app/core/budgets.py) and logs every
// request against them; the frontend had none, so nothing stopped the bundle a
// customer on a phone downloads before seeing anything from growing a little
// with each release. Measured gzipped, as it travels. The limits sit about a
// third above where the build was on 2026-10-29 (first load ~109 KB:
// app 32, vendor 59, CSS 17; the largest lazy page 23 KB), so a heavy new
// dependency trips them and an ordinary feature does not. The per-chunk limit
// is for the lazy pages only: what loads first is already counted, together.
import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { gzipSync } from "node:zlib";

export const BUDGET_KB = { firstLoad: 140, chunk: 40 };

const kb = (bytes) => Math.round((bytes / 1024) * 10) / 10;
const gzipped = (path) => gzipSync(readFileSync(path), { level: 9 }).length;

/** Gzipped sizes: what index.html pulls in first, and each lazy JS chunk. */
export function measure(distDir) {
  const html = readFileSync(join(distDir, "index.html"), "utf8");
  const firstLoad = [...new Set(html.match(/\/assets\/[^"']+\.(?:js|css)/g) ?? [])];
  const chunks = readdirSync(join(distDir, "assets")).filter(
    (name) => name.endsWith(".js") && !firstLoad.includes(`/assets/${name}`),
  );
  return {
    firstLoad: firstLoad.reduce((sum, asset) => sum + gzipped(join(distDir, asset)), 0),
    firstLoadAssets: firstLoad,
    chunks: Object.fromEntries(
      chunks.map((name) => [name, gzipped(join(distDir, "assets", name))]),
    ),
  };
}

/** One line per budget broken; empty when the build fits. */
export function overBudget(measured, budget = BUDGET_KB) {
  const problems = [];
  if (kb(measured.firstLoad) > budget.firstLoad) {
    problems.push(
      `first load is ${kb(measured.firstLoad)} KB gzipped, over its ${budget.firstLoad} KB budget ` +
        `(${measured.firstLoadAssets.join(", ")})`,
    );
  }
  for (const [name, bytes] of Object.entries(measured.chunks)) {
    if (kb(bytes) > budget.chunk) {
      problems.push(
        `${name} is ${kb(bytes)} KB gzipped, over the ${budget.chunk} KB budget for a lazy chunk`,
      );
    }
  }
  return problems;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const dist = resolve(process.argv[2] ?? "dist");
  const measured = measure(dist);
  const problems = overBudget(measured);
  console.log(
    `first load ${kb(measured.firstLoad)}/${BUDGET_KB.firstLoad} KB gzipped; ` +
      `largest lazy chunk ${kb(Math.max(0, ...Object.values(measured.chunks)))}/${BUDGET_KB.chunk} KB`,
  );
  for (const problem of problems) console.error(`over budget: ${problem}`);
  process.exit(problems.length ? 1 : 0);
}
