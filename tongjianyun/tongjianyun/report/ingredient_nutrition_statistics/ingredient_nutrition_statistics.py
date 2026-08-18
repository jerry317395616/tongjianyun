from __future__ import annotations

from collections import defaultdict
import re
from typing import Any

import frappe
from frappe.utils import escape_html, flt

from tongjianyun.recipe_analysis import CATEGORY_PROFILES, classify_ingredient


RECIPE_DOCTYPE = "Tongjianyun Recipe"
DISH_DOCTYPE = "Tongjianyun Recipe Dish"
INGREDIENT_DOCTYPE = "Tongjianyun Recipe Ingredient"

CATEGORY_LABELS = {
    "fine_grain": "细粮",
    "coarse_grain": "杂粮",
    "pastry": "糕点",
    "dry_bean": "干豆类",
    "soy": "豆制品",
    "non_green_veg": "非深色蔬菜",
    "green_veg": "深色蔬菜",
    "fruit": "水果",
    "dairy": "奶及奶制品",
    "egg": "蛋类",
    "meat": "肉类",
    "liver": "动物肝脏",
    "fish": "鱼虾水产",
    "sugar": "糖类",
    "oil": "油脂及坚果",
    "water": "饮用水",
}
CATEGORY_KEYS = {label: key for key, label in CATEGORY_LABELS.items()}

MEAL_LABELS = {
    "breakfast": "早餐",
    "morningSnack": "早点",
    "lunch": "午餐",
    "snack": "午点",
    "dinner": "晚餐",
}
MEAL_KEYS = {label: key for key, label in MEAL_LABELS.items()}

# 字段、名称、单位、小数位、列宽、是否属于核心指标。
NUTRIENT_META = (
    ("energy", "能量", "kcal", 1, 115, True),
    ("protein", "蛋白质", "g", 2, 112, True),
    ("fat", "脂肪", "g", 2, 100, True),
    ("carbohydrate", "碳水化合物", "g", 2, 128, True),
    ("calcium", "钙", "mg", 2, 100, True),
    ("phosphorus", "磷", "mg", 2, 100, False),
    ("potassium", "钾", "mg", 2, 100, False),
    ("magnesium", "镁", "mg", 2, 100, False),
    ("iron", "铁", "mg", 3, 96, True),
    ("zinc", "锌", "mg", 3, 96, True),
    ("selenium", "硒", "μg", 3, 96, False),
    ("vitamin_a", "维生素A", "μg RAE", 2, 125, True),
    ("vitamin_b1", "维生素B1", "mg", 3, 116, False),
    ("vitamin_b2", "维生素B2", "mg", 3, 116, False),
    ("vitamin_c", "维生素C", "mg", 2, 116, True),
    ("vitamin_e", "维生素E", "mg α-TE", 3, 126, False),
    ("niacin", "烟酸", "mg NE", 3, 106, False),
    ("carotene", "总胡萝卜素", "μg", 2, 126, False),
    ("fiber", "膳食纤维", "g", 2, 112, False),
    ("cholesterol", "胆固醇", "mg", 2, 112, False),
)
NUTRIENT_LABELS = {fieldname: label for fieldname, label, *_rest in NUTRIENT_META}
SORT_KEYS = {
    "能量": "energy",
    "蛋白质": "protein",
    "脂肪": "fat",
    "碳水化合物": "carbohydrate",
    "钙": "calcium",
    "铁": "iron",
    "锌": "zinc",
    "维生素A": "vitamin_a",
    "维生素C": "vitamin_c",
    "膳食纤维": "fiber",
}


