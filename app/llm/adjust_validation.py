"""Validation for shock-adjustment overrides.

Encodes the hard rules for the iterative shock-adjustment path. Unlike the
initial `validate_shock_proposal` (which exposes envelope violations as advisory
errors that the retry loop tries to fix), this validator is unambiguous: an
override is either in-envelope or exactly 0.0 (explicit removal), with no
prompt-text loophole.

Used by `adjust_scenario_shocks` for both manual (slider) and prompt-derived
overrides; the LLM patch path is bound by these same rules belt-and-braces in
case the model returns a `scope="local"` patch that includes an out-of-scope
factor.
"""

from __future__ import annotations

import math

from app.llm.schemas import ScenarioResult


def validate_factor_overrides(
    canonical: ScenarioResult,
    overrides: dict[str, float],
) -> list[str]:
    """Return a list of human-readable validation errors. Empty list = OK.

    Rules:
      1. `overrides` MUST have exactly the same factor-name set as
         `canonical.factor_shocks`. Missing or extra keys are errors.
      2. `new_shock == 0.0` is ALWAYS accepted (explicit removal sentinel),
         even if 0.0 falls outside the envelope.
      3. Otherwise, `new_shock` MUST be in
         [canonical.factor_envelope[factor].p10,
          canonical.factor_envelope[factor].p90].
      4. NaN / Inf values are rejected.
    """
    errors: list[str] = []

    canonical_factors = {fs.factor for fs in canonical.factor_shocks}
    override_factors = set(overrides.keys())

    missing = canonical_factors - override_factors
    if missing:
        errors.append(
            f"Override is missing factors that exist in the canonical scenario: "
            f"{sorted(missing)}. Provide every factor (use 0.0 to remove)."
        )

    extra = override_factors - canonical_factors
    if extra:
        errors.append(
            f"Override includes factors not in the canonical scenario: "
            f"{sorted(extra)}. Adding new factors requires a full rerun."
        )

    for factor, value in overrides.items():
        if factor not in canonical_factors:
            continue
        if not math.isfinite(value):
            errors.append(f"Override for '{factor}' is not finite: {value!r}.")
            continue
        if value == 0.0:
            continue
        env = canonical.factor_envelope.get(factor)
        if env is None:
            errors.append(
                f"Override for '{factor}' = {value:.4f}, but no envelope is available "
                f"for that factor; only 0.0 (removal) is allowed."
            )
            continue
        p10 = env.get("p10")
        p90 = env.get("p90")
        if p10 is None or p90 is None:
            errors.append(
                f"Override for '{factor}' = {value:.4f}, but envelope p10/p90 is "
                f"missing; only 0.0 (removal) is allowed."
            )
            continue
        if not (p10 <= value <= p90):
            errors.append(
                f"Factor '{factor}' override {value:.4f} is outside the envelope "
                f"[p10={p10:.4f}, p90={p90:.4f}]. Move inside the band or set to 0.0 "
                f"to remove."
            )

    return errors
