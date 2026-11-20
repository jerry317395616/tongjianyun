"""Real schema/record lifecycle, ONLY on the separately provisioned test site.

Never use the production bench sites directory. No production credentials or
data are copied. Test records are retained in the isolated database for audit.
"""
import json
import os
import stat
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse


SITE = 'unified-business-acceptance.localhost'
BASE = Path('/home/zyd/frappe/remote-workspace').resolve()
sites = Path(os.environ['UNIFIED_BUSINESS_SITES']).resolve(strict=True)
source = Path(os.environ['UNIFIED_BUSINESS_SOURCE']).resolve(strict=True)
assert sites.is_relative_to(BASE), 'Only the dedicated remote-workspace test sites are allowed'
assert 'native-bench/sites' not in str(sites), 'Never run this against production'
config = json.loads((sites / SITE / 'site_config.json').read_text())
assert config.get('unified_business_acceptance') == 1, 'Explicit test-site marker is required'
assert config.get('db_host') == '127.0.0.1' and int(config.get('db_port', 3306)) == 23316
assert config.get('db_name') == 'tgy_blueprint_qa'
assert not config.get('db_socket')
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
for key in list(os.environ):
    if key.startswith(('FRAPPE_DB_', 'FRAPPE_REDIS_')):
        os.environ.pop(key)
sys.path.insert(0, str(source))
os.environ['FRAPPE_BENCH_ROOT'] = str(sites.parent)
os.chdir(sites)

import frappe

from tongjianyun import business_blueprints as bp
from tongjianyun import frappe_project_views as project
from tongjianyun.meal_chat import TaskStore
from tongjianyun.meal_view_tool import use_site_os_identity
from tongjianyun.meal_views import get_view

assert Path(bp.__file__).resolve().is_relative_to(source), 'Wrong source under test'
use_site_os_identity(sites / SITE)
run_id = uuid.uuid4().hex[:10]
checks = []


def check(name, condition):
    assert condition, name
    checks.append(name)


def denied(action, exception=frappe.PermissionError):
    try:
        action()
    except exception:
        return True
    return False


def connect():
    frappe.init(site=SITE, sites_path=str(sites))
    assert frappe.conf.unified_business_acceptance == 1
    assert frappe.conf.db_name == config['db_name']
    assert frappe.conf.db_host == '127.0.0.1' and int(frappe.conf.db_port) == 23316
    assert not frappe.conf.db_socket and not frappe.conf.developer_mode
    for key in ('redis_cache', 'redis_queue'):
        endpoint = urlparse(frappe.conf.get(key) or '')
        assert endpoint.scheme == 'redis' and endpoint.hostname == '127.0.0.1' and endpoint.port == 23379
    frappe.connect()
    frappe.set_user('Administrator')


