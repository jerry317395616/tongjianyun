"""Install native Frappe metadata for the Tongjianyun standard recipe library."""
import json
from urllib.parse import urlencode

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.desk.doctype.custom_sidebar.custom_sidebar import add_site_sidebar_item
from frappe.desk.doctype.dock.dock import get_dock, resolve_app_dock, save_site_dock

from tongjianyun.dish_library import enroll_dish
from tongjianyun.standard_recipes import (
    AGE, ALLERGENS, CATEGORIES, CATEGORY, DISH, DISH_CATEGORY, DRAFT, MARKER, METHOD, NET_QTY,
    PENDING, PUBLISHED, REPLACES, STATE,
)

APP = "tongjianyun"
MODULE = "膳食与食堂"
LAYOUT = "标准菜品"
ITEM_LAYOUT = "标准菜品食材"
DISH_LAYOUT = "标准菜品档案"
LIBRARY = "标准菜品库"
LIBRARY_PAGE = "standard-dish-library"
CONDITION = f"doc.{MARKER} == 1"
LIBRARY_OPTIONS = {"layout": LAYOUT, MARKER: 1}
LIBRARY_URL = "/desk/bom?" + urlencode(LIBRARY_OPTIONS)
DISH_OPTIONS = {"layout": DISH_LAYOUT, DISH: 1}

FIELDS = {
    "Item": [
        {"fieldname": DISH, "label": "标准菜品", "fieldtype": "Check",
         "insert_after": "item_name", "default": "0", "hidden": 1, "no_copy": 1},
        {"fieldname": DISH_CATEGORY, "label": "菜品分类", "fieldtype": "Select", "insert_after": DISH,
         "options": "\n" + "\n".join(CATEGORIES), "depends_on": f"eval:doc.{DISH}"},
    ],
    "BOM": [
        {"fieldname": MARKER, "label": "标准菜品", "fieldtype": "Check",
         "insert_after": "item", "default": "0", "hidden": 1},
        {"fieldname": CATEGORY, "label": "菜品分类", "fieldtype": "Select", "insert_after": MARKER,
         "options": "\n" + "\n".join(CATEGORIES)},
        {"fieldname": AGE, "label": "适用年龄", "fieldtype": "Data", "insert_after": CATEGORY},
        {"fieldname": ALLERGENS, "label": "过敏原", "fieldtype": "Small Text", "insert_after": AGE},
        {"fieldname": METHOD, "label": "做法", "fieldtype": "Small Text", "insert_after": ALLERGENS},
        {"fieldname": STATE, "label": "审核状态", "fieldtype": "Select", "insert_after": METHOD,
         "options": f"\n{DRAFT}\n{PENDING}\n{PUBLISHED}", "read_only": 1, "no_copy": 1},
        {"fieldname": REPLACES, "label": "来源配方", "fieldtype": "Link", "options": "BOM",
         "insert_after": STATE, "read_only": 1, "no_copy": 1},
    ],
    "BOM Item": [
        {"fieldname": NET_QTY, "label": "每份可食净量", "fieldtype": "Float", "insert_after": "qty",
         "hidden": 1, "in_list_view": 1, "description": "可选，使用本行食材单位。留空表示未记录。"},
    ],
}


def install():
    frappe.only_for("System Manager")
    from ione_core.meal_dish_catalog import classify_existing_dishes, install_meal_slot_fields
    from ione_core.meal_planning import SLOT_FIELDS

    create_custom_fields({
        doctype: [
            dict(field, module="Tongjianyun", **({"depends_on": f"eval:doc.{MARKER}"} if doctype == "BOM"
                                               and field["fieldname"] != MARKER else {}))
            for field in fields
        ]
        for doctype, fields in FIELDS.items()
    })
    install_meal_slot_fields(DISH, DISH_CATEGORY)
    _save_layout("BOM Item", ITEM_LAYOUT, {
        "item_code": {"label": "食材"},
        "qty": {"label": "每份采购毛用量"},
        NET_QTY: {"hidden": 0, "in_list_view": 1},
    }, is_child_table=1)
    _save_layout("BOM", LAYOUT, {
        "item": {"label": "菜品物料"},
        "quantity": {"label": "基准份数", "default": "1", "read_only": 1},
        "items": {"label": "每份食材带量"},
        CATEGORY: {"in_list_view": 1, "in_standard_filter": 1},
        STATE: {"in_list_view": 1, "in_standard_filter": 1},
        "item_name": {"label": "菜名", "in_list_view": 1},
    }, condition=CONDITION, child_tables=[{"table_fieldname": "items", "child_layout": ITEM_LAYOUT}])
    _save_layout("Item", DISH_LAYOUT, {
        "item_name": {"label": "菜名", "in_list_view": 1},
        "item_code": {"label": "菜品编码", "read_only": 1},
        "stock_uom": {"label": "默认单位", "in_list_view": 1},
        "disabled": {"in_list_view": 1, "in_standard_filter": 1},
        DISH_CATEGORY: {"in_list_view": 1, "in_standard_filter": 1, "reqd": 1},
        **{field: {"in_standard_filter": 1} for field in SLOT_FIELDS.values()},
    }, condition=f"doc.{DISH} == 1")
    enroll_legacy_dishes()
    classify_existing_dishes(DISH)
    _install_sidebar()
    frappe.clear_cache()


