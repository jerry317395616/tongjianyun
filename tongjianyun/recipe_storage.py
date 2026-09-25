from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import frappe
from frappe import _
from frappe.query_builder.functions import Count
from frappe.utils import cint, flt, getdate, now_datetime, nowdate

RECIPE_DOCTYPE = "Tongjianyun Recipe"
DISH_DOCTYPE = "Tongjianyun Recipe Dish"
INGREDIENT_DOCTYPE = "Tongjianyun Recipe Ingredient"

PROCUREMENT_REQUEST_TITLE_PREFIX = "童健云食谱采购 · "

MEAL_SLOTS = ("breakfast", "morningSnack", "lunch", "snack", "dinner")
MEAL_LABELS = {
    "breakfast": "\u65e9\u9910",
    "morningSnack": "\u65e9\u70b9",
    "lunch": "\u5348\u9910",
    "snack": "\u5348\u70b9",
    "dinner": "\u665a\u9910",
}


def _doctype_available(doctype: str) -> bool:
    """Return whether a DocType is registered, not merely backed by an old table."""
    try:
        return bool(frappe.db.exists("DocType", doctype))
    except Exception:
        return False


def _require_login() -> None:
    if frappe.session.user == "Guest":
        frappe.throw(_("Not logged in."), frappe.AuthenticationError)


def _require_recipe_write() -> None:
    _require_login()
    if not frappe.has_permission(RECIPE_DOCTYPE, ptype="write"):
        frappe.throw(_("Not permitted."), frappe.PermissionError)


