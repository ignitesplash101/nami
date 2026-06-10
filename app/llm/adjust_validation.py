"""Validation for shock-adjustment overrides.

Encodes the hard rules for the iterative shock-adjustment path. Unlike the
initial `validate_shock_proposal` (whose one-retry loop lets the LLM repair a
violation before failing), this validator rejects immediately: an override is
either in-envelope, exactly 0.0 (explicit removal), or — for factors whose
analog count is below MIN_ENVELOPE_COUNT_FOR_BAND_CHECK, where the band is
interpolation-shaped and unreliable — equal to the canonical shock
(keep-or-remove). The carve-out mirrors the proposal-side count gate so the two
validators agree on when a band is evidence.

Used by `adjust_scenario_shocks` for both manual (slider) and prompt-derived
overrides; the LLM patch path is bound by these same rules belt-and-braces in
case the model returns a `scope="local"` patch that includes an out-of-scope
factor — so a direct API call cannot bypass the UI's disabled low-evidence
sliders either.
"""

from __future__ import annotations

import math

from app.llm.schemas import ScenarioResult
from app.llm.validation import MIN_ENVELOPE_COUNT_FOR_BAND_CHECK


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
      3. When the factor's envelope has count >= MIN_ENVELOPE_COUNT_FOR_BAND_CHECK,
         `new_shock` MUST be in [p10, p90].
      4. When the envelope is low-evidence (count < 3, or the envelope row /
         p10/p90 is missing), the only valid values are 0.0 or the canonical
         shock itself: keep or remove, no re-tuning without evidence.
      5. NaN / Inf values are rejected.
    """
    errors: list[str] = []

    canonical_factors = {fs.factor for fs in canonical.factor_shocks}
    canonical_shocks = {fs.factor: fs.shock for fs in canonical.factor_shocks}
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
        count = env.get("count") if env is not None else None
        p10 = env.get("p10") if env is not None else None
        p90 = env.get("p90") if env is not None else None
        band_reliable = (
            count is not None
            and count >= MIN_ENVELOPE_COUNT_FOR_BAND_CHECK
            and p10 is not None
            and p90 is not None
        )
        if band_reliable:
            if not (p10 <= value <= p90):
                errors.append(
                    f"Factor '{factor}' override {value:.4f} is outside the envelope "
                    f"[p10={p10:.4f}, p90={p90:.4f}]. Move inside the band or set to 0.0 "
                    f"to remove."
                )
            continue
        # Low-evidence carve-out: a count<3 band is interpolation between 1-2
        # points (count=0 rows are stored as 0/0/0), so re-tuning against it is
        # meaningless — keep the canonical value or remove the factor.
        if not math.isclose(value, canonical_shocks[factor], rel_tol=1e-9, abs_tol=1e-12):
            n = int(count) if count is not None else 0
            errors.append(
                f"Factor '{factor}' has only n={n} analog observation(s) — no reliable "
                f"envelope. Keep the proposed shock, set 0.0 to remove, or re-run the "
                f"scenario."
            )

    return errors
