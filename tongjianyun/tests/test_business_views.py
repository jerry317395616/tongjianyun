import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import frappe
from tongjianyun import business_views as business
from tongjianyun import meal_views as views
from tongjianyun.business_view_registry import REGISTRY, DOMAINS


class BusinessViewsTests(unittest.TestCase):
    def select(self, **kwargs):
        return views.selection({'view': 'business_list', 'entity': 'purchase_orders', **kwargs}, '2026-09-24', 'lunch')

    def test_registry_excludes_sensitive_fields_and_system_tables(self):
        forbidden = {'Password', 'User', 'Role', 'DocType', 'Server Script', 'Bank Account'}
        sensitive = {'template_ciphertext', 'password', 'api_key', 'api_secret', 'id_number', 'bank_ac_no', 'medical_history', 'allergy_history', 'contact_phone'}
        self.assertGreaterEqual(len(REGISTRY), 50)
        self.assertEqual(set(e.domain for e in REGISTRY.values()), set(DOMAINS))
        for entry in REGISTRY.values():
            self.assertNotIn(entry.doctype, forbidden)
            self.assertFalse(sensitive & {c[0] for c in entry.columns})
            self.assertTrue(entry.columns)

    def test_selection_is_allowlisted_not_arbitrary_query(self):
        invalid = [dict(entity='User'), dict(sql='select *'), dict(period='forever'), dict(offset=-1),
                   dict(offset=1.5), dict(offset=True), dict(start_date='2026-01-01'),
                   dict(start_date='2026-09-25', end_date='2026-09-01'), dict(keyword=['x']),
                   dict(keyword='x\n<script>'), dict(entity='students'), dict(presentation='html')]
        with patch.object(frappe, 'throw', side_effect=ValueError):
            for item in invalid:
                with self.subTest(item=item), self.assertRaises(ValueError):
                    self.select(**item)
            with self.assertRaises(ValueError):
                views.selection({'view': 'students', 'entity': 'payments'})
            with self.assertRaises(ValueError):
                views.selection({'view': 'stock', 'record': 'private'})
            with self.assertRaises(ValueError):
                views.selection({'view': 'business_record', 'entity': 'purchase_orders'}, '2026-09-24')

    def test_defaults_and_period_bounds(self):
        choice = self.select()
        self.assertEqual(choice['day'], '2026-09-24')
        self.assertEqual(business.date_range(choice, REGISTRY['purchase_orders']), ('2026-09-21', '2026-09-27'))
        choice = self.select(entity='payments', day='2024-02-15')
        self.assertEqual(business.date_range(choice, REGISTRY['payments']), ('2024-02-01', '2024-02-29'))
        self.assertIsNone(business.date_range(self.select(period='all'), REGISTRY['purchase_orders']))
        choice = self.select(start_date='2026-01-01', end_date='2026-01-31')
        self.assertEqual(business.date_range(choice, REGISTRY['purchase_orders']), ('2026-01-01', '2026-01-31'))

    def test_interval_overlap_and_datetime_end_day(self):
        meta = MagicMock()
        meta.get_field.return_value.fieldtype = 'Date'
        with patch.object(business, 'scope_filters', return_value=[]), patch.object(frappe, 'get_meta', return_value=meta):
            filters, _ = business.query_filters(self.select(entity='student_leave'), REGISTRY['student_leave'], {'from_date', 'to_date'})
            self.assertIn(['from_date', '<=', '2026-09-27'], filters)
            self.assertIn(['to_date', '>=', '2026-09-21'], filters)
            meta.get_field.return_value.fieldtype = 'Datetime'
            filters, _ = business.query_filters(self.select(entity='staff_checkins'), REGISTRY['staff_checkins'], {'time'})
            self.assertIn(['time', '<', '2026-09-25 00:00:00'], filters)

    def test_hidden_filter_fields_cannot_be_used_for_inference(self):
        with patch.object(business, 'scope_filters', return_value=[]), patch.object(frappe, 'throw', side_effect=ValueError):
            with self.assertRaises(ValueError):
                business.query_filters(self.select(company='SECRET'), REGISTRY['purchase_orders'], set())
            with self.assertRaises(frappe.PermissionError):
                business.query_filters(self.select(), REGISTRY['purchase_orders'], set())

    def test_health_and_biometrics_keep_domain_gate(self):
        with patch.object(frappe, 'db', MagicMock()), patch.object(frappe, 'has_permission') as permission, \
             patch('tongjianyun.health_registration.access', side_effect=frappe.PermissionError):
            with self.assertRaises(frappe.PermissionError):
                business.guard(REGISTRY['health'])
            permission.assert_not_called()
        with patch.object(frappe, 'db', MagicMock()), \
             patch('tongjianyun.video_attendance.api.require_manager', side_effect=frappe.PermissionError):
            with self.assertRaises(frappe.PermissionError):
                business.guard(REGISTRY['face_profiles'])

    def test_record_requires_row_permission_before_get_doc(self):
        with patch.object(business, 'guard'), patch.object(business, 'visible_fields', return_value={'name'}), \
             patch.object(business, 'scope_filters', return_value=[]), patch.object(frappe, 'get_list', return_value=[]), \
             patch.object(frappe, 'get_doc') as get_doc:
            with self.assertRaises(frappe.PermissionError):
                business.record_view({'entity': 'payments', 'record': 'secret'})
            get_doc.assert_not_called()

    def test_page_count_not_financial_total_and_no_rows_in_model_summary(self):
        entry = REGISTRY['purchase_orders']
        rows = [frappe._dict(name=f'PO-{i}', supplier_name='Private Supplier', grand_total=123, currency='USD') for i in range(31)]
        meta = MagicMock(is_submittable=True)
        meta.get_field.return_value = SimpleNamespace(fieldtype='Data')
        fields = {c[0] for c in entry.columns} | {'docstatus'}
        with patch.object(business, 'guard'), patch.object(business, 'visible_fields', return_value=fields), \
             patch.object(business, 'native_actions', return_value=[]), \
             patch.object(business, 'query_filters', return_value=([], [])), patch.object(frappe, 'get_meta', return_value=meta), \
             patch.object(frappe, 'get_list', side_effect=[rows, [frappe._dict(total=40)]]):
            result = business.records_view(self.select())
        self.assertEqual(result['summary']['record_count'], 40)
        self.assertEqual(result['summary']['page_count'], 30)
        self.assertTrue(result['summary']['has_more'])
        self.assertNotIn('Private', str(result['summary']))
        self.assertNotIn('USD', str(result['summary']))
        self.assertEqual(next(a for a in result['actions'] if a['label'] == '下一页')['selection']['offset'], 30)
        self.assertEqual(len(result['components'][1]['rows']), 30)

    def test_null_check_is_not_false_and_nonfinite_is_unknown(self):
        meta = MagicMock()
        meta.get_field.return_value.fieldtype = 'Check'
        self.assertIsNone(business.cell(None, 'enabled', meta))
        self.assertEqual(business.cell(0, 'enabled', meta), '否')
        self.assertEqual(business.cell(1, 'enabled', meta), '是')
        meta.get_field.return_value.fieldtype = 'Float'
        self.assertIsNone(business.cell(float('nan'), 'qty', meta))
        self.assertEqual(business.cell(0, 'qty', meta), 0)

    def test_child_table_read_uses_parent_permission_not_sql_column_names(self):
        choice = self.select(view='business_record', record='PO1')
        parentmeta = MagicMock(is_submittable=True)
        parentmeta.get_field.side_effect = lambda field: SimpleNamespace(fieldtype='Table', permlevel=0, options='Purchase Order Item') if field == 'items' else SimpleNamespace(fieldtype='Data')
        childmeta = MagicMock()
        childmeta.has_field.return_value = False
        childmeta.get_field.return_value = SimpleNamespace(fieldtype='Data')
        doc = MagicMock(name='document')
        doc.name = 'PO1'
        doc.meta = parentmeta
        values = {'name': 'PO1', 'items': [frappe._dict(item_name='食材', qty=2, uom='Kg')]}
        doc.get.side_effect = lambda key: values.get(key)
        with patch.object(business, 'guard'), patch.object(business, 'visible_fields', return_value={'name'}), \
             patch.object(business, 'native_actions', return_value=[]), \
             patch.object(business, 'scope_filters', return_value=[]), patch.object(frappe, 'get_list', return_value=['PO1']), \
             patch.object(frappe, 'get_doc', return_value=doc), \
             patch.object(frappe, 'get_meta', side_effect=lambda dt: parentmeta if dt == 'Purchase Order' else childmeta), \
             patch.object(business, 'get_permitted_fields', return_value=['item_name', 'qty', 'uom']):
            result = business.record_view(choice)
        tables = [c for c in result['components'] if c['type'] == 'table']
        self.assertEqual(len(tables), 2)
        self.assertEqual(tables[1]['rows'][0]['cells'], ['食材', 2, 'Kg'])
        doc.apply_fieldlevel_read_permissions.assert_called_once()


