"""Install native Frappe metadata for the Tongjianyun standard recipe library."""
import json
from urllib.parse import urlencode

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.desk.doctype.custom_sidebar.custom_sidebar import add_site_sidebar_item
from frappe.desk.doctype.dock.dock import get_dock, resolve_app_dock, save_site_dock

from tongjianyun.canteen_ops.navigation import install_navigation
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
DISH_MEAL_COLUMN = "custom_tjy_dish_meal_column"
DISH_ADVANCED_COLUMN = "custom_tjy_dish_advanced_column"
DISH_RECIPE_SECTION = "custom_tjy_dish_recipe_section"
DISH_RECIPE_PREVIEW = "custom_tjy_dish_recipe_preview"
DISH_LAYOUT_FIELDS = {
    DISH_MEAL_COLUMN: {"fieldtype": "Column Break"},
    DISH_ADVANCED_COLUMN: {"fieldtype": "Column Break"},
    DISH_RECIPE_SECTION: {"fieldtype": "Section Break", "label": "配方与食材"},
    DISH_RECIPE_PREVIEW: {"fieldtype": "HTML"},
}

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
    _install_dish_layout_fields()
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
        "section_break_zlmj": {"label": "菜品信息"},
        "section_break_11": {"label": "更多物料属性"},
        "item_name": {"label": "菜名", "in_list_view": 1, "reqd": 1},
        "item_code": {"label": "菜品编码", "read_only": 1},
        "stock_uom": {"label": "默认单位", "in_list_view": 1},
        "disabled": {"in_list_view": 1, "in_standard_filter": 1},
        DISH_CATEGORY: {"in_list_view": 1, "in_standard_filter": 1, "reqd": 1},
        **{field: {"in_standard_filter": 1} for field in SLOT_FIELDS.values()},
        **{field: {"depends_on": "eval:true"} for field in DISH_LAYOUT_FIELDS},
    }, condition=f"doc.{DISH} == 1")
    enroll_legacy_dishes()
    classify_existing_dishes(DISH)
    _install_sidebar()
    frappe.clear_cache()


def _install_dish_layout_fields():
    metadata = frappe.get_meta("Item", cached=False).fields
    # Append the layout-only fields to the base form, where they stay hidden.
    anchor = next(row.fieldname for row in reversed(metadata) if row.fieldname not in DISH_LAYOUT_FIELDS)
    fields = []
    for name, properties in DISH_LAYOUT_FIELDS.items():
        fields.append({
            "fieldname": name, "module": "Tongjianyun", "insert_after": anchor,
            "depends_on": "eval:false", **properties,
        })
        anchor = name
    create_custom_fields({"Item": fields})


def _arrange_dish_details(metadata, fields):
    from ione_core.meal_dish_catalog import SECTION
    from ione_core.meal_planning import SLOT_FIELDS

    rows = {row["fieldname"]: row for row in fields}
    start = next(i for i, row in enumerate(metadata) if row.fieldname == "details")
    stop = next(i for i, row in enumerate(metadata) if i > start and row.fieldtype == "Tab Break")
    first_meal, *other_meals = SLOT_FIELDS.values()
    names = [
        "section_break_zlmj", "item_name", "item_group", "column_break0", DISH_CATEGORY, "stock_uom",
        SECTION, first_meal,
    ]
    for column, meal in zip(
        ("column_break_kpmi", "column_break_ixrh", "column_break_wugd", DISH_MEAL_COLUMN),
        other_meals, strict=True,
    ):
        names.extend((column, meal))
    names.extend((
        DISH_RECIPE_SECTION, DISH_RECIPE_PREVIEW,
        "section_break_11", "item_code", "naming_series", "disabled", "is_stock_item",
        "is_fixed_asset", "auto_create_assets", "is_grouped_asset", "asset_category", "asset_naming_series",
        DISH_ADVANCED_COLUMN,
    ))
    placed = set(names)
    advanced = [rows[row.fieldname] for row in metadata[start + 1:stop]
                if row.fieldname not in placed and row.fieldtype not in {"Section Break", "Column Break"}]
    other_tabs = [row for row in fields[stop:] if row["fieldname"] not in DISH_LAYOUT_FIELDS]
    return [*fields[:start + 1], *(rows[name] for name in names), *advanced, *other_tabs]


def _save_layout(doctype, title, overrides, **properties):
    values = {
        "doctype": "DocType Layout",
        "title": title,
        "document_type": doctype,
        "module": "Tongjianyun",
        "is_standard": 1,
        **properties,
    }
    metadata = frappe.get_meta(doctype).fields
    fields = [dict(
        fieldname=df.fieldname,
        label=df.label,
        **{name: df.get(name) for name in ("hidden", "reqd", "read_only", "in_list_view", "in_standard_filter")},
    ) for df in metadata]
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
    values["fields"] = _arrange_dish_details(metadata, fields) if title == DISH_LAYOUT else fields
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
    _install_dish_link()
    _install_week_link()
    _install_meal_ledger_link()
    _install_ingredient_analysis_link()
    _install_staffing_links()
    _install_sidebar_link("DocType", "Tongjianyun Nutrition Improvement Plan", "营养改善计划", "list-checks")
    install_navigation(MODULE, json.dumps(DISH_OPTIONS, ensure_ascii=False))


def _install_dish_link():
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


def _install_week_link():
    _install_sidebar_link("DocType", "Meal Planning Week", "自定义周食谱", "calendar")


def _install_meal_ledger_link():
    _install_sidebar_link("Report", "Tongjianyun Meal Ledger", "膳食台账", "book-open")


def _install_ingredient_analysis_link():
    _install_sidebar_link("Report", "Tongjianyun Ingredient Analysis", "食材采购与消耗分析", "chart-bar")


def _install_staffing_links():
    _install_sidebar_link("DocType", "Tongjianyun Canteen Staffing Rule", "食堂岗位配置", "users")
    _install_sidebar_link("Report", "Tongjianyun Canteen Staffing Analysis", "人员配置分析", "chart-bar")


def _install_sidebar_link(link_type, target, label, icon):
    site_sidebar = frappe.db.get_value("Custom Sidebar", {"module": MODULE, "user": ""}, "name")
    if site_sidebar:
        sidebar = frappe.get_doc("Custom Sidebar", site_sidebar)
        if any(row.link_type == link_type and row.link_to == target for row in sidebar.sidebar_items):
            return
    add_site_sidebar_item(MODULE, {
        "type": "Link", "link_type": link_type, "link_to": target, "label": label, "icon": icon,
    })


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
