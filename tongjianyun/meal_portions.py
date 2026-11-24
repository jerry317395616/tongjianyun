"""Build single-meal recipes from the original recipe's ingredient rows."""

from contextvars import ContextVar
from decimal import Decimal, InvalidOperation

import frappe
from frappe.utils import flt, getdate
from ione_core import meal_planning as planning

from tongjianyun.dish_library import _supports_inline_ingredients, _visible
from tongjianyun.recipe_nutrition import SNAPSHOT
from tongjianyun.standard_recipes import MARKER, NET_QTY, REPLACES, STATE

SOURCE = "custom_tjy_meal_recipe_source"
SCOPE = "custom_tjy_meal_recipe_scope"
PENDING = "custom_tjy_meal_portions"
_BUILDING = ContextVar("tjy_meal_recipe_building", default=False)


class MealExecutionBOM:
    def manage_default_bom(self):
        if not self.get(SOURCE):
            return super().manage_default_bom()


def meal_scope(week, date, slot):
    return planning._digest([week, str(getdate(date)), slot])


def _check_recipe(bom, company):
    if bom.docstatus != 1 or not bom.is_active or bom.quantity != 1 or bom.company != company:
        frappe.throw("请选择本园所已发布且启用的单份配方。")


def _recipes(name, company, scope):
    current = _visible("BOM", name)
    _check_recipe(current, company)
    source = current.get(SOURCE)
    if not source:
        return current, current
    if current.get(SCOPE) != scope:
        frappe.throw("这份带量配方属于其他餐次。")
    standard = _visible("BOM", source)
    if (standard.get(SOURCE) or standard.item != current.item or standard.company != company
            or standard.docstatus != 1 or standard.quantity != 1):
        frappe.throw("本餐带量缺少有效的标准配方来源。")
    if [(row.item_code, row.uom) for row in current.items] != [(row.item_code, row.uom) for row in standard.items]:
        frappe.throw("本餐带量与来源配方的食材明细不一致。")
    return current, standard


@frappe.whitelist(methods=["GET"])
def details(week_name: str, meal_date: str, meal_type: str, bom_name: str):
    week = _visible("Meal Planning Week", week_name)
    if meal_type not in planning.SLOTS or getdate(meal_date) not in planning._dates(week):
        frappe.throw("请选择本周的有效餐次。")
    current, standard = _recipes(bom_name, week.company, meal_scope(week_name, meal_date, meal_type))
    adjustable = bool(standard.is_active and _supports_inline_ingredients(standard))
    current.apply_fieldlevel_read_permissions()
    if standard is not current:
        standard.apply_fieldlevel_read_permissions()
    if not current.get("items") or not standard.get("items"):
        return {"adjustable": False, "rows": []}
    return {"adjustable": adjustable, "rows": [
        dict(row=base.name, name=row.get("item_name") or row.get("item_code"), uom=row.get("uom"),
             standard_gross=base.get("qty"), standard_net=base.get(NET_QTY) or None,
             gross=row.get("qty"), net=row.get(NET_QTY) or None)
        for base, row in zip(standard.get("items") or [], current.get("items") or [], strict=True)
    ]}


def parse_portions(value):
    if not value:
        return {}
    try:
        portions = frappe.parse_json(value)
    except (TypeError, ValueError):
        frappe.throw("本餐带量格式有误，请重新打开餐次。")
    if not isinstance(portions, dict) or any(
        not isinstance(name, str) or not isinstance(rows, list) for name, rows in portions.items()
    ):
        frappe.throw("本餐带量格式有误，请重新打开餐次。")
    return portions


def _amount(value, row, field, label):
    try:
        amount = Decimal(str(value))
        if amount.is_finite() and abs(amount) < 10 ** 12 and amount == Decimal(str(flt(amount, row.precision(field)))):
            return float(amount)
    except (InvalidOperation, ValueError):
        pass
    frappe.throw(f"第 {row.idx} 行的{label}须为有效数字，且小数位数符合字段精度。")


def _changes(standard, requested):
    if requested and not _supports_inline_ingredients(standard):
        frappe.throw("按比例或工序计算的配方请通过标准配方修订。")
    existing = {row.name: row for row in standard.items}
    changes = {}
    seen = set()
    for entry in requested:
        key = entry.get("row") if isinstance(entry, dict) else None
        if not isinstance(key, str) or key not in existing or key in seen:
            frappe.throw("食材行已变更或重复，请重新打开带量明细。")
        seen.add(key)
        row = existing[key]
        gross = _amount(entry.get("gross"), row, "qty", "采购毛用量")
        raw_net = entry.get("net")
        net = None if raw_net in (None, "") else _amount(raw_net, row, NET_QTY, "可食净量")
        if gross <= 0 or (net is not None and not 0 <= net <= gross):
            frappe.throw(f"第 {row.idx} 行采购毛用量须大于 0，可食净量须在 0 与毛用量之间。")
        net = net or None
        if gross != row.qty or net != (row.get(NET_QTY) or None):
            changes[key] = (gross, net)
    return changes


