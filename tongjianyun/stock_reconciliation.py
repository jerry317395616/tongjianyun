"""A source-voucher-bound inventory check, with an explicit repair action.

Opening this view never writes stock. Values and eligible targets come only
from the permission-checked stock service, not from model-provided amounts.
"""
import frappe

FIELDS = {'source_doctype', 'source_name'}


def selection(value):
    if set(value) - {'view', *FIELDS}:
        frappe.throw('库存核对只接受来源单据，不支持任意物料、仓库或组件筛选。')
    kind, name = value.get('source_doctype'), value.get('source_name')
    if kind not in ('Purchase Receipt', 'Stock Entry'):
        frappe.throw('请选择采购收货单或库存凭证进行核对。')
    if not isinstance(name, str) or not name.strip() or len(name) > 140 or any(ord(char) < 32 for char in name):
        frappe.throw('请指定准确的来源单据编号。')
    return {'view': 'stock_reconciliation', 'source_doctype': kind, 'source_name': name.strip()}


def get_view(choice):
    from tongjianyun.stock_operations import inspect_stock
    info = inspect_stock(choice['source_doctype'], choice['source_name'])
    rows, summary = info['rows'], info['summary']
    currency = info.get('currency') or '本位币'
    statuses = {'not_posted': '尚未过账', 'pending': '重估待完成', 'mismatch': '发现差异',
                'consistent': '本次核对一致', 'blocked': '暂不能修复'}
    components = [
        {'type': 'stats', 'items': [
            {'label': '核对物料与仓库组合', 'value': summary['checked_pairs'], 'unit': '组'},
            {'label': '存在差异', 'value': summary['mismatched_pairs'], 'unit': '组'}]},
        {'type': 'notice', 'text': '核对当前库存汇总与有效库存流水，不是单据发生时的历史库存。数量和价值逐行比较，不跨物料、单位或公司相加。'},
    ]
    for warning in info.get('warnings', []):
        components.append({'type': 'notice', 'text': str(warning), 'warning': True})
    if info.get('pending_revaluations'):
        components.append({'type': 'notice', 'text': '原生库存重估尚未完成或存在失败项；请先处理原重估任务，本视图不会强行执行队列。', 'warning': True})
    components.append({'type': 'table', 'title': '来源单据涉及的当前库存',
                       'columns': ['物料', '仓库', '单位', '库存汇总数量', '有效流水数量',
                                   f'库存汇总价值（{currency}）', f'有效流水价值（{currency}）', '核对结果'],
                       'rows': [{'cells': [row['item_code'], row['warehouse'], row.get('stock_uom'),
                                           row.get('bin_qty'), row.get('ledger_qty'), row.get('bin_value'),
                                           row.get('ledger_value'),
                                           row.get('reason') or ('一致' if row['quantity_matches'] and row['value_matches'] else '存在差异')]}
                                for row in rows]})
    components.append({'type': 'stock_repair', 'source_doctype': info['source_doctype'],
                       'source_name': info['source_name'], 'revision': info['revision'],
                       'can_repair': info['can_repair'] is True,
                       'targets': [{'item_code': row['item_code'], 'warehouse': row['warehouse']}
                                   for row in rows if row['can_repair'] is True],
                       'status': summary['status']})
    # Warning messages remain intact but occupy one component, keeping the
    # component protocol bounded regardless of the number of affected pairs.
    notes = [block for block in components if block['type'] == 'notice']
    components = [components[0], {'type': 'notice', 'text': '\n'.join(block['text'] for block in notes),
                                  'warning': any(block.get('warning') for block in notes)},
                  *[block for block in components[1:] if block['type'] != 'notice']]
    return {'title': '库存核对',
            'subtitle': f"{choice['source_name']} · {info.get('company') or '来源公司'} · {statuses.get(summary['status'], '需核对')}",
            'components': components,
            'actions': [{'label': '重新核对', 'selection': choice},
                        {'label': '查看来源单据', 'selection': {'view': 'frappe_document',
                         'doctype': choice['source_doctype'], 'document': choice['source_name']}}],
            'source': '原生来源单据、有效 Stock Ledger Entry、Bin 与库存重估状态；按当前账号权限读取',
            'summary': {**summary, 'source_doctype': choice['source_doctype'], 'source_name': choice['source_name'],
                        'can_repair': info['can_repair'] is True,
                        'answer': '只完成核对，尚未执行修复。发现差异不等于可以直接改库存或金额。'}}