def _can_restore_recipe() -> bool:
    return frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles(frappe.session.user) or (
        "Tongjianyun Business Operator" in frappe.get_roles(frappe.session.user)
        and frappe.has_permission(RECIPE_DOCTYPE, ptype="write")
    )


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value) if value.strip() else {}
        return parsed if isinstance(parsed, dict) else {}
    return dict(value)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        parsed = json.loads(value) if value.strip() else []
        return parsed if isinstance(parsed, list) else []
    return list(value)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _row_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(_clean(part) for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _grams(amount: float, unit: str) -> float:
    normalized = _clean(unit).lower()
    if normalized in {"g", "gram", "grams", "\u514b"}:
        return amount
    if normalized in {"kg", "kilogram", "kilograms", "\u5343\u514b", "\u516c\u65a4"}:
        return amount * 1000
    if normalized in {"mg", "milligram", "milligrams", "\u6beb\u514b"}:
        return amount / 1000
    return 0


def _save_doc(doc) -> None:
    doc.flags.ignore_permissions = True
    if doc.name:
        doc.save(ignore_permissions=True)
    else:
        doc.insert(ignore_permissions=True)


def _delete_recipe_rows(recipe_name: str) -> None:
    frappe.db.delete(INGREDIENT_DOCTYPE, {"recipe": recipe_name})
    frappe.db.delete(DISH_DOCTYPE, {"recipe": recipe_name})


def _get_recipe_name(recipe: str) -> str:
    recipe_name = frappe.db.exists(RECIPE_DOCTYPE, recipe) or frappe.db.exists(
        RECIPE_DOCTYPE,
        {"recipe_id": recipe},
    )
    if not recipe_name:
        frappe.throw(_("Recipe not found."), frappe.DoesNotExistError)
    return recipe_name


def _unique_linked_parents(child_doctype: str, filters: dict[str, Any]) -> list[str]:
    if not _doctype_available(child_doctype) or not frappe.db.table_exists(child_doctype):
        return []
    rows = frappe.get_all(
        child_doctype,
        filters=filters,
        pluck="parent",
        limit_page_length=0,
    )
    return sorted({_clean(name) for name in rows if _clean(name)})


def _erpnext_procurement_links(recipe_doc) -> list[dict[str, Any]]:
    """Return ERPNext procurement records created from this recipe."""
    if not _doctype_available("Material Request") or not frappe.db.table_exists("Material Request"):
        return []

    request_title = PROCUREMENT_REQUEST_TITLE_PREFIX + _clean(recipe_doc.name)
    requests = [
        _clean(name)
        for name in frappe.get_all(
            "Material Request",
            filters={
                "title": request_title,
                "material_request_type": "Purchase",
            },
            pluck="name",
            limit_page_length=0,
        )
        if _clean(name)
    ]
    if not requests:
        return []

    links = [{"doctype": "Material Request", "label": "采购需求", "count": len(set(requests))}]
    orders = _unique_linked_parents(
        "Purchase Order Item",
        {"material_request": ["in", requests]},
    )
    if orders:
        links.append({"doctype": "Purchase Order", "label": "采购订单", "count": len(orders)})

        receipts = _unique_linked_parents(
            "Purchase Receipt Item",
            {"purchase_order": ["in", orders]},
        )
        if receipts:
            links.append({"doctype": "Purchase Receipt", "label": "采购收货", "count": len(receipts)})

        invoices = _unique_linked_parents(
            "Purchase Invoice Item",
            {"purchase_order": ["in", orders]},
        )
        if invoices:
            links.append({"doctype": "Purchase Invoice", "label": "采购发票", "count": len(invoices)})
    return links


def _recipe_business_links(recipe_doc) -> list[dict[str, Any]]:
    """Return downstream business records that overlap or identify this recipe."""

    links: list[dict[str, Any]] = _erpnext_procurement_links(recipe_doc)

    if recipe_doc.week_start and recipe_doc.week_end:
        for doctype, label, date_field in (
            ("Tongjianyun Daily Meal Confirmation", "就餐确认", "meal_date"),
            ("Tongjianyun Daily Meal Adjustment", "就餐调整", "meal_date"),
        ):
            if (
                not _doctype_available(doctype)
                or not frappe.db.table_exists(doctype)
                or not frappe.db.has_column(doctype, date_field)
            ):
                continue
            count = frappe.db.count(
                doctype,
                {date_field: ["between", [recipe_doc.week_start, recipe_doc.week_end]]},
            )
            if count:
                links.append({"doctype": doctype, "label": label, "count": count})
    return links


def _recipe_actions(doc, links: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    status = doc.workflow_status or "草稿"
    links = links if links is not None else _recipe_business_links(doc)
    return {
        "can_delete": not doc.is_deleted and not links,
        "can_withdraw": not doc.is_deleted and status == "待审核",
        "can_archive": not doc.is_deleted and status == "已发布",
        "can_restore": bool(doc.is_deleted) and _can_restore_recipe(),
        "business_links": links,
    }


def _move_recipe_to_recycle_bin(doc) -> None:
    doc.status_before_delete = doc.workflow_status or "草稿"
    doc.is_deleted = 1
    doc.deleted_at = now_datetime()
    doc.deleted_by = frappe.session.user


def _recipe_payload(doc) -> dict[str, Any]:
    return {
        "recipeId": doc.recipe_id,
        "title": doc.title or "",
        "weekStart": str(doc.week_start or ""),
        "weekEnd": str(doc.week_end or ""),
        "sourceFileName": doc.source_file_name or "",
        "parser": doc.parser or "",
        "relationSource": doc.relation_source or "",
        "importedAt": str(doc.imported_at or ""),
        "workflowStatus": doc.workflow_status or "草稿",
        "isDeleted": bool(doc.is_deleted),
        "revision": str(doc.modified or ""),
    }


def _save_current_recipe(payload: Any, *, commit: bool) -> dict[str, Any]:
    _require_recipe_write()
    from tongjianyun.recipe_week import lock_recipe_writes, validate_weekly_recipe, week_bounds
    lock_recipe_writes()
    root = _as_dict(payload)
    recipe_data = _as_dict(root.get("recipe"))
    days = [_as_dict(day) for day in _as_list(root.get("days"))]
    recipe_id = _clean(recipe_data.get("recipeId")) or "current"

    existing = frappe.db.exists(RECIPE_DOCTYPE, {"recipe_id": recipe_id})
    recipe = frappe.get_doc(RECIPE_DOCTYPE, existing) if existing else frappe.new_doc(RECIPE_DOCTYPE)
    if recipe.get("is_deleted"):
        frappe.throw("该食谱已在回收站中，请先恢复后再编辑。")
    if recipe.get('workflow_status') == '已归档':
        frappe.throw('这份食谱已归档，仅供查阅历史；请编辑本周当前食谱。')
    recipe.check_permission('write' if existing else 'create')
    week_bounds(recipe_data.get('weekStart'), recipe_data.get('weekEnd'))
    dates = [getdate(day['date']) if day.get('date') else None for day in days]
    if (len(set(dates)) != len(dates) or any(day is None or not
            getdate(recipe_data['weekStart']) <= day <= getdate(recipe_data['weekEnd']) for day in dates)):
        frappe.throw('食谱日期不能重复，且必须位于本周起止日期内。')
    previous = None
    if existing:
        locked_revision = frappe.db.get_value(RECIPE_DOCTYPE, recipe.name, 'modified', for_update=True)
        if (not recipe_data.get('revision') or str(recipe_data['revision']) != str(locked_revision)
                or str(recipe.modified) != str(locked_revision)):
            frappe.throw('食谱已更新或缺少版本号。请重新读取这份食谱后再保存，不要另建副本。')
        if (str(recipe.week_start) != str(recipe_data.get('weekStart'))
                or str(recipe.week_end) != str(recipe_data.get('weekEnd'))):
            frappe.throw('编辑不能改变原食谱日期范围；编排另一周时请新建该周食谱。')
        previous = _current_recipe_payload(recipe)
        from tongjianyun.meal_scene import editable_day_content
        current_days = {str(day.get('date')): day for day in days}
        for old in previous['days']:
            if old.get('locked'):
                current = current_days.get(str(old['date']))
                if current is None or editable_day_content(current) != editable_day_content(old):
                    frappe.throw(f"{old['date']} 的食谱已锁定，不能修改或删除该日内容。")
                # Client payloads cannot clear an existing execution lock.
                current.clear()
                current.update(deepcopy(old))
    recipe.recipe_id = recipe_id
    recipe.title = (_clean(recipe_data.get("title")) or "\u5f53\u524d\u5468\u98df\u8c31")[:140]
    recipe.week_start = recipe_data.get("weekStart") or None
    recipe.week_end = recipe_data.get("weekEnd") or None
    recipe.source_file_name = _clean(recipe_data.get("sourceFileName"))[:140]
    recipe.parser = _clean(recipe_data.get("parser"))[:140]
    recipe.relation_source = _clean(recipe_data.get("relationSource"))[:140]
    recipe.imported_at = recipe_data.get("importedAt") or now_datetime()
    # Content saving is never publishing or replaying downstream purchasing.
    recipe.workflow_status = '草稿'
    validate_weekly_recipe(recipe)
    if previous:
        frappe.get_doc({'doctype': 'Version', 'ref_doctype': RECIPE_DOCTYPE, 'docname': recipe.name,
            'data': json.dumps({'recipe_snapshot': previous, 'recipe_revision': str(locked_revision),
                                'changed': [], 'added': [], 'removed': [], 'row_changed': []},
                               ensure_ascii=False, default=str)}).insert(ignore_permissions=True)
    _save_doc(recipe)

    _delete_recipe_rows(recipe.name)

    for day_index, day in enumerate(days):
        day_id = _clean(day.get("id")) or f"DAY-{day_index + 1}"
        meal_date = day.get("date") or None
        day_label = _clean(day.get("day"))
        portions = [_as_dict(portion) for portion in _as_list(day.get("portions"))]
        for portion_index, portion in enumerate(portions):
            slot = _clean(portion.get("slot"))
            if slot not in MEAL_SLOTS:
                continue
            ingredient_rows = [_as_dict(row) for row in _as_list(portion.get("dishIngredientRows"))]
            dish_names: list[str] = []
            for value in _as_list(portion.get("dishes")):
                name = _clean(value)
                if name and name not in dish_names:
                    dish_names.append(name)
            for row in ingredient_rows:
                name = _clean(row.get("dishName"))
                if name and name not in dish_names:
                    dish_names.append(name)
            if not dish_names:
                fallback_name = _clean(day.get(slot))
                if fallback_name:
                    dish_names.append(fallback_name)

            unassigned = [row for row in ingredient_rows if not _clean(row.get("dishName"))]
            if unassigned and len(dish_names) != 1:
                ingredient_names = "\u3001".join(_clean(row.get("ingredient")) for row in unassigned[:5])
                frappe.throw(_("Ingredients must be linked to a dish: {0}").format(ingredient_names))

            for dish_order, dish_name in enumerate(dish_names):
                dish_row_id = _row_id(
                    "DISH",
                    recipe.name,
                    day_id,
                    slot,
                    dish_order,
                    dish_name,
                )
                dish = frappe.new_doc(DISH_DOCTYPE)
                dish.dish_row_id = dish_row_id
                dish.recipe = recipe.name
                dish.day_id = day_id
                dish.meal_date = meal_date
                dish.day_label = day_label
                dish.meal_slot = slot
                dish.meal_label = _clean(portion.get("label")) or MEAL_LABELS[slot]
                dish.dish_name = dish_name
                dish.dish_order = dish_order
                dish.amount_per_child_text = _clean(portion.get("amountPerChild"))
                dish.total_amount_text = _clean(portion.get("totalAmount"))
                dish.day_score = flt(day.get("score"))
                dish.day_risk = _clean(day.get("risk"))
                dish.day_locked = cint(day.get("locked"))
                dish.day_updated_at = day.get("updatedAt") or None
                dish.day_updated_by = _clean(day.get("updatedBy"))[:140]
                dish.day_edit_reason = _clean(day.get("editReason"))
                dish.day_version = max(1, cint(day.get("version")))
                dish.sort_order = day_index * 1000 + portion_index * 100 + dish_order
                _save_doc(dish)

                linked_rows = [
                    row
                    for row in ingredient_rows
                    if _clean(row.get("dishName")) == dish_name
                    or (not _clean(row.get("dishName")) and len(dish_names) == 1)
                ]
                for ingredient_order, row in enumerate(linked_rows):
                    ingredient_name = _clean(row.get("ingredient"))
                    if not ingredient_name:
                        continue
                    amount = flt(row.get("amount"))
                    unit = _clean(row.get("unit")) or "g"
                    ingredient = frappe.new_doc(INGREDIENT_DOCTYPE)
                    ingredient.ingredient_row_id = _row_id(
                        "ING",
                        dish_row_id,
                        ingredient_order,
                        ingredient_name,
                        amount,
                        unit,
                    )
                    ingredient.recipe = recipe.name
                    ingredient.recipe_dish = dish.name
                    ingredient.ingredient_name = ingredient_name
                    ingredient.amount = amount
                    ingredient.unit = unit
                    ingredient.grams_per_child = _grams(amount, unit)
                    ingredient.sort_order = ingredient_order
                    _save_doc(ingredient)

    from tongjianyun.recipe_item_sync import schedule_after_save
    sync = schedule_after_save(recipe.name)
    if commit:
        frappe.db.commit()
    result = _current_recipe_payload(recipe)
    result["erp_sync"] = sync
    return result


def _current_recipe_payload(recipe) -> dict[str, Any]:
    dish_rows = frappe.get_all(
        DISH_DOCTYPE,
        filters={"recipe": recipe.name},
        fields=[
            "name",
            "day_id",
            "meal_date",
            "day_label",
            "meal_slot",
            "meal_label",
            "dish_name",
            "dish_order",
            "amount_per_child_text",
            "total_amount_text",
            "day_score",
            "day_risk",
            "day_locked",
            "day_updated_at",
            "day_updated_by",
            "day_edit_reason",
            "day_version",
            "sort_order",
        ],
        order_by="sort_order asc, dish_order asc",
        limit_page_length=0,
    )
    ingredient_rows = frappe.get_all(
        INGREDIENT_DOCTYPE,
        filters={"recipe": recipe.name},
        fields=["recipe_dish", "ingredient_name", "amount", "unit", "grams_per_child", "sort_order"],
        order_by="sort_order asc",
        limit_page_length=0,
    )
    ingredients_by_dish: dict[str, list[dict[str, Any]]] = {}
    for row in ingredient_rows:
        ingredients_by_dish.setdefault(row.recipe_dish, []).append(
            {
                "ingredient": row.ingredient_name,
                "amount": flt(row.amount),
                "unit": row.unit or "g",
                "gramsPerChild": flt(row.grams_per_child),
            }
        )

    days: dict[str, dict[str, Any]] = {}
    day_order: list[str] = []
    portions_by_day: dict[str, dict[str, dict[str, Any]]] = {}
    for row in dish_rows:
        day_key = row.day_id or str(row.meal_date or "")
        if day_key not in days:
            day_order.append(day_key)
            days[day_key] = {
                "id": day_key,
                "date": str(row.meal_date or ""),
                "day": row.day_label or "",
                "breakfast": "",
                "morningSnack": "",
                "lunch": "",
                "snack": "",
                "dinner": "",
                "portions": [],
                "score": flt(row.day_score),
                "risk": row.day_risk or "normal",
                "locked": bool(row.day_locked),
                "updatedAt": str(row.day_updated_at or ""),
                "updatedBy": row.day_updated_by or "",
                "editReason": row.day_edit_reason or "",
                "version": max(1, cint(row.day_version)),
            }
            portions_by_day[day_key] = {}
        portions = portions_by_day[day_key]
        if row.meal_slot not in portions:
            portions[row.meal_slot] = {
                "slot": row.meal_slot,
                "label": row.meal_label or MEAL_LABELS.get(row.meal_slot, row.meal_slot),
                "dishes": [],
                "amountPerChild": row.amount_per_child_text or "",
                "totalAmount": row.total_amount_text or "",
                "energyKcal": 0,
                "proteinG": 0,
                "dishIngredientRows": [],
            }
        portion = portions[row.meal_slot]
        portion["dishes"].append(row.dish_name)
        for ingredient in ingredients_by_dish.get(row.name, []):
            portion["dishIngredientRows"].append(
                {
                    "dishName": row.dish_name,
                    "ingredient": ingredient["ingredient"],
                    "amount": ingredient["amount"],
                    "unit": ingredient["unit"],
                    "gramsPerChild": ingredient["gramsPerChild"],
                }
            )

    result_days: list[dict[str, Any]] = []
    for day_key in day_order:
        day = days[day_key]
        portions = portions_by_day[day_key]
        day["portions"] = [portions[slot] for slot in MEAL_SLOTS if slot in portions]
        for slot in MEAL_SLOTS:
            day[slot] = " / ".join(portions.get(slot, {}).get("dishes", []))
        result_days.append(day)

    return {"recipe": _recipe_payload(recipe), "days": result_days}


@frappe.whitelist()
def get_current_recipe() -> dict[str, Any] | None:
    _require_login()
    name = frappe.db.get_value(RECIPE_DOCTYPE, {"recipe_id": "current", "is_deleted": 0, "workflow_status": ["!=", "已归档"]}, "name")
    if not name:
        name = frappe.db.get_value(
            RECIPE_DOCTYPE,
            {"week_start": ["<=", nowdate()], "week_end": [">=", nowdate()], "is_deleted": 0, "workflow_status": ["!=", "已归档"]},
            "name",
            order_by="modified desc",
        )
    if not name:
        name = frappe.db.get_value(
            RECIPE_DOCTYPE,
            {"is_deleted": 0, "workflow_status": ["!=", "已归档"]},
            "name",
            order_by="week_start desc, modified desc",
        )
    if not name:
        return None
    return _current_recipe_payload(frappe.get_doc(RECIPE_DOCTYPE, name))


@frappe.whitelist()
def get_recipe_detail(recipe: str) -> dict[str, Any]:
    _require_login()
    recipe_name = _get_recipe_name(recipe)
    return _current_recipe_payload(frappe.get_doc(RECIPE_DOCTYPE, recipe_name))


@frappe.whitelist()
def get_recipe_history(recipe: str, version: str | None = None) -> dict[str, Any]:
    """Read prior complete versions without making a second weekly recipe."""
    _require_login()
    doc = frappe.get_doc(RECIPE_DOCTYPE, _get_recipe_name(recipe))
    doc.check_permission('read')
    if version:
        row = frappe.get_doc('Version', version)
        if row.ref_doctype != RECIPE_DOCTYPE or row.docname != doc.name:
            frappe.throw('版本不属于当前食谱。', frappe.PermissionError)
        # Require complete detail visibility, as for editing this recipe.
        from tongjianyun.meal_scene import get_recipe
        get_recipe(doc.name)
        snapshot = json.loads(row.data or '{}').get('recipe_snapshot')
        if not snapshot:
            frappe.throw('该历史记录不是完整食谱快照。')
        return {'name': row.name, 'created': str(row.creation), 'payload': snapshot}
    rows = frappe.get_all('Version', filters={'ref_doctype': RECIPE_DOCTYPE, 'docname': doc.name},
                         fields=['name', 'creation', 'owner', 'data'], order_by='creation desc', limit_page_length=100)
    return {'recipe': doc.name, 'versions': [
        {'name': row.name, 'created': str(row.creation), 'actor': row.owner}
        for row in rows if 'recipe_snapshot' in json.loads(row.data or '{}')]}


@frappe.whitelist()
def get_recipe_library(
    search: str | None = None,
    status: str | None = None,
    include_test: int | None = None,
    recycle_bin: int = 0,
    start: int = 0,
    page_length: int = 50,
) -> dict[str, Any]:
    """Return the recipe-library projection; ``include_test`` is kept for old clients."""

    _require_login()
    start = max(0, cint(start))
    page_length = min(100, max(1, cint(page_length) or 50))
    filters: list[list[Any]] = []
    or_filters: list[list[Any]] = []
    search_text = _clean(search)
    if search_text:
        or_filters.extend(
            [
                [RECIPE_DOCTYPE, "title", "like", f"%{search_text}%"],
                [RECIPE_DOCTYPE, "recipe_id", "like", f"%{search_text}%"],
            ]
        )
    status_text = _clean(status)
    filters.append([RECIPE_DOCTYPE, "is_deleted", "=", 1 if cint(recycle_bin) else 0])
    if status_text and status_text not in {"全部", "回收站"}:
        filters.append([RECIPE_DOCTYPE, "workflow_status", "=", status_text])
    recipes = frappe.get_list(
        RECIPE_DOCTYPE,
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name",
            "recipe_id",
            "title",
            "week_start",
            "week_end",
            "source_file_name",
            "parser",
            "relation_source",
            "imported_at",
            "modified",
            "modified_by",
            "workflow_status",
            "is_deleted",
            "status_before_delete",
            "deleted_at",
            "deleted_by",
        ],
        order_by="week_start desc, modified desc",
        start=start,
        page_length=page_length,
    )
    recipe_names = [row.name for row in recipes]
    counts: dict[str, dict[str, int]] = {
        name: {"dish_count": 0, "ingredient_count": 0} for name in recipe_names
    }
    if recipe_names:
        dish = frappe.qb.DocType(DISH_DOCTYPE)
        dish_counts = (
            frappe.qb.from_(dish)
            .select(dish.recipe, Count(dish.name).as_("dish_count"))
            .where(dish.recipe.isin(recipe_names))
            .groupby(dish.recipe)
        ).run(as_dict=True)
        ingredient = frappe.qb.DocType(INGREDIENT_DOCTYPE)
        ingredient_counts = (
            frappe.qb.from_(ingredient)
            .select(ingredient.recipe, Count(ingredient.name).as_("ingredient_count"))
            .where(ingredient.recipe.isin(recipe_names))
            .groupby(ingredient.recipe)
        ).run(as_dict=True)
        for row in dish_counts:
            counts[row.recipe]["dish_count"] = cint(row.dish_count)
        for row in ingredient_counts:
            counts[row.recipe]["ingredient_count"] = cint(row.ingredient_count)

    items = []
    for row in recipes:
        item = dict(row)
        item.update(counts[row.name])
        recipe_doc = frappe.get_doc(RECIPE_DOCTYPE, row.name)
        links = _recipe_business_links(recipe_doc)
        item["workflow_status"] = item.get("workflow_status") or ("已发布" if item["dish_count"] else "草稿")
        item["status"] = {
            "草稿": "draft",
            "待审核": "review",
            "已发布": "published",
            "已归档": "archived",
        }.get(item["workflow_status"], "draft")
        item["display_status"] = "回收站" if item.get("is_deleted") else item["workflow_status"]
        if item.get("is_deleted"):
            item["status"] = "deleted"
        item["actions"] = _recipe_actions(recipe_doc, links)
        items.append(item)

    return {
        "items": items,
        "start": start,
        "page_length": page_length,
        "has_more": len(items) == page_length,
    }


@frappe.whitelist()
def get_recipe_actions(recipe: str) -> dict[str, Any]:
    _require_login()
    doc = frappe.get_doc(RECIPE_DOCTYPE, _get_recipe_name(recipe))
    return _recipe_actions(doc)


@frappe.whitelist()
def update_recipe_lifecycle(recipe: str, action: str) -> dict[str, Any]:
    _require_recipe_write()
    doc = frappe.get_doc(RECIPE_DOCTYPE, _get_recipe_name(recipe))
    action = _clean(action)
    status = doc.workflow_status or "草稿"

    if action == "withdraw":
        if doc.is_deleted or status != "待审核":
            frappe.throw(_("Only recipes awaiting review can be withdrawn."))
        doc.workflow_status = "草稿"
        message = "食谱已撤回为草稿"
    elif action == "archive":
        if doc.is_deleted or status != "已发布":
            frappe.throw(_("Only published recipes can be archived."))
        doc.workflow_status = "已归档"
        message = "食谱已归档"
    elif action == "delete":
        if doc.is_deleted:
            frappe.throw(_("Recipe is already in the recycle bin."))
        links = _recipe_business_links(doc)
        if links:
            details = "、".join(f"{row['label']} {row['count']} 条" for row in links)
            frappe.throw(f"该食谱已有下游业务数据（{details}），不能删除。")
        _move_recipe_to_recycle_bin(doc)
        message = "食谱已移入回收站"
    elif action == "restore":
        if not _can_restore_recipe():
            frappe.throw("只有系统管理员可以从回收站恢复食谱。", frappe.PermissionError)
        if not doc.is_deleted:
            frappe.throw(_("Recipe is not in the recycle bin."))
        doc.workflow_status = doc.status_before_delete or "草稿"
        doc.is_deleted = 0
        doc.status_before_delete = ""
        doc.deleted_at = None
        doc.deleted_by = ""
        message = "食谱已恢复"
    else:
        frappe.throw(_("Unsupported recipe action."))

    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {
        "name": doc.name,
        "workflow_status": doc.workflow_status,
        "is_deleted": bool(doc.is_deleted),
        "message": message,
        "actions": _recipe_actions(doc),
    }


@frappe.whitelist()
def bulk_delete_recipes(recipes: Any) -> dict[str, Any]:
    """Move selected recipes to the recycle bin using the normal lifecycle policy."""

    _require_recipe_write()
    selected = list(dict.fromkeys(_clean(value) for value in _as_list(recipes) if _clean(value)))
    if not selected:
        frappe.throw("请至少选择一份食谱。")
    if len(selected) > 100:
        frappe.throw("单次最多删除 100 份食谱。")

    moved: list[str] = []
    blocked: list[dict[str, Any]] = []
    for value in selected:
        try:
            recipe_name = _get_recipe_name(value)
            result = update_recipe_lifecycle(recipe_name, "delete")
            moved.append(result["name"])
        except Exception as exc:
            blocked.append({"name": value, "reason": _clean(getattr(exc, "message", None) or exc)})
            frappe.db.rollback()

    frappe.db.commit()
    return {"moved": len(moved), "names": moved, "blocked": blocked}


@frappe.whitelist()
def save_current_recipe(payload: Any = None) -> dict[str, Any]:
    _require_login()
    return _save_current_recipe(payload, commit=True)


def save_recipe_payload(payload: Any, *, commit: bool = False) -> dict[str, Any]:
    """Persist one complete recipe payload for trusted in-process integrations.

    Row identifiers remain server-managed: dishes and ingredients are rebuilt
    atomically by ``_save_current_recipe`` and receive deterministic IDs from
    their recipe, day, meal and row content.
    """

    return _save_current_recipe(payload, commit=commit)


@frappe.whitelist()
def delete_current_recipe() -> dict[str, int]:
    """Retain the legacy endpoint while enforcing the lifecycle policy.

    Older clients still call this method for the special ``current`` recipe.
    Route those requests through the same guarded soft-delete operation used by
    the workbench so the endpoint cannot bypass status or downstream-data
    checks and cannot physically erase recipe history.
    """

    _require_recipe_write()
    names = frappe.get_all(
        RECIPE_DOCTYPE,
        filters={"recipe_id": "current", "is_deleted": 0},
        pluck="name",
        limit_page_length=0,
    )
    for name in names:
        update_recipe_lifecycle(name, "delete")
    return {"deleted": 0, "moved_to_recycle_bin": len(names)}


def install() -> None:
    table_columns = set(frappe.db.get_table_columns(RECIPE_DOCTYPE))
    for fieldname in (
        "is_current",
        "status",
        "age_group",
        "estimated_children",
        "source",
        "version",
    ):
        if fieldname in table_columns:
            frappe.db.sql_ddl(f"ALTER TABLE `tab{RECIPE_DOCTYPE}` DROP COLUMN `{fieldname}`")
