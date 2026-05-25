from __future__ import annotations

from pathlib import Path

import streamlit as st

from app.utils.disclaimers import DISCLAIMER_LONG

_DOC_PATH = Path(__file__).resolve().parents[2] / "docs" / "methodology.md"


def render() -> None:
    st.header("Methodology")
    st.markdown(DISCLAIMER_LONG)
    st.divider()
    if _DOC_PATH.exists():
        st.markdown(_DOC_PATH.read_text(encoding="utf-8"))
    else:
        st.info("Methodology documentation not yet shipped.", icon="📘")
