"""Kitchen execution backed by native Stock Entry and Stock Ledger Entry.

No entry is submitted by a create API. Actual consumption and loss share the
same submitted transfer-source balance; planned recipe quantities are never
represented as actual stock movements. Callers own commit/rollback.
"""
# ruff: noqa: RUF001

import hashlib
import json
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import now_datetime, today

SLOTS = ("早餐", "早点", "午餐", "午点", "晚餐")
ACTIONS = ("领用", "退料", "耗用", "损耗")
MANAGER_ROLES = {"System Manager", "Stock Manager"}
ZERO = Decimal("0")
EPSILON = Decimal("0.000000001")
MAX_QTY = Decimal("999999999999.999999999")
_MANAGED = ContextVar("meal_kitchen_managed", default=False)
_DAY_PROTECTED = (
	"meal_week",
	"meal_date",
	"company",
	"source_warehouse",
	"prepared_by",
	"approved_by",
	"approved_at",
	"execution_snapshot",
	"carry_confirmed",
	"carry_confirmation_snapshot",
	"owner",
)


@contextmanager
def _managed():
	token = _MANAGED.set(True)
	try:
		yield
	finally:
		_MANAGED.reset(token)


def _fail(message, permission=False):
	frappe.throw(_(message), frappe.PermissionError if permission else frappe.ValidationError)


def _date(value):
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	try:
		return date.fromisoformat(str(value))
	except TypeError, ValueError:
		_fail("请填写有效的厨房业务日期。")


def _decimal(value):
	try:
		result = Decimal(str(value if value is not None and value != "" else 0))
	except TypeError, ValueError, InvalidOperation:
		_fail("厨房数量必须是有效数字。")
	if not result.is_finite():
		_fail("厨房数量必须为有限数字。")
	return result


def _text(value):
	return format(_decimal(value).normalize(), "f")


def _same(left, right):
	return abs(_decimal(left) - _decimal(right)) <= EPSILON


def _json(value):
	if not value:
		return {}
	try:
		result = json.loads(value) if isinstance(value, str) else value
	except TypeError, ValueError:
		_fail("厨房核销依据格式无效，请核对记录。")
	if not isinstance(result, dict):
		_fail("厨房核销依据格式无效，请核对记录。")
	return result


def _hash(value):
	return hashlib.sha256(
		json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
	).hexdigest()


def _login():
	if frappe.session.user == "Guest":
		_fail("请先登录。", permission=True)


def _role(manager=False):
	_login()
	allowed = MANAGER_ROLES.copy()
	if not manager:
		allowed.update({"Stock User", "膳食业务经办员"})
	if not allowed.intersection(frappe.get_roles()):
		_fail("需要库管审核权限。" if manager else "需要厨房库存业务权限。", permission=True)


def _week(value, lock=False):
	_login()
	if not value or (not isinstance(value, str) and not getattr(value, "name", None)):
		_fail("请选择有效的食谱周。")
	if lock and not isinstance(value, str):
		value = value.name
	if lock:
		from tongjianyun.meal_stock_claims import lock_claim_scope

		company = frappe.db.get_value("Meal Planning Week", value, "company")
		if not company:
			_fail("请选择有效的食谱周。")
		lock_claim_scope(company)
	doc = frappe.get_doc("Meal Planning Week", value, for_update=lock) if isinstance(value, str) else value
	doc.check_permission("read")
	if doc.docstatus != 1:
		_fail("厨房执行必须关联已审核的周食谱。")
	return doc


def _day(name, lock=False, week_name=None):
	_login()
	if lock:
		# Read the immutable link only to establish Week -> Day lock order. The
		# locked header below is authoritative even after an earlier RR snapshot.
		week_name = week_name or frappe.db.get_value("Meal Kitchen Day", name, "meal_week")
		_week(week_name, lock=True)
		frappe.db.sql("SELECT name FROM `tabMeal Kitchen Day` WHERE name=%s FOR UPDATE", (name,))
	doc = frappe.get_doc("Meal Kitchen Day", name, for_update=lock)
	doc.check_permission("read")
	if lock and doc.meal_week != week_name:
		_fail("厨房业务来源、审批和核销依据由系统维护。")
	_week(doc.meal_week, lock=lock)
	return doc


def _refresh_day_plan(doc, week):
	meals, items = _effective_day(week, doc.meal_date, lock=True)
	changed = _item_signature(doc.items) != _item_signature(items) or {
		row.meal_type: _decimal(row.planned_headcount) for row in doc.meals
	} != {row.meal_type: _decimal(row.planned_headcount) for row in meals}
	if not changed:
		return False
	doc.check_permission("write")
	if doc.docstatus != 0 or any(entry.docstatus < 2 for entry in _read_entries(doc.name, lock=True)):
		_fail("食谱已变化；厨房已有库存单据或已日结，请先处理原单据，不能沿用旧菜单。")
	with _managed():
		doc.set("items", items)
		doc.carry_confirmed = 0
		doc.carry_confirmation_snapshot = None
		doc.set(
			"meals",
			[
				{
					"meal_type": row.meal_type,
					"planned_headcount": row.planned_headcount,
					"actual_headcount": 0,
					"actual_confirmed": 0,
					"reason": None,
				}
				for row in meals
			],
		)
		doc.save()
	return True


def _warehouses(day, week):
	if day.company != week.company or day.source_warehouse != week.raw_material_warehouse:
		_fail("厨房公司或源仓与周食谱不一致。")
	if not day.kitchen_warehouse or day.kitchen_warehouse == day.source_warehouse:
		_fail("请选择与原料源仓不同的厨房实际仓库。")
	for name in (day.source_warehouse, day.kitchen_warehouse):
		warehouse = frappe.get_cached_doc("Warehouse", name)
		if warehouse.company != week.company or warehouse.is_group or warehouse.disabled:
			_fail("厨房和原料仓必须为本园所启用的非汇总仓库。")


@frappe.whitelist(methods=["POST"])
def configure_kitchen_warehouse(week_name, kitchen_warehouse):
	"""Set a real kitchen warehouse before execution; never move any stock."""
	_role(manager=True)
	week = _week(week_name, lock=True)
	if not isinstance(kitchen_warehouse, str) or not kitchen_warehouse:
		_fail("请选择有效的厨房实际仓库。")
	_warehouses(
		frappe._dict(
			company=week.company,
			source_warehouse=week.raw_material_warehouse,
			kitchen_warehouse=kitchen_warehouse,
		),
		week,
	)
	if week.get("kitchen_warehouse") == kitchen_warehouse:
		return {"name": week.name, "kitchen_warehouse": kitchen_warehouse, "changed": False}
	if frappe.db.sql(
		"SELECT name FROM `tabMeal Kitchen Day` WHERE meal_week=%s LIMIT 1 FOR UPDATE", (week.name,)
	) or frappe.db.sql(
		"SELECT name FROM `tabStock Entry` WHERE custom_meal_week=%s LIMIT 1 FOR UPDATE", (week.name,)
	):
		_fail("本周已有厨房执行或库存单据，不能更换周计划厨房仓库。")
	week.db_set("kitchen_warehouse", kitchen_warehouse, update_modified=False)
	return {"name": week.name, "kitchen_warehouse": kitchen_warehouse, "changed": True}


def _effective_day(week, meal_date, lock=False, *, issue_review=None):
	# Delayed import: the adjustment module owns effective menu selection.
	from tongjianyun.meal_adjustments import get_effective_meals
	from tongjianyun.meal_planning import _recipe_signature

	meal_date = _date(meal_date)
	if not _date(week.week_start) <= meal_date <= _date(week.week_end):
		_fail("厨房日期不在所选食谱周内。")
	meals = [row for row in get_effective_meals(week, lock=lock) if _date(row.meal_date) == meal_date]
	if len(meals) != 5 or {row.meal_type for row in meals} != set(SLOTS):
		_fail("厨房日期必须有完整且不重复的五个有效餐次。")
	quantities = defaultdict(lambda: ZERO)
	uoms = {}
	for meal in meals:
		count = _decimal(meal.planned_headcount)
		if count < ZERO or count != count.to_integral_value():
			_fail("有效餐次人数必须为非负整数。")
		if count == ZERO:
			continue
		if not meal.get("production_plan") or not meal.get("recipe_hash"):
			_fail("有效餐次缺少已冻结的生产计划或配方依据。")
		plan = frappe.get_doc("Production Plan", meal.production_plan, for_update=lock)
		if issue_review is None:
			plan.check_permission("read")
		if (
			plan.docstatus != 1
			or plan.company != week.company
			or plan.custom_meal_week != week.name
			or _date(plan.custom_meal_date) != meal_date
			or plan.custom_meal_type != meal.meal_type
			or any(not _same(row.planned_qty, count) for row in plan.po_items)
		):
			_fail("有效餐次的原生生产计划来源、状态或人数不一致。")
		if _recipe_signature(plan) != meal.recipe_hash:
			_fail("厨房餐次配方与冻结依据不一致，请先按流程处理食谱变更。")
		frozen = meal.get("frozen_requirements")
		if not isinstance(frozen, list) or not frozen:
			_fail("厨房餐次缺少冻结食材需求，不能用当前库存代替计划依据。")
		for row in frozen:
			code = row.get("item_code")
			item = frappe.get_cached_doc("Item", code)
			policy = row.get("policy")
			if item.disabled or policy != item.get("custom_meal_procurement_policy"):
				_fail("食材启用或采购分类与冻结依据不一致。")
			if row.get("warehouse") != week.raw_material_warehouse:
				_fail("冻结食材来源仓库与周食谱不一致。")
			if policy == "厨房用水":
				continue
			if policy != "采购" or not item.is_stock_item:
				_fail("厨房库存执行仅支持已确认采购的库存食材。")
			uom = row.get("stock_uom") or row.get("uom")
			if uom != item.stock_uom:
				_fail("冻结食材需求必须使用对应物料的库存单位。")
			qty = _decimal(row.get("required_qty"))
			if qty <= ZERO:
				_fail("冻结食材需求必须为正数。")
			if code in uoms and uoms[code] != uom:
				_fail("同一食材存在不一致的库存单位。")
			uoms[code] = uom
			quantities[code] += qty
	items = [
		{"item_code": code, "planned_qty": float(quantities[code]), "stock_uom": uoms[code]}
		for code in sorted(quantities)
	]
	return sorted(meals, key=lambda row: SLOTS.index(row.meal_type)), items


