"""Native sidebar entries for the meal and canteen module."""
import frappe
from frappe.desk.doctype.custom_sidebar.custom_sidebar import get_customization
from frappe.desk.doctype.sidebar.sidebar import item_key

from tongjianyun.canteen_ops import common

GROUPS = (
    ("供餐计划与执行", (
        ("DocType", common.TERM, "学期膳食项目", "calendar"),
        ("DocType", common.TASK, "每周膳食任务", "list-checks"),
        ("DocType", common.DAY, "逐餐供餐与日结", "book-open"),
    )),
    ("采购与配送", (
        ("DocType", common.DISPATCH, "采购申请下发", "list-checks"),
        ("Report", "Tongjianyun Canteen Quotation Comparison", "食材询价比价", "chart-bar"),
        ("DocType", common.PRICE, "采购价格复核", "list-checks"),
        ("DocType", common.DELIVERY, "供应商配送批次", "list-checks"),
        ("Report", "Tongjianyun Canteen Ingredient Purchases", "食材采购报表", "chart-bar"),
    )),
    ("验收与库存", (
        ("DocType", common.RECEIVING, "食材扫码验收", "list-checks"),
        ("DocType", common.LOT_MOVEMENT, "食材批次流转", "book-open"),
        ("Report", "Tongjianyun Canteen Inventory Batches", "实时库存与效期", "chart-bar"),
        ("Report", "Tongjianyun Canteen Stock Count", "食堂盘点报表", "chart-bar"),
    )),
    ("食品安全与人员", (
        ("DocType", common.CANTEEN, "食堂资质与场所档案", "book-open"),
        ("DocType", common.CREDENTIAL, "食堂证照与健康证", "book-open"),
        ("DocType", common.TRAINING, "从业人员培训记录", "users"),
        ("Report", "Tongjianyun Canteen Credential Expiry", "食堂证照到期提醒", "chart-bar"),
        ("DocType", common.SAMPLE, "食品留样", "list-checks"),
        ("DocType", common.COMPANION, "陪餐登记与评价", "list-checks"),
    )),
    ("账务与结算", (
        ("DocType", common.POLICY, "地方采购与财务流程", "list-checks"),
        ("DocType", common.STATEMENT, "供应商对账单", "book-open"),
        ("Report", "Tongjianyun Canteen Supplier Accounts", "供应商对账与结算", "chart-bar"),
        ("DocType", common.VOUCHER, "食堂会计凭证申请", "book-open"),
        ("DocType", common.SUBSIDY, "营养餐补助人次核对", "list-checks"),
        ("Report", "Tongjianyun Canteen Accounting Records", "食堂账务记录", "chart-bar"),
        ("Report", "Tongjianyun Canteen Operations Report", "食堂经营报表", "chart-bar"),
        ("Report", "Tongjianyun Canteen Income Expense", "食堂收支报表", "chart-bar"),
        ("Report", "Tongjianyun Canteen Nutrition Subsidy", "营养餐补助报表", "chart-bar"),
        ("Report", "Tongjianyun Canteen Fund Hierarchy", "经费分级统计", "chart-bar"),
    )),
    ("监管与整改", (
        ("Report", "Tongjianyun Canteen Data Quality", "监管数据质量", "chart-bar"),
        ("DocType", common.FINDING, "监管整改", "list-checks"),
    )),
)


def install_navigation(module):
    saved = get_customization(module, None)
    sidebar = (frappe.get_doc("Custom Sidebar", saved.name, for_update=True) if saved
               else frappe.new_doc("Custom Sidebar").update({"module": module, "user": ""}))
    original = {item_key(row) for row in sidebar.sidebar_items}
    installed = 0
    changed = False
    for title, entries in GROUPS:
        heading = {"type": "Section Break", "label": title, "collapsible": 1, "keep_closed": 1, "added": 1}
        heading_key = item_key(heading)
        section = next((row for row in sidebar.sidebar_items if item_key(row) == heading_key), None)
        if section is None:
            section = sidebar.append("sidebar_items", heading)
            changed = True
        siblings = sidebar.sidebar_items
        end = siblings.index(section) + 1
        while end < len(siblings) and siblings[end].child and siblings[end].type != "Section Break":
            end += 1
        for link_type, target, label, icon in entries:
            entry = {"type": "Link", "link_type": link_type, "link_to": target, "label": label,
                     "icon": icon, "child": 1, "added": 1}
            key = item_key(entry)
            if key in original:
                continue
            sidebar.append("sidebar_items", entry, position=end)
            end += 1
            original.add(key)
            installed += 1
    if changed or installed:
        sidebar.save()
    return installed
