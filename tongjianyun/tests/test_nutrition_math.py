from decimal import Decimal as D

from tongjianyun.nutrition_math import (
    PER_100_G, PER_100_ML, ingredient_amounts, number, summarize, unit_factor,
)


def test_measured_edible_weight_takes_precedence_over_default_ratio():
    amounts, grams, basis = ingredient_amounts(D("100"), D("80"), D("1"), D("50"), D("100"),
                                               {"protein": D("20"), "sodium": D("0")})
    assert grams == D("80")
    assert amounts == {"protein": D("16"), "sodium": D("0")}
    assert basis == "配方可食净量"


def test_uses_edible_ratio_only_when_recorded():
    amounts, grams, _ = ingredient_amounts(D("0.12"), None, D("1000"), D("75"), D("100"),
                                           {"protein": D("20")})
    assert grams == D("90") and amounts["protein"] == D("18")
    assert ingredient_amounts(D("100"), None, D("1"), None, D("100"), {})[0] == {}


def test_package_and_volume_conversions_require_a_mass_basis():
    assert unit_factor("盒", "g", None, None, PER_100_G, D("100")) is None
    assert unit_factor("盒", "g", None, D("175"), PER_100_G, D("100")) == D("175")
    assert unit_factor("只", "只", "52.3", 1, PER_100_G, D("100")) == D("52.3")
    assert unit_factor("mL", "g", None, None, PER_100_ML, D("103")) == D("1.03")


def test_aggregation_distinguishes_missing_nutrients_from_confirmed_zero():
    totals = summarize([{"amounts": {"protein": "0", "fat": "2"}}, {"amounts": {"protein": "2.1"}},
                        {"amounts": {}, "issue": "缺少已审核的营养档案"}])
    assert totals["protein"] == {"value": D("2.1"), "covered": 2, "total": 3}
    assert totals["fat"] == {"value": D("2"), "covered": 1, "total": 3}
    assert totals["sodium"] == {"value": None, "covered": 0, "total": 3}
    assert number("NaN") is None and number("0") == D("0")
