"""Real source-bound inventory verification/repair on the fixed QA site only."""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

SITE = 'unified-business-acceptance.localhost'
ROOT = Path('/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925').resolve()
sites = Path(os.environ['UNIFIED_BUSINESS_SITES']).resolve(strict=True)
source = Path(os.environ['UNIFIED_BUSINESS_SOURCE']).resolve(strict=True)
assert sites == ROOT / 'sites', 'Only the dedicated isolated sites directory is permitted'
config = {**json.loads((sites / 'common_site_config.json').read_text()),
          **json.loads((sites / SITE / 'site_config.json').read_text())}


def guard(conf):
    assert conf.get('unified_business_acceptance') == 1
    assert conf.get('db_host') == '127.0.0.1' and int(conf.get('db_port', 0)) == 23316
    assert conf.get('db_name') == 'tgy_blueprint_qa'
    assert conf.get('db_user', conf.get('db_name')) == 'tgy_blueprint_qa'
    assert not conf.get('db_socket') and not conf.get('developer_mode')
    assert conf.get('pause_scheduler') == 1 and conf.get('disable_scheduler') == 1
    for key in ('redis_cache', 'redis_queue', 'redis_socketio'):
        endpoint = urlparse(conf.get(key) or '')
        assert endpoint.scheme == 'redis' and endpoint.hostname == '127.0.0.1' and endpoint.port == 23379


guard(config)
for key in list(os.environ):
    if key.startswith(('FRAPPE_DB_', 'FRAPPE_REDIS_')):
        os.environ.pop(key)
os.environ['FRAPPE_BENCH_ROOT'] = str(ROOT)
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.dont_write_bytecode = True
sys.path.insert(0, str(source))
os.chdir(sites)

import frappe
from frappe.utils import nowdate
from werkzeug.wrappers import Request
from erpnext.stock.doctype.purchase_receipt.mapper import make_purchase_return
from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import execute_reposting_entry
from tongjianyun import stock_operations as service
from tongjianyun.meal_view_tool import use_site_os_identity

assert Path(service.__file__).resolve().is_relative_to(source), 'Wrong candidate source'
use_site_os_identity(sites / SITE)
os.umask(0o077)
run_id = uuid.uuid4().hex[:10]
checks, records, snapshots = [], {}, []


def check(label, condition):
    assert condition, label
    checks.append(label)
    print(json.dumps({'passed': label}, ensure_ascii=False), flush=True)


def denied(label, action, exception=frappe.ValidationError):
    point = 'reject_' + uuid.uuid4().hex[:8]
    frappe.db.savepoint(point)
    try:
        action()
    except exception:
        frappe.db.rollback(save_point=point)
        check(label, True)
        return
    raise AssertionError(label + ': unexpected success')


def connect():
    frappe.init(site=SITE, sites_path=str(sites))
    guard(frappe.conf)
    frappe.connect()
    frappe.set_user('Administrator')
    frappe.local.request = Request.from_values(method='POST')


def inspect(doc):
    result = service.inspect_stock(doc.doctype, doc.name)
    snapshots.append(result)
    return result


def repair(doc, snapshot, **overrides):
    values = dict(source_doctype=doc.doctype, source_name=doc.name, revision=snapshot['revision'],
        targets=[{'item_code': row['item_code'], 'warehouse': row['warehouse']} for row in snapshot['rows']],
        confirm='recalculate')
    values.update(overrides)
    return service.repair_stock(**values)


