// ESLint flat config.
//
// Scoped deliberately narrowly. The point of linting this codebase is to catch
// the mistakes that survive a passing test suite — a hook called conditionally,
// a variable that no longer exists, a dependency array that silently stales a
// closure. Style is not in scope: the source is hand-formatted, and a rule that
// rewrites it would churn every file without making anything more correct.
// That mirrors the backend, where ruff lints but `ruff format` is not run.

import js from "@eslint/js";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

export default [
  {
    ignores: ["dist/**", "node_modules/**", "coverage/**"],
  },

  js.configs.recommended,

  {
    files: ["**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
      globals: {
        ...globals.browser,
      },
    },
    settings: {
      // Without this the plugin warns on every file that it is guessing.
      react: { version: "detect" },
    },
    plugins: {
      react,
      "react-hooks": reactHooks,
    },
    rules: {
      ...react.configs.flat.recommended.rules,
      // The app is on the new JSX transform, so React is not in scope in a
      // file that only renders — these two rules are for the old runtime.
      "react/react-in-jsx-scope": "off",
      "react/jsx-uses-react": "off",

      // The rules this config exists for. A stale dependency array is the
      // single hardest bug to see by reading, and the pages here are built out
      // of useCallback/useEffect pairs where it is easy to get wrong.
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",

      // Off: props are documented by the components' own comments, and turning
      // this on would mean several hundred lines of propTypes that no test
      // reads and the build strips.
      "react/prop-types": "off",

      // Unused code is either a leftover or a typo, and both are worth seeing.
      // The underscore escape hatch is for a signature that must keep a
      // parameter it does not use, e.g. a catch binding or an event handler.
      "no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrors: "none",
        },
      ],

      // console.error is how ErrorBoundary reports, and the browser console is
      // the only reporting channel this app has. A stray console.log is not.
      "no-console": ["warn", { allow: ["error", "warn"] }],
    },
  },

  {
    // Tests run in jsdom under vitest, so they have both browser globals and
    // the test runner's. Without this every `describe` is an undefined name.
    files: ["**/*.test.{js,jsx}", "src/test/**"],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
        describe: "readonly",
        it: "readonly",
        test: "readonly",
        expect: "readonly",
        beforeEach: "readonly",
        afterEach: "readonly",
        beforeAll: "readonly",
        afterAll: "readonly",
        vi: "readonly",
      },
    },
  },

  {
    // Config files are Node, not browser, and so are the build scripts
    // (scripts/*.mjs — the prerender), which the block above does not match:
    // linted with no globals at all, every `process` and `console` in them
    // was an error.
    files: ["*.config.js", "vite.config.js", "**/*.mjs"],
    languageOptions: {
      globals: { ...globals.node },
    },
  },
];
