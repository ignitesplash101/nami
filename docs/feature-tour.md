# Nami feature tour

This is the detailed companion to the project overview. It explains how the
scenario engine, analyst workflow, evidence surfaces, and operational controls fit
together without making the main README carry the full product inventory.

## Start with the answer

Every completed run opens with a plain-language impact summary: modeled portfolio
P&L, the largest driver, active return against the selected benchmark, and the
amount of historical evidence behind the result. The waterfall then separates
systematic factor contributions from material ticker-specific shocks.

The page deliberately keeps the answer layer visible while deeper material is
organized into Drivers, Positions, Story, Adjust, and Advanced views. A live
seven-step progress stream shows where an uncached run is spending time, and a
command palette accelerates common actions without becoming the only way to reach
them.

## Understand the portfolio first

The portfolio profile is an engine-only workflow: it uses no language-model calls.
It shows the weighted factor exposures that scenario shocks will hit, per-position
fit quality, usable history, idiosyncratic volatility, and the portfolio's one-week
idiosyncratic dispersion floor.

Sample books use a dated, frozen snapshot of capitalization weights and descriptive
tags. That makes runs reproducible and prevents runtime data drift. Custom books can
include a benchmark and a zero-exposure cash sleeve. Results can be viewed as
returns, against the benchmark, or as original-to-stressed position values after a
notional value or marked quantity is supplied.

Sector and country views connect portfolio composition to modeled P&L, so a user
can distinguish a large exposure from a large loss contribution.

## Challenge the severity

Nami provides several deliberately different comparisons:

- **Historical-event replay** pushes every curated event through the current
  portfolio's estimated betas. It is a factor-model severity screen, not a backtest.
- **Analog replay** shows what the same portfolio model implies if each selected
  analog's realized factor moves are applied directly.
- **Severity bounds** move each evidence-banded shock to the favorable or adverse
  edge for this portfolio, creating exact best, base, and worst engine outcomes.
- **Idiosyncratic dispersion** reports a residual-risk floor; it is explicitly not
  presented as a confidence interval.

One shared Evidence & bounds surface puts those ranges on a comparable scale. It
also calls out shocks with no enforced historical band, scenarios outside their own
analog replay range, and positions with weakly determined betas.

An engine-replay harness goes further: it estimates vintage betas for each valid
historical event and sample-book pair, compares modeled returns with realized
buy-and-hold returns, and publishes pair-level omissions. This separates
quantitative-engine tracking error from scenario-interpretation error.

## Explore and preserve the result

An analyst can adjust structured shocks with sliders or a short natural-language
instruction without repeating analog selection or evidence gathering. Notional
values update dollar P&L immediately, while marked portfolios use date-appropriate
prices and fail closed when a required mark or currency conversion is unavailable.

Backdated runs enforce no-look-ahead rules on events and market data. Their reports
also disclose two unavoidable caveats: the language model itself is not restored to
a historical vintage, and sample-book weights come from today's dated snapshot.

Named portfolios retain immutable dated holding snapshots. Saved analyses contain
their complete result, exact holdings, selected events, notes, tags, and
reproducibility metadata. Permalinks reopen the stored record without relying on a
live cache or a changing event registry.

Analyst tables use tabular numerals, sorting, and wide-table overflow affordances.
A protected UTF-8 export bundle captures the complete result, while the event replay
and operations surfaces keep their own purpose-specific exports.

## Inspect the methodology

The production attribution view includes only factors explicitly shocked by the
scenario; unshocked factors remain zero. A grouped view rolls contributions into
market, sector, style, and macro totals. Algebraic and full-conditional variants are
kept as advanced diagnostics and never replace the headline result.

Every saved record includes model, prompt, factor-universe, event-registry, and
regression versions together with the selected events, holdings, lookback settings,
and requested and effective dates. The in-app methodology viewer links factor names
and attribution controls directly to the relevant explanation and references.

## Operate it responsibly

Paid endpoints have per-client rate limits, a transactional daily cost breaker, a
run cap, and token accounting. Passcode attempts have durable lockout protection.
Structured logs, request identifiers, dependency readiness checks, and an audit
trail make failures traceable.

The administrative console shows run volume, estimated spend, token use, cache-hit
rate, errors, and latency. It derives aggregate usage from the application's own
access log: there is no tracking cookie or separate analytics service. Hashed network
identifiers are used only for distinct-visitor counting and remain server-side.

Errors use a machine-readable contract that maps each cause to a specific message
and recovery action. Runs can be cancelled, concurrent attempts cannot overwrite
one another, expired sessions surface visibly, and mutating actions confirm their
outcome. Administrative data can be exported or purged through guarded workflows.

## Use it across devices

The interface supports keyboard navigation, visible focus states, trapped modal
focus, labelled controls, reduced-motion preferences, screen-reader announcements,
browser text scaling, and touch targets sized for compact screens. Responsive checks
cover widths from 320 to 1920 pixels, both visual themes, horizontal overflow, compact
targets, and 200% text scaling.

The first-load script is 89.67 KiB compressed and the complete on-demand chart path
is 402.79 KiB compressed. Release checks enforce 100 KiB and 425 KiB budgets,
respectively. Heavy chart and methodology code loads only when needed, and immutable
content-hashed assets make repeat visits fast.
