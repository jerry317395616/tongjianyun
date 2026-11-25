"""Controlled weekly meal planning using Education and native ERPNext documents."""
# ruff: noqa: RUF001

import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import cint, getdate, now_datetime

SLOTS = ("早餐", "早点", "午餐", "午点", "晚餐")
SLOT_FIELDS = dict(zip(SLOTS, (
	"custom_meal_slot_breakfast", "custom_meal_slot_morning_snack", "custom_meal_slot_lunch",
	"custom_meal_slot_afternoon_snack", "custom_meal_slot_dinner",
), strict=True))
COLORS = ("#e9b949", "#66b88a", "#5b8bd9", "#a887d5", "#e58b64")
_MANAGED = ContextVar("meal_planning_managed_update", default=False)
_HEADER = ("company", "week_start", "week_end", "raw_material_warehouse", "academic_year", "academic_term")
_PROTECTED = (
	"population_snapshot",
	"population_as_of",
	"population_basis",
	"revision",
	"source_week",
	"material_request",
	"procurement_snapshot",
	"stock_reviewed",
	"kitchen_warehouse",
	"kitchen_reconciled",
	"kitchen_reconciled_at",
	"kitchen_reconciliation_snapshot",
	"requirement_weight_basis",
	"requirement_weight_snapshot",
)


@contextmanager
def _managed():
	token = _MANAGED.set(True)
	try:
		yield
	finally:
		_MANAGED.reset(token)


def _login():
	if frappe.session.user == "Guest":
		frappe.throw(_("请先登录。"), frappe.AuthenticationError)


def _week(name, ptype="read"):
	_login()
	doc = frappe.get_doc("Meal Planning Week", name)
	doc.check_permission(ptype)
	return doc


def _planner(doc):
	doc.check_permission("write")
	roles = set(frappe.get_roles())
	if frappe.session.user != "Administrator" and not roles.intersection(
		{"System Manager", "食谱编排员", "食谱审核员"}
	):
		frappe.throw(_("需要食谱编排权限。"), frappe.PermissionError)


def _monday(value):
	day = getdate(value)
	if day.weekday() != 0:
		frappe.throw(_("周开始日期必须是星期一。"))
	return day


def _json(value):
	return json.loads(value) if isinstance(value, str) and value else (value or {})


def _digest(value):
	return hashlib.sha256(
		json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
	).hexdigest()


def _dates(doc):
	start = _monday(doc.week_start)
	return [start + timedelta(days=i) for i in range(5)]


def _population(doc):
	from tongjianyun.meal_population import get_population_snapshot

	dates = _dates(doc)
	serving = set(doc.meal_service_dates()) if hasattr(doc, "meal_service_dates") else set(dates)
	return {
		str(day): (get_population_snapshot(doc.company, day, doc.academic_year, doc.academic_term)
		           if day in serving else {"total": 0, "classes": [], "roster_hash": _digest([doc.company, str(day), "停供"]),
		                                   "basis": "学期供餐日历停供"})
		for day in dates
	}


def _validate_warehouse(doc):
	if not doc.raw_material_warehouse:
		frappe.throw(_("请选择原料仓库。"))
	warehouse = frappe.get_doc("Warehouse", doc.raw_material_warehouse)
	if warehouse.company != doc.company or warehouse.is_group or warehouse.disabled:
		frappe.throw(_("原料仓库必须属于本园所，且为启用的实际仓库。"))


def _recipe_signature(plan):
	recipes = []
	for row in plan.po_items:
		bom = frappe.get_doc("BOM", row.bom_no)
		if (
			bom.docstatus != 1
			or not bom.is_active
			or bom.item != row.item_code
			or Decimal(str(bom.quantity)) != 1
		):
			frappe.throw(_("菜品配方必须是已提交、启用且以1名幼儿为基准的配方：{0}").format(row.bom_no))
		if bom.company and bom.company != plan.company:
			frappe.throw(_("菜品配方所属园所不一致。"))
		recipes.append(
			{
				"item": bom.item,
				"bom": bom.name,
				"quantity": str(bom.quantity),
				"uom": bom.uom,
				"ingredients": [
					{
						"item": x.item_code,
						"qty": str(x.qty),
						"uom": x.uom,
						"conversion_factor": str(x.conversion_factor),
					}
					for x in bom.items
				],
			}
		)
	return _digest(recipes)


def _title(doc):
	return f"{getdate(doc.week_start):%Y年%m月%d日}—{getdate(doc.week_end):%m月%d日}周食谱"


