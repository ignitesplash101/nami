from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.data.sample_portfolios import get_portfolio
from app.factors.analogs import load_events
from app.llm.schemas import ScenarioResult


def render() -> None:
    st.header("Results")

    result: ScenarioResult | None = st.session_state.get("scenario_result")
    if result is None:
        st.info(
            "Run a scenario from the Scenario tab to see results here.",
            icon="ℹ️",
        )
        return

    pnl = result.portfolio_pnl

    _render_top_metrics(result, pnl)
    st.divider()
    _render_factor_waterfall(pnl)
    st.divider()
    _render_name_breakdown(result, pnl)
    st.divider()
    _render_narrative_and_citations(result)
    st.divider()
    _render_analog_windows(result)


def _render_top_metrics(result: ScenarioResult, pnl) -> None:
    top_factor_name, top_factor_value = max(
        pnl.by_factor.items(), key=lambda kv: abs(kv[1]), default=("—", 0.0)
    )
    col_pnl, col_top, col_analogs = st.columns(3)
    col_pnl.metric("Portfolio P&L", f"{pnl.total_pnl:.2%}")
    col_top.metric(
        f"Top driver: {top_factor_name}",
        f"{top_factor_value:.2%}",
    )
    col_analogs.metric("Analogs used", len(result.analogs_selected))


def _render_factor_waterfall(pnl) -> None:
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


def _render_name_breakdown(result: ScenarioResult, pnl) -> None:
    st.subheader("Name-level breakdown")
    portfolio = get_portfolio(result.portfolio_key)

    rows = []
    for ticker, total in pnl.by_ticker_total.items():
        weight = portfolio.holdings.get(ticker, 0.0)
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
