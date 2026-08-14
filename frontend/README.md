# nami frontend

React + TypeScript + Vite workbench for the nami scenario explorer. React owns
the waterfall SVG and interaction; `d3-scale` supplies geometry only.

See the [root README](../README.md) for the project overview, backend setup, and
live demo link.

## Stack

- **React 18** + **TypeScript 5** in strict mode
- **Vite 6** for development and production builds
- **D3 scales + React-owned SVG** for the responsive waterfall
- **react-markdown** for the methodology drawer
- **Vitest + React Testing Library + jsdom** for component and pure tests
- **Playwright + axe-core** for responsive, cross-engine, and accessibility gates
- **lucide-react** for icons

## Standalone scripts

```bash
npm ci
npm run dev             # Vite dev server; proxies /api to :8080
npm run lint            # ESLint, including the Rules of Hooks gate
npm run typecheck       # tsc --noEmit, no build artifacts
npm test                # Vitest unit/component suite
npm run test:budget     # bundle-checker unit tests
npm run build           # tsc -b && vite build to dist/
npm run bundle:check    # manifest-based gzip budgets
npm run e2e:chromium    # full two-theme/eight-width browser suite
npm run e2e             # Chromium suite + Firefox/WebKit smoke coverage
```

The dev server expects the FastAPI backend at `http://localhost:8080` (see
`vite.config.ts`). Start it separately with
`uv run uvicorn app.api.main:api --reload --port 8080` from the repo root.

## Notable internal modules

- [src/api.ts](src/api.ts) — typed API client and SSE reader for the seven-step run progress UI
- [src/useOverlay.ts](src/useOverlay.ts) — shared body-scroll-lock and Escape-to-close primitive
- [src/OverlayShell.tsx](src/OverlayShell.tsx) — shared drawer/dialog focus, backdrop, and return-focus frame
- [src/useMediaQuery.ts](src/useMediaQuery.ts) — SSR-safe rail and phone-orientation breakpoint hook
- [src/MethodologyDrawer.tsx](src/MethodologyDrawer.tsx) — lazy methodology surface sourced from `docs/methodology.md`
- [src/RunProgress.tsx](src/RunProgress.tsx) — seven-stage streaming progress stepper
- [src/factors.ts](src/factors.ts) — human factor labels with transparent tickers
- [src/charts.ts](src/charts.ts) — semantic waterfall builders, step caps, periphery preservation, aggregation, residual reconciliation, and formatting
- [src/results/WaterfallChart.tsx](src/results/WaterfallChart.tsx) — lazy chart boundary and safe loading fallback
- [src/results/WaterfallSvg.tsx](src/results/WaterfallSvg.tsx) — ResizeObserver-driven vertical/phone-horizontal SVG with keyboard and pointer tooltips
- [src/App.tsx](src/App.tsx) — application shell and the Scenario / Your book / Library workbench

## Tests and release contracts

Pure tests pin mixed-sign waterfall geometry, aggregation, material periphery,
residuals, invalid input, and percent/currency formatting. Component tests cover
both orientations, resize/fullscreen behavior, accessible names, tooltips, the
factor-table fallback, and theme-token use.

The mocked Playwright gate runs both themes at 320, 390, 768, 1024, 1080, 1440,
1600, and 1920 pixels in Chromium, plus 200% text, overflow, phone exposure rows,
tab persistence, keyboard/fullscreen flow, and serious/critical axe checks.
Firefox and WebKit run the tagged run/chart/theme/fullscreen keyboard smoke flow.
No paid scenario request is needed.

## Build output

`npm run build` emits `dist/` plus Vite's manifest. The bundle checker follows
the manifest graph, counts each file once, and enforces gzip ceilings of 100 KiB
for initial JavaScript, 45 KiB for the complete lazy waterfall path, and 25 KiB
for CSS. FastAPI serves `dist/` at runtime. The multi-stage
[Dockerfile](../Dockerfile) runs `npm ci && npm run build` in its Node stage and
copies the result into the Python image.
