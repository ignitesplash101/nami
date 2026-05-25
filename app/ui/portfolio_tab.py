from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from app.data.sample_portfolios import SAMPLE_PORTFOLIOS, Portfolio, get_portfolio
from app.ui import auth

_CHOICES = list(SAMPLE_PORTFOLIOS.keys()) + ["custom"]


def render() -> None:
    st.header("Portfolio")
    mode = auth.get_access_mode()

    if not auth.can_use_custom_portfolio(mode):
        _render_visitor_portfolio()
        return

    st.write("Pick a sample, upload a CSV (`ticker,weight`), or edit holdings inline.")

    choice = st.selectbox(
        "Start from",
        _CHOICES,
        format_func=lambda k: "Custom (blank)" if k == "custom" else SAMPLE_PORTFOLIOS[k].name,
        key="portfolio_choice",
    )

    uploaded = st.file_uploader(
        "Or upload CSV (ticker,weight)",
        type=["csv"],
        key="portfolio_upload",
    )
    upload_result = _parse_csv(uploaded) if uploaded is not None else None
    upload_holdings, upload_errors = upload_result if upload_result else (None, [])
    for err in upload_errors:
        st.error(err)

    if upload_holdings:
        seed_holdings = upload_holdings
        source_id = f"upload-{abs(hash(tuple(sorted(seed_holdings.items()))))}"
    elif choice == "custom":
        seed_holdings = {"AAPL": 0.5, "MSFT": 0.5}
        source_id = "sample-custom"
    else:
        seed_holdings = get_portfolio(choice).holdings
        source_id = f"sample-{choice}"

    seed_df = pd.DataFrame([{"ticker": t, "weight": w} for t, w in seed_holdings.items()])

    edited = st.data_editor(
        seed_df,
        num_rows="dynamic",
        column_config={
            "ticker": st.column_config.TextColumn("Ticker", required=True),
            "weight": st.column_config.NumberColumn(
                "Weight (decimal)",
                min_value=0.0,
                max_value=1.0,
                format="%.4f",
            ),
        },
        use_container_width=True,
        key=f"portfolio_editor::{source_id}",
    )

    issues = _validate_editor(edited)
    total = float(edited["weight"].sum()) if len(edited) and "weight" in edited else 0.0
    n_rows = len(edited)

    col_total, col_count, col_status = st.columns(3)
    col_total.metric("Total weight", f"{total:.2%}")
    col_count.metric("Holdings", n_rows)
    col_status.metric("Status", "valid" if not issues else f"{len(issues)} issue(s)")

    for msg in issues:
        st.error(msg)

    saved_portfolio: Portfolio | None = st.session_state.get("portfolio")
    if saved_portfolio is not None:
        st.caption(
            f"Currently saved: **{saved_portfolio.name}** "
            f"({len(saved_portfolio.holdings)} holdings)"
        )

    if st.button("Save & use this portfolio", type="primary", disabled=bool(issues)):
        holdings = {
            str(row["ticker"]).strip().upper(): float(row["weight"])
            for _, row in edited.iterrows()
            if pd.notna(row.get("ticker")) and pd.notna(row.get("weight"))
        }
        if choice in SAMPLE_PORTFOLIOS and not upload_holdings and seed_holdings == holdings:
            sample = SAMPLE_PORTFOLIOS[choice]
            name, description = sample.name, sample.description
        else:
            name = "Custom"
            description = "User-edited portfolio"
        portfolio = Portfolio(name=name, description=description, holdings=holdings)
        st.session_state["portfolio"] = portfolio
        st.session_state["portfolio_key"] = choice if name != "Custom" else "custom"
        st.success(f"Saved {len(holdings)} holdings as '{name}'. Ready to run scenarios.")