def _save_layout(doctype, title, overrides, **properties):
    values = {
        "doctype": "DocType Layout",
        "title": title,
        "document_type": doctype,
        "module": "Tongjianyun",
        "is_standard": 1,
        **properties,
    }
    fields = [dict(
        fieldname=df.fieldname,
        label=df.label,
        **{name: df.get(name) for name in ("hidden", "reqd", "read_only", "in_list_view", "in_standard_filter")},
    ) for df in frappe.get_meta(doctype).fields]
    for field in fields:
        if title == DISH_LAYOUT:
            field["in_list_view"] = 0
        field.update(overrides.get(field["fieldname"], {}))
    if doctype == "BOM":
        for field in fields:
            if field["fieldname"] in {"connections_tab", "costing", "section_break0", "with_operations",
                                      "bom_configuration_section", "operations_section",
                                      "operations_section_section", "operations"}:
                field["hidden"] = 1
    values["fields"] = fields
    existing = frappe.db.exists("DocType Layout", title)
    if existing:
        layout = frappe.get_doc("DocType Layout", existing)
        if layout.document_type != doctype or layout.module != "Tongjianyun" or not layout.is_standard:
            frappe.throw(f"表单布局「{title}」已存在，请处理同名配置。")
        layout.update(values)
    else:
        layout = frappe.get_doc(values)
    previous_import, previous_migrate = frappe.flags.in_import, frappe.flags.in_migrate
    try:
        frappe.flags.in_import = frappe.flags.in_migrate = True
        layout.save()
    finally:
        frappe.flags.in_import, frappe.flags.in_migrate = previous_import, previous_migrate


def _install_sidebar():
    app = frappe.db.get_value("Module Def", MODULE, "app_name")
    if app and app != APP:
        frappe.throw(f"模块「{MODULE}」已被其他应用使用。")
    entries = resolve_app_dock(APP, upto="site", gated=False)
    if not any(row["link_type"] == "Sidebar" and row["link_to"] == MODULE for row in entries):
        dock = get_dock(APP)
        rows = [row.as_dict() for row in dock.items] if dock else entries
        rows.append({
            "link_type": "Sidebar", "link_to": MODULE, "title": MODULE, "icon": "utensils", "added": 1,
        })
        save_site_dock(APP, rows, [] if app else [MODULE])
    link = {
        "type": "Link", "link_type": "DocType", "link_to": "Item", "label": LIBRARY, "icon": "book-open",
        "route_options": json.dumps(DISH_OPTIONS, ensure_ascii=False),
    }
    site_sidebar = frappe.db.get_value("Custom Sidebar", {"module": MODULE, "user": ""}, "name")
    if site_sidebar:
        sidebar = frappe.get_doc("Custom Sidebar", site_sidebar)
        for row in sidebar.sidebar_items:
            if row.link_type == "DocType" and row.link_to == "Item" and row.route_options == link["route_options"]:
                return
        for row in sidebar.sidebar_items:
            legacy_link = row.link_type == "DocType" and row.link_to == "BOM" and (
                row.route_options == json.dumps(LIBRARY_OPTIONS, ensure_ascii=False) or row.label == LIBRARY
            )
            legacy_page = row.link_type == "Page" and row.link_to == LIBRARY_PAGE
            if legacy_page or legacy_link or (row.link_type == "URL" and row.url == LIBRARY_URL):
                row.update({**link, "url": None, "open_in_new_tab": 0})
                sidebar.save()
                return
    add_site_sidebar_item(MODULE, link)


def enroll_legacy_dishes():
    categories = {}
    for row in frappe.get_all("BOM", filters={MARKER: 1}, fields=["item", CATEGORY], distinct=True):
        if row.item:
            values = categories.setdefault(row.item, set())
            if row.get(CATEGORY) in CATEGORIES:
                values.add(row.get(CATEGORY))
    for item, values in categories.items():
        enroll_dish(item, next(iter(values)) if len(values) == 1 else None)


def mark_existing_meal_recipes():
    """Enroll existing submitted recipes actually used in active meal plans."""
    frappe.only_for("System Manager")
    names = frappe.db.sql_list("""
        SELECT DISTINCT bom.name
        FROM `tabProduction Plan Item` AS line
        INNER JOIN `tabProduction Plan` AS plan ON plan.name = line.parent
        INNER JOIN `tabBOM` AS bom ON bom.name = line.bom_no
        INNER JOIN `tabItem` AS item ON item.name = bom.item
        WHERE plan.custom_is_meal_plan = 1 AND plan.docstatus < 2
          AND bom.docstatus = 1 AND bom.is_active = 1 AND bom.quantity = 1
          AND bom.company = plan.company AND COALESCE(bom.custom_tjy_standard_recipe, 0) = 0
          AND item.disabled = 0 AND item.is_purchase_item = 0
    """)
    for name in names:
        frappe.db.set_value("BOM", name, {MARKER: 1, STATE: PUBLISHED}, update_modified=False)
    if names:
        enroll_legacy_dishes()
    return len(names)
