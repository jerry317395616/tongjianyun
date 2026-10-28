"""One presentation model for the report page, temporary preview and Excel.

Only source quantities and presentation ratios are aggregated here. Unknown
reference targets and unsupported model metrics must never become zeroes.
"""
from collections import defaultdict
from decimal import Decimal
from html import escape
from math import ceil

from tongjianyun.ai_nutrition import NUTRIENTS, validate_result
from tongjianyun.nutrition_profiles import classify_ingredient

GROUPS = (
    ("粮食类", (("fine_grain", "细粮", 3), ("coarse_grain", "杂粮", 3), ("pastry", "糕点", 2))),
    ("豆类", (("dry_bean", "干豆类", 2), ("soy", "豆制品", 2))),
    ("蔬菜类", (("non_green_veg", "其他蔬菜", 5), ("green_veg", "绿叶蔬菜", 3))),
    ("水果", (("fruit", "", 2),)), ("乳类", (("dairy", "", 2),)),
    ("蛋类", (("egg", "", 2),)),
    ("鱼肉类", (("meat", "肉类", 2), ("liver", "肝", 2), ("fish", "鱼虾", 2))),
    ("糖类", (("sugar", "", 2),)), ("油脂类", (("oil", "", 1),)),
    ("厨房用水", (("water", "", 1),)), ("成品及待分类", (("unclassified", "", 2),)),
)
WIDTHS = [62, 67] + [90, 69] * 5 + [83, 78, 43, 118, 96, 96, 115, 94, 100]
MEALS = ("早餐", "早点", "中餐", "午点", "晚餐")
MISSING = "未提供"


def number(value):
    return f"{Decimal(str(value)):.3f}".rstrip("0").rstrip(".") or "0"


def interval(value, suffix=""):
    if value is None:
        return MISSING
    if value[0] == value[1]:
        return number(value[0]) + suffix
    return number(value[0]) + "–" + number(value[1]) + suffix


def unit(value):
    return {"Gram": "g", "Millilitre": "ml", "Milliliter": "ml", "Kg": "kg", "Liter": "L", "Litre": "L"}.get(value, value)


def total(foods):
    amounts = defaultdict(Decimal)
    for food in foods:
        amounts[unit(food["unit"])] += Decimal(food["daily"])
    return "\n".join(number(value) + " " + key for key, value in sorted(amounts.items())) or "0 g"