connect()
try:
    spec = bp.validate_spec({
        'key': 'acceptance_' + run_id, 'title': '隔离验收登记',
        'description': '仅测试，不属于真实园所业务；覆盖全部允许字段。',
        'fields': [
            {'fieldname': 'entry_data', 'label': '内容', 'fieldtype': 'Data', 'reqd': 1},
            {'fieldname': 'entry_text', 'label': '备注', 'fieldtype': 'Small Text'},
            {'fieldname': 'entry_date', 'label': '日期', 'fieldtype': 'Date'},
            {'fieldname': 'entry_time', 'label': '时间', 'fieldtype': 'Datetime'},
            {'fieldname': 'entry_int', 'label': '数量', 'fieldtype': 'Int'},
            {'fieldname': 'entry_float', 'label': '读数', 'fieldtype': 'Float'},
            {'fieldname': 'entry_currency', 'label': '金额', 'fieldtype': 'Currency'},
            {'fieldname': 'entry_check', 'label': '已核对', 'fieldtype': 'Check'},
            {'fieldname': 'entry_select', 'label': '状态', 'fieldtype': 'Select', 'options': '待处理\n已完成'},
            {'fieldname': 'entry_link', 'label': '单位', 'fieldtype': 'Link', 'options': 'UOM'},
        ],
    })
    dt = bp.doctype_name(spec)
    store = TaskStore()
    task_id = str(uuid.uuid4())
    store.update(task_id, owner='Administrator', status='running', cancel_requested='0',
                 day='2026-09-25', meal='lunch')
    proposal = bp.propose_for_task(task_id, spec)
    check('task_bound_proposal_emits_view', proposal['display_requested'] and
          store.events(task_id)[-1]['selection']['proposal_id'] == proposal['proposal_id'])
    file = frappe.get_doc('File', proposal['proposal_id'])
    file_path = Path(file.get_full_path())
    check('private_file_owned_by_service', file.is_private == 1 and file_path.stat().st_uid == os.geteuid()
          and stat.S_IMODE(file_path.stat().st_mode) == 0o600)
    preview = get_view({'view': 'business_blueprint', 'proposal_id': proposal['proposal_id']})
    check('preview_does_not_create_table', preview['summary']['state'] == 'proposed' and not frappe.db.table_exists(dt))
    check('changed_revision_rejected_before_ddl', denied(
        lambda: bp.activate(proposal['proposal_id'], 'changed'), frappe.ValidationError) and not frappe.db.table_exists(dt))
    result = bp.activate(proposal['proposal_id'], proposal['revision'])
    check('real_table_and_exact_metadata_created', result['state'] == 'active' and bp._state(spec) == 'active')
    check('repeat_activation_is_idempotent', bp.activate(proposal['proposal_id'], proposal['revision']) == result
          and frappe.db.count('DocType', {'name': dt}) == 1 and frappe.db.count(dt) == 0)

    # Use native Document insert/save and permissions, not direct SQL writes.
    check('native_required_field_validation', denied(
        lambda: frappe.get_doc({'doctype': dt, 'title': '缺少必填'}).insert(), frappe.MandatoryError))
    uom = frappe.get_doc({'doctype': 'UOM', 'uom_name': 'QA-Unit-' + run_id}).insert().name
    record = frappe.get_doc({'doctype': dt, 'title': '隔离记录', 'entry_data': '初始内容',
        'entry_text': '测试备注', 'entry_date': '2026-09-25', 'entry_time': '2026-09-25 09:30:00',
        'entry_int': 2, 'entry_float': 1.25, 'entry_currency': 3.5, 'entry_check': 1,
        'entry_select': '待处理', 'entry_link': uom}).insert()
    frappe.db.commit()
    name = record.name
    record.entry_data = '修订内容'
    record.entry_select = '已完成'
    record.save()
    frappe.db.commit()
    check('update_preserves_record_identity', record.name == name and frappe.db.count(dt) == 1)
    check('native_change_history_created', frappe.db.count('Version', {'ref_doctype': dt, 'docname': name}) >= 1)
    modules = project.module_apps()
    entries = project.catalog_entries({'kind': 'doctype', 'keyword': dt}, modules)
    check('new_business_auto_discovered', any(row['name'] == dt for row in entries))
    check('native_create_view_available', get_view({'view': 'frappe_new', 'doctype': dt})['summary']['route_verified'])
    check('native_record_view_available', get_view({'view': 'frappe_document', 'doctype': dt, 'document': name})['summary']['route_verified'])

    manager = 'acceptance-manager-' + run_id + '@example.invalid'
    viewer = 'acceptance-viewer-' + run_id + '@example.invalid'
    for email, roles in ((manager, ['System Manager']), (viewer, [])):
        frappe.get_doc({'doctype': 'User', 'email': email, 'first_name': '隔离验收', 'enabled': 1,
            'send_welcome_email': 0, 'user_type': 'System User',
            'roles': [{'role': role} for role in roles]}).insert()
    frappe.db.commit()
    frappe.set_user(manager)
    check('other_manager_cannot_activate_owned_proposal', denied(lambda: bp.preview(proposal['proposal_id'])))
    check('manager_can_read_created_records_without_delete', frappe.has_permission(dt, 'read')
          and frappe.has_permission(dt, 'write') and not frappe.has_permission(dt, 'delete'))
    frappe.set_user(viewer)
    check('ungranted_user_cannot_read_new_business', not frappe.has_permission(dt, 'read'))
    frappe.set_user('Guest')
    check('guest_cannot_preview_or_activate', denied(lambda: bp.preview(proposal['proposal_id']))
          and denied(lambda: bp.activate(proposal['proposal_id'], proposal['revision'])))

    # Re-open using a new connection: no cached in-process record as evidence.
    frappe.destroy()
    connect()
    reread = frappe.get_doc(dt, name)
    check('new_connection_reads_saved_revision', reread.entry_data == '修订内容' and reread.entry_select == '已完成')
    check('saved_proposal_reopens_as_active', bp.preview(proposal['proposal_id'])['summary']['state'] == 'active')
    store = TaskStore()
    store.update(task_id, status='cancelled', cancel_requested='1')
    files_before = frappe.db.count('File')
    check('cancelled_task_cannot_create_proposal', denied(lambda: bp.propose_for_task(task_id,
          {**spec, 'key': 'cancelled_' + run_id}), ValueError) and frappe.db.count('File') == files_before)
    report = {'isolated_site': SITE, 'run_id': run_id, 'source_commit': os.environ.get('UNIFIED_BUSINESS_COMMIT', 'working-source'),
              'checks': checks, 'passed': len(checks), 'retained_doctype': dt, 'retained_record': name,
              'production_writes': False, 'browser_ui_tested': False}
    print(json.dumps(report, ensure_ascii=False))
    (sites.parent / ('blueprint-lifecycle-' + run_id + '.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2))
finally:
    if getattr(frappe.local, 'db', None):
        frappe.db.rollback()
    frappe.destroy()