def resolve(week, date, slot, name, requested):
    scope = meal_scope(week.name, date, slot)
    _, standard = _recipes(name, week.company, scope)
    _check_recipe(standard, week.company)
    changes = _changes(standard, requested)
    if not changes:
        return standard.name
    digest = planning._digest([scope, standard.name, sorted(changes.items())])
    name = f"BOM-MEAL-V{digest[:32].upper()}"
    if frappe.db.exists("BOM", name):
        recipe = frappe.get_doc("BOM", name)
        _check_recipe(recipe, week.company)
        if recipe.get(SCOPE) != scope or recipe.get(SOURCE) != standard.name or recipe.item != standard.item:
            frappe.throw("本餐执行配方归属不一致。")
        return name

    recipe = frappe.copy_doc(standard)
    recipe.update({SOURCE: standard.name, SCOPE: scope, MARKER: 0, STATE: None, REPLACES: None, SNAPSHOT: None,
                   "amended_from": None, "bom_creator": None, "bom_creator_item": None, "is_default": 0, "is_active": 1})
    for base, line in zip(standard.items, recipe.items, strict=True):
        if base.name in changes:
            gross, net = changes[base.name]
            line.update({"qty": gross, "stock_qty": gross * flt(line.conversion_factor), NET_QTY: net})
    token = _BUILDING.set(True)
    try:
        recipe.insert(ignore_permissions=True, set_name=name)
        recipe.flags.ignore_permissions = True
        recipe.submit()
    finally:
        _BUILDING.reset(token)
    return recipe.name


def protect_recipe(doc, method=None):
    previous = doc.get_doc_before_save()
    current_scoped = doc.get(SOURCE) or doc.get(SCOPE)
    previous_scoped = previous and (previous.get(SOURCE) or previous.get(SCOPE))
    if not (current_scoped or previous_scoped) or _BUILDING.get():
        return
    if method == "before_update_after_submit" and previous and all(
        doc.get(field) == previous.get(field) for field in (SOURCE, SCOPE, MARKER, "is_active", "is_default")
    ):
        return
    frappe.throw("请在对应餐次的周食谱或单餐变更中调整带量。")


def _scoped_recipes(names):
    if not names or not frappe.get_meta("BOM").has_field(SOURCE):
        return {}
    return {row.name: row for row in frappe.get_all(
        "BOM", filters={"name": ["in", names], SOURCE: ["is", "set"]}, fields=["name", SOURCE, SCOPE],
    )}


def validate_plan_scope(doc, method=None):
    recipes = _scoped_recipes({row.bom_no for row in doc.po_items or [] if row.bom_no})
    if not recipes:
        return
    scope = meal_scope(doc.custom_meal_week, doc.custom_meal_date, doc.custom_meal_type) if doc.get("custom_meal_week") else None
    for row in doc.po_items:
        recipe = recipes.get(row.bom_no)
        if not recipe or recipe.get(SCOPE) == scope:
            continue
        if doc.is_new() and doc.get("custom_meal_source") and planning._MANAGED.get() and scope:
            source = _visible("BOM", recipe.get(SOURCE))
            _check_recipe(source, doc.company)
            row.bom_no = source.name
        else:
            frappe.throw("本餐执行配方只能用于所属餐次。")


def validate_adjustment(doc, method=None):
    if doc.docstatus == 2:
        return
    boms = {row.bom_no for row in doc.dishes if row.bom_no}
    scope = meal_scope(doc.meal_week, doc.meal_date, doc.meal_type)
    if any(row.get(SCOPE) != scope for row in _scoped_recipes(boms).values()):
        frappe.throw("本餐执行配方只能用于所属餐次。")
    pending = {name: rows for name, rows in parse_portions(doc.get(PENDING)).items() if name in boms}
    if pending and not doc.service_suspended:
        company = frappe.db.get_value("Meal Planning Week", doc.meal_week, "company")
        for name, rows in pending.items():
            _, standard = _recipes(name, company, scope)
            _check_recipe(standard, company)
            _changes(standard, rows)
    doc.set(PENDING, frappe.as_json(pending) if pending else None)


def submit_adjustment(doc, method=None):
    pending = parse_portions(doc.get(PENDING))
    if not pending or doc.service_suspended:
        return
    week = _visible("Meal Planning Week", doc.meal_week)
    for row in doc.dishes:
        if row.bom_no in pending:
            row.bom_no = resolve(week, doc.meal_date, doc.meal_type, row.bom_no, pending[row.bom_no])