def verify_business_views():
    """Read-only server integration probe. Returns metadata/aggregates, never personal rows."""
    frappe.set_user('Administrator')
    failures, checked, schema = [], [], []
    counts_before = {entry.doctype: frappe.db.count(entry.doctype) for entry in REGISTRY.values()}
    for key, entry in REGISTRY.items():
        meta = frappe.get_meta(entry.doctype)
        for field, _ in entry.columns:
            if field != 'name' and not meta.has_field(field):
                schema.append(key + ':' + field)
        for field, _, specification in entry.children:
            if not meta.has_field(field):
                schema.append(key + ':' + field)
                continue
            child = frappe.get_meta(meta.get_field(field).options)
            for column in specification.split('|'):
                if not child.has_field(column.split(':', 1)[0]):
                    schema.append(key + ':' + column.split(':', 1)[0])
        try:
            result = views.get_view({'view': 'business_list', 'entity': key, 'day': '2026-09-24', 'period': 'all'})
            rows = next(b for b in result['components'] if b['type'] == 'table')['rows']
            detail = False
            if rows:
                result_detail = views.get_view(rows[0]['action']['selection'])
                assert result_detail['selection']['view'] == 'business_record'
                if entry.children:
                    assert len([c for c in result_detail['components'] if c['type'] == 'table']) == 1 + len(entry.children), 'Missing child tables'
                detail = True
            checked.append({'key': key, 'count': result['summary']['record_count'], 'detail_checked': detail})
            views.get_view({'view': 'business_list', 'entity': key, 'day': '2026-09-24'})
        except Exception as error:
            failures.append({'key': key, 'error': str(error)[:250], 'type': type(error).__name__})
    catalog = views.get_view({'view': 'business_catalog', 'day': '2026-09-24'})
    stock = views.get_view({'view': 'stock', 'day': '2026-09-24'})
    ingredients = views.get_view({'view': 'ingredient_nutrition', 'day': '2026-09-24'})
    weekly = views.get_view({'view': 'weekly_orders', 'day': '2026-09-24'})
    classroom = views.get_view({'view': 'classroom_day', 'day': '2026-09-24'})
    class_rows = classroom['components'][1]['rows']
    if class_rows:
        classroom = views.get_view(class_rows[0]['action']['selection'])
    assert len(catalog['components']) <= 12
    assert counts_before == {entry.doctype: frappe.db.count(entry.doctype) for entry in REGISTRY.values()}
    return {'failures': failures, 'missing_fields': schema, 'checked': checked, 'catalog': catalog['summary'],
            'stock': stock['summary'], 'ingredient_nutrition': ingredients['summary'],
            'weekly_orders': weekly['summary'], 'classroom_day': classroom['summary'], 'record_counts_unchanged': True}
