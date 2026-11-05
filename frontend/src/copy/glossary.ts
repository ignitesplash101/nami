/** Single source of truth for plain-language explanations of quant terms.
 * `plain` is the retail-first sentence (no formulas, no Greek); `detail`
 * carries the precise quant statement — including any honesty caveat, which
 * must survive VERBATIM when a surface migrates its hover-title here. */

export interface GlossaryEntry {
  term: string;
  plain: string;
  detail?: string;
  naiveDetail?: string;
}

export const GLOSSARY = {
  singleNameNoise: {
    term: "Single-name noise (±1σ)",
    plain:
      "How much individual stocks' own moves could swing this result beyond the market-wide factors.",
    detail:
      "±1σ idiosyncratic dispersion around the factor-driven point estimate, scaled to the median selected-analog horizon. A dispersion floor under independence assumptions — not a confidence interval on the scenario."
  },
  historicalEvents: {
    term: "Historical events",
    plain:
      "Real past market episodes matched to this scenario; their measured moves anchor and bound the shock sizes.",
    detail:
      "Called analogs in the methodology: each selected event's realized factor returns feed the evidence envelope."
  },
  rSquaredAdj: {
    term: "R² adj",
    plain:
      "How much of this stock's weekly moves the factors explain — higher means the model knows this name better.",
    detail:
      "Degrees-of-freedom-adjusted R² from the ridge regression; can be negative for poorly explained names."
  },
  idioVolWeekly: {
    term: "Idio vol (wk)",
    plain: "This stock's typical weekly wobble that the factors don't explain.",
    detail:
      "Weekly idiosyncratic volatility — the standard deviation of the regression residuals; not annualized."
  },
  scenarioMove: {
    term: "Scenario move",
    plain:
      "How far the scenario pushes each market driver — the same move for every portfolio. The dots show what that driver actually did in each matched historical event.",
    detail:
      "The shock applied to the factor's return series (decimal change over the scenario horizon; yields and volatility move as a percent of their level). The shaded band is the analogs' p10–p90 envelope, shown only when at least 3 events cover the factor. Each row is scaled to its own factor's history."
  },
  pnlEffect: {
    term: "Effect on your P&L",
    plain:
      "What that move does to this portfolio, given how exposed its holdings are. Every row shares one scale, so bar lengths compare directly.",
    detail:
      "The factor's contribution under explicit conditional Shapley attribution: it sums exactly to the factor P&L, correlated shocks share credit, and unshocked factors stay at 0. Company-specific rows are weight × the single-name shock.",
    naiveDetail:
      "This result carries no conditional attribution, so each factor row is the engine's naive exposure × shock (the Σ weight × beta multiplier times the move). Company-specific rows are weight × the single-name shock."
  },
  portfolioBeta: {
    term: "Portfolio beta",
    plain: "How hard a 1% move in each factor would hit this book, given its current holdings.",
    detail: "Σ weight × beta per factor — the exact multiplier a scenario shock is applied to."
  }
} satisfies Record<string, GlossaryEntry>;