def _verify_effective_source(day, week, lock=False, *, issue_review=None):
	if issue_review is not None:
		# The reviewer verifies the frozen recipe through the linked transfer. No
		# manufacturing document is returned or made readable outside this check.
		if (issue_review.custom_meal_kitchen_day, issue_review.custom_meal_week, issue_review.custom_meal_action) != (
			day.name, week.name, "领用"
		) or not _can_review_issue(issue_review):
			_fail("没有审核本日领用单的权限。", permission=True)
	meals, expected = _effective_day(week, day.meal_date, lock=lock, issue_review=issue_review)
	if _item_signature(day.items) != _item_signature(expected):
		_fail("厨房食材计划与当前有效食谱不一致，请先核对食谱调整。")
	if len(day.meals) != 5 or {row.meal_type for row in day.meals} != set(SLOTS):
		_fail("厨房执行必须保留完整五餐。")
	planned = {row.meal_type: row.planned_headcount for row in meals}
	if any(not _same(row.planned_headcount, planned[row.meal_type]) for row in day.meals):
		_fail("厨房计划人数与当前有效食谱不一致，请先核对食谱调整。")


def _item_signature(items):
	result = {}
	for row in items:
		code = row.get("item_code")
		if not code or code in result:
			_fail("厨房食材存在空物料或重复行。")
		result[code] = (row.get("stock_uom"), _decimal(row.get("planned_qty")))
	return result


def validate_day(doc, method=None):
	week = _week(doc.meal_week, lock=True)
	_warehouses(doc, week)
	meals, expected = _effective_day(week, doc.meal_date, lock=True)
	doc.active_day_key = _hash([doc.meal_week, str(_date(doc.meal_date))]) if doc.docstatus != 2 else None
	old = doc.get_doc_before_save()
	if not _MANAGED.get():
		if not old:
			_fail("请从食谱周计划建立厨房执行记录。")
		for field in _DAY_PROTECTED:
			if str(doc.get(field) or "") != str(old.get(field) or ""):
				_fail("厨房业务来源、审批和核销依据由系统维护。")
		if doc.kitchen_warehouse != old.kitchen_warehouse:
			if any(entry.docstatus < 2 for entry in _read_entries(doc.name, lock=True)):
				_fail("已经建立库存流水后不能更换厨房仓库。")
	if _item_signature(doc.items) != _item_signature(expected):
		_fail("厨房食材计划与当前有效食谱不一致，请核对食谱调整和执行记录。")
	if len(doc.meals) != 5 or {row.meal_type for row in doc.meals} != set(SLOTS):
		_fail("厨房执行必须保留完整五餐，停供餐次填写零人数和原因。")
	planned = {row.meal_type: row.planned_headcount for row in meals}
	for row in doc.meals:
		if not _same(row.planned_headcount, planned[row.meal_type]):
			_fail("厨房餐次计划人数由有效食谱维护。")
		actual = _decimal(row.actual_headcount)
		if actual < ZERO or actual != actual.to_integral_value():
			_fail("实际供餐人数必须为非负整数。")
		if row.actual_confirmed and (actual == ZERO or actual != _decimal(row.planned_headcount)):
			if not str(row.reason or "").strip():
				_fail("停供或实际人数与计划不一致时必须填写原因。")
		row.actual_headcount = int(actual)
	if old and (_day_business_signature(doc) != _day_business_signature(old)):
		doc.carry_confirmed = 0
		doc.carry_confirmation_snapshot = None
	doc.status = "已取消" if doc.docstatus == 2 else ("已日结" if doc.docstatus == 1 else "执行草稿")


@frappe.whitelist(methods=["POST"])
def get_kitchen_day(week_name, meal_date, kitchen_warehouse=None):
	_role()
	week = _week(week_name, lock=True)
	if not frappe.has_permission("Meal Kitchen Day", "create"):
		_fail("没有建立厨房执行记录的权限。", permission=True)
	meal_date = _date(meal_date)
	existing = [
		row.name
		for row in frappe.db.sql(
			"SELECT name FROM `tabMeal Kitchen Day` WHERE meal_week=%s AND meal_date=%s "
			"AND docstatus<2 ORDER BY name LIMIT 2 FOR UPDATE",
			(week.name, meal_date),
			as_dict=True,
		)
	]
	if existing:
		if len(existing) != 1:
			_fail("同日厨房执行记录重复，请先核对。")
		doc = _day(existing[0], lock=True, week_name=week.name)
		if kitchen_warehouse and kitchen_warehouse != doc.kitchen_warehouse:
			_fail("该日已有厨房执行记录，请打开已有记录核对仓库。")
		refreshed = _refresh_day_plan(doc, week)
		return {"name": doc.name, "created": False, "plan_refreshed": refreshed}
	if frappe.db.sql(
		"SELECT s.name FROM `tabStock Entry` s JOIN `tabMeal Kitchen Day` d "
		"ON d.name=s.custom_meal_kitchen_day WHERE d.meal_week=%s AND d.meal_date=%s "
		"AND d.docstatus=2 AND s.docstatus=1 LIMIT 1 FOR UPDATE",
		(week.name, meal_date),
	):
		_fail("已取消的同日厨房记录仍有有效库存流水，请先处理原库存更正。")
	meals, items = _effective_day(week, meal_date, lock=True)
	if all(row.service_suspended for row in meals):
		_fail("该日已全部停供，无需建立厨房日结。")
	doc = frappe.get_doc(
		{
			"doctype": "Meal Kitchen Day",
			"meal_week": week.name,
			"meal_date": meal_date,
			"company": week.company,
			"source_warehouse": week.raw_material_warehouse,
			"kitchen_warehouse": kitchen_warehouse or week.get("kitchen_warehouse"),
			"prepared_by": frappe.session.user,
			"items": items,
			"meals": [
				{
					"meal_type": row.meal_type,
					"planned_headcount": row.planned_headcount,
					"actual_headcount": 0,
					"actual_confirmed": 0,
				}
				for row in meals
			],
		}
	)
	with _managed():
		doc.insert()
	return {"name": doc.name, "created": True}


@frappe.whitelist(methods=["POST"])
def refresh_kitchen_day_plan(day_name):
	_role()
	doc = _day(day_name, lock=True)
	return {"name": doc.name, "plan_refreshed": _refresh_day_plan(doc, _week(doc.meal_week, lock=True))}


def _read_entries(day_name, lock=False):
	suffix = " FOR UPDATE" if lock else ""
	headers = [
		frappe._dict(row)
		for row in frappe.db.sql(
			"SELECT * FROM `tabStock Entry` WHERE custom_meal_kitchen_day=%s ORDER BY creation,name" + suffix,
			(day_name,),
			as_dict=True,
		)
	]
	if not headers:
		return []
	names = [row.name for row in headers]
	children = frappe.db.sql(
		"SELECT * FROM `tabStock Entry Detail` WHERE parent IN %(names)s "
		"AND parenttype='Stock Entry' ORDER BY parent,idx,name" + suffix,
		{"names": names},
		as_dict=True,
	)
	by_parent = defaultdict(list)
	for row in children:
		by_parent[row.parent].append(frappe._dict(row))
	for row in headers:
		row["items"] = by_parent[row.name]
	return headers


def _entry_qty(row):
	qty = _decimal(row.get("qty"))
	if qty <= ZERO or _decimal(row.get("conversion_factor")) != 1 or _decimal(row.get("transfer_qty")) != qty:
		_fail("厨房库存行须使用真实正数库存数量，换算系数必须为一。")
	return qty


