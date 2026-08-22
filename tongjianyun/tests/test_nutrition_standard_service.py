from __future__ import annotations

from tongjianyun import nutrition_standard_service


def _sheet(standard: dict, filters: dict) -> dict:
    return {
        "recipe": {"name": "RECIPE-1", "title": "测试食谱"},
        "filters": filters,
        "analysis": {
            "standard": standard,
            "calculation_rule": {
                "rule_code": "DEFAULT-V1",
                "title": "默认营养计算规则 V1",
                "version": "1.0",
                "rule_hash": "hash-1",
            },
        },
    }


def test_explains_manual_full_day_energy_formula(monkeypatch) -> None:
    monkeypatch.setattr(
        nutrition_standard_service,
        "_get_nutrition_sheet",
        lambda *args: _sheet(
            {
                "energy": 1312.5,
                "profile": "手动估算·4–5岁平均·男女平均",
                "source": nutrition_standard_service.OFFICIAL_SOURCE,
            },
            {"standard_mode": "手动估算", "garden_ratio": 80},
        ),
    )

    result = nutrition_standard_service.explain_nutrition_standard(
        "energy", standard_mode="手动估算", age_group="4–5岁平均"
    )

    assert result["calculation"]["full_day_expression"] == (
        "(1300 × 1 + 1250 × 1 + 1400 × 1 + 1300 × 1) ÷ 4"
    )
    assert result["calculation"]["full_day_standard"] == 1312.5
    assert result["calculation"]["garden_standard"] == 1050


def test_explains_roster_weighted_energy_formula(monkeypatch) -> None:
    population = {
        "student_count": 3,
        "reference_date": "2026-06-22",
        "composition": [
            {"label": "4岁男", "count": 2},
            {"label": "5岁女", "count": 1},
        ],
    }
    monkeypatch.setattr(
        nutrition_standard_service,
        "_get_nutrition_sheet",
        lambda *args: _sheet(
            {
                "energy": 1300,
                "profile": "自动计算·全园启用学生·3名学生",
                "source": nutrition_standard_service.OFFICIAL_SOURCE,
                "population": population,
            },
            {"standard_mode": "自动（按学生档案）", "garden_ratio": 80},
        ),
    )

    result = nutrition_standard_service.explain_nutrition_standard("energy")

    assert result["calculation"]["full_day_expression"] == (
        "(1300 × 2 + 1300 × 1) ÷ 3"
    )
    assert result["population"] == population
    assert result["source"]["url"].endswith("11504294.pdf")


def test_explanation_discloses_manual_fallback_when_roster_is_empty(monkeypatch) -> None:
    calls = []

    def get_sheet(*args):
        calls.append(args)
        if args[1] == nutrition_standard_service.AUTO_MODE:
            raise RuntimeError("当前没有启用学生，无法计算营养标准。")
        return _sheet(
            {
                "energy": 1312.5,
                "profile": "手动估算·4–5岁平均·男女平均",
                "source": nutrition_standard_service.OFFICIAL_SOURCE,
            },
            {"standard_mode": "手动估算", "garden_ratio": 80},
        )

    monkeypatch.setattr(nutrition_standard_service, "_get_nutrition_sheet", get_sheet)

    result = nutrition_standard_service.explain_nutrition_standard(
        "energy", standard_mode=nutrition_standard_service.AUTO_MODE, age_group="4–5岁平均"
    )

    assert result["requested_standard_mode"] == nutrition_standard_service.AUTO_MODE
    assert result["standard_mode"] == "手动估算"
    assert result["fallback"]["used"] is True
    assert "当前没有启用学生" in result["fallback"]["reason"]
    assert "以下为手动估算" in result["answer_summary"]
    assert calls[1][1] == "手动估算"
