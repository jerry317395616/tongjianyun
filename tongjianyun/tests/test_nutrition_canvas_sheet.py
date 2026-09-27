"""Pure report projection tests; no database, export endpoint or attachments."""
from copy import deepcopy
from importlib.resources import files
from io import BytesIO
import unittest
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from tongjianyun.recipe_analysis import analyze_recipe_payload, build_report_xlsx
from tongjianyun.nutrition_canvas_sheet import NUTRIENT_ROWS, NS, project_report_bytes, spreadsheet_component


def synthetic_analysis():
    return analyze_recipe_payload({'recipe': {'title': '合成食谱 · 仅用于布局验证', 'weekStart': '2026-09-21', 'weekEnd': '2026-09-25'},
        'days': [{'portions': [{'slot': 'lunch', 'dishIngredientRows': [
            {'ingredient': name, 'gramsPerChild': grams, 'unit': 'g'} for name, grams in
            [('大米', 80), ('小米', 20), ('面粉', 30), ('牛奶', 150), ('鸡蛋', 35), ('猪肉', 25),
             ('鱼', 20), ('胡萝卜', 40), ('青菜', 50), ('苹果', 100), ('豆腐', 35), ('食用油', 8)]]}]}]}, person_days=257)


def indexed(block):
    return {cell['ref']: cell for row in block['rows'] for cell in row['cells']}


class NutritionCanvasSheetTests(unittest.TestCase):
    def test_exact_template_merges_coverage_and_no_stale_example_values(self):
        analysis = synthetic_analysis()
        block = spreadsheet_component(analysis, analysis['nutrient_evaluations'], True)
        cells = indexed(block)
        original = indexed(project_report_bytes(build_report_xlsx(analysis)))
        semantic_corrections = {'P12', 'P16', 'P17', 'P23', 'N19'}
        for ref, cell in cells.items():
            if ref not in semantic_corrections:
                self.assertEqual(cell, original[ref], ref)
        with ZipFile(BytesIO(files('tongjianyun').joinpath('templates/食谱带量分析元素.xlsx').read_bytes())) as archive:
            template = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        self.assertEqual(sum(c['rowspan'] > 1 or c['colspan'] > 1 for c in cells.values()), len(template.findall('s:mergeCells/s:mergeCell', NS)))
        covered = set()
        for row in block['rows']:
            for cell in row['cells']:
                for r in range(row['number'], row['number'] + cell['rowspan']):
                    for col in range(cell['column'], cell['column'] + cell['colspan']):
                        self.assertNotIn((r, col), covered)
                        covered.add((r, col))
        self.assertEqual(len(covered), 36 * 21)
        self.assertEqual(len(block['columns']), 21)
        self.assertEqual(cells['N4']['value'], 257)
        self.assertGreater(cells['T4']['value'], 0)
        self.assertEqual(cells['P23']['value'], '硒（μg）')
        self.assertEqual(cells['B4']['rowspan'], 8)
        self.assertNotIn('79种', cells['D2']['value'])

    def test_overflow_keeps_every_ingredient_and_amount(self):
        analysis = synthetic_analysis()
        analysis['ingredients'] = [{'name': f'食材{i:02}', 'category': 'fine_grain', 'grams': i + 1} for i in range(22)]
        cells = indexed(spreadsheet_component(analysis, analysis['nutrient_evaluations'], True))
        self.assertEqual(cells['L6']['value'], '\n'.join(f'食材{i:02}' for i in range(14, 22)))
        self.assertEqual(cells['M6']['value'], '\n'.join(str(i + 1) for i in range(14, 22)))

    def test_unknown_amounts_are_masked_without_mutating_analysis(self):
        analysis = synthetic_analysis()
        analysis['ingredients'][0]['grams'] = None
        before = deepcopy(analysis)
        assessed = {key: {**value, 'actual': None, 'percent': None, 'status': '未评价'} for key, value in analysis['nutrient_evaluations'].items()}
        cells = indexed(spreadsheet_component(analysis, assessed, False))
        self.assertEqual(before, analysis)
        self.assertEqual(cells['B4']['value'], '粮食类\n—')
        self.assertEqual(cells['T4']['value'], '—')
        self.assertEqual(cells['V4']['value'], '未评价')
        self.assertEqual(cells['O12']['value'], '—')
        self.assertEqual(cells['O19']['value'], '—')
        self.assertIn('不代表实际摄入为零', cells['P32']['value'])


if __name__ == '__main__':
    unittest.main()
