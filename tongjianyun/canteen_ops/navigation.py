"""Native sidebar entries for the meal and canteen module."""
from urllib.parse import urlencode

import frappe
from frappe.desk.doctype.custom_sidebar.custom_sidebar import get_customization
from frappe.desk.doctype.sidebar.sidebar import item_key

from tongjianyun.canteen_ops import common
from tongjianyun.ingredient_library import LAYOUT, LIBRARY, MARKER

INGREDIENT_URL = "/desk/item/view/list?" + urlencode({"layout": LAYOUT, MARKER: 1})

GROUPS = (
    ("菜品与食谱", "book-open", (
        ("DocType", "Item", "标准菜品库", "book-open"),
        ("URL", INGREDIENT_URL, LIBRARY, "carrot"),
        ("DocType", "Tongjianyun Food Nutrition Profile", "食物营养档案", "clipboard-list"),
        ("DocType", common.WEEK, "自定义周食谱", "calendar"),
        ("DocType", common.NUTRITION, "营养改善计划", "list-checks"),
    )),
    ("供餐计划与执行", "calendar-days", (
        ("DocType", common.TERM, "学期膳食项目", "calendar"),
        ("DocType", common.TASK, "每周膳食任务", "list-checks"),
        ("DocType", common.DAY, "逐餐供餐与日结", "book-open"),
        ("Report", "Tongjianyun Meal Ledger", "膳食台账", "book-open"),
    )),
    ("采购与配送", "truck", (
        ("DocType", common.DISPATCH, "采购申请下发", "list-checks"),
        ("Report", "Tongjianyun Canteen Quotation Comparison", "食材询价比价", "chart-bar"),
        ("DocType", common.PRICE, "采购价格复核", "list-checks"),
        ("DocType", common.DELIVERY, "供应商配送批次", "list-checks"),
        ("Report", "Tongjianyun Canteen Ingredient Purchases", "食材采购报表", "chart-bar"),
        ("Report", "Tongjianyun Ingredient Analysis", "食材采购与消耗分析", "chart-bar"),
    )),
    ("验收与库存", "warehouse", (
        ("DocType", common.RECEIVING, "食材扫码验收", "list-checks"),
        ("DocType", common.LOT_MOVEMENT, "食材批次流转", "book-open"),
        ("Report", "Tongjianyun Canteen Inventory Batches", "实时库存与效期", "chart-bar"),
        ("Report", "Tongjianyun Canteen Stock Count", "食堂盘点报表", "chart-bar"),
    )),
    ("食品安全与资质", "shield-check", (
        ("DocType", common.CANTEEN, "食堂资质与场所档案", "book-open"),
        ("DocType", common.CREDENTIAL, "食堂证照与健康证", "book-open"),
        ("Report", "Tongjianyun Canteen Credential Expiry", "食堂证照到期提醒", "chart-bar"),
        ("DocType", common.SAMPLE, "食品留样", "list-checks"),
        ("DocType", common.COMPANION, "陪餐登记与评价", "list-checks"),
    )),
    ("人员与岗位", "users", (
        ("DocType", "Tongjianyun Canteen Staffing Rule", "食堂岗位配置", "users"),
        ("Report", "Tongjianyun Canteen Staffing Analysis", "人员配置分析", "chart-bar"),
        ("DocType", common.TRAINING, "从业人员培训记录", "users"),
    )),
    ("账务与结算", "wallet", (
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
    ("监管与整改", "clipboard-check", (
        ("Report", "Tongjianyun Canteen Data Quality", "监管数据质量", "chart-bar"),
        ("DocType", common.FINDING, "监管整改", "list-checks"),
    )),
)

PREVIOUS_TITLES = {"食品安全与资质": "食品安全与人员"}


def _entry_key(row):
    return item_key(row), row.get("route_options") or ""


def install_navigation(module, dish_route_options):
    saved = get_customization(module, None)
    sidebar = (frappe.get_doc("Custom Sidebar", saved.name, for_update=True) if saved
               else frappe.new_doc("Custom Sidebar").update({"module": module, "user": ""}))
    previous = list(sidebar.sidebar_items)
    headings = {row.label: row for row in previous if row.type == "Section Break"}
    links = {_entry_key(row): row for row in previous if row.type == "Link"}
    layout, managed = [], set()
    updated = False
    for index, (title, icon, entries) in enumerate(GROUPS):
        section = headings.get(title) or headings.get(PREVIOUS_TITLES.get(title))
        heading = {"type": "Section Break", "label": title, "icon": icon, "indent": 1,
                   "collapsible": 1, "keep_closed": int(index != 0), "show_arrow": 0}
        if section is None:
            section = sidebar.append("sidebar_items", {**heading, "added": 1})
            updated = True
        elif any(section.get(key) != value for key, value in heading.items()):
            if section.label != title:
                section.key = item_key(section)
            section.update(heading)
            updated = True
        children = []
        for link_type, target, label, icon in entries:
            entry = {"type": "Link", "link_type": link_type, "link_to": target, "label": label,
                     "icon": icon, "child": 1, "added": 1}
            if link_type == "URL":
                entry.update(link_to=None, url=target, open_in_new_tab=0)
            elif target == "Item":
                entry["route_options"] = dish_route_options
            row = links.get(_entry_key(entry))
            if row is None:
                row = sidebar.append("sidebar_items", entry)
                updated = True
            elif not row.child:
                row.child = 1
                updated = True
            children.append(row)
        layout.append((section, children))
        managed.update(id(row) for row in (section, *children))

    # User-added children of a managed section follow that section. Other custom blocks
    # keep their original order and child relationships.
    by_section = {id(section): children for section, children in layout}
    remaining = []
    parent = None
    for row in previous:
        if row.type == "Section Break":
            parent = by_section.get(id(row))
        if id(row) not in managed:
            if row.child and parent is not None and row.type != "Section Break":
                parent.append(row)
            else:
                remaining.append(row)
    ordered = remaining + [row for section, children in layout for row in (section, *children)]
    if not updated and ordered == previous:
        return False
    sidebar.set("sidebar_items", ordered)
    for index, row in enumerate(sidebar.sidebar_items, 1):
        row.idx = index
    sidebar.save()
    return True
