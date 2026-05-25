from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.factors.analogs import load_events
from app.llm.schemas import PortfolioPnL, ScenarioResult


def render() -> None:
    st.header("Results")

    result: ScenarioResult | None = st.session_state.get("scenario_result")
    if result is None:
        st.info("Run a scenario from the Scenario tab to see results here.", icon="ℹ️")
        return

    pnl = result.portfolio_pnl

    _render_top_metrics(result, pnl)
    st.divider()
    _render_factor_waterfall(pnl)
    st.divider()
    _render_factor_reasoning(result, pnl)
    st.divider()
    _render_periphery_reasoning(result, pnl)
    st.divider()
    _render_name_breakdown(result, pnl)
    st.divider()
    _render_narrative_and_citations(result)
    st.divider()
    _render_analog_windows(result)


def _render_top_metrics(result: ScenarioResult, pnl: PortfolioPnL) -> None:
    if pnl.by_factor:
        top_factor, top_contrib = max(pnl.by_factor.items(), key=lambda kv: abs(kv[1]))
        top_shock = next(
            (fs.shock for fs in result.factor_shocks if fs.factor == top_factor), 0.0
        )
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


def _render_factor_waterfall(pnl: PortfolioPnL) -> None:
    st.subheader("Factor contributions")
    periphery_total = sum(pnl.by_ticker_periphery.values())

    bars = list(pnl.by_factor.items())
    bars.sort(key=lambda kv: abs(kv[1]), reverse=True)
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


def _render_factor_reasoning(result: ScenarioResult, pnl: PortfolioPnL) -> None:
    st.subheader("Factor reasoning")
    st.caption(
        "**Shock applied** = the magnitude the LLM proposed for the factor. "
        "**Contrib to P&L** = how that shock weighted through the portfolio."
    )
    rows = [
        {
            "factor": fs.factor,
            "shock applied (%)": fs.shock * 100,
            "contrib to P&L (%)": pnl.by_factor.get(fs.factor, 0.0) * 100,
            "LLM reasoning": fs.reasoning,
        }
        for fs in result.factor_shocks
    ]
    if not rows:
        st.caption("No factor shocks returned.")
        return
    df = pd.DataFrame(rows).sort_values("contrib to P&L (%)").reset_index(drop=True)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "factor": st.column_config.TextColumn("Factor", width="small"),
            "shock applied (%)": st.column_config.NumberColumn(
                "Shock applied (%)", format="%.2f"
            ),
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
            "shock applied (%)": st.column_config.NumberColumn(
                "Shock applied (%)", format="%.2f"
            ),
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
            "total contrib (%)": st.column_config.NumberColumn(
                "Total contrib (%)", format="%.3f"
            ),
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
