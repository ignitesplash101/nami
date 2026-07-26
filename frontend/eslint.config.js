import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

// Deliberately narrow. This config exists for ONE failure class: Phase 33 shipped a
// Rules-of-Hooks crash (a hook called below ResultsPanel's early returns — a
// first-run crash) that typecheck and unit tests structurally could not catch, and
// the phase log flagged the missing gate as a candidate addition. Style opinions
// stay out; widen only with a reason.
export default tseslint.config(
  {
    ignores: [
      "dist",
      "node_modules",
      "coverage",
      "playwright-report",
      "test-results",
      "**/*.tsbuildinfo",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.browser },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      // Warn, not error: the existing tree has deliberate omissions (one-shot
      // effects, stable refs) that would need individual review. Escalate once
      // the backlog is worked through.
      "react-hooks/exhaustive-deps": "warn",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrorsIgnorePattern: "^_" },
      ],
    },
  },
  {
    files: ["**/*.test.{ts,tsx}", "e2e/**/*.ts", "vite.config.ts", "vitest.config.ts"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
  },
  {
    files: ["**/*.mjs"],
    languageOptions: { globals: { ...globals.node }, sourceType: "module" },
  },
);