def validate_week(doc):
	old = doc.get_doc_before_save()
	if old and doc.owner != old.owner:
		frappe.throw(_("周食谱经办人不能更换；请保留原创建人和审核记录。"), frappe.PermissionError)
	if not _MANAGED.get() and doc.is_new() and doc.get("amended_from"):
		source = _week(doc.amended_from, "amend")
		if source.docstatus != 2:
			frappe.throw(_("只有已取消的周计划可以建立修订版本。"))
		for key in ("company", "week_start", "raw_material_warehouse", "academic_year", "academic_term"):
			doc.set(key, source.get(key))
		doc.source_week = source.name
		doc.template_week_start = source.week_start
		doc.revision = cint(source.revision) + 1
		doc.set("meals", [])
		for key in (
			"population_snapshot",
			"population_as_of",
			"population_basis",
			"material_request",
			"procurement_snapshot",
		):
			doc.set(key, None)
		doc.stock_reviewed = 0
		doc.kitchen_reconciled = 0
		doc.kitchen_reconciled_at = None
		doc.kitchen_reconciliation_snapshot = None
		doc.requirement_weight_basis = "待确认"
		doc.requirement_weight_snapshot = None
		with _managed():
			validate_week(doc)
		return
	start = _monday(doc.week_start)
	doc.week_end = start + timedelta(days=4)
	doc.title = _title(doc)
	doc.revision = cint(doc.revision) or 1
	doc.active_week_key = _digest([doc.company, str(start)]) if doc.docstatus != 2 else None
	_validate_warehouse(doc)
	if doc.docstatus != 2 and frappe.db.exists(
		"Meal Planning Week",
		{"company": doc.company, "week_start": start, "docstatus": ["<", 2], "name": ["!=", doc.name or ""]},
	):
		frappe.throw(_("该园所本周已有有效周计划，请打开已有记录或先完成修订。"))
	if not _MANAGED.get():
		if old and old.meals:
			if not doc.meals:
				frappe.throw(_("已编排周计划不能清空餐次；请调整已有餐次或修订整周。"))
			for key in _HEADER + _PROTECTED:
				if str(doc.get(key) or "") != str(old.get(key) or ""):
					frappe.throw(_("已编排周计划的园所、日期、人数依据和采购关联只能通过专用操作调整。"))
		elif doc.meals:
			frappe.throw(_("请先保存空周计划，再使用“从上一周编排”。"))
		elif any(
			doc.get(key)
			for key in (
				"population_snapshot",
				"population_as_of",
				"population_basis",
				"source_week",
				"material_request",
				"procurement_snapshot",
				"stock_reviewed",
				"kitchen_reconciled",
				"kitchen_reconciled_at",
				"kitchen_reconciliation_snapshot",
				"requirement_weight_snapshot",
			)
		):
			frappe.throw(_("人数来源、库存核对和采购关联须通过专用操作生成。"))
	if not doc.meals:
		doc.status = "待编排"
		return
	expected = {(str(day), slot) for day in _dates(doc) for slot in SLOTS}
	actual = [(str(getdate(row.meal_date)), row.meal_type) for row in doc.meals]
	if len(actual) != 25 or set(actual) != expected:
		frappe.throw(_("一周必须包含五天、每天五个餐次，不能重复或遗漏。"))
	old_rows = {(str(getdate(r.meal_date)), r.meal_type): r for r in old.meals} if old else {}
	counts_changed = False
	for row in doc.meals:
		key = (str(getdate(row.meal_date)), row.meal_type)
		previous = old_rows.get(key)
		if not _MANAGED.get() and previous:
			for field in (
				"source_plan",
				"production_plan",
				"base_student_count",
				"planned_headcount",
				"menu",
			):
				if str(row.get(field) or "") != str(previous.get(field) or ""):
					frappe.throw(_("餐次来源及人数基线由系统维护，请使用刷新人数或调整菜品操作。"))
		raw = str(row.excluded_count or 0)
		try:
			excluded = Decimal(raw)
		except Exception:
			frappe.throw(_("停餐调整人数必须是非负整数。"))
		if (
			not excluded.is_finite()
			or excluded != excluded.to_integral_value()
			or excluded < 0
			or (excluded >= cint(row.base_student_count)
				    and not (row.get("service_suspended") and excluded == 0 and cint(row.base_student_count) == 0))
		):
			frappe.throw(_("停餐调整人数必须是非负整数，且小于在册人数。"))
		if excluded and not str(row.adjustment_reason or "").strip():
			frappe.throw(_("调整供餐人数时请填写停餐原因。"))
		row.excluded_count = int(excluded)
		if row.get("service_suspended") and not str(row.get("suspension_reason") or "").strip():
			frappe.throw(_("整餐停供时请填写停供原因。"))
		row.planned_headcount = (
			0 if row.get("service_suspended") else cint(row.base_student_count) - int(excluded)
		)
		if previous and row.planned_headcount != previous.planned_headcount:
			counts_changed = True
	if counts_changed and not _MANAGED.get():
		if doc.docstatus != 0 or doc.material_request:
			frappe.throw(_("已审核或已产生采购申请的周计划需要修订后再调整人数。"))
		doc.stock_reviewed = 0
		doc.procurement_snapshot = None
		doc.revision = cint(doc.revision) + 1
		with _managed():
			for row in doc.meals:
				plan = _bound_plan(doc, row)
				if plan.docstatus:
					frappe.throw(_("请先修订已经提交的生产计划。"))
				for dish in plan.po_items:
					if row.planned_headcount:
						dish.planned_qty = row.planned_headcount
				plan.set("mr_items", [])
				plan.custom_meal_headcount = row.planned_headcount
				plan.save(ignore_permissions=True)
	doc.status = (
		"已取消"
		if doc.docstatus == 2
		else (
			"已核销"
			if doc.get("kitchen_reconciled")
			else (
				"采购申请已生成" if doc.material_request else ("已审核" if doc.docstatus == 1 else "编排草稿")
			)
		)
	)


