from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from importlib.resources import files
from io import BytesIO
import math
import re
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile
import xml.etree.ElementTree as ET


SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
ET.register_namespace("", SHEET_NS)

NUTRIENT_KEYS = (
    "energy", "protein", "fat", "carbohydrate", "calcium", "vitamin_a", "vitamin_b1",
    "vitamin_b2", "vitamin_c", "vitamin_e", "niacin", "potassium", "magnesium", "iron",
    "zinc", "phosphorus", "selenium", "carotene", "fiber", "cholesterol",
)
MEAL_SLOTS = ("breakfast", "morningSnack", "lunch", "snack", "dinner")
MEAL_STANDARD = {"breakfast": 20, "morningSnack": 10, "lunch": 30, "snack": 10, "dinner": 30}

# 4-5 岁儿童参考档案；在园目标按全日参考量的 80% 计算，可由站点营养标准档案覆盖。
DEFAULT_STANDARD = {
    "profile": "4-5岁儿童（男女平均）",
    "source": "DB4403/T 489-2024及中国居民膳食营养素参考摄入量",
    "garden_ratio": 0.8,
    "energy": 1325, "protein": 30, "calcium": 600, "vitamin_a": 385,
    "vitamin_b1": 0.9, "vitamin_b2": 0.85, "vitamin_c": 50, "vitamin_e": 7,
    "niacin": 8, "potassium": 1400, "magnesium": 200, "iron": 10, "zinc": 5.5,
    "phosphorus": 450, "selenium": 30,
    "carbohydrate_energy_range": (50, 65), "fat_energy_range": (20, 30),
    "protein_energy_range": (10, 20),
}

# 每 100 克可食部的代表性数据。精确别名优先；未命中时使用分类代表值并在报告中披露。
CATEGORY_PROFILES = {
    "fine_grain": dict(energy=350, protein=8, fat=1.2, carbohydrate=77, calcium=18, phosphorus=115, potassium=120, magnesium=35, iron=1.8, zinc=1.4, selenium=4, vitamin_b1=.15, vitamin_b2=.05, niacin=2, fiber=1.2),
    "coarse_grain": dict(energy=340, protein=9, fat=2.5, carbohydrate=70, calcium=25, phosphorus=220, potassium=280, magnesium=90, iron=3, zinc=2, selenium=5, vitamin_b1=.3, vitamin_b2=.12, niacin=2.5, fiber=5),
    "pastry": dict(energy=330, protein=8, fat=8, carbohydrate=58, calcium=35, phosphorus=100, potassium=110, magnesium=30, iron=1.5, zinc=.8, selenium=4, vitamin_b1=.1, vitamin_b2=.08, niacin=1, fiber=1.5),
    "dry_bean": dict(energy=360, protein=25, fat=16, carbohydrate=34, calcium=190, phosphorus=470, potassium=1500, magnesium=200, iron=8, zinc=3.3, selenium=6, vitamin_b1=.4, vitamin_b2=.2, niacin=2, fiber=15),
    "soy": dict(energy=105, protein=10, fat=5, carbohydrate=4, calcium=160, phosphorus=140, potassium=150, magnesium=65, iron=2, zinc=1, selenium=2, vitamin_b1=.08, vitamin_b2=.05, niacin=.4, fiber=.5),
    "non_green_veg": dict(energy=25, protein=1.2, fat=.2, carbohydrate=4.5, calcium=25, phosphorus=30, potassium=180, magnesium=15, iron=.5, zinc=.25, selenium=.6, vitamin_a=15, carotene=90, vitamin_b1=.03, vitamin_b2=.04, vitamin_c=12, vitamin_e=.4, niacin=.5, fiber=1.3),
    "green_veg": dict(energy=28, protein=2, fat=.3, carbohydrate=4, calcium=75, phosphorus=45, potassium=260, magnesium=28, iron=1.5, zinc=.4, selenium=1, vitamin_a=180, carotene=1080, vitamin_b1=.06, vitamin_b2=.1, vitamin_c=35, vitamin_e=1, niacin=.7, fiber=2),
    "fruit": dict(energy=52, protein=.6, fat=.2, carbohydrate=12, calcium=12, phosphorus=15, potassium=150, magnesium=10, iron=.3, zinc=.15, selenium=.3, vitamin_a=20, carotene=120, vitamin_b1=.03, vitamin_b2=.03, vitamin_c=18, vitamin_e=.5, niacin=.4, fiber=1.5),
    "dairy": dict(energy=62, protein=3.2, fat=3.4, carbohydrate=4.8, calcium=105, phosphorus=73, potassium=109, magnesium=11, iron=.1, zinc=.4, selenium=2, vitamin_a=24, vitamin_b1=.03, vitamin_b2=.14, vitamin_c=1, vitamin_e=.2, niacin=.1, cholesterol=15),
    "egg": dict(energy=144, protein=13.3, fat=8.8, carbohydrate=2.8, calcium=56, phosphorus=130, potassium=154, magnesium=10, iron=2, zinc=1.1, selenium=14, vitamin_a=234, vitamin_b1=.11, vitamin_b2=.27, vitamin_e=1.8, niacin=.2, cholesterol=585),
    "meat": dict(energy=170, protein=20, fat=9, carbohydrate=0, calcium=8, phosphorus=180, potassium=300, magnesium=22, iron=2, zinc=3, selenium=10, vitamin_a=5, vitamin_b1=.35, vitamin_b2=.15, vitamin_e=.4, niacin=5, cholesterol=70),
    "liver": dict(energy=130, protein=19, fat=4, carbohydrate=5, calcium=10, phosphorus=310, potassium=235, magnesium=25, iron=22, zinc=5, selenium=26, vitamin_a=5000, vitamin_b1=.2, vitamin_b2=2, vitamin_c=20, vitamin_e=.9, niacin=15, cholesterol=300),
    "fish": dict(energy=110, protein=19, fat=3, carbohydrate=0, calcium=45, phosphorus=190, potassium=310, magnesium=30, iron=1, zinc=.8, selenium=25, vitamin_a=15, vitamin_b1=.05, vitamin_b2=.1, vitamin_e=.8, niacin=3, cholesterol=65),
    "sugar": dict(energy=395, protein=0, fat=0, carbohydrate=99, calcium=5, phosphorus=1, potassium=10, magnesium=2, iron=.2, zinc=0, selenium=0),
    "oil": dict(energy=899, protein=0, fat=99.9, carbohydrate=0, calcium=0, phosphorus=0, potassium=0, magnesium=0, iron=0, zinc=0, selenium=0, vitamin_e=40),
    "water": dict(energy=0, protein=0, fat=0, carbohydrate=0, calcium=0, phosphorus=0, potassium=0, magnesium=0, iron=0, zinc=0, selenium=0),
}

