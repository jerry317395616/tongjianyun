import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import frappe
from tongjianyun import frappe_project_views as project
from tongjianyun import meal_views, meal_chat


class FrappeProjectTests(unittest.TestCase):
    def setUp(self):
        for target in ('can_manage_projects', 'can_use_admin_chat'):
            manager = patch('tongjianyun.scene_access.' + target, return_value=True)
            manager.start()
            self.addCleanup(manager.stop)

    def select(self, **kwargs):
        return meal_views.selection({'view': 'frappe_catalog', **kwargs}, '2026-09-25', 'lunch')

    def test_no_arbitrary_url_sql_or_cross_site_in_selection(self):
        with patch.object(frappe, 'throw', side_effect=ValueError):
            for args in ({'url': 'https://evil'}, {'site': 'other'}, {'sql': 'select *'},
                         {'kind': 'html'}, {'view': 'frappe_doctype'}, {'offset': -1},
                         {'view': 'frappe_document', 'doctype': 'Student'}, {'components': ['frappe_frame']}):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    self.select(**args)
            with self.assertRaises(ValueError):
                meal_views.selection({'view': 'students', 'doctype': 'User'})

    def test_native_choice_keeps_verified_business_names(self):
        result = self.select(view='frappe_document', doctype='Sales Invoice', document='INV/0001')
        self.assertEqual(result['document'], 'INV/0001')
        self.assertEqual(result['doctype'], 'Sales Invoice')
        self.assertNotIn('url', result)

    def test_doctype_requires_installed_module_nonchild_and_read_access(self):
        meta = SimpleNamespace(module='Accounts', istable=0)
        with patch.object(frappe, 'get_meta', return_value=meta), patch.object(frappe, 'has_permission', return_value=False):
            with self.assertRaises(frappe.PermissionError):
                project._doctype('Sales Invoice', {'Accounts': 'erpnext'})
        with patch.object(frappe, 'get_meta', return_value=meta), patch.object(frappe, 'has_permission', return_value=True):
            with self.assertRaises(frappe.PermissionError):
                project._doctype('Sales Invoice', {})
            meta.istable = 1
            with self.assertRaises(frappe.PermissionError):
                project._doctype('Sales Invoice Item', {'Accounts': 'erpnext'})

    def test_native_document_checks_record_permission_and_never_returns_values(self):
        meta = SimpleNamespace(name='Sales Invoice', module='Accounts')
        record = MagicMock()
        record.name = 'INV/0001'
        choice = self.select(view='frappe_document', doctype='Sales Invoice', document='INV/0001')
        with patch.object(project, 'module_apps', return_value={'Accounts': 'erpnext'}), \
             patch.object(project, '_doctype', return_value=meta), patch.object(frappe, 'get_doc', return_value=record), \
             patch.object(project, 'operation_capabilities', return_value={'operations': []}), \
             patch.object(frappe, '_', side_effect=lambda s, **kw: s), patch.object(frappe, 'local', SimpleNamespace(site='test')):
            result = project.native_view(choice)
        record.check_permission.assert_called_once_with('read')
        self.assertEqual(result['components'][1]['route'], '/desk/sales-invoice/INV%2F0001')
        self.assertEqual(set(result['components'][1]), {'type', 'title', 'route'})
        self.assertNotIn('amount', str(result))

    def test_ordinary_stock_document_does_not_offer_admin_reconciliation(self):
        for doctype in ('Purchase Receipt', 'Stock Entry'):
            meta = SimpleNamespace(name=doctype, module='Stock')
            record = MagicMock()
            record.name = 'EXACT-SOURCE'
            choice = self.select(view='frappe_document', doctype=doctype, document=record.name)
            with self.subTest(doctype=doctype), patch.object(project, 'module_apps', return_value={'Stock': 'erpnext'}), \
                 patch.object(project, '_doctype', return_value=meta), patch.object(frappe, 'get_doc', return_value=record), \
                 patch.object(project, 'operation_capabilities', return_value={'operations': []}), \
                 patch.object(frappe, '_', side_effect=lambda value, **kw: value), \
                 patch.object(frappe, 'local', SimpleNamespace(site='test')), \
                 patch('tongjianyun.scene_access.can_use_admin_chat', return_value=False) as allowed:
                result = project.native_view(choice)
                self.assertNotIn('stock_reconciliation', str(result['actions']))
                allowed.return_value = True
                self.assertEqual(project.native_view(choice)['actions'][-1]['selection']['view'], 'stock_reconciliation')

    def test_new_route_checks_create_and_never_creates_a_record(self):
        meta = SimpleNamespace(name='Purchase Order', module='Buying', issingle=0, is_submittable=1)
        choice = self.select(view='frappe_new', doctype='Purchase Order')
        with patch.object(project, 'module_apps', return_value={'Buying': 'erpnext'}), \
             patch.object(project, '_doctype', return_value=meta), \
             patch.object(project, 'operation_capabilities', return_value={'operations': []}), \
             patch.object(frappe, 'has_permission', return_value=True) as permission, \
             patch.object(frappe, 'get_doc') as get_doc, \
             patch.object(frappe, '_', side_effect=lambda s, **kw: s), \
             patch.object(frappe, 'local', SimpleNamespace(site='test')):
            result = project.native_view(choice)
            permission.assert_called_once_with('Purchase Order', 'create')
            get_doc.assert_not_called()
            self.assertEqual(result['components'][1]['route'], '/desk/purchase-order/new')
            permission.return_value = False
            with self.assertRaises(frappe.PermissionError):
                project.native_view(choice)

    def test_new_route_rejects_single_recipe_and_extra_document(self):
        with patch.object(frappe, 'throw', side_effect=ValueError):
            for doctype, single in [('Company Settings', 1), ('Tongjianyun Recipe', 0)]:
                meta = SimpleNamespace(name=doctype, module='Test', issingle=single)
                with patch.object(project, 'module_apps', return_value={'Test': 'test'}), \
                     patch.object(project, '_doctype', return_value=meta):
                    with self.subTest(doctype=doctype), self.assertRaises(ValueError):
                        project.native_view(self.select(view='frappe_new', doctype=doctype))
            for extra in ({'document': 'existing'}, {'values': {'title': 'unsafe'}}, {'site': 'other'}):
                with self.subTest(extra=extra), self.assertRaises(ValueError):
                    self.select(view='frappe_new', doctype='Purchase Order', **extra)

    def test_capabilities_keep_state_permissions_and_final_validation_separate(self):
        meta = SimpleNamespace(name='Purchase Order', issingle=0, is_submittable=1, fields=[])
        record = SimpleNamespace(docstatus=1, secret='never in response')
        no_workflow = {'configured': False, 'actions': [], 'reason': '未启用审批工作流。'}
        with patch.object(project, '_workflow_capability', return_value=no_workflow), \
             patch.object(frappe, 'has_permission', side_effect=lambda dt, p, **kw: p != 'delete'):
            data = project.operation_capabilities(meta, record)
            rows = {row['key']: row for row in data['operations']}
            self.assertFalse(rows['write']['available'])
            self.assertFalse(rows['submit']['available'])
            self.assertTrue(rows['cancel']['available'])
            self.assertFalse(rows['delete']['permission'])
            self.assertFalse(rows['amend']['available'])
            self.assertTrue(data['final_validation_required'])
            self.assertNotIn('secret', str(data))
            record.docstatus = 2
            rows = {row['key']: row for row in project.operation_capabilities(meta, record)['operations']}
            self.assertTrue(rows['amend']['available'])
            self.assertFalse(rows['write']['available'])
            self.assertFalse(rows['cancel']['available'])

    def test_entry_capabilities_do_not_claim_record_actions_are_executable(self):
        meta = SimpleNamespace(name='Purchase Order', issingle=0, is_submittable=1, fields=[])
        with patch.object(project, '_workflow_capability', return_value={'configured': False, 'actions': [], 'reason': 'none'}), \
             patch.object(frappe, 'has_permission', return_value=True):
            result = project.operation_capabilities(meta)
        self.assertEqual(result['scope'], 'entry')
        rows = {row['key']: row for row in result['operations']}
        self.assertTrue(rows['create']['available'])
        self.assertTrue(rows['submit']['supported'])
        self.assertTrue(rows['submit']['permission'])
        self.assertTrue(rows['submit']['requires_record'])
        self.assertFalse(rows['submit']['available'])

    def test_workflow_disables_direct_submit_and_returns_only_action_names(self):
        meta = SimpleNamespace(name='Purchase Order', issingle=0, is_submittable=1, fields=[])
        record = SimpleNamespace(docstatus=0)
        with patch.object(project, '_workflow_capability', return_value={'configured': True, 'actions': ['Approve'], 'reason': 'checked'}), \
             patch.object(frappe, 'has_permission', return_value=True):
            result = project.operation_capabilities(meta, record)
        rows = {row['key']: row for row in result['operations']}
        self.assertFalse(rows['submit']['supported'])
        self.assertFalse(rows['cancel']['available'])
        self.assertTrue(rows['workflow']['available'])
        self.assertEqual(result['workflow_actions'], ['Approve'])

    def test_native_actions_keep_recipe_identity_and_deny_generic_new(self):
        meta = SimpleNamespace(name='Tongjianyun Recipe', module='Tongjianyun', issingle=0)
        record = MagicMock()
        record.name = 'ORIGINAL-WEEK'
        with patch.object(project, 'module_apps', return_value={'Tongjianyun': 'tongjianyun'}), \
             patch.object(project, '_doctype', return_value=meta), \
             patch.object(project, 'operation_capabilities', return_value={'operations': [{'key': 'write', 'available': True}]}):
            self.assertEqual(project.native_actions(meta.name, {}), [])
            result = project.native_actions(meta.name, {}, record)
        self.assertEqual(result[0]['selection'], {'view': 'frappe_document', 'doctype': meta.name, 'document': 'ORIGINAL-WEEK'})
        record.check_permission.assert_called_once_with('read')

    def test_list_actions_only_offer_new_for_create_permission(self):
        meta = SimpleNamespace(name='Supplier', module='Buying', issingle=0)
        context = {'day': '2026-09-25', 'meal': 'lunch'}
        with patch.object(project, 'module_apps', return_value={'Buying': 'erpnext'}), \
             patch.object(project, '_doctype', return_value=meta), \
             patch.object(frappe, 'has_permission', return_value=True) as permission:
            actions = project.native_actions(meta.name, context)
            self.assertEqual([row['selection']['view'] for row in actions], ['frappe_doctype', 'frappe_new'])
            self.assertEqual(actions[1]['selection']['day'], context['day'])
            permission.return_value = False
            actions = project.native_actions(meta.name, context)
            self.assertEqual([row['selection']['view'] for row in actions], ['frappe_doctype'])
        with patch.object(project, 'module_apps', return_value={}), \
             patch.object(project, '_doctype', side_effect=frappe.PermissionError):
            self.assertEqual(project.native_actions(meta.name, context), [])

    def test_inventory_distinguishes_native_coverage_from_scenario_acceptance(self):
        entries = [{'kind': 'doctype', 'name': 'Student', 'module': 'Education', 'title': '学生'},
                   {'kind': 'report', 'name': 'Enrollment', 'module': 'Education', 'title': '注册报表'}]
        with patch.object(project, 'module_apps', return_value={'Education': 'education'}), \
             patch.object(project, 'catalog_entries', return_value=entries), patch.object(project, '_doctype'), \
             patch.object(project, 'operation_capabilities', return_value={'operations': []}), \
             patch.object(frappe, 'get_installed_apps', return_value=['education']), \
             patch.object(frappe, 'local', SimpleNamespace(site='test')):
            result = project.capability_inventory()
        self.assertEqual(result['entry_count'], 2)
        self.assertTrue(all(row['integration'] == 'native_in_scene' for row in result['entries']))
        self.assertTrue(all(row['scenario_tested'] is False for row in result['entries']))

    def test_denied_report_cannot_be_opened(self):
        doc = MagicMock(disabled=0, module='Accounts')
        doc.is_permitted.return_value = False
        with patch.object(frappe, 'get_doc', return_value=doc):
            with self.assertRaises(frappe.PermissionError):
                project._report('Secret report', {'Accounts': 'erpnext'})

    def test_project_scan_is_bounded_and_never_reads_config_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'app' / '.git').mkdir(parents=True)
            (root / 'config').mkdir()
            (root / 'native-bench' / 'apps' / 'erpnext').mkdir(parents=True)
            rows = project.project_directories(root)
        self.assertTrue(any(r['name'] == 'erpnext' and r['kind'] == 'Frappe 应用源码' for r in rows))
        self.assertEqual(next(r for r in rows if r['name'] == 'app')['status'], 'Git 项目')

    def test_project_listing_rechecks_management_before_reading_paths(self):
        with patch('tongjianyun.scene_access.require_project_access', side_effect=frappe.PermissionError), \
             patch.object(project, 'project_directories') as scan:
            with self.assertRaises(frappe.PermissionError):
                project.projects_view({'view': 'project_catalog'})
        scan.assert_not_called()

    def test_business_catalog_does_not_offer_project_paths_to_nonmanager(self):
        with patch('tongjianyun.scene_access.can_manage_projects', return_value=False), \
             patch('tongjianyun.scene_access.can_use_admin_chat', return_value=False), \
             patch.object(project, 'module_apps', return_value={}), \
             patch.object(project, 'catalog_entries', return_value=[]), \
             patch.object(frappe, 'get_installed_apps', return_value=[]), \
             patch.object(frappe, 'local', SimpleNamespace(site='test')):
            result = project.catalog_view(self.select())
        self.assertNotIn('project_catalog', str(result))
        self.assertNotIn('/home/', str(result))

    def test_ordinary_catalog_queries_only_audited_doctype_kind(self):
        with patch('tongjianyun.scene_access.can_use_admin_chat', return_value=False), \
             patch.object(frappe, 'get_all', return_value=[]) as query, \
             patch.object(project, '_workspaces') as workspaces:
            self.assertEqual(project.catalog_entries({}, {}), [])
            self.assertEqual([call.args[0] for call in query.call_args_list], ['DocType'])
            workspaces.assert_not_called()
            for kind in ('report', 'page', 'workspace'):
                with self.subTest(kind=kind), self.assertRaises(frappe.PermissionError):
                    project.catalog_entries({'kind': kind}, {})

    def test_catalog_summary_describes_only_the_displayed_level(self):
        entry = {'kind': 'doctype', 'name': 'Asset', 'title': 'Asset', 'module': 'Assets', 'note': 'native'}
        with patch.object(project, 'module_apps', return_value={'Assets': 'erpnext'}), \
             patch.object(project, 'catalog_entries', return_value=[entry]), \
             patch.object(frappe, 'get_installed_apps', return_value=['erpnext']), \
             patch.object(frappe, '_', side_effect=lambda s, **kw: s), \
             patch.object(frappe, 'local', SimpleNamespace(site='test')):
            overview = project.catalog_view(self.select())['summary']
            modules = project.catalog_view(self.select(app='erpnext'))['summary']
            details = project.catalog_view(self.select(module='Assets'))['summary']
        self.assertEqual(overview['displayed_apps'], ['erpnext'])
        self.assertNotIn('page_entries', overview)
        self.assertEqual(modules['displayed_modules'], ['Assets'])
        self.assertNotIn('page_entries', modules)
        self.assertEqual(details['page_entries'][0]['name'], 'Asset')

    def test_fresh_and_resumed_codex_use_project_root_with_separate_session_key(self):
        cache = MagicMock()
        with patch.object(frappe, 'cache', return_value=cache), patch.object(frappe, 'session', SimpleNamespace(user='U')), \
             patch.object(frappe, 'local', SimpleNamespace(site='test')):
            cache.get_value.return_value = None
            fresh = meal_chat._command(None)
            cache.get_value.return_value = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
            resumed = meal_chat._command(None)
            self.assertIn('frappe-wide-v1', meal_chat._cache_key())
        for command in (fresh, resumed):
            self.assertEqual(command[:3], [meal_chat.CODEX, '-C', '/home/zyd/frappe'])
            self.assertIn('--skip-git-repo-check', command)
        self.assertIn('resume', resumed)
        self.assertNotIn('resume', fresh)


