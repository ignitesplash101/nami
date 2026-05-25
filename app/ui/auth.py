from __future__ import annotations

import hmac
import os
from typing import Literal

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

AccessMode = Literal["visitor", "admin"]


def configured_passcode() -> str | None:
    raw = os.getenv("PASSCODE")
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


def verify_passcode(candidate: str, expected: str | None = None) -> bool:
    expected_passcode = configured_passcode() if expected is None else expected.strip()
    candidate_passcode = candidate.strip()
    if not expected_passcode or not candidate_passcode:
        return False
    return hmac.compare_digest(candidate_passcode, expected_passcode)


def get_access_mode() -> AccessMode:
    return "admin" if st.session_state.get("access_mode") == "admin" else "visitor"


def is_admin(mode: AccessMode | None = None) -> bool:
    return (mode or get_access_mode()) == "admin"


def can_use_custom_portfolio(mode: AccessMode) -> bool:
    return mode == "admin"


def can_use_free_text_scenario(mode: AccessMode) -> bool:
    return mode == "admin"


def can_use_narrative_decomposition(mode: AccessMode) -> bool:
    return mode == "admin"


def render_access_control() -> AccessMode:
    passcode = configured_passcode()

    with st.sidebar:
        st.subheader("Access")
        if get_access_mode() == "admin":
            st.success("Admin mode")
            if st.button("Return to visitor mode", key="lock_admin_mode"):
                st.session_state["access_mode"] = "visitor"
                st.rerun()
            return "admin"

        st.info("Visitor mode")
        if not passcode:
            st.warning("Admin passcode is not configured; admin mode is unavailable.")
            return "visitor"

        with st.expander("Admin unlock"):
            candidate = st.text_input("Passcode", type="password", key="admin_passcode_input")
            if st.button("Unlock", key="unlock_admin_mode"):
                if verify_passcode(candidate, passcode):
                    st.session_state["access_mode"] = "admin"
                    st.rerun()
                else:
                    st.error("Incorrect passcode.")

    return "visitor"
