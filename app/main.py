from __future__ import annotations

import streamlit as st

from app.ui import auth, methodology_tab, portfolio_tab, results_tab, scenario_tab
from app.utils.disclaimers import DISCLAIMER_SHORT, FOOTER


def main() -> None:
    st.set_page_config(
        page_title="nami — scenario explorer",
        page_icon="🌊",
        layout="wide",
    )
    st.title("nami — 波")
    st.caption("LLM-driven scenario explorer for equity portfolios")
    st.warning(DISCLAIMER_SHORT, icon="⚠️")
    auth.render_access_control()

    portfolio, scenario, results, methodology = st.tabs(
        ["Portfolio", "Scenario", "Results", "Methodology"]
    )

    with portfolio:
        portfolio_tab.render()
    with scenario:
        scenario_tab.render()
    with results:
        results_tab.render()
    with methodology:
        methodology_tab.render()

    st.divider()
    st.caption(FOOTER)


if __name__ == "__main__":
    main()
