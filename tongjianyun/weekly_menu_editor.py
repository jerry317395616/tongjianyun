"""Calendar editing for the existing I-ONE Core meal planning week."""

from datetime import timedelta

import frappe
from frappe.database.query import Engine
from frappe.model.delete_doc import (
    check_if_doc_is_dynamically_linked,
    check_if_doc_is_linked,
    get_linked_docs,
    raise_link_exists_exception,
)
from frappe.query_builder.functions import Coalesce
from frappe.utils import cint, getdate, now_datetime
from ione_core import meal_planning as planning
from ione_core.meal_adjustments import get_effective_meals

from tongjianyun.dish_library import _preview_ingredients, _require, _visible
from tongjianyun.meal_portions import SOURCE, parse_portions, resolve
from tongjianyun.standard_recipes import CATEGORIES, DISH, DISH_CATEGORY, MARKER, PENDING, STATE

PAGE_SIZE = 15
UNCLASSIFIED = "未分类"


class MealMenuDraftPlan:
    """A managed draft meal may be empty until it is planned or marked as stopped."""

    def _get_missing_mandatory_fields(self):
        missing = super()._get_missing_mandatory_fields()
        if (self.docstatus == 0 and self.get("custom_is_meal_plan") and self.get("custom_meal_week")
                and planning._MANAGED.get()):
            return [entry for entry in missing if entry[0] != "po_items"]
        return missing


def _editable_week(name, *, lock=False):
    week = _visible("Meal Planning Week", name, lock=lock)
    planning._planner(week)
    if week.docstatus or week.material_request:
        frappe.throw("请在采购前的周计划草稿中调整餐次。")
    return week


def _meal(week, meal_date, meal_type):
    row = next((row for row in week.meals if str(row.meal_date) == meal_date and row.meal_type == meal_type), None)
    if not row:
        frappe.throw("未找到对应餐次，请刷新周计划。")
    return row


def _usable_recipe(bom, company):
    return bom.docstatus == 1 and bom.is_active and bom.quantity == 1 and bom.company == company


def _meal_lock(name):
    return frappe.cache.lock(f"meal-week:{name}", timeout=180, blocking_timeout=2)


def delete_draft_meal_plans(week, method=None):
    """Remove only the generated drafts owned by a week being deleted."""
    if week.docstatus != 0:
        return

    # Frappe already holds the week row lock. Never wait for an editor that
    # holds the meal lock and is about to acquire that row lock.
    lock = _meal_lock(week.name)
    if not lock.acquire(blocking=False):
        frappe.throw("周食谱正在编排或修改，请稍后重试删除。")

    def release_lock():
        if lock.owned():
            lock.release()

    frappe.db.after_commit.add(release_lock)
    frappe.db.after_rollback.add(release_lock)

    plan_type = "Production Plan"
    if week.material_request:
        frappe.throw("周食谱已关联采购申请，请先处理采购流程。")
    names = set(frappe.get_all(plan_type, filters={"custom_meal_week": week.name}, pluck="name"))
    meals = {row.production_plan: row for row in week.meals}
    if names != meals.keys() or len(meals) != len(week.meals):
        frappe.throw("周食谱的餐次和生产计划关联不完整，请先核对对应记录。")
    if not names:
        return

    plans = []
    for name in sorted(names):
        plan = frappe.get_doc(plan_type, name, for_update=True)
        meal = meals[name]
        if (not plan.get("custom_is_meal_plan") or plan.get("custom_meal_week") != week.name
                or plan.get("custom_meal_batch") != week.name or plan.company != week.company
                or str(plan.custom_meal_date) != str(meal.meal_date) or plan.custom_meal_type != meal.meal_type):
            frappe.throw(f"餐次生产计划 {name} 的归属不一致，请先核对对应记录。")
        if plan.docstatus != 0 or plan.get("custom_meal_adjustment") or plan.get("material_requests"):
            frappe.throw(f"餐次生产计划 {name} 已进入后续流程，请先处理关联业务。")
        plans.append(plan)

    for link in get_linked_docs(week):
        doctype, name = link["reference_doctype"], link["reference_docname"]
        if doctype != plan_type or name not in names:
            raise_link_exists_exception(week, doctype, name)
    check_if_doc_is_dynamically_linked(week)

    # Break just the backward links from this week's meal rows. Keep the
    # in-memory document intact for Frappe's deleted-document archive.
    frappe.db.set_value(week.meta.get_field("meals").options,
                        {"parent": week.name, "parenttype": week.doctype, "parentfield": "meals"},
                        "production_plan", None, update_modified=False)
    for plan in plans:
        check_if_doc_is_linked(plan)
        check_if_doc_is_dynamically_linked(plan)
    for plan in plans:
        frappe.delete_doc(plan_type, plan.name, ignore_permissions=True, ignore_missing=False)


