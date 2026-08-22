from __future__ import annotations

from tongjianyun import nutrition_standard_service
from tongjianyun.nutrition_rules import default_rule_set, normalize_rule_set


def test_standard_profile_uses_active_versioned_reference_values() -> None:
    rule_set = normalize_rule_set(default_rule_set())
    standard, profile = nutrition_standard_service.standard_profile(
        "4–5岁平均", "男女平均", rule_set
    )

    assert profile == "4–5岁平均·男女平均"
    assert standard["energy"] == 1312.5
    assert standard["protein"] == 30


def test_explanation_returns_components_formula_source_and_rule(monkeypatch) -> None:
    rule_set = normalize_rule_set(default_rule_set())
    monkeypatch.setattr(
        nutrition_standard_service, "_get_active_rule_set", lambda: rule_set
    )

    result = nutrition_standard_service.explain_nutrition_standard(
        "energy", "4–5岁平均", "男女平均", 80
    )

    assert [item["value"] for item in result["components"]] == [
        1300,
        1250,
        1400,
        1300,
    ]
    assert result["calculation"]["full_day_expression"] == (
        "(1300 + 1250 + 1400 + 1300) ÷ 4"
    )
    assert result["calculation"]["full_day_standard"] == 1312.5
    assert result["calculation"]["garden_standard"] == 1050
    assert result["active_rule"]["rule_hash"] == rule_set["rule_hash"]
    assert "DB4403/T 489" in result["source"]["title"]