def _entry_facts(day, entries, exclude=None, opening=None):
	"""Pure balance reconstruction from submitted entries; no draft is consumed."""
	planned = _item_signature(day.items)
	allowed = dict(planned)
	issues = {}
	for source in opening or []:
		ref, code = source.get("issue_detail"), source.get("item_code")
		qty = _decimal(source.get("qty"))
		if not ref or ref in issues or qty <= ZERO or not source.get("stock_uom"):
			_fail("厨房期初领用来源不唯一或数量无效。")
		if code in allowed and allowed[code][0] != source["stock_uom"]:
			_fail("厨房期初食材单位与当前计划不一致。")
		allowed.setdefault(code, (source["stock_uom"], ZERO))
		issues[ref] = {**source, "item_code": code, "qty": qty, "entry": source["origin_entry"]}
	uses = defaultdict(lambda: ZERO)
	totals = {
		code: {
			"opening_qty": sum((row["qty"] for row in issues.values() if row["item_code"] == code), ZERO),
			"issued_qty": ZERO,
			"returned_qty": ZERO,
			"consumed_qty": ZERO,
			"loss_qty": ZERO,
			"balance_qty": ZERO,
			"carry_out_qty": ZERO,
		}
		for code in allowed
	}
	active = [entry for entry in entries if entry.name != exclude and entry.docstatus == 1]
	seen_entries = set()
	for entry in active:
		if entry.name in seen_entries:
			_fail("厨房库存来源存在重复单据。")
		seen_entries.add(entry.name)
		if (
			entry.custom_meal_week != day.meal_week
			or entry.company != day.company
			or entry.custom_meal_action not in ACTIONS
		):
			_fail("厨房库存单据的周、公司、日期或动作来源不一致。")
		action = entry.custom_meal_action
		posted, service = _date(entry.posting_date), _date(day.meal_date)
		if posted > service or (action != "领用" and posted != service):
			_fail("领用日期不能晚于供餐日期，其他厨房动作须按供餐日期记账。")
		purpose = "Material Transfer" if action in ("领用", "退料") else "Material Issue"
		if entry.purpose != purpose or entry.stock_entry_type != purpose or not entry.get("items"):
			_fail("厨房动作与原生库存单据类型不一致。")
		for row in entry.get("items"):
			code = row.item_code
			if code not in allowed or row.stock_uom != allowed[code][0] or row.uom != allowed[code][0]:
				_fail("库存食材或计量单位不属于本日有效食谱。")
			if action in ("领用", "耗用") and code not in planned:
				_fail("领用或耗用食材必须属于本日有效菜单。")
			qty = _entry_qty(row)
			source = day.source_warehouse if action == "领用" else day.kitchen_warehouse
			if row.s_warehouse != source or (action == "领用" and row.t_warehouse != day.kitchen_warehouse):
				_fail("厨房库存行的源仓或目标仓不一致。")
			if action == "领用":
				if not row.name or row.name in issues or row.get("custom_meal_issue_detail"):
					_fail("厨房领用来源行不唯一或错误引用其他领用。")
				issues[row.name] = {
					"item_code": code,
					"qty": qty,
					"entry": entry.name,
					"origin_entry": entry.name,
					"origin_week": day.meal_week,
					"origin_date": str(_date(entry.posting_date)),
					"origin_order": str(entry.get("creation") or entry.name),
					"original_qty": _text(qty),
					"source_warehouse": day.source_warehouse,
					"kitchen_warehouse": day.kitchen_warehouse,
					"stock_uom": row.stock_uom,
				}
				totals[code]["issued_qty"] += qty
	for entry in active:
		action = entry.custom_meal_action
		if action == "领用":
			continue
		for row in entry.get("items"):
			ref = row.get("custom_meal_issue_detail")
			if ref not in issues or issues[ref]["item_code"] != row.item_code:
				_fail("退料、耗用或损耗必须引用有效期初或本日同食材的已提交领用行。")
			target = issues[ref]["source_warehouse"] if action == "退料" else None
			if (row.t_warehouse or None) != target:
				_fail("退料必须返回原领用源仓，耗用和损耗不能指定目标仓。")
			qty = _entry_qty(row)
			uses[ref] += qty
			if uses[ref] > issues[ref]["qty"]:
				_fail("退料、耗用与损耗合计超过已提交领用量，不能重复消耗或超退。")
			key = {"退料": "returned_qty", "耗用": "consumed_qty", "损耗": "loss_qty"}[action]
			totals[row.item_code][key] += qty
	for values in totals.values():
		values["balance_qty"] = (
			values["opening_qty"]
			+ values["issued_qty"]
			- values["returned_qty"]
			- values["consumed_qty"]
			- values["loss_qty"]
		)
		values["carry_out_qty"] = values["balance_qty"]
	return {
		"totals": totals,
		"issues": issues,
		"uses": uses,
		"entries": active,
		"opening_sources": list(opening or []),
		"allowed_items": allowed,
	}


def _carry_sources(facts, owner_week):
	return [
		{
			"issue_detail": ref,
			"item_code": source["item_code"],
			"stock_uom": source["stock_uom"],
			"source_warehouse": source["source_warehouse"],
			"kitchen_warehouse": source["kitchen_warehouse"],
			"origin_entry": source["entry"],
			"origin_week": source["origin_week"],
			"origin_date": source.get("origin_date"),
			"origin_order": source.get("origin_order"),
			"original_qty": source["original_qty"],
			"qty": _text(source["qty"] - facts["uses"].get(ref, ZERO)),
			"owner_week": owner_week,
		}
		for ref, source in sorted(
			facts["issues"].items(),
			key=lambda pair: (pair[1].get("origin_date") or "", pair[1].get("origin_order") or "", pair[0]),
		)
		if source["qty"] - facts["uses"].get(ref, ZERO) > ZERO
	]


def _opening_sources(day, lock=False):
	rows = frappe.db.sql(
		"SELECT name FROM `tabMeal Kitchen Day` WHERE company=%s AND kitchen_warehouse=%s "
		"AND meal_date<%s AND docstatus=1 ORDER BY meal_date DESC,name DESC LIMIT 1"
		+ (" FOR UPDATE" if lock else ""),
		(day.company, day.kitchen_warehouse, day.meal_date),
		as_dict=True,
	)
	if not rows:
		return [], None
	previous = frappe.get_doc("Meal Kitchen Day", rows[0].name, for_update=lock)
	_verified_day(previous, lock=lock)
	proof = _json(previous.execution_snapshot)
	return proof.get("carry_out_sources", []), {
		"day_name": previous.name,
		"ledger_hash": proof["ledger_hash"],
	}


def _check_execution_order(day, advance_issue=False):
	rows = frappe.db.sql(
		"SELECT d.name,d.meal_date,d.docstatus, EXISTS(SELECT 1 FROM `tabStock Entry` e "
		"WHERE e.custom_meal_kitchen_day=d.name AND e.docstatus=1 AND "
		"(e.custom_meal_action<>'领用' OR e.posting_date>=d.meal_date)) AS started_service "
		"FROM `tabMeal Kitchen Day` d WHERE d.company=%s "
		"AND d.kitchen_warehouse=%s AND d.name<>%s AND d.docstatus<2 AND "
		"(d.docstatus=1 OR EXISTS(SELECT s.name FROM `tabStock Entry` s "
		"WHERE s.custom_meal_kitchen_day=d.name AND s.docstatus=1)) "
		"ORDER BY d.meal_date,d.name FOR UPDATE",
		(day.company, day.kitchen_warehouse, day.name),
		as_dict=True,
	)
	if any(_date(row.meal_date) > _date(day.meal_date) and (row.docstatus == 1 or row.started_service) for row in rows):
		_fail("厨房后日已有实际业务，不能回填或取消前日来源。")
	if not advance_issue and any(_date(row.meal_date) < _date(day.meal_date) and row.docstatus != 1 for row in rows):
		_fail("请先完成前一厨房执行日的真实日结，再使用留存。")


def _assert_actual_kitchen_stock(day, facts):
	rows = frappe.db.sql(
		"SELECT item_code,actual_qty FROM `tabBin` WHERE warehouse=%s ORDER BY item_code FOR UPDATE",
		(day.kitchen_warehouse,),
		as_dict=True,
	)
	actual = {row.item_code: _decimal(row.actual_qty) for row in rows}
	expected = {code: row["balance_qty"] for code, row in facts["totals"].items()}
	# All open service days share this physical warehouse. Their individual allocations
	# must be counted in Bin, but never passed into another day's carry or consumption.
	others = frappe.db.sql(
		"""SELECT i.item_code, SUM((CASE WHEN i.t_warehouse=d.kitchen_warehouse THEN i.transfer_qty ELSE 0 END)
		    - (CASE WHEN i.s_warehouse=d.kitchen_warehouse THEN i.transfer_qty ELSE 0 END)) AS qty
		FROM `tabMeal Kitchen Day` d JOIN `tabStock Entry` s ON s.custom_meal_kitchen_day=d.name
		JOIN `tabStock Entry Detail` i ON i.parent=s.name
		WHERE d.company=%s AND d.kitchen_warehouse=%s AND d.docstatus=0 AND d.name<>%s
		  AND s.docstatus=1 GROUP BY i.item_code FOR UPDATE""",
		(day.company, day.kitchen_warehouse, day.name), as_dict=True,
	)
	for row in others:
		expected[row.item_code] = expected.get(row.item_code, ZERO) + _decimal(row.qty)
	if any(
		not _same(actual.get(code, ZERO), expected.get(code, ZERO)) for code in set(actual) | set(expected)
	):
		_fail("厨房实际库存与可追溯领用余额不一致，请先核对真实库存更正。")


