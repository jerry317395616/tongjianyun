"""The dish catalog projects native Item and BOM records into the same workflow."""

from unicodedata import normalize
from uuid import uuid4

import frappe
from frappe.database.query import Engine
from frappe.model.document import copy_doc
from frappe.utils import cint

from tongjianyun.standard_recipes import (
    CATEGORY, CATEGORIES, DISH, DISH_CATEGORY, DRAFT, MARKER, PUBLISHED, REPLACES, STATE,
)

PAGE_SIZE = 20
BOM_FIELDS = ("name", "item", "company", "docstatus", "is_active", CATEGORY, STATE, REPLACES)


def _require(doctype, action="read"):
    frappe.has_permission(doctype, action, throw=True)


def _visible(doctype, name, *, lock=False):
    if not frappe.get_list(doctype, filters={"name": name}, pluck="name", page_length=1):
        frappe.throw("当前账号无法访问此记录。", frappe.PermissionError)
    doc = frappe.get_doc(doctype, name, for_update=lock)
    doc.check_permission("read")
    return doc


def _same_name(first, second):
    return normalize("NFKC", first).casefold() == normalize("NFKC", second).casefold()


def _valid_production_item(item):
    return not (item.disabled or item.is_purchase_item)


def _recipes(items):
    return frappe.get_list(
        "BOM", filters={MARKER: 1, "item": ["in", items]},
        fields=list(BOM_FIELDS), order_by="creation desc, name desc", limit_page_length=0,
    )


def _summary(dish, recipes):
    current = next((row for row in recipes if row.docstatus == 1 and row.is_active), None)
    draft = next((row for row in recipes if row.docstatus == 0), None)
    recipe = current or draft or next(iter(recipes), None)
    state = PUBLISHED if current else (
        (draft.get(STATE) or DRAFT) if draft else ("无在用配方" if recipes else "待配置配方")
    )
    return {
        "name": dish.name, "label": dish.item_name, "unit": dish.stock_uom,
        "category": dish.get(DISH_CATEGORY) or (recipe.get(CATEGORY) if recipe else None),
        "recipes": len(recipes), "state": state, "current": current.name if current else None,
        "draft_state": (draft.get(STATE) or DRAFT) if current and draft else None,
        "can_make_recipe": _valid_production_item(dish),
    }


def _check_dish(name):
    _require("BOM")
    dish = _visible("Item", name)
    recipes = _recipes([name])
    if not (dish.get(DISH) or recipes):
        frappe.throw("请选择库中的菜品。")
    return dish, recipes


@frappe.whitelist(methods=["GET"])
def dishes(search: str = "", start: int = 0):
    _require("Item")
    _require("BOM")
    item = frappe.qb.DocType("Item")
    known = Engine().get_query("BOM", fields=["item"], filters={MARKER: 1}, ignore_permissions=False)
    query = Engine().get_query(
        item, fields=["name", "item_name", "stock_uom", "disabled", "is_purchase_item", DISH_CATEGORY],
        ignore_permissions=False,
        order_by="item_name asc, name asc",
    ).where((getattr(item, DISH) == 1) | item.name.isin(known))
    search = str(search or "").strip()[:140]
    if search:
        pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(item.item_name.like(pattern) | item.name.like(pattern))
    found = query.limit(PAGE_SIZE + 1).offset(max(0, cint(start))).run(as_dict=True)
    page = found[:PAGE_SIZE]
    grouped = {row.name: [] for row in page}
    if grouped:
        for recipe in _recipes(list(grouped)):
            grouped[recipe.item].append(recipe)
    return {
        "rows": [_summary(row, grouped[row.name]) for row in page],
        "has_more": len(found) > PAGE_SIZE, "page_size": PAGE_SIZE,
        "can_create_dish": bool(frappe.has_permission("Item", "create")),
        "can_create_recipe": bool(frappe.has_permission("BOM", "create")),
        "categories": list(CATEGORIES), "default_unit": "份" if frappe.db.exists("UOM", {"name": "份", "enabled": 1}) else "",
    }


@frappe.whitelist(methods=["GET"])
def detail(dish: str):
    item, recipes = _check_dish(dish)
    can_create = _valid_production_item(item) and frappe.has_permission("BOM", "create")
    return {
        "dish": _summary(item, recipes),
        "recipes": [dict(
            name=row.name, company=row.company, from_recipe=row.get(REPLACES),
            state=PUBLISHED if row.docstatus == 1 else ("已作废" if row.docstatus == 2 else row.get(STATE) or DRAFT),
            active=bool(row.is_active), can_copy=row.docstatus == 1 and bool(row.is_active),
        ) for row in recipes],
        "can_create_recipe": bool(can_create),
    }


@frappe.whitelist(methods=["POST"])
def save_dish(label: str, category: str, unit: str | None = None,
              item_group: str | None = None, existing: str | None = None):
    _require("Item")
    _require("BOM")
    label = str(label or "").strip()
    if not label or len(label) > 140 or category not in CATEGORIES:
        frappe.throw("请填写有效的菜名和菜品分类。")
    if existing:
        item = _visible("Item", existing, lock=True)
        if not _valid_production_item(item) or not _same_name(item.item_name, label):
            frappe.throw("选择的物料与当前菜名或自制菜品条件不一致。")
        if not item.get(DISH):
            item.set(DISH, 1)
            item.set(DISH_CATEGORY, category)
            item.save()
        return {"dish": item.name}

    _require("Item", "create")
    # Serialize same-name catalog creation through the native Item metadata row.
    frappe.db.get_value("DocType", "Item", "name", for_update=True)
    candidates = Engine().get_query(
        "Item", fields=["name", "item_name", "item_group", "stock_uom"],
        filters={"item_name": label, "disabled": 0, "is_purchase_item": 0},
        ignore_permissions=False, for_update=True, limit=20,
    ).run(as_dict=True)
    matches = [row for row in candidates if _same_name(row.item_name, label)]
    if matches:
        return {"matches": matches}
    if not unit or not item_group:
        frappe.throw("请为新菜品选择默认单位和物料组。")
    if not frappe.db.exists("UOM", {"name": unit, "enabled": 1}):
        frappe.throw("请选择启用的默认单位。")
    item = frappe.new_doc("Item", item_code=f"DISH-{uuid4().hex[:12].upper()}", item_name=label,
                          item_group=item_group, stock_uom=unit, is_purchase_item=0, disabled=0)
    item.set(DISH, 1)
    item.set(DISH_CATEGORY, category)
    item.insert()
    return {"dish": item.name}


@frappe.whitelist(methods=["POST"])
def copy_recipe(dish: str, source: str):
    _require("BOM", "create")
    item, _ = _check_dish(dish)
    if not _valid_production_item(item):
        frappe.throw("请先启用菜品并确认其为自制物料。")
    previous = _visible("BOM", source)
    if previous.item != item.name or previous.docstatus != 1 or not previous.is_active or not previous.get(MARKER):
        frappe.throw("请选择该菜品已发布且启用的配方作为新版来源。")
    frappe.db.get_value("Item", item.name, "name", for_update=True)
    waiting = Engine().get_query(
        "BOM", fields=["name"], filters={MARKER: 1, "item": item.name, REPLACES: previous.name, "docstatus": 0},
        ignore_permissions=False, for_update=True, limit=1,
    ).run(as_dict=True)
    if waiting:
        return {"recipe": waiting[0].name}
    recipe = copy_doc(previous, ignore_no_copy=False)
    recipe.docstatus = 0
    recipe.set(MARKER, 1)
    recipe.set(REPLACES, previous.name)
    recipe.insert()
    return {"recipe": recipe.name}
