"""Real native fixed-asset acquisition, capitalization, movement and reversal.

Writes only synthetic documents in the exact isolated QA database. No accounting
or asset state is set through SQL, no native validator/permission is bypassed,
and no production configuration, worker, scheduler or ERPNext source is changed.
Successful and incomplete evidence stays in the private QA root.
"""
import json
import os
import sys
import uuid
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote, urlparse

SITE = 'unified-business-acceptance.localhost'
ROOT = Path('/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925').resolve()
sites = Path(os.environ['UNIFIED_BUSINESS_SITES']).resolve(strict=True)
source = Path(os.environ['UNIFIED_BUSINESS_SOURCE']).resolve(strict=True)
assert sites == ROOT / 'sites', 'Only the dedicated QA sites directory is allowed'
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
from frappe.utils import add_to_date, getdate, nowdate
from erpnext.accounts.utils import get_balance_on
from tongjianyun import asset_history, frappe_project_views, meal_views
from tongjianyun.meal_view_tool import use_site_os_identity

for module in (asset_history, meal_views, frappe_project_views):
    assert Path(module.__file__).resolve().is_relative_to(source), 'Wrong candidate source'
use_site_os_identity(sites / SITE)
os.umask(0o077)
run_id = uuid.uuid4().hex[:10]
checks, stages, records, observed_defects = [], [], {}, []
amount = Decimal('1200.00')
automatic = '--auto-create' in sys.argv
source_doctype = 'Purchase Invoice' if '--source-invoice' in sys.argv else 'Purchase Receipt'
source_field = 'purchase_invoice' if source_doctype == 'Purchase Invoice' else 'purchase_receipt'
source_item_field = source_field + '_item'
assert '--draft-boundaries' not in sys.argv or automatic, 'Draft boundaries require --auto-create'


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal('.01'))


def check(label, condition):
    assert condition, label
    checks.append(label)
    print(json.dumps({'passed': label}, ensure_ascii=False), flush=True)


def connect():
    frappe.init(site=SITE, sites_path=str(sites))
    guard(frappe.conf)  # Recheck effective configuration BEFORE connecting.
    frappe.connect()
    frappe.set_user('Administrator')


def gl(doctype, name, active=None):
    filters = {'voucher_type': doctype, 'voucher_no': name}
    if active is not None:
        filters['is_cancelled'] = 0 if active else 1
    return frappe.get_all('GL Entry', filters=filters,
        fields=['name', 'account', 'debit', 'credit', 'is_cancelled'], order_by='creation asc')


def net(rows, account):
    return sum((money(row.debit) - money(row.credit) for row in rows if row.account == account), Decimal(0))


def balanced(rows):
    return bool(rows) and sum((money(row.debit) - money(row.credit) for row in rows), Decimal(0)) == 0


def rejected(label, action, exception=frappe.ValidationError):
    point = 'reject_' + uuid.uuid4().hex[:8]
    frappe.db.savepoint(point)
    try:
        action()
    except exception:
        frappe.db.rollback(save_point=point)
        check(label, True)
        return
    raise AssertionError(label + ': unexpected success')


def movements(asset, active=None):
    names = frappe.get_all('Asset Movement Item', filters={'asset': asset}, pluck='parent')
    if not names:
        return []
    filters = {'name': ['in', names]}
    if active is not None:
        filters['docstatus'] = 1 if active else 2
    return frappe.get_all('Asset Movement', filters=filters,
        fields=['name', 'purpose', 'docstatus', 'transaction_date', 'reference_doctype', 'reference_name'],
        order_by='transaction_date asc, name asc')


def movement_snapshot(name):
    doc = frappe.get_doc('Asset Movement', name)
    return {**{key: doc.get(key) for key in ('name', 'docstatus', 'company', 'purpose',
        'transaction_date', 'reference_doctype', 'reference_name', 'creation', 'modified', 'owner')},
        'assets': [{key: row.get(key) for key in ('name', 'asset', 'source_location', 'target_location',
            'from_employee', 'to_employee', 'parent', 'idx')} for row in doc.assets]}


