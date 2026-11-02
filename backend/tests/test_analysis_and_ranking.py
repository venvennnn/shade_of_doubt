import pytest

from app.analysis import decision_label, exposure_derivative, paired_delta, summarise_deltas
from app.ranking import compare_rankings, rank_products, severity


def test_missing_raw_score_is_not_filled_from_ui():
    delta, reason = paired_delta(None, 40)
    assert delta is None
    assert "ui_score" in reason
    delta, reason = paired_delta(42, None)
    assert delta is None
    assert "baseline" in reason


def test_delta_range_and_exposure_derivative_use_only_valid_endpoints():
    summary = summarise_deltas([1.0, -2.0, 0.5])
    assert summary["min_delta"] == -2.0
    assert summary["max_delta"] == 1.0
    assert summary["max_abs_delta"] == 2.0
    assert summary["n"] == 3
    derivative = exposure_derivative(51, 49, 1.1, 0.9)
    assert derivative["value"] == pytest.approx(10)
    missing = exposure_derivative(None, 49, 1.1, 0.9)
    assert missing["value"] is None


def test_direction_severity_and_ties():
    assert severity(80, "higher_is_healthier") == 20
    assert severity(80, "higher_is_more_concern") == 80
    products = [
        {
            "id": "b",
            "name": "B",
            "source_url": "https://example.com/b",
            "price": "20",
            "currency": "USD",
            "ingredient_label": "water, glycerin",
            "mappings": [{"concern": "redness", "reviewer_confirmed": True, "support_note": "label lists glycerin"}],
        },
        {
            "id": "a",
            "name": "A",
            "source_url": "https://example.com/a",
            "price": "10",
            "currency": "USD",
            "ingredient_label": "water",
            "mappings": [{"concern": "redness", "reviewer_confirmed": True, "support_note": "page describes redness"}],
        },
    ]
    ranked = rank_products(products, {"redness": 70}, {"redness": 1}, "higher_is_healthier", [], [], 1)
    assert [item["product_id"] for item in ranked["ordered"]] == ["a", "b"]
    assert ranked["ordered"][0]["score_tie"] is True
    assert ranked["margin"] == 0
    blocked = rank_products(
        [{**products[0], "ingredient_label": None}],
        {"redness": 70},
        {"redness": 1},
        "higher_is_healthier",
        [],
        ["fragrance"],
        1,
    )
    assert blocked["eligible"] is False
    assert "ingredient" in blocked["ineligible"][0]["reason"]


def test_unconfirmed_mapping_is_not_used():
    product = {
        "id": "p",
        "name": "P",
        "source_url": "https://example.com/p",
        "price": None,
        "currency": None,
        "ingredient_label": "water",
        "mappings": [{"concern": "pore", "reviewer_confirmed": False, "support_note": "guess"}],
    }
    ranked = rank_products([product], {"pore": 50}, {"pore": 1}, "higher_is_healthier", [], [], 3)
    assert ranked["eligible"] is False


def test_decision_labels_and_coverage_denominator():
    changed = decision_label(
        baseline_ok=True, eligible_products=2, valid_variants=4, minimum_valid=4, top_one_changes=1, score_only=False
    )
    assert changed["label"] == "recommendation_changed"
    assert "1 of 4" in changed["statement"]
    stable = decision_label(
        baseline_ok=True, eligible_products=2, valid_variants=6, minimum_valid=4, top_one_changes=0, score_only=False
    )
    assert stable["label"] == "stable_under_tested_transformations"
    assert "6" in stable["statement"]
    thin = decision_label(
        baseline_ok=True, eligible_products=2, valid_variants=2, minimum_valid=4, top_one_changes=1, score_only=False
    )
    assert thin["label"] == "insufficient_evidence"
    assert "partial" in thin["statement"].lower() or "below" in thin["statement"]
    empty = decision_label(
        baseline_ok=True, eligible_products=0, valid_variants=6, minimum_valid=4, top_one_changes=0, score_only=True
    )
    assert empty["label"] == "insufficient_evidence"


def test_rank_displacement_and_top_one_change():
    base = {"eligible": True, "ordered": [{"product_id": "a", "rank": 1}, {"product_id": "b", "rank": 2}], "top_k": ["a"], "margin": 1}
    variant = {"eligible": True, "ordered": [{"product_id": "b", "rank": 1}, {"product_id": "a", "rank": 2}], "top_k": ["b"], "margin": 1}
    compared = compare_rankings(base, variant, 1)
    assert compared["top_one_changed"] is True
    displacement = {item["product_id"]: item["displacement"] for item in compared["displacements"]}
    assert displacement["a"] == 1
    assert displacement["b"] == -1
