# nami frontend

React + TypeScript + Vite + Plotly.js workbench for the nami scenario explorer.

See the [root README](../README.md) for the project overview, backend setup, and live demo link.

## Stack

- **React 18** + **TypeScript 5** (strict mode)
- **Vite 6** dev server + build
- **Plotly.js** for waterfall + bar charts
- **react-markdown** for the methodology drawer
- **Vitest + React Testing Library + jsdom** for tests
- **lucide-react** for icons

## Standalone scripts

```bash
npm install
npm run dev          # Vite dev server, http://localhost:5173, proxies /api → :8080
npm run typecheck    # tsc --noEmit, no build artifacts
npm test             # vitest run
npm run build        # tsc -b && vite build → dist/
npm run bundle:check # enforce initial and lazy Plotly gzip budgets
npm run e2e          # mocked Chromium release matrix
```

The dev server expects the FastAPI backend at `http://localhost:8080` (see `vite.config.ts`). Start the backend separately with `uv run uvicorn app.api.main:api --reload --port 8080` from the repo root.

## Notable internal modules

- [src/api.ts](src/api.ts) — typed client for the FastAPI endpoints, including `/api/factors` metadata and the SSE chunked reader (`runScenarioStream`) that drives the engine-aware progress UI
- [src/useOverlay.ts](src/useOverlay.ts) — shared body-scroll-lock + Esc-to-close primitive for overlay state
- [src/OverlayShell.tsx](src/OverlayShell.tsx) — shared drawer/dialog frame for backdrop click, focus trap, focus return, optional close header, and initial focus
- [src/useMediaQuery.ts](src/useMediaQuery.ts) — SSR-safe media-query hook; drives the desktop ↔ tablet rail switch and the mobile Plotly layout
- [src/MethodologyDrawer.tsx](src/MethodologyDrawer.tsx) — slide-in drawer that parses `docs/methodology.md` at render time, sections split on `\n---\n`
- [src/RunProgress.tsx](src/RunProgress.tsx) — the 7-step stepper (cache_check → market → analogs → envelope → narrative → betas → attribution)
- [src/factors.ts](src/factors.ts) — factor label helpers; render human labels plus transparent tickers throughout the workbench
- [src/charts.ts](src/charts.ts) — Plotly trace builders for the systematic waterfall, group-total attribution view, material periphery expansion, factor shocks, and production-readout defaults
- [src/results/ResultsPanel.tsx](src/results/ResultsPanel.tsx) — engine-aware results surface; legacy keeps Conditional Shapley/adjustment diagnostics while Quant V2 shows direct attribution and its historical model range/support
- [src/results/exportBundle.ts](src/results/exportBundle.ts) — one lazy ZIP export of formula-safe UTF-8 CSVs, including Quant range/support/exposure/source files when present
- [src/App.tsx](src/App.tsx) — first-screen workbench layout; visitor and admin share sample chips plus a Custom state, while visitor custom text stays restricted to sample portfolios

## Tests

Frontend tests cover the load-bearing UI logic:

- `App.test.tsx` — access-gated rendering (visitor vs admin permissions)
- `charts.test.ts` — waterfall, group-total attribution, material periphery expansion, and attribution-selection chart helpers
- `useOverlay.test.ts` — overlay primitive (body lock, Esc handling, onClose ordering)
- `OverlayShell.test.tsx` — shared overlay frame focus/backdrop behavior
- `uiCleanup.test.tsx` — compact visitor first screen, custom text affordance, and non-duplicated result summary facts

The mocked Playwright suite is the deterministic release gate for desktop/phone layouts, both themes, 200% text, overlays/fullscreen, transport retries, and declared API contracts. Quant V2 controls, payload values, direct results, hidden legacy-only tabs, and no-overflow behavior run in both themes at 390px and 1440px. It does not replace a live backend smoke check for network-dependent Gemini, FRED, French-library, or Yahoo behavior.

## Build output

`npm run build` emits to `dist/`, which the FastAPI app serves via `StaticFiles` at runtime (`app/api/main.py` line 591). The multi-stage `Dockerfile` runs `npm ci && npm run build` in a Node stage and copies `dist/` into the Python stage — see the root [Dockerfile](../Dockerfile).
