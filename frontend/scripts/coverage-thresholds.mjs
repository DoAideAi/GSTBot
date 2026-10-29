// The coverage ratchet, read by vitest (vite.config.js) and by CI's coverage
// step (scripts/check-coverage.mjs), so the two can never disagree. Why each
// figure is where it is: see the comment above `thresholds` in vite.config.js.
export const COVERAGE_THRESHOLDS = { statements: 99, branches: 99.5, functions: 99, lines: 99 };