def child_probe(mode, payload):
    """Separate connection; fixed QA guard and exact synthetic-item gate above."""
    connect()
    try:
        doc = frappe.get_doc(payload['doctype'], payload['name'])
        assert doc.doctype in service.SOURCES and doc.company.startswith('QA Meal ')
        assert doc.items and all(row.item_code == payload['item'] for row in doc.items)
        assert payload['item'].startswith('QA-VERIFY-')
        assert frappe.get_doc('Item', payload['item']).item_name.startswith('Synthetic stock repair ')
        assert payload['warehouse'].startswith('QA Verify ')
        if mode == '--race-repair':
            try:
                result = service.repair_stock(doc.doctype, doc.name,
                    [{'item_code': payload['item'], 'warehouse': payload['warehouse']}],
                    payload['revision'], confirm='recalculate')
                frappe.db.commit()
                print(json.dumps({'outcome': 'recalculated', 'inspection': result['inspection']}), flush=True)
            except frappe.ValidationError:
                frappe.db.rollback()
                print(json.dumps({'outcome': 'stale_rejected'}), flush=True)
            except frappe.QueryDeadlockError:
                frappe.db.rollback()
                print(json.dumps({'outcome': 'concurrent_conflict_rejected'}), flush=True)
        elif mode == '--native-writer':
            # Session-only short wait: no runtime or server setting is changed.
            frappe.db.sql('set session innodb_lock_wait_timeout = 1')
            stage = 'construct'
            try:
                company = frappe.get_doc('Company', doc.company)
                entry = frappe.get_doc({'doctype': 'Stock Entry', 'stock_entry_type': payload['entry_type'],
                    'purpose': 'Material Receipt', 'company': doc.company, 'posting_date': nowdate(),
                    'items': [{'item_code': payload['item'], 'qty': 1, 't_warehouse': payload['warehouse'],
                               'basic_rate': 3, 'expense_account': company.default_expense_account,
                               'cost_center': company.cost_center}]}).insert()
                stage = 'native_submit'
                entry.submit()
                print(json.dumps({'outcome': 'native_writer_completed_then_rolled_back', 'stage': stage}), flush=True)
            except (frappe.QueryTimeoutError, frappe.QueryDeadlockError) as exc:
                print(json.dumps({'outcome': 'native_writer_lock_blocked', 'stage': stage,
                                  'exception': type(exc).__name__}), flush=True)
        elif mode == '--po-writer':
            # Observation only: preserve the exact native get_bin return and
            # write path, notify the parent when its stale snapshot was read.
            # The parent's real Bin row lock, not this wrapper, blocks the SQL.
            import erpnext.stock.utils as stock_utils
            original_get_bin = stock_utils.get_bin

            def observed_get_bin(item_code, warehouse):
                bin_doc = original_get_bin(item_code, warehouse)
                if item_code == payload['item'] and warehouse == payload['warehouse']:
                    print(json.dumps({'event': 'native_po_read_bin', 'stock_value': bin_doc.stock_value,
                                      'actual_qty': bin_doc.actual_qty}), flush=True)
                return bin_doc

            from erpnext.buying.doctype.purchase_order.purchase_order import update_status
            frappe.db.sql('set session innodb_lock_wait_timeout = 8')
            order = frappe.get_doc('Purchase Order', payload['order'])
            assert order.company == doc.company and order.docstatus == 1
            assert all(row.item_code == payload['item'] and row.warehouse == payload['warehouse'] for row in order.items)
            try:
                stock_utils.get_bin = observed_get_bin
                update_status('Closed', order.name)
            except frappe.QueryDeadlockError as exc:
                frappe.db.rollback()
                print(json.dumps({'outcome': 'native_po_conflict_rejected', 'order': order.name,
                                  'exception': type(exc).__name__, 'message': str(exc)}), flush=True)
                return
            finally:
                stock_utils.get_bin = original_get_bin
            frappe.db.commit()
            print(json.dumps({'outcome': 'native_po_committed', 'order': order.name}), flush=True)
        else:
            raise AssertionError('Unknown isolated probe')
    finally:
        frappe.db.rollback()
        frappe.destroy()


if len(sys.argv) > 1:
    assert len(sys.argv) == 3
    child_probe(sys.argv[1], json.loads(sys.argv[2]))
    raise SystemExit(0)


