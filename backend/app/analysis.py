"""Observed sensitivity from persisted raw scores.

delta(c, k) = raw(c, k) - raw(c, baseline).
Ranges describe the tested variants only. They are not confidence intervals,
minimal detectable change, or population uncertainty.
"""

from __future__ import annotations

from app.config import SCORE_DIRECTION_SOURCE


def paired_delta(variant_raw: float | None, baseline_raw: float | None) -> tuple[float | None, str | None]:
    if baseline_raw is None:
        return None, "baseline raw_score is unavailable"
    if variant_raw is None:
        return None, "variant raw_score is unavailable; ui_score was not substituted"
    return variant_raw - baseline_raw, None


def summarise_deltas(points: list[float]) -> dict:
    if not points:
        return {"min_delta": None, "max_delta": None, "max_abs_delta": None, "observed_range": None, "n": 0}
    low = min(points)
    high = max(points)
    return {
        "min_delta": low,
        "max_delta": high,
        "max_abs_delta": max(abs(value) for value in points),
        "observed_range": high - low,
        "n": len(points),
    }


def finite_difference(high_raw: float | None, low_raw: float | None, step: float) -> tuple[float | None, str | None]:
    if step == 0:
        return None, "parameter step is zero"
    if high_raw is None or low_raw is None:
        return None, "both endpoints must have raw scores"
    return (high_raw - low_raw) / step, None


def exposure_derivative(raw_high: float | None, raw_low: float | None, high: float, low: float) -> dict:
    value, reason = finite_difference(raw_high, raw_low, high - low)
    return {
        "kind": "exposure",
        "value": value,
        "unit": "raw score points per exposure-multiplier unit",
        "low_multiplier": low,
        "high_multiplier": high,
        "unavailable_reason": reason,
        "label": "local empirical sensitivity",
    }


def colour_derivative(
    raw_warm: float | None,
    raw_cool: float | None,
    warm_red: float,
    cool_red: float,
    warm_blue: float,
    cool_blue: float,
) -> dict:
    value, reason = finite_difference(raw_warm, raw_cool, warm_red - cool_red)
    return {
        "kind": "colour_balance",
        "value": value,
        "unit": "raw score points per red-channel-gain unit",
        "warm_red_gain": warm_red,
        "cool_red_gain": cool_red,
        "warm_blue_gain": warm_blue,
        "cool_blue_gain": cool_blue,
        "unavailable_reason": reason,
        "label": "local empirical sensitivity",
        "note": "Blue gain moves in the opposite direction. Green is unchanged. This is not a biological response.",
    }


def decision_label(
    *,
    baseline_ok: bool,
    eligible_products: int,
    valid_variants: int,
    minimum_valid: int,
    top_one_changes: int,
    score_only: bool,
) -> dict:
    failures_note = "Invalid and provider-failed variants are excluded from n."
    if not baseline_ok:
        return {
            "label": "insufficient_evidence",
            "statement": "Insufficient evidence: the unmodified baseline has no accepted raw scores.",
            "note": failures_note,
        }
    if score_only or eligible_products == 0:
        return {
            "label": "insufficient_evidence",
            "statement": "Insufficient evidence for a product decision: no eligible confirmed products were in the frozen shortlist.",
            "note": "Score deltas are still reported separately. They are not a shopping recommendation.",
        }
    if valid_variants < minimum_valid:
        partial = ""
        if top_one_changes:
            partial = " A top-one change appeared in the partial set, and it is not treated as a concluded result."
        return {
            "label": "insufficient_evidence",
            "statement": (
                f"Insufficient evidence: {valid_variants} valid tested variants is below the configured minimum of {minimum_valid}."
                + partial
            ),
            "note": "The minimum is an engineering coverage setting, not a clinical cut-off. " + failures_note,
        }
    if top_one_changes:
        return {
            "label": "recommendation_changed",
            "statement": f"Recommendation changed in {top_one_changes} of {valid_variants} valid tested variants.",
            "note": "This count is not a real-world flip probability. " + failures_note,
        }
    return {
        "label": "stable_under_tested_transformations",
        "statement": f"Unchanged in {valid_variants} tested variants.",
        "note": "Stable under the tested transformations only. " + failures_note,
    }


def direction_block(direction: str) -> dict:
    return {
        "value": direction,
        "meaning": (
            "Higher raw_score means a healthier-looking result in the provider documentation."
            if direction == "higher_is_healthier"
            else "Higher raw_score is configured as more of the named concern. Confirm this against current documentation before relying on it."
        ),
        "source": SCORE_DIRECTION_SOURCE,
        "limitations": [
            "API appearance scores are model outputs, not physiological measurements.",
            "A higher redness raw score is not a measurement of greater physical redness.",
            "UI scores are a separate, provider-adjusted presentation and are never copied into raw deltas.",
            "No clinical threshold, confidence interval, or product-efficacy claim is computed.",
        ],
    }