def _bound_plan(doc, row):
	plan = frappe.get_doc("Production Plan", row.production_plan)
	if (
		plan.company != doc.company
		or plan.custom_meal_week != doc.name
		or getdate(plan.custom_meal_date) != getdate(row.meal_date)
		or plan.custom_meal_type != row.meal_type
	):
		frappe.throw(_("餐次生产计划关联不一致。"))
	return plan


def _source_plans(doc):
	if doc.source_week:
		source = _week(doc.source_week)
		if source.company != doc.company or len(source.meals) != 25:
			frappe.throw(_("来源周计划的园所或餐次不完整。"))
		from tongjianyun.meal_adjustments import get_effective_meals

		return [(r.meal_date, r.meal_type, r.production_plan) for r in get_effective_meals(source)]
	start = _monday(doc.template_week_start)
	rows = frappe.get_list(
		"Production Plan",
		filters={
			"company": doc.company,
			"custom_is_meal_plan": 1,
			"docstatus": ["<", 2],
			"custom_meal_date": ["between", [start, start + timedelta(days=4)]],
		},
		fields=["name", "custom_meal_date", "custom_meal_type"],
		limit_page_length=0,
	)
	if len(rows) != 25 or len({(str(r.custom_meal_date), r.custom_meal_type) for r in rows}) != 25:
		frappe.throw(_("来源周必须恰好有25张可读取的餐次计划。"))
	return [(r.custom_meal_date, r.custom_meal_type, r.name) for r in rows]


def _plan_values(doc, source, day, slot, headcount):
	index = SLOTS.index(slot)
	menu = "、".join(
		frappe.db.get_value("Item", r.item_code, "item_name") or r.item_code for r in source.po_items
	)
	values = {
		"doctype": "Production Plan",
		"company": doc.company,
		"posting_date": day,
		"get_items_from": "",
		"for_warehouse": doc.raw_material_warehouse,
		"combine_items": 0,
		"combine_sub_items": 0,
		"reserve_stock": 0,
		"ignore_existing_ordered_qty": 0,
		"custom_is_meal_plan": 1,
		"custom_meal_week": doc.name,
		"custom_meal_headcount": headcount,
		"custom_meal_date": day,
		"custom_meal_end_date": day,
		"custom_meal_type": slot,
		"custom_meal_title": f"{index + 1:02} {slot}｜{menu}"[:140],
		"custom_meal_menu": menu,
		"custom_meal_batch": doc.name,
		"custom_meal_color": COLORS[index],
		"custom_meal_source": source.name,
		"custom_meal_notice": "按教育在册名册确认的计划供餐人数；非当天实到记录。",
		"po_items": [
			{
				"item_code": r.item_code,
				"bom_no": r.bom_no,
				"planned_qty": headcount,
				"stock_uom": r.stock_uom,
				"planned_start_date": f"{day} 00:00:00",
				"warehouse": r.warehouse,
				"custom_dish_name": frappe.db.get_value("Item", r.item_code, "item_name"),
				"description": r.description,
			}
			for r in source.po_items
		],
	}
	return values


