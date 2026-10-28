"""Deterministic, read-only weekly per-child gross-quantity report."""

from collections import defaultdict
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from tongjianyun.analysis_engine import analyze
from tongjianyun.nutrition_reference import NUTRIENT_UNITS

CATEGORY_LABELS = {
    "fine_grain": "细粮",
    "coarse_grain": "杂粮",
    "pastry": "糕点",
    "dry_bean": "豆类",
    "soy": "豆制品",
    "non_green_veg": "其他蔬菜",
    "green_veg": "绿叶及其他蔬菜",
    "fruit": "水果",
    "dairy": "乳类",
    "egg": "蛋类",
    "meat": "肉类",
    "liver": "肝类",
    "fish": "鱼虾类",
    "sugar": "糖类",
    "oil": "油脂",
    "water": "水",
    "unclassified": "未分类（待核对）",
}
NUTRIENT_LABELS = {
    "energy": "能量",
    "protein": "蛋白质",
    "fat": "脂肪",
    "carbohydrate": "碳水化合物",
    "calcium": "钙",
    "vitamin_a": "维生素A",
    "vitamin_b1": "维生素B1",
    "vitamin_b2": "维生素B2",
    "vitamin_c": "维生素C",
    "vitamin_e": "维生素E",
    "niacin": "烟酸",
    "potassium": "钾",
    "magnesium": "镁",
    "iron": "铁",
    "zinc": "锌",
    "phosphorus": "磷",
    "selenium": "硒",
    "carotene": "胡萝卜素",
    "fiber": "膳食纤维",
    "cholesterol": "胆固醇",
}
NOTES = (
    "食材为每名幼儿计划毛重；日均量＝一周人均带量÷编排天数，保留原单位。",
    "营养数值仅是分类代表值对已覆盖食材的部分粗估；毛重可食部及烹调损耗未逐项核实。",
    "体积缺少密度时不换成重量；成品和未知分类不自动匹配。未知营养值不是零，不作达标判断。",
    "计划配方并非实际摄入；供餐人数及实际人日数未在本报表推算。",
)


def build_sheet_data(details, dates, source):
    """Keep item and unit identity; expose partial estimates and exact coverage."""
    summary = analyze(details, dates)
    buckets = defaultdict(list)
    for row in summary["foods"]:
        category = (
            row["category"] if row["category"] in CATEGORY_LABELS else "unclassified"
        )
        buckets[category].append(
            {
                "code": row["code"],
                "name": row["name"],
                "unit": row["uom"],
                "weekly": format(Decimal(row["quantity"]), "f"),
                "daily": format(Decimal(row["daily_quantity"]), "f"),
                "basis": row["basis"],
            }
        )
    groups = [
        {
            "category": CATEGORY_LABELS[category],
            "items": sorted(
                buckets[category], key=lambda x: (x["name"], x["code"], x["unit"])
            ),
        }
        for category in CATEGORY_LABELS
        if buckets[category]
    ]
    nutrients = [
        {
            "label": NUTRIENT_LABELS[key],
            "unit": NUTRIENT_UNITS[key],
            "amount": summary["nutrients"][key],
            "covered_rows": summary["coverage"][key],
            "total_rows": summary["line_count"],
        }
        for key in NUTRIENT_LABELS
    ]
    return {
        "source": dict(source),
        "dates": list(map(str, dates)),
        "day_count": summary["day_count"],
        "food_count": summary["food_count"],
        "line_count": summary["line_count"],
        "covered_rows": summary["used_rows"],
        "groups": groups,
        "nutrients": nutrients,
        "missing": [
            {**row, "quantity": format(Decimal(row["quantity"]), "f")}
            for row in summary["missing"]
        ],
        "notes": list(NOTES),
    }


