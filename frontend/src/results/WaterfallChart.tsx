import { Suspense } from "react";
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

/** The attribution waterfall plot. Reads chartTheme() at render, so a theme
 * flip (which re-renders the results tree) re-colors it automatically. */
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
  return (
    <Suspense fallback={<div className="skeleton-block" style={{ height: chartHeight }} />}>
      <PlotLazy
        data={[
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
        ]}
        layout={{
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
        }}
        config={{ displayModeBar: false, responsive: true }}
        useResizeHandler
        className="plot"
      />
    </Suspense>
  );
}