@frappe.whitelist(methods=["GET"])
def calendar(week_name: str):
    week = _visible("Meal Planning Week", week_name)
    rows = get_effective_meals(week) if week.docstatus == 1 else week.meals
    return {
        "days": [str(day) for day in planning._dates(week)], "slots": list(planning.SLOTS), "categories": list(CATEGORIES),
        "initialized": bool(week.meals), "modified": str(week.modified),
        "meals": [dict(
            date=str(row.meal_date), slot=row.meal_type, menu=row.menu, headcount=row.planned_headcount,
            stopped=bool(row.get("service_suspended")), reason=row.get("suspension_reason"),
        ) for row in rows],
    }


def _copy_sources(week):
    start = getdate(week.week_start) - timedelta(days=7)
    week.template_week_start = start
    previous = frappe.get_list("Meal Planning Week", filters={"company": week.company, "week_start": start,
                                                               "docstatus": 1}, pluck="name", page_length=1)
    week.source_week = previous[0] if previous else None
    sources = {(getdate(day) - start, slot): name for day, slot, name in planning._source_plans(week)}
    expected = {(timedelta(days=index), slot) for index in range(5) for slot in planning.SLOTS}
    if set(sources) != expected:
        frappe.throw("上周的餐次日期或餐次类型不完整。")
    return sources


def _copy_menu(name, company):
    if not name:
        return frappe._dict(name=None, po_items=[]), 0
    source = _visible("Production Plan", name)
    if source.company != company:
        frappe.throw("来源餐次必须属于本园所。")
    rows = []
    for row in source.po_items:
        bom = _visible("BOM", row.bom_no)
        if bom.get(SOURCE):
            bom = _visible("BOM", bom.get(SOURCE))
            row = frappe._dict(row.as_dict())
            row.bom_no = bom.name
        item = _visible("Item", row.item_code)
        if _usable_recipe(bom, company) and not item.disabled and not item.is_purchase_item and bom.item == item.name:
            rows.append(row)
    return frappe._dict(name=source.name, po_items=rows), len(source.po_items) - len(rows)


@frappe.whitelist(methods=["POST"])
def initialize(week_name: str, copy_previous: int = 0):
    _editable_week(week_name)
    with _meal_lock(week_name):
        week = _editable_week(week_name, lock=True)
        if week.meals:
            return {"name": week.name, "skipped_recipes": 0}
        population = planning._population(week)
        days = planning._dates(week)
        if any(not cint(population[str(day)]["total"]) for day in days):
            frappe.throw("有供餐日的有效在园人数为 0，请先核对学期和教育名册。")
        sources = _copy_sources(week) if copy_previous else {}
        snapshot = {"dates": population, "recipe_hashes": {}}
        skipped = 0
        with planning._managed():
            for index, day in enumerate(days):
                count = cint(population[str(day)]["total"])
                for slot in planning.SLOTS:
                    source, omitted = _copy_menu(sources.get((timedelta(days=index), slot)), week.company)
                    plan = frappe.get_doc(planning._plan_values(week, source, day, slot, count))
                    suffix = planning._digest([week.name, str(day), slot])[:8].upper()
                    plan.insert(ignore_permissions=True, set_name=f"MEAL-{day:%Y%m%d}-{planning.SLOTS.index(slot) + 1:02}-{suffix}")
                    snapshot["recipe_hashes"][plan.name] = planning._recipe_signature(plan)
                    week.append("meals", dict(
                        meal_date=day, meal_type=slot, source_plan=source.name, production_plan=plan.name,
                        base_student_count=count, planned_headcount=count, menu=plan.custom_meal_menu,
                    ))
                    skipped += omitted
            week.population_snapshot = frappe.as_json(snapshot)
            week.population_as_of = now_datetime()
            week.population_basis = "教育有效在册名册；计划供餐人数，非当天实到"
            week.stock_reviewed = 0
            week.save()
        planning.share_linked_plans(week)
        return {"name": week.name, "skipped_recipes": skipped}