CATEGORY_ROWS = {
    "fine_grain": (4, 6), "coarse_grain": (7, 9), "pastry": (10, 11),
    "dry_bean": (12, 13), "soy": (14, 15), "non_green_veg": (16, 20),
    "green_veg": (21, 23), "fruit": (24, 25), "dairy": (26, 27),
    "egg": (28, 29), "meat": (30, 31), "liver": (32, 33), "fish": (34, 35),
    "sugar": (36, 37),
}
CATEGORY_LABEL_CELLS = {
    "grain": "B4", "bean": "B12", "vegetable": "B16", "fruit": "B24", "dairy": "B26",
    "egg": "B28", "animal": "B30", "sugar": "B36",
}
SUBCATEGORY_LABEL_CELLS = {
    "fine_grain": ("C4", "细粮"), "coarse_grain": ("C7", "杂粮"), "pastry": ("C10", "糕点"),
    "dry_bean": ("C12", "干豆类"), "soy": ("C14", "豆制品"),
    "non_green_veg": ("C16", "非绿蔬菜"), "green_veg": ("C21", "绿橙蔬菜"),
    "meat": ("C30", "肉类"), "liver": ("C32", "肝"), "fish": ("C34", "鱼"),
}

ALIASES = {
    "纯牛奶": "牛奶", "巴氏杀菌乳": "牛奶", "酸奶": "牛奶", "西红柿": "番茄",
    "西蓝花": "西兰花", "红萝卜": "胡萝卜", "大肉": "猪肉", "猪瘦肉": "猪肉",
    "猪里脊肉": "猪肉", "肉丝": "猪肉", "肉丁": "猪肉", "龙利鱼": "鱼",
    "鱼头": "鱼", "甜玉米": "玉米", "甜玉米粒": "玉米", "玉米粒": "玉米",
    "小麦粉": "面粉", "全麦面粉": "面粉", "糕点": "切片面包", "饮用水": "水",
}