def verify_project_views():
    frappe.set_user('Administrator')
    modules = project.module_apps()
    entries = project.catalog_entries({}, modules)
    failures = []
    counts = {kind: 0 for kind in project.KINDS}
    for entry in entries:
        try:
            result = meal_views.get_view(project.entry_selection(entry['kind'], entry['name'], {'day': '2026-09-25', 'meal': 'lunch'}))
            frame = next(c for c in result['components'] if c['type'] == 'frappe_frame')
            assert frame['route'].startswith('/desk/') and '?' not in frame['route']
            counts[entry['kind']] += 1
        except Exception as error:
            failures.append({'kind': entry['kind'], 'name': entry['name'], 'error': str(error)[:160]})
    for app in frappe.get_installed_apps():
        meal_views.get_view({'view': 'frappe_catalog', 'app': app, 'day': '2026-09-25'})
    projects = meal_views.get_view({'view': 'project_catalog', 'day': '2026-09-25'})
    frappe.set_user('Guest')
    try:
        meal_views.get_view({'view': 'frappe_catalog', 'day': '2026-09-25'})
        raise AssertionError('Guest allowed')
    except frappe.PermissionError:
        pass
    return {'apps': list(set(modules.values())), 'modules': len(modules), 'entries': counts,
            'route_failures': failures, 'project_directories': len(projects['summary']['projects']), 'guest_denied': True}
