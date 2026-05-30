from __future__ import annotations

import math

from app.data.sample_portfolios import CASH_TICKER


def normalize_ticker(raw: object) -> str:
    if raw is None:
        return ""
    s = str(raw).strip()
    if "." in s:
        head, _, tail = s.rpartition(".")
        return f"{head.upper()}.{tail.upper()}"
    return s.upper()


def validate_holdings(raw_holdings: dict[str, float]) -> tuple[dict[str, float], list[str]]:
    errors: list[str] = []
    normalized: dict[str, float] = {}

    if not raw_holdings:
        return {}, ["Portfolio is empty; add at least one holding."]

    for ticker, weight in raw_holdings.items():
        normalized_ticker = normalize_ticker(ticker)
        if not normalized_ticker:
            errors.append("Every row needs a non-blank ticker.")
            continue
        if normalized_ticker in normalized:
            errors.append(f"Duplicate ticker not allowed: {normalized_ticker}")
            continue
        try:
            weight_value = float(weight)
        except (TypeError, ValueError):
            errors.append(f"{normalized_ticker} weight must be numeric.")
            continue
        if not math.isfinite(weight_value):
            errors.append(f"{normalized_ticker} weight must be finite.")
        elif weight_value < 0:
            errors.append(f"{normalized_ticker} weight cannot be negative.")
        else:
            normalized[normalized_ticker] = weight_value

    if errors:
        return normalized, errors

    total = sum(normalized.values())
    if 95.0 <= total <= 105.0:
        normalized = {ticker: weight / 100.0 for ticker, weight in normalized.items()}
        total = sum(normalized.values())

    if not (0.999 <= total <= 1.001):
        errors.append(f"Weights must sum to 1.00 (currently {total:.4f}).")

    # CASH is a zero-exposure sentinel; a book of only cash has nothing to shock.
    market_weight = sum(w for t, w in normalized.items() if t != CASH_TICKER)
    if market_weight <= 0:
        errors.append("Portfolio needs at least one non-cash holding.")

    return normalized, errors


def validate_quantities(raw_quantities: dict[str, float]) -> tuple[dict[str, float], list[str]]:
    """Validate share quantities for mark-to-market.

    Like `validate_holdings` (uppercase tickers, reject blanks/dupes/non-finite)
    but with NO sum-to-1 normalization (these are raw share counts) and a
    non-negative rule (v1 does not support shorts). Requires ≥1 positive position.
    """
    errors: list[str] = []
    normalized: dict[str, float] = {}

    if not raw_quantities:
        return {}, ["No positions; add at least one holding with a share quantity."]

    for ticker, qty in raw_quantities.items():
        normalized_ticker = normalize_ticker(ticker)
        if not normalized_ticker:
            errors.append("Every row needs a non-blank ticker.")
            continue
        if normalized_ticker in normalized:
            errors.append(f"Duplicate ticker not allowed: {normalized_ticker}")
            continue
        try:
            qty_value = float(qty)
        except (TypeError, ValueError):
            errors.append(f"{normalized_ticker} quantity must be numeric.")
            continue
        if not math.isfinite(qty_value):
            errors.append(f"{normalized_ticker} quantity must be finite.")
        elif qty_value < 0:
            errors.append(
                f"{normalized_ticker} quantity cannot be negative "
                "(short positions are not supported in v1)."
            )
        else:
            normalized[normalized_ticker] = qty_value

    if not errors:
        market_qty = sum(q for t, q in normalized.items() if t != CASH_TICKER)
        if market_qty <= 0:
            errors.append("At least one non-cash position must have a positive share quantity.")

    return normalized, errors


def validate_nav(nav: object) -> tuple[float, list[str]]:
    """Validate a portfolio NAV scalar: finite and strictly positive."""
    try:
        value = float(nav)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0, ["Portfolio value (NAV) must be numeric."]
    if not math.isfinite(value):
        return value, ["Portfolio value (NAV) must be finite."]
    if value <= 0:
        return value, ["Portfolio value (NAV) must be positive."]
    return value, []