def _assert_global_source_balance(day, candidate):
	if candidate.custom_meal_action == "领用":
		return
	needed = defaultdict(lambda: ZERO)
	for row in candidate.items:
		needed[row.custom_meal_issue_detail] += _entry_qty(row)
	refs = sorted(needed)
	rows = frappe.db.sql(
		"SELECT d.name,d.parent,d.item_code,d.stock_uom,d.uom,d.qty,d.transfer_qty,d.conversion_factor,"
		"d.s_warehouse,d.t_warehouse,s.company,s.docstatus,s.custom_meal_action,s.posting_date "
		"FROM `tabStock Entry Detail` d JOIN `tabStock Entry` s ON s.name=d.parent "
		"WHERE d.name IN %(refs)s ORDER BY d.name FOR UPDATE",
		{"refs": refs},
		as_dict=True,
	)
	if {row.name for row in rows} != set(refs):
		_fail("厨房原始领用来源不存在或不完整。")
	for row in rows:
		if (
			row.docstatus != 1
			or row.company != day.company
			or row.custom_meal_action != "领用"
			or row.t_warehouse != day.kitchen_warehouse
			or _date(row.posting_date) > _date(day.meal_date)
		):
			_fail("厨房原始领用的公司、仓库、日期或状态不一致。")
		frappe.get_doc("Stock Entry", row.parent, for_update=True).check_permission("read")
	uses = frappe.db.sql(
		"SELECT d.custom_meal_issue_detail,d.qty,d.transfer_qty,d.conversion_factor,d.item_code,d.stock_uom,"
		"d.uom,d.s_warehouse,d.t_warehouse,s.company,s.custom_meal_action,s.posting_date "
		"FROM `tabStock Entry Detail` d JOIN `tabStock Entry` s ON s.name=d.parent "
		"WHERE d.custom_meal_issue_detail IN %(refs)s AND s.docstatus=1 AND s.name<>%(excluded)s "
		"ORDER BY d.custom_meal_issue_detail,s.name,d.name FOR UPDATE",
		{"refs": refs, "excluded": candidate.name or ""},
		as_dict=True,
	)
	originals = {row.name: row for row in rows}
	spent = defaultdict(lambda: ZERO)
	for row in uses:
		source = originals[row.custom_meal_issue_detail]
		if (
			row.company != day.company
			or row.item_code != source.item_code
			or row.stock_uom != source.stock_uom
			or row.uom != source.stock_uom
			or row.s_warehouse != day.kitchen_warehouse
			or row.custom_meal_action not in ("耗用", "退料", "损耗")
			or (row.t_warehouse or None) != (source.s_warehouse if row.custom_meal_action == "退料" else None)
		):
			_fail("厨房跨日来源存在不一致的实际使用记录。")
		spent[source.name] += _entry_qty(row)
	if any(spent[ref] + qty - _entry_qty(originals[ref]) > EPSILON for ref, qty in needed.items()):
		_fail("厨房原始领用已被其他日期使用，本次合计不能超过原量。")


def get_kitchen_carry_available(company, kitchen_warehouse, as_of=None, lock=False):
	"""Internal source balance evidence; kitchen stock is never raw shared stock."""
	if lock:
		from tongjianyun.meal_stock_claims import lock_claim_scope

		lock_claim_scope(company)
	rows = frappe.db.sql(
		"SELECT d.name FROM `tabMeal Kitchen Day` d WHERE d.company=%s AND d.kitchen_warehouse=%s "
		"AND d.docstatus<2 AND d.meal_date<=%s AND (d.docstatus=1 OR EXISTS(SELECT s.name "
		"FROM `tabStock Entry` s WHERE s.custom_meal_kitchen_day=d.name AND s.docstatus=1)) "
		"ORDER BY d.meal_date DESC,d.name DESC LIMIT 1" + (" FOR UPDATE" if lock else ""),
		(company, kitchen_warehouse, as_of or today()),
		as_dict=True,
	)
	if not rows:
		return {
			"company": company,
			"kitchen_warehouse": kitchen_warehouse,
			"sources": [],
			"totals": {},
			"owner_day": None,
		}
	day = frappe.get_doc("Meal Kitchen Day", rows[0].name, for_update=lock)
	day.check_permission("read")
	facts = _ledger(day, lock=lock, verify_sle=True)
	return {
		"company": company,
		"kitchen_warehouse": kitchen_warehouse,
		"owner_day": day.name,
		"current_owner_week": day.meal_week,
		"sources": _carry_sources(facts, day.meal_week),
		"totals": {code: _text(row["balance_qty"]) for code, row in facts["totals"].items()},
	}


def _verify_sle(day, facts, lock=False):
	names = [entry.name for entry in facts["entries"]]
	if not names:
		return []
	rows = frappe.db.sql(
		"SELECT name,voucher_no,voucher_detail_no,warehouse,item_code,actual_qty "
		"FROM `tabStock Ledger Entry` WHERE voucher_type='Stock Entry' AND voucher_no IN %(names)s "
		"AND COALESCE(is_cancelled,0)=0 ORDER BY voucher_no,voucher_detail_no,warehouse,name"
		+ (" FOR UPDATE" if lock else ""),
		{"names": names},
		as_dict=True,
	)
	actual = defaultdict(lambda: ZERO)
	for row in rows:
		actual[(row.voucher_no, row.voucher_detail_no, row.warehouse, row.item_code)] += _decimal(
			row.actual_qty
		)
	expected = defaultdict(lambda: ZERO)
	for entry in facts["entries"]:
		for row in entry.get("items"):
			qty = _entry_qty(row)
			expected[(entry.name, row.name, row.s_warehouse, row.item_code)] -= qty
			if row.t_warehouse:
				expected[(entry.name, row.name, row.t_warehouse, row.item_code)] += qty
	if set(actual) != set(expected) or any(not _same(actual[key], qty) for key, qty in expected.items()):
		_fail("已提交厨房单据与实际库存账流水不一致，不能认定已执行。")
	return [
		{
			"entry": key[0],
			"detail": key[1],
			"warehouse": key[2],
			"item_code": key[3],
			"actual_qty": _text(actual[key]),
		}
		for key in sorted(actual)
	]


def _ledger(day, lock=False, verify_sle=False, exclude=None):
	entries = _read_entries(day.name, lock)
	opening, previous = _opening_sources(day, lock=lock)
	facts = _entry_facts(day, entries, exclude, opening=opening)
	facts["opening_day"] = previous
	if verify_sle:
		facts["stock_ledger"] = _verify_sle(day, facts, lock)
	facts["drafts"] = [entry for entry in entries if entry.name != exclude and entry.docstatus == 0]
	return facts


def _carry_basis(day, facts):
	return _hash(
		{
			"day": day.name,
			"company": day.company,
			"kitchen": day.kitchen_warehouse,
			"actual": _day_business_signature(day),
			"notes": str(day.get("carry_notes") or "").strip(),
			"opening_day": facts.get("opening_day"),
			"opening_sources": facts.get("opening_sources", []),
			"sources": _carry_sources(facts, day.meal_week),
			"stock_ledger": facts.get("stock_ledger", []),
			"stock_entries": [entry.name for entry in facts["entries"]],
		}
	)


def _carry_confirmation(day, facts):
	basis = _carry_basis(day, facts)
	positive = {
		code: _text(row["balance_qty"]) for code, row in facts["totals"].items() if row["balance_qty"] > ZERO
	}
	proof = _json(day.get("carry_confirmation_snapshot"))
	current = bool(
		day.get("carry_confirmed")
		and proof.get("basis_hash") == basis
		and proof.get("physical_counts") == positive
		and proof.get("confirmed_by")
		and proof.get("confirmed_at")
	)
	return positive, basis, current, proof


def _invalidate_carry(day):
	if day.get("carry_confirmed") or day.get("carry_confirmation_snapshot"):
		day.db_set({"carry_confirmed": 0, "carry_confirmation_snapshot": None}, update_modified=False)


@frappe.whitelist(methods=["POST"])
def confirm_kitchen_carry(day_name, physical_counts, notes=None):
	"""Record an operator's explicit physical count; never infer it from Bin."""
	_role()
	day = _day(day_name, lock=True)
	day.check_permission("write")
	if day.docstatus != 0 or _date(day.meal_date) > _date(today()):
		_fail("只能清点当前或过去尚未日结的厨房余料。")
	_check_execution_order(day)
	facts = _ledger(day, lock=True, verify_sle=True)
	if facts["drafts"]:
		_fail("请先处理厨房库存草稿，再确认实际留存。")
	_assert_actual_kitchen_stock(day, facts)
	if isinstance(physical_counts, str):
		try:
			physical_counts = json.loads(physical_counts)
		except TypeError, ValueError:
			_fail("请逐食材输入真实盘点数量。")
	if not isinstance(physical_counts, list):
		_fail("请逐食材输入真实盘点数量。")
	expected = {
		code: row["balance_qty"] for code, row in facts["totals"].items() if row["balance_qty"] > ZERO
	}
	observed = {}
	for row in physical_counts:
		if not isinstance(row, dict) or set(row) != {"item_code", "qty"}:
			_fail("实物清点仅接受食材和实际数量。")
		code = row["item_code"]
		if not isinstance(code, str) or code in observed or row["qty"] in (None, ""):
			_fail("请逐食材输入真实盘点数量，不能留空或重复。")
		observed[code] = _decimal(row["qty"])
	if set(observed) != set(expected) or any(observed[code] != qty for code, qty in expected.items()):
		_fail("实物清点与系统留存不一致，请先核对并按真实业务更正。")
	carry_notes = str(notes if notes is not None else day.get("carry_notes") or "").strip()
	if expected and not carry_notes:
		_fail("有真实余料留厨时必须填写留存说明。")
	day.carry_notes = carry_notes
	_, basis, _, _ = _carry_confirmation(day, facts)
	proof = {
		"basis_hash": basis,
		"physical_counts": {code: _text(qty) for code, qty in sorted(observed.items())},
		"confirmed_by": frappe.session.user,
		"confirmed_at": str(now_datetime()),
		"notes": carry_notes,
	}
	day.db_set(
		{
			"carry_notes": carry_notes,
			"carry_confirmed": 1,
			"carry_confirmation_snapshot": frappe.as_json(proof),
		},
		update_modified=False,
	)
	return {"name": day.name, "carry_confirmed": True, "basis_hash": basis}


