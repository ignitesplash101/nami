from __future__ import annotations

import math


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

    return normalized, errors
