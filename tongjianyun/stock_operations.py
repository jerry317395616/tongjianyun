"""Source-bound stock verification and explicit native Bin recalculation.

No stock posting, queue draining, arbitrary Bin target, permission elevation or
SQL value updates. The repair is one request transaction; callers must not
commit a failed operation. ERPNext remains the authority for recalculation.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import math
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

import frappe

SOURCES = frozenset({'Purchase Receipt', 'Stock Entry'})
MAX_PAIRS = 20
MAX_LEDGER = 2000
MAX_REPOSTS = 1000
SUPPORTED_METHODS = frozenset({'FIFO', 'Moving Average'})
LEDGER_FIELDS = ('name', 'modified', 'creation', 'docstatus', 'item_code', 'warehouse',
                 'posting_datetime', 'voucher_type', 'voucher_no', 'actual_qty',
                 'qty_after_transaction', 'valuation_rate', 'stock_value', 'is_cancelled')
BIN_FIELDS = ('name', 'modified', 'item_code', 'warehouse', 'actual_qty', 'stock_value',
              'valuation_rate', 'stock_uom', 'planned_qty', 'indented_qty', 'ordered_qty',
              'reserved_qty', 'reserved_qty_for_production', 'reserved_qty_for_sub_contract',
              'reserved_qty_for_production_plan', 'reserved_stock', 'projected_qty')
REPOST_FIELDS = ('name', 'modified', 'docstatus', 'based_on', 'item_code', 'warehouse',
                 'voucher_type', 'voucher_no', 'status', 'company')
QA_SITE = 'unified-business-acceptance.localhost'
QA_SITE_PATH = '/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925/sites/' + QA_SITE
REPAIR_GATE_REASON = '当前仅开放库存核验；原生并发写入尚未完成生产验收，重算仅允许在专用隔离验收站点执行'


def _repair_environment():
    """Hard release gate, not an admin-configurable production enable flag.

    Native ordered/reserved writers can read Bin before waiting on its lock.
    The QA DB rejects their stale whole-row writes using snapshot isolation;
    production concurrency must be separately proven before opening repair.
    """
    conf = frappe.conf
    try:
        allowed = (frappe.local.site == QA_SITE and str(Path(frappe.get_site_path()).resolve()) == QA_SITE_PATH
            and conf.get('unified_business_acceptance') == 1 and conf.get('db_host') == '127.0.0.1'
            and int(conf.get('db_port', 0)) == 23316 and conf.get('db_name') == 'tgy_blueprint_qa'
            and conf.get('db_user', conf.get('db_name')) == 'tgy_blueprint_qa'
            and not conf.get('db_socket') and conf.get('pause_scheduler') == 1
            and conf.get('disable_scheduler') == 1 and not conf.get('developer_mode'))
        for field in ('redis_cache', 'redis_queue', 'redis_socketio'):
            endpoint = urlparse(conf.get(field) or '')
            allowed = allowed and endpoint.scheme == 'redis' and endpoint.hostname == '127.0.0.1' \
                and endpoint.port == 23379
        return bool(allowed)
    except (TypeError, ValueError, OSError):
        return False


def _fail(message):
    raise frappe.ValidationError(message)


def _access():
    if not frappe.session.user or frappe.session.user == 'Guest':
        raise frappe.PermissionError('请登录后核验库存')
    # Cached roles can outlive account disabling, especially direct tool calls.
    if frappe.db.get_value('User', frappe.session.user, 'enabled') != 1:
        raise frappe.PermissionError('当前账号已停用，不能核验或重算库存')


def _text(value, label):
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 140 \
            or any(ord(char) < 32 for char in value):
        _fail('无效的' + label)
    return value


def _source(doctype, name, lock=False):
    if not isinstance(doctype, str) or doctype not in SOURCES:
        _fail('只支持采购收货单（含退货）或库存单的库存核验')
    _text(name, '来源单据')
    doc = frappe.get_doc(doctype, name, for_update=lock)
    doc.check_permission('read')
    _read_fields(doc, ('company',))
    return doc


def _read_fields(doc, fields):
    """Do not expose amounts hidden by native field-level/mask permissions."""
    if frappe.session.user == 'Administrator':
        return
    levels = doc.get_permlevel_access('read')
    masked = {field.fieldname for field in doc.meta.get_masked_fields()}
    for field in fields:
        df = doc.meta.get_field(field)
        if field in masked or (df and df.permlevel and df.permlevel not in levels):
            raise frappe.PermissionError('核验所需字段受原生读取权限限制')


def _values(doc, fields):
    return {field: doc.get(field) for field in fields}


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), default=str, allow_nan=False).encode()).hexdigest()


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        _fail('库存记录含无效数值，请交由管理员检查')
    if not math.isfinite(number):
        _fail('库存记录含非有限数值，请交由管理员检查')
    return number


def _matches(left, right):
    # SLE and Bin both persist Float values. Avoid binary-float noise while not
    # hiding currency-sized discrepancies or using a percent-relative tolerance.
    try:
        return abs(Decimal(str(_number(left))) - Decimal(str(_number(right)))) <= Decimal('0.000001')
    except InvalidOperation:
        return False


def _query(doctype, fields, condition, maximum, lock=False, order=None):
    table = frappe.qb.DocType(doctype)
    query = frappe.qb.from_(table).select(*(table[field] for field in fields)).where(condition(table))
    if order:
        from frappe.query_builder import Order
        for field in order:
            query = query.orderby(table[field], order=Order.desc)
    query = query.limit(maximum + 1)
    if lock:
        query = query.for_update()
    rows = query.run(as_dict=True)
    if len(rows) > maximum:
        _fail('核验范围超出单次受限处理上限，请使用原生库存审计工具')
    return rows


def _check_rows(doctype, rows, lock=False):
    # get_all/query-builder is only used to find a COMPLETE scope. Every found
    # row then crosses native document permissions; hidden jobs cannot look done.
    for row in rows:
        doc = frappe.get_doc(doctype, row['name'], for_update=lock)
        doc.check_permission('read')
        _read_fields(doc, row.keys())


def _source_pairs(doc, lock=False):
    rows = _query('Stock Ledger Entry', ('name', 'item_code', 'warehouse'),
        lambda t: (t.voucher_type == doc.doctype) & (t.voucher_no == doc.name), MAX_LEDGER, lock)
    _check_rows('Stock Ledger Entry', rows, lock)
    pairs = sorted({(row['item_code'], row['warehouse']) for row in rows})
    if len(pairs) > MAX_PAIRS:
        _fail('来源单据涉及过多库存位置，请使用原生库存审计工具')
    return pairs


def _related_reposts(pairs, ledgers, lock=False):
    if not pairs:
        return []
    vouchers = {(row['voucher_type'], row['voucher_no']) for rows in ledgers.values() for row in rows}

    def condition(t):
        predicate = None
        for item, warehouse in pairs:
            clause = (t.based_on == 'Item and Warehouse') & (t.item_code == item) & (t.warehouse == warehouse)
            predicate = clause if predicate is None else predicate | clause
        if vouchers:
            # Filter voucher_type below as names may overlap across DocTypes.
            predicate |= (t.based_on == 'Transaction') & t.voucher_no.isin(sorted({name for _, name in vouchers}))
        return predicate

    candidates = _query('Repost Item Valuation', REPOST_FIELDS, condition, MAX_REPOSTS, lock)
    rows = [row for row in candidates if row['based_on'] == 'Item and Warehouse'
            or (row['voucher_type'], row['voucher_no']) in vouchers]
    _check_rows('Repost Item Valuation', rows, lock)
    return sorted(rows, key=lambda row: row['name'])


def _pending(rows):
    return [row for row in rows if int(row['docstatus']) != 2
            and (int(row['docstatus']) != 1 or row['status'] not in {'Completed', 'Skipped'})]


def _snapshot(doc, lock=False):
    from erpnext.stock.utils import get_valuation_method

    company = frappe.get_doc('Company', doc.company, for_update=lock)
    company.check_permission('read')
    _read_fields(company, ('default_currency',))
    pairs = _source_pairs(doc, lock)
    rows, ledgers, bin_docs, inputs = [], {}, {}, []
    for item_code, warehouse in pairs:
        item = frappe.get_doc('Item', item_code, for_update=lock)
        store = frappe.get_doc('Warehouse', warehouse, for_update=lock)
        item.check_permission('read')
        store.check_permission('read')
        _read_fields(item, ('stock_uom', 'valuation_method'))
        _read_fields(store, ('company',))
        ledger = _query('Stock Ledger Entry', LEDGER_FIELDS,
            lambda t: (t.item_code == item_code) & (t.warehouse == warehouse), MAX_LEDGER, lock,
            order=('posting_datetime', 'creation'))
        _check_rows('Stock Ledger Entry', ledger, lock)
        ledgers[(item_code, warehouse)] = ledger
        bins = _query('Bin', ('name',), lambda t: (t.item_code == item_code) & (t.warehouse == warehouse), 1, lock)
        bin_doc = frappe.get_doc('Bin', bins[0]['name'], for_update=lock) if bins else None
        if bin_doc:
            bin_doc.check_permission('read')
            _read_fields(bin_doc, BIN_FIELDS)
            bin_docs[(item_code, warehouse)] = bin_doc
        latest = next((entry for entry in ledger if not entry['is_cancelled']), None)
        ledger_qty = _number(latest['qty_after_transaction']) if latest else 0
        ledger_value = _number(latest['stock_value']) if latest else 0
        bin_qty = _number(bin_doc.actual_qty) if bin_doc else None
        bin_value = _number(bin_doc.stock_value) if bin_doc else None
        method = get_valuation_method(item_code)
        quantity_matches = bool(bin_doc and _matches(bin_qty, ledger_qty))
        value_matches = bool(bin_doc and _matches(bin_value, ledger_value))
        reason = ''
        if not bin_doc:
            reason = '缺少原生库存记录，不能由核验接口新建'
        elif method not in SUPPORTED_METHODS:
            reason = '此估值方法需使用原生专项核验，本入口不进行重算'
        elif quantity_matches and value_matches:
            reason = '库存数量及金额与最后有效流水一致'
        elif not doc.has_permission('write') or not bin_doc.has_permission('write'):
            reason = '当前账号没有来源单据及 Bin 的原生写权限，仅可核验'
        rows.append({'item_code': item_code, 'warehouse': warehouse, 'stock_uom': item.stock_uom,
            'bin_name': bin_doc.name if bin_doc else None, 'bin_qty': bin_qty, 'ledger_qty': ledger_qty,
            'bin_value': bin_value, 'ledger_value': ledger_value, 'quantity_matches': quantity_matches,
            'value_matches': value_matches, 'valuation_method': method, 'can_repair': not reason,
            'reason': reason, 'last_effective_sle': ({'name': latest['name'],
                'posting_datetime': str(latest['posting_datetime']), 'quantity': ledger_qty,
                'value': ledger_value} if latest else None)})
        inputs.append({'item': _values(item, ('name', 'modified', 'valuation_method', 'stock_uom')),
            'warehouse': _values(store, ('name', 'modified', 'company')), 'valuation_method': method,
            'bin': _values(bin_doc, BIN_FIELDS) if bin_doc else None, 'ledger': ledger})
    reposts = _related_reposts(pairs, ledgers, lock)
    pending = _pending(reposts)
    warnings = []
    if not _repair_environment():
        warnings.append(REPAIR_GATE_REASON)
        for row in rows:
            if row['can_repair']:
                row['reason'] = REPAIR_GATE_REASON
            row['can_repair'] = False
    if pending:
        warnings.append('关联库存重估尚未完成或已失败；不能宣称库存金额已完成，也不能执行此重算')
        for row in rows:
            row.update(can_repair=False, reason=warnings[-1])
    if int(doc.docstatus) == 0:
        warnings.append('来源单据尚未提交，不代表已发生库存变动')
        for row in rows:
            row.update(can_repair=False, reason=warnings[-1])
    elif not rows:
        warnings.append('来源单据没有可核验的库存流水，不能推断库存已完成')
    mismatched = sum(not row['quantity_matches'] or not row['value_matches'] for row in rows)
    unsupported = any(row['valuation_method'] not in SUPPORTED_METHODS or not row['bin_name'] for row in rows)
    status = ('not_posted' if int(doc.docstatus) == 0 else 'pending' if pending else
              'blocked' if unsupported or not rows else 'mismatch' if mismatched else 'consistent')
    revision = _hash({'version': 1, 'user': frappe.session.user, 'source': doc.as_dict(),
                      'currency': company.default_currency, 'inputs': inputs, 'reposts': reposts})
    output = {'source_doctype': doc.doctype, 'source_name': doc.name, 'source_docstatus': int(doc.docstatus),
        'company': company.name, 'currency': company.default_currency,
        'revision': revision, 'rows': rows, 'pending_revaluations': [
            {'name': row['name'], 'status': row['status'], 'docstatus': row['docstatus']} for row in pending],
        'can_repair': any(row['can_repair'] for row in rows), 'warnings': warnings,
        'summary': {'checked_pairs': len(rows), 'mismatched_pairs': mismatched, 'status': status}}
    return output, bin_docs, _hash({'source': doc.as_dict(), 'ledger': inputs_to_ledgers(inputs), 'reposts': reposts})


def inputs_to_ledgers(inputs):
    return [{key: value for key, value in item.items() if key != 'bin'} for item in inputs]


@frappe.whitelist()
def inspect_stock(source_doctype, source_name):
    _access()
    return _snapshot(_source(source_doctype, source_name))[0]


def _targets(value):
    if isinstance(value, str):
        if len(value.encode()) > 16384:
            _fail('重算目标过大')
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            _fail('重算目标须为已核验的物料及仓库')
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_PAIRS:
        _fail('请选择本次核验中需要重算的库存位置')
    pairs = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {'item_code', 'warehouse'}:
            _fail('目标仅接受物料和仓库，不接受任意 Bin 或其他字段')
        pairs.append((_text(row['item_code'], '物料'), _text(row['warehouse'], '仓库')))
    if len(set(pairs)) != len(pairs):
        _fail('不能重复选择库存位置')
    return sorted(pairs)


def _lock_pairs(pairs):
    from erpnext.stock.stock_ledger import sle_processing_gate

    # This deployment uses MariaDB REPEATABLE READ next-key locks. Do not claim
    # phantom protection on another DB/isolation level without separate testing.
    if frappe.db.db_type != 'mariadb':
        _fail('当前数据库尚未完成此重算入口的并发验收，请使用原生工具')
    isolation = frappe.db.sql('select @@tx_isolation')[0][0]
    if str(isolation).upper().replace('_', '-') not in {'REPEATABLE-READ', 'SERIALIZABLE'}:
        _fail('数据库隔离级别不足以安全锁定库存范围')
    if frappe.db.sql('select @@innodb_snapshot_isolation')[0][0] != 1:
        _fail('当前数据库缺少已验证的旧快照写入保护，不能执行重算')
    for item_code, warehouse in pairs:
        sle_processing_gate(item_code, warehouse)
        _query('Stock Ledger Entry', ('name',),
            lambda t: (t.item_code == item_code) & (t.warehouse == warehouse), MAX_LEDGER, True)


@frappe.whitelist(methods=['POST'])
def repair_stock(source_doctype, source_name, targets, revision, confirm=None):
    _access()
    if getattr(frappe.request, 'method', None) != 'POST':
        _fail('库存重算必须通过明确确认的 POST 请求')
    if confirm != 'recalculate':
        _fail('请明确确认原生库存重算')
    if not isinstance(revision, str) or len(revision) != 64 or any(c not in '0123456789abcdef' for c in revision):
        _fail('缺少有效核验版本，请重新核验')
    requested = _targets(targets)
    if not _repair_environment():
        _fail(REPAIR_GATE_REASON)
    # Check source permissions before taking locks on any inventory.
    source = _source(source_doctype, source_name)
    source.check_permission('write')
    point = 'stock_recalculate_' + uuid.uuid4().hex[:12]
    frappe.db.savepoint(point)
    try:
        source = _source(source_doctype, source_name, lock=True)
        source.check_permission('write')
        pairs = _source_pairs(source, lock=True)
        if not set(requested).issubset(set(pairs)):
            _fail('重算目标不属于此来源单据，必须重新核验')
        _lock_pairs(pairs)
        before, bins, immutable = _snapshot(source, lock=True)
        if not hmac.compare_digest(before['revision'], revision):
            _fail('库存或单据已发生变化，请重新核验；未执行重算')
        allowed = {(row['item_code'], row['warehouse']) for row in before['rows'] if row['can_repair']}
        if not set(requested).issubset(allowed):
            _fail('目标存在未完成重估、权限不足或无需重算，未执行操作')
        for pair in requested:
            bins[pair].check_permission('write')
            bins[pair].recalculate_values()
        after, _, after_immutable = _snapshot(_source(source_doctype, source_name, lock=True), lock=True)
        selected = [row for row in after['rows'] if (row['item_code'], row['warehouse']) in requested]
        if immutable != after_immutable or after['pending_revaluations'] or len(selected) != len(requested) \
                or not all(row['quantity_matches'] and row['value_matches'] for row in selected):
            _fail('原生重算后的回读未通过，已撤回本次重算，请重新核验')
        # Native Comment supplies a source-linked, actor-attributed audit trail;
        # source contents/status are not changed and no independent commit occurs.
        source.add_comment('Info', '童健云库存核验：显式确认后调用 Bin.recalculate_values（同时重算计划、订购、预留及预计等原生库存汇总）；核验版本 '
            + revision + '；目标 ' + html.escape(json.dumps(
                [{'item_code': i, 'warehouse': w} for i, w in requested], ensure_ascii=False)))
        return {'status': 'recalculated', 'before_revision': revision,
                'targets': [{'item_code': i, 'warehouse': w} for i, w in requested], 'inspection': after}
    except Exception as exc:
        # MariaDB aborts the WHOLE transaction on deadlock, removing savepoints.
        # Do not mask that original conflict with "SAVEPOINT does not exist".
        if isinstance(exc, frappe.QueryDeadlockError):
            frappe.db.rollback()
        else:
            frappe.db.rollback(save_point=point)
        raise
