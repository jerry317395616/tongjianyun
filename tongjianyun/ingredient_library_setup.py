"""Install the standard ingredient view using native Frappe metadata."""

import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from tongjianyun.canteen_ops.navigation import install_navigation
from tongjianyun.food_nutrition import MISSING, STATUS
from tongjianyun.ingredient_library import ALIASES, LAYOUT, MARKER
from tongjianyun.standard_recipe_setup import DISH_LAYOUT_FIELDS, DISH_OPTIONS, MODULE, _save_layout

FIELDS = [
    {"fieldname": MARKER, "label": "标准食材", "fieldtype": "Check", "insert_after": "item_name",
     "default": "0", "hidden": 1, "no_copy": 1},
    {"fieldname": ALIASES, "label": "食材别名", "fieldtype": "Small Text", "insert_after": MARKER,
     "depends_on": f"eval:doc.{MARKER}", "description": "每行一个名称，菜谱选材时可按别名查找。"},
]
OVERVIEW = "custom_tjy_ing_overview"
CLASSIFICATION_COLUMN = "custom_tjy_ing_classification_column"
ALIASES_SECTION = "custom_tjy_ing_aliases_section"
PURCHASING = "custom_tjy_ing_purchasing"
UNITS_COLUMN = "custom_tjy_ing_units_column"
POLICY_COLUMN = "custom_tjy_ing_policy_column"
ADVANCED = "custom_tjy_ing_advanced"
ADVANCED_COLUMN = "custom_tjy_ing_advanced_column"
CODE = "custom_tjy_ing_code"
NUTRITION_TAB = "custom_tjy_nutrition_tab"
NUTRITION_PREVIEW = "custom_tjy_nutrition_preview"
RETIRED_HEADINGS = {"custom_tjy_ing_profile", "custom_tjy_ing_units"}

LAYOUT_FIELDS = {
    OVERVIEW: {"fieldtype": "Section Break", "label": "食材资料", "hide_border": 1},
    CLASSIFICATION_COLUMN: {"fieldtype": "Column Break"},
    ALIASES_SECTION: {"fieldtype": "Section Break"},
    PURCHASING: {"fieldtype": "Section Break", "label": "计量与采购"},
    UNITS_COLUMN: {"fieldtype": "Column Break"},
    POLICY_COLUMN: {"fieldtype": "Column Break"},
    ADVANCED: {"fieldtype": "Section Break", "label": "更多物料设置", "collapsible": 1,
               "collapsible_depends_on": "eval:false"},
    ADVANCED_COLUMN: {"fieldtype": "Column Break"},
    CODE: {"fieldtype": "Section Break"},
    NUTRITION_TAB: {"fieldtype": "Tab Break", "label": "营养成分"},
    NUTRITION_PREVIEW: {"fieldtype": "HTML"},
}
PRIMARY_FIELDS = (
    OVERVIEW, "item_name", CLASSIFICATION_COLUMN, "item_group",
    ALIASES_SECTION, ALIASES,
    PURCHASING, "stock_uom", UNITS_COLUMN, "purchase_uom", POLICY_COLUMN, "custom_meal_procurement_policy",
)
ADVANCED_SWITCHES = ("is_purchase_item", "is_sales_item", "allow_alternative_item", "has_variants")


def install():
    frappe.only_for("System Manager")
    create_custom_fields({"Item": [dict(field, module="Tongjianyun") for field in FIELDS]})
    _install_layout()
    frappe.db.set_value("Item", {MARKER: 1, STATUS: ["is", "not set"]}, STATUS, MISSING, update_modified=False)
    install_navigation(MODULE, json.dumps(DISH_OPTIONS, ensure_ascii=False))
    frappe.clear_cache()


def _install_layout():
    from ione_core.meal_planning import SLOT_FIELDS

    _install_layout_fields()
    _save_layout("Item", LAYOUT, {
        "item_name": {"label": "标准食材名称", "in_list_view": 1, "reqd": 1},
        "item_code": {"label": "食材编码", "read_only": 1, "reqd": 0,
                      "description": "新建食材时自动生成。"},
        "item_group": {"label": "食材分类", "in_list_view": 1, "in_standard_filter": 1},
        "stock_uom": {"label": "库存单位", "in_list_view": 1},
        ALIASES: {"description": "每行一个别名，菜谱选材时可按别名搜索。"},
        "purchase_uom": {"label": "默认采购单位", "in_list_view": 1,
                         "description": "与库存单位不同时，在「计量单位」中维护换算。"},
        "custom_meal_procurement_policy": {"description": "厨房用水不生成采购申请。自产配料需先维护配方。"},
        "uoms": {"label": "单位换算"},
        **{fieldname: {"hidden": 1} for fieldname in SLOT_FIELDS.values()},
        **{name: {"depends_on": "eval:true"} for name in LAYOUT_FIELDS},
        STATUS: {"hidden": 0, "in_standard_filter": 1},
    }, arrange_fields=_arrange_basic_info, condition=f"doc.{MARKER} == 1")


def _install_layout_fields():
    # Keep layout-only breaks beyond the native tabs, where they only affect this layout.
    fields = frappe.get_meta("Item", cached=False).fields
    layout_fields = {STATUS, *LAYOUT_FIELDS, *RETIRED_HEADINGS, *DISH_LAYOUT_FIELDS}
    anchor = next(df.fieldname for df in reversed(fields) if df.fieldname not in layout_fields)
    custom = []
    for name, properties in LAYOUT_FIELDS.items():
        custom.append({"fieldname": name, "module": "Tongjianyun", "insert_after": anchor,
                       "depends_on": "eval:false", **properties})
        anchor = name
    custom.append({"fieldname": STATUS, "module": "Tongjianyun", "insert_after": anchor,
                   "label": "营养数据状态", "fieldtype": "Select", "hidden": 1, "read_only": 1,
                   "default": MISSING, "options": "\n缺少数据\n待审核\n已匹配", "no_copy": 1})
    create_custom_fields({"Item": custom})


def _arrange_basic_info(metadata, fields):
    by_name = {row["fieldname"]: row for row in fields}
    details = next(i for i, df in enumerate(metadata) if df.fieldname == "details")
    end = next(i for i, df in enumerate(metadata) if i > details and df.fieldtype == "Tab Break")
    placed = {*PRIMARY_FIELDS, *ADVANCED_SWITCHES, *LAYOUT_FIELDS, *RETIRED_HEADINGS, "item_code", STATUS}
    advanced = [row.fieldname for row in metadata[details + 1:end]
                if row.fieldname not in placed and row.fieldtype not in {"Section Break", "Column Break"}]
    layout_order = (*PRIMARY_FIELDS, ADVANCED, *ADVANCED_SWITCHES, ADVANCED_COLUMN, *advanced, CODE, "item_code")
    other_tabs = [row for row in fields[end:] if row["fieldname"] not in placed]
    return [*fields[:details + 1], *(by_name[name] for name in layout_order),
            by_name[NUTRITION_TAB], by_name[STATUS], by_name[NUTRITION_PREVIEW], *other_tabs]
