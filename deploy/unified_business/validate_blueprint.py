"""Read-only native DocType validation: no insert, save, migration or DDL."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch


source = Path(os.environ['UNIFIED_BUSINESS_SOURCE']).resolve()
sys.path.insert(0, str(source))
sites = Path('/home/zyd/frappe/native-bench/sites')
os.chdir(sites)

import frappe

frappe.init(site='child.myyr.top', sites_path=str(sites))
frappe.connect()
try:
    frappe.set_user('Administrator')
    from tongjianyun import business_blueprints as blueprint

    assert str(Path(blueprint.__file__).resolve()).startswith(str(source) + '/'), 'Wrong source overlay'
    examples = [
        {'key': 'bp_readonly_validation', 'title': '只读校验示例', 'description': '仅构造元数据并运行原校验，不启用。',
         'fields': [{'fieldname': 'entry_value', 'label': '记录内容', 'fieldtype': 'Data'}]},
        {'key': 'bp_readonly_all_types', 'title': '字段类型校验', 'description': '原校验覆盖全部允许字段类型，不写库。',
         'fields': [{'fieldname': 'entry_' + str(i), 'label': kind, 'fieldtype': kind,
                     'reqd': 1 if kind in {'Date', 'Select'} else 0,
                     **({'options': '待处理\n已完成'} if kind == 'Select' else
                        {'options': 'Student'} if kind == 'Link' else {})}
                    for i, kind in enumerate(sorted(blueprint.TYPES))]},
        {'key': 'z' * blueprint.MAX_KEY, 'title': '长度边界校验', 'description': '仅校验允许最长名称。',
         'fields': [{'fieldname': 'x' * 48, 'label': '长度边界字段', 'fieldtype': 'Small Text'}]},
    ]
    before = {name: frappe.db.count(name) for name in ('DocType', 'DocField', 'DocPerm')}
    sql = frappe.db.sql

    def read_only_sql(query, *args, **kwargs):
        prefix = str(query).lstrip().split(None, 1)[0].lower()
        if prefix not in {'select', 'show', 'describe', 'explain'}:
            raise AssertionError('Validation attempted a non-read database query')
        return sql(query, *args, **kwargs)

    checked = []
    with patch.object(frappe.db, 'sql', side_effect=read_only_sql), \
         patch.object(frappe.db, 'commit', side_effect=AssertionError('Validation attempted commit')):
        for value in examples:
            spec = blueprint.validate_spec(value)
            blueprint._validate_links(spec)
            definition = blueprint._definition(spec)
            assert not frappe.db.exists('DocType', definition['name']), 'Test name must not already exist'
            doc = frappe.get_doc(definition)
            doc.set('__islocal', 1)
            doc.validate()
            doc.validate_field_name_conflicts()
            fields = ('fieldname', 'label', 'fieldtype', 'reqd', 'options', 'in_list_view')
            normalize = lambda row: {key: row.get(key) or (0 if key in {'reqd', 'in_list_view'} else '') for key in fields}
            assert [normalize(row) for row in doc.fields] == [normalize(row) for row in definition['fields']], 'Native validation changed the previewed fields'
            checked.append({'key_length': len(spec['key']), 'fields': len(spec['fields']),
                            'native_validate': True, 'field_conflict_check': True, 'preview_fields_unchanged': True})
        after = {name: frappe.db.count(name) for name in before}
        assert before == after, 'Metadata record counts changed'
        assert not any(frappe.db.table_exists(blueprint.doctype_name(value)) for value in examples), 'Validation created a table'
    print(json.dumps({'source_overlay': str(source), 'checked': checked,
                      'metadata_counts_unchanged': True, 'no_tables_created': True}, ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
