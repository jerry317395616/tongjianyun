"""Real complex extension lifecycle; synthetic data on the dedicated QA DB only."""
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

SITE = 'unified-business-acceptance.localhost'
BASE = Path('/home/zyd/frappe/remote-workspace').resolve()
sites = Path(os.environ['UNIFIED_BUSINESS_SITES']).resolve(strict=True)
source = Path(os.environ['UNIFIED_BUSINESS_SOURCE']).resolve(strict=True)
assert sites.is_relative_to(BASE) and 'native-bench/sites' not in str(sites)
config = json.loads((sites / SITE / 'site_config.json').read_text())
assert config.get('unified_business_acceptance') == 1
assert config.get('db_host') == '127.0.0.1' and int(config.get('db_port', 0)) == 23316
assert config.get('db_name') == 'tgy_blueprint_qa' and not config.get('db_socket')
for key in list(os.environ):
    if key.startswith(('FRAPPE_DB_', 'FRAPPE_REDIS_')):
        os.environ.pop(key)
sys.dont_write_bytecode = True
sys.path.insert(0, str(source))
os.environ['FRAPPE_BENCH_ROOT'] = str(sites.parent)
os.chdir(sites)

import frappe
from frappe.model.workflow import apply_workflow
from tongjianyun import business_blueprints as bp
from tongjianyun import business_blueprints_v2 as v2
from tongjianyun.tests.test_business_blueprints_v2 import SPEC
from tongjianyun.meal_views import get_view

assert Path(v2.__file__).resolve().is_relative_to(source)
run_id = uuid.uuid4().hex[:10]
checks = []


def connect():
    frappe.init(site=SITE, sites_path=str(sites))
    assert frappe.conf.unified_business_acceptance == 1 and not frappe.conf.developer_mode
    assert frappe.conf.db_name == config['db_name'] and frappe.conf.db_host == '127.0.0.1'
    assert int(frappe.conf.db_port) == 23316 and not frappe.conf.db_socket
    for key in ('redis_cache', 'redis_queue'):
        endpoint = urlparse(frappe.conf.get(key) or '')
        assert endpoint.hostname == '127.0.0.1' and endpoint.port == 23379
    frappe.connect()
    frappe.set_user('Administrator')


def check(name, condition):
    assert condition, name
    checks.append(name)


def denied(action, exception=frappe.ValidationError):
    # Test APIs may mutate the in-memory object before rejecting it. Each next
    # assertion reloads the persisted document, never reuses a failed object.
    try:
        action()
    except exception:
        return True
    return False


