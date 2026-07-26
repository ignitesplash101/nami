import { Suspense, useMemo } from "react";
import { PlotLazy } from "../PlotLazy";
import { chartTheme } from "../charts";
import type { WaterfallData } from "../charts";

type WaterfallTrace = {
  type: "waterfall";
  orientation: "v";
  x: string[];
  y: number[];
  measure: ("relative" | "total")[];
  text: string[];
  hovertext: string[];
  hovertemplate: string;
  textposition: "outside";
  connector: { line: { color: string } };
  increasing: { marker: { color: string } };
  decreasing: { marker: { color: string } };
  totals: { marker: { color: string } };
};

const PLOT_CONFIG = { displayModeBar: false, responsive: true };

/** The attribution waterfall plot.
 *
 * `data`/`layout`/`config` MUST be memoized: react-plotly.js compares them by
 * REFERENCE (`prevProps.layout === this.props.layout`, factory.js), so fresh
 * object literals made `figureChanged` true on every render and triggered a full
 * `Plotly.react()`. With NAV lifted to App state, that meant one full re-plot per
 * keystroke in the NAV field — two for admins, who also render a second hidden
 * waterfall in the Advanced tab.
 *
 * `chartTheme()` is memoized per theme and returns a STABLE identity while the
 * theme is unchanged, so using it as a dep both keeps the memo alive across
 * renders and invalidates it on a theme flip — which is what re-colors the chart.
 */
export function WaterfallChart({
  waterfall,
  showDollars,
  chartHeight,
  isPhone
}: {
  waterfall: WaterfallData;
  showDollars: boolean;
  chartHeight: number;
  isPhone: boolean;
}) {
  const theme = chartTheme();
  const data = useMemo(
    () => [
      {
        type: "waterfall",
        orientation: "v",
        x: waterfall.x,
        y: waterfall.y,
        measure: waterfall.measure,
        text: waterfall.text,
        hovertext: waterfall.hoverText,
        hovertemplate: "%{hovertext}<extra></extra>",
        textposition: "outside",
        connector: { line: { color: theme.connector } },
        increasing: { marker: { color: theme.up } },
        decreasing: { marker: { color: theme.down } },
        totals: { marker: { color: theme.total } }
      } as WaterfallTrace
    ],
    [waterfall, theme]
  );
  const layout = useMemo(
    () => ({
      autosize: true,
      height: chartHeight,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: theme.text, family: theme.fontMono },
      margin: { l: 42, r: 18, t: 20, b: isPhone ? 110 : 70 },
      yaxis: {
        tickformat: showDollars ? "$,.0f" : ".1%",
        gridcolor: theme.grid
      },
      xaxis: {
        tickangle: isPhone ? -90 : -35,
        tickfont: isPhone ? { size: 9 } : undefined,
        automargin: true
      },
      showlegend: false
    }),
    [chartHeight, isPhone, showDollars, theme]
  );
  return (
    <Suspense fallback={<div className="skeleton-block" style={{ height: chartHeight }} />}>
      <PlotLazy
        data={data}
        layout={layout}
        config={PLOT_CONFIG}
        useResizeHandler
        className="plot"
      />
    </Suspense>
  );
}
