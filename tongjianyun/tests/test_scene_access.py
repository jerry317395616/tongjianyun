"""Unified shell access cannot grant root chat, schema changes or business scope."""
import unittest
from contextlib import ExitStack
from unittest.mock import patch, MagicMock

import frappe
from tongjianyun import scene_access as access, meal_views, meal_chat, meal_scene
from tongjianyun.www import tongjianyun_meal_scene as page


class SceneAccessTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.account = frappe._dict(enabled=1, user_type='System User')
        self.readable = {'Student', 'Student Group', 'Student Attendance', 'Student Leave Application', meal_scene.CLASS_MEAL}
        self.stack.enter_context(patch.object(frappe, 'session', frappe._dict(user='teacher')))
        self.stack.enter_context(patch.object(frappe.db, 'get_value', side_effect=self.user_value))
        self.stack.enter_context(patch.object(frappe.db, 'exists', return_value=True))
        self.stack.enter_context(patch.object(frappe, 'has_permission', side_effect=lambda dt, action='read', **kw: dt in self.readable))
        self.roles = self.stack.enter_context(patch.object(frappe, 'get_roles', return_value=['Instructor', 'Academics User']))
        self.groups = self.stack.enter_context(patch('tongjianyun.attendance_scope.allowed_groups', return_value=['G1']))
        self.private = self.stack.enter_context(patch.object(access, 'mark_private_response'))

    def user_value(self, doctype, name=None, fieldname=None, **kwargs):
        self.assertEqual(doctype, 'User')
        self.assertEqual(name, frappe.session.user)
        return self.account if isinstance(fieldname, list) else '当前教师'

    def bootstrap(self, **kwargs):
        return access.get_bootstrap(day='2026-09-22', meal='lunch', **kwargs)

    def test_enabled_teacher_enters_shell_without_food_or_root_permission(self):
        access.require_scene_account()
        self.private.assert_called_once()
        self.assertFalse(meal_scene.has_access())
        self.assertFalse(access.can_manage_projects())

    def test_guest_disabled_and_website_accounts_cannot_bootstrap_or_read_views(self):
        for user, enabled, user_type in [('Guest', 1, 'System User'), ('teacher', 0, 'System User'), ('parent', 1, 'Website User')]:
            self.account.update(enabled=enabled, user_type=user_type)
            with self.subTest(user=user, enabled=enabled), patch.object(frappe, 'session', frappe._dict(user=user)), \
                 patch.object(meal_views, 'students_view') as query:
                for call in (self.bootstrap, lambda: meal_views.get_view({'view': 'students'})):
                    with self.assertRaises(frappe.PermissionError):
                        call()
                query.assert_not_called()

    def test_bootstrap_selects_own_class_and_does_not_claim_codex_enabled(self):
        result = self.bootstrap()
        self.assertEqual(result['default_view'], {'view': 'classroom_day', 'day': '2026-09-22', 'meal': 'lunch', 'group': 'G1'})
        self.assertEqual(result['scope'], {'group_count': 1, 'selected_group': 'G1'})
        self.assertFalse(result['recipe_calendar'])
        self.assertFalse(result['chat']['allowed'])
        self.assertEqual(result['chat']['mode'], 'unavailable')
        self.assertEqual(result['phase'], 'views_only_for_non_admin')
        self.assertNotIn('project_catalog', str(result))
        self.assertNotIn('/home/', str(result))

    def test_multiple_classes_do_not_arbitrarily_select_first(self):
        self.groups.return_value = ['G1', 'G2']
        result = self.bootstrap()
        self.assertIsNone(result['scope']['selected_group'])
        self.assertNotIn('group', result['default_view'])
        selected = self.bootstrap(group='G2')
        self.assertEqual(selected['default_view']['group'], 'G2')

    def test_foreign_group_and_nonstring_context_denied(self):
        for group in ('FOREIGN', '', ['G1'], 'x' * 141):
            with self.subTest(group=group), self.assertRaises(frappe.PermissionError):
                self.bootstrap(group=group)

    def test_no_assigned_class_does_not_fall_back_to_unrelated_class(self):
        self.groups.return_value = []
        result = self.bootstrap()
        self.assertEqual(result['scope'], {'group_count': 0, 'selected_group': None})
        self.assertEqual(result['default_view'], {'view': 'students'})
        self.assertNotIn('本班点名', str(result['navigation']))
        self.assertNotIn('核对用餐', str(result['navigation']))
        with self.assertRaises(frappe.PermissionError):
            self.bootstrap(group='G1')

    def test_without_student_read_does_not_enumerate_class_scope(self):
        self.readable.remove('Student')
        result = self.bootstrap()
        self.groups.assert_not_called()
        self.assertEqual(result['default_view']['view'], 'frappe_catalog')
        self.assertEqual(result['scope']['group_count'], 0)
        self.assertNotIn('G1', str(result))

    def test_missing_attendance_read_hides_attendance_but_not_existing_meal_service(self):
        self.readable.remove('Student Attendance')
        result = self.bootstrap()
        self.assertNotIn('classroom_day', str(result['navigation']))
        self.assertEqual(result['default_view']['view'], 'meal_counts')
        self.assertFalse(result['chat']['allowed'])

    def test_calendar_requires_recipe_not_merely_purchase_permission(self):
        self.readable.add('Purchase Order')
        self.assertTrue(meal_scene.has_access())
        self.assertFalse(self.bootstrap()['recipe_calendar'])
        with self.assertRaises(frappe.PermissionError):
            access.require_view_access('recipe_week')
        self.readable.add(meal_scene.RECIPE)
        result = self.bootstrap()
        self.assertTrue(result['recipe_calendar'])
        self.assertEqual(result['default_view']['view'], 'recipe_week')
        self.assertFalse(result['chat']['allowed'])

    def test_admin_bootstrap_preserves_existing_chat_and_calendar(self):
        self.roles.return_value = ['System Manager']
        self.readable.add(meal_scene.RECIPE)
        result = self.bootstrap()
        self.assertTrue(result['chat']['allowed'])
        self.assertEqual(result['chat']['mode'], 'admin_project')
        self.assertEqual(result['default_view']['view'], 'recipe_week')

    def test_teacher_business_chat_requires_verified_readiness_and_never_admin_mode(self):
        with patch('tongjianyun.business_agent_service.chat_access', return_value={'allowed':True,'can_submit':True,'reason':''}):
            result = self.bootstrap()
        self.assertTrue(result['chat']['allowed'])
        self.assertEqual(result['chat']['mode'], 'business')
        self.assertEqual(result['phase'], 'business_codex')
        self.assertFalse(access.can_use_admin_chat())

    def test_runtime_offline_keeps_business_history_and_stop_access(self):
        with patch('tongjianyun.business_agent_service.chat_access', return_value={'allowed':True,'can_submit':False,'reason':'后台不可用'}):
            result = self.bootstrap()
        self.assertEqual(result['chat']['mode'], 'business')
        self.assertTrue(result['chat']['allowed'])
        self.assertFalse(result['chat']['can_submit'])

    def test_admin_mode_does_not_probe_or_fall_back_to_business_runtime(self):
        self.roles.return_value = ['System Manager']
        self.readable.add(meal_scene.RECIPE)
        with patch('tongjianyun.business_agent_service.available', side_effect=AssertionError('unexpected probe')):
            self.assertEqual(self.bootstrap()['chat']['mode'], 'admin_project')

    def test_bootstrap_does_not_invent_chat_access_for_manager_without_meal_access(self):
        self.roles.return_value = ['System Manager']
        self.assertFalse(self.bootstrap()['chat']['allowed'])

    def test_each_audited_view_admission_is_separate_from_root_chat(self):
        with patch.object(meal_chat, 'require_chat_access') as admin:
            for view in access.BUSINESS_VIEWS:
                access.require_view_access(view)
        admin.assert_not_called()
        for view in ('project_catalog', 'stock_reconciliation', 'recipe_nutrition', 'business_blueprint', 'business_record',
                     'frappe_report', 'frappe_page', 'frappe_workspace'):
            with self.subTest(view=view), self.assertRaises(frappe.PermissionError):
                access.require_view_access(view)

    def test_teacher_can_read_audited_view_but_business_guard_still_runs(self):
        data = {'components': [], 'summary': {'student_count': 0}}
        with patch.object(meal_views, 'students_view', return_value=data) as query, \
             patch.object(meal_views, 'now_datetime', return_value='2026-09-25 00:00:00'):
            self.assertEqual(meal_views.get_view({'view': 'students'})['summary']['student_count'], 0)
            query.assert_called_once()
            query.side_effect = frappe.PermissionError
            with self.assertRaises(frappe.PermissionError):
                meal_views.get_view({'view': 'students'})

    def test_view_scope_rejects_cross_class_before_document_read(self):
        with patch.object(meal_views, '_groups', return_value=[]), patch.object(frappe, 'throw', side_effect=frappe.PermissionError), \
             patch.object(meal_views, '_scope') as read:
            with self.assertRaises(frappe.PermissionError):
                meal_views.get_view({'view': 'class_students', 'group': 'FOREIGN'})
        read.assert_not_called()

    def test_native_student_record_still_checks_exact_document_permission(self):
        from tongjianyun import frappe_project_views as project
        meta = frappe._dict(name='Student', module='Education', istable=0)
        record = MagicMock()
        record.check_permission.side_effect = frappe.PermissionError
        with patch.object(project, 'module_apps', return_value={'Education': 'education'}), \
             patch.object(frappe, 'get_meta', return_value=meta), patch.object(frappe, 'get_doc', return_value=record) as read:
            with self.assertRaises(frappe.PermissionError):
                meal_views.get_view({'view': 'frappe_document', 'doctype': 'Student', 'document': 'FOREIGN-STUDENT'})
        read.assert_called_once_with('Student', 'FOREIGN-STUDENT')
        record.check_permission.assert_called_once_with('read')

    def test_native_daily_summary_denied_before_loading_any_document(self):
        from tongjianyun import frappe_project_views as project
        meta = frappe._dict(name='Tongjianyun Daily Meal Confirmation', module='Tongjianyun', istable=0)
        with patch.object(project, 'module_apps', return_value={'Tongjianyun': 'tongjianyun'}), \
             patch.object(frappe, 'get_meta', return_value=meta), patch.object(frappe, 'get_doc') as read:
            for view in ('frappe_doctype', 'frappe_document', 'frappe_new'):
                choice = {'view': view, 'doctype': meta.name}
                if view == 'frappe_document':
                    choice['document'] = 'EXACT-DAILY-ID'
                with self.subTest(view=view), self.assertRaises(frappe.PermissionError):
                    meal_views.get_view(choice)
        read.assert_not_called()

    def test_bootstrap_is_read_only_and_accepts_no_actor_or_runner_override(self):
        with patch.object(frappe, 'get_doc') as doc, patch.object(frappe, 'enqueue') as enqueue:
            self.bootstrap()
        doc.assert_not_called()
        enqueue.assert_not_called()
        for value in ({'actor': 'Administrator'}, {'runner_mode': 'admin_project'}, {'site': 'other'}):
            with self.subTest(value=value), self.assertRaises(TypeError):
                self.bootstrap(**value)

    def test_chat_endpoints_still_deny_teacher_before_task_access(self):
        calls = (lambda: meal_chat.send_message(message='do admin work', stream=1),
                 meal_chat.get_conversation, lambda: meal_chat.stream_events('task'), lambda: meal_chat.cancel_task('task'))
        with patch.object(meal_chat, 'TaskStore') as store:
            for call in calls:
                with self.assertRaises(frappe.PermissionError):
                    call()
        store.assert_not_called()

    def test_private_blueprint_access_not_broadened_by_scene_entry(self):
        from tongjianyun import business_blueprints
        with patch.object(frappe, 'get_doc') as read:
            with self.assertRaises(frappe.PermissionError):
                business_blueprints.preview('private-admin-proposal')
        read.assert_not_called()

    def test_scene_page_uses_enabled_account_not_food_access(self):
        context = frappe._dict()
        with patch.object(page, 'mark_private_response'), patch.object(page, 'get_csrf_token', return_value='test-token'):
            page.get_context(context)
        self.assertEqual(context.csrf_token, 'test-token')
        self.assertEqual(context.no_cache, 1)

    def test_disabled_scene_page_rejected_before_csrf_token(self):
        self.account.enabled = 0
        with patch.object(page, 'mark_private_response'), patch.object(page, 'get_csrf_token') as csrf:
            with self.assertRaises(frappe.PermissionError):
                page.get_context(frappe._dict())
        csrf.assert_not_called()

    def test_client_view_cannot_supply_actor_site_or_html(self):
        with patch.object(frappe, 'throw', side_effect=ValueError):
            for value in ({'actor': 'Administrator'}, {'site': 'other'}, {'html': '<script>'}):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    meal_views.get_view({'view': 'students', **value})

    def test_teacher_classroom_pager_returns_only_accessible_catalog(self):
        from tongjianyun.business_views import pager
        choice = {'view': 'classroom_day', 'group': 'G1', 'day': '2026-09-22', 'meal': 'lunch', 'offset': 30}
        actions = pager(choice, True)
        self.assertEqual(actions[0], {'label': '可用业务', 'selection': {'view': 'frappe_catalog', 'day': choice['day'], 'meal': 'lunch'}})
        self.assertNotIn('business_catalog', str(actions))
        self.assertEqual(actions[1]['selection']['group'], 'G1')
        self.assertEqual(actions[1]['selection']['offset'], 0)
        self.assertEqual(actions[2]['selection']['offset'], 60)

    def test_admin_classroom_pager_retains_existing_catalog(self):
        from tongjianyun.business_views import pager
        self.roles.return_value = ['System Manager']
        self.readable.add(meal_scene.RECIPE)
        self.assertEqual(pager({'view': 'classroom_day', 'day': '2026-09-22', 'meal': 'lunch'}, False)[0]['selection']['view'], 'business_catalog')