KEYWORDS = (
    ("water", ("水", "骨汤")), ("oil", ("油", "芝麻酱", "花生米", "核桃仁")),
    ("dairy", ("奶", "酸奶")), ("egg", ("蛋",)), ("liver", ("肝",)),
    ("fish", ("鱼", "虾", "海鲜")), ("meat", ("肉", "鸡", "牛", "排骨", "火腿")),
    ("soy", ("豆腐", "豆干", "豆芽")), ("dry_bean", ("黄豆", "红豆", "绿豆", "青豆", "豌豆", "毛豆")),
    ("fruit", ("苹果", "香蕉", "西瓜", "哈密瓜", "葡萄", "火龙果", "梨", "蓝莓", "圣女果")),
    ("green_veg", ("菠菜", "油麦菜", "生菜", "青菜", "菜心", "西兰花", "西蓝花", "芹菜", "西芹", "青椒", "韭菜", "荷兰豆")),
    ("non_green_veg", ("菜", "瓜", "番茄", "西红柿", "萝卜", "葱", "姜", "蒜", "木耳", "香菇", "蘑菇", "海带", "紫菜", "莲藕", "土豆", "山药", "芋头")),
    ("sugar", ("糖", "果酱")), ("pastry", ("面包", "糕点", "饼干")),
    ("coarse_grain", ("小米", "黑米", "糙米", "燕麦", "玉米", "薏米", "紫薯", "红薯", "玉米糁", "玉米粉")),
    ("fine_grain", ("大米", "面粉", "面条", "饺子皮", "馄饨皮", "江米", "淀粉")),
)


def _profile(values: dict[str, float]) -> dict[str, float]:
    return {key: float(values.get(key, 0) or 0) for key in NUTRIENT_KEYS}


def classify_ingredient(name: str) -> tuple[str, str]:
    clean = re.sub(r"[（(].*?[）)]", "", str(name or "")).strip()
    clean = ALIASES.get(clean, clean)
    for category, words in KEYWORDS:
        if any(word in clean for word in words):
            return category, clean
    return "non_green_veg", clean


def _grams(row: dict[str, Any]) -> float:
    amount = float(row.get("gramsPerChild") or row.get("grams_per_child") or row.get("amount") or 0)
    unit = str(row.get("unit") or "g").lower()
    if row.get("gramsPerChild") or row.get("grams_per_child"):
        return max(0, amount)
    if unit in {"kg", "千克", "公斤"}:
        return max(0, amount * 1000)
    if unit in {"mg", "毫克"}:
        return max(0, amount / 1000)
    if unit in {"ml", "毫升"}:
        return max(0, amount)
    return max(0, amount)