def _service_menus(day):
	from tongjianyun.meal_adjustments import get_effective_meals

	meals = [row for row in get_effective_meals(day.meal_week) if _date(row.meal_date) == _date(day.meal_date)]
	plans = [row.production_plan for row in meals if row.production_plan]
	visible = []
	if plans and frappe.has_permission("Production Plan", "read"):
		visible = frappe.get_list(
			"Production Plan", filters={"name": ("in", plans)}, pluck="name", limit_page_length=0
		)

	lines = []
	if visible:
		lines = frappe.get_all(
			"Production Plan Item",
			filters={"parent": ("in", visible), "parenttype": "Production Plan", "parentfield": "po_items"},
			fields=["parent", "item_code", "custom_dish_name"], order_by="parent, idx",
		)

	codes = {line.item_code for line in lines if line.item_code}
	images = {}
	if codes and frappe.has_permission("Item", "read"):
		items = frappe.get_list(
			"Item", filters={"name": ("in", list(codes))}, fields=["name", "image"], limit_page_length=0
		)
		images = {item.name: item.image for item in items}

	dishes = defaultdict(list)
	for line in lines:
		dishes[line.parent].append({"name": line.custom_dish_name or line.item_code, "image": images.get(line.item_code)})
	menus = {}
	for meal in meals:
		menus[meal.meal_type] = {
			"suspended": bool(meal.service_suspended),
			"reason": meal.suspension_reason,
			"dishes": dishes.get(meal.production_plan) or [
				{"name": name.strip()} for name in (meal.menu or "").split("、") if name.strip()
			],
		}
	return menus


@frappe.whitelist()
def get_kitchen_ledger(day_name, include_menu=False):
	day = _day(day_name)
	facts = _ledger(day, verify_sle=True)
	blockers = []
	if _date(day.meal_date) > _date(today()):
		blockers.append("未来日期不能日结。")
	if facts["drafts"]:
		blockers.append("仍有未提交库存草稿，请核实后提交或删除。")
	positive, basis, confirmed, proof = _carry_confirmation(day, facts)
	if positive and not confirmed:
		blockers.append("厨房正余料尚未按当前流水逐项实盘确认留存。")
	if not all(row.actual_confirmed for row in day.meals):
		blockers.append("五餐实际供餐人数尚未全部确认。")
	positive_meals = any(_decimal(row.actual_headcount) > ZERO for row in day.meals)
	consumed = any(values["consumed_qty"] > ZERO for values in facts["totals"].values())
	if positive_meals and not consumed:
		blockers.append("有实际供餐人数但尚无实际耗用库存流水。")
	if not positive_meals and consumed:
		blockers.append("五餐均停供却存在供餐耗用，请先核对。")
	rows = []
	planned = _item_signature(day.items)
	for code, values in sorted(facts["totals"].items()):
		uom, planned_qty = facts["allowed_items"][code]
		actions = ["领用", "耗用"] if code in planned else []
		if values["balance_qty"] > ZERO:
			actions += ["退料", "损耗"]
		rows.append(
			{
				"item_code": code,
				"item_name": frappe.db.get_value("Item", code, "item_name"),
				"stock_uom": uom,
				"planned_qty": _text(planned_qty),
				"suggested_issue_qty": _text(max(ZERO, planned_qty - values["opening_qty"] - values["issued_qty"])),
				"allowed_actions": actions,
				"can_issue": code in planned,
				**{key: _text(value) for key, value in values.items()},
			}
		)
	return {
		"day_name": day.name,
		"meal_date": str(_date(day.meal_date)),
		**({"menus": _service_menus(day)} if str(include_menu).lower() in ("1", "true") else {}),
		"rows": rows,
		"stock_entries": [
			_stock_entry_summary(day, entry, include_menu=str(include_menu).lower() in ("1", "true"))
			for entry in facts["entries"] + facts["drafts"]
		],
		"has_drafts": bool(facts["drafts"]),
		"can_close": not blockers,
		"blockers": blockers,
		"carry_required": bool(positive),
		"carry_confirmation_current": confirmed,
		"carry_reviewer": proof.get("confirmed_by") if confirmed else None,
		"physical_counts": proof.get("physical_counts", {}) if confirmed else {},
		"basis_hash": basis,
		"opening_day": facts.get("opening_day"),
	}


def _issue_review_token(day, entry):
	return _hash([entry.name, str(entry.modified), day.source_warehouse, day.kitchen_warehouse, _item_signature(day.items)])


def _can_review_issue(entry):
	return bool(
		entry.owner != frappe.session.user
		and MANAGER_ROLES.intersection(frappe.get_roles())
		and entry.has_permission("submit")
	)


def _issue_review_blocker(day, entry):
	from frappe.model.workflow import get_workflow_name

	if day.docstatus != 0:
		return "厨房执行单已关闭。"
	if get_workflow_name("Stock Entry", entry):
		return "此领用单已启用库存审批工作流，请按该工作流审批。"
	return ""


def _stock_entry_summary(day, entry, include_menu):
	result = {
		"name": entry.name,
		"action": entry.custom_meal_action,
		"docstatus": entry.docstatus,
		"posting_date": str(entry.posting_date),
	}
	if not include_menu or entry.custom_meal_action != "领用":
		return result
	doc = frappe.get_doc({"doctype": "Stock Entry", **entry})
	if not doc.has_permission("read"):
		return result
	quantities = defaultdict(lambda: ZERO)
	for row in doc.items:
		quantities[row.item_code] += _decimal(row.qty)
	result["source_warehouse"] = day.source_warehouse
	result["kitchen_warehouse"] = day.kitchen_warehouse
	result["issue_quantities"] = {code: _text(qty) for code, qty in quantities.items()}
	if doc.docstatus == 0:
		result.update(
			can_review=_can_review_issue(doc),
			latest_issue_date=str(min(_date(day.meal_date), _date(today()))),
			review_blocker=_issue_review_blocker(day, doc),
			review_token=_issue_review_token(day, doc),
		)
	else:
		proof = _json(doc.get("custom_meal_raw_claim_snapshot"))
		result.update(approved_by=proof.get("approved_by"), approved_at=proof.get("approved_at"))
	return result


@frappe.whitelist(methods=["POST"])
def approve_kitchen_issue(day_name: str, stock_entry: str, review_token: str, issue_date: str | None = None):
	"""Submit the reviewed native transfer under the current user's permissions."""
	_role(manager=True)
	day = _day(day_name, lock=True)
	entry = frappe.get_doc("Stock Entry", stock_entry, for_update=True)
	entry.check_permission("read")
	if (entry.custom_meal_kitchen_day, entry.custom_meal_week, entry.custom_meal_action) != (
		day.name, day.meal_week, "领用"
	):
		_fail("请选择本日执行单的领用记录。")
	if not _can_review_issue(entry):
		_fail("领用单须由另一位有提交权限的库存主管审核。", permission=True)
	if entry.docstatus == 1:
		return {"stock_entry": entry.name, "already_submitted": True}
	if entry.docstatus != 0:
		_fail("领用单已取消，请刷新执行单。")
	if review_token != _issue_review_token(day, entry):
		_fail("领用单或计划已更新，请重新核对明细。")
	if blocker := _issue_review_blocker(day, entry):
		_fail(blocker)
	# Older clients reviewed only the draft's posting date. Never silently move that
	# transaction to an earlier day on their behalf.
	actual_date = _date(entry.posting_date if issue_date is None else issue_date)
	if actual_date > min(_date(today()), _date(day.meal_date)):
		_fail("实际领用日期不能晚于今天或供餐日期。")
	entry.posting_date = actual_date
	entry.set_posting_time = 1
	entry.posting_time = now_datetime().time() if actual_date == _date(today()) else "23:59:59"
	entry.submit()
	return {"stock_entry": entry.name, "already_submitted": False}


def _input_items(day, items, action=None, opening=None):
	if isinstance(items, str):
		try:
			items = json.loads(items)
		except TypeError, ValueError:
			_fail("库存数量列表格式无效。")
	if not isinstance(items, list) or not items or len(items) > 200:
		_fail("请填写本次实际操作的食材和数量。")
	allowed = _item_signature(day.items)
	if action in ("退料", "损耗"):
		for source in opening or []:
			allowed.setdefault(source["item_code"], (source["stock_uom"], ZERO))
	result = {}
	for row in items:
		if not isinstance(row, dict) or set(row) - {"item_code", "qty"}:
			_fail("厨房库存输入仅接受食材和实际库存数量。")
		code = row.get("item_code")
		qty = _decimal(row.get("qty"))
		if not isinstance(code, str) or code not in allowed or code in result or qty <= ZERO:
			_fail("食材必须来自本日计划，不能重复，实际数量必须为正数。")
		if qty > MAX_QTY or qty.normalize().as_tuple().exponent < -9:
			_fail("实际库存数量超出系统支持的数值范围或小数精度。")
		item = frappe.get_cached_doc("Item", code)
		if item.disabled or not item.is_stock_item or item.get("has_batch_no") or item.get("has_serial_no"):
			_fail("当前厨房执行仅支持启用且无需批次或序列号的库存食材。")
		uom = frappe.get_cached_doc("UOM", item.stock_uom)
		if uom.must_be_whole_number and qty != qty.to_integral_value():
			_fail("该食材库存单位要求整数数量。")
		result[code] = qty
	return result