connect()
try:
    if '--unit-tests' in sys.argv:
        import unittest
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName(
            'tongjianyun.tests.test_asset_history'))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    if '--inspect-run' in sys.argv:
        inspection_id = sys.argv[sys.argv.index('--inspect-run') + 1]
        assert len(inspection_id) == 10 and all(value in '0123456789abcdef' for value in inspection_id)
        evidence_file = ROOT / ('asset-lifecycle-' + inspection_id + '.json')
        if not evidence_file.exists():
            evidence_file = ROOT / ('asset-lifecycle-incomplete-' + inspection_id + '.json')
        previous = json.loads(evidence_file.read_text())['retained_synthetic_records']
        assert previous['item'] == 'QA-ASSET-' + inspection_id
        snapshots = {}
        prior_type = previous.get('source_doctype', 'Purchase Receipt')
        prior_key = 'purchase_invoice' if prior_type == 'Purchase Invoice' else 'purchase_receipt'
        for key, doctype in [(prior_key, prior_type), ('asset', 'Asset'),
                             ('initial_receipt_movement', 'Asset Movement'), ('transfer', 'Asset Movement')]:
            if key not in previous:
                continue
            name = previous[key]
            snapshots[key] = {'exists': bool(frappe.db.exists(doctype, name))}
            if snapshots[key]['exists']:
                document = frappe.get_doc(doctype, name)
                snapshots[key].update(docstatus=document.docstatus, status=document.get('status'),
                    location=document.get('location'), gl=gl(doctype, name))
        if previous.get('asset'):
            snapshots['asset_movements'] = movements(previous['asset'])
        snapshots['assets_for_exact_synthetic_item'] = frappe.get_all('Asset', filters={'item_code': previous['item']},
            fields=['name', 'docstatus', 'purchase_receipt', 'purchase_invoice'])
        print(json.dumps({'inspection_run_id': inspection_id, 'snapshots': snapshots}, default=str))
        raise SystemExit(0)
    # A new process and QA-only hook cache refresh must use the actual installed
    # extension. Never monkeypatch a controller to make the lifecycle pass.
    frappe.cache.delete_value('app_hooks')
    from frappe.model.base_document import get_controller
    for kind in ('Purchase Receipt', 'Purchase Invoice'):
        check(kind.replace(' ', '_').lower() + '_loads_candidate_history_extension',
              issubclass(get_controller(kind), asset_history.PreserveAssetHistory))
    day = nowdate()
    companies = frappe.get_all('Company', filters={'company_name': ['like', 'QA Meal %']}, pluck='name')
    assert len(companies) == 1, 'Expected exactly one retained synthetic QA Meal Company'
    company = frappe.get_doc('Company', companies[0])
    assert company.company_name.startswith('QA Meal ')
    accounts = frappe.get_all('Account', filters={'company': company.name, 'is_group': 0, 'disabled': 0},
        fields=['name', 'account_name', 'account_type', 'account_currency'])
    fixed = next((row.name for row in accounts if row.account_name == 'Capital Equipment'
                  and row.account_type == 'Fixed Asset'), None)
    cwip = next((row.name for row in accounts if row.account_type == 'Capital Work in Progress'), None)
    received = company.default_payable_account if source_doctype == 'Purchase Invoice' else company.asset_received_but_not_billed
    assert fixed and cwip and received and company.cost_center, 'Retained Company asset accounts required'
    asset_accounts = (fixed, cwip, received)
    baseline = {account: money(get_balance_on(account=account, date=day, company=company.name))
                for account in asset_accounts}
    records.update(company=company.name, fixed_asset_account=fixed, cwip_account=cwip,
                   acquisition_liability_account=received, source_doctype=source_doctype,
                   auto_create_assets=automatic)
    if not frappe.db.exists('Fiscal Year', {'year_start_date': ['<=', day], 'year_end_date': ['>=', day], 'disabled': 0}):
        date = getdate(day)
        frappe.get_doc({'doctype': 'Fiscal Year', 'year': 'QA Asset ' + run_id,
            'year_start_date': str(date.replace(month=1, day=1)),
            'year_end_date': str(date.replace(month=12, day=31))}).insert()
    uom = frappe.get_doc({'doctype': 'UOM', 'uom_name': 'QA Asset Unit ' + run_id, 'must_be_whole_number': 1}).insert()
    item_root = frappe.db.get_value('Item Group', {'is_group': 1}, 'name')
    supplier_root = frappe.db.get_value('Supplier Group', {'is_group': 1}, 'name')
    assert item_root and supplier_root, 'Retained native group roots required'
    item_group = frappe.get_doc({'doctype': 'Item Group', 'item_group_name': 'QA Assets ' + run_id,
                                'parent_item_group': item_root}).insert()
    supplier_group = frappe.get_doc({'doctype': 'Supplier Group', 'supplier_group_name': 'QA Assets ' + run_id,
                                    'parent_supplier_group': supplier_root}).insert()
    supplier = frappe.get_doc({'doctype': 'Supplier', 'supplier_name': 'QA Assets ' + run_id,
        'supplier_type': 'Company', 'supplier_group': supplier_group.name}).insert()
    category = frappe.get_doc({'doctype': 'Asset Category', 'asset_category_name': 'QA Asset CWIP ' + run_id,
        'enable_cwip_accounting': 1, 'non_depreciable_category': 1,
        'accounts': [{'company_name': company.name, 'fixed_asset_account': fixed,
                      'capital_work_in_progress_account': cwip}]}).insert()
    locations = [frappe.get_doc({'doctype': 'Location', 'location_name': 'QA Asset ' + suffix + ' ' + run_id,
                                'is_group': 0}).insert().name for suffix in ('Receiving', 'Classroom')]
    item = frappe.get_doc({'doctype': 'Item', 'item_code': 'QA-ASSET-' + run_id,
        'item_name': 'Synthetic fixed asset ' + run_id, 'item_group': item_group.name,
        'stock_uom': uom.name, 'is_stock_item': 0, 'is_fixed_asset': 1, 'is_purchase_item': 1,
        'asset_category': category.name, 'auto_create_assets': int(automatic),
        'asset_naming_series': 'ACC-ASS-.YYYY.-',
        'item_defaults': [{'company': company.name, 'buying_cost_center': company.cost_center,
                           'expense_account': company.default_expense_account}]}).insert()
    records.update(supplier=supplier.name, category=category.name, locations=locations, item=item.name)

    receipt = frappe.get_doc({'doctype': source_doctype, 'company': company.name,
        'supplier': supplier.name, 'posting_date': day, 'posting_time': '09:00:00', 'set_posting_time': 1,
        'currency': company.default_currency, 'conversion_rate': 1,
        'cost_center': company.cost_center,
        **({'update_stock': 1, 'due_date': day, 'bill_no': 'QA-ASSET-' + run_id,
            'credit_to': received} if source_doctype == 'Purchase Invoice' else {}),
        'items': [{'item_code': item.name, 'qty': 1, 'rate': float(amount),
                   'asset_location': locations[0], 'cost_center': company.cost_center}]}).insert()
    records[source_field] = receipt.name
    check('draft_fixed_asset_receipt_has_no_gl_asset_or_stock_ledger', receipt.docstatus == 0
          and not gl(receipt.doctype, receipt.name)
          and not frappe.db.exists('Asset', {source_field: receipt.name})
          and not frappe.db.exists('Stock Ledger Entry', {'item_code': item.name}))
    receipt.submit()
    frappe.db.commit()
    receipt.reload()
    receipt_gl = gl(receipt.doctype, receipt.name, active=True)
    check('acquisition_posts_native_balanced_cwip_and_exact_liability', receipt.docstatus == 1
          and balanced(receipt_gl) and net(receipt_gl, cwip) == amount and net(receipt_gl, received) == -amount)
    generated = frappe.get_all('Asset', filters={source_field: receipt.name}, pluck='name')
    check('native_auto_creation_matches_item_policy', len(generated) == (1 if automatic else 0))
    stages.append({'stage': 'receipt_submitted', 'receipt_gl': receipt_gl})

    if '--draft-boundaries' in sys.argv:
        assert automatic, 'Draft boundaries require --auto-create'
        # An unused automatically-created draft still follows native deletion;
        # the extension must not simply disable all acquisition cleanup.
        first_draft = generated[0]
        check('unused_auto_draft_has_no_movement_history', not movements(first_draft))
        receipt.cancel()
        frappe.db.commit()
        check('unused_auto_draft_is_deleted_by_native_cleanup_and_gl_reversed',
              not frappe.db.exists('Asset', first_draft) and not gl(source_doctype, receipt.name, active=True))
        second = frappe.copy_doc(receipt).insert()
        second.submit()
        frappe.db.commit()
        records.update(deleted_unused_draft=first_draft, second_acquisition=second.name)
        second_asset_name = frappe.db.get_value('Asset', {source_field: second.name}, 'name')
        assert second_asset_name, 'Native automatic creation must produce a draft for the second source'
        # Native draft deletion can revert the naming series; reuse is not loss
        # of history because this first unused draft had no movement records.
        records['unused_draft_name_reused'] = second_asset_name == first_draft
        records['retained_draft'] = second_asset_name
        second_asset = frappe.get_doc('Asset', second_asset_name)
        check('second_acquisition_creates_another_native_draft', second.docstatus == 1 and second_asset.docstatus == 0)
        def receipt_movement(when, source_reference):
            return frappe.get_doc({'doctype': 'Asset Movement', 'company': company.name, 'purpose': 'Receipt',
                'transaction_date': when,
                **({'reference_doctype': source_doctype, 'reference_name': second.name} if source_reference else {}),
                'assets': [{'asset': second_asset_name, 'target_location': locations[0]}]}).insert()
        historic = receipt_movement(day + ' 10:00:00', True)
        records['draft_history_movement'] = historic.name
        historic.submit()
        historic.cancel()
        active = receipt_movement(day + ' 10:01:00', False)
        records['draft_guarded_movement'] = active.name
        active.submit()
        frappe.db.commit()
        historical_snapshot = movement_snapshot(historic.name)
        rejected('auto_draft_with_submitted_unreferenced_movement_refuses_acquisition_cancel',
                 lambda: frappe.get_doc(source_doctype, second.name).cancel())
        check('refused_cancel_retains_draft_active_and_cancelled_movement_and_acquisition_gl',
              frappe.get_doc(source_doctype, second.name).docstatus == 1
              and frappe.get_doc('Asset', second_asset_name).docstatus == 0
              and frappe.get_doc('Asset Movement', active.name).docstatus == 1
              and movement_snapshot(historic.name) == historical_snapshot
              and balanced(gl(source_doctype, second.name, active=True)))
        active.reload()
        active.cancel()
        frappe.db.commit()
        snapshots = [movement_snapshot(name) for name in (historic.name, active.name)]
        second.reload()
        second.cancel()
        frappe.db.commit()
        second_asset.reload()
        check('auto_draft_with_cancelled_history_is_retained_and_source_detached',
              second_asset.docstatus == 0 and not second_asset.get(source_field) and not second_asset.supplier
              and second_asset.item_code == item.name and money(second_asset.net_purchase_amount) == amount)
        check('draft_history_retains_exact_parent_child_source_and_timestamps',
              [movement_snapshot(name) for name in (historic.name, active.name)] == snapshots)
        records.update(deleted_unused_draft=first_draft, second_acquisition=second.name,
            retained_draft=second_asset_name, cancelled_draft_movements=[historic.name, active.name])
        frappe.destroy()
        connect()
        check('fresh_connection_retains_draft_history_and_both_cancelled_acquisitions',
              frappe.get_doc(source_doctype, receipt.name).docstatus == 2
              and frappe.get_doc(source_doctype, second.name).docstatus == 2
              and (first_draft == second_asset_name or not frappe.db.exists('Asset', first_draft))
              and frappe.get_doc('Asset', second_asset_name).docstatus == 0
              and not frappe.get_doc('Asset', second_asset_name).get(source_field)
              and [movement_snapshot(name) for name in (historic.name, active.name)] == snapshots)
        check('draft_boundaries_restore_preexisting_account_balances_without_asset_gl',
              not gl(source_doctype, receipt.name, active=True) and not gl(source_doctype, second.name, active=True)
              and not gl('Asset', first_draft) and not gl('Asset', second_asset_name)
              and all(money(get_balance_on(account=account, date=day, company=company.name)) == baseline[account]
                      for account in asset_accounts))
        report = {'isolated_site': SITE, 'run_id': run_id, 'passed': len(checks), 'checks': checks,
            'retained_synthetic_records': records, 'scenario': 'Native automatic draft cleanup and cancelled movement preservation',
            'source_doctype': source_doctype, 'auto_create_assets': automatic,
            'movement_snapshots': snapshots, 'native_financial_reversal_complete': True,
            'account_balances_before': {key: float(value) for key, value in baseline.items()},
            'all_movement_history_preserved': True, 'production_writes': False, 'real_payment_sent': False,
            'browser_ui_tested': False, 'native_asset_source_modified': False}
        (ROOT / ('asset-draft-boundaries-' + run_id + '.json')).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str))
        print(json.dumps(report, ensure_ascii=False, default=str), flush=True)
        raise SystemExit(0)

    asset_values = {'doctype': 'Asset', 'naming_series': 'ACC-ASS-.YYYY.-',
        'asset_name': 'QA Native Asset ' + run_id, 'company': company.name,
        'item_code': item.name, 'asset_category': category.name, 'asset_quantity': 1,
        'asset_owner': 'Company', 'location': locations[0], 'supplier': supplier.name,
        'purchase_date': day, 'available_for_use_date': day, 'calculate_depreciation': 0,
        source_field: receipt.name, source_item_field: receipt.items[0].name,
        'purchase_amount': float(amount), 'net_purchase_amount': float(amount),
        'cost_center': company.cost_center}
    if automatic:
        asset = frappe.get_doc('Asset', generated[0])
        asset.available_for_use_date = day
        asset.cost_center = company.cost_center
        asset.save()
    else:
        asset = frappe.get_doc(asset_values).insert()
    records['asset'] = asset.name
    check('draft_asset_preserves_exact_acquisition_row_and_value', asset.docstatus == 0
          and asset.get(source_field) == receipt.name and asset.get(source_item_field) == receipt.items[0].name
          and asset.item_code == item.name and money(asset.net_purchase_amount) == amount
          and not gl('Asset', asset.name) and not movements(asset.name))
    rejected('native_asset_quantity_validation_rejects_duplicate_from_same_receipt',
             lambda: frappe.copy_doc(asset).insert())
    asset.submit()
    frappe.db.commit()
    asset.reload()
    asset_gl = gl('Asset', asset.name, active=True)
    check('asset_submit_capitalizes_exact_native_cwip_amount', asset.docstatus == 1 and asset.status == 'Submitted'
          and asset.booked_fixed_asset == 1 and balanced(asset_gl)
          and net(asset_gl, fixed) == amount and net(asset_gl, cwip) == -amount)
    initial_movements = movements(asset.name, active=True)
    check('asset_submit_creates_native_receipt_movement_with_exact_source', len(initial_movements) == 1
          and initial_movements[0].purpose == 'Receipt'
          and initial_movements[0].reference_doctype == source_doctype
          and initial_movements[0].reference_name == receipt.name and asset.location == locations[0])
    records['initial_receipt_movement'] = initial_movements[0].name
    check('receipt_plus_asset_gl_has_no_residual_cwip_and_one_capitalization',
          net(receipt_gl + asset_gl, cwip) == 0 and net(receipt_gl + asset_gl, fixed) == amount
          and net(receipt_gl + asset_gl, received) == -amount)
    rejected('native_receipt_cancel_refuses_still_submitted_asset',
             lambda: frappe.get_doc(source_doctype, receipt.name).cancel())
    check('blocked_receipt_cancel_keeps_source_and_asset_submitted',
          frappe.get_doc(source_doctype, receipt.name).docstatus == 1
          and frappe.get_doc('Asset', asset.name).docstatus == 1)
    stages.append({'stage': 'asset_capitalized', 'asset_gl': asset_gl, 'movements': initial_movements})

    def transfer(source_location, target_location, when):
        return frappe.get_doc({'doctype': 'Asset Movement', 'company': company.name, 'purpose': 'Transfer',
            'transaction_date': when, 'reference_doctype': source_doctype, 'reference_name': receipt.name,
            'assets': [{'asset': asset.name, 'source_location': source_location, 'target_location': target_location}]})

    movement_time = add_to_date(initial_movements[0].transaction_date, minutes=1, as_datetime=True)
    rejected('native_transfer_rejects_wrong_source_location',
             lambda: transfer(locations[1], locations[0], movement_time).insert())
    rejected('native_transfer_rejects_same_source_and_destination',
             lambda: transfer(locations[0], locations[0], movement_time).insert())
    rejected('native_transfer_rejects_backdated_movement',
             lambda: transfer(locations[0], locations[1],
                 add_to_date(initial_movements[0].transaction_date, minutes=-1, as_datetime=True)).insert())
    move = transfer(locations[0], locations[1], movement_time).insert()
    records['transfer'] = move.name
    check('draft_movement_does_not_move_asset', frappe.get_doc('Asset', asset.name).location == locations[0]
          and move.docstatus == 0)
    move.submit()
    frappe.db.commit()
    asset.reload()
    check('native_transfer_submit_updates_location_and_preserves_capitalization', asset.location == locations[1]
          and money(asset.net_purchase_amount) == amount and asset.docstatus == 1
          and len(movements(asset.name, active=True)) == 2 and gl('Asset', asset.name, active=True) == asset_gl
          and not gl('Asset Movement', move.name))
    # Native auto_make_assets uses db_insert (no "Asset created" activity).
    # Both modes must still retain Receipt movement, submission and Transfer.
    activity_before_cancel = frappe.get_all('Asset Activity', filters={'asset': asset.name}, pluck='name')
    check('native_asset_activity_records_submit_and_movements_for_creation_mode',
          len(activity_before_cancel) >= (3 if automatic else 4))
    stages.append({'stage': 'asset_transferred', 'location': asset.location, 'movements': movements(asset.name)})

    for doc in (asset, move, receipt):
        view = meal_views.get_view({'view': 'frappe_document', 'doctype': doc.doctype, 'document': doc.name})
        frame = next(block for block in view['components'] if block['type'] == 'frappe_frame')
        check(doc.doctype.replace(' ', '_').lower() + '_business_view_targets_exact_native_record',
              frame['route'] == '/desk/' + frappe_project_views.slug(doc.doctype) + '/' + quote(doc.name, safe=''))

    viewer = 'asset-qa-viewer-' + run_id + '@example.invalid'
    frappe.get_doc({'doctype': 'User', 'email': viewer, 'first_name': 'Synthetic Asset QA',
        'enabled': 1, 'user_type': 'System User', 'send_welcome_email': 0, 'roles': []}).insert()
    records['ungranted_viewer'] = viewer
    frappe.set_user(viewer)
    rejected('ungranted_user_cannot_read_native_asset',
             lambda: frappe.get_doc('Asset', asset.name).check_permission('read'), frappe.PermissionError)
    rejected('ungranted_user_cannot_create_native_asset_movement',
             lambda: transfer(locations[1], locations[0],
                 add_to_date(movement_time, minutes=1, as_datetime=True)).insert(), frappe.PermissionError)
    rejected('ungranted_user_cannot_cancel_native_asset_movement',
             lambda: frappe.get_doc('Asset Movement', move.name).cancel(), frappe.PermissionError)
    rejected('ungranted_user_cannot_cancel_acquisition',
             lambda: frappe.get_doc(source_doctype, receipt.name).cancel(), frappe.PermissionError)
    rejected('ungranted_user_cannot_open_asset_business_view',
             lambda: meal_views.get_view({'view': 'frappe_document', 'doctype': 'Asset', 'document': asset.name}),
             frappe.PermissionError)
    frappe.set_user('Administrator')
    check('denied_actions_keep_asset_location_and_active_movement_unchanged',
          frappe.get_doc('Asset', asset.name).location == locations[1]
          and frappe.get_doc('Asset Movement', move.name).docstatus == 1)
    move.reload()
    move.cancel()
    frappe.db.commit()
    asset.reload()
    check('native_transfer_cancel_restores_previous_location', move.docstatus == 2
          and asset.location == locations[0] and len(movements(asset.name, active=True)) == 1)
    check('movement_cancel_does_not_reverse_asset_capitalization',
          gl('Asset', asset.name, active=True) == asset_gl and asset.booked_fixed_asset == 1)
    stages.append({'stage': 'transfer_cancelled', 'location': asset.location, 'movements': movements(asset.name)})

    asset.cancel()
    frappe.db.commit()
    asset.reload()
    check('native_asset_cancel_reverses_capitalization_and_cancels_receipt_movement',
          asset.docstatus == 2 and asset.status == 'Cancelled' and asset.booked_fixed_asset == 0
          and not gl('Asset', asset.name, active=True) and not movements(asset.name, active=True))
    check('asset_cancel_preserves_original_acquisition_document_until_separate_cancellation',
          frappe.get_doc(source_doctype, receipt.name).docstatus == 1
          and gl(source_doctype, receipt.name, active=True) == receipt_gl
          and money(get_balance_on(account=cwip, date=day, company=company.name)) == baseline[cwip] + amount)
    cancelled_movements_before_receipt = movements(asset.name)
    history_snapshots = [movement_snapshot(row.name) for row in cancelled_movements_before_receipt]
    check('asset_cancel_retains_both_cancelled_movement_documents_before_receipt_cancel',
          len(cancelled_movements_before_receipt) == 2
          and all(row.docstatus == 2 for row in cancelled_movements_before_receipt))
    receipt.reload()
    receipt.cancel()
    frappe.db.commit()
    check('native_receipt_cancel_reverses_acquisition_gl_and_retains_cancelled_asset',
          frappe.get_doc(source_doctype, receipt.name).docstatus == 2
          and not gl(source_doctype, receipt.name, active=True)
          and frappe.get_doc('Asset', asset.name).docstatus == 2)
    retained_movements = movements(asset.name)
    deleted_movements = [dict(row) for row in cancelled_movements_before_receipt
                         if not frappe.db.exists('Asset Movement', row.name)]
    check('acquisition_cancel_preserves_every_cancelled_movement_and_exact_source',
          not deleted_movements and retained_movements == cancelled_movements_before_receipt
          and len(retained_movements) == 2 and all(row.docstatus == 2 for row in retained_movements))
    check('acquisition_cancel_retains_exact_movement_rows_and_timestamps',
          [movement_snapshot(row.name) for row in retained_movements] == history_snapshots)
    check('acquisition_cancel_retains_preexisting_native_asset_activities',
          all(frappe.db.exists('Asset Activity', name) for name in activity_before_cancel))
    check('fixed_asset_flow_never_creates_stock_ledger_or_depreciation_schedule',
          not frappe.db.exists('Stock Ledger Entry', {'item_code': item.name})
          and not frappe.db.exists('Asset Depreciation Schedule', {'asset': asset.name}))
    stages.append({'stage': 'asset_and_receipt_cancelled', 'asset_gl': gl('Asset', asset.name),
                   'receipt_gl': gl(source_doctype, receipt.name), 'movements': movements(asset.name)})

    frappe.destroy()
    connect()
    check('fresh_connection_reads_exact_cancelled_source_asset_and_movements',
          frappe.get_doc(source_doctype, receipt.name).docstatus == 2
          and frappe.get_doc('Asset', asset.name).docstatus == 2
          and frappe.get_doc('Asset', asset.name).get(source_field) == receipt.name
          and frappe.get_doc('Asset', asset.name).get(source_item_field) == receipt.items[0].name
          and not movements(asset.name, active=True)
          and len(movements(asset.name, active=False)) == 2
          and movements(asset.name) == cancelled_movements_before_receipt
          and [movement_snapshot(row.name) for row in movements(asset.name)] == history_snapshots)
    check('fresh_connection_has_no_active_gl_and_restores_all_asset_account_balances',
          not gl('Asset', asset.name, active=True) and not gl(source_doctype, receipt.name, active=True)
          and all(money(get_balance_on(account=account, date=day, company=company.name)) == baseline[account]
                  for account in asset_accounts))
    report = {'isolated_site': SITE, 'run_id': run_id, 'passed': len(checks), 'checks': checks, 'stages': stages,
        'retained_synthetic_records': records, 'scenario': 'CWIP fixed asset acquisition, native capitalization, location transfer and full reversal',
        'source_doctype': source_doctype, 'auto_create_assets': automatic,
        'currency': company.default_currency, 'amount': float(amount),
        'account_balances_before': {key: float(value) for key, value in baseline.items()},
        'observed_defects': observed_defects, 'native_financial_reversal_complete': True,
        'all_movement_history_preserved': not bool(deleted_movements),
        'production_writes': False, 'browser_ui_tested': False, 'real_payment_sent': False,
        'all_assets_covered': False, 'native_asset_source_modified': False,
        'not_tested': ['depreciation posting', 'asset disposal or sale', 'asset repair or maintenance',
                       'custodian employee issue and return', 'revaluation', 'grouped assets', 'multi-currency acquisition']}
    (ROOT / ('asset-lifecycle-' + run_id + '.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(report, ensure_ascii=False, default=str), flush=True)
except Exception as error:
    report = {'isolated_site': SITE, 'run_id': run_id, 'passed_before_failure': len(checks), 'checks': checks,
              'stages': stages, 'retained_synthetic_records': records, 'observed_defects': observed_defects, 'outcome': 'incomplete',
              'error_type': type(error).__name__, 'failed_step': str(error), 'production_writes': False}
    (ROOT / ('asset-lifecycle-incomplete-' + run_id + '.json')).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(report, ensure_ascii=False, default=str), flush=True)
    raise
finally:
    if getattr(frappe.local, 'db', None):
        frappe.db.rollback()
    frappe.destroy()
