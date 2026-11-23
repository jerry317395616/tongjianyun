"""Deterministic food-composition calculations with explicit missing values."""

from decimal import Decimal, InvalidOperation

from tongjianyun.ai_nutrition import NUTRIENTS as REPORT_NUTRIENTS

NUTRIENTS = {**REPORT_NUTRIENTS, "sodium": ("钠", "mg")}
MASS_UNITS = {
    "g": 1, "gram": 1, "grams": 1, "克": 1, "公克": 1, "gms": 1,
    "kg": 1000, "kilogram": 1000, "kilograms": 1000, "公斤": 1000, "千克": 1000,
    "mg": "0.001", "毫克": "0.001", "斤": 500,
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


def mass_in_grams(unit):
    return positive(MASS_UNITS.get(str(unit or "").strip().casefold()))


def stock_mass_in_grams(stock_unit, conversions):
    if mass := mass_in_grams(stock_unit):
        return mass
    masses = [grams / factor for unit, raw_factor in conversions.items()
              if (grams := mass_in_grams(unit)) and (factor := positive(raw_factor))]
    if masses and all(abs(value / masses[0] - 1) <= Decimal("0.000001") for value in masses):
        return masses[0]


def unit_factor(unit, stock_mass, stock_conversion):
    if mass := mass_in_grams(unit):
        return mass
    conversion = positive(stock_conversion)
    return conversion * stock_mass if conversion and stock_mass else None


def ingredient_amounts(gross, net, grams_per_unit, nutrients):
    """Return known contributions and the actual basis used to calculate them."""
    if net is None or not 0 < net <= gross:
        return {}, None, "缺少可食净量"
    if not grams_per_unit:
        return {}, None, "缺少重量换算"
    grams = net * grams_per_unit
    return {key: value * grams / 100 for key, value in nutrients.items()}, grams, "配方可食净量"


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
