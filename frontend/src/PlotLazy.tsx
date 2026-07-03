import { lazy } from "react";

/** The ONLY Plot import path in the app.
 *
 * Two deliberate choices live here:
 * - `plotly.js-finance-dist-min` is the SMALLEST partial bundle that includes
 *   the `waterfall` trace (the `basic` bundle does not) — swapping it for a
 *   smaller partial silently breaks the attribution chart.
 * - `React.lazy` keeps the multi-hundred-KB plotly chunk out of the first
 *   load entirely; it is fetched when the first result renders. Call sites
 *   must wrap in <Suspense> with a skeleton fallback.
 */
export const PlotLazy = lazy(async () => {
  const [{ default: createPlotlyComponent }, { default: Plotly }] = await Promise.all([
    import("react-plotly.js/factory"),
    import("plotly.js-finance-dist-min")
  ]);
  return { default: createPlotlyComponent(Plotly) };
});
