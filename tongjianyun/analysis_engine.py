"""Per-child recipe structure and explicit partial category estimates; no database I/O."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from tongjianyun.nutrition_profiles import CATEGORY_PROFILES, NUTRIENT_KEYS, classify_ingredient

MASS_FACTORS = {"g": Decimal(1), "Gram": Decimal(1), "克": Decimal(1), "kg": Decimal(1000), "Kg": Decimal(1000), "Kilogram": Decimal(1000), "千克": Decimal(1000), "mg": Decimal("0.001"), "Milligram": Decimal("0.001")}
VOLUME_FACTORS = {"ml": Decimal(1), "Millilitre": Decimal(1), "毫升": Decimal(1), "L": Decimal(1000), "Litre": Decimal(1000)}


def positive(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("食材带量无效") from None
    if not number.is_finite() or number <= 0:
        raise ValueError("食材带量必须为有限正数")
    return number


def analyze(details, dates):
    dates = tuple(str(day) for day in dates)
    if not dates or len(set(dates)) != len(dates):
        raise ValueError("食谱分析需要明确且不重复的日期")
    foods, daily = {}, {day: set() for day in dates}
    nutrients = {key: Decimal(0) for key in NUTRIENT_KEYS}
    coverage = {key: 0 for key in NUTRIENT_KEYS}
    category_mass, meal_energy = defaultdict(Decimal), defaultdict(Decimal)
    missing, used_rows = [], 0
    for row in details:
        day, code, unit = str(row["meal_date"]), row["ingredient_code"], row["uom"]
        if day not in daily or not code:
            raise ValueError("食材来源日期或标识与周表不一致")
        quantity = positive(row["per_child_qty"])
        daily[day].add(code)
        category, name = classify_ingredient(row["ingredient_name"])
        food = foods.setdefault((code, unit), {"code": code, "name": name, "uom": unit, "quantity": Decimal(0), "category": category})
        food["quantity"] += quantity
        profile = CATEGORY_PROFILES.get(category)
        if unit not in MASS_FACTORS:
            reason = "缺少经核实的密度，不把体积当作重量" if unit in VOLUME_FACTORS else "缺少经核实的质量换算"
        elif profile is None:
            reason = "缺少对应营养资料；未自动归为蔬菜"
        else:
            grams = quantity * MASS_FACTORS[unit]
            category_mass[category] += grams
            used_rows += 1
            for key in NUTRIENT_KEYS:
                # An absent nutrient value is missing data, never a measured zero.
                if key not in profile:
                    continue
                value = Decimal(str(profile[key])) * grams / Decimal(100) / Decimal(len(dates))
                nutrients[key] += value
                coverage[key] += 1
                if key == "energy":
                    meal_energy[row["meal_type"]] += value
            food["basis"] = "分类代表值粗估；毛重及烹调变化未逐食材校核"
            continue
        food["basis"] = reason
        missing.append({"code": code, "name": name, "date": day, "meal_type": row["meal_type"], "quantity": str(quantity), "uom": unit, "reason": reason})
    return {
        "day_count": len(dates), "line_count": len(details), "used_rows": used_rows,
        "food_count": len({code for code, _unit in foods}),
        "daily_foods": {day: len(codes) for day, codes in daily.items()},
        "foods": [{**food, "quantity": str(food["quantity"]), "daily_quantity": str(food["quantity"] / Decimal(len(dates)))} for food in foods.values()],
        "nutrients": {key: float(nutrients[key]) if coverage[key] else None for key in NUTRIENT_KEYS},
        "coverage": coverage, "category_daily_mass": {key: float(value / Decimal(len(dates))) for key, value in category_mass.items()},
        "meal_daily_energy": {key: float(value) for key, value in meal_energy.items()},
        "missing": missing, "is_estimate": True, "compliance_conclusion": None,
    }
