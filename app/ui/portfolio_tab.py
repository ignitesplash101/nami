from __future__ import annotations

import pandas as pd
import streamlit as st

from app.data.sample_portfolios import get_portfolio, list_portfolios


def render() -> None:
    st.header("Portfolio")
    st.write("Load a sample portfolio or upload a CSV (`ticker, weight`).")

    choices = dict(list_portfolios())
    key = st.selectbox("Sample portfolio", list(choices), format_func=choices.get)
    st.session_state["portfolio_key"] = key

    portfolio = get_portfolio(key)
    st.caption(portfolio.description)

    weights_df = (
        pd.DataFrame([{"ticker": t, "weight (%)": w * 100} for t, w in portfolio.holdings.items()])
        .sort_values("weight (%)", ascending=False)
        .reset_index(drop=True)
    )

    col_count, col_total = st.columns(2)
    col_count.metric("Holdings", len(weights_df))
    col_total.metric("Total weight", f"{weights_df['weight (%)'].sum():.2f}%")

    st.dataframe(
        weights_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "ticker": st.column_config.TextColumn("Ticker"),
            "weight (%)": st.column_config.NumberColumn("Weight (%)", format="%.2f"),
        },
    )