@frappe.whitelist(methods=["GET"])
def get_meal(week_name: str, meal_date: str, meal_type: str):
    week = _editable_week(week_name)
    row = _meal(week, meal_date, meal_type)
    plan = planning._bound_plan(week, row)
    plan.check_permission("read")
    codes = {line.item_code for line in plan.po_items}
    categories = {}
    if codes and frappe.has_permission("Item", "read"):
        categories = {item.name: item.get(DISH_CATEGORY) for item in frappe.get_list(
            "Item", filters={"name": ["in", sorted(codes)]}, fields=["name", DISH_CATEGORY], limit_page_length=0,
        )}
    return {
        "modified": str(week.modified), "base_headcount": row.base_student_count,
        "excluded_count": row.excluded_count, "adjustment_reason": row.adjustment_reason,
        "stopped": bool(row.service_suspended), "reason": row.suspension_reason,
        "dishes": [dict(
            bom=line.bom_no, item=line.item_code, name=line.custom_dish_name or line.item_code,
            category=categories.get(line.item_code),
        ) for line in plan.po_items],
    }


@frappe.whitelist(methods=["GET"])
def dishes(week_name: str, meal_type: str, search: str = "", category: str = "", start: int = 0,
           all_slots: int = 0):
    week = _editable_week(week_name)
    _require("BOM")
    if meal_type not in planning.SLOTS or (category and category not in (*CATEGORIES, UNCLASSIFIED)):
        frappe.throw("请选择有效的餐次和菜品分类。")
    item = frappe.qb.DocType("Item")
    filters = {DISH: 1, "disabled": 0, "is_purchase_item": 0, "has_variants": 0}
    if category in CATEGORIES:
        filters[DISH_CATEGORY] = category
    query = Engine().get_query(
        item, fields=["name", "item_name", DISH_CATEGORY, *planning.SLOT_FIELDS.values()], filters=filters,
        ignore_permissions=False, order_by="item_name asc, name asc",
    )
    if category == UNCLASSIFIED:
        query = query.where(Coalesce(getattr(item, DISH_CATEGORY), "") == "")
    if not all_slots:
        slot_field = planning.SLOT_FIELDS[meal_type]
        no_slots = Coalesce(getattr(item, slot_field), 0) == 0
        for field in planning.SLOT_FIELDS.values():
            no_slots &= Coalesce(getattr(item, field), 0) == 0
        query = query.where((getattr(item, slot_field) == 1) | no_slots)
    if term := search.strip()[:140]:
        term = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(item.name.like(term) | item.item_name.like(term))
    rows = query.offset(max(0, start)).limit(PAGE_SIZE + 1).run(as_dict=True)
    choices = rows[:PAGE_SIZE]
    by_item = {}
    if choices:
        for bom in frappe.get_list(
            "BOM", filters={MARKER: 1, "company": week.company, "item": ["in", [row.name for row in choices]],
                            "docstatus": ["<", 2]},
            fields=["name", "item", "docstatus", "is_active", "quantity", STATE],
            order_by="is_default desc, creation desc, name desc", limit_page_length=0,
        ):
            by_item.setdefault(bom.item, []).append(bom)
    result = []
    for row in choices:
        recipes = by_item.get(row.name, [])
        active = next((bom for bom in recipes if bom.docstatus == 1 and bom.is_active and bom.quantity == 1), None)
        status = "可选" if active else _unavailable_status(recipes)
        result.append(dict(
            item=row.name, name=row.item_name, category=row.get(DISH_CATEGORY),
            meal_slots=[slot for slot, field in planning.SLOT_FIELDS.items() if cint(row.get(field)) == 1],
            bom=active.name if active else None, status=status,
        ))
    return {"rows": result, "has_more": len(rows) > PAGE_SIZE, "page_size": PAGE_SIZE}


def _unavailable_status(recipes):
    if any(row.docstatus == 0 and row.get(STATE) == PENDING for row in recipes):
        return "配方待审核"
    if any(row.docstatus == 0 for row in recipes):
        return "配方待发布"
    return "暂无可用配方" if recipes else "待配置配方"


