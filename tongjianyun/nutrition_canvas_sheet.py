"""Bounded, text-only projection of our own Excel report, not an uploaded workbook.

The existing report builder supplies all calculations and the bundled template
supplies geometry/borders. No File, snapshot, spreadsheet execution or write.
"""
from copy import deepcopy
from io import BytesIO
from math import isfinite
import re
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from tongjianyun.recipe_analysis import build_report_xlsx, CATEGORY_LABEL_CELLS, SUBCATEGORY_LABEL_CELLS

NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
NUTRIENT_ROWS = dict(zip(
    ('energy', 'protein', 'calcium', 'vitamin_a', 'vitamin_b1', 'vitamin_b2', 'vitamin_c',
     'vitamin_e', 'niacin', 'potassium', 'magnesium', 'iron', 'zinc', 'phosphorus', 'selenium'),
    (4, 8, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23)))


def coordinate(ref):
    match = re.fullmatch(r'([A-Z]+)(\d+)', ref)
    if not match:
        raise ValueError('Invalid report cell')
    column = 0
    for letter in match[1]:
        column = column * 26 + ord(letter) - 64
    return int(match[2]), column


def project_report_bytes(content):
    """Only called with server-generated reports. Never accept user workbook bytes."""
    with ZipFile(BytesIO(content)) as archive:
        root = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        styles = ET.fromstring(archive.read('xl/styles.xml'))
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared = [''.join(si.itertext()) for si in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
    borders = list(styles.find('s:borders', NS))
    formats = list(styles.find('s:cellXfs', NS))
    cells = {coordinate(c.get('r')): c for c in root.findall('s:sheetData/s:row/s:c', NS)}
    merges, covered = {}, set()
    for merge in root.findall('s:mergeCells/s:mergeCell', NS):
        start, end = map(coordinate, merge.get('ref').split(':'))
        if not (2 <= start[0] <= end[0] <= 37 and 2 <= start[1] <= end[1] <= 22):
            raise ValueError('Unexpected report merge')
        merges[start] = end
        covered.update((r, c) for r in range(start[0], end[0] + 1) for c in range(start[1], end[1] + 1) if (r, c) != start)

    def border_at(position, side):
        cell = cells.get(position)
        if cell is None:
            return False
        border = borders[int(formats[int(cell.get('s', 0))].get('borderId', 0))]
        edge = border.find('s:' + side, NS)
        return edge is not None and edge.get('style') not in (None, 'none')

    rows = []
    for r in range(2, 38):
        row = {'number': r, 'cells': []}
        for col in range(2, 23):
            if (r, col) in covered:
                continue
            cell = cells.get((r, col))
            if cell is None or cell.find('s:f', NS) is not None:
                raise ValueError('Unexpected missing/formula report cell')
            end_r, end_c = merges.get((r, col), (r, col))
            raw = cell.find('s:v', NS)
            value = raw.text if raw is not None else ''
            if cell.get('t') == 's':
                value = shared[int(value)]
            elif cell.get('t') == 'inlineStr':
                value = ''.join(cell.find('s:is', NS).itertext())
            elif raw is not None:
                value = float(value)
                if not isfinite(value):
                    raise ValueError('Nonfinite report value')
                value = int(value) if value.is_integer() else value
            edges = ''
            for side, code, positions in (
                ('top', 't', ((r, c) for c in range(col, end_c + 1))),
                ('bottom', 'b', ((end_r, c) for c in range(col, end_c + 1))),
                ('left', 'l', ((i, col) for i in range(r, end_r + 1))),
                ('right', 'r', ((i, end_c) for i in range(r, end_r + 1))),
            ):
                if any(border_at(pos, side) for pos in positions):
                    edges += code
            row['cells'].append({'ref': cell.get('r'), 'column': col, 'value': value,
                                 'rowspan': end_r - r + 1, 'colspan': end_c - col + 1,
                                 'borders': edges})
        rows.append(row)
    # Preserve template column proportions, enlarged for readable browser text.
    columns = [70] * 21
    for col in root.findall('s:cols/s:col', NS):
        for index in range(max(2, int(col.get('min'))), min(22, int(col.get('max'))) + 1):
            columns[index - 2] = round((float(col.get('width')) * 7 + 5) * 1.30)
    return {'type': 'nutrition_sheet', 'layout': 'weekly-nutrition-excel-v1', 'columns': columns, 'rows': rows}


def spreadsheet_component(analysis, assessed, has_amounts):
    safe = deepcopy(analysis)
    # The original builder cannot format None/NaN amounts. Internal placeholders
    # are always masked below; they are never displayed as measured zero.
    if not has_amounts:
        for item in safe['ingredients']:
            item['grams'] = 0
    block = project_report_bytes(build_report_xlsx(safe))
    cells = {cell['ref']: cell for row in block['rows'] for cell in row['cells']}
    # Keep the template's format, correcting its historical unit/label typos.
    for ref, label in {'P12': '维生素A（μg RAE）', 'P16': '维生素E（mg α-TE）',
                       'P17': '烟酸（mg NE）', 'P23': '硒（μg）', 'N19': '实给比例'}.items():
        cells[ref]['value'] = label
    for key, row in NUTRIENT_ROWS.items():
        evaluation = assessed[key]
        for col, field in (('R', 'full_target'), ('S', 'garden_target'), ('T', 'actual')):
            value = evaluation.get(field)
            cells[f'{col}{row}']['value'] = round(float(value), 2) if value is not None and isfinite(float(value)) else '—'
        value = evaluation.get('percent')
        cells[f'U{row}']['value'] = f'{value:.1f}'.rstrip('0').rstrip('.') + '%' if value is not None and isfinite(float(value)) else '—'
        cells[f'V{row}']['value'] = evaluation['status']
    if not has_amounts:
        for ref in list(CATEGORY_LABEL_CELLS.values()) + [ref for ref, _ in SUBCATEGORY_LABEL_CELLS.values()]:
            cells[ref]['value'] = str(cells[ref]['value']).split('\n')[0] + '\n—'
        for row in range(4, 38):
            for col in 'EGIKM':
                cells[f'{col}{row}']['value'] = '—' if cells[f'{chr(ord(col)-1)}{row}']['value'] else ''
        for row in (5, 6, 7, 9, 10):
            for col in 'RSTU':
                cells[f'{col}{row}']['value'] = '—'
            cells[f'V{row}']['value'] = '未评价'
        for row in range(12, 17):
            cells[f'O{row}']['value'] = '—'
        cells['O19']['value'] = '—'
        for ref, label in (('N20', '胡萝卜素（μg）'), ('N22', '纤维（g）'), ('N24', '胆固醇（mg）')):
            cells[ref]['value'] = label + '：—'
        cells['P32']['value'] = '食材用量缺失或不完整，暂不能评价营养。未填写不代表实际摄入为零；请补齐用量后重新分析。'
    return block
