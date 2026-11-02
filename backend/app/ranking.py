"""Explicit shopping-suggestion ranking.

match(product) = sum over confirmed mapped concerns of normalised_priority(c) * severity(c)

severity = 100 - raw_score when the frozen direction is higher_is_healthier.
The 100 anchor is the documented top of the score range, not a population norm.

Tie-break, in order: higher match, lower price when both prices share a currency,
then ascending product id. Displayed ranks are therefore unique. Products with
the same match are still flagged as tied on the match score.

Unknown concern mappings are omitted. If the user excludes an ingredient and the
label text is absent, the product is ineligible rather than assumed safe.
Outputs are shopping suggestions, not safety or efficacy advice.
"""

from __future__ import annotations

from app.config import FORMULA_ID


def formula_document(direction: str, top_k: int) -> dict:
    return {
        "formula_id": FORMULA_ID,
        "top_k": top_k,
        "score_direction": direction,
        "expression": "match = sum(normalised_priority(c) * severity(c)) over reviewer-confirmed mappings",
        "severity": "100 - raw_score" if direction == "higher_is_healthier" else "raw_score",
        "tie_break": ["match descending", "price ascending when currency matches", "product id ascending"],
        "limitations": [
            "This is a shopping suggestion from a frozen rule, not personalised safety or efficacy advice.",
            "A stable ranking can mean the rule is insensitive. Read the margin next to the score deltas.",
            "Absent ingredient labels are not treated as ingredient-free.",
            "Unconfirmed mappings are ignored and are not guessed.",
        ],
    }


def severity(raw_score: float | None, direction: str) -> float | None:
    if raw_score is None:
        return None
    if direction == "higher_is_healthier":
        return 100.0 - float(raw_score)
    if direction == "higher_is_more_concern":
        return float(raw_score)
    raise ValueError(f"unsupported score direction {direction}")


def _price(product: dict) -> tuple[int, float]:
    currency = (product.get("currency") or "").upper()
    raw = product.get("price")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return (1, 0.0)
    if not currency:
        return (1, 0.0)
    return (0, value)


def rank_products(
    products: list[dict],
    raw_scores: dict[str, float | None],
    priorities: dict[str, float],
    direction: str,
    excluded_product_ids: list[str],
    excluded_ingredients: list[str],
    top_k: int,
) -> dict:
    selected = [concern for concern, weight in priorities.items() if weight > 0 and concern in raw_scores]
    weight_sum = sum(priorities[concern] for concern in selected) or 1.0
    severities = {concern: severity(raw_scores.get(concern), direction) for concern in selected}
    if any(value is None for value in severities.values()):
        return {
            "eligible": False,
            "reason": "one or more selected concerns has no raw score on this image",
            "ordered": [],
            "margin": None,
            "ties": [],
        }
    excluded_ids = set(excluded_product_ids)
    needles = [item.strip().lower() for item in excluded_ingredients if item.strip()]
    ranked = []
    ineligible = []
    for product in products:
        if product["id"] in excluded_ids:
            ineligible.append({"id": product["id"], "reason": "excluded by the user"})
            continue
        label = product.get("ingredient_label")
        if needles and not label:
            ineligible.append({"id": product["id"], "reason": "ingredient list is absent, so exclusions cannot be checked"})
            continue
        if needles and label and any(needle in label.lower() for needle in needles):
            ineligible.append({"id": product["id"], "reason": "ingredient label contains an excluded term"})
            continue
        mappings = [item for item in product.get("mappings", []) if item.get("reviewer_confirmed")]
        used = []
        total = 0.0
        for item in mappings:
            concern = item["concern"]
            if concern not in severities:
                continue
            share = priorities.get(concern, 0.0) / weight_sum
            contribution = share * float(severities[concern])
            total += contribution
            used.append({"concern": concern, "priority_share": share, "severity": severities[concern], "contribution": contribution, "support_note": item.get("support_note", "")})
        if not used:
            ineligible.append({"id": product["id"], "reason": "no reviewer-confirmed mapping for the selected concerns"})
            continue
        ranked.append({**product, "match": total, "contributions": used})
    ranked.sort(key=lambda item: (-item["match"], _price(item), item["id"]))
    ordered = []
    ties = []
    for index, item in enumerate(ranked, start=1):
        score_tie = [other["id"] for other in ranked if other["id"] != item["id"] and abs(other["match"] - item["match"]) < 1e-9]
        if score_tie:
            ties.append({"product_id": item["id"], "tied_with": score_tie, "match": item["match"]})
        ordered.append(
            {
                "rank": index,
                "product_id": item["id"],
                "name": item["name"],
                "source_url": item["source_url"],
                "price": item.get("price"),
                "currency": item.get("currency"),
                "match": item["match"],
                "score_tie": bool(score_tie),
                "contributions": item["contributions"],
            }
        )
    margin = None
    if len(ordered) >= 2:
        margin = ordered[0]["match"] - ordered[1]["match"]
    return {
        "eligible": bool(ordered),
        "reason": None if ordered else "no eligible products",
        "ordered": ordered,
        "top_k": [item["product_id"] for item in ordered[:top_k]],
        "margin": margin,
        "ties": ties,
        "ineligible": ineligible,
        "severities": severities,
    }


def compare_rankings(baseline: dict, variant: dict, top_k: int) -> dict:
    if not baseline.get("eligible") or not variant.get("eligible"):
        return {
            "comparable": False,
            "top_one_changed": False,
            "reason": "ranking is not eligible on the baseline or this variant",
        }
    base_top = baseline["ordered"][0]["product_id"]
    var_top = variant["ordered"][0]["product_id"]
    base_set = set(baseline.get("top_k") or [])
    var_set = set(variant.get("top_k") or [])
    intersection = base_set & var_set
    union = base_set | var_set
    base_ranks = {item["product_id"]: item["rank"] for item in baseline["ordered"]}
    var_ranks = {item["product_id"]: item["rank"] for item in variant["ordered"]}
    displacements = []
    for product_id in sorted(set(base_ranks) | set(var_ranks)):
        displacements.append(
            {
                "product_id": product_id,
                "baseline_rank": base_ranks.get(product_id),
                "variant_rank": var_ranks.get(product_id),
                "displacement": (
                    None
                    if product_id not in base_ranks or product_id not in var_ranks
                    else var_ranks[product_id] - base_ranks[product_id]
                ),
            }
        )
    return {
        "comparable": True,
        "top_one_changed": base_top != var_top,
        "baseline_top": base_top,
        "variant_top": var_top,
        "top_k_intersection": sorted(intersection),
        "top_k_overlap_count": len(intersection),
        "top_k_jaccard": (len(intersection) / len(union)) if union else None,
        "top_k": top_k,
        "displacements": displacements,
        "baseline_margin": baseline.get("margin"),
        "variant_margin": variant.get("margin"),
    }
