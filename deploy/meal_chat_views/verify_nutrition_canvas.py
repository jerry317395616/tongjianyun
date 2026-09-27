"""Compare the canvas with the original nutrition service in a READ ONLY session.

No export, File creation, population freeze, task/model, migration or native save.
"""
import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--day', default='2026-09-24')
    parser.add_argument('--unit-tests', action='store_true')
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    if source not in (Path('/home/zyd/frappe/native-bench/apps/tongjianyun'),
                      Path('/home/zyd/frappe/remote-workspace/nutrition-canvas-production-20260927'),
                      Path('/home/zyd/frappe/remote-workspace/nutrition-excel-production-20260927')):
        raise RuntimeError('Unexpected source')
    sys.path.insert(0, str(source))
    import frappe
    from tongjianyun.meal_views import get_view
    from tongjianyun.nutrition_canvas_sheet import NUTRIENT_ROWS, project_report_bytes
    from tongjianyun.recipe_analysis import build_report_xlsx
    from tongjianyun.nutrition_sheet import get_nutrition_sheet
    sites = Path('/home/zyd/frappe/native-bench/sites')
    frappe.init(site='child.myyr.top', sites_path=str(sites))
    frappe.connect()
    try:
        frappe.db.sql('SET SESSION TRANSACTION READ ONLY')
        assert frappe.db.sql('SELECT @@session.tx_read_only')[0][0] == 1
        frappe.flags.read_only = True
        frappe.set_user('Administrator')
        if args.unit_tests:
            import unittest
            result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames([
                'tongjianyun.tests.test_meal_nutrition_view', 'tongjianyun.tests.test_frappe_project_views',
                'tongjianyun.tests.test_meal_views', 'tongjianyun.tests.test_nutrition_canvas_sheet']))
            if not result.wasSuccessful():
                raise RuntimeError('Production-baseline canvas regression failed')
        doctypes = ['Tongjianyun Recipe', 'Tongjianyun Recipe Dish', 'Tongjianyun Recipe Ingredient', 'File']
        counts = {name: frappe.db.count(name) for name in doctypes}
        view = get_view({'view': 'frappe_page', 'page': 'weekly-recipe-nutrition-sheet', 'day': args.day})
        assert view['selection']['view'] == 'recipe_nutrition'
        assert not any(block['type'] == 'frappe_frame' for block in view['components'])
        recipe = view['selection'].get('recipe')
        assert recipe and view['summary']['analysis_ready'], 'No unique amount-bearing recipe for comparison'
        before = frappe.get_doc('Tongjianyun Recipe', recipe).as_dict()
        original = get_nutrition_sheet(recipe=recipe)
        sheet = next(block for block in view['components'] if block['type'] == 'nutrition_sheet')
        cells = {cell['ref']: cell for row in sheet['rows'] for cell in row['cells']}
        original_sheet = project_report_bytes(build_report_xlsx(original['analysis']))
        expected_cells = {cell['ref']: cell for row in original_sheet['rows'] for cell in row['cells']}
        for ref, cell in cells.items():
            if ref not in {'P12', 'P16', 'P17', 'P23', 'N19'}:
                assert cell == expected_cells[ref], ref
        for key, row in NUTRIENT_ROWS.items():
            evaluation = original['analysis']['nutrient_evaluations'].get(key)
            if evaluation and evaluation.get('garden_target', 0) > 0:
                assert cells[f'T{row}']['value'] == round(evaluation['actual'], 2)
                assert cells[f'V{row}']['value'] == evaluation['status']
        assert all(block['collapsed'] for block in view['components'] if block['type'] == 'table')
        assert counts == {name: frappe.db.count(name) for name in doctypes}
        assert before == frappe.get_doc('Tongjianyun Recipe', recipe).as_dict()
        print(json.dumps({'original_page_replaced': True, 'original_values_match': True,
                          'nutrient_rows': len(NUTRIENT_ROWS), 'excel_layout_matches': True,
                          'record_counts_unchanged': True, 'recipe_unchanged': True,
                          'recipe': recipe, 'source': str(source)}, ensure_ascii=False))
    finally:
        frappe.db.rollback()
        frappe.destroy()


if __name__ == '__main__':
    main()
