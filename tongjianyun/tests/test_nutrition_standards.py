from datetime import date

import pytest

from tongjianyun.nutrition_standards import (
    completed_years,
    normalize_gender,
    standard_profile,
    weighted_standard,
)


def test_manual_profile_keeps_the_previous_equal_weight_estimate() -> None:
    values, profile = standard_profile("4–5岁平均", "男女平均")

    assert values["energy"] == 1312.5
    assert values["calcium"] == 600
    assert profile == "手动估算·4–5岁平均·男女平均"


def test_weighted_standard_uses_each_student_age_and_gender() -> None:
    values, composition = weighted_standard(
        [
            {"age": 4, "gender": "男"},
            {"age": 4, "gender": "女"},
            {"age": 5, "gender": "男"},
        ]
    )

    assert values["energy"] == pytest.approx((1300 + 1250 + 1400) / 3)
    assert values["vitamin_a"] == pytest.approx((390 + 380 + 390) / 3)
    assert composition == {"4岁男": 1, "4岁女": 1, "5岁男": 1}


def test_age_uses_completed_years_on_the_recipe_start_date() -> None:
    birth = date(2022, 8, 22)

    assert completed_years(birth, date(2026, 8, 21)) == 3
    assert completed_years(birth, date(2026, 8, 22)) == 4


def test_normalizes_education_gender_values() -> None:
    assert normalize_gender("Male") == "男"
    assert normalize_gender("female") == "女"
    assert normalize_gender("未知") is None