def start_probe(mode, payload):
    return subprocess.Popen([sys.executable, __file__, mode, json.dumps(payload)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def read_probe(process):
    output, errors = process.communicate(timeout=25)
    assert process.returncode == 0, errors[-1800:]
    return json.loads(output.strip().splitlines()[-1])


connect()
try:
    database_protection = {'version': frappe.db.sql('select version()')[0][0],
        'transaction_isolation': frappe.db.sql('select @@tx_isolation')[0][0],
        'innodb_snapshot_isolation': frappe.db.sql('select @@innodb_snapshot_isolation')[0][0]}
    print(json.dumps({'database_protection': database_protection}), flush=True)
    companies = frappe.get_all('Company', filters={'company_name': ['like', 'QA Meal %']}, pluck='name')
    assert len(companies) == 1, 'Only retained synthetic Company can be used'
    company = frappe.get_doc('Company', companies[0])
    assert company.company_name.startswith('QA Meal ')
    uom = frappe.get_doc({'doctype': 'UOM', 'uom_name': 'QA Verify Unit ' + run_id,
                         'must_be_whole_number': 1}).insert()
    ig_root = frappe.db.get_value('Item Group', {'is_group': 1}, 'name')
    sg_root = frappe.db.get_value('Supplier Group', {'is_group': 1}, 'name')
    assert ig_root and sg_root
    item_group = frappe.get_doc({'doctype': 'Item Group', 'item_group_name': 'QA Verify ' + run_id,
        'parent_item_group': ig_root}).insert()
    supplier_group = frappe.get_doc({'doctype': 'Supplier Group', 'supplier_group_name': 'QA Verify ' + run_id,
        'parent_supplier_group': sg_root}).insert()
    supplier = frappe.get_doc({'doctype': 'Supplier', 'supplier_name': 'QA Verify ' + run_id,
        'supplier_type': 'Company', 'supplier_group': supplier_group.name}).insert()
    warehouse_parent = frappe.db.get_value('Warehouse', {'company': company.name, 'is_group': 1}, 'name')
    assert warehouse_parent
    warehouse = frappe.get_doc({'doctype': 'Warehouse', 'warehouse_name': 'QA Verify ' + run_id,
        'company': company.name, 'parent_warehouse': warehouse_parent, 'is_group': 0}).insert()
    item = frappe.get_doc({'doctype': 'Item', 'item_code': 'QA-VERIFY-' + run_id,
        'item_name': 'Synthetic stock repair ' + run_id, 'item_group': item_group.name,
        'stock_uom': uom.name, 'is_stock_item': 1, 'is_purchase_item': 1, 'valuation_method': 'FIFO',
        'item_defaults': [{'company': company.name, 'default_warehouse': warehouse.name,
            'buying_cost_center': company.cost_center, 'expense_account': company.default_expense_account}]}).insert()
    records.update(company=company.name, item=item.name, supplier=supplier.name, warehouse=warehouse.name)
    original = frappe.get_doc({'doctype': 'Purchase Receipt', 'company': company.name,
        'supplier': supplier.name, 'posting_date': nowdate(), 'currency': company.default_currency,
        'conversion_rate': 1, 'items': [{'item_code': item.name, 'qty': 5, 'received_qty': 5,
            'rate': 3, 'warehouse': warehouse.name}]}).insert()
    records['receipt'] = original.name
    draft = inspect(original)
    check('draft_no_actual_stock_or_false_completion', draft['summary']['status'] == 'not_posted'
          and not draft['can_repair'] and not draft['rows'])
    original.submit()
    initial = inspect(original)
    check('receipt_exact_source_and_pair', initial['source_name'] == original.name
          and initial['rows'][0]['item_code'] == item.name and initial['rows'][0]['warehouse'] == warehouse.name)
    check('native_receipt_consistent_quantity_and_value', initial['summary']['status'] == 'consistent'
          and initial['rows'][0]['bin_qty'] == 5 and initial['rows'][0]['bin_value'] == 15
          and initial['currency'] == company.default_currency and not initial['can_repair'])
    denied('healthy_bin_cannot_be_recalculated', lambda: repair(original, initial))

    returned = make_purchase_return(original.name)
    returned.items[0].qty = -2
    returned.items[0].received_qty = -2
    returned = frappe.get_doc(returned.as_dict()).insert()
    returned.submit()
    records['return'] = returned.name
    returned.cancel()
    pending = inspect(returned)
    check('cancel_return_reproduces_stale_native_stock_value', pending['rows'][0]['bin_qty'] == 5
          and pending['rows'][0]['bin_value'] == 9 and pending['rows'][0]['ledger_value'] == 15)
    check('unfinished_revaluation_blocks_completion', pending['summary']['status'] == 'pending'
          and pending['pending_revaluations'] and not pending['can_repair'])
    denied('pending_job_cannot_be_bypassed_by_explicit_confirmation', lambda: repair(returned, pending))
    for job in pending['pending_revaluations']:
        doc = frappe.get_doc('Repost Item Valuation', job['name'])
        assert doc.company == company.name
        assert (doc.item_code == item.name and doc.warehouse == warehouse.name) or (
            doc.voucher_type == 'Purchase Receipt' and doc.voucher_no in {original.name, returned.name})
        old_flag, old_max = frappe.flags.through_repost_item_valuation, frappe.db.MAX_WRITES_PER_TRANSACTION
        try:
            execute_reposting_entry(doc.name)
        finally:
            frappe.flags.through_repost_item_valuation = old_flag
            frappe.db.MAX_WRITES_PER_TRANSACTION = old_max
    ready = inspect(returned)
    check('completed_native_job_does_not_hide_stale_bin', not ready['pending_revaluations']
          and ready['summary']['status'] == 'mismatch' and ready['can_repair']
          and ready['rows'][0]['bin_value'] == 9 and ready['rows'][0]['ledger_value'] == 15)
    denied('old_pending_snapshot_revision_rejected', lambda: repair(returned, pending))
    denied('missing_explicit_confirmation_rejected', lambda: repair(returned, ready, confirm=None))
    denied('unrelated_target_rejected', lambda: repair(returned, ready,
        targets=[{'item_code': 'not-this-source', 'warehouse': warehouse.name}]))
    denied('bin_name_injection_rejected', lambda: repair(returned, ready,
        targets=[{'item_code': item.name, 'warehouse': warehouse.name, 'name': ready['rows'][0]['bin_name']}]))
    frappe.local.request = Request.from_values(method='GET')
    denied('get_request_cannot_repair', lambda: repair(returned, ready))
    frappe.local.request = Request.from_values(method='POST')

    reader = frappe.get_doc({'doctype': 'User', 'email': 'qa-stock-reader-' + run_id + '@example.invalid',
        'first_name': 'Synthetic Stock Reader', 'enabled': 1, 'send_welcome_email': 0,
        'user_type': 'System User', 'roles': [{'role': 'Stock Manager'}, {'role': 'Purchase Manager'},
                                            {'role': 'Stock User'}]}).insert()
    records['reader'] = reader.name
    frappe.set_user(reader.name)
    readable = inspect(returned)
    check('native_read_roles_can_inspect_but_not_gain_bin_write', readable['summary']['status'] == 'mismatch'
          and not readable['can_repair'] and not frappe.get_doc('Bin', readable['rows'][0]['bin_name']).has_permission('write'))
    denied('native_read_user_cannot_repair', lambda: repair(returned, readable),
           (frappe.PermissionError, frappe.ValidationError))
    frappe.set_user('Guest')
    denied('guest_cannot_inspect', lambda: service.inspect_stock(returned.doctype, returned.name), frappe.PermissionError)
    denied('guest_cannot_repair', lambda: repair(returned, ready), frappe.PermissionError)
    frappe.set_user('Administrator')
    check('all_rejected_operations_leave_stale_evidence_unchanged', inspect(returned)['rows'][0]['bin_value'] == 9)
    reader.reload()
    reader.enabled = 0
    reader.save()
    frappe.set_user(reader.name)
    denied('disabled_actor_cannot_inspect_even_with_retained_roles',
           lambda: service.inspect_stock(returned.doctype, returned.name), frappe.PermissionError)
    denied('disabled_actor_cannot_repair_even_with_prior_revision', lambda: repair(returned, readable), frappe.PermissionError)
    frappe.set_user('Administrator')

    # Exercise the non-SLE native writer race. Only this exact QA DB's snapshot
    # isolation is proven to reject its stale whole-row write. The observation
    # wrapper does not change native returned values, calculation, or writes.
    racing_order = frappe.get_doc({'doctype': 'Purchase Order', 'company': company.name,
        'supplier': supplier.name, 'transaction_date': nowdate(), 'schedule_date': nowdate(),
        'currency': company.default_currency, 'conversion_rate': 1,
        'items': [{'item_code': item.name, 'qty': 2, 'rate': 3,
                   'schedule_date': nowdate(), 'warehouse': warehouse.name}]}).insert()
    racing_order.submit()
    records['racing_order'] = racing_order.name
    race_before = inspect(returned)
    frappe.db.commit()
    locked_source = service._source(returned.doctype, returned.name, lock=True)
    service._lock_pairs(service._source_pairs(locked_source, lock=True))
    service._snapshot(locked_source, lock=True)
    po_probe_args = {'doctype': returned.doctype, 'name': returned.name, 'item': item.name,
                     'warehouse': warehouse.name, 'order': racing_order.name}
    po_writer = start_probe('--po-writer', po_probe_args)
    observed_line = po_writer.stdout.readline()
    assert observed_line, po_writer.stderr.read()[-1800:]
    po_read = json.loads(observed_line)
    check('native_po_writer_reads_old_bin_before_waiting_for_real_row_lock',
          po_read['event'] == 'native_po_read_bin' and po_read['stock_value'] == 9)
    transient_repair = repair(returned, race_before)
    check('repair_temporarily_correct_before_native_po_waiter_released',
          transient_repair['inspection']['rows'][0]['bin_value'] == 15)
    frappe.db.commit()
    po_result = read_probe(po_writer)
    frappe.db.rollback()
    overwritten = inspect(returned)
    check('qa_snapshot_isolation_rejects_native_po_stale_whole_bin_overwrite',
          po_result['outcome'] == 'native_po_conflict_rejected' and overwritten['rows'][0]['bin_value'] == 15
          and overwritten['rows'][0]['ledger_value'] == 15)
    records['racing_order'] = po_result['order']
    racing_order = frappe.get_doc('Purchase Order', po_result['order'])
    racing_order.cancel()
    frappe.db.commit()

    # Make a new real native cancellation defect; do not SQL-reset Bin to force
    # another repair. The prior race result remains retained independently.
    second_return = make_purchase_return(original.name)
    second_return.items[0].qty = -2
    second_return.items[0].received_qty = -2
    second_return = frappe.get_doc(second_return.as_dict()).insert()
    second_return.submit()
    second_return.cancel()
    records['second_return'] = second_return.name
    for job in inspect(second_return)['pending_revaluations']:
        current = frappe.get_doc('Repost Item Valuation', job['name'])
        assert current.company == company.name and (
            current.item_code == item.name and current.warehouse == warehouse.name
            or current.voucher_type == 'Purchase Receipt' and current.voucher_no in {original.name, returned.name, second_return.name})
        old_flag, old_max = frappe.flags.through_repost_item_valuation, frappe.db.MAX_WRITES_PER_TRANSACTION
        try:
            execute_reposting_entry(current.name)
        finally:
            frappe.flags.through_repost_item_valuation = old_flag
            frappe.db.MAX_WRITES_PER_TRANSACTION = old_max

    before = inspect(returned)
    derived_fields = ['planned_qty', 'indented_qty', 'ordered_qty', 'reserved_qty',
                      'reserved_qty_for_production', 'reserved_qty_for_sub_contract',
                      'reserved_qty_for_production_plan', 'projected_qty']
    derived_before = frappe.db.get_value('Bin', before['rows'][0]['bin_name'], derived_fields, as_dict=True)
    frappe.db.commit()
    probe_args = {'doctype': returned.doctype, 'name': returned.name, 'item': item.name,
                  'warehouse': warehouse.name, 'revision': before['revision']}
    racers = [start_probe('--race-repair', probe_args) for _ in range(2)]
    race = [read_probe(process) for process in racers]
    check('concurrent_same_revision_repair_commits_exactly_once',
          sum(result['outcome'] == 'recalculated' for result in race) == 1
          and all(result['outcome'] in {'recalculated', 'stale_rejected', 'concurrent_conflict_rejected'} for result in race))
    frappe.db.rollback()  # Refresh this connection's snapshot after the winner committed.
    repaired = inspect(returned)
    check('adapter_calls_native_recalculation_and_reads_back', repaired['summary']['status'] == 'consistent'
          and repaired['rows'][0]['bin_qty'] == 5 and repaired['rows'][0]['bin_value'] == 15
          and not repaired['can_repair'])
    derived_after = frappe.db.get_value('Bin', repaired['rows'][0]['bin_name'], derived_fields, as_dict=True)
    check('native_full_recalculation_preserves_correct_other_derived_totals', derived_before == derived_after
          and derived_after.projected_qty == 5
          and all(derived_after[field] == 0 for field in derived_fields if field != 'projected_qty'))
    check('source_remains_cancelled_and_original_quantities_unchanged',
          frappe.get_doc('Purchase Receipt', returned.name).docstatus == 2
          and frappe.get_doc('Purchase Receipt', original.name).items[0].qty == 5)
    comments = frappe.get_all('Comment', filters={'reference_doctype': returned.doctype,
        'reference_name': returned.name, 'comment_type': 'Info'}, fields=['content', 'owner'])
    check('repair_has_actor_and_revision_linked_source_audit', any(before['revision'] in row.content
          and row.owner == 'Administrator' for row in comments))
    denied('duplicate_repair_with_old_revision_is_rejected', lambda: repair(returned, before))
    healthy = inspect(returned)
    denied('duplicate_repair_with_fresh_revision_is_unnecessary_and_rejected', lambda: repair(returned, healthy))

    entry_type = frappe.get_doc({'doctype': 'Stock Entry Type', 'name': 'QA Receipt ' + run_id,
                                'purpose': 'Material Receipt'}).insert()
    records['stock_entry_type'] = entry_type.name
    frappe.db.commit()
    locked_source = service._source(returned.doctype, returned.name, lock=True)
    service._lock_pairs(service._source_pairs(locked_source, lock=True))
    service._snapshot(locked_source, lock=True)
    lock_probe = read_probe(start_probe('--native-writer', dict(probe_args, entry_type=entry_type.name)))
    check('native_concurrent_stock_submit_blocked_while_repair_scope_locked',
          lock_probe['outcome'] == 'native_writer_lock_blocked' and lock_probe['stage'] == 'native_submit')
    frappe.db.rollback()
    released_probe = read_probe(start_probe('--native-writer', dict(probe_args, entry_type=entry_type.name)))
    check('native_stock_submit_can_continue_after_repair_locks_release',
          released_probe['outcome'] == 'native_writer_completed_then_rolled_back')
    check('rolled_back_concurrency_probe_preserves_repaired_stock', inspect(returned)['rows'][0]['bin_value'] == 15)
    entry = frappe.get_doc({'doctype': 'Stock Entry', 'stock_entry_type': entry_type.name,
        'purpose': 'Material Receipt', 'company': company.name, 'posting_date': nowdate(),
        'items': [{'item_code': item.name, 'qty': 1, 't_warehouse': warehouse.name,
                   'basic_rate': 3, 'expense_account': company.default_expense_account,
                   'cost_center': company.cost_center}]}).insert()
    entry.submit()
    records['stock_entry'] = entry.name
    entry_view = inspect(entry)
    check('stock_entry_uses_same_controlled_source_adapter', entry_view['source_doctype'] == 'Stock Entry'
          and entry_view['source_name'] == entry.name and entry_view['rows'][0]['bin_qty'] == 6
          and entry_view['summary']['status'] == 'consistent')
    frappe.db.commit()
    frappe.destroy()
    connect()
    reread = inspect(frappe.get_doc('Purchase Receipt', returned.name))
    check('fresh_connection_current_ledger_bin_and_prior_source_consistent', reread['summary']['status'] == 'consistent'
          and reread['rows'][0]['bin_qty'] == 6 and reread['rows'][0]['bin_value'] == 18
          and reread['rows'][0]['last_effective_sle']['name'] == entry_view['rows'][0]['last_effective_sle']['name'])
    report = {'run_id': run_id, 'checks': checks, 'records': records, 'snapshots': snapshots,
        'native_flow_defect_preserved': {'source': returned.name, 'observed_bin_value': 9,
            'expected_ledger_value': 15, 'pending_and_completed_job_snapshots_retained': True},
        'repair': {'service': 'Bin.recalculate_values', 'quantity_before_after': [5, 5],
                   'value_before_after': [9, 15], 'production_writes': False,
                   'other_native_derived_before': derived_before, 'other_native_derived_after': derived_after},
        'database_protection': database_protection,
        'release_gate': 'repairs permitted only in fixed isolated site; production diagnostics read-only',
        'concurrency': {'duplicate_repair': race, 'native_writer_while_locked': lock_probe,
                        'native_writer_after_release': released_probe,
                        'qa_native_po_whole_bin_write_conflict': {'reader': po_read, 'writer': po_result,
                            'value_before_repair': 9, 'value_after_repair_before_release': 15,
                            'value_after_native_po_attempt': overwritten['rows'][0]['bin_value']}},
        'limitations': ['FIFO fixture; serial/batch/Standard Cost and large-history scope not acceptance tested',
                       'Native planned/ordered/reserved/projected are also recalculated; fixture keeps them unchanged',
                       'PO Close contention tested only on recorded QA database configuration',
                       'Concurrent MR/Sales Order/manufacturing/reservation writers not end-to-end tested']}
    path = ROOT / ('stock-operations-' + run_id + '.json')
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n')
    print(json.dumps({'run_id': run_id, 'passed': len(checks), 'report': str(path)}, ensure_ascii=False), flush=True)
finally:
    frappe.db.rollback()
    frappe.destroy()