@frappe.whitelist(methods=["GET"])
def ingredients(week_name: str, bom_name: str):
    week = _visible("Meal Planning Week", week_name)
    bom = _visible("BOM", bom_name)
    if bom.company != week.company or bom.docstatus != 1 or bom.quantity != 1:
        frappe.throw("请选择本园所已发布的单份配方。")
    return _preview_ingredients(bom)


@frappe.whitelist(methods=["POST"])
def save_meal(week_name: str, meal_date: str, meal_type: str, modified: str, boms: str,
              excluded_count: int = 0, adjustment_reason: str = "", stopped: int = 0, reason: str = "",
              portions: str = ""):
    _editable_week(week_name)
    try:
        names = frappe.parse_json(boms)
    except ValueError:
        frappe.throw("菜品配方格式有误，请刷新后重试。")
    if (not isinstance(names, list) or len(names) > 20 or not all(isinstance(name, str) and name for name in names)
            or len(set(names)) != len(names)):
        frappe.throw("每餐最多选择 20 个不重复的菜品配方。")
    changes = parse_portions(portions)
    if changes.keys() - set(names):
        frappe.throw("只能调整本餐已选菜品的带量。")
    with _meal_lock(week_name):
        week = _editable_week(week_name, lock=True)
        if str(week.modified) != modified:
            frappe.throw("本周计划已由其他操作更新，请刷新后继续。")
        row = _meal(week, meal_date, meal_type)
        plan = planning._bound_plan(week, row)
        plan.check_permission("read")
        if plan.docstatus:
            frappe.throw("只能调整尚未提交的餐次。")
        count = cint(row.base_student_count) - excluded_count
        if excluded_count < 0 or count <= 0 or (excluded_count and not adjustment_reason.strip()):
            frappe.throw("停餐调整人数须小于在园人数，并填写调整原因。")
        if stopped and not reason.strip():
            frappe.throw("请填写整餐停供原因。")
        rows = _dish_rows(week, plan, names)
        for dish in rows:
            if dish.bom_no in changes:
                dish.bom_no = resolve(week, meal_date, meal_type, dish.bom_no, changes[dish.bom_no])
        values = planning._plan_values(week, frappe._dict(name=plan.custom_meal_source, po_items=rows),
                                       getdate(meal_date), meal_type, count)
        with planning._managed():
            plan.set("po_items", values["po_items"])
            plan.set("mr_items", [])
            plan.custom_meal_title = values["custom_meal_title"]
            plan.custom_meal_menu = values["custom_meal_menu"]
            plan.custom_meal_headcount = 0 if stopped else count
            plan.save(ignore_permissions=True)
            row.update(dict(menu=plan.custom_meal_menu, excluded_count=excluded_count,
                            planned_headcount=plan.custom_meal_headcount, adjustment_reason=adjustment_reason.strip(),
                            service_suspended=cint(bool(stopped)), suspension_reason=reason.strip() if stopped else None))
            snapshot = planning._json(week.population_snapshot)
            snapshot["recipe_hashes"][plan.name] = planning._recipe_signature(plan)
            week.population_snapshot = frappe.as_json(snapshot)
            week.stock_reviewed = 0
            week.procurement_snapshot = None
            week.requirement_weight_basis = "待确认"
            week.requirement_weight_snapshot = None
            week.revision = cint(week.revision) + 1
            week.save()
        return {"name": week.name, "modified": str(week.modified)}


def _dish_rows(week, plan, names):
    existing = {row.bom_no: row for row in plan.po_items}
    rows = []
    for name in names:
        bom = _visible("BOM", name)
        item = _visible("Item", bom.item)
        if (not _usable_recipe(bom, week.company) or item.disabled or item.is_purchase_item or item.has_variants
                or (name not in existing and not (item.get(DISH) and bom.get(MARKER)))):
            frappe.throw("请选择本园所启用的单份标准菜品配方。")
        if name in existing:
            rows.append(existing[name])
        else:
            rows.append(frappe._dict(item_code=item.name, bom_no=name, stock_uom=item.stock_uom,
                                     warehouse=None, description=item.item_name))
    return rows


def validate_menu_for_submission(doc, method=None):
    if doc._action != "submit":
        return
    for row in doc.meals:
        if not row.service_suspended and not planning._bound_plan(doc, row).po_items:
            frappe.throw(f"{row.meal_date} {row.meal_type}尚未编排，请选菜或确认整餐停供后再提交。")
