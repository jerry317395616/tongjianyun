"""Real Workflow guards, only on the dedicated isolated synthetic QA site.

Metadata drift is injected into this script's own synthetic transition inside
an uncommitted transaction; native execution is replaced by a spy. No webhook,
server script, production data or live service is invoked.
"""
import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch
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
from tongjianyun import business_blueprint_workflow as guard
from tongjianyun import business_blueprints as bp
from tongjianyun import business_blueprints_v2 as v2
from tongjianyun.tests.test_business_blueprints_v2 import SPEC

assert Path(guard.__file__).resolve().is_relative_to(source)
run_id = uuid.uuid4().hex[:10]
checks = []


def check(name, condition):
    assert condition, name
    checks.append(name)


def rejected(action, phrase=None):
    try:
        action()
    except (frappe.ValidationError, frappe.PermissionError) as error:
        return phrase is None or phrase in str(error)
    return False


frappe.init(site=SITE, sites_path=str(sites))
assert frappe.conf.unified_business_acceptance == 1 and not frappe.conf.developer_mode
assert frappe.conf.db_name == config['db_name'] and frappe.conf.db_host == '127.0.0.1'
assert int(frappe.conf.db_port) == 23316 and not frappe.conf.db_socket
for key in ('redis_cache', 'redis_queue'):
    endpoint = urlparse(frappe.conf.get(key) or '')
    assert endpoint.hostname == '127.0.0.1' and endpoint.port == 23379
