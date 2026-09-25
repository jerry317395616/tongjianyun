"""No DDL against the live site: activation tests use an explicit fake boundary."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from tongjianyun import business_blueprints as blueprint


SPEC = {'key': 'visitor_log', 'title': '访客登记', 'description': '记录到访时间与事由，不代表出入审批。',
        'fields': [{'fieldname': 'visited_on', 'label': '到访日期', 'fieldtype': 'Date', 'reqd': 1},
                   {'fieldname': 'reason', 'label': '事由', 'fieldtype': 'Small Text'}]}


class BlueprintTests(unittest.TestCase):
    def test_canonical_definition_has_history_and_restricted_permissions(self):
        spec = blueprint.validate_spec(SPEC)
        definition = blueprint._definition(spec)
        self.assertEqual(definition['name'], 'Tongjianyun Extension visitor_log')
        self.assertEqual(definition['track_changes'], 1)
        self.assertEqual(definition['custom'], 1)
        self.assertEqual(definition['is_submittable'], 0)
        self.assertEqual(definition['permissions'][0]['role'], 'System Manager')
        self.assertEqual(definition['permissions'][0]['delete'], 0)
        self.assertEqual(definition['fields'][0]['fieldname'], 'title')

    def test_no_code_defaults_permissions_or_system_fields(self):
        for value in [dict(SPEC, script='print(1)'), dict(SPEC, roles=['Guest']),
                      dict(SPEC, key='../DocType')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                blueprint.validate_spec(value)
        for extra in [{'fieldname': 'owner'}, {'fieldname': '__proto__'}, {'fieldtype': 'HTML'},
                      {'fieldname': 'get'}, {'fieldname': 'save'}, {'fieldname': 'insert'}, {'fieldname': 'as_dict'},
                      {'default': 'eval:1'}, {'permlevel': 0}, {'depends_on': 'eval:1'},
                      {'fieldtype': 'Link', 'options': 'User'}, {'fieldtype': 'Data', 'options': 'eval:1'}]:
            value = copy.deepcopy(SPEC)
            value['fields'][0].update(extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                blueprint.validate_spec(value)

    def test_duplicate_and_unbounded_fields_rejected(self):
        for fields in [[], SPEC['fields'] * 2, SPEC['fields'] * 13]:
            with self.subTest(count=len(fields)), self.assertRaises(ValueError):
                blueprint.validate_spec(dict(SPEC, fields=fields))

    def test_generated_table_name_respects_database_identifier_limit(self):
        spec = blueprint.validate_spec(dict(SPEC, key='a' * blueprint.MAX_KEY))
        self.assertLessEqual(len('tab' + blueprint.doctype_name(spec)), 64)
        with self.assertRaises(ValueError):
            blueprint.validate_spec(dict(SPEC, key='a' * (blueprint.MAX_KEY + 1)))

    def test_select_and_link_schemas(self):
        value = dict(SPEC, fields=[{'fieldname': 'status', 'label': '状态', 'fieldtype': 'Select',
                                  'options': '待处理\n已完成'}])
        self.assertEqual(blueprint.validate_spec(value)['fields'][0]['options'], '待处理\n已完成')
        for options in ['', '重复\n重复', '一\n\n二', '重复\n 重复 ']:
            value['fields'][0]['options'] = options
            with self.assertRaises(ValueError):
                blueprint.validate_spec(value)

    def test_preview_digest_changes_when_any_field_changes(self):
        first = blueprint.validate_spec(SPEC)
        other = copy.deepcopy(first)
        other['fields'][0]['reqd'] = 0
        self.assertNotEqual(blueprint.revision(first), blueprint.revision(other))
        self.assertEqual(blueprint.revision(first), blueprint.revision(blueprint.validate_spec(json.dumps(SPEC))))

    def test_proposal_owner_and_private_file_are_checked_before_content_read(self):
        file = MagicMock(owner='someone-else', is_private=1, file_url='/private/files/x.json')
        file.file_name = 'business-blueprint-' + 'a' * 32 + '.json'
        with patch.object(blueprint, '_access'), patch.object(frappe, 'session', SimpleNamespace(user='Administrator')), \
             patch.object(frappe, 'get_doc', return_value=file):
            with self.assertRaises(frappe.PermissionError):
                blueprint._load('proposal')
        file.get_content.assert_not_called()

    def test_remote_file_is_rejected_before_content_read(self):
        file = MagicMock(owner='Administrator', is_private=1, file_url='https://external.test/x.json')
        file.file_name = 'business-blueprint-' + 'a' * 32 + '.json'
        with patch.object(blueprint, '_access'), patch.object(frappe, 'session', SimpleNamespace(user='Administrator')), \
             patch.object(frappe, 'get_doc', return_value=file):
            with self.assertRaises(frappe.PermissionError):
                blueprint._load('proposal')
        file.get_content.assert_not_called()

    def test_activation_rejects_changed_preview_before_ddl(self):
        with patch.object(blueprint, '_load', return_value=blueprint.validate_spec(SPEC)), \
             patch.object(frappe, 'throw', side_effect=ValueError), patch.object(frappe, 'get_doc') as get_doc:
            with self.assertRaises(ValueError):
                blueprint.activate('P1', 'old-revision')
        get_doc.assert_not_called()

    def test_activation_requires_native_create_permission(self):
        spec = blueprint.validate_spec(SPEC)
        with patch.object(blueprint, '_load', return_value=spec), \
             patch.object(frappe, 'has_permission', side_effect=frappe.PermissionError), \
             patch.object(frappe, 'get_doc') as get_doc:
            with self.assertRaises(frappe.PermissionError):
                blueprint.activate('P1', blueprint.revision(spec))
        get_doc.assert_not_called()

    def test_activation_calls_orm_once_and_repeat_does_not_duplicate(self):
        spec = blueprint.validate_spec(SPEC)
        doc = MagicMock()
        doc.insert.return_value = doc
        with patch.object(blueprint, '_load', return_value=spec), \
             patch.object(blueprint, '_validate_links'), patch.object(blueprint, '_state', side_effect=['proposed', 'active', 'active']), \
             patch.object(frappe, 'local', SimpleNamespace(site='test')), patch.object(frappe, 'has_permission', return_value=True), \
             patch.object(frappe, 'cache', return_value=MagicMock()), patch.object(frappe, 'get_doc', return_value=doc) as get_doc, \
             patch.object(frappe, 'db', MagicMock()) as db:
            first = blueprint.activate('P1', blueprint.revision(spec))
            second = blueprint.activate('P1', blueprint.revision(spec))
        self.assertEqual(first, second)
        get_doc.assert_called_once()
        doc.insert.assert_called_once_with()
        self.assertEqual(db.commit.call_count, 2)

    def test_existing_mismatched_type_is_not_overwritten(self):
        spec = blueprint.validate_spec(SPEC)
        with patch.object(blueprint, '_load', return_value=spec), patch.object(blueprint, '_validate_links'), \
             patch.object(blueprint, '_state', return_value='conflict'), \
             patch.object(frappe, 'local', SimpleNamespace(site='test')), patch.object(frappe, 'has_permission', return_value=True), \
             patch.object(frappe, 'cache', return_value=MagicMock()), patch.object(frappe, 'throw', side_effect=ValueError), \
             patch.object(frappe, 'get_doc') as get_doc:
            with self.assertRaises(ValueError):
                blueprint.activate('P1', blueprint.revision(spec))
        get_doc.assert_not_called()

    def test_preview_does_not_create_type_or_records(self):
        spec = blueprint.validate_spec(SPEC)
        with patch.object(blueprint, '_load', return_value=spec), patch.object(blueprint, '_validate_links'), \
             patch.object(blueprint, '_state', return_value='proposed'), \
             patch.object(frappe, 'has_permission', return_value=True), patch.object(frappe, 'get_doc') as get_doc:
            result = blueprint.preview('P1')
        self.assertTrue(result['components'][0]['can_activate'])
        self.assertEqual(result['summary']['state'], 'proposed')
        get_doc.assert_not_called()

    def test_schema_exact_match_required_for_active_state(self):
        spec = blueprint.validate_spec(SPEC)
        definition = blueprint._definition(spec)
        meta = SimpleNamespace(custom=1, module='Tongjianyun', track_changes=1,
                               description=definition['description'], fields=copy.deepcopy(definition['fields']),
                               permissions=definition['permissions'], is_submittable=0, autoname='hash', title_field='title', search_fields='title')
        columns = ['name', 'owner', 'creation', 'modified', 'modified_by', 'docstatus', 'idx', 'title', 'visited_on', 'reason']
        db = MagicMock()
        db.get_table_columns.return_value = columns
        with patch.object(frappe, 'db', db), patch.object(frappe, 'get_meta', return_value=meta):
            self.assertEqual(blueprint._state(spec), 'active')
            meta.fields[1]['reqd'] = 0
            self.assertEqual(blueprint._state(spec), 'conflict')

    def test_metadata_without_table_is_not_success_after_failed_ddl(self):
        db = MagicMock()
        db.table_exists.return_value = False
        with patch.object(frappe, 'db', db):
            self.assertEqual(blueprint._state(blueprint.validate_spec(SPEC)), 'conflict')

    def test_missing_physical_column_is_not_an_active_business(self):
        spec = blueprint.validate_spec(SPEC)
        definition = blueprint._definition(spec)
        meta = SimpleNamespace(fields=definition['fields'])
        db = MagicMock()
        db.get_table_columns.return_value = ['name', 'title']
        with patch.object(frappe, 'db', db), patch.object(frappe, 'get_meta', return_value=meta):
            self.assertEqual(blueprint._state(spec), 'conflict')

    def test_blueprint_selection_cannot_include_executable_components(self):
        from tongjianyun.meal_views import selection
        with patch.object(frappe, 'throw', side_effect=ValueError):
            for value in [{'view': 'business_blueprint'}, {'view': 'business_blueprint', 'proposal_id': 'P', 'components': ['html']},
                          {'view': 'students', 'proposal_id': 'P'}]:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    selection(value)
        self.assertEqual(selection({'view': 'business_blueprint', 'proposal_id': 'P'}),
                         {'view': 'business_blueprint', 'proposal_id': 'P'})
