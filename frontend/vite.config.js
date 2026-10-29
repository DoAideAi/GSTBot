// defineConfig comes from vitest/config, not vite: the plain vite helper does
// not carry the `test` key through, which leaves the suite running in the
// default node environment with no DOM and no localStorage.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  build: {
    // deploy.sh builds beside the live dist (GSTBOT_BUILD_DIR=dist.next) and
    // swaps it in only once the build has succeeded; see deploy/deploy.sh.
    outDir: process.env.GSTBOT_BUILD_DIR || "dist",
    rollupOptions: {
      output: {
        // React and the router change only when package.json does, while the
        // app chunk changes on every release. Split, a returning visitor keeps
        // the larger of the two cached across deploys instead of downloading
        // both again for a one-line copy change.
        //
        // A function rather than the object form because scripts/prerender.mjs
        // runs an SSR build off this same config, where React is external and
        // the object form refuses to name an external module.
        manualChunks(id) {
          if (/node_modules\/(react|react-dom|react-router|react-router-dom|scheduler)\//.test(id)) {
            return "vendor";
          }
        },
      },
    },
  },
  server: {
    port: 5173,
    // Proxy /api to the FastAPI backend during development, so the app talks
    // to a same-origin path and CORS never enters the picture locally.
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.js",
    css: false,
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      include: ["src/**/*.{js,jsx}"],
      exclude: [
        "src/**/*.test.{js,jsx}",
        "src/test/**",
        // The entry point mounts the app and applies the preloaded font
        // stylesheet; neither has anything to assert that rendering the app in
        // a test does not, and jsdom loads no stylesheets to check.
        "src/main.jsx",
      ],
      // A ratchet against tests being deleted or a component landing with
      // none — not a target to code towards. Raise it in the commit that
      // earns it, the same way backend/pyproject.toml does.
      //
      // `functions` sat below the rest for as long as v8's count of inline JSX
      // arrows was the reason it could not reach the others: a component whose
      // lines are fully covered still scores under 100 when it renders a row
      // of handlers no single test clicks. 87 → 95 when the flow tests landed
      // and drove the app across pages, which measured 97.
      //
      // The remaining three points were not the JSX artifact at all. They were
      // one handler, written seven times: the `onDismiss` on every page's
      // error banner, which no test had ever clicked — the banner's appearance
      // is what each page test was written about, and the × beside it went in
      // with it and was asserted nowhere. `src/App.dismiss.test.jsx` sweeps
      // the route table for it and the measured figure is 100, so the gate
      // joins the other three at one point under what the suite reaches.
      //
      // `branches` is at 99.5 rather than at the 99.81 actually measured, and
      // the gap is deliberate. Three branches are unreachable by construction
      // and are left in as guards rather than deleted:
      //
      //   * InvoiceDetailPage's `draft[field] ?? ""` — `adopt` already
      //     coerces every field, and the form does not render without an
      //     invoice.
      //   * validate.js's `Number.isFinite(value) ? value : null` — a field
      //     the amount check let through is finite by then.
      //   * ReconcilePage's `|| "Could not load this period."` — every
      //     rejection this page can see is raised by `lib/api.js`, and since
      //     `errorMessage` stopped being able to produce a blank line there is
      //     no API failure left with an empty message. It now answers a
      //     rejection from somewhere else, which is why it stays.
      //
      // A gate at the measured figure would make removing any of those guards
      // the way to keep CI green.
      thresholds: { statements: 99, branches: 99.5, functions: 99, lines: 99 },
    },
  },
});
