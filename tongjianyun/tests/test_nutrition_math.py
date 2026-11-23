from decimal import Decimal as D

from tongjianyun.nutrition_math import (
    ingredient_amounts, number, stock_mass_in_grams, summarize, unit_factor,
)


def test_measured_edible_weight_applies_the_fixed_per_100_gram_basis():
    amounts, grams, basis = ingredient_amounts(D("100"), D("80"), D("1"),
                                               {"protein": D("20"), "sodium": D("0")})
    assert grams == D("80")
    assert amounts == {"protein": D("16"), "sodium": D("0")}
    assert basis == "配方可食净量"


def test_gross_weight_without_edible_weight_is_incomplete():
    assert ingredient_amounts(D("100"), None, D("1"), {"protein": D("20")}) == (
        {}, None, "缺少可食净量",
    )
    assert ingredient_amounts(D("100"), D("80"), None, {"protein": D("20")}) == (
        {}, None, "缺少重量换算",
    )


def test_stock_weight_uses_native_mass_conversions():
    assert unit_factor("盒", D("1"), None) is None
    assert unit_factor("盒", D("1"), D("175")) == D("175")
    assert unit_factor("kg", None, None) == D("1000")
    assert stock_mass_in_grams("只", {"g": "0.02", "kg": "20"}) == D("50")
    assert stock_mass_in_grams("只", {"g": "0.02", "kg": "10"}) is None
    assert stock_mass_in_grams("毫升", {}) is None


def test_aggregation_distinguishes_missing_nutrients_from_confirmed_zero():
    totals = summarize([{"amounts": {"protein": "0", "fat": "2"}}, {"amounts": {"protein": "2.1"}},
                        {"amounts": {}, "issue": "缺少已审核的营养档案"}])
    assert totals["protein"] == {"value": D("2.1"), "covered": 2, "total": 3}
    assert totals["fat"] == {"value": D("2"), "covered": 1, "total": 3}
    assert totals["sodium"] == {"value": None, "covered": 0, "total": 3}
    assert number("NaN") is None and number("0") == D("0")
