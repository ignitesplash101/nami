from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.factors.analogs import load_events
from app.llm.schemas import PortfolioPnL, ScenarioResult

_NO_LLM_SHOCK_NOTE = "No explicit LLM shock; attributed via correlation"


def render() -> None:
    st.header("Results")

    result: ScenarioResult | None = st.session_state.get("scenario_result")
    if result is None:
        st.info("Run a scenario from the Scenario tab to see results here.", icon="ℹ️")
        return

    pnl = result.portfolio_pnl
    by_factor = _select_attribution(pnl)

    _render_top_metrics(result, pnl, by_factor)
    st.divider()
    _render_factor_waterfall(pnl, by_factor)
    st.divider()
    _render_factor_reasoning(result, by_factor)
    st.divider()
    _render_periphery_reasoning(result, pnl)
    st.divider()
    _render_name_breakdown(result, pnl)
    st.divider()
    _render_narrative_and_citations(result)
    st.divider()
    _render_narrative_shapley(result)
    st.divider()
    _render_analog_windows(result)


def _select_attribution(pnl: PortfolioPnL) -> dict[str, float]:
    """Render the Naive | Conditional Shapley toggle and return the active dict."""
    shapley_available = pnl.by_factor_conditional_shapley is not None
    options = ["Naive"]
    captions = [
        "(Σᵢ wᵢ · βᵢ,f) · sf — exact per-factor decomposition assuming independence",
    ]
    if shapley_available:
        options.append("Conditional Shapley")
        captions.append(
            "(Experimental) Conditional Shapley — redistributes credit across factors "
            "using historical covariance. NOT a causal attribution."
        )

    if shapley_available:
        method = st.radio(
            "Attribution method",
            options=options,
            captions=captions,
            horizontal=True,
            index=1,  # default to Shapley when available
        )
    else:
        st.caption(
            "Attribution method: **Naive** — (Σᵢ wᵢ · βᵢ,f) · sf "
            "(Conditional Shapley unavailable for this scenario)."
        )
        method = "Naive"

    if method == "Conditional Shapley" and pnl.by_factor_conditional_shapley is not None:
        return pnl.by_factor_conditional_shapley
    return pnl.by_factor_naive


def _render_top_metrics(
    result: ScenarioResult,
    pnl: PortfolioPnL,
    by_factor: dict[str, float],
) -> None:
    if by_factor:
        top_factor, top_contrib = max(by_factor.items(), key=lambda kv: abs(kv[1]))
        top_shock = next((fs.shock for fs in result.factor_shocks if fs.factor == top_factor), 0.0)
    else:
        top_factor, top_contrib, top_shock = "—", 0.0, 0.0

    col_pnl, col_top, col_analogs = st.columns(3)
    col_pnl.metric("Portfolio P&L", f"{pnl.total_pnl:.2%}")
    col_top.metric(
        "Top contributor",
        value=top_factor,
        delta=f"{top_shock:+.1%} shock applied → {top_contrib:+.2%} of P&L",
        delta_color="off",
    )
    col_analogs.metric("Analogs used", len(result.analogs_selected))

    if result.portfolio_name and result.portfolio_name != "(unknown)":
        st.caption(
            f"Portfolio: **{result.portfolio_name}** "
            f"({len(result.portfolio_holdings)} holdings) · "
            f"Scenario date: {result.market_date}"
        )


