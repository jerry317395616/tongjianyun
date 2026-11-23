"""Install the standard ingredient view and audit using native Frappe metadata."""

import json
from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.modules.import_file import import_file_by_path

from tongjianyun.canteen_ops.navigation import install_navigation
from tongjianyun.ingredient_library import ALIASES, LAYOUT, MARKER
from tongjianyun.standard_recipe_setup import DISH_LAYOUT_FIELDS, DISH_OPTIONS, MODULE, _save_layout

FIELDS = [
    {"fieldname": MARKER, "label": "标准食材", "fieldtype": "Check", "insert_after": "item_name",
     "default": "0", "hidden": 1, "no_copy": 1},
    {"fieldname": ALIASES, "label": "食材别名", "fieldtype": "Small Text", "insert_after": MARKER,
     "depends_on": f"eval:doc.{MARKER}", "description": "每行一个名称，菜谱选材时可按别名查找。"},
]
OVERVIEW = "custom_tjy_ing_overview"
PROFILE = "custom_tjy_ing_profile"
UNITS_COLUMN = "custom_tjy_ing_units_column"
UNITS = "custom_tjy_ing_units"
ADVANCED = "custom_tjy_ing_advanced"
ADVANCED_COLUMN = "custom_tjy_ing_advanced_column"
CODE = "custom_tjy_ing_code"

LAYOUT_FIELDS = {
    OVERVIEW: {"fieldtype": "Section Break"},
    PROFILE: {"fieldtype": "Heading", "label": "食材资料"},
    UNITS_COLUMN: {"fieldtype": "Column Break"},
    UNITS: {"fieldtype": "Heading", "label": "计量与采购"},
    ADVANCED: {"fieldtype": "Section Break", "label": "更多物料设置", "collapsible": 1,
               "collapsible_depends_on": "eval:false"},
    ADVANCED_COLUMN: {"fieldtype": "Column Break"},
    CODE: {"fieldtype": "Section Break"},
}
PRIMARY_FIELDS = (
    OVERVIEW, PROFILE, "item_name", "item_group", ALIASES,
    UNITS_COLUMN, UNITS, "stock_uom", "purchase_uom", "custom_meal_procurement_policy",
)
ADVANCED_SWITCHES = ("is_purchase_item", "is_sales_item", "allow_alternative_item", "has_variants")
REPORT_PATH = Path(__file__).parent / "tongjianyun/report/tongjianyun_ingredient_master_audit"


def install():
    frappe.only_for("System Manager")
    create_custom_fields({"Item": [dict(field, module="Tongjianyun") for field in FIELDS]})
    _install_layout()
    previous = frappe.flags.in_migrate
    try:
        frappe.flags.in_migrate = True
        import_file_by_path(str(REPORT_PATH / "tongjianyun_ingredient_master_audit.json"), force=True)
    finally:
        frappe.flags.in_migrate = previous
    install_navigation(MODULE, json.dumps(DISH_OPTIONS, ensure_ascii=False))
    frappe.clear_cache()


def _install_layout():
    from ione_core.meal_planning import SLOT_FIELDS

    _install_layout_fields()
    _save_layout("Item", LAYOUT, {
        "item_name": {"label": "标准食材名称", "in_list_view": 1, "reqd": 1},
        "item_code": {"label": "食材编码", "read_only": 1},
        "item_group": {"label": "食材分类", "in_list_view": 1, "in_standard_filter": 1},
        "stock_uom": {"label": "库存单位", "in_list_view": 1},
        ALIASES: {"description": "每行一个别名，菜谱选材时可按别名搜索。"},
        "purchase_uom": {"label": "默认采购单位", "in_list_view": 1,
                         "description": "采购单位不同时，在「计量单位」中维护换算。"},
        "uoms": {"label": "单位换算"},
        **{fieldname: {"hidden": 1} for fieldname in SLOT_FIELDS.values()},
        **{name: {"depends_on": "eval:true"} for name in LAYOUT_FIELDS},
    }, arrange_fields=_arrange_basic_info, condition=f"doc.{MARKER} == 1")


def _install_layout_fields():
    # Keep layout-only breaks beyond the native tabs, where they only affect this layout.
    fields = frappe.get_meta("Item", cached=False).fields
    anchor = next(df.fieldname for df in reversed(fields)
                  if df.fieldname not in LAYOUT_FIELDS and df.fieldname not in DISH_LAYOUT_FIELDS)
    custom = []
    for name, properties in LAYOUT_FIELDS.items():
        custom.append({"fieldname": name, "module": "Tongjianyun", "insert_after": anchor,
                       "depends_on": "eval:false", **properties})
        anchor = name
    create_custom_fields({"Item": custom})


def _arrange_basic_info(metadata, fields):
    by_name = {row["fieldname"]: row for row in fields}
    details = next(i for i, df in enumerate(metadata) if df.fieldname == "details")
    end = next(i for i, df in enumerate(metadata) if i > details and df.fieldtype == "Tab Break")
    placed = {*PRIMARY_FIELDS, *ADVANCED_SWITCHES, *LAYOUT_FIELDS, "item_code"}
    advanced = [row.fieldname for row in metadata[details + 1:end]
                if row.fieldname not in placed and row.fieldtype not in {"Section Break", "Column Break"}]
    layout_order = (*PRIMARY_FIELDS, ADVANCED, *ADVANCED_SWITCHES, ADVANCED_COLUMN, *advanced, CODE, "item_code")
    other_tabs = [row for row in fields[end:] if row["fieldname"] not in placed]
    return [*fields[:details + 1], *(by_name[name] for name in layout_order), *other_tabs]
