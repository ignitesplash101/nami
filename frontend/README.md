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
```

The dev server expects the FastAPI backend at `http://localhost:8080` (see `vite.config.ts`). Start the backend separately with `uv run uvicorn app.api.main:api --reload --port 8080` from the repo root.

## Notable internal modules

- [src/api.ts](src/api.ts) — typed client for the FastAPI endpoints, including the SSE chunked reader (`runScenarioStream`) that drives the 7-step progress UI
- [src/useOverlay.ts](src/useOverlay.ts) — shared body-scroll-lock + Esc-to-close primitive for overlay state
- [src/OverlayShell.tsx](src/OverlayShell.tsx) — shared drawer/dialog frame for backdrop click, focus trap, focus return, optional close header, and initial focus
- [src/useMediaQuery.ts](src/useMediaQuery.ts) — SSR-safe media-query hook; drives the desktop ↔ tablet rail switch and the mobile Plotly layout
- [src/MethodologyDrawer.tsx](src/MethodologyDrawer.tsx) — slide-in drawer that parses `docs/methodology.md` at render time, sections split on `\n---\n`
- [src/RunProgress.tsx](src/RunProgress.tsx) — the 7-step stepper (cache_check → market → analogs → envelope → narrative → betas → attribution)
- [src/charts.ts](src/charts.ts) — Plotly trace builders for waterfall, factor shocks, and attribution comparison
- [src/App.tsx](src/App.tsx) — first-screen workbench layout; visitor mode keeps sample selection chip-only and uses a compact empty-results placeholder

## Tests

Frontend tests cover the load-bearing UI logic:

- `App.test.tsx` — access-gated rendering (visitor vs admin permissions)
- `charts.test.ts` — waterfall and attribution-selection chart helpers
- `useOverlay.test.ts` — overlay primitive (body lock, Esc handling, onClose ordering)
- `OverlayShell.test.tsx` — shared overlay frame focus/backdrop behavior
- `uiCleanup.test.tsx` — compact visitor first screen and non-duplicated result summary facts

No e2e tests yet. Backend changes that affect the API contract should be paired with manual smoke checks via `npm run dev` against a live backend.

## Build output

`npm run build` emits to `dist/`, which the FastAPI app serves via `StaticFiles` at runtime (`app/api/main.py` line 591). The multi-stage `Dockerfile` runs `npm ci && npm run build` in a Node stage and copies `dist/` into the Python stage — see the root [Dockerfile](../Dockerfile).