def _allocate_sources(facts, quantities):
	remaining = dict(quantities)
	rows = []
	for ref, source in facts["issues"].items():
		code = source["item_code"]
		available = source["qty"] - facts["uses"].get(ref, ZERO)
		taken = min(remaining.get(code, ZERO), available)
		if taken > ZERO:
			rows.append((code, taken, ref))
			remaining[code] -= taken
	if any(qty > ZERO for qty in remaining.values()):
		_fail("本次退料、耗用或损耗超过可用领用余额。")
	return rows


@frappe.whitelist(methods=["POST"])
def create_kitchen_stock_entry(day_name, action, items, reason=None):
	_role()
	day = _day(day_name, lock=True)
	week = _week(day.meal_week, lock=True)
	day.check_permission("write")
	if day.docstatus != 0 or week.get("kitchen_reconciled"):
		_fail("只有尚未日结或周结的厨房草稿可以登记库存操作。")
	if action not in ACTIONS:
		_fail("厨房库存动作无效。")
	if not frappe.has_permission("Stock Entry", "create"):
		_fail("没有创建原生库存单据的权限。", permission=True)
	_verify_effective_source(day, week, lock=True)
	facts = _ledger(day, lock=True, verify_sle=True)
	quantities = _input_items(day, items, action=action, opening=facts.get("opening_sources", []))
	if action == "损耗" and not str(reason or "").strip():
		_fail("登记损耗必须填写实际原因。")
	matching = [entry for entry in facts["drafts"] if entry.custom_meal_action == action]
	if matching:
		if len(matching) == 1:
			existing = matching[0]
			previous = defaultdict(lambda: ZERO)
			for row in existing.get("items"):
				previous[row.item_code] += _entry_qty(row)
			if dict(previous) == quantities:
				frappe.get_doc("Stock Entry", existing.name, for_update=True).check_permission("read")
				return {"stock_entry": existing.name, "created": False}
		_fail("该动作已有库存草稿，请先核实并处理已有草稿。")
	planned = _item_signature(day.items)
	if (
		action == "领用"
		and any(
			facts["totals"][code].get("opening_qty", ZERO)
			+ facts["totals"][code]["issued_qty"]
			+ qty
			- planned[code][1]
			> EPSILON
			for code, qty in quantities.items()
		)
		and not str(reason or "").strip()
	):
		_fail("超过计划食材量的领用必须填写实际原因。")
	allocations = (
		[(code, qty, None) for code, qty in quantities.items()]
		if action == "领用"
		else _allocate_sources(facts, quantities)
	)
	purpose = "Material Transfer" if action in ("领用", "退料") else "Material Issue"
	entry = frappe.new_doc("Stock Entry")
	entry.update(
		{
			"company": day.company,
			"stock_entry_type": purpose,
			"purpose": purpose,
			"posting_date": day.meal_date,
			"set_posting_time": 1,
			"custom_meal_week": day.meal_week,
			"custom_meal_kitchen_day": day.name,
			"custom_meal_action": action,
			"remarks": str(reason or "").strip(),
		}
	)
	for code, qty, ref in allocations:
		entry.append(
			"items",
			{
				"item_code": code,
				"qty": float(qty),
				"transfer_qty": float(qty),
				"uom": facts["allowed_items"][code][0],
				"stock_uom": facts["allowed_items"][code][0],
				"conversion_factor": 1,
				"s_warehouse": day.source_warehouse if action == "领用" else day.kitchen_warehouse,
				"t_warehouse": day.kitchen_warehouse
				if action == "领用"
				else (facts["issues"][ref]["source_warehouse"] if action == "退料" else None),
				"custom_meal_issue_detail": ref,
			},
		)
	entry.run_method("set_missing_values")
	with _managed():
		entry.insert()
	return {"stock_entry": entry.name, "created": True}


def validate_stock_entry(doc, method=None):
	old = doc.get_doc_before_save()
	if not any(
		doc.get(field) or (old and old.get(field))
		for field in ("custom_meal_week", "custom_meal_kitchen_day")
	):
		return
	if not doc.get("custom_meal_kitchen_day"):
		_fail("厨房库存单据缺少完整的每日执行来源。")
	_role(manager=doc.docstatus == 1)
	if not old and not _MANAGED.get():
		_fail("请从厨房执行记录建立原生库存草稿。")
	for field in ("custom_meal_week", "custom_meal_kitchen_day", "custom_meal_action"):
		if old and doc.get(field) != old.get(field):
			_fail("厨房库存来源和动作不能清除或更换。")
	if doc.get("custom_meal_raw_claim_snapshot") != (
		old.get("custom_meal_raw_claim_snapshot") if old else None
	):
		_fail("厨房原料归属依据由提交审核维护，不能手工更改。")
	if old and old.docstatus == 1 and _stock_business_signature(doc) != _stock_business_signature(old):
		_fail("已提交厨房单据的数量和仓库已冻结。")
	if old and doc.owner != old.owner:
		_fail("厨房库存单据经办人不能更换。")
	if doc.docstatus == 1 and doc.owner == frappe.session.user:
		_fail("厨房库存单据必须由其他授权审核人提交，经办人不能自行批准。", permission=True)
	day = _day(doc.custom_meal_kitchen_day, lock=True)
	week = _week(day.meal_week, lock=True)
	if day.docstatus != 0 or week.get("kitchen_reconciled"):
		_fail("已日结或周结的厨房记录不能修改库存流水。")
	_warehouses(day, week)
	issue_review = doc if doc.docstatus == 1 and doc.custom_meal_action == "领用" else None
	_verify_effective_source(day, week, lock=True, issue_review=issue_review)
	if doc.docstatus == 1 and _date(doc.posting_date) > _date(today()):
		_fail("未来日期的厨房库存草稿不能提交为实际执行。")
	if doc.custom_meal_action == "损耗" and not str(doc.remarks or "").strip():
		_fail("厨房损耗必须填写实际原因。")
	facts = _ledger(day, lock=True, verify_sle=True, exclude=doc.name)
	# Candidate remains a draft in storage until native submit. Treat it as
	# submitted only in this in-memory check, never in the real database.
	candidate = frappe._dict(doc.as_dict())
	candidate.docstatus = 1
	candidate["items"] = [frappe._dict(row.as_dict()) for row in doc.items]
	combined = _entry_facts(day, facts["entries"] + [candidate], opening=facts.get("opening_sources", []))
	if doc.docstatus == 1 and (not old or old.docstatus != 1):
		_check_execution_order(day, advance_issue=doc.custom_meal_action == "领用" and _date(doc.posting_date) < _date(day.meal_date))
		_assert_actual_kitchen_stock(day, facts)
		_assert_global_source_balance(day, doc)
		if doc.custom_meal_action == "领用":
			from tongjianyun.meal_stock_claims import assert_week_raw_stock_available

			doc.custom_meal_raw_claim_snapshot = frappe.as_json(
				assert_week_raw_stock_available(
					week,
					{
						code: sum((_entry_qty(row) for row in doc.items if row.item_code == code), ZERO)
						for code in {row.item_code for row in doc.items}
					},
					exclude_entry=doc.name,
					posting_date=doc.posting_date,
					posting_time=doc.posting_time,
				)
			)
	if doc.custom_meal_action == "领用" and not str(doc.remarks or "").strip():
		planned = _item_signature(day.items)
		if any(
			values["opening_qty"] + values["issued_qty"] - planned[code][1] > EPSILON
			for code, values in combined["totals"].items()
			if code in planned
		):
			_fail("超过计划食材量的领用必须填写实际原因。")
	_input_items(
		day,
		[
			{
				"item_code": code,
				"qty": float(sum((_entry_qty(row) for row in doc.items if row.item_code == code), ZERO)),
			}
			for code in sorted({row.item_code for row in doc.items})
		],
		action=doc.custom_meal_action,
		opening=facts.get("opening_sources", []),
	)
	_invalidate_carry(day)


def before_cancel_stock_entry(doc, method=None):
	old = doc.get_doc_before_save()
	if not any(
		doc.get(field) or (old and old.get(field))
		for field in ("custom_meal_week", "custom_meal_kitchen_day")
	):
		return
	if not doc.get("custom_meal_kitchen_day") or any(
		old and doc.get(field) != old.get(field)
		for field in (
			"custom_meal_week",
			"custom_meal_kitchen_day",
			"custom_meal_action",
			"owner",
			"custom_meal_raw_claim_snapshot",
		)
	):
		_fail("取消厨房库存单据时不能清除或更换原业务来源。")
	if old and _stock_business_signature(doc) != _stock_business_signature(old):
		_fail("取消厨房库存单据时不能改写原数量、单位、金额或仓库。")
	_role(manager=True)
	day = _day(doc.custom_meal_kitchen_day, lock=True)
	if day.docstatus == 1 or _week(day.meal_week, lock=True).get("kitchen_reconciled"):
		_fail("库存单据所属日结或周结仍有效，请先按正式更正流程处理。")
	entries = _read_entries(day.name, lock=True)
	if doc.custom_meal_action == "领用":
		refs = {row.name for row in doc.items}
		if frappe.db.sql(
			"SELECT d.name FROM `tabStock Entry Detail` d JOIN `tabStock Entry` s ON s.name=d.parent "
			"WHERE d.custom_meal_issue_detail IN %(refs)s AND s.docstatus<2 AND s.name<>%(name)s "
			"LIMIT 1 FOR UPDATE",
			{"refs": sorted(refs), "name": doc.name},
		):
			_fail("原领用已有跨日使用或草稿引用，不能取消。")
		if any(
			row.get("custom_meal_issue_detail") in refs
			for entry in entries
			if entry.name != doc.name and entry.docstatus < 2
			for row in entry.get("items")
		):
			_fail("该领用已有退料、耗用或损耗来源，请先处理后续单据及草稿。")
	_check_execution_order(day, advance_issue=doc.custom_meal_action == "领用" and _date(doc.posting_date) < _date(day.meal_date))
	opening, _ = _opening_sources(day, lock=True)
	_entry_facts(day, entries, exclude=doc.name, opening=opening)
	_invalidate_carry(day)