def _render_visitor_portfolio() -> None:
    st.write("Choose one of the sample portfolios.")

    choice = st.selectbox(
        "Sample portfolio",
        list(SAMPLE_PORTFOLIOS.keys()),
        format_func=lambda k: SAMPLE_PORTFOLIOS[k].name,
        key="visitor_portfolio_choice",
    )
    portfolio = get_portfolio(choice)
    st.session_state["portfolio"] = portfolio
    st.session_state["portfolio_key"] = choice

    st.markdown(f"**{portfolio.name}**")
    st.caption(portfolio.description)
    st.dataframe(
        pd.DataFrame(
            [{"ticker": ticker, "weight": weight} for ticker, weight in portfolio.holdings.items()]
        ),
        hide_index=True,
        use_container_width=True,
    )
    st.info("Visitor mode uses sample portfolios only. Enter the admin passcode to edit or upload.")


def _normalize_ticker(raw: object) -> str:
    if raw is None:
        return ""
    s = str(raw).strip()
    if "." in s:
        head, _, tail = s.rpartition(".")
        return f"{head.upper()}.{tail.upper()}"
    return s.upper()


def _validate_editor(df: pd.DataFrame) -> list[str]:
    errs: list[str] = []
    if df is None or len(df) == 0:
        return ["Portfolio is empty — add at least one holding."]
    if "ticker" not in df.columns or "weight" not in df.columns:
        return ["Editor must have 'ticker' and 'weight' columns."]

    tickers = [_normalize_ticker(t) for t in df["ticker"]]
    if any(not t for t in tickers):
        errs.append("Every row needs a non-blank ticker.")
    if len(tickers) != len(set(tickers)):
        dups = sorted({t for t in tickers if tickers.count(t) > 1 and t})
        errs.append(f"Duplicate tickers not allowed: {dups}")

    weights = pd.to_numeric(df["weight"], errors="coerce")
    if weights.isna().any():
        errs.append("Every row needs a numeric weight.")
    elif (weights < 0).any():
        errs.append("Weights cannot be negative.")
    elif not weights.replace([math.inf, -math.inf], pd.NA).notna().all():
        errs.append("Weights must be finite numbers.")
    else:
        total = float(weights.sum())
        if not (0.999 <= total <= 1.001):
            errs.append(f"Weights must sum to 1.00 (currently {total:.4f}).")

    return errs


def _parse_csv(uploaded) -> tuple[dict[str, float], list[str]] | None:
    """Parse an uploaded CSV; return (holdings_dict, error_list).

    Required columns: `ticker`, `weight`.
    Tickers uppercased (suffixes after a dot preserved as uppercase too).
    Weights accept totals in [0.95, 1.05] (decimals) OR [95, 105] (percentages, divided by 100).
    """
    errs: list[str] = []
    try:
        df = pd.read_csv(uploaded)
    except Exception as exc:  # noqa: BLE001
        return {}, [f"Could not read CSV: {exc}"]

    missing = {"ticker", "weight"} - set(df.columns)
    if missing:
        return {}, [f"CSV is missing required columns: {sorted(missing)}"]

    df = df[["ticker", "weight"]].copy()
    df["ticker"] = df["ticker"].map(_normalize_ticker)
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce")

    if df["ticker"].eq("").any():
        errs.append("CSV has rows with blank tickers.")
    if df["weight"].isna().any():
        errs.append("CSV has rows with non-numeric or blank weights.")
    if (df["weight"].dropna() < 0).any():
        errs.append("CSV has rows with negative weights.")
    dups = df["ticker"][df["ticker"].duplicated() & df["ticker"].ne("")].unique().tolist()
    if dups:
        errs.append(f"CSV has duplicate tickers: {sorted(set(dups))}")

    if errs:
        return {}, errs

    total = float(df["weight"].sum())
    if 0.95 <= total <= 1.05:
        normalized = df.set_index("ticker")["weight"].to_dict()
    elif 95.0 <= total <= 105.0:
        normalized = (df.set_index("ticker")["weight"] / 100.0).to_dict()
    else:
        return {}, [
            f"CSV weights sum to {total:.4f}. Use decimals near 1.0 or percentages near 100."
        ]

    if not (0.999 <= sum(normalized.values()) <= 1.001):
        scale = 1.0 / sum(normalized.values())
        normalized = {t: w * scale for t, w in normalized.items()}

    return {str(t): float(w) for t, w in normalized.items()}, []
