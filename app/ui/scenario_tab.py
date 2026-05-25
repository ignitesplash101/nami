from __future__ import annotations

import streamlit as st

SAMPLES: dict[str, str] = {
    "(choose…)": "",
    "COVID-like pandemic shock": (
        "Sudden global pandemic resurgence; 30-day lockdown across major economies; "
        "risk-off liquidation across all asset classes."
    ),
    "China tariff escalation": (
        "US announces 60% tariffs on China imports; prolonged trade war; "
        "tech supply-chain disruption; semiconductor names hit hardest."
    ),
    "Yen carry trade unwind": (
        "BoJ surprise rate hike triggers global yen-funded carry-trade unwind; "
        "sharp JPY appreciation; equities sell off; Japanese exporters down."
    ),
    "Banking sector stress": (
        "Several mid-sized US banks fail in quick succession; deposit flight; "
        "Fed intervenes with emergency liquidity; financials sector under heavy pressure."
    ),
}


def render() -> None:
    st.header("Scenario")
    st.write("Describe a forward-looking market scenario in natural language.")

    sample = st.selectbox("Sample scenarios", list(SAMPLES.keys()))
    scenario_text = st.text_area(
        "Describe the scenario",
        value=SAMPLES[sample],
        height=140,
        placeholder="e.g. 'BoJ raises rates 50bps; yen surges to 130; global risk-off.'",
    )

    portfolio_key = st.session_state.get("portfolio_key")
    if portfolio_key is None:
        st.warning("Pick a portfolio on the Portfolio tab first.", icon="⚠️")

    can_run = bool(scenario_text and portfolio_key)
    run = st.button("Run Scenario", type="primary", disabled=not can_run)

    if run:
        with st.spinner("Running scenario (~15s — Gemini + grounding + factor model)…"):
            try:
                from app.llm.scenario import run_scenario

                result = run_scenario(scenario_text, portfolio_key)
                st.session_state["scenario_result"] = result
                st.success(
                    f"✓ Scenario complete. Portfolio P&L: {result.portfolio_pnl.total_pnl:.2%}. "
                    "Click the Results tab to see the full breakdown."
                )
            except Exception as exc:  # noqa: BLE001 — surface ALL errors to the user
                st.error(f"Scenario failed: {exc}")
