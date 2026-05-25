from __future__ import annotations

import streamlit as st

from app.utils.disclaimers import DISCLAIMER_LONG


def render() -> None:
    st.header("Methodology")
    st.markdown(DISCLAIMER_LONG)
    st.info("Full methodology docs coming in Phase 5.", icon="📘")
