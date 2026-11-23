"""Install the standard ingredient view and audit using native Frappe metadata."""

import json
from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.modules.import_file import import_file_by_path

from tongjianyun.canteen_ops.navigation import install_navigation
from tongjianyun.ingredient_library import ALIASES, LAYOUT, MARKER
from tongjianyun.standard_recipe_setup import DISH_OPTIONS, MODULE, _save_layout

FIELDS = [
    {"fieldname": MARKER, "label": "标准食材", "fieldtype": "Check", "insert_after": "item_name",
     "default": "0", "hidden": 1, "no_copy": 1},
    {"fieldname": ALIASES, "label": "食材别名", "fieldtype": "Small Text", "insert_after": MARKER,
     "depends_on": f"eval:doc.{MARKER}", "description": "每行一个名称，菜谱选材时可按别名查找。"},
]
REPORT_PATH = Path(__file__).parent / "tongjianyun/report/tongjianyun_ingredient_master_audit"


def install():
    frappe.only_for("System Manager")
    create_custom_fields({"Item": [dict(field, module="Tongjianyun") for field in FIELDS]})
    _save_layout("Item", LAYOUT, {
        "section_break_zlmj": {"label": "食材信息"},
        "item_name": {"label": "标准食材名称", "in_list_view": 1},
        "item_code": {"label": "食材编码"},
        "item_group": {"label": "食材分类", "in_list_view": 1, "in_standard_filter": 1},
        "stock_uom": {"label": "库存单位", "in_list_view": 1},
        "purchase_uom": {"label": "默认采购单位", "in_list_view": 1},
        "uoms": {"label": "单位换算"},
    }, condition=f"doc.{MARKER} == 1")
    previous = frappe.flags.in_migrate
    try:
        frappe.flags.in_migrate = True
        import_file_by_path(str(REPORT_PATH / "tongjianyun_ingredient_master_audit.json"), force=True)
    finally:
        frappe.flags.in_migrate = previous
    install_navigation(MODULE, json.dumps(DISH_OPTIONS, ensure_ascii=False))
    frappe.clear_cache()
