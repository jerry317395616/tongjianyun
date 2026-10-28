"""In-memory Excel export of the same cells shown on the report page."""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from tongjianyun.ai_nutrition import NUTRIENTS, display_range
from tongjianyun.nutrition_layout import make_sheet


def workbook_bytes(data, result):
    sheet = make_sheet(data, result)
    wb = Workbook()
    ws = wb.active
    ws.title = "食谱带量分析"
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "D4"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = "1:3"
    thin = Side(style="thin", color="777777")
    ws.column_dimensions["A"].width = 2
    for col, width in enumerate(sheet["widths"], 2):
        ws.column_dimensions[get_column_letter(col)].width = width / 7
    for row in range(2, sheet["rows"] + 2):
        ws.row_dimensions[row].height = 28
    ws.row_dimensions[3].height = 42
    for item in sheet["cells"]:
        row, col = item["row"] + 2, item["col"] + 2
        cell = ws.cell(row, col, item["value"])
        # Food names beginning with = remain text, never Excel formulas.
        cell.data_type = "s"
        cell.font = Font(name="微软雅黑", size=9, color="666666" if item["kind"] == "unavailable" else "222222", bold=item["kind"] == "heading")
        cell.alignment = Alignment(horizontal="right" if item["kind"] == "quantity" else "left" if item["kind"] in ("food", "note") else "center",
                                   vertical="top" if item["kind"] == "note" else "center", wrap_text=True)
        cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        if item["kind"] == "heading":
            cell.fill = PatternFill("solid", fgColor="F7F7F5")
        if item["rowspan"] > 1 or item["colspan"] > 1:
            ws.merge_cells(start_row=row, start_column=col, end_row=row + item["rowspan"] - 1, end_column=col + item["colspan"] - 1)
    ws.print_area = f"B2:V{sheet['rows'] + 1}"
    detail = wb.create_sheet("每日营养与依据")
    detail.sheet_view.showGridLines = False
    rows = [["营养素", "单位", *data["dates"], "五日日均", "估算依据／缺项"]]
    for nutrient in result["nutrients"]:
        label, unit = NUTRIENTS[nutrient["key"]]
        rows.append([label, unit, *map(display_range, nutrient["daily"]), display_range(nutrient["average"]), nutrient["basis"]])
    rows += [["主要假设", text] for text in result["assumptions"]]
    rows += [["缺项", text] for text in result["missing"]]
    for row in rows:
        detail.append(row)
    for row in detail:
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = "s"
            cell.font = Font(name="微软雅黑", size=10)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for col in range(1, 10):
        detail.column_dimensions[get_column_letter(col)].width = 22 if col < 9 else 80
    for row in range(2, len(rows) + 1):
        detail.row_dimensions[row].height = 60
    detail.freeze_panes = "C2"
    output = BytesIO()
    wb.save(output)
    return output.getvalue()
