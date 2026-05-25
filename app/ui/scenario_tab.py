from __future__ import annotations

import streamlit as st

from app.data.sample_portfolios import SAMPLE_PORTFOLIOS, get_portfolio
from app.ui import auth

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
    mode = auth.get_access_mode()
    is_admin = auth.is_admin(mode)

    if auth.can_use_free_text_scenario(mode):
        st.write("Describe a forward-looking market scenario in natural language.")
        sample = st.selectbox("Sample scenarios", list(SAMPLES.keys()), key="admin_scenario_sample")
        scenario_text = st.text_area(
            "Describe the scenario",
            value=SAMPLES[sample],
            height=140,
            placeholder="e.g. 'BoJ raises rates 50bps; yen surges to 130; global risk-off.'",
        )
    else:
        st.write("Choose one of the sample scenarios.")
        sample = st.selectbox(
            "Sample scenarios",
            list(SAMPLES.keys()),
            key="visitor_scenario_sample",
        )
        scenario_text = SAMPLES[sample]
        st.text_area(
            "Scenario preview",
            value=scenario_text,
            height=140,
            disabled=True,
            placeholder="Choose a sample scenario to preview it.",
        )
        st.info(
            "Visitor mode runs sample scenarios only. Enter the admin passcode for custom text."
        )

    portfolio = st.session_state.get("portfolio")
    portfolio_key = st.session_state.get("portfolio_key")
    if not is_admin and portfolio_key not in SAMPLE_PORTFOLIOS:
        portfolio_key = next(iter(SAMPLE_PORTFOLIOS))
        portfolio = get_portfolio(portfolio_key)
        st.session_state["portfolio"] = portfolio
        st.session_state["portfolio_key"] = portfolio_key

    if portfolio is None and portfolio_key is None:
        st.warning("Pick or build a portfolio on the Portfolio tab first.", icon="⚠️")
    elif portfolio is not None:
        st.caption(f"Using portfolio: **{portfolio.name}** ({len(portfolio.holdings)} holdings)")

    if auth.can_use_narrative_decomposition(mode):
        decompose = st.checkbox(
            "Also compute experimental narrative decomposition",
            value=False,
            help=(
                "(Experimental) Splits the scenario into 2-4 sub-narratives and runs "
                "2^N (up to 16) scenario evaluations to assign per-sub-narrative Shapley "
                "values. This is counterfactual PIPELINE attribution, not a causal "
                "decomposition. Costs ~$0.02 and ~3-4 min runtime. Don't close the tab."
            ),
        )
    else:
        decompose = False

    can_run = bool(scenario_text and (portfolio is not None or portfolio_key is not None))
    run = st.button("Run Scenario", type="primary", disabled=not can_run)

    if run:
        spinner_msg = (
            "Running scenario (~15s — Gemini + grounding + factor model)…"
            if not decompose
            else "Running base scenario before decomposition…"
        )
        with st.spinner(spinner_msg):
            try:
                from app.llm.scenario import run_scenario

                if portfolio is not None:
                    result = run_scenario(scenario_text, portfolio)
                else:
                    result = run_scenario(scenario_text, portfolio_key=portfolio_key)
            except Exception as exc:  # noqa: BLE001 — surface ALL errors to the user
                st.error(f"Scenario failed: {exc}")
                return

        if decompose:
            try:
                _run_narrative_decomposition(result)
                # _run_narrative_decomposition stores the augmented result itself
                augmented = st.session_state.get("scenario_result", result)
                st.success(
                    f"✓ Scenario + decomposition complete. "
                    f"Portfolio P&L: {augmented.portfolio_pnl.total_pnl:.2%}. "
                    "Click the Results tab to see the breakdown."
                )
            except Exception as exc:  # noqa: BLE001
                # Decomposition failed but base scenario succeeded — keep the base result
                st.session_state["scenario_result"] = result
                st.warning(f"Decomposition failed ({exc}); base scenario results still available.")
        else:
            st.session_state["scenario_result"] = result
            st.success(
                f"✓ Scenario complete. Portfolio P&L: {result.portfolio_pnl.total_pnl:.2%}. "
                "Click the Results tab to see the full breakdown."
            )


def _run_narrative_decomposition(base_result) -> None:
    """Orchestrate the 2^N subset re-runs and attach narrative_shapley to session_state."""
    from app.config import load_config
    from app.data.cache import CloudStorageCache
    from app.llm.gemini_client import GeminiClient
    from app.llm.narrative_shapley import compute_narrative_shapley

    config = load_config()
    gemini = GeminiClient(config)
    scenario_cache = CloudStorageCache(config.gcs_bucket, prefix="scenario_cache")
    decomposition_cache = CloudStorageCache(config.gcs_bucket, prefix="decomposition_cache")

    pb = st.progress(0.0, text="Decomposing scenario into sub-narratives…")

    def _on_progress(done: int, total: int) -> None:
        pb.progress(min(done / total, 1.0), text=f"Narrative decomposition: {done}/{total} subsets")

    augmented = compute_narrative_shapley(
        base_result,
        config=config,
        gemini=gemini,
        cache=scenario_cache,
        decomposition_cache=decomposition_cache,
        market_date=base_result.market_date,
        progress=_on_progress,
    )
    pb.empty()
    st.session_state["scenario_result"] = augmented
