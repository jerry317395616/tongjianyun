"""Native synthetic payables on the dedicated QA site; never production.

Only native documents post/reverse GL and Payment Ledger entries. The optional
synthetic funding Journal Entry makes cash available and is cancelled last.
There is no SQL balance/status update, broad role grant, worker or external pay.
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
assert sites == ROOT / 'sites', 'Only the dedicated QA sites path is allowed'
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
from frappe.utils import getdate, nowdate
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from erpnext.accounts.utils import get_balance_on
from tongjianyun import frappe_project_views, meal_views
from tongjianyun.meal_view_tool import use_site_os_identity

for module in (meal_views, frappe_project_views):
    assert Path(module.__file__).resolve().is_relative_to(source), 'Wrong candidate source'
use_site_os_identity(sites / SITE)
os.umask(0o077)
run_id = uuid.uuid4().hex[:10]
checks, stages, records = [], [], {}
amount = Decimal('100.00')


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal('.01'))


def check(label, condition):
    assert condition, label
    checks.append(label)
    print(json.dumps({'passed': label}, ensure_ascii=False), flush=True)


def connect():
    frappe.init(site=SITE, sites_path=str(sites))
    guard(frappe.conf)  # Effective configuration checked before DB connect.
    frappe.connect()
    frappe.set_user('Administrator')


def gl(doctype, name, active=None):
    filters = {'voucher_type': doctype, 'voucher_no': name}
    if active is not None:
        filters['is_cancelled'] = 0 if active else 1
    return frappe.get_all('GL Entry', filters=filters,
        fields=['name', 'account', 'party_type', 'party', 'debit', 'credit', 'is_cancelled',
                'against_voucher_type', 'against_voucher'], order_by='creation asc')


def net(rows, account):
    return sum((money(row.debit) - money(row.credit) for row in rows if row.account == account), Decimal(0))


def balanced(rows):
    return bool(rows) and sum((money(row.debit) - money(row.credit) for row in rows), Decimal(0)) == 0


def ple(supplier, invoice, payment=None, active=True):
    filters = {'party_type': 'Supplier', 'party': supplier,
               'against_voucher_type': 'Purchase Invoice', 'against_voucher_no': invoice}
    if payment:
        filters.update(voucher_type='Payment Entry', voucher_no=payment)
    if active:
        filters['delinked'] = 0
    return frappe.get_all('Payment Ledger Entry', filters=filters,
        fields=['name', 'voucher_type', 'voucher_no', 'against_voucher_type', 'against_voucher_no',
                'amount', 'amount_in_account_currency', 'delinked'], order_by='creation asc')


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


connect()
try:
    day = nowdate()
    companies = frappe.get_all('Company', filters={'company_name': ['like', 'QA Meal %']}, pluck='name')
    assert len(companies) == 1, 'Expected exactly one retained synthetic QA Meal Company'
    company = frappe.get_doc('Company', companies[0])
    assert company.company_name.startswith('QA Meal ')
    accounts = frappe.get_all('Account', filters={'company': company.name, 'is_group': 0, 'disabled': 0},
        fields=['name', 'account_name', 'account_type', 'root_type', 'account_currency', 'balance_must_be'])
    if '--inspect' in sys.argv:
        print(json.dumps({'synthetic_company': company.name, 'currency': company.default_currency,
            'expense': company.default_expense_account, 'payable': company.default_payable_account,
            'cost_center': company.cost_center, 'accounts': accounts,
            'unlink_payment_on_cancellation_of_invoice': frappe.get_single_value('Accounts Settings', 'unlink_payment_on_cancellation_of_invoice'),
            'retained_payables': frappe.get_all('Purchase Invoice', filters={'bill_no': ['like', 'QA-BILL-%']},
                fields=['name', 'bill_no', 'supplier', 'docstatus', 'outstanding_amount'], order_by='creation desc', limit_page_length=8)}, ensure_ascii=False))
        raise SystemExit(0)
    expense = next((row.name for row in accounts if row.account_name == 'Administrative Expenses'
                    and row.root_type == 'Expense'), None)
    payable = company.default_payable_account
    assert expense and payable and company.cost_center, 'Synthetic Company accounting defaults are incomplete'
    cash_options = sorted((row for row in accounts if row.account_type == 'Cash'
                           and (not row.account_currency or row.account_currency == company.default_currency)), key=lambda row: row.name)
    equity_options = sorted((row for row in accounts if row.account_name == 'Opening Balance Equity'
                             and row.root_type == 'Equity'), key=lambda row: row.name)
    assert cash_options and equity_options, 'Existing native Cash / Opening Balance Equity account required'
    cash, opening = cash_options[0].name, equity_options[0].name
    records.update(company=company.name, cash_account=cash, expense_account=expense, payable_account=payable)
    cash_before = money(get_balance_on(account=cash, date=day, company=company.name))
    if not frappe.db.exists('Fiscal Year', {'year_start_date': ['<=', day], 'year_end_date': ['>=', day], 'disabled': 0}):
        date = getdate(day)
        frappe.get_doc({'doctype': 'Fiscal Year', 'year': 'QA Payables ' + run_id,
            'year_start_date': str(date.replace(month=1, day=1)), 'year_end_date': str(date.replace(month=12, day=31))}).insert()
    uom = frappe.get_doc({'doctype': 'UOM', 'uom_name': 'QA Service Unit ' + run_id, 'must_be_whole_number': 1}).insert()
    item_root = frappe.db.get_value('Item Group', {'is_group': 1}, 'name')
    supplier_root = frappe.db.get_value('Supplier Group', {'is_group': 1}, 'name')
    assert item_root and supplier_root, 'Retained native group roots must exist'
    item_group = frappe.get_doc({'doctype': 'Item Group', 'item_group_name': 'QA Payables ' + run_id,
                                'parent_item_group': item_root}).insert()
    supplier_group = frappe.get_doc({'doctype': 'Supplier Group', 'supplier_group_name': 'QA Payables ' + run_id,
                                    'parent_supplier_group': supplier_root}).insert()
    supplier = frappe.get_doc({'doctype': 'Supplier', 'supplier_name': 'QA Payables ' + run_id,
        'supplier_type': 'Company', 'supplier_group': supplier_group.name,
        'accounts': [{'company': company.name, 'account': payable}]}).insert()
    item = frappe.get_doc({'doctype': 'Item', 'item_code': 'QA-SERVICE-' + run_id,
        'item_name': 'Synthetic service expense ' + run_id, 'item_group': item_group.name,
        'stock_uom': uom.name, 'is_stock_item': 0, 'is_purchase_item': 1,
        'item_defaults': [{'company': company.name, 'expense_account': expense,
                           'buying_cost_center': company.cost_center}]}).insert()
    records.update(supplier=supplier.name, item=item.name)

    # Synthetic funding only, posted/reversed through the native Journal Entry.
    funding = frappe.get_doc({'doctype': 'Journal Entry', 'voucher_type': 'Journal Entry',
        'company': company.name, 'posting_date': day, 'user_remark': 'Synthetic QA funding ' + run_id + '; no real transfer',
        'accounts': [{'account': cash, 'debit_in_account_currency': float(amount)},
                     {'account': opening, 'credit_in_account_currency': float(amount)}]}).insert()
    funding.submit()
    records['funding_journal'] = funding.name
    check('synthetic_funding_is_balanced_native_gl', balanced(gl('Journal Entry', funding.name, active=True))
          and money(get_balance_on(account=cash, date=day, company=company.name)) == cash_before + amount)
    frappe.db.commit()

    invoice = frappe.get_doc({'doctype': 'Purchase Invoice', 'company': company.name,
        'supplier': supplier.name, 'posting_date': day, 'due_date': day, 'bill_no': 'QA-BILL-' + run_id,
        'bill_date': day, 'currency': company.default_currency, 'conversion_rate': 1,
        'credit_to': payable, 'cost_center': company.cost_center, 'update_stock': 0,
        'items': [{'item_code': item.name, 'qty': 8, 'rate': 12.5, 'expense_account': expense,
                   'cost_center': company.cost_center}]}).insert()
    records['purchase_invoice'] = invoice.name
    check('draft_invoice_has_no_gl_or_stock_movement', invoice.docstatus == 0 and money(invoice.grand_total) == amount
          and not gl('Purchase Invoice', invoice.name) and not frappe.db.exists('Stock Ledger Entry', {'item_code': item.name}))
    invoice.submit()
    frappe.db.commit()
    invoice.reload()
    invoice_gl = gl('Purchase Invoice', invoice.name, active=True)
    check('invoice_native_submit_posts_balanced_expense_and_payable', invoice.docstatus == 1 and balanced(invoice_gl)
          and net(invoice_gl, expense) == amount and net(invoice_gl, payable) == -amount)
    check('invoice_has_supplier_payable_and_exact_outstanding', money(invoice.outstanding_amount) == amount
          and any(row.account == payable and row.party_type == 'Supplier' and row.party == supplier.name for row in invoice_gl))
    check('invoice_payment_ledger_records_exact_payable_reference', bool(ple(supplier.name, invoice.name))
          and abs(sum((money(row.amount) for row in ple(supplier.name, invoice.name)), Decimal(0))) == amount)
    stages.append({'stage': 'invoice_submitted', 'outstanding': float(money(invoice.outstanding_amount)),
                   'invoice_gl': invoice_gl, 'payment_ledger': ple(supplier.name, invoice.name)})

    payment = get_payment_entry('Purchase Invoice', invoice.name, bank_account=cash, reference_date=day)
    payment = frappe.get_doc(payment.as_dict())  # Same serialization boundary as native Desk.
    payment.posting_date = day
    payment.reference_no = 'QA-PAY-' + run_id
    payment.reference_date = day
    payment.insert()
    records['payment_entry'] = payment.name
    check('native_payment_mapper_keeps_invoice_supplier_and_full_allocation', payment.payment_type == 'Pay'
          and payment.party_type == 'Supplier' and payment.party == supplier.name and payment.paid_from == cash
          and payment.paid_to == payable and len(payment.references) == 1
          and payment.references[0].reference_doctype == 'Purchase Invoice'
          and payment.references[0].reference_name == invoice.name
          and money(payment.references[0].allocated_amount) == amount)
    invoice.reload()
    check('draft_payment_does_not_settle_invoice_or_post_gl', payment.docstatus == 0
          and money(invoice.outstanding_amount) == amount and not gl('Payment Entry', payment.name))
    payment.submit()
    frappe.db.commit()
    payment.reload()
    invoice.reload()
    payment_gl = gl('Payment Entry', payment.name, active=True)
    check('payment_native_submit_posts_balanced_payable_and_cash', payment.docstatus == 1 and balanced(payment_gl)
          and net(payment_gl, payable) == amount and net(payment_gl, cash) == -amount)
    check('payment_settles_exact_invoice_and_has_no_unallocated_difference', money(invoice.outstanding_amount) == 0
          and money(payment.unallocated_amount) == 0 and money(payment.difference_amount) == 0
          and money(payment.total_allocated_amount) == amount)
    settlement = ple(supplier.name, invoice.name, payment.name)
    check('payment_ledger_allocation_links_exact_invoice_and_nets_to_zero', bool(settlement)
          and abs(sum((money(row.amount) for row in settlement), Decimal(0))) == amount
          and sum((money(row.amount) for row in ple(supplier.name, invoice.name)), Decimal(0)) == 0)
    check('paid_cash_balance_returns_to_prefunding_baseline',
          money(get_balance_on(account=cash, date=day, company=company.name)) == cash_before)
    payment_ledger_before_duplicate = [row.name for row in ple(supplier.name, invoice.name)]
    def duplicate_payment():
        duplicate = frappe.copy_doc(payment)
        duplicate.reference_no = 'QA-DUPLICATE-' + run_id
        duplicate.insert()
        duplicate.submit()
    rejected('native_validation_rejects_duplicate_full_payment', duplicate_payment)
    check('rejected_duplicate_keeps_exact_original_allocation',
          money(frappe.get_doc('Purchase Invoice', invoice.name).outstanding_amount) == 0
          and [row.name for row in ple(supplier.name, invoice.name)] == payment_ledger_before_duplicate)
    stages.append({'stage': 'paid', 'outstanding': float(money(invoice.outstanding_amount)),
                   'payment_gl': payment_gl, 'payment_ledger': ple(supplier.name, invoice.name)})

    for doc in (invoice, payment):
        view = meal_views.get_view({'view': 'frappe_document', 'doctype': doc.doctype, 'document': doc.name})
        frame = next(block for block in view['components'] if block['type'] == 'frappe_frame')
        check(doc.doctype.replace(' ', '_').lower() + '_native_view_targets_exact_record',
              frame['route'] == '/desk/' + frappe_project_views.slug(doc.doctype) + '/' + quote(doc.name, safe=''))
    payment.reload()
    payment.cancel()
    frappe.db.commit()
    invoice.reload()
    check('native_payment_cancel_reopens_invoice_outstanding', frappe.get_doc('Payment Entry', payment.name).docstatus == 2
          and money(invoice.outstanding_amount) == amount)
    check('cancelled_payment_has_no_active_gl_or_allocated_payment_ledger', not gl('Payment Entry', payment.name, active=True)
          and not ple(supplier.name, invoice.name, payment.name)
          and money(get_balance_on(account=cash, date=day, company=company.name)) == cash_before + amount)
    stages.append({'stage': 'payment_cancelled', 'outstanding': float(money(invoice.outstanding_amount)),
                   'payment_gl': gl('Payment Entry', payment.name), 'payment_ledger': ple(supplier.name, invoice.name)})
    invoice.cancel()
    frappe.db.commit()
    check('native_invoice_cancel_reverses_remaining_payable_and_expense',
          frappe.get_doc('Purchase Invoice', invoice.name).docstatus == 2
          and not gl('Purchase Invoice', invoice.name, active=True) and not ple(supplier.name, invoice.name))
    cancelled_invoice = frappe.get_doc('Purchase Invoice', invoice.name)
    stages.append({'stage': 'invoice_cancelled', 'docstatus': int(cancelled_invoice.docstatus),
        'stored_outstanding_amount': float(money(cancelled_invoice.outstanding_amount)),
        'active_payable_exists': bool(ple(supplier.name, invoice.name)),
        'invoice_gl': gl('Purchase Invoice', invoice.name),
        'note': 'Cancelled document outstanding_amount can retain its prior value; active GL/PLE and docstatus determine whether payable remains.'})
    check('nonstock_expense_path_never_creates_stock_ledger', not frappe.db.exists('Stock Ledger Entry', {'item_code': item.name}))
    funding.reload()
    funding.cancel()
    frappe.db.commit()
    check('native_funding_cancel_restores_original_cash_balance',
          money(get_balance_on(account=cash, date=day, company=company.name)) == cash_before
          and not gl('Journal Entry', funding.name, active=True))
    viewer = 'payables-qa-viewer-' + run_id + '@example.invalid'
    frappe.get_doc({'doctype': 'User', 'email': viewer, 'first_name': 'Synthetic Payables QA',
        'enabled': 1, 'user_type': 'System User', 'send_welcome_email': 0, 'roles': []}).insert()
    records['ungranted_viewer'] = viewer
    frappe.set_user(viewer)
    rejected('ungranted_user_cannot_read_invoice_native_document',
             lambda: frappe.get_doc('Purchase Invoice', invoice.name).check_permission('read'), frappe.PermissionError)
    rejected('ungranted_user_cannot_create_native_payment',
             lambda: frappe.copy_doc(payment).insert(), frappe.PermissionError)
    rejected('ungranted_user_cannot_open_payment_business_view',
             lambda: meal_views.get_view({'view': 'frappe_document', 'doctype': 'Payment Entry', 'document': payment.name}),
             frappe.PermissionError)
    frappe.set_user('Administrator')
    frappe.db.commit()
    frappe.destroy()
    connect()
    check('fresh_connection_reads_all_cancelled_and_no_active_payables', all(
        frappe.get_doc(dt, name).docstatus == 2 for dt, name in (
            ('Purchase Invoice', invoice.name), ('Payment Entry', payment.name), ('Journal Entry', funding.name)))
        and not gl('Purchase Invoice', invoice.name, active=True) and not gl('Payment Entry', payment.name, active=True)
        and not ple(supplier.name, invoice.name)
        and money(get_balance_on(account=cash, date=day, company=company.name)) == cash_before)
    report = {'isolated_site': SITE, 'run_id': run_id, 'passed': len(checks), 'checks': checks, 'stages': stages,
        'retained_synthetic_records': records, 'scenario': 'single-currency non-stock expense invoice paid in full and reversed',
        'currency': company.default_currency, 'amount': float(amount), 'cash_balance_before': float(cash_before),
        'native_funding_journal_cancelled': True,
        'unlink_payment_on_cancellation_of_invoice': frappe.get_single_value('Accounts Settings', 'unlink_payment_on_cancellation_of_invoice'),
        'production_writes': False, 'browser_ui_tested': False,
        'real_payment_sent': False, 'all_finance_covered': False, 'native_accounting_source_modified': False}
    (ROOT / ('payables-lifecycle-' + run_id + '.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))
except Exception as error:
    report = {'isolated_site': SITE, 'run_id': run_id, 'passed_before_failure': len(checks), 'checks': checks,
              'stages': stages, 'retained_synthetic_records': records, 'outcome': 'incomplete',
              'error_type': type(error).__name__, 'failed_step': str(error), 'production_writes': False}
    (ROOT / ('payables-lifecycle-incomplete-' + run_id + '.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False), flush=True)
    raise
finally:
    if getattr(frappe.local, 'db', None):
        frappe.db.rollback()
    frappe.destroy()
