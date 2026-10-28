"""Render transient model results; never calculate nutritional quantities."""
from io import BytesIO
from math import ceil

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from tongjianyun.ai_nutrition import NUTRIENTS, display_range, grouped_foods, validate_result


def workbook_bytes(data, result):
    validate_result(result, data)
    wb = Workbook()
    ws = wb.active
    ws.title = "食谱带量分析"
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "B5"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = "1:4"
    border = Side(style="thin", color="A9BCB1")

    def put(row, col, value, header=False):
        cell = ws.cell(row, col, value)
        if isinstance(value, str):
            cell.data_type = "s"
        cell.font = Font(name="微软雅黑", size=10, color="183128", bold=header)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = Border(left=border, right=border, top=border, bottom=border)
        if header:
            cell.fill = PatternFill("solid", fgColor="E7F2EB")
        return cell

    for col in range(1, 17):
        ws.column_dimensions[get_column_letter(col)].width = 15
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["M"].width = 20
    ws.column_dimensions["P"].width = 30
    ws.column_dimensions["I"].width = 35
    ws.merge_cells("A1:P1")
    put(1, 1, "食谱带量分析（AI营养估算，仅供参考）", True).font = Font(name="微软雅黑", size=16, bold=True)
    ws.row_dimensions[1].height = 30
    ws.merge_cells("A2:P2")
    put(2, 1, data["dates"][0] + " 至 " + data["dates"][-1] + "；每名幼儿计划配方毛重，非实际摄入。")
    ws.merge_cells("A3:L3")
    put(3, 1, "每人每日平均计划带量（保留原单位；食物分类由大模型给出）", True)
    ws.merge_cells("M3:P3")
    put(3, 13, "五日日均营养区间（大模型直接计算）", True)
    put(4, 1, "食物分类", True)
    for col in range(2, 12, 2):
        put(4, col, "食材", True)
        put(4, col + 1, "人均日量", True)
    for col, label in enumerate(("营养素", "日均估算区间", "单位", "估算依据／缺项"), 13):
        put(4, col, label, True)
    row = 5
    for category, foods in grouped_foods(data, result).items():
        for offset in range(0, len(foods), 5):
            put(row, 1, category if offset == 0 else "")
            for index, food in enumerate(foods[offset:offset + 5]):
                put(row, 2 + index * 2, food["name"])
                put(row, 3 + index * 2, food["daily"] + " " + food["unit"])
            ws.row_dimensions[row].height = 36
            row += 1
    for index, nutrient in enumerate(result["nutrients"], 5):
        label, unit = NUTRIENTS[nutrient["key"]]
        for col, value in enumerate((label, display_range(nutrient["average"]), unit, nutrient["basis"]), 13):
            put(index, col, value)
        ws.row_dimensions[index].height = max(48, ceil(len(nutrient["basis"]) / 14) * 15)
    row = max(row, 5 + len(result["nutrients"])) + 1
    notes = ["资料来源：模型通用营养知识，未联网检索或核验；不使用系统内置营养代表值。",
             "营养计算、单位换算及营养汇总由大模型完成；系统仅校验格式和排版，不保证算术或估算准确，也不作达标判断。",
             "结果不写入ERP、营养资料库或长期聊天记录；服务仅在内存临时保留，过期清除。下载文件由使用者自行保管。",
             *["主要假设：" + text for text in result["assumptions"]], *["缺项：" + text for text in result["missing"]]]
    for text in notes:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=16)
        put(row, 1, text)
        ws.row_dimensions[row].height = 36
        row += 1
    for col, value in enumerate(("营养素", "单位", *data["dates"], "五日日均", "估算依据／缺项"), 1):
        put(row, col, value, True)
    row += 1
    for nutrient in result["nutrients"]:
        label, unit = NUTRIENTS[nutrient["key"]]
        for col, value in enumerate((label, unit, *map(display_range, nutrient["daily"]), display_range(nutrient["average"]), nutrient["basis"]), 1):
            put(row, col, value)
        ws.row_dimensions[row].height = max(48, ceil(len(nutrient["basis"]) / 16) * 15)
        row += 1
    ws.print_area = f"A1:P{row - 1}"
    output = BytesIO()
    wb.save(output)
    return output.getvalue()