def share_linked_plans(doc):
	"""Mirror explicit week readers to its own new plans, without global grants."""
	users = {doc.owner, frappe.session.user}
	users.update(
		frappe.get_all(
			"DocShare",
			filters={"share_doctype": "Meal Planning Week", "share_name": doc.name, "read": 1},
			pluck="user",
		)
	)
	for user in users - {None, "", "Guest", "Administrator"}:
		constrained = frappe.db.exists("User Permission", {"user": user, "allow": "Production Plan"})
		for row in doc.meals:
			frappe.share.add(
				"Production Plan",
				row.production_plan,
				user,
				read=1,
				write=0,
				submit=0,
				share=0,
				notify=0,
				flags={"ignore_share_permission": True},
			)
			if constrained and not frappe.db.exists(
				"User Permission",
				{"user": user, "allow": "Production Plan", "for_value": row.production_plan},
			):
				frappe.get_doc(
					{
						"doctype": "User Permission",
						"user": user,
						"allow": "Production Plan",
						"for_value": row.production_plan,
						"applicable_for": "Production Plan",
						"apply_to_all_doctypes": 0,
					}
				).insert(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def initialize_week(name):
	doc = _week(name, "write")
	_planner(doc)
	if doc.docstatus:
		frappe.throw(_("只能初始化草稿周计划。"))
	with frappe.cache.lock(f"meal-week:{name}", timeout=180, blocking_timeout=2):
		doc.reload()
		if doc.meals:
			return {"name": doc.name, "already_initialized": True}
		population = _population(doc)
		sources = _source_plans(doc)
		source_start = min(getdate(day) for day, _slot, _name in sources)
		source_keys = {(getdate(day) - source_start, slot) for day, slot, _name in sources}
		if source_keys != {(timedelta(days=i), slot) for i in range(5) for slot in SLOTS}:
			frappe.throw(_("来源餐次日期不完整。"))
		snapshot = {"dates": population, "recipe_hashes": {}}
		with _managed():
			for source_day, slot, source_name in sorted(
				sources, key=lambda x: (getdate(x[0]), SLOTS.index(x[1]))
			):
				day = getdate(doc.week_start) + (getdate(source_day) - source_start)
				source = frappe.get_doc("Production Plan", source_name)
				source.check_permission("read")
				count = cint(population[str(day)]["total"])
				suspended = population[str(day)].get("basis") == "学期供餐日历停供"
				if not count and not suspended:
					frappe.throw(_("有效在册人数为0，不能生成供餐计划。"))
				if suspended:
					source = frappe._dict(name=None, po_items=[])
				plan = frappe.get_doc(_plan_values(doc, source, day, slot, count))
				suffix = _digest([doc.name, str(day), slot])[:8].upper()
				plan.insert(
					ignore_permissions=True, set_name=f"MEAL-{day:%Y%m%d}-{SLOTS.index(slot) + 1:02}-{suffix}"
				)
				recipe_hash = _recipe_signature(plan)
				snapshot["recipe_hashes"][plan.name] = recipe_hash
				doc.append(
					"meals",
					{
						"meal_date": day,
						"meal_type": slot,
						"source_plan": source.name,
						"service_suspended": int(suspended),
						"suspension_reason": "学期供餐日历停供" if suspended else None,
						"production_plan": plan.name,
						"base_student_count": count,
						"excluded_count": 0,
						"planned_headcount": count,
						"menu": plan.custom_meal_menu,
					},
				)
			doc.population_snapshot = frappe.as_json(snapshot)
			doc.population_as_of = now_datetime()
			doc.population_basis = "教育有效在册名册；计划供餐人数，非当天实到"
			doc.stock_reviewed = 0
			doc.save(ignore_permissions=True)
		share_linked_plans(doc)
		return {
			"name": doc.name,
			"meals": len(doc.meals),
			"headcount": population[str(getdate(doc.week_start))]["total"],
		}


@frappe.whitelist(methods=["POST"])
def refresh_population(name):
	doc = _week(name, "write")
	_planner(doc)
	if doc.docstatus or doc.material_request or not doc.meals:
		frappe.throw(_("只有尚未采购的已编排草稿可以刷新人数。"))
	population = _population(doc)
	snapshot = _json(doc.population_snapshot)
	with _managed():
		for row in doc.meals:
			row.base_student_count = population[str(getdate(row.meal_date))]["total"]
			row.planned_headcount = (
				0 if row.get("service_suspended") else cint(row.base_student_count) - cint(row.excluded_count)
			)
			if row.planned_headcount <= 0 and not row.get("service_suspended"):
				frappe.throw(_("停餐调整人数已超过刷新后的在册人数。"))
			plan = _bound_plan(doc, row)
			if plan.docstatus:
				frappe.throw(_("已有餐次计划提交，请先修订。"))
			for dish in plan.po_items:
				if row.planned_headcount:
					dish.planned_qty = row.planned_headcount
			plan.custom_meal_headcount = row.planned_headcount
			plan.set("mr_items", [])
			plan.save(ignore_permissions=True)
		snapshot["dates"] = population
		doc.population_snapshot = frappe.as_json(snapshot)
		doc.population_as_of = now_datetime()
		doc.revision = cint(doc.revision) + 1
		doc.stock_reviewed = 0
		doc.procurement_snapshot = None
		doc.save(ignore_permissions=True)
	return {"name": doc.name}


@frappe.whitelist(methods=["POST"])
def copy_next_week(name, target_week_start=None):
	source = _week(name)
	if not frappe.has_permission("Meal Planning Week", "create"):
		frappe.throw(_("没有新建周计划权限。"), frappe.PermissionError)
	start = _monday(target_week_start or (getdate(source.week_start) + timedelta(days=7)))
	if start == getdate(source.week_start):
		frappe.throw(_("复制的目标周必须与来源周不同。"))
	existing = frappe.get_list(
		"Meal Planning Week",
		filters={"company": source.company, "week_start": start, "docstatus": ["<", 2]},
		pluck="name",
		limit_page_length=2,
	)
	if existing:
		frappe.throw(_("该周已有计划：{0}").format(existing[0]))
	with _managed():
		doc = frappe.get_doc(
			{
				"doctype": "Meal Planning Week",
				"company": source.company,
				"week_start": start,
				"source_week": source.name,
				"template_week_start": source.week_start,
				"raw_material_warehouse": source.raw_material_warehouse,
				"kitchen_warehouse": source.get("kitchen_warehouse"),
				"academic_year": source.academic_year,
				"academic_term": source.academic_term,
				"revision": 1,
			}
		).insert()
	initialize_week(doc.name)
	return {"name": doc.name}


@frappe.whitelist(methods=["GET", "POST"])
def search_meal_recipes(doctype, txt, searchfield, start, page_len, filters):
	"""Find executable recipes in the selected week, with optional meal suggestions."""
	from frappe.database.query import Engine
	from frappe.query_builder.functions import Coalesce

	filters = _json(filters)
	if doctype != "BOM" or not isinstance(filters, dict) or filters.get("meal_type") not in SLOTS:
		return []
	week_name = filters.get("week_name")
	if not isinstance(week_name, str) or not week_name:
		return []
	week = _week(week_name)
	_planner(week)
	item = frappe.qb.DocType("Item")
	bom = frappe.qb.DocType("BOM")
	items = Engine().get_query(
		"Item", fields=["name"], filters={"disabled": 0, "is_purchase_item": 0}, ignore_permissions=False,
	)
	slot = SLOT_FIELDS[filters["meal_type"]]
	if not cint(filters.get("include_all")) and all(frappe.db.has_column("Item", field) for field in SLOT_FIELDS.values()):
		unassigned = None
		for field in SLOT_FIELDS.values():
			empty = Coalesce(getattr(item, field), 0) == 0
			unassigned = empty if unassigned is None else unassigned & empty
		items = items.where((getattr(item, slot) == 1) | unassigned)
	query = Engine().get_query(
		"BOM", fields=["name", "item"],
		filters={"docstatus": 1, "is_active": 1, "quantity": 1, "company": week.company},
		ignore_permissions=False, order_by="item_name asc, name asc",
	).where(bom.item.isin(items))
	search = str(txt or "").strip()[:140]
	if search:
		term = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
		by_name = frappe.qb.from_(item).select(item.name).where(item.item_name.like(term) | item.name.like(term))
		query = query.where(bom.name.like(term) | bom.item.isin(by_name))
	rows = query.limit(max(1, min(cint(page_len), 50))).offset(max(0, cint(start))).run(as_dict=True)
	if not rows:
		return []
	names = frappe.get_list("Item", filters={"name": ["in", sorted({row.item for row in rows})]},
		fields=["name", "item_name"], limit_page_length=0)
	labels = {row.name: row.item_name for row in names}
	return [(row.name, labels.get(row.item) or row.item) for row in rows]


@frappe.whitelist(methods=["POST"])
def update_meal_dishes(week_name, meal_date, meal_type, boms):
	doc = _week(week_name, "write")
	_planner(doc)
	if doc.docstatus or doc.material_request:
		frappe.throw(_("请在草稿阶段调整菜品。"))
	boms = json.loads(boms) if isinstance(boms, str) else boms
	if not isinstance(boms, list) or not boms or len(boms) > 20 or len(set(boms)) != len(boms):
		frappe.throw(_("请选择1到20个不重复的菜品配方。"))
	row = next(
		(r for r in doc.meals if getdate(r.meal_date) == getdate(meal_date) and r.meal_type == meal_type),
		None,
	)
	if not row:
		frappe.throw(_("未找到对应餐次。"))
	plan = _bound_plan(doc, row)
	target_warehouse = plan.po_items[0].warehouse
	items = []
	for name in boms:
		bom = frappe.get_doc("BOM", name)
		bom.check_permission("read")
		item = frappe.get_doc("Item", bom.item)
		if item.is_purchase_item or item.disabled:
			frappe.throw(_("请选择启用的自制菜品配方。"))
		items.append(
			{
				"item_code": bom.item,
				"bom_no": name,
				"planned_qty": row.planned_headcount,
				"stock_uom": item.stock_uom,
				"planned_start_date": f"{getdate(row.meal_date)} 00:00:00",
				"warehouse": target_warehouse,
				"custom_dish_name": item.item_name,
				"description": item.item_name,
			}
		)
	with _managed():
		plan.set("po_items", items)
		plan.set("mr_items", [])
		plan.custom_meal_menu = "、".join(i["custom_dish_name"] for i in items)
		plan.custom_meal_title = (
			f"{SLOTS.index(row.meal_type) + 1:02} {row.meal_type}｜{plan.custom_meal_menu}"[:140]
		)
		_recipe_signature(plan)
		plan.save(ignore_permissions=True)
		row.menu = plan.custom_meal_menu
		snapshot = _json(doc.population_snapshot)
		snapshot["recipe_hashes"][plan.name] = _recipe_signature(plan)
		doc.population_snapshot = frappe.as_json(snapshot)
		doc.stock_reviewed = 0
		doc.procurement_snapshot = None
		doc.requirement_weight_basis = "待确认"
		doc.requirement_weight_snapshot = None
		doc.revision = cint(doc.revision) + 1
		doc.save(ignore_permissions=True)
	return {"name": doc.name}


@frappe.whitelist(methods=["POST"])
def confirm_stock_review(name):
	doc = _week(name)
	if frappe.session.user != "Administrator" and not {
		"System Manager",
		"Purchase Manager",
		"Stock Manager",
	}.intersection(frappe.get_roles()):
		frappe.throw(_("需要库管或采购审核权限。"), frappe.PermissionError)
	if doc.docstatus != 0 or not doc.meals:
		frappe.throw(_("请在周计划提交前核对账面库存。"))
	from tongjianyun.meal_procurement import get_procurement_preview

	preview = get_procurement_preview(doc.name)
	if preview.get("blockers"):
		frappe.throw(_("请先处理采购需求预览中的阻断项。"))
	with _managed():
		doc.stock_reviewed = 1
		doc.procurement_snapshot = frappe.as_json(
			{"reviewed_basis_hash": preview["basis_hash"], "reviewed_at": str(now_datetime())}
		)
		doc.save(ignore_permissions=True)
	return {"name": doc.name, "basis": "账面库存核对，未声明完成实物盘点"}


def submit_week(doc):
	from tongjianyun.meal_stock_claims import lock_claim_scope

	lock_claim_scope(doc.company)
	original_owner = frappe.db.get_value("Meal Planning Week", doc.name, "owner", for_update=True)
	if not original_owner or doc.owner != original_owner:
		frappe.throw(_("周食谱经办人与原始创建记录不一致，不能审核。"), frappe.PermissionError)
	if original_owner == frappe.session.user:
		frappe.throw(_("周食谱经办人与审核人必须不同，请由另一名授权审核人员提交。"), frappe.PermissionError)
	if not doc.meals or not doc.stock_reviewed:
		frappe.throw(_("请先完整编排25餐并核对采购需求与账面库存。"))
	verify_purchase_weight_basis(doc)
	current = _population(doc)
	snapshot = _json(doc.population_snapshot)
	for day, population in current.items():
		if (
			population["roster_hash"] != snapshot["dates"][day]["roster_hash"]
			or population["total"] != snapshot["dates"][day]["total"]
		):
			frappe.throw(_("教育名册已变化，请先刷新人数并重新核对采购需求。"))
	for row in doc.meals:
		plan = _bound_plan(doc, row)
		if row.get("service_suspended"):
			if row.planned_headcount or plan.docstatus:
				frappe.throw(_("停供餐次应为零人数，并保留未提交的配方草稿。"))
			continue
		if plan.docstatus or any(Decimal(str(x.planned_qty)) != row.planned_headcount for x in plan.po_items):
			frappe.throw(_("餐次草稿数量或状态不一致，请重新核对。"))
		if _recipe_signature(plan) != snapshot["recipe_hashes"].get(plan.name):
			frappe.throw(_("菜品配方已变化，请重新确认配方。"))
	from tongjianyun.meal_procurement import prepare_procurement_rows

	prepared = prepare_procurement_rows(doc)
	if prepared.get("blockers"):
		frappe.throw(_("采购需求仍有待处理项：{0}").format("；".join(map(str, prepared["blockers"]))))
	review = _json(doc.procurement_snapshot)
	if review.get("reviewed_basis_hash") != prepared["snapshot"].get("basis_hash"):
		frappe.throw(_("库存、到货或采购需求已变化，请重新核对账面库存后再提交。"))
	from tongjianyun.meal_native_reservations import ensure_current_native_reservation_inputs

	ensure_current_native_reservation_inputs(doc.company)
	with _managed():
		for row in doc.meals:
			if row.get("service_suspended"):
				continue
			plan = _bound_plan(doc, row)
			plan.set("mr_items", prepared["plans"].get(plan.name, []))
			plan.save(ignore_permissions=True)
			plan.flags.ignore_permissions = True
			plan.submit()
		doc.procurement_snapshot = frappe.as_json(
			{**prepared["snapshot"], "reviewed_at": review.get("reviewed_at")}
		)
		doc.status = "已审核"


def verify_purchase_weight_basis(week, material_requests=None):
	from tongjianyun.meal_weights import verify_purchase_weight_basis as verify

	return verify(week, material_requests)


def cancel_week(doc):
	if (
		doc.get("kitchen_reconciled")
		or frappe.db.exists("Meal Plan Adjustment", {"meal_week": doc.name, "docstatus": 1})
		or frappe.db.exists("Stock Entry", {"custom_meal_week": doc.name, "docstatus": 1})
		or frappe.db.exists("Meal Kitchen Day", {"meal_week": doc.name, "docstatus": 1})
	):
		frappe.throw(_("本周已有厨房执行或已审核单餐变更，请保留业务事实并使用专用调整流程。"))
	if (
		doc.material_request
		and frappe.db.get_value("Material Request", doc.material_request, "docstatus") != 2
	):
		frappe.throw(_("请先处理关联采购申请及其后续订单，再取消本周。"))
	with _managed():
		for row in doc.meals:
			plan = _bound_plan(doc, row)
			if plan.docstatus == 1:
				plan.flags.ignore_permissions = True
				plan.cancel()
	doc.db_set("active_week_key", None, update_modified=False)


def validate_production_plan(doc, method=None):
	if _MANAGED.get():
		return
	old = doc.get_doc_before_save()
	if not doc.get("custom_meal_week") and not (old and old.get("custom_meal_week")):
		return
	if not old:
		frappe.throw(_("请从食谱周计划生成餐次。"))
	if doc.docstatus != old.docstatus:
		frappe.throw(_("请通过食谱周计划统一审核或取消餐次。"))

	def signature(plan):
		return {
			"fields": {
				k: str(plan.get(k) or "")
				for k in (
					"company",
					"custom_meal_week",
					"custom_meal_date",
					"custom_meal_type",
					"custom_meal_headcount",
					"for_warehouse",
				)
			},
			"dishes": [
				{k: str(r.get(k) or "") for k in ("item_code", "bom_no", "planned_qty", "warehouse")}
				for r in plan.po_items
			],
			"materials": [
				{
					k: str(r.get(k) or "")
					for k in (
						"item_code",
						"quantity",
						"required_bom_qty",
						"warehouse",
						"schedule_date",
						"uom",
					)
				}
				for r in plan.mr_items
			],
		}

	if signature(doc) != signature(old):
		frappe.throw(_("此餐次受周计划管理，请从周计划调整人数、菜品或采购需求。"))


def _report_week(filters):
	filters = frappe._dict(filters or {})
	name = filters.get("week_name")
	if not name:
		names = frappe.get_list(
			"Meal Planning Week",
			filters={"docstatus": ["<", 2]},
			pluck="name",
			order_by="week_start desc, modified desc",
			limit_page_length=1,
		)
		if not names:
			return None
		name = names[0]
	return _week(name)


def _details(doc):
	data = []
	from tongjianyun.meal_adjustments import get_effective_meals

	for meal in sorted(
		get_effective_meals(doc), key=lambda x: (getdate(x.meal_date), SLOTS.index(x.meal_type))
	):
		if meal.get("service_suspended") or not meal.planned_headcount:
			continue
		plan = _bound_plan(doc, meal)
		if doc.docstatus == 1 and _recipe_signature(plan) != meal.get("recipe_hash"):
			frappe.throw(_("已审核菜品配方发生变化，请先修订周计划。"))
		for dish in plan.po_items:
			bom = frappe.get_doc("BOM", dish.bom_no)
			for ingredient in bom.items:
				per_child = Decimal(str(ingredient.qty)) / Decimal(str(bom.quantity))
				data.append(
					{
						"week_name": doc.name,
						"meal_date": str(getdate(meal.meal_date)),
						"meal_type": meal.meal_type,
						"dish_name": frappe.db.get_value("Item", dish.item_code, "item_name"),
						"ingredient_code": ingredient.item_code,
						"ingredient_name": frappe.db.get_value("Item", ingredient.item_code, "item_name"),
						"per_child_qty": float(per_child),
						"uom": ingredient.uom,
						"headcount": meal.planned_headcount,
						"total_qty": float(per_child * meal.planned_headcount),
						"plan_name": plan.name,
						"bom_no": bom.name,
					}
				)
	return data


def ingredient_report_data(filters=None):
	from tongjianyun.meal_plan_reports import report_context, resolve_report_filters

	filters = resolve_report_filters(filters)
	historical = report_context(filters)
	doc = None if historical else _report_week(filters)
	columns = [
		{"fieldname": f, "label": label, "fieldtype": kind, "width": width, **extra}
		for f, label, kind, width, extra in [
			("meal_date", "供餐日期", "Date", 120, {}),
			("meal_type", "餐次", "Data", 75, {}),
			("dish_name", "菜品", "Data", 150, {}),
			("ingredient_name", "食材", "Data", 140, {}),
			("per_child_qty", "人均带量", "Float", 105, {"precision": 6}),
			("uom", "单位", "Data", 75, {}),
			("headcount", "计划供餐人数", "Int", 120, {}),
			("total_qty", "备料总量", "Float", 115, {"precision": 6}),
			("plan_name", "餐次计划", "Link", 230, {"options": "Production Plan"}),
			("bom_no", "菜品配方", "Link", 230, {"options": "BOM"}),
		]
	]
	return columns, historical["details"] if historical else (_details(doc) if doc else [])


def weekly_report_data(filters=None):
	from tongjianyun.meal_plan_reports import report_context, resolve_report_filters

	filters = resolve_report_filters(filters)
	historical = report_context(filters)
	doc = None if historical else _report_week(filters)
	columns = [
		{"fieldname": "meal_type", "label": "餐次", "fieldtype": "Data", "width": 80},
		{"fieldname": "row_kind", "label": "内容", "fieldtype": "Data", "width": 80},
	]
	columns += [
		{"fieldname": f"day_{i}", "label": f"星期{'一二三四五'[i]}", "fieldtype": "Data", "width": 230}
		for i in range(5)
	]
	if historical:
		for i, day in enumerate(historical["dates"]):
			columns[i + 2]["label"] = f"星期{'一二三四五'[i]} {day}"
		return columns, historical["rows"]
	if not doc:
		return columns, []
	for i, day in enumerate(_dates(doc)):
		columns[i + 2]["label"] = f"星期{'一二三四五'[i]} {day}"
	details = _details(doc)
	from tongjianyun.meal_adjustments import get_effective_meals

	meals = get_effective_meals(doc)
	data = []
	for slot in SLOTS:
		for kind in ("菜品", "带量"):
			record = {"week_name": doc.name, "meal_type": slot, "row_kind": kind}
			for i, day in enumerate(_dates(doc)):
				meal = next(r for r in meals if getdate(r.meal_date) == day and r.meal_type == slot)
				record[f"plan_{i}"] = None if meal.get("service_suspended") else meal.production_plan
				record[f"headcount_{i}"] = meal.planned_headcount
				record[f"date_{i}"] = str(day)
				record[f"suspended_{i}"] = cint(meal.get("service_suspended"))
				record[f"suspension_reason_{i}"] = meal.get("suspension_reason")
				if meal.get("service_suspended"):
					record[f"day_{i}"] = (
						f"停供：{meal.get('suspension_reason') or ''}" if kind == "菜品" else ""
					)
					continue
				if kind == "菜品":
					record[f"day_{i}"] = meal.menu
				else:
					quantities = {}
					for row in details:
						if row["meal_date"] == str(day) and row["meal_type"] == slot:
							key = (row["ingredient_code"], row["ingredient_name"], row["uom"])
							quantities[key] = quantities.get(key, Decimal(0)) + Decimal(
								str(row["per_child_qty"])
							)
					record[f"day_{i}"] = "；".join(
						f"{name}{qty.normalize():f}{uom}" for (_code, name, uom), qty in quantities.items()
					)
			data.append(record)
	return columns, data


@frappe.whitelist()
def get_meal_ingredients(plan_name):
	_login()
	plan = frappe.get_doc("Production Plan", plan_name)
	plan.check_permission("read")
	if not plan.get("custom_meal_week"):
		from tongjianyun.meal_plan_reports import plan_details

		quantities = {}
		for row in plan_details(plan):
			key = (row["ingredient_code"], row["ingredient_name"], row["uom"])
			quantities[key] = quantities.get(key, Decimal(0)) + Decimal(str(row["per_child_qty"]))
		return {
			"rows": [
				{"ingredient_name": name, "uom": uom, "per_child_qty": format(value.normalize(), "f"), "total_qty": None}
				for (_code, name, uom), value in quantities.items()
			],
			"headcount_confirmed": False,
		}
	doc = _week(plan.get("custom_meal_week"))
	quantities = {}
	for row in _details(doc):
		if row["plan_name"] != plan.name:
			continue
		key = (row["ingredient_code"], row["ingredient_name"], row["uom"])
		item = quantities.setdefault(key, {"per_child_qty": Decimal(0), "total_qty": Decimal(0)})
		item["per_child_qty"] += Decimal(str(row["per_child_qty"]))
		item["total_qty"] += Decimal(str(row["total_qty"]))
	return {
		"rows": [
			{
				"ingredient_name": name,
				"uom": uom,
				"per_child_qty": format(value["per_child_qty"].normalize(), "f"),
				"total_qty": format(value["total_qty"].normalize(), "f"),
			}
			for (_code, name, uom), value in quantities.items()
		]
	}
