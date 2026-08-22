from __future__ import annotations

from copy import deepcopy

import pytest

from tongjianyun.nutrition_rules import (
    DEFAULT_FORMULA,
    NutritionFormulaError,
    calculate_nutrient_value,
    default_rule_set,
    evaluate_formula,
    evaluate_nutrient,
    normalize_rule_set,
)
from tongjianyun.recipe_analysis import analyze_recipe_payload


FORMULA_CONTEXT = {
    "per_100g": 50,
    "grams": 200,
    "day_count": 2,
    "edible_ratio": 1,
    "retention_rate": 0.8,
}


def test_default_formula_matches_existing_calculation() -> None:
    assert evaluate_formula(DEFAULT_FORMULA, FORMULA_CONTEXT) == 40
    assert (
        calculate_nutrient_value(
            "vitamin_c",
            per_100g=50,
            grams=200,
            day_count=2,
        )
        == 50
    )


@pytest.mark.parametrize(
    "formula",
    (
        "__import__('os').system('whoami')",
        "per_100g.__class__",
        "globals()",
        "per_100g if grams else 0",
        "[per_100g][0]",
        "per_100g ** 2",
    ),
)
def test_formula_engine_rejects_non_whitelisted_code(formula: str) -> None:
    with pytest.raises(NutritionFormulaError):
        evaluate_formula(formula, FORMULA_CONTEXT)


def test_formula_engine_reports_division_by_zero() -> None:
    with pytest.raises(NutritionFormulaError, match="除零"):
        evaluate_formula("per_100g / (day_count - day_count)", FORMULA_CONTEXT)


def test_rule_thresholds_and_hash_are_deterministic() -> None:
    first = normalize_rule_set(default_rule_set())
    second = normalize_rule_set(deepcopy(first))
    assert first["rule_hash"] == second["rule_hash"]
    assert evaluate_nutrient("energy", 89.9, first) == "偏低"
    assert evaluate_nutrient("energy", 100, first) == "适宜"
    assert evaluate_nutrient("energy", 110.1, first) == "偏高"
    assert evaluate_nutrient("calcium", 121, first) == "适宜"


def test_custom_retention_rate_changes_only_selected_nutrient() -> None:
    payload = {
        "recipe": {"recipeId": "RULE-TEST"},
        "days": [
            {
                "date": "2026-08-22",
                "portions": [
                    {
                        "slot": "lunch",
                        "dishIngredientRows": [
                            {"ingredient": "西兰花", "amount": 100, "unit": "g"}
                        ],
                    }
                ],
            }
        ],
    }
    baseline = analyze_recipe_payload(payload)
    changed = default_rule_set()
    changed["rules"]["vitamin_c"]["retention_rate"] = 0.5
    candidate = analyze_recipe_payload(payload, rule_set=changed)

    assert (
        candidate["nutrients"]["vitamin_c"] == baseline["nutrients"]["vitamin_c"] * 0.5
    )
    assert candidate["nutrients"]["energy"] == baseline["nutrients"]["energy"]
    assert (
        candidate["calculation_rule"]["rule_hash"]
        != baseline["calculation_rule"]["rule_hash"]
    )