def make_sheet(data, result=None):
    if result is not None:
        validate_result(result, data)
    cells, occupied = [], set()

    def put(row, col, value="", rs=1, cs=1, kind="", title=""):
        area = {(r, c) for r in range(row, row + rs) for c in range(col, col + cs)}
        if occupied.intersection(area):
            raise ValueError("Overlapping report cells")
        occupied.update(area)
        cells.append(dict(row=row, col=col, value=value, rowspan=rs, colspan=cs, kind=kind, title=title))

    counts = len({food["code"] for food in data["foods"]})
    put(0, 0, "食物分类重量", rs=2, cs=2, kind="heading")
    put(0, 2, f"每人每天平均计划带量（{counts}种食材；毛重；保留原单位）", cs=10, kind="heading")
    put(0, 12, "营养分析及改进建议", cs=9, kind="heading")
    for col in range(2, 12, 2):
        put(1, col, "食物", kind="heading")
        put(1, col + 1, "重量", kind="heading")
    foods = defaultdict(list)
    for food in data["foods"]:
        key, _ = classify_ingredient(food["name"])
        foods[key].append(food)
    row = 2
    for group, subgroups in GROUPS:
        group_foods = [food for key, _, _ in subgroups for food in foods[key]]
        if group in ("油脂类", "厨房用水", "成品及待分类") and not group_foods:
            continue
        spans = [max(minimum, ceil(len(foods[key]) / 5)) for key, _, minimum in subgroups]
        group_rows = sum(spans)
        put(row, 0, group + "\n" + total(group_foods), rs=group_rows,
            cs=2 if len(subgroups) == 1 else 1, kind="category")
        for (key, label, _), height in zip(subgroups, spans):
            if len(subgroups) > 1:
                put(row, 1, label + "\n" + total(foods[key]), rs=height, kind="category")
            for index, food in enumerate(foods[key]):
                r, c = row + index // 5, 2 + (index % 5) * 2
                put(r, c, food["name"], kind="food")
                put(r, c + 1, number(food["daily"]) + " " + unit(food["unit"]), kind="quantity")
            row += height
    put(1, 12, "分析天数（一周）", cs=2, kind="heading")
    put(1, 14, "营养素", cs=2, kind="heading")
    for col, label in enumerate(("全日标准量", "在园标准量", "在园计划量\n（AI估算）", "在园计划%", "评价"), 16):
        put(1, col, label, kind="heading")
    put(2, 12, str(len(data["dates"])) + " 天", cs=2)
    put(3, 12, "各餐热量参考分配", cs=2, kind="heading")
    put(9, 12, "各餐热量计划分配", cs=2, kind="heading")
    for index, meal in enumerate(MEALS):
        put(4 + index, 12, meal)
        put(4 + index, 13, "未设定", kind="unavailable")
        put(10 + index, 12, meal)
        put(10 + index, 13, "待分析" if result is None else MISSING, kind="unavailable")
    put(15, 12, "钙／磷比例", cs=2, kind="heading")
    put(16, 12, "参考比例")
    put(16, 13, "未设定", kind="unavailable")
    put(17, 12, "计划比例")
    nutrients = {n["key"]: n for n in result["nutrients"]} if result else {}

    def amount(key):
        return nutrients.get(key, {}).get("average")

    def ratio(numerator, denominator, factor=1):
        if numerator is None or denominator is None or denominator[0] <= 0:
            return None
        return [numerator[0] / denominator[1] * factor, numerator[1] / denominator[0] * factor]

    put(17, 13, "待分析" if result is None else interval(ratio(amount("calcium"), amount("phosphorus"))))
    for key, r in (("carotene", 18), ("fiber", 20), ("cholesterol", 22)):
        label, nutrient_unit = NUTRIENTS[key]
        value = "待分析" if result is None else interval(amount(key), " " + nutrient_unit)
        put(r, 12, label + "\n" + value, rs=2, cs=2)
    keys = ["energy", "carbohydrate_energy", "fat_energy", "protein_energy", "protein", "animal_protein", "animal_soy_protein",
            "calcium", "vitamin_a", "vitamin_b1", "vitamin_b2", "vitamin_c", "vitamin_e", "niacin", "potassium", "magnesium", "iron", "zinc", "phosphorus", "selenium"]
    extras = {"carbohydrate_energy": ("碳水供能", 4, "carbohydrate"), "fat_energy": ("脂肪供能", 9, "fat"),
              "protein_energy": ("蛋白质供能", 4, "protein"), "animal_protein": ("动物蛋白（g）", None, None),
              "animal_soy_protein": ("动豆蛋白（g）", None, None)}
    put(2, 14, "热量", rs=4, kind="category")
    put(6, 14, "蛋白质", rs=3, kind="category")
    for index, key in enumerate(keys, 2):
        suffix, note = "", nutrients.get(key, {}).get("basis", "")
        value = amount(key)
        if key in extras:
            label, factor, base = extras[key]
            if factor:
                value, suffix = ratio(amount(base), amount("energy"), 100 * factor), "%"
                note = "按AI估算区间以4/9/4系数折算供能占比；区间端点不可相加。"
        else:
            label = NUTRIENTS[key][0] + "（" + NUTRIENTS[key][1] + "）"
        put(index, 15 if index < 9 else 14, label, cs=1 if index < 9 else 2, kind="metric")
        put(index, 16, "未设定", kind="unavailable")
        put(index, 17, "未设定", kind="unavailable")
        put(index, 18, "待分析" if result is None else interval(value, suffix), kind="quantity", title=note)
        put(index, 19, "—", kind="unavailable")
        put(index, 20, "待分析" if result is None else "未作评价", kind="unavailable")
    put(22, 14, "计划量为AI估算区间，非实测摄入。缺少参考目标的项目不计算达标率。", rs=2, cs=7, kind="note")
    source = data["source"]
    caption = (f"日期：{data['dates'][0]} 至 {data['dates'][-1]}\n"
               f"食谱：{source.get('week_name') or source.get('plan_batch') or source['week_start']}\n"
               "带量口径：每名幼儿的计划配方毛重，五日平均；克与毫升分别汇总。\n"
               "参考口径：3—6岁混龄、在园占全天80%（用户确认的参考假设，非实际年龄构成）。\n"
               "食材分类按名称初分；成品及无法确认的食材单列。")
    put(24, 12, caption, rs=6, cs=9, kind="note")
    put(30, 12, "分析说明\n与建议", rs=6, cs=2, kind="heading")
    notes = (["点击“生成AI营养分析”后，结果直接显示在本表中，并可下载相同版式的Excel。"] if result is None else
             ["AI估算，来自模型通用知识，未联网核验。",
              *["主要假设：" + text[:160] + ("…" if len(text) > 160 else "") for text in result["assumptions"][:1]],
              *["缺项：" + text[:100] + ("…" if len(text) > 100 else "") for text in result["missing"][:1]],
              "完整假设和缺项见下载文件的“每日营养与依据”页。"])
    notes.append("当前模型未提供独立参考标准、各餐供能和蛋白来源分项，因此保留栏目并标明未提供，不沿用样表旧值或判为达标。")
    put(30, 14, "\n".join(notes), rs=6, cs=7, kind="note")
    height = max(row, 36)
    for r in range(height):
        for c in range(21):
            if (r, c) not in occupied:
                put(r, c)
    return {"cells": sorted(cells, key=lambda c: (c["row"], c["col"])), "rows": height,
            "widths": WIDTHS, "dates": data["dates"], "title": "食谱带量分析", "ready": result is not None}


