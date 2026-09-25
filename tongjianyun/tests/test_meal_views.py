import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from tongjianyun import meal_views as views


class MealViewsTests(unittest.TestCase):
    def test_selection_rejects_unregistered_code_or_fields(self):
        with patch.object(frappe, 'throw', side_effect=ValueError):
            for value in ({'view': 'html'}, {'view': 'students', 'sql': 'select *'},
                          {'view': 'students', 'presentation': 'script'}, [], 'not json'):
                with self.assertRaises(ValueError):
                    views.selection(value)

    def test_date_defaults_are_bound_to_task_not_model_guess(self):
        self.assertEqual(views.selection({'view': 'meal_counts'}, '2026-09-22', 'morning_snack'),
                         {'view': 'meal_counts', 'day': '2026-09-22', 'meal': 'morning_snack'})

    def test_component_selection_is_bounded_and_view_specific(self):
        self.assertEqual(views.selection({'view': 'students', 'components': ['stats', 'bars', 'table']})['components'],
                         ['stats', 'bars', 'table'])
        with patch.object(frappe, 'throw', side_effect=ValueError):
            for blocks in (['html'], ['bars', 'bars'], [], ['notice'], ['table', {}]):
                with self.assertRaises(ValueError):
                    views.selection({'view': 'students', 'components': blocks})
            with self.assertRaises(ValueError):
                views.selection({'view': 'meal_counts', 'components': ['bars']})

    def test_component_order_follows_selection_but_warnings_remain(self):
        data = {'components': [{'type': 'stats'}, {'type': 'notice', 'warning': True},
                               {'type': 'table'}, {'type': 'bars'}]}
        with patch('tongjianyun.meal_chat.require_chat_access'), \
             patch.object(views, 'now_datetime', return_value='2026-09-25 02:30:00'), \
             patch.object(views, 'students_view', return_value=data):
            result = views.get_view({'view': 'students', 'components': ['bars', 'table', 'stats']})
        self.assertEqual([c['type'] for c in result['components']], ['bars', 'table', 'stats', 'notice'])

    def test_roster_total_is_unique_and_membership_counts_do_not_include_hidden_students(self):
        facts = views.roster_facts(['S1', 'S2', 'S3'], [
            ({'name': 'G1'}, ['S1', 'S1', 'SECRET']), ({'name': 'G2'}, ['S1', 'S2'])])
        self.assertEqual(facts['total'], 3)
        self.assertEqual([r['count'] for r in facts['groups']], [1, 2])
        self.assertEqual(facts['unassigned'], 1)
        self.assertEqual(facts['overlap'], 1)

    def test_get_view_checks_web_actor_before_reading(self):
        with patch('tongjianyun.meal_chat.require_chat_access', side_effect=frappe.PermissionError), \
             patch.object(views, 'students_view') as query:
            with self.assertRaises(frappe.PermissionError):
                views.get_view({'view': 'students'})
        query.assert_not_called()

    def test_class_details_reject_out_of_scope_class(self):
        with patch.object(views, '_groups', return_value=[]), \
             patch.object(frappe, 'throw', side_effect=ValueError), patch.object(views, '_scope') as scope:
            with self.assertRaises(ValueError):
                views.class_students_view({'view': 'class_students', 'group': 'SECRET', 'offset': 0})
        scope.assert_not_called()

    def test_class_tool_summary_never_sends_names_to_model(self):
        group = frappe._dict(name='G1', student_group_name='一班')
        roster = [{'student': f'S{i}', 'student_name': f'Private name {i}'} for i in range(51)]
        with patch.object(views, '_groups', return_value=[group]), patch.object(views, '_scope'), \
             patch.object(views, '_roster', return_value=roster):
            result = views.class_students_view({'view': 'class_students', 'group': '一班', 'offset': 0})
        self.assertNotIn('Private', str(result['summary']))
        self.assertEqual(len(result['components'][1]['rows']), 50)
        self.assertEqual(result['actions'][-1]['selection']['offset'], 50)

    def test_unconfirmed_meals_remain_unknown(self):
        result = {'available': True, 'rows': [{'group': 'G1', 'label': '一班', 'expected': None, 'actual': None,
                    'confirmed': False, 'has_plan': False}],
                  'summary': {'visible_groups': 1, 'confirmed_groups': 0, 'actual': None, 'confirmed_subtotal': None}}
        with patch.object(views, 'class_plans', return_value=result):
            data = views.meal_counts_view({'day': '2026-09-22', 'meal': 'lunch'})
        self.assertIsNone(data['components'][0]['items'][0]['value'])
        self.assertFalse(data['summary']['final'])
        self.assertIn('实际用餐人数未知', data['summary']['answer'])
        self.assertTrue(data['components'][1]['warning'])

    def test_meal_selection_keeps_group_for_in_scene_confirmation(self):
        result = views.selection({'view': 'meal_counts', 'group': 'G1'}, '2026-09-22', 'lunch')
        self.assertEqual(result['group'], 'G1')
        self.assertEqual(result['meal'], 'lunch')

    def test_meal_register_is_scoped_unknown_and_does_not_prefill_actual_from_expected(self):
        group = frappe._dict(name='G1', student_group_name='一班')
        data = {'revision': '', 'record': {'students': [{'student': 'S1', 'student_name': 'Private child',
                'lunch': '未确认', 'lunch_expected': 1}]}, 'meals': {'lunch': {
                'expected': 1, 'actual': None, 'complete': False, 'status': '未确认'}}}
        with patch.object(views, '_groups', return_value=[group]), \
             patch('tongjianyun.classroom.get_meals', return_value=data) as read, \
             patch('tongjianyun.classroom._capabilities', return_value={'meals_write': True, 'future': False}):
            result = views.meal_register_view({'view': 'meal_counts', 'group': '一班', 'day': '2026-09-22', 'meal': 'lunch'})
        component = result['components'][1]
        self.assertEqual(component['rows'][0]['value'], '未确认')
        self.assertTrue(component['rows'][0]['expected'])
        self.assertFalse(component['confirmed'])
        self.assertIsNone(component['facts']['actual'])
        self.assertNotIn('Private', str(result['summary']))
        read.assert_called_once_with('G1', '2026-09-22')

    def test_meal_register_rejects_foreign_group_before_roster_read(self):
        with patch.object(views, '_groups', return_value=[]), patch.object(frappe, 'throw', side_effect=ValueError), \
             patch('tongjianyun.classroom.get_meals') as read:
            with self.assertRaises(ValueError):
                views.meal_register_view({'view': 'meal_counts', 'group': 'secret'})
        read.assert_not_called()

    def test_publisher_uses_task_owner_and_only_emits_descriptor(self):
        from tongjianyun import meal_chat
        store = MagicMock()
        store.read.return_value = {'owner': 'actual-owner', 'status': 'running', 'day': '2026-09-22',
                                   'meal': 'lunch', 'cancel_requested': '0'}
        payload = {'title': '学生', 'selection': {'view': 'students'}, 'summary': {'student_count': 3},
                   'components': [{'rows': ['private data']} ]}
        with patch.object(meal_chat, 'TaskStore', return_value=store), \
             patch.object(frappe, 'session', SimpleNamespace(user='Administrator')), \
             patch.object(frappe, 'set_user') as set_user, patch.object(views, 'get_view', return_value=payload):
            result = views.publish_for_task('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', {'view': 'students'})
        self.assertEqual(set_user.call_args_list[0].args, ('actual-owner',))
        self.assertEqual(set_user.call_args_list[-1].args, ('Administrator',))
        self.assertNotIn('private', str(store.emit.call_args))
        self.assertTrue(result['display_requested'])
        self.assertNotIn('displayed', result)

    def test_cancelled_task_cannot_publish(self):
        from tongjianyun import meal_chat
        store = MagicMock()
        store.read.return_value = {'status': 'running', 'cancel_requested': '1'}
        with patch.object(meal_chat, 'TaskStore', return_value=store):
            with self.assertRaises(ValueError):
                views.publish_for_task('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', {'view': 'students'})
        store.emit.assert_not_called()


