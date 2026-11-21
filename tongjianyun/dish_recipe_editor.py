"""Edit a standard dish's ingredient rows through its native BOM draft."""

from math import isfinite

import frappe
from erpnext.stock.get_item_details import get_conversion_factor

from tongjianyun.dish_library import (
    _can_select_company,
    _new_recipe_version,
    _recipe_versions,
    _recipes,
    _require,
    _supports_inline_ingredients,
    _valid_production_item,
    _visible,
)
from tongjianyun.standard_recipes import CATEGORY, DISH, DISH_CATEGORY, DRAFT, MARKER, NET_QTY, STATE


def _context(dish, company, *, lock=False):
    _require("BOM")
    if not company:
        frappe.throw("请选择配方所属机构。")
    item = _visible("Item", dish, lock=lock)
    if not item.get(DISH) or not _valid_production_item(item):
        frappe.throw("请选择启用的自制标准菜品。")
    recipes = _recipes([dish], company=company, lock=lock)
    if not recipes and not _can_select_company(company):
        frappe.throw("当前账号无法访问该机构的配方。", frappe.PermissionError)
    current, draft = _recipe_versions(recipes, company)
    return item, draft or current, bool(draft)


def _editable_bom(selection, editing_draft, *, lock=False):
    if not editing_draft:
        _require("BOM", "create")
    bom = _visible("BOM", selection.name, lock=lock) if selection else None
    if editing_draft:
        bom.check_permission("write")
        if bom.docstatus != 0 or (bom.get(STATE) or DRAFT) != DRAFT:
            frappe.throw("请在配方表单撤回审核后，再编辑食材。")
    if bom and not _supports_inline_ingredients(bom):
        frappe.throw("按比例或工序计算用量的配方，请在原生配方表单中编辑。")
    if frappe.session.user != "Administrator":
        item_meta = frappe.get_meta("BOM Item")
        fields = [frappe.get_meta("BOM").get_field("items")]
        fields.extend(item_meta.get_field(key) for key in ("item_code", "qty", NET_QTY, "uom", "conversion_factor"))
        permissions_doc = bom or frappe.new_doc("BOM")
        readable = permissions_doc.get_permlevel_access("read")
        writable = permissions_doc.get_permlevel_access("write")
        if any(df.permlevel and (df.permlevel not in readable or df.permlevel not in writable) for df in fields):
            frappe.throw("当前账号无权编辑食材明细。", frappe.PermissionError)
    return bom


@frappe.whitelist(methods=["GET"])
def load_editor(dish: str, company: str):
    _, selection, editing_draft = _context(dish, company)
    bom = _editable_bom(selection, editing_draft)
    if not bom:
        return {"recipe": None, "modified": None, "mode": "new", "ingredients": []}
    bom.apply_fieldlevel_read_permissions()
    return {
        "recipe": bom.name, "modified": str(bom.modified), "mode": "draft" if editing_draft else "revision",
        "ingredients": [dict(
            row=row.name, item_code=row.item_code, name=row.get("item_name") or row.item_code,
            gross=row.qty, net=row.get(NET_QTY) or None, uom=row.uom,
        ) for row in bom.get("items") or []],
    }


@frappe.whitelist(methods=["POST"])
def save_ingredients(dish: str, company: str, ingredients: str, recipe: str | None = None,
                     modified: str | None = None):
    rows = _parse_ingredients(ingredients)
    item, selection, editing_draft = _context(dish, company, lock=True)
    if (selection.name if selection else None) != (recipe or None):
        frappe.throw("配方已变更，请重新加载配方后再编辑。")
    source = _editable_bom(selection, editing_draft, lock=True)
    if source and str(source.modified) != modified:
        frappe.throw("配方已变更，请重新加载配方后再编辑。")

    bom = source if editing_draft else _first_or_revised_bom(item, company, source)
    existing = {row.name: child for row, child in zip(source.items, bom.items, strict=True)} if source else {}
    bom.set("items", [])
    for index, values in enumerate(rows, start=1):
        _apply_ingredient(bom, existing, values, index)
    if editing_draft:
        bom.save()
    else:
        bom.insert()
    return {"recipe": bom.name}


