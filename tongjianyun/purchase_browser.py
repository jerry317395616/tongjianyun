"""Permission-aware browser for date-labelled recipe purchase orders."""
import re
import frappe
from frappe.utils import getdate, nowdate, add_days, cint


@frappe.whitelist()
def search(scope='current', start_date=None, end_date=None, status=None, keyword=None, offset=0):
    if not frappe.has_permission('Purchase Order', 'read'):
        frappe.throw('无权查看采购订单', frappe.PermissionError)
    filters = [['title', 'like', '____-__-__ · %']]
    if scope not in ('current', 'history', 'all'):
        frappe.throw('无效查询范围')
    if start_date and end_date and getdate(start_date) > getdate(end_date):
        frappe.throw('开始日期不能晚于结束日期')
    if scope == 'current':
        filters.append(['title', '>=', nowdate()])
    elif scope == 'history':
        filters.append(['title', '<', nowdate()])
    if start_date:
        filters.append(['title', '>=', str(getdate(start_date))])
    if end_date:
        filters.append(['title', '<', str(add_days(getdate(end_date), 1))])
    if status not in (None, '', '0', '1', '2'):
        frappe.throw('无效订单状态')
    if status not in (None, ''):
        filters.append(['docstatus', '=', int(status)])
    query = {'filters': filters, 'fields': ['name', 'title', 'supplier_name', 'supplier', 'docstatus', 'grand_total', 'currency', 'transaction_date'], 'order_by': 'title desc, name desc', 'limit_start': max(0, cint(offset)), 'limit_page_length': 21}
    if keyword:
        query['or_filters'] = [[field, 'like', '%' + str(keyword)[:100] + '%'] for field in ('name', 'title', 'supplier_name', 'supplier')]
    rows = frappe.get_list('Purchase Order', **query)
    for row in rows:
        row['recipe_date'] = row.title[:10]
    return {'orders': rows[:20], 'has_more': len(rows) > 20}


@frappe.whitelist()
def details(name):
    doc = frappe.get_doc('Purchase Order', name)
    doc.check_permission('read')
    return {'items': [{'item_name': x.item_name, 'qty': x.qty, 'uom': x.uom, 'rate': x.rate, 'amount': x.amount} for x in doc.items]}