def analyze_recipe_payload(payload: dict[str, Any], *, standard: dict[str, Any] | None = None, person_days: int | None = None) -> dict[str, Any]:
    days = list(payload.get("days") or [])
    if not days:
        raise ValueError("食谱没有可分析的日期明细")
    standard_values = deepcopy(DEFAULT_STANDARD)
    standard_values.update(standard or {})
    day_count = len(days)
    ingredients: dict[str, dict[str, Any]] = {}
    meal_nutrients = {slot: defaultdict(float) for slot in MEAL_SLOTS}
    total_nutrients = defaultdict(float)
    animal_protein = 0.0
    animal_soy_protein = 0.0

    for day in days:
        for portion in day.get("portions") or []:
            slot = str(portion.get("slot") or "")
            if slot not in meal_nutrients:
                continue
            for row in portion.get("dishIngredientRows") or []:
                raw_name = str(row.get("ingredient") or row.get("ingredient_name") or "").strip()
                if not raw_name:
                    continue
                grams = _grams(row)
                category, normalized = classify_ingredient(raw_name)
                profile = _profile(CATEGORY_PROFILES[category])
                item = ingredients.setdefault(normalized, {"name": normalized, "grams": 0.0, "category": category, "basis": "分类代表值"})
                item["grams"] += grams / day_count
                for key, per_100g in profile.items():
                    value = per_100g * grams / 100 / day_count
                    total_nutrients[key] += value
                    meal_nutrients[slot][key] += value
                protein = profile["protein"] * grams / 100 / day_count
                if category in {"egg", "meat", "liver", "fish", "dairy"}:
                    animal_protein += protein
                    animal_soy_protein += protein
                elif category in {"soy", "dry_bean"}:
                    animal_soy_protein += protein

    energy = total_nutrients["energy"]
    macro = {
        "carbohydrate": total_nutrients["carbohydrate"] * 4 / energy * 100 if energy else 0,
        "fat": total_nutrients["fat"] * 9 / energy * 100 if energy else 0,
        "protein": total_nutrients["protein"] * 4 / energy * 100 if energy else 0,
    }
    meal_energy = {slot: meal_nutrients[slot]["energy"] for slot in MEAL_SLOTS}
    meal_ratio = {slot: (meal_energy[slot] / energy * 100 if energy else 0) for slot in MEAL_SLOTS}
    totals_by_category = defaultdict(float)
    for item in ingredients.values():
        totals_by_category[item["category"]] += item["grams"]
    result = {
        "recipe": payload.get("recipe") or {}, "day_count": day_count,
        "person_days": int(person_days or day_count), "ingredients": sorted(ingredients.values(), key=lambda item: (item["category"], item["name"])),
        "category_totals": dict(totals_by_category), "nutrients": dict(total_nutrients),
        "meal_standard": MEAL_STANDARD, "meal_ratio": meal_ratio, "macro_energy_ratio": macro,
        "animal_protein": animal_protein, "animal_soy_protein": animal_soy_protein,
        "calcium_phosphorus_ratio": total_nutrients["calcium"] / total_nutrients["phosphorus"] if total_nutrients["phosphorus"] else 0,
        "standard": standard_values,
    }
    result["conclusion"] = _conclusion(result)
    return result


def _percent(actual: float, target: float) -> float:
    return actual / target * 100 if target else 0


def _evaluation(percent: float) -> str:
    if percent < 80:
        return "偏低"
    if percent > 120:
        return "偏高"
    return "适宜"


def _conclusion(result: dict[str, Any]) -> str:
    standard = result["standard"]
    garden_ratio = float(standard["garden_ratio"])
    nutrients = result["nutrients"]
    checks = []
    for key, label in (("energy", "热量"), ("protein", "蛋白质"), ("calcium", "钙"), ("iron", "铁"), ("zinc", "锌"), ("vitamin_a", "维生素A"), ("vitamin_c", "维生素C")):
        status = _evaluation(_percent(float(nutrients.get(key, 0)), float(standard[key]) * garden_ratio))
        if status != "适宜":
            checks.append(f"{label}{status}")
    diversity = len(result["ingredients"])
    first = f"本周食谱日均覆盖 {diversity} 种食材；" + ("主要营养指标处于参考范围。" if not checks else f"需关注：{'、'.join(checks)}。")
    return first + "建议结合实际可食部、品牌营养标签和就餐人数复核。本报告为膳食管理估算，不替代临床诊断。"


def _set_cell(root: ET.Element, ref: str, value: Any) -> None:
    ns = {"m": SHEET_NS}
    cell = root.find(f".//m:c[@r='{ref}']", ns)
    if cell is None:
        raise ValueError(f"模板缺少单元格 {ref}")
    for child in list(cell):
        if child.tag in {f"{{{SHEET_NS}}}v", f"{{{SHEET_NS}}}is", f"{{{SHEET_NS}}}f"}:
            cell.remove(child)
    if value is None or value == "":
        cell.attrib.pop("t", None)
        return
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        cell.attrib.pop("t", None)
        ET.SubElement(cell, f"{{{SHEET_NS}}}v").text = str(round(float(value), 2))
    else:
        cell.set("t", "inlineStr")
        inline = ET.SubElement(cell, f"{{{SHEET_NS}}}is")
        text = ET.SubElement(inline, f"{{{SHEET_NS}}}t")
        text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        text.text = str(value)