def _render_factor_waterfall(pnl: PortfolioPnL, by_factor: dict[str, float]) -> None:
    st.subheader("Factor contributions")
    periphery_total = sum(pnl.by_ticker_periphery.values())

    bars = sorted(by_factor.items(), key=lambda kv: abs(kv[1]), reverse=True)
    # Trim near-zero contributions to keep the chart readable
    bars = [(f, v) for f, v in bars if abs(v) > 1e-6]
    bars.append(("Periphery", periphery_total))

    fig = go.Figure(
        go.Waterfall(
            orientation="v",
            x=[name for name, _ in bars] + ["Total"],
            y=[v for _, v in bars] + [pnl.total_pnl],
            measure=["relative"] * len(bars) + ["total"],
            text=[f"{v:.2%}" for _, v in bars] + [f"{pnl.total_pnl:.2%}"],
            textposition="outside",
        )
    )
    fig.update_layout(
        height=420,
        margin={"l": 10, "r": 10, "t": 20, "b": 10},
        yaxis={"tickformat": ".1%"},
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_factor_reasoning(
    result: ScenarioResult,
    by_factor: dict[str, float],
) -> None:
    st.subheader("Factor reasoning")
    st.caption(
        "**Shock applied** = the magnitude the LLM proposed for the factor. "
        "**Contrib to P&L** = the contribution under the selected attribution method. "
        "Rows labelled *'No explicit LLM shock; attributed via correlation'* exist only "
        "when Conditional Shapley is active and the LLM didn't shock that factor."
    )

    shocks_by_factor = {fs.factor: fs for fs in result.factor_shocks}
    rows = []
    for factor, contrib in by_factor.items():
        fs = shocks_by_factor.get(factor)
        if fs is None:
            rows.append(
                {
                    "factor": factor,
                    "shock applied (%)": 0.0,
                    "contrib to P&L (%)": contrib * 100,
                    "LLM reasoning": _NO_LLM_SHOCK_NOTE,
                }
            )
        else:
            rows.append(
                {
                    "factor": factor,
                    "shock applied (%)": fs.shock * 100,
                    "contrib to P&L (%)": contrib * 100,
                    "LLM reasoning": fs.reasoning,
                }
            )
    # Hide near-zero correlation-only rows to avoid 22-row clutter
    rows = [
        r
        for r in rows
        if abs(r["contrib to P&L (%)"]) > 1e-4 or r["LLM reasoning"] != _NO_LLM_SHOCK_NOTE
    ]
    if not rows:
        st.caption("No factor contributions to display.")
        return

    df = pd.DataFrame(rows).sort_values("contrib to P&L (%)").reset_index(drop=True)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "factor": st.column_config.TextColumn("Factor", width="small"),
            "shock applied (%)": st.column_config.NumberColumn("Shock applied (%)", format="%.2f"),
            "contrib to P&L (%)": st.column_config.NumberColumn(
                "Contrib to P&L (%)", format="%.3f"
            ),
            "LLM reasoning": st.column_config.TextColumn("LLM reasoning", width="large"),
        },
    )


def _render_periphery_reasoning(result: ScenarioResult, pnl: PortfolioPnL) -> None:
    if not result.periphery_shocks:
        return
    st.subheader("Periphery (name-specific) reasoning")
    st.caption(
        "Idiosyncratic per-ticker moves the LLM proposed ON TOP OF the factor-driven returns."
    )
    holdings = result.portfolio_holdings
    rows = []
    for ps in result.periphery_shocks:
        weight = holdings.get(ps.ticker, 0.0)
        contrib = pnl.by_ticker_periphery.get(ps.ticker, 0.0)
        rows.append(
            {
                "ticker": ps.ticker,
                "weight (%)": weight * 100,
                "shock applied (%)": ps.shock * 100,
                "contrib to P&L (%)": contrib * 100,
                "LLM reasoning": ps.reasoning,
            }
        )
    df = pd.DataFrame(rows).sort_values("contrib to P&L (%)").reset_index(drop=True)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "ticker": st.column_config.TextColumn("Ticker", width="small"),
            "weight (%)": st.column_config.NumberColumn("Weight (%)", format="%.2f"),
            "shock applied (%)": st.column_config.NumberColumn("Shock applied (%)", format="%.2f"),
            "contrib to P&L (%)": st.column_config.NumberColumn(
                "Contrib to P&L (%)", format="%.3f"
            ),
            "LLM reasoning": st.column_config.TextColumn("LLM reasoning", width="large"),
        },
    )


