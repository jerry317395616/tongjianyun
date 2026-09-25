import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import frappe
from tongjianyun import frappe_project_views as project
from tongjianyun import meal_views, meal_chat


class FrappeProjectTests(unittest.TestCase):
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
             patch.object(frappe, '_', side_effect=lambda s, **kw: s), patch.object(frappe, 'local', SimpleNamespace(site='test')):
            result = project.native_view(choice)
        record.check_permission.assert_called_once_with('read')
        self.assertEqual(result['components'][1]['route'], '/desk/sales-invoice/INV%2F0001')
        self.assertEqual(set(result['components'][1]), {'type', 'title', 'route'})
        self.assertNotIn('amount', str(result))

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