def workbook_bytes(data):
    """One landscape report, with every source ingredient and missing-data row."""
    wb = Workbook()
    ws = wb.active
    ws.title = "食谱带量分析"
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.freeze_panes = "B5"
    ws.print_title_rows = "1:4"
    for col in range(1, 17):
        ws.column_dimensions[get_column_letter(col)].width = (
            15 if col in (1, 13, 14) else 13
        )
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["M"].width = 19
    ws.column_dimensions["N"].width = 13
    ws.column_dimensions["O"].width = 11
    ws.column_dimensions["P"].width = 13
    ink = "183128"
    pale = "E7F2EB"
    border = Side(style="thin", color="A9BCB1")

    def put(row, col, value, bold=False, fill=None):
        cell = ws.cell(row, col, value)
        if isinstance(value, str):
            cell.data_type = "s"  # Never execute source text as a formula.
        cell.font = Font(name="微软雅黑", size=10, color=ink, bold=bold)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = Border(left=border, right=border, top=border, bottom=border)
        if fill:
            cell.fill = PatternFill("solid", fgColor=fill)
        return cell

    ws.merge_cells("A1:P1")
    put(1, 1, "食谱带量分析（计划毛重与部分营养粗估）", True, "D7EBDD").font = Font(
        name="微软雅黑", size=16, bold=True, color=ink
    )
    ws.row_dimensions[1].height = 30
    ws.merge_cells("A2:P2")
    put(
        2,
        1,
        f"{data['dates'][0]} 至 {data['dates'][-1]}　编排 {data['day_count']} 天　食材 {data['food_count']} 种　原始明细 {data['line_count']} 条",
        True,
    )
    ws.merge_cells("A3:L3")
    put(3, 1, "每人每日平均计划毛重（食材及原单位）", True, pale)
    ws.merge_cells("M3:P3")
    put(3, 13, "营养分析：分类代表值的已覆盖部分粗估", True, pale)
    put(4, 1, "食物分类", True, pale)
    for i in range(5):
        put(4, 2 + i * 2, "食材", True, pale)
        put(4, 3 + i * 2, "人均日量", True, pale)
    put(4, 12, "")
    put(4, 13, "营养素", True, pale)
    put(4, 14, "部分粗估", True, pale)
    put(4, 15, "单位", True, pale)
    put(4, 16, "覆盖条数", True, pale)
    row = 5
    for group in data["groups"]:
        items = group["items"]
        for offset in range(0, len(items), 5):
            put(row, 1, group["category"] if offset == 0 else "")
            for index, item in enumerate(items[offset : offset + 5]):
                put(row, 2 + index * 2, item["name"])
                display_unit = {"Millilitre": "ml", "Gram": "g", "Kilogram": "kg"}.get(
                    item["unit"], item["unit"]
                )
                if display_unit in {"ml", "L", "g", "kg", "mg", "克", "千克", "毫升"}:
                    cell = put(row, 3 + index * 2, float(Decimal(item["daily"])))
                    cell.number_format = f'0.00####" {display_unit}"'
                else:
                    put(
                        row,
                        3 + index * 2,
                        f"{Decimal(item['daily']).normalize():f} {display_unit}",
                    )
                if len(item["name"]) > 9:
                    ws.row_dimensions[row].height = 30
            row += 1
    for index, nutrient in enumerate(data["nutrients"], start=5):
        put(index, 13, nutrient["label"])
        amount = nutrient["amount"]
        cell = put(index, 14, amount if amount is not None else "待补资料")
        if amount is not None:
            cell.number_format = "0.00"
        put(index, 15, nutrient["unit"])
        put(index, 16, f"{nutrient['covered_rows']}/{nutrient['total_rows']}")
    end = max(row, 5 + len(data["nutrients"])) + 1
    for note in data["notes"]:
        ws.merge_cells(start_row=end, start_column=1, end_row=end, end_column=16)
        put(end, 1, note)
        ws.row_dimensions[end].height = 24
        end += 1
    ws.merge_cells(start_row=end, start_column=1, end_row=end, end_column=16)
    put(
        end,
        1,
        f"待补资料：{len(data['missing'])} 条（逐条列出，不以零代替）",
        True,
        pale,
    )
    end += 1
    for item in data["missing"]:
        ws.merge_cells(start_row=end, start_column=1, end_row=end, end_column=16)
        put(
            end,
            1,
            f"{item['date']}　{item['meal_type']}　{item['name']}　{item['quantity']} {item['uom']}　{item['reason']}",
        )
        end += 1
    ws.print_area = f"A1:P{end - 1}"
    out = BytesIO()
    wb.save(out)
    return out.getvalue()