def execute(filters: dict[str, Any] | None = None):
    filters = frappe._dict(filters or {})
    recipe_name = filters.get("recipe") or _latest_recipe()
    if not recipe_name:
        frappe.throw("暂无可统计的食谱，请先创建或导入一份食谱。")

    recipe = frappe.get_doc(RECIPE_DOCTYPE, recipe_name)
    recipe.check_permission("read")
    if recipe.is_deleted:
        frappe.throw("回收站中的食谱不能生成食材营养统计。")

    dishes = _get_dishes(recipe.name)
    day_count = max(1, len({row.get("day_id") or str(row.get("meal_date") or "") for row in dishes if row.get("day_id") or row.get("meal_date")}))
    dish_map = {row.name: row for row in dishes}
    meal_key = MEAL_KEYS.get(str(filters.get("meal_slot") or ""), "")
    category_key = CATEGORY_KEYS.get(str(filters.get("category") or ""), "")
    keyword = _clean(filters.get("ingredient")).lower()

    aggregates: dict[str, dict[str, Any]] = {}
    ingredient_rows = frappe.get_all(
        INGREDIENT_DOCTYPE,
        filters={"recipe": recipe.name},
        fields=["recipe_dish", "ingredient_name", "amount", "unit", "grams_per_child"],
        order_by="ingredient_name asc",
        limit_page_length=0,
    )
    for row in ingredient_rows:
        dish = dish_map.get(row.recipe_dish)
        if not dish or (meal_key and dish.meal_slot != meal_key):
            continue
        raw_name = _clean(row.ingredient_name)
        if not raw_name or (keyword and keyword not in raw_name.lower()):
            continue
        category, display_name = classify_ingredient(raw_name)
        if category_key and category != category_key:
            continue
        item = aggregates.setdefault(
            display_name,
            {
                "ingredient": display_name,
                "category_key": category,
                "category": CATEGORY_LABELS.get(category, category),
                "occurrences": 0,
                "weekly_grams": 0.0,
                "dishes": set(),
                "meals": set(),
            },
        )
        item["occurrences"] += 1
        item["weekly_grams"] += _grams(row)
        if dish.dish_name:
            item["dishes"].add(dish.dish_name)
        item["meals"].add(MEAL_LABELS.get(dish.meal_slot, dish.meal_label or dish.meal_slot))

    if not aggregates:
        frappe.throw("当前筛选条件下没有食材数据。")

    value_basis = str(filters.get("value_basis") or "日均每人贡献")
    nutrient_scope = str(filters.get("nutrient_scope") or "全部指标")
    data: list[dict[str, Any]] = []
    for item in aggregates.values():
        profile = CATEGORY_PROFILES.get(item["category_key"], {})
        weekly_grams = flt(item["weekly_grams"])
        daily_grams = weekly_grams / day_count
        if value_basis == "每100克营养成分":
            nutrient_grams = 100.0
        elif value_basis == "周合计每人贡献":
            nutrient_grams = weekly_grams
        else:
            nutrient_grams = daily_grams
        row = {
            "ingredient": item["ingredient"],
            "category": item["category"],
            "occurrences": item["occurrences"],
            "weekly_grams": weekly_grams,
            "daily_grams": daily_grams,
            "meals": "、".join(sorted(item["meals"])),
            "dishes": "、".join(sorted(item["dishes"])),
            "data_basis": "分类代表值/100g可食部",
        }
        for fieldname, _label, _unit, _precision, _width, _is_core in NUTRIENT_META:
            row[fieldname] = flt(profile.get(fieldname)) * nutrient_grams / 100
        data.append(row)

    sort_key = SORT_KEYS.get(str(filters.get("sort_by") or "能量"), "energy")
    data.sort(key=lambda row: (-flt(row.get(sort_key)), row.get("category") or "", row.get("ingredient") or ""))

    columns = _columns(value_basis, nutrient_scope)
    chart = _chart(data, sort_key, value_basis)
    report_summary = _summary(data, day_count)
    message = _message(recipe, day_count, value_basis, nutrient_scope, len(data))
    return columns, data, message, chart, report_summary, 1


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _grams(row: Any) -> float:
    grams = flt(row.grams_per_child)
    if grams:
        return max(0.0, grams)
    amount = flt(row.amount)
    unit = _clean(row.unit).lower()
    if unit in {"kg", "kilogram", "kilograms", "千克", "公斤"}:
        return max(0.0, amount * 1000)
    if unit in {"mg", "milligram", "milligrams", "毫克"}:
        return max(0.0, amount / 1000)
    if unit in {"ml", "毫升"}:
        return max(0.0, amount)
    return max(0.0, amount)


def _latest_recipe() -> str | None:
    rows = frappe.get_list(
        RECIPE_DOCTYPE,
        filters={"is_deleted": 0},
        fields=["name"],
        order_by="week_start desc, modified desc",
        limit=1,
    )
    return rows[0].name if rows else None


def _get_dishes(recipe_name: str) -> list[Any]:
    return frappe.get_all(
        DISH_DOCTYPE,
        filters={"recipe": recipe_name},
        fields=["name", "day_id", "meal_date", "meal_slot", "meal_label", "dish_name"],
        order_by="sort_order asc",
        limit_page_length=0,
    )


def _basis_suffix(value_basis: str) -> str:
    if value_basis == "每100克营养成分":
        return "/100g"
    if value_basis == "周合计每人贡献":
        return "/人周"
    return "/人日"