connect()
try:
    frappe.clear_cache()  # Isolated Redis only: load the candidate wildcard hook.
    check('candidate_runtime_hook_loaded', 'tongjianyun.business_blueprints_v2.validate_document' in
          frappe.get_hooks('doc_events')['*']['before_validate'])
    spec = bp.validate_spec({**SPEC, 'key': 'estimate_' + run_id})
    dt = bp.doctype_name(spec)
    proposal = bp.propose(spec)
    preview = bp.preview(proposal['proposal_id'])
    check('preview_includes_tables_math_and_review', bool(preview['components'][0]['tables']) and
          len(preview['components'][0]['calculations']) == 2 and preview['components'][0]['workflow']['template'] == 'review')
    check('preview_performs_no_ddl', not frappe.db.exists('DocType', dt))
    try:
        result = bp.activate(proposal['proposal_id'], proposal['revision'])
    except Exception:
        # Only synthetic metadata, never site credentials or business records.
        for definition in v2.definitions(spec):
            meta = frappe.get_meta(definition['name'], cached=False)
            for key in ('custom', 'istable', 'is_submittable', 'track_changes', 'module', 'autoname',
                        'title_field', 'search_fields', 'description', 'is_virtual', 'issingle'):
                if str(meta.get(key) or '') != str(definition.get(key) or ''):
                    print('metadata mismatch', key, '(manifest)' if key == 'description' else [meta.get(key), definition.get(key)])
            if [v2._values(f, v2.FIELD_KEYS) for f in meta.fields] != [v2._values(f, v2.FIELD_KEYS) for f in definition['fields']]:
                print('actual fields', [v2._values(f, v2.FIELD_KEYS) for f in meta.fields])
                print('expected fields', [v2._values(f, v2.FIELD_KEYS) for f in definition['fields']])
            print('schema exact', definition['name'], v2._schema_matches(definition))
            if [v2._values(p, v2.PERM_KEYS) for p in meta.permissions] != [v2._values(p, v2.PERM_KEYS) for p in definition['permissions']]:
                print('actual permissions', [v2._values(p, v2.PERM_KEYS) for p in meta.permissions])
                print('expected permissions', [v2._values(p, v2.PERM_KEYS) for p in definition['permissions']])
            print('columns', frappe.db.get_table_columns(definition['name']))
        print('workflow exact', v2._workflow_matches(spec))
        raise
    check('complex_schema_and_workflow_exactly_active', bp._state(spec) == 'active')
    check('repeated_activation_is_idempotent', bp.activate(proposal['proposal_id'], proposal['revision']) == result)

    people = ['estimate-owner-' + run_id + '@example.invalid', 'estimate-reviewer-' + run_id + '@example.invalid']
    for email in people:
        frappe.get_doc({'doctype': 'User', 'email': email, 'first_name': '隔离复核测试', 'enabled': 1,
            'send_welcome_email': 0, 'user_type': 'System User', 'roles': [{'role': 'System Manager'}]}).insert()
    frappe.db.commit()
    frappe.set_user(people[0])
    doc = frappe.get_doc({'doctype': dt, 'title': '合成活动估算', 'estimated_total': 999,
        'estimate_lines': [{'item_label': '测试材料A', 'quantity': 2.5, 'unit_price': 3.8, 'line_amount': 999},
                           {'item_label': '测试材料B', 'quantity': 10, 'unit_price': 1.25, 'line_amount': 999}]}).insert()
    name = doc.name
    frappe.db.commit()
    def load():
        return frappe.get_doc(dt, name)
    def change(**values):
        current = load()
        current.update(values)
        return current.save()
    check('native_insert_recomputes_untrusted_amounts', doc.estimated_total == 22 and
          [r.line_amount for r in doc.estimate_lines] == [9.5, 12.5])
    check('first_state_is_draft', doc.workflow_state == '扩展·草稿' and doc.docstatus == 0)
    check('native_record_view_available', get_view({'view': 'frappe_document', 'doctype': dt, 'document': name})['summary']['route_verified'])
    check('direct_submit_without_review_rejected', denied(lambda: load().submit()))
    check('direct_state_jump_rejected', denied(lambda: change(workflow_state='扩展·通过'), (frappe.ValidationError, frappe.PermissionError)))
    apply_workflow(load(), '扩展·送审')
    frappe.db.commit()
    check('native_workflow_enters_review', load().workflow_state == '扩展·待复核')
    check('owner_cannot_approve_with_workflow_api', denied(lambda: apply_workflow(load(), '扩展·复核通过'), (frappe.ValidationError, frappe.PermissionError)))
    def direct_approve():
        current = load()
        current.workflow_state = '扩展·通过'
        return current.submit()
    check('owner_cannot_bypass_workflow_via_submit', denied(direct_approve, (frappe.ValidationError, frappe.PermissionError)))
    check('pending_contents_frozen', denied(lambda: change(title='不应保存')))
    frappe.set_user(people[1])
    check('second_manager_does_not_need_private_proposal_access', denied(lambda: bp.preview(proposal['proposal_id']), frappe.PermissionError))
    apply_workflow(load(), '扩展·退回修改')
    frappe.db.commit()
    frappe.set_user(people[0])
    current = load()
    current.estimate_lines[0].quantity = 3
    current.save()
    frappe.db.commit()
    check('returned_record_can_be_revised_and_recalculated', load().estimated_total == 23.9 and load().name == name)
    apply_workflow(load(), '扩展·重新送审')
    frappe.db.commit()
    frappe.set_user(people[1])
    apply_workflow(load(), '扩展·复核通过')
    frappe.db.commit()
    check('different_manager_approves_native_submit', load().docstatus == 1 and load().workflow_state == '扩展·通过')
    check('approved_contents_cannot_change', denied(lambda: change(title='非法改动')))
    apply_workflow(load(), '扩展·撤销通过')
    frappe.db.commit()
    check('native_cancel_preserves_record_and_history', load().docstatus == 2 and
          frappe.db.count('Version', {'ref_doctype': dt, 'docname': name}) >= 3)
    check('cancelled_contents_cannot_change', denied(lambda: change(title='非法改动')))
    frappe.destroy()
    connect()
    check('new_connection_reads_final_state_and_amount', load().docstatus == 2 and load().estimated_total == 23.9)
    check('metadata_still_exact_after_full_lifecycle', bp._state(spec) == 'active')
    report = {'run_id': run_id, 'isolated_site': SITE, 'checks': checks, 'passed': len(checks),
              'retained_doctype': dt, 'retained_document': name, 'production_writes': False, 'browser_ui_tested': False}
    (sites.parent / ('complex-blueprint-lifecycle-' + run_id + '.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))
finally:
    if getattr(frappe.local, 'db', None):
        frappe.db.rollback()
    frappe.destroy()