def verify_read_only_views():
    """Bench-only production read check; returns aggregates, never student names."""
    frappe.set_user('Administrator')
    doctypes = ['Student', 'Student Group', 'Tongjianyun Class Meal Confirmation', 'Tongjianyun Recipe']
    before = {dt: frappe.db.count(dt) for dt in doctypes}
    result = views.get_view({'view': 'students'})
    counts = result['summary']
    combined = views.get_view({'view': 'students', 'components': ['stats', 'bars', 'table']})
    assert [c['type'] for c in combined['components'] if c['type'] != 'notice'] == ['stats', 'bars', 'table']
    class_result = None
    if counts['groups']:
        detail = views.get_view({'view': 'class_students', 'group': counts['groups'][0]['group']})
        class_result = {'count': detail['summary']['student_count'], 'components': [c['type'] for c in detail['components']]}
    meals = views.get_view({'view': 'meal_counts', 'day': '2026-09-22', 'meal': 'morning_snack'})
    calendar = views.get_view({'view': 'recipe_week', 'day': '2026-09-22', 'meal': 'morning_snack'})
    assert before == {dt: frappe.db.count(dt) for dt in doctypes}
    return {'students': counts, 'class_view': class_result, 'meals': meals['summary'],
            'combined_components': [c['type'] for c in combined['components']],
            'calendar': calendar['selection'], 'record_counts_unchanged': True}