def _stock_business_signature(doc):
	headers = {
		key: str(doc.get(key) or "")
		for key in ("company", "purpose", "stock_entry_type", "posting_date", "posting_time")
	}
	items = []
	for row in doc.get("items"):
		item = {
			key: str(row.get(key) or "")
			for key in (
				"name",
				"item_code",
				"stock_uom",
				"uom",
				"s_warehouse",
				"t_warehouse",
				"custom_meal_issue_detail",
				"expense_account",
				"cost_center",
				"project",
			)
		}
		item.update(
			{
				key: _text(row.get(key))
				for key in (
					"qty",
					"transfer_qty",
					"conversion_factor",
					"basic_rate",
					"basic_amount",
					"valuation_rate",
					"amount",
					"additional_cost",
				)
			}
		)
		items.append(item)
	return {"headers": headers, "items": sorted(items, key=lambda row: row["name"])}


def _day_plans(week, meal_date=None, lock=False):
	rows = (
		frappe.db.sql(
			"SELECT name,company,docstatus,status,custom_meal_date,custom_meal_type FROM `tabProduction Plan` "
			"WHERE custom_meal_week=%s ORDER BY name FOR UPDATE",
			(week.name,),
			as_dict=True,
		)
		if lock
		else frappe.get_all(
			"Production Plan",
			filters={"custom_meal_week": week.name},
			fields=["name", "company", "docstatus", "status", "custom_meal_date", "custom_meal_type"],
			order_by="name asc",
			limit_page_length=0,
		)
	)
	result = []
	for row in rows:
		if (
			row.company != week.company
			or not _date(week.week_start) <= _date(row.custom_meal_date) <= _date(week.week_end)
			or row.custom_meal_type not in SLOTS
		):
			_fail("关联本周的生产计划存在公司、日期或餐次来源冲突。")
		if meal_date is not None and _date(row.custom_meal_date) != _date(meal_date):
			continue
		if row.docstatus == 0:
			plan = frappe.get_doc("Production Plan", row.name, for_update=lock)
			if _is_suspended_draft(week, plan, lock=lock):
				continue
			_fail("本周仍有未审核的餐次或替换生产计划。")
		if row.docstatus == 1:
			result.append(frappe.get_doc("Production Plan", row.name, for_update=lock))
	return result


def _is_suspended_draft(week, plan, lock=False):
	from tongjianyun.meal_adjustments import get_effective_meals
	from tongjianyun.meal_planning import _recipe_signature

	if plan.docstatus != 0 or plan.get("mr_items"):
		return False
	matches = [
		row
		for row in get_effective_meals(week, lock=lock)
		if row.get("production_plan") == plan.name
		and _date(row.meal_date) == _date(plan.custom_meal_date)
		and row.meal_type == plan.custom_meal_type
	]
	if len(matches) != 1:
		return False
	meal = matches[0]
	if (
		not meal.get("service_suspended")
		or _decimal(meal.planned_headcount) != ZERO
		or not meal.get("recipe_hash")
	):
		return False
	if _recipe_signature(plan) != meal.recipe_hash:
		_fail("停供草稿的配方与冻结依据不一致。")
	_no_work_orders(plan, lock=lock)
	return True


def _no_work_orders(plan, lock=False):
	filters = {"production_plan": plan.name, "docstatus": ["<", 2]}
	exists = (
		frappe.db.sql(
			"SELECT name FROM `tabWork Order` WHERE production_plan=%s AND docstatus<2 LIMIT 1 FOR UPDATE",
			(plan.name,),
		)
		if lock
		else frappe.db.exists("Work Order", filters)
	)
	if exists:
		_fail("餐次已有生产工单，请先核对实际制造业务，不能按厨房非制造核销关闭。")


def _native_close(plan):
	plan.check_permission("write")
	_no_work_orders(plan, lock=True)
	if plan.docstatus != 1:
		_fail("只能关闭已审核的餐次生产计划。")
	if plan.status not in ("Closed", "Completed"):
		from tongjianyun.meal_native_reservations import ensure_current_native_reservation_inputs

		ensure_current_native_reservation_inputs(plan.company)
		# Official close recalculates the plan's own native Bin reservations;
		# never edit Bin or pretend a finished good has been manufactured.
		plan.set_status(close=True)
	return plan.name


def close_meal_plan(plan):
	"""Internal adjustment helper: close only a future, wholly unexecuted plan."""
	_role(manager=True)
	plan = frappe.get_doc("Production Plan", plan) if isinstance(plan, str) else plan
	week = _week(plan.get("custom_meal_week"), lock=True)
	plan = frappe.get_doc("Production Plan", plan.name, for_update=True)
	if (
		plan.get("custom_meal_week") != week.name
		or plan.company != week.company
		or not _date(week.week_start) <= _date(plan.custom_meal_date) <= _date(week.week_end)
		or plan.custom_meal_type not in SLOTS
	):
		_fail("待关闭餐次不属于所选食谱周。")
	if _date(plan.custom_meal_date) < _date(today()):
		_fail("历史餐次不能作为尚未执行餐次关闭。")
	if frappe.db.sql(
		"SELECT name FROM `tabMeal Kitchen Day` WHERE meal_week=%s AND meal_date=%s "
		"AND docstatus=1 LIMIT 1 FOR UPDATE",
		(week.name, plan.custom_meal_date),
	):
		_fail("该日已经日结，不能关闭旧餐次以变更实际。")
	if frappe.db.sql(
		"SELECT s.name FROM `tabStock Entry` s JOIN `tabMeal Kitchen Day` d "
		"ON d.name=s.custom_meal_kitchen_day WHERE d.meal_week=%s AND d.meal_date=%s "
		"AND s.docstatus=1 LIMIT 1 FOR UPDATE",
		(week.name, plan.custom_meal_date),
	):
		_fail("该日已有实际厨房库存流水，不能关闭旧餐次进行食谱变更。")
	return _native_close(plan)


def _day_execution(day, lock=False):
	if _date(day.meal_date) > _date(today()):
		_fail("未来日期不能完成厨房日结。")
	week = _week(day.meal_week, lock=lock)
	_warehouses(day, week)
	_verify_effective_source(day, week, lock=lock)
	if len(day.meals) != 5 or {row.meal_type for row in day.meals} != set(SLOTS):
		_fail("日结缺少完整五餐记录。")
	actuals = []
	for row in sorted(day.meals, key=lambda row: SLOTS.index(row.meal_type)):
		actual = _decimal(row.actual_headcount)
		if not row.actual_confirmed or actual < ZERO or actual != actual.to_integral_value():
			_fail("五餐实际供餐人数必须逐餐明确确认，不能用默认零代替。")
		if (actual == ZERO or actual != _decimal(row.planned_headcount)) and not str(
			row.reason or ""
		).strip():
			_fail("实际停供或人数与教育计划不同必须保留原因。")
		actuals.append(
			{
				"meal_type": row.meal_type,
				"planned_headcount": int(row.planned_headcount),
				"actual_headcount": int(actual),
				"reason": str(row.reason or "").strip(),
			}
		)
	facts = _ledger(day, lock, verify_sle=True)
	if facts["drafts"]:
		_fail("仍有未提交厨房库存草稿，请核实后提交或删除。")
	positive, _, carry_confirmed, carry_proof = _carry_confirmation(day, facts)
	if positive and not carry_confirmed:
		_fail("厨房正余料须逐项实盘确认留存，不能假耗用或假退库。")
	if positive and day.get("approved_by") and day.approved_by == carry_proof.get("confirmed_by"):
		_fail("留存实盘确认人与日结审核人必须不同。", permission=True)
	if any(row["actual_headcount"] > 0 for row in actuals) and not any(
		row["consumed_qty"] > ZERO for row in facts["totals"].values()
	):
		_fail("存在实际供餐人数但没有已提交且有库存账证明的实际耗用，不能日结。")
	if not any(row["actual_headcount"] > 0 for row in actuals) and any(
		row["consumed_qty"] > ZERO for row in facts["totals"].values()
	):
		_fail("五餐均停供却存在供餐耗用，请先核对人数或库存业务原因。")
	proof = {
		"version": 2,
		"day_name": day.name,
		"meal_week": day.meal_week,
		"meal_date": str(_date(day.meal_date)),
		"company": day.company,
		"source_warehouse": day.source_warehouse,
		"kitchen_warehouse": day.kitchen_warehouse,
		"prepared_by": day.prepared_by,
		"owner": day.owner,
		"approved_by": day.approved_by,
		"approved_at": str(day.approved_at or ""),
		"actual_meals": actuals,
		"totals": {
			code: {key: _text(value) for key, value in row.items()} for code, row in facts["totals"].items()
		},
		"stock_ledger": facts["stock_ledger"],
		"opening_day": facts.get("opening_day"),
		"opening_sources": facts.get("opening_sources", []),
		"carry_out_sources": _carry_sources(facts, day.meal_week),
		"carry_confirmation": carry_proof if positive else None,
		"stock_entries": [
			{
				"name": entry.name,
				"action": entry.custom_meal_action,
				"owner": entry.owner,
				"last_actor": entry.modified_by,
			}
			for entry in facts["entries"]
		],
	}
	return proof


