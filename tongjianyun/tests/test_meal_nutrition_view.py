import unittest
from unittest.mock import patch

import frappe
from tongjianyun import meal_views as views
from tongjianyun import meal_nutrition_view as nutrition


def selection(**kwargs):
    return views.selection({'view': 'recipe_nutrition', 'day': '2026-09-24', **kwargs})


def sheet():
    return {'recipe': {'name': 'R1', 'title': '本周食谱', 'week_start': '2026-09-21', 'week_end': '2026-09-25'},
            'analysis': {'standard': {'profile': '自动计算', 'source': '原标准',
                                     'population': {'student_count': 12, 'warnings': ['排除1名超出年龄范围学生']}},
                         'nutrients': {'energy': 1096.54, 'protein': 45.18, 'calcium': 375.07},
                         'nutrient_evaluations': {'energy': {'actual': 1096.54, 'full_target': 1291.63,
                                                   'garden_target': 1033.31, 'percent': 106.12, 'status': '适宜'}},
                         'conclusion': '原服务结论', 'day_count': 5,
                         'ingredients': [{'name': '<script>食材</script>', 'category': 'fine_grain', 'grams': 20}],
                         'category_totals': {'fine_grain': 20}}}


class NutritionViewTests(unittest.TestCase):
    def test_selection_defaults_and_task_day(self):
        choice = views.selection({'view': 'recipe_nutrition'}, '2026-09-24', 'morning_snack')
        self.assertEqual(choice['day'], '2026-09-24')
        self.assertEqual(choice['meal'], 'morning_snack')
        self.assertEqual(choice['standard_mode'], nutrition.AUTO_MODE)
        self.assertEqual(choice['garden_ratio'], 80)

    def test_invalid_filters_are_rejected(self):
        with patch.object(frappe, 'throw', side_effect=ValueError):
            for change in ({'garden_ratio': 0}, {'garden_ratio': 'nan'}, {'garden_ratio': 101},
                           {'garden_ratio': 'bad'}, {'standard_mode': 'guess'}, {'recipe': ''},
                           {'recipe': ['R1']}, {'student_groups': ['']}, {'student_groups': 'G1'},
                           {'age_group': '3岁'}, {'gender': 'unknown'}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    selection(**change)
            with self.assertRaises(ValueError):
                views.selection({'view': 'students', 'recipe': 'R1'})

    def test_no_matching_recipe_does_not_fall_back_to_latest_or_zero(self):
        with patch.object(nutrition, 'visible_rows', return_value={'available': True, 'rows': [], 'has_more': False}) as query, \
             patch.object(nutrition, 'get_nutrition_sheet') as calculate:
            result = nutrition.nutrition_view(selection())
        calculate.assert_not_called()
        self.assertFalse(result['summary']['available'])
        self.assertEqual([c['type'] for c in result['components']], ['notice'])
        self.assertEqual(query.call_args.args[2]['week_end'], ['>=', '2026-09-24'])

    def test_multiple_recipes_require_selection_and_keep_filters(self):
        rows = [{'name': name, 'title': name, 'week_start': '2026-09-21', 'week_end': '2026-09-25',
                 'workflow_status': '草稿'} for name in ('R1', 'R2')]
        with patch.object(nutrition, 'visible_rows', return_value={'available': True, 'rows': rows, 'has_more': False}), \
             patch.object(nutrition, 'get_nutrition_sheet') as calculate:
            result = nutrition.nutrition_view(selection(garden_ratio=90))
        calculate.assert_not_called()
        self.assertEqual(result['components'][1]['rows'][1]['action']['selection']['recipe'], 'R2')
        self.assertEqual(result['components'][1]['rows'][1]['action']['selection']['garden_ratio'], 90)

    def test_unique_recipe_reuses_original_service_and_pins_result(self):
        choice = selection()
        with patch.object(nutrition, 'visible_rows', return_value={'available': True, 'rows': [{'name': 'R1'}], 'has_more': False}), \
             patch.object(nutrition, 'get_recipe') as check_rows, \
             patch.object(nutrition, 'read_doc', return_value=frappe._dict(workflow_status='草稿')), \
             patch.object(nutrition, 'get_nutrition_sheet', return_value=sheet()) as calculate:
            result = nutrition.nutrition_view(choice)
        check_rows.assert_called_once_with('R1')
        self.assertEqual(calculate.call_args.kwargs['standard_mode'], nutrition.AUTO_MODE)
        self.assertNotIn('freeze', calculate.call_args.kwargs)
        self.assertEqual(choice['recipe'], 'R1')
        self.assertTrue(result['summary']['available'])

    def test_explicit_recipe_does_not_use_latest_query(self):
        with patch.object(nutrition, 'visible_rows') as query, patch.object(nutrition, 'get_recipe'), \
             patch.object(nutrition, 'read_doc', return_value=frappe._dict(workflow_status='草稿')), \
             patch.object(nutrition, 'get_nutrition_sheet', return_value=sheet()) as calculate:
            nutrition.nutrition_view(selection(recipe='R1', standard_mode=nutrition.MANUAL_MODE, age_group='5岁'))
        query.assert_not_called()
        self.assertEqual(calculate.call_args.kwargs['age_group'], '5岁')
        self.assertEqual(calculate.call_args.kwargs['standard_mode'], nutrition.MANUAL_MODE)

    def test_recipe_row_permission_failure_stops_analysis(self):
        with patch.object(nutrition, 'get_recipe', side_effect=frappe.PermissionError), \
             patch.object(nutrition, 'get_nutrition_sheet') as calculate:
            with self.assertRaises(frappe.PermissionError):
                nutrition.nutrition_view(selection(recipe='SECRET'))
        calculate.assert_not_called()

    def test_inaccessible_group_not_silently_dropped(self):
        with patch.object(nutrition, 'get_recipe'), patch.object(nutrition, 'read_doc'), \
             patch.object(frappe, 'get_list', return_value=['G1']), patch.object(nutrition, 'get_nutrition_sheet') as calculate:
            with self.assertRaises(frappe.PermissionError):
                nutrition.nutrition_view(selection(recipe='R1', student_groups=['G1', 'SECRET']))
        calculate.assert_not_called()

    def test_population_failure_does_not_fall_back_to_manual(self):
        with patch.object(nutrition, 'get_recipe'), patch.object(nutrition, 'read_doc'), \
             patch.object(nutrition, 'get_nutrition_sheet', side_effect=frappe.ValidationError('档案缺失')) as calculate:
            with self.assertRaises(frappe.ValidationError):
                nutrition.nutrition_view(selection(recipe='R1'))
        self.assertEqual(calculate.call_count, 1)

    def test_projection_preserves_values_evaluation_warnings_and_missing_data(self):
        result = nutrition.project_sheet(sheet(), selection(recipe='R1'), '草稿')
        rows = next(c for c in result['components'] if c.get('title') == '营养素对照 · 日均每生')['rows']
        self.assertEqual(rows[0]['cells'], ['热量（kcal）', 1291.63, 1033.31, 1096.54, '106.1%', '适宜'])
        self.assertIsNone(rows[1]['cells'][1])
        self.assertEqual(rows[1]['cells'][-1], '未评价')
        self.assertIn('草稿', result['components'][0]['text'])
        self.assertIn('排除1名', result['components'][0]['text'])
        self.assertLessEqual(len(result['components']), 12)
        self.assertNotIn('population', result['summary'])

    def test_get_view_routes_and_retains_required_warnings(self):
        with patch('tongjianyun.meal_chat.require_chat_access'), \
             patch.object(views, 'now_datetime', return_value='2026-09-25'), \
             patch.object(nutrition, 'nutrition_view', return_value=nutrition.project_sheet(sheet(), selection(), '草稿')):
            result = views.get_view({**selection(), 'components': ['stats']})
        self.assertIn('notice', [c['type'] for c in result['components']])
        self.assertEqual(result['selection']['view'], 'recipe_nutrition')


def verify_live_nutrition_view():
    """Bench-only: compare original and canvas without saving business records."""
    frappe.set_user('Administrator')
    doctypes = ['Tongjianyun Recipe', 'Tongjianyun Recipe Dish', 'Tongjianyun Recipe Ingredient', 'File']
    before = {dt: frappe.db.count(dt) for dt in doctypes}
    result = views.get_view({'view': 'recipe_nutrition', 'day': '2026-09-24'})
    recipe = result['selection']['recipe']
    doc_before = frappe.get_doc('Tongjianyun Recipe', recipe).as_dict()
    original = nutrition.get_nutrition_sheet(recipe=recipe)
    rows = next(c['rows'] for c in result['components'] if c.get('title') == '营养素对照 · 日均每生')
    for (key, _, _), row in zip(nutrition.NUTRIENTS, rows):
        expected = original['analysis']['nutrient_evaluations'][key]
        assert row['cells'][3] == round(expected['actual'], 2)
        assert row['cells'][5] == expected['status']
    assert before == {dt: frappe.db.count(dt) for dt in doctypes}
    assert doc_before == frappe.get_doc('Tongjianyun Recipe', recipe).as_dict()
    return {'selection': result['selection'], 'nutrient_count': len(rows), 'original_values_match': True,
            'record_counts_unchanged': True, 'summary': result['summary']}