def _fmt(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def build_report_xlsx(analysis: dict[str, Any], template_bytes: bytes | None = None) -> bytes:
    if template_bytes is None:
        template_bytes = files("tongjianyun").joinpath("templates/食谱带量分析元素.xlsx").read_bytes()
    source = BytesIO(template_bytes)
    target = BytesIO()
    with ZipFile(source) as zin, ZipFile(target, "w", ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            content = zin.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                root = ET.fromstring(content)
                _populate_sheet(root, analysis)
                content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            zout.writestr(info, content)
    return target.getvalue()


def _populate_sheet(root: ET.Element, analysis: dict[str, Any]) -> None:
    totals = analysis["category_totals"]
    _set_cell(root, "D2", f"每人每天平均进食量（折算为整全天，即一个人日数）（{len(analysis['ingredients'])}种）（克）（可食重量）")
    group_totals = {
        "grain": sum(totals.get(key, 0) for key in ("fine_grain", "coarse_grain", "pastry")),
        "bean": totals.get("dry_bean", 0) + totals.get("soy", 0),
        "vegetable": totals.get("non_green_veg", 0) + totals.get("green_veg", 0),
        "fruit": totals.get("fruit", 0), "dairy": totals.get("dairy", 0), "egg": totals.get("egg", 0),
        "animal": sum(totals.get(key, 0) for key in ("meat", "liver", "fish")), "sugar": totals.get("sugar", 0),
    }
    labels = {"grain": "粮食类", "bean": "豆类", "vegetable": "蔬菜类", "fruit": "水果", "dairy": "乳类", "egg": "蛋类", "animal": "鱼肉类", "sugar": "糖类"}
    for key, cell in CATEGORY_LABEL_CELLS.items():
        _set_cell(root, cell, f"{labels[key]}\n{_fmt(group_totals[key])}")
    for key, (cell, label) in SUBCATEGORY_LABEL_CELLS.items():
        _set_cell(root, cell, f"{label}\n{_fmt(totals.get(key, 0))}")

    by_category = defaultdict(list)
    for item in analysis["ingredients"]:
        category = item["category"]
        if category in CATEGORY_ROWS:
            by_category[category].append(item)
    for category, (start, end) in CATEGORY_ROWS.items():
        slots = [(f"{name_col}{row}", f"{weight_col}{row}") for row in range(start, end + 1) for name_col, weight_col in (("D", "E"), ("F", "G"), ("H", "I"), ("J", "K"), ("L", "M"))]
        for index, (name_cell, weight_cell) in enumerate(slots):
            item = by_category[category][index] if index < len(by_category[category]) else None
            _set_cell(root, name_cell, item["name"] if item else "")
            _set_cell(root, weight_cell, round(item["grams"], 1) if item else "")

    _set_cell(root, "N4", analysis["person_days"])
    for row, slot in zip(range(6, 11), MEAL_SLOTS):
        _set_cell(root, f"O{row}", f"{analysis['meal_standard'][slot]}%")
    for row, slot in zip(range(12, 17), MEAL_SLOTS):
        _set_cell(root, f"O{row}", f"{_fmt(analysis['meal_ratio'][slot])}%")
    _set_cell(root, "O18", "1.2-2.0")
    _set_cell(root, "O19", _fmt(analysis["calcium_phosphorus_ratio"], 2))
    _set_cell(root, "N20", f"胡萝卜素：{_fmt(analysis['nutrients']['carotene'])}ug")
    _set_cell(root, "N22", f"纤维：{_fmt(analysis['nutrients']['fiber'])}g")
    _set_cell(root, "N24", f"胆固醇：{_fmt(analysis['nutrients']['cholesterol'])}mg")

    std = analysis["standard"]
    garden_ratio = float(std["garden_ratio"])
    nutrient_rows = {
        4: "energy", 8: "protein", 11: "calcium", 12: "vitamin_a", 13: "vitamin_b1",
        14: "vitamin_b2", 15: "vitamin_c", 16: "vitamin_e", 17: "niacin", 18: "potassium",
        19: "magnesium", 20: "iron", 21: "zinc", 22: "phosphorus", 23: "selenium",
    }
    for row, key in nutrient_rows.items():
        full = float(std[key])
        garden = full * garden_ratio
        actual = float(analysis["nutrients"].get(key, 0))
        pct = _percent(actual, garden)
        _set_cell(root, f"R{row}", round(full, 2))
        _set_cell(root, f"S{row}", round(garden, 2))
        _set_cell(root, f"T{row}", round(actual, 2))
        _set_cell(root, f"U{row}", f"{_fmt(pct)}%")
        _set_cell(root, f"V{row}", _evaluation(pct))
    for row, macro_key, range_key in ((5, "carbohydrate", "carbohydrate_energy_range"), (6, "fat", "fat_energy_range"), (7, "protein", "protein_energy_range")):
        low, high = std[range_key]
        actual = analysis["macro_energy_ratio"][macro_key]
        _set_cell(root, f"R{row}", f"{low}-{high}%")
        _set_cell(root, f"S{row}", f"{low}-{high}%")
        _set_cell(root, f"T{row}", f"{_fmt(actual)}%")
        _set_cell(root, f"U{row}", f"{_fmt(actual)}%")
        _set_cell(root, f"V{row}", "适宜" if low <= actual <= high else ("偏低" if actual < low else "偏高"))
    protein = analysis["nutrients"]["protein"]
    for row, actual in ((9, analysis["animal_protein"]), (10, analysis["animal_soy_protein"])):
        pct = actual / protein * 100 if protein else 0
        _set_cell(root, f"T{row}", round(actual, 2))
        _set_cell(root, f"U{row}", f"{_fmt(pct)}%")
        _set_cell(root, f"V{row}", "适宜" if pct >= (30 if row == 9 else 50) else "偏低")
    recipe = analysis.get("recipe") or {}
    _set_cell(root, "N26", f"食谱：{recipe.get('title') or recipe.get('recipeId') or '—'}\n日期：{recipe.get('weekStart') or '—'} 至 {recipe.get('weekEnd') or '—'}\n标准：{std['profile']}；在园目标按全日 {garden_ratio:.0%} 计算。食物成分采用分类代表值估算。")
    _set_cell(root, "P32", analysis["conclusion"])


def create_and_attach_recipe_analysis(recipe_name: str, *, standard: dict[str, Any] | None = None) -> dict[str, Any]:
    import frappe
    from frappe.utils import get_url
    from tongjianyun.recipe_storage import get_recipe_detail

    recipe = frappe.get_doc("Tongjianyun Recipe", recipe_name)
    recipe.check_permission("read")
    payload = get_recipe_detail(recipe.name)
    analysis = analyze_recipe_payload(payload, standard=standard, person_days=_person_days(recipe))
    content = build_report_xlsx(analysis)
    recipe_id = str((payload.get("recipe") or {}).get("recipeId") or recipe.name)
    file_name = f"食谱带量分析-{recipe_id}.xlsx"
    for old_name in frappe.get_all("File", filters={"attached_to_doctype": recipe.doctype, "attached_to_name": recipe.name, "file_name": file_name}, pluck="name"):
        frappe.delete_doc("File", old_name, ignore_permissions=True)
    file_doc = frappe.get_doc({"doctype": "File", "file_name": file_name, "is_private": 1, "content": content, "attached_to_doctype": recipe.doctype, "attached_to_name": recipe.name}).insert(ignore_permissions=True)
    return {"recipe": recipe.name, "file_name": file_name, "file_url": file_doc.file_url, "download_url": get_url(file_doc.file_url), "file_size": len(content), "ingredient_count": len(analysis["ingredients"]), "analysis": {"profile": analysis["standard"]["profile"], "conclusion": analysis["conclusion"]}}


def _person_days(recipe: Any) -> int:
    import frappe
    dates = frappe.get_all("Tongjianyun Recipe Dish", filters={"recipe": recipe.name}, distinct=True, pluck="meal_date")
    total = 0
    if "Tongjianyun Daily Meal Confirmation" in frappe.get_all("DocType", pluck="name", filters={"name": "Tongjianyun Daily Meal Confirmation"}):
        fields = ["total_breakfast_count", "total_morning_snack_count", "total_lunch_count", "total_afternoon_snack_count", "total_dinner_count"]
        for row in frappe.get_all("Tongjianyun Daily Meal Confirmation", filters={"meal_date": ["in", dates]}, fields=fields):
            total += max(int(row.get(field) or 0) for field in fields)
    return total or max(1, len([date for date in dates if date]))
