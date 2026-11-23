"""Deterministic food-composition calculations with explicit missing values."""

from decimal import Decimal, InvalidOperation

from tongjianyun.ai_nutrition import NUTRIENTS as REPORT_NUTRIENTS

NUTRIENTS = {**REPORT_NUTRIENTS, "sodium": ("钠", "mg")}
PRIMARY = ("energy", "protein", "fat", "carbohydrate")
PER_100_G = "每100克"
PER_100_ML = "每100毫升"
PER_SERVING = "每份"
MASS_UNITS = {
    "g": 1, "gram": 1, "grams": 1, "克": 1, "公克": 1, "gms": 1,
    "kg": 1000, "kilogram": 1000, "kilograms": 1000, "公斤": 1000, "千克": 1000,
    "mg": "0.001", "毫克": "0.001", "斤": 500,
}
VOLUME_UNITS = {
    "ml": 1, "milliliter": 1, "milliliters": 1, "毫升": 1,
    "l": 1000, "liter": 1000, "litre": 1000, "升": 1000,
}


def number(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def positive(value):
    result = number(value)
    return result if result is not None and result > 0 else None


def unit_factor(unit, stock_unit, grams_per_stock_unit, stock_conversion, basis, basis_grams):
    key = str(unit or "").strip().casefold()
    if key in MASS_UNITS:
        return Decimal(MASS_UNITS[key])
    if basis == PER_100_ML and key in VOLUME_UNITS:
        return Decimal(VOLUME_UNITS[key]) * basis_grams / 100
    stock = str(stock_unit or "").strip().casefold()
    stock_mass = positive(grams_per_stock_unit)
    if stock in MASS_UNITS:
        stock_mass = Decimal(MASS_UNITS[stock])
    elif basis == PER_100_ML and stock in VOLUME_UNITS:
        stock_mass = Decimal(VOLUME_UNITS[stock]) * basis_grams / 100
    conversion = positive(stock_conversion)
    return conversion * stock_mass if conversion and stock_mass else None


def ingredient_amounts(gross, net, grams_per_unit, edible_pct, basis_grams, nutrients):
    """Return known contributions and the actual basis used to calculate them."""
    if not basis_grams:
        return {}, None, "缺少营养档案原始计量依据"
    if not grams_per_unit:
        return {}, None, "缺少重量换算"
    if net is not None and 0 < net <= gross:
        grams, basis = net * grams_per_unit, "配方可食净量"
    elif edible_pct is not None:
        grams, basis = gross * grams_per_unit * edible_pct / 100, "默认可食率"
    else:
        return {}, None, "缺少可食净量或可食率"
    amounts = {key: value * grams / basis_grams for key, value in nutrients.items()}
    return amounts, grams, basis


def summarize(lines):
    """Return per-nutrient sums with coverage, preserving confirmed zeroes."""
    lines = tuple(lines)
    result = {}
    for key in NUTRIENTS:
        values = [number(line["amounts"][key]) for line in lines if key in line["amounts"]]
        result[key] = {
            "value": sum(values, Decimal(0)) if values else None,
            "covered": len(values),
            "total": len(lines),
        }
    return result