def before_submit_day(doc, method=None):
	_role(manager=True)
	if doc.owner == frappe.session.user:
		_fail("厨房日结必须由其他授权审核人批准，经办人不能自行日结。", permission=True)
	week = _week(doc.meal_week, lock=True)
	frappe.db.sql("SELECT name FROM `tabMeal Kitchen Day` WHERE name=%s FOR UPDATE", (doc.name,))
	_check_execution_order(doc)
	facts = _ledger(doc, lock=True, verify_sle=True)
	_assert_actual_kitchen_stock(doc, facts)
	positive, _, _, carry_proof = _carry_confirmation(doc, facts)
	if positive and carry_proof.get("confirmed_by") == frappe.session.user:
		_fail("留存实盘确认人与日结审核人必须不同。", permission=True)
	_day_execution(doc, lock=True)
	for plan in _day_plans(week, doc.meal_date, lock=True):
		plan.check_permission("write")
		_no_work_orders(plan, lock=True)
	doc.approved_by = frappe.session.user
	doc.approved_at = now_datetime()


def on_submit_day(doc, method=None):
	proof = _day_execution(doc, lock=True)
	closed = [
		_native_close(plan) for plan in _day_plans(_week(doc.meal_week, lock=True), doc.meal_date, lock=True)
	]
	proof["closed_plans"] = sorted(closed)
	proof["ledger_hash"] = _hash(proof)
	doc.db_set({"execution_snapshot": frappe.as_json(proof), "status": "已日结"}, update_modified=False)


def before_cancel_day(doc, method=None):
	_role(manager=True)
	old = doc.get_doc_before_save()
	if old:
		for field in (*_DAY_PROTECTED, "kitchen_warehouse"):
			if str(doc.get(field) or "") != str(old.get(field) or ""):
				_fail("取消日结时不能更换业务来源、实际仓库或审批依据。")
		if _day_business_signature(doc) != _day_business_signature(old):
			_fail("取消日结时不能改写已批准的实际人数或食材计划。")
	if _week(doc.meal_week, lock=True).get("kitchen_reconciled"):
		_fail("该日已纳入有效周结，须先按正式周结更正流程处理。")
	_check_execution_order(doc)
	if frappe.db.sql(
		"SELECT u.name FROM `tabStock Entry Detail` u JOIN `tabStock Entry` s ON s.name=u.parent "
		"JOIN `tabStock Entry Detail` original ON original.name=u.custom_meal_issue_detail "
		"JOIN `tabStock Entry` source ON source.name=original.parent "
		"WHERE source.custom_meal_kitchen_day=%s AND s.custom_meal_kitchen_day<>%s "
		"AND s.docstatus<2 LIMIT 1 FOR UPDATE",
		(doc.name, doc.name),
	):
		_fail("本日领用已有后日使用或草稿引用，不能取消日结。")
	doc.active_day_key = None
	doc.status = "已取消"
	# Do not reopen native plans or reverse stock automatically. Native stock
	# cancellation is a separate, explicitly authorized correction operation.


def _day_business_signature(doc):
	return {
		"meals": sorted(
			[
				{
					key: str(row.get(key) or "")
					for key in (
						"meal_type",
						"planned_headcount",
						"actual_headcount",
						"actual_confirmed",
						"reason",
					)
				}
				for row in doc.meals
			],
			key=lambda row: row["meal_type"],
		),
		"items": _item_signature(doc.items),
		"carry_notes": str(doc.get("carry_notes") or "").strip(),
	}


def before_update_after_submit_day(doc, method=None):
	if not _MANAGED.get():
		_fail("已日结的实际人数、审批和核销依据已冻结，请按正式更正流程处理。")


def _verified_day(day, lock=False):
	if day.docstatus != 1:
		_fail("周结需要五个已审核的真实厨房日结。")
	if not day.approved_by or not day.approved_at or day.approved_by == day.owner:
		_fail("厨房日结缺少经办与审核分离的真实审批依据。")
	proof = _day_execution(day, lock=lock)
	plans = _day_plans(_week(day.meal_week, lock=lock), day.meal_date, lock=lock)
	if any(plan.status not in ("Closed", "Completed") for plan in plans):
		_fail("厨房日结对应生产计划尚未通过官方关闭释放保留量。")
	proof["closed_plans"] = sorted(plan.name for plan in plans)
	proof["ledger_hash"] = _hash(proof)
	stored = _json(day.execution_snapshot)
	if stored != proof:
		_fail("日结实际人数、库存流水或关闭来源与冻结依据不一致。")
	return {"name": day.name, "meal_date": proof["meal_date"], "ledger_hash": proof["ledger_hash"]}


def _week_execution(week, lock=False):
	from tongjianyun.meal_adjustments import get_effective_meals

	expected = {_date(row.meal_date) for row in get_effective_meals(week, lock=lock) if not row.service_suspended}
	if max(expected, default=_date(week.week_start)) > _date(today()):
		_fail("未来食谱周不能提前完成厨房周结。")
	if frappe.db.sql(
		"SELECT s.name FROM `tabStock Entry` s JOIN `tabMeal Kitchen Day` d "
		"ON d.name=s.custom_meal_kitchen_day WHERE d.meal_week=%s "
		"AND d.docstatus<>1 AND s.docstatus=1 LIMIT 1" + (" FOR UPDATE" if lock else ""),
		(week.name,),
	):
		_fail("本周有未纳入有效日结的实际库存流水，请先完成更正或日结。")
	names = (
		[
			row.name
			for row in frappe.db.sql(
				"SELECT name FROM `tabMeal Kitchen Day` WHERE meal_week=%s AND docstatus=1 ORDER BY name FOR UPDATE",
				(week.name,),
				as_dict=True,
			)
		]
		if lock
		else frappe.get_all(
			"Meal Kitchen Day",
			filters={"meal_week": week.name, "docstatus": 1},
			pluck="name",
			order_by="name asc",
			limit_page_length=0,
		)
	)
	days = [frappe.get_doc("Meal Kitchen Day", name, for_update=lock) for name in names]
	actual = {_date(day.meal_date) for day in days}
	if (len(actual) != len(days) or not expected.issubset(actual)
		or any(not _date(week.week_start) <= day <= _date(week.week_end) for day in actual)):
		_fail("本周每个实际供餐日必须有一条已审核的厨房日结。")
	proofs = [_verified_day(day, lock=lock) for day in sorted(days, key=lambda day: _date(day.meal_date))]
	plans = _day_plans(week, lock=lock)
	if any(plan.status not in ("Closed", "Completed") for plan in plans):
		_fail("本周仍有未关闭的原餐次或调整替换生产计划。")
	last_day = max(days, key=lambda day: _date(day.meal_date), default=None)
	return {
		"week_name": week.name,
		"days": proofs,
		"closed_plans": sorted(plan.name for plan in plans),
		"carry_out_sources": _json(last_day.execution_snapshot).get("carry_out_sources", []) if last_day else [],
	}


def _procurement_proof(week, lock=True):
	from tongjianyun.meal_purchasing import verify_week_procurement_settled

	proof = verify_week_procurement_settled(week, lock=lock)
	if not isinstance(proof, dict) or not proof.get("settled"):
		_fail("本周采购来源仍未结清，不能释放跨周库存承诺。")
	return {key: value for key, value in proof.items() if key != "checked_at"}


@frappe.whitelist(methods=["POST"])
def reconcile_kitchen_week(week_name):
	_role(manager=True)
	week = _week(week_name, lock=True)
	if week.get("kitchen_reconciled"):
		return verify_week_kitchen_reconciled(week)
	proof = _week_execution(week, lock=True)
	proof["procurement"] = _procurement_proof(week)
	proof["basis_hash"] = _hash(proof)
	week.db_set(
		{
			"kitchen_reconciled": 1,
			"kitchen_reconciled_at": now_datetime(),
			"kitchen_reconciliation_snapshot": frappe.as_json(proof),
			"status": "已核销",
		},
		update_modified=False,
	)
	return {"reconciled": True, **proof}


def verify_week_kitchen_reconciled(week, lock=True):
	"""Revalidate real evidence before another week can reuse stock; no writes."""
	week = _week(week, lock=lock)
	if not week.get("kitchen_reconciled") or not week.get("kitchen_reconciled_at"):
		_fail("本周尚未完成有实际执行依据的厨房周结。")
	proof = _week_execution(week, lock=lock)
	proof["procurement"] = _procurement_proof(week, lock=lock)
	proof["basis_hash"] = _hash(proof)
	if _json(week.get("kitchen_reconciliation_snapshot")) != proof:
		_fail("周结冻结依据与实际日结、库存或采购来源不一致。")
	return {"reconciled": True, **proof, "checked_at": str(now_datetime())}