def _render_name_breakdown(result: ScenarioResult, pnl: PortfolioPnL) -> None:
    st.subheader("Name-level breakdown")
    holdings = result.portfolio_holdings or {}

    rows = []
    for ticker, total in pnl.by_ticker_total.items():
        weight = holdings.get(ticker, 0.0)
        factor_contrib = pnl.by_ticker_factor.get(ticker, 0.0)
        periphery_contrib = pnl.by_ticker_periphery.get(ticker, 0.0)
        periphery_shock = periphery_contrib / weight if weight > 0 else 0.0
        rows.append(
            {
                "ticker": ticker,
                "weight (%)": weight * 100,
                "factor contrib (%)": factor_contrib * 100,
                "periphery shock (%)": periphery_shock * 100,
                "total contrib (%)": total * 100,
            }
        )

    df = pd.DataFrame(rows).sort_values("total contrib (%)").reset_index(drop=True)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "ticker": st.column_config.TextColumn("Ticker"),
            "weight (%)": st.column_config.NumberColumn("Weight (%)", format="%.2f"),
            "factor contrib (%)": st.column_config.NumberColumn(
                "Factor contrib (%)", format="%.3f"
            ),
            "periphery shock (%)": st.column_config.NumberColumn(
                "Periphery shock (%)", format="%.2f"
            ),
            "total contrib (%)": st.column_config.NumberColumn("Total contrib (%)", format="%.3f"),
        },
    )


def _render_narrative_and_citations(result: ScenarioResult) -> None:
    st.subheader("Scenario narrative")
    st.markdown(result.narrative)

    if result.citations:
        with st.expander(f"Sources ({len(result.citations)})"):
            for cite in result.citations:
                title = cite.title or cite.url
                line = f"- [{title}]({cite.url})"
                if cite.snippet:
                    line += f" — {cite.snippet}"
                st.markdown(line)
    else:
        st.caption("No citations returned for this scenario.")


def _render_narrative_shapley(result: ScenarioResult) -> None:
    nsr = result.narrative_shapley
    if nsr is None:
        return
    with st.expander(
        f"Experimental: narrative decomposition ({len(nsr.sub_narratives)} sub-narratives)",
        expanded=False,
    ):
        st.caption(
            "Each sub-narrative's Shapley value is computed by running the FULL pipeline "
            "on all 2^N subset combinations. Values reflect counterfactual *pipeline* "
            "behavior, not a causal decomposition of the original scenario."
        )
        df = pd.DataFrame(
            [
                {
                    "#": c.narrative_index + 1,
                    "sub-narrative": c.narrative_text,
                    "Shapley P&L contrib (%)": c.shapley_value * 100,
                    "relative (%)": c.relative_contribution * 100,
                }
                for c in nsr.contributions
            ]
        )
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "#": st.column_config.NumberColumn("#", width="small"),
                "sub-narrative": st.column_config.TextColumn("Sub-narrative", width="large"),
                "Shapley P&L contrib (%)": st.column_config.NumberColumn(
                    "Shapley P&L contrib (%)", format="%.3f"
                ),
                "relative (%)": st.column_config.NumberColumn("Relative (%)", format="%.1f"),
            },
        )
        total = sum(c.shapley_value for c in nsr.contributions)
        st.caption(
            f"Sum of Shapley contributions: {total:+.2%} "
            f"(should ≈ total P&L {nsr.total_pnl:+.2%}; "
            "small drift is float-point noise + LLM variance)."
        )


def _render_analog_windows(result: ScenarioResult) -> None:
    st.subheader("Historical analogs used")
    registry = load_events()
    rows = []
    for analog in result.analogs_selected:
        event = registry.get(analog.event_id)
        if event is None:
            rows.append(
                {
                    "event_id": analog.event_id,
                    "name": "(unknown in registry)",
                    "dates": "—",
                    "why relevant": analog.why_relevant,
                }
            )
            continue
        rows.append(
            {
                "event_id": analog.event_id,
                "name": event.name,
                "dates": f"{event.start_date} → {event.end_date}",
                "why relevant": analog.why_relevant,
            }
        )

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
    )