CSS = """
.tjy-analysis{color:#222;background:#fff;font:13px/1.4 'Microsoft YaHei','SimSun',sans-serif}
.tjy-analysis-scroll{overflow:auto;max-width:100%;padding-bottom:12px}
.tjy-analysis table{border-collapse:collapse;table-layout:fixed;border:2px solid #333;margin:0;background:#fff;font-size:12px;line-height:1.4}
.tjy-analysis td,.tjy-analysis th{border:1px solid #777;padding:5px 4px;vertical-align:middle;white-space:pre-line;overflow-wrap:anywhere;box-sizing:border-box;font-weight:400;color:#222}
.tjy-analysis th,.tjy-analysis .category{text-align:center;border-color:#333}
.tjy-analysis .heading{font-weight:600;background:#f7f7f5;color:#111;text-align:center}
.tjy-analysis .quantity{text-align:right;font-variant-numeric:tabular-nums}
.tjy-analysis .unavailable{text-align:center;color:#6b6b6b;font-size:11px}
.tjy-analysis .note{text-align:left;line-height:1.7;padding:12px;vertical-align:top}
.tjy-analysis .food{text-align:left}.tjy-analysis .metric{font-size:11px}.tjy-analysis tr{height:32px}
.tjy-analysis-title{font-size:20px;text-align:center;color:#222;margin:8px 0}
.tjy-analysis-subtitle{text-align:center;margin:0 0 12px;font-size:12px;color:#555}
@media print{.tjy-analysis-scroll{overflow:visible}.tjy-analysis table{width:100%!important;zoom:1!important;font-size:8px}.tjy-analysis td,.tjy-analysis th{padding:2px;font-size:8px!important}.tjy-analysis tr{break-inside:avoid}.tjy-analysis .note{padding:5px}.tjy-analysis col{width:auto!important}}
"""


def render_sheet(data, result=None):
    sheet = make_sheet(data, result)
    out = [f'<style>{CSS}</style><section class="tjy-analysis" aria-label="食谱带量分析">',
           '<h2 class="tjy-analysis-title">食谱带量分析</h2>',
           '<p class="tjy-analysis-subtitle">' + escape(data["dates"][0] + " 至 " + data["dates"][-1]) + ' · 每名幼儿日均计划毛重</p>',
           '<div class="tjy-analysis-scroll" tabindex="0" role="region" aria-label="食谱带量分析横向表，可左右滚动">',
           f'<table width="{sum(WIDTHS)}" aria-label="食材带量与营养分析"><colgroup>']
    out.extend(f'<col width="{width}">' for width in WIDTHS)
    out.append('</colgroup><tbody>')
    current = -1
    for cell in sheet["cells"]:
        if cell["row"] != current:
            if current >= 0:
                out.append('</tr>')
            current = cell["row"]
            out.append('<tr>')
        tag = "th" if cell["kind"] == "heading" else "td"
        out.append(f'<{tag} rowspan="{cell["rowspan"]}" colspan="{cell["colspan"]}" class="{cell["kind"]}" title="{escape(cell["title"], quote=True)}">{escape(str(cell["value"]))}</{tag}>')
    out.append('</tr></tbody></table></div></section>')
    return ''.join(out)
