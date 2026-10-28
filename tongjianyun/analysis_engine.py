"""Recipe structure and gross quantities only. All nutrition analysis is transient AI."""
from decimal import Decimal, InvalidOperation


def positive(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("食材带量无效") from None
    if not number.is_finite() or number <= 0:
        raise ValueError("食材带量必须为有限正数")
    return number


def analyze(details, dates):
    dates = tuple(map(str, dates))
    if not dates or len(set(dates)) != len(dates):
        raise ValueError("食谱分析需要明确且不重复的日期")
    daily, foods = {day: set() for day in dates}, {}
    for row in details:
        day, code, unit = str(row["meal_date"]), row["ingredient_code"], row["uom"]
        if day not in daily or not code or not unit:
            raise ValueError("食材来源日期或标识与周表不一致")
        qty = positive(row["per_child_qty"])
        daily[day].add(code)
        food = foods.setdefault((code, unit), {"code": code, "name": row["ingredient_name"], "uom": unit, "quantity": Decimal(0)})
        food["quantity"] += qty
    return {"day_count": len(dates), "line_count": len(details), "food_count": len({code for code, unit in foods}),
            "daily_foods": {day: len(codes) for day, codes in daily.items()},
            "foods": [{**food, "quantity": str(food["quantity"]), "daily_quantity": str(food["quantity"] / len(dates))} for food in foods.values()]}