def _columns(value_basis: str, nutrient_scope: str) -> list[dict[str, Any]]:
    columns = [
        {"fieldname": "ingredient", "label": "食材", "fieldtype": "Data", "width": 150},
        {"fieldname": "category", "label": "食材分类", "fieldtype": "Data", "width": 120},
        {"fieldname": "occurrences", "label": "出现次数", "fieldtype": "Int", "width": 88},
        {"fieldname": "weekly_grams", "label": "周人均用量(g)", "fieldtype": "Float", "precision": 1, "width": 126},
        {"fieldname": "daily_grams", "label": "日均人均用量(g)", "fieldtype": "Float", "precision": 1, "width": 136},
        {"fieldname": "meals", "label": "涉及餐次", "fieldtype": "Data", "width": 120},
        {"fieldname": "dishes", "label": "涉及菜品", "fieldtype": "Data", "width": 230},
    ]
    suffix = _basis_suffix(value_basis)
    for fieldname, label, unit, precision, width, is_core in NUTRIENT_META:
        if nutrient_scope == "核心指标" and not is_core:
            continue
        columns.append(
            {
                "fieldname": fieldname,
                "label": f"{label}({unit}{suffix})",
                "fieldtype": "Float",
                "precision": precision,
                "width": width,
            }
        )
    columns.append({"fieldname": "data_basis", "label": "数据依据", "fieldtype": "Data", "width": 155})
    return columns


def _chart(data: list[dict[str, Any]], sort_key: str, value_basis: str) -> dict[str, Any]:
    top = data[:10]
    label = NUTRIENT_LABELS.get(sort_key, "能量")
    return {
        "data": {
            "labels": [row["ingredient"] for row in top],
            "datasets": [{"name": f"{label}{_basis_suffix(value_basis)}", "values": [round(flt(row.get(sort_key)), 3) for row in top]}],
        },
        "type": "bar",
        "height": 300,
        "colors": ["#1f7a5a"],
        "axisOptions": {"xAxisMode": "tick", "yAxisMode": "tick"},
    }


def _summary(data: list[dict[str, Any]], day_count: int) -> list[dict[str, Any]]:
    weekly_grams = sum(flt(row.get("weekly_grams")) for row in data)
    daily_factor = 1 / max(1, day_count)
    daily_energy = sum(flt(row.get("energy")) for row in _daily_rows(data, day_count))
    daily_protein = sum(flt(row.get("protein")) for row in _daily_rows(data, day_count))
    daily_calcium = sum(flt(row.get("calcium")) for row in _daily_rows(data, day_count))
    return [
        {"label": "食材种类", "value": len(data), "datatype": "Int", "indicator": "Green"},
        {"label": "出现次数", "value": sum(int(row.get("occurrences") or 0) for row in data), "datatype": "Int", "indicator": "Blue"},
        {"label": "周人均用量(g)", "value": round(weekly_grams, 1), "datatype": "Float", "indicator": "Blue"},
        {"label": "日均能量(kcal)", "value": round(daily_energy, 1), "datatype": "Float", "indicator": "Orange"},
        {"label": "日均蛋白质(g)", "value": round(daily_protein, 2), "datatype": "Float", "indicator": "Green"},
        {"label": "日均钙(mg)", "value": round(daily_calcium, 1), "datatype": "Float", "indicator": "Purple"},
    ]


def _daily_rows(data: list[dict[str, Any]], day_count: int) -> list[dict[str, float]]:
    rows = []
    for row in data:
        category = next((key for key, label in CATEGORY_LABELS.items() if label == row.get("category")), "non_green_veg")
        profile = CATEGORY_PROFILES.get(category, {})
        grams = flt(row.get("weekly_grams")) / max(1, day_count)
        rows.append({fieldname: flt(profile.get(fieldname)) * grams / 100 for fieldname, *_rest in NUTRIENT_META})
    return rows


def _message(recipe: Any, day_count: int, value_basis: str, nutrient_scope: str, ingredient_count: int) -> str:
    date_range = ""
    if recipe.week_start or recipe.week_end:
        date_range = f"（{escape_html(str(recipe.week_start or ''))} 至 {escape_html(str(recipe.week_end or ''))}）"
    return (
        '<div style="padding:10px 12px;line-height:1.7;border-left:3px solid #1f7a5a;background:var(--subtle-fg);">'
        f'<b>{escape_html(recipe.title or recipe.name)}</b>{date_range}：共统计 {ingredient_count} 种食材、{day_count} 个食谱日；'
        f'当前口径为“{escape_html(value_basis)}”，显示“{escape_html(nutrient_scope)}”。'
        '<br><span style="color:var(--text-muted);">营养值采用食材分类代表值估算，适用于食谱编制和趋势筛查；正式评价请结合准确食物成分、可食部、品牌标签及烹调损耗复核。</span>'
        '</div>'
    )
