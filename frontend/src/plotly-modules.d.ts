// Type shims for the partial-bundle Plotly wiring (PlotLazy.tsx). The factory
// entry and the dist-min bundles ship no types; reuse react-plotly.js's Plot
// props so call sites keep full type checking.
declare module "react-plotly.js/factory" {
  import type Plot from "react-plotly.js";
  export default function createPlotlyComponent(plotly: unknown): typeof Plot;
}

declare module "plotly.js-finance-dist-min" {
  const Plotly: unknown;
  export default Plotly;
}