frappe.connect()
frappe.set_user('Administrator')
try:
    frappe.clear_cache()  # Dedicated QA Redis only.
    overrides = frappe.get_hooks('override_whitelisted_methods')
    for method in ('apply_workflow', 'get_transitions', 'bulk_workflow_approval'):
        check('http_override_' + method,
              overrides['frappe.model.workflow.' + method][-1] == 'tongjianyun.business_blueprint_workflow.' + method)
    workflow_hooks = frappe.get_hooks('doc_events')['Workflow']
    check('workflow_metadata_hooks_loaded', all(
        'tongjianyun.business_blueprint_workflow.validate_workflow_metadata' in workflow_hooks[event]
        for event in ('before_insert', 'before_validate', 'on_trash')))

    spec = bp.validate_spec({**SPEC, 'key': 'wf_guard_' + run_id})
    dt = bp.doctype_name(spec)
    proposal = bp.propose(spec)
    bp.activate(proposal['proposal_id'], proposal['revision'])
    wf_name = v2.workflow_definition(spec)['workflow_name']
    check('fixed_workflow_initial_install_allowed', v2.state(spec) == 'active')
    task_name = 'QA Empty Tasks ' + run_id
    frappe.get_doc({'doctype': 'Workflow Transition Tasks', 'name': task_name, 'tasks': []}).insert()
    frappe.db.commit()

    mutations = [
        ('condition', lambda doc: doc.transitions[0].set('condition', 'True')),
        ('tasks', lambda doc: doc.transitions[0].set('transition_tasks', task_name)),
        ('role', lambda doc: doc.transitions[0].set('allowed', 'Guest')),
        ('disable', lambda doc: doc.set('is_active', 0)),
        ('retarget', lambda doc: doc.set('document_type', 'Workflow Transition Tasks')),
        ('state_update', lambda doc: doc.states[0].update({'update_field': 'title', 'update_value': 'not allowed'})),
    ]
    for label, mutate in mutations:
        workflow = frappe.get_doc('Workflow', wf_name)
        mutate(workflow)
        check('native_metadata_' + label + '_rejected_by_guard',
              rejected(workflow.save, '受控复核流程'))
        frappe.db.rollback()
        check('metadata_exact_after_' + label, v2.state(spec) == 'active')
    check('owned_workflow_delete_rejected', rejected(
        lambda: frappe.delete_doc('Workflow', wf_name), '受控复核流程'))
    frappe.db.rollback()
    check('workflow_preserved_after_delete_attempt', frappe.db.exists('Workflow', wf_name) and v2.state(spec) == 'active')

    # client.save(child) does not save its parent: the child hook must cover it.
    from frappe.client import save as native_client_save
    for field, child_type, change in [
        ('transitions', 'Workflow Transition', {'condition': 'True'}),
        ('states', 'Workflow Document State', {'update_field': 'title', 'update_value': 'not allowed'}),
    ]:
        child = frappe.get_doc('Workflow', wf_name).get(field)[0]
        child.update(change)
        check('direct_client_save_' + field + '_rejected', rejected(
            lambda: native_client_save(child.as_dict()), '受控复核流程'))
        frappe.db.rollback()
        check('direct_child_delete_' + field + '_rejected', rejected(
            lambda: frappe.delete_doc(child_type, child.name), '受控复核流程'))
        frappe.db.rollback()
        check('metadata_exact_after_direct_child_' + field, v2.state(spec) == 'active')

    doc = frappe.get_doc({'doctype': dt, 'title': '仅隔离测试复核入口',
                         'estimate_lines': [{'item_label': '合成材料', 'quantity': 2.5, 'unit_price': 3.8}]}).insert()
    frappe.db.commit()
    doc_ref = {'doctype': dt, 'name': doc.name}

    # Deliberate drift of this test's own row, never committed. Spy proves no
    # native task/condition/queue entry runs before the guard rejects the drift.
    transition_name = frappe.get_doc('Workflow', wf_name).transitions[0].name
    assert frappe.db.get_value('Workflow Transition', transition_name, 'parent') == wf_name
    frappe.db.set_value('Workflow Transition', transition_name, 'transition_tasks', task_name)
    with patch('frappe.model.workflow.apply_workflow') as apply, \
         patch('frappe.model.workflow.get_transitions') as transitions, \
         patch('frappe.model.workflow.bulk_workflow_approval') as bulk:
        check('drift_stops_apply_before_native_tasks', rejected(lambda: guard.apply_workflow(doc_ref, '扩展·送审')))
        check('drift_stops_transitions_before_native_conditions', rejected(lambda: guard.get_transitions(doc_ref)))
        check('drift_stops_bulk_before_native_queue', rejected(lambda: guard.bulk_workflow_approval([doc.name], dt, '扩展·送审')))
        check('no_native_side_effect_entry_called', not apply.called and not transitions.called and not bulk.called)
    frappe.db.rollback()
    frappe.clear_cache(doctype=dt)
    check('drift_rolled_back_and_bundle_active', v2.state(spec) == 'active')

    check('valid_wrapper_lists_native_transitions', bool(guard.get_transitions(doc_ref)))
    guard.apply_workflow(doc_ref, '扩展·送审')
    frappe.db.commit()
    check('valid_wrapper_enters_review', frappe.get_doc(dt, doc.name).workflow_state == '扩展·待复核')
    # Administrator's documented native self-approval exception is intentional.
    guard.apply_workflow(doc_ref, '扩展·复核通过')
    frappe.db.commit()
    check('valid_wrapper_native_submit_works', frappe.get_doc(dt, doc.name).docstatus == 1)
    guard.apply_workflow(doc_ref, '扩展·撤销通过')
    frappe.db.commit()
    final = frappe.get_doc(dt, doc.name)
    check('valid_wrapper_native_cancel_preserves_amount', final.docstatus == 2 and final.estimated_total == 9.5)
    check('final_bundle_unchanged', v2.state(spec) == 'active')
    report = {'run_id': run_id, 'isolated_site': SITE, 'checks': checks, 'passed': len(checks),
              'retained_doctype': dt, 'retained_document': doc.name, 'retained_workflow': wf_name,
              'retained_empty_task_group': task_name, 'production_writes': False,
              'http_transport_tested': False, 'native_http_override_functions_tested': True,
              'external_tasks_executed': False}
    (sites.parent / ('blueprint-workflow-guard-' + run_id + '.json')).write_text(
        json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))
finally:
    if getattr(frappe.local, 'db', None):
        frappe.db.rollback()
    frappe.destroy()