def _first_or_revised_bom(item, company, source):
    # The Item lock also serializes the native copy-for-revision endpoint.
    if frappe.db.get_value("BOM", {MARKER: 1, "item": item.name, "company": company, "docstatus": 0},
                           "name", for_update=True):
        frappe.throw("该机构已有配方草稿，请刷新后打开已有草稿。")
    if source:
        bom = _new_recipe_version(source)
        bom.is_active = 1
        bom.is_default = source.is_default
        return bom
    if not item.get(DISH_CATEGORY):
        frappe.throw("请先填写并保存菜品分类。")
    bom = frappe.new_doc("BOM", item=item.name, company=company, quantity=1, is_active=1, is_default=0)
    bom.set(MARKER, 1)
    bom.set(CATEGORY, item.get(DISH_CATEGORY))
    return bom


def _parse_ingredients(payload):
    try:
        rows = frappe.parse_json(payload)
    except ValueError:
        frappe.throw("食材明细格式有误，请重新加载配方后再编辑。")
    if not isinstance(rows, list) or not rows or not all(isinstance(row, dict) for row in rows):
        frappe.throw("请至少添加一条有效的食材明细。")
    return rows


def _quantity(value, index, label):
    try:
        number = float(str(value))
        if isfinite(number):
            return number
    except (ValueError, OverflowError):
        pass
    frappe.throw(f"第 {index} 行的{label}须为有效数字。")


def _apply_ingredient(bom, existing, values, index):
    row_id = values.get("row")
    if row_id and (not isinstance(row_id, str) or row_id not in existing):
        frappe.throw(f"第 {index} 行食材已变更，请重新加载配方。")
    row = existing.pop(row_id) if row_id else None
    code = values.get("item_code")
    unit = values.get("uom")
    if not isinstance(code, str) or not code or code == bom.item:
        frappe.throw(f"请为第 {index} 行选择有效的食材。")
    if row and row.item_code != code:
        frappe.throw(f"第 {index} 行需要更换食材时，请删除原行并添加新行。")
    if not isinstance(unit, str) or not unit:
        frappe.throw(f"请选择第 {index} 行的食材单位。")
    gross = _quantity(values.get("gross"), index, "采购毛用量")
    net_value = values.get("net")
    net = _quantity(net_value, index, "可食净量") if net_value not in (None, "") else None
    if gross <= 0 or (net is not None and not 0 <= net <= gross):
        frappe.throw(f"第 {index} 行采购毛用量须大于 0，可食净量须在 0 与毛用量之间。")

    factor = float(row.conversion_factor or 0) if row and row.uom == unit else 0
    if factor <= 0:
        factor = _checked_factor(code, unit, index)
    stock_qty = gross * factor
    if not isfinite(stock_qty):
        frappe.throw(f"第 {index} 行换算后的食材用量超出允许范围。")
    line = bom.append("items", row) if row else bom.append("items", {"item_code": code})
    if row and row.uom != unit:
        line.rate = float(line.rate or 0) / float(line.conversion_factor or 1) * factor
    line.update(dict(uom=unit, qty=gross, conversion_factor=factor, stock_qty=stock_qty))
    line.set(NET_QTY, net)


def _checked_factor(code, unit, index):
    item = _visible("Item", code)
    if item.disabled or item.is_fixed_asset or not item.include_item_in_manufacturing:
        frappe.throw(f"第 {index} 行物料无法用于配方。")
    if not frappe.db.exists("UOM", {"name": unit, "enabled": 1}):
        frappe.throw(f"第 {index} 行食材单位未启用。")
    factor = float(get_conversion_factor(code, unit).get("conversion_factor") or 0)
    if factor <= 0 or not isfinite(factor):
        frappe.throw(f"第 {index} 行食材需要配置该单位的换算系数。")
    return factor
