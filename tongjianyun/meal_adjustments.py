"""Future, unexecuted meal revisions that preserve native purchasing history."""
# ruff: noqa: RUF001

from contextlib import contextmanager
from contextvars import ContextVar
from copy import copy
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, getdate, now_datetime, today

_MANAGED = ContextVar("meal_adjustment_managed", default=False)
_APPLYING = ContextVar("meal_adjustment_applying", default=None)
_SOURCE = ("meal_week", "meal_date", "meal_type", "source_plan", "source_adjustment", "source_snapshot")
_RESULT = ("replacement_plan", "material_request", "applied_snapshot", "purchase_change_summary")


@contextmanager
def _managed():
	token = _MANAGED.set(True)
	try:
		yield
	finally:
		_MANAGED.reset(token)


def _fail(message, permission=False):
	frappe.throw(_(message), frappe.PermissionError if permission else frappe.ValidationError)


def _week(value, lock=False):
	from tongjianyun.meal_planning import _week as load

	doc = load(value) if isinstance(value, str) else value
	doc.check_permission("read")
	if lock:
		from tongjianyun.meal_stock_claims import lock_claim_scope

		lock_claim_scope(doc.company)
		doc = frappe.get_doc("Meal Planning Week", doc.name, for_update=True)
		doc.check_permission("read")
	return doc


def _state(meal):
	return {
		"meal_date": str(getdate(meal.meal_date)),
		"meal_type": meal.meal_type,
		"production_plan": meal.get("production_plan"),
		"adjustment": meal.get("adjustment"),
		"planned_headcount": cint(meal.planned_headcount),
		"service_suspended": cint(meal.get("service_suspended")),
		"menu": meal.get("menu"),
		"recipe_hash": meal.get("recipe_hash"),
	}


def _same_creation(left, right):
	try:
		return (get_datetime(left) if left else None) == (get_datetime(right) if right else None)
	except TypeError, ValueError:
		return False


def get_effective_meals(week, lock=False):
	"""Return effective meals; mutations use current reads after locking the week.

	Under MariaDB REPEATABLE READ, a plain query keeps an earlier transaction
	snapshot even after waiting for the week row lock. The approved revision
	chain must therefore use a locking current read on execution paths too.
	Read-only reports keep their ordinary consistent snapshot without locks.
	"""
	from tongjianyun.meal_planning import _json

	week = _week(week, lock=lock)
	population = _json(week.population_snapshot)
	procurement = _json(week.procurement_snapshot)
	rows = {}
	for original in week.meals:
		row = frappe._dict(original.as_dict() if hasattr(original, "as_dict") else dict(original))
		row.recipe_hash = population.get("recipe_hashes", {}).get(row.production_plan)
		row.frozen_requirements = [
			r for r in procurement.get("rows", []) if r.get("production_plan") == row.production_plan
		]
		row.adjustment = None
		rows[(str(getdate(row.meal_date)), row.meal_type)] = row
	if not frappe.db.exists("DocType", "Meal Plan Adjustment"):
		return list(rows.values())
	if lock:
		revisions = frappe.db.sql(
			"""SELECT name,meal_date,meal_type,applied_snapshot
			FROM `tabMeal Plan Adjustment`
			WHERE meal_week=%s AND docstatus=1 ORDER BY creation,name FOR UPDATE""",
			(week.name,),
			as_dict=True,
		)
	else:
		revisions = frappe.get_all(
			"Meal Plan Adjustment",
			filters={"meal_week": week.name, "docstatus": 1},
			fields=["name", "meal_date", "meal_type", "applied_snapshot"],
			order_by="creation asc, name asc",
		)
	for revision in revisions:
		if revision.name == _APPLYING.get():
			continue
		proof = _json(revision.applied_snapshot)
		if not proof or proof.get("week") != week.name or proof.get("adjustment") != revision.name:
			_fail("已审核单餐变更缺少应用依据，请核对记录。")
		key = (str(getdate(revision.meal_date)), revision.meal_type)
		if key not in rows or proof.get("source") != _state(rows[key]):
			_fail("单餐变更来源链不连续，请核对已审核记录。")
		row = frappe._dict(rows[key].copy())
		row.update(proof["effective_meal"])
		row.adjustment = revision.name
		row.frozen_requirements = proof.get("requirements", [])
		rows[key] = row
	return list(rows.values())


def _current(doc, lock=False):
	week = _week(doc.meal_week, lock=lock)
	if week.docstatus != 1 or week.get("kitchen_reconciled"):
		_fail("只能变更尚未核销的已审核周食谱。")
	if getdate(doc.meal_date) < getdate(today()):
		_fail("不能改写过去日期的食谱，请保留已发生的业务事实。")
	if not getdate(week.week_start) <= getdate(doc.meal_date) <= getdate(week.week_end):
		_fail("变更日期不在该食谱周内。")
	if lock:
		closed_day = frappe.db.sql(
			"SELECT name FROM `tabMeal Kitchen Day` WHERE meal_week=%s AND meal_date=%s "
			"AND docstatus=1 LIMIT 1 FOR UPDATE",
			(week.name, doc.meal_date),
		)
	else:
		closed_day = frappe.db.exists(
			"Meal Kitchen Day", {"meal_week": week.name, "meal_date": doc.meal_date, "docstatus": 1}
		)
	executed = frappe.db.sql(
		"SELECT s.name FROM `tabStock Entry` s JOIN `tabMeal Kitchen Day` d ON d.name=s.custom_meal_kitchen_day "
		"WHERE d.meal_week=%s AND d.meal_date=%s AND s.docstatus=1 LIMIT 1" + (" FOR UPDATE" if lock else ""),
		(week.name, doc.meal_date),
	)
	if closed_day:
		_fail("该日已经完成厨房日结，不能改写计划。")
	if executed:
		_fail("该日已有实际厨房出入库，请先按实际业务处理，不能覆盖计划。")
	meal = next(
		(
			row
			for row in get_effective_meals(week, lock=lock)
			if getdate(row.meal_date) == getdate(doc.meal_date) and row.meal_type == doc.meal_type
		),
		None,
	)
	if not meal:
		_fail("没有找到本周对应餐次。")
	return week, meal


@frappe.whitelist(methods=["POST"])
def create_adjustment(week_name, meal_date, meal_type):
	from tongjianyun.meal_planning import _planner

	week = _week(week_name)
	_planner(week)
	if not frappe.has_permission("Meal Plan Adjustment", "create"):
		_fail("没有发起单餐变更的权限。", permission=True)
	probe = frappe._dict(meal_week=week.name, meal_date=meal_date, meal_type=meal_type)
	week, meal = _current(probe)
	plan = frappe.get_doc("Production Plan", meal.production_plan) if meal.production_plan else None
	values = {
		"doctype": "Meal Plan Adjustment",
		"meal_week": week.name,
		"meal_date": meal_date,
		"meal_type": meal_type,
		"reason": "待填写变更原因",
		"target_headcount": meal.planned_headcount,
		"service_suspended": cint(meal.get("service_suspended")),
		"source_plan": meal.get("production_plan"),
		"source_adjustment": meal.get("adjustment"),
		"source_snapshot": frappe.as_json(_state(meal)),
		"dishes": [{"bom_no": row.bom_no} for row in plan.po_items] if plan else [],
	}
	with _managed():
		doc = frappe.get_doc(values).insert()
	return {"name": doc.name}


def validate_adjustment(doc, lock=False):
	from tongjianyun.meal_planning import _json

	old = doc.get_doc_before_save()
	if old and doc.owner != old.owner:
		_fail("单餐变更经办人不能更换；请保留原创建人和审核记录。", permission=True)
	if old and not _same_creation(doc.creation, old.creation):
		_fail("单餐变更创建时间决定来源回放顺序，不能更改。", permission=True)
	if not _MANAGED.get():
		if doc.is_new():
			_fail("请从已审核周食谱发起单餐变更。")
		if old and any(str(doc.get(key) or "") != str(old.get(key) or "") for key in _SOURCE + _RESULT):
			_fail("来源餐次及应用结果由系统维护，不能手工改写。")
	if doc.docstatus == 2:
		return
	week, meal = _current(doc, lock=lock)
	if _json(doc.source_snapshot) != _state(meal):
		_fail("申请期间该餐已被其他变更更新，请重新发起申请。")
	try:
		count = Decimal(str(doc.target_headcount or 0))
	except Exception:
		_fail("目标人数必须是非负整数。")
	if not count.is_finite() or count != count.to_integral_value() or count < 0:
		_fail("目标人数必须是非负整数。")
	if bool(count == 0) != bool(doc.service_suspended):
		_fail("零人数必须明确整餐停供；正常供餐必须填写正数人数。")
	if not str(doc.reason or "").strip():
		_fail("请填写单餐变更原因。")
	if not doc.service_suspended:
		boms = [row.bom_no for row in doc.dishes]
		if not boms or len(boms) > 20 or len(set(boms)) != len(boms):
			_fail("请选择1至20个不重复的菜品配方。")
		for name in boms:
			bom = frappe.get_doc("BOM", name, for_update=lock)
			bom.check_permission("read")
			item = frappe.get_cached_doc("Item", bom.item)
			if (
				bom.docstatus != 1
				or not bom.is_active
				or Decimal(str(bom.quantity)) != 1
				or bom.company != week.company
				or item.disabled
				or item.is_purchase_item
			):
				_fail("变更菜品必须是本园所启用、已提交、每名幼儿为基准的自制配方。")


def before_submit_adjustment(doc):
	if not {"System Manager", "食谱审核员"}.intersection(frappe.get_roles()):
		_fail("需要食谱审核权限。", permission=True)
	from tongjianyun.meal_stock_claims import lock_claim_scope

	lock_claim_scope(_week(doc.meal_week).company)
	original_owner = frappe.db.get_value("Meal Plan Adjustment", doc.name, "owner", for_update=True)
	if not original_owner or doc.owner != original_owner:
		_fail("单餐变更经办人与原始创建记录不一致，不能审核。", permission=True)
	if original_owner == frappe.session.user:
		_fail("变更经办人与审核人必须不同。", permission=True)
	original_creation = frappe.db.get_value("Meal Plan Adjustment", doc.name, "creation", for_update=True)
	if not original_creation or not _same_creation(doc.creation, original_creation):
		_fail("单餐变更创建时间与原始记录不一致，不能审核。", permission=True)
	if str(doc.reason or "").strip() == "待填写变更原因" or not str(doc.review_notes or "").strip():
		_fail("请填写真实变更原因和审核意见。")
	frappe.db.sql("SELECT name FROM `tabMeal Planning Week` WHERE name=%s FOR UPDATE", (doc.meal_week,))
	validate_adjustment(doc, lock=True)
	from tongjianyun.meal_weights import verify_purchase_weight_basis

	verify_purchase_weight_basis(doc.meal_week)


def _share_replacement(week, plan, owner):
	users = {owner}
	users.update(
		frappe.get_all(
			"DocShare",
			filters={"share_doctype": "Meal Planning Week", "share_name": week.name, "read": 1},
			pluck="user",
		)
	)
	for user in users - {None, "", "Guest", "Administrator"}:
		frappe.share.add(
			"Production Plan",
			plan.name,
			user,
			read=1,
			write=0,
			submit=0,
			share=0,
			notify=0,
			flags={"ignore_share_permission": True},
		)
		if frappe.db.exists(
			"User Permission", {"user": user, "allow": "Production Plan"}
		) and not frappe.db.exists(
			"User Permission", {"user": user, "allow": "Production Plan", "for_value": plan.name}
		):
			frappe.get_doc(
				{
					"doctype": "User Permission",
					"user": user,
					"allow": "Production Plan",
					"for_value": plan.name,
					"applicable_for": "Production Plan",
					"apply_to_all_doctypes": 0,
				}
			).insert(ignore_permissions=True)


def _replacement(doc, week, old_plan):
	from tongjianyun.meal_planning import _digest, _plan_values, _recipe_signature
	from tongjianyun.meal_planning import _managed as plan_managed

	if doc.service_suspended:
		return None
	if not old_plan:
		_fail("恢复供餐时缺少可追溯的原配方计划。")
	values = _plan_values(week, old_plan, getdate(doc.meal_date), doc.meal_type, cint(doc.target_headcount))
	values["custom_meal_adjustment"] = doc.name
	values["po_items"] = []
	warehouse = old_plan.po_items[0].warehouse
	for chosen in doc.dishes:
		bom = frappe.get_doc("BOM", chosen.bom_no)
		item = frappe.get_cached_doc("Item", bom.item)
		values["po_items"].append(
			{
				"item_code": item.name,
				"bom_no": bom.name,
				"planned_qty": cint(doc.target_headcount),
				"stock_uom": item.stock_uom,
				"planned_start_date": f"{getdate(doc.meal_date)} 00:00:00",
				"warehouse": warehouse,
				"custom_dish_name": item.item_name,
				"description": item.description or item.item_name,
			}
		)
	values["custom_meal_menu"] = "、".join(row["custom_dish_name"] for row in values["po_items"])
	values["custom_meal_title"] = f"{doc.meal_type}｜{values['custom_meal_menu']}"[:140]
	with plan_managed():
		plan = frappe.get_doc(values).insert(
			ignore_permissions=True, set_name=f"MEAL-CHANGE-{_digest([doc.name])[:16].upper()}"
		)
	_recipe_signature(plan)
	_share_replacement(week, plan, doc.owner)
	return plan


def _changed_quantities(before, after):
	def aggregate(rows):
		result = {}
		for row in rows:
			if row.get("policy") == "厨房用水":
				continue
			key = (row["item_code"], row["warehouse"], row["stock_uom"])
			result[key] = result.get(key, Decimal(0)) + Decimal(str(row["required_qty"]))
		return result

	old, new = aggregate(before), aggregate(after)
	return [
		{
			"item_code": key[0],
			"warehouse": key[1],
			"uom": key[2],
			"old_gross_qty": str(old.get(key, 0)),
			"new_gross_qty": str(new.get(key, 0)),
			"gross_difference": str(new.get(key, Decimal(0)) - old.get(key, Decimal(0))),
		}
		for key in sorted(set(old) | set(new))
		if old.get(key, 0) != new.get(key, 0)
	]


def on_submit_adjustment(doc):
	from tongjianyun.meal_kitchen import close_meal_plan
	from tongjianyun.meal_planning import _managed as plan_managed
	from tongjianyun.meal_planning import _recipe_signature
	from tongjianyun.meal_procurement import prepare_adjustment_procurement

	token = _APPLYING.set(doc.name)
	try:
		week, original = _current(doc, lock=True)
		original_state = _state(original)
		old_plan = (
			frappe.get_doc("Production Plan", original.production_plan, for_update=True)
			if original.production_plan
			else None
		)
		if old_plan and old_plan.docstatus == 1 and old_plan.status not in ("Closed", "Completed"):
			close_meal_plan(old_plan)
		plan = _replacement(doc, week, old_plan)
		revised = frappe._dict(original.copy())
		revised.update(
			planned_headcount=cint(doc.target_headcount),
			service_suspended=cint(doc.service_suspended),
			suspension_reason=doc.reason if doc.service_suspended else None,
			production_plan=plan.name if plan else original.production_plan,
			menu=plan.custom_meal_menu if plan else original.menu,
			recipe_hash=_recipe_signature(plan) if plan else original.get("recipe_hash"),
			adjustment=doc.name,
		)
		meals = get_effective_meals(week, lock=True)
		meals = [
			revised
			if getdate(row.meal_date) == getdate(doc.meal_date) and row.meal_type == doc.meal_type
			else row
			for row in meals
		]
		closed_days = set(
			map(
				str,
				frappe.get_all(
					"Meal Kitchen Day", filters={"meal_week": week.name, "docstatus": 1}, pluck="meal_date"
				),
			)
		)
		proxy = copy(week)
		proxy.meals = [row for row in meals if str(getdate(row.meal_date)) not in closed_days]
		proxy.material_request = None
		prepared = prepare_adjustment_procurement(proxy)
		if prepared.get("blockers"):
			_fail("；".join(map(str, prepared["blockers"])))
		requirements = [
			row for row in prepared["snapshot"]["rows"] if plan and row["production_plan"] == plan.name
		]
		if plan:
			from tongjianyun.meal_native_reservations import ensure_current_native_reservation_inputs

			with plan_managed():
				plan.set("mr_items", prepared["plans"].get(plan.name, []))
				plan.save(ignore_permissions=True)
				plan.flags.ignore_permissions = True
				ensure_current_native_reservation_inputs(plan.company)
				plan.submit()
		proof = {
			"version": 1,
			"week": week.name,
			"adjustment": doc.name,
			"source": original_state,
			"effective_meal": _state(revised),
			"requirements": requirements,
			"weight_basis": "采购毛重",
			"approved_by": frappe.session.user,
			"approved_at": str(now_datetime()),
			"quantity_changes": _changed_quantities(original.get("frozen_requirements", []), requirements),
			"procurement_warnings": prepared.get("warnings", []),
		}
		doc.applied_snapshot = frappe.as_json(proof)
		doc.replacement_plan = plan.name if plan else None
		doc.db_set(
			{"applied_snapshot": doc.applied_snapshot, "replacement_plan": doc.replacement_plan},
			update_modified=False,
		)
		request = None
		if plan:
			purchasable = [
				row
				for row in requirements
				if row["status"] == "purchase" and Decimal(str(row["purchase_qty"])) > 0
			]
			if purchasable:
				request = _create_delta_request(doc, week, plan, requirements)
		doc.material_request = request.name if request else None
		doc.purchase_change_summary = frappe.as_json(
			{
				"quantity_changes": proof["quantity_changes"],
				"additional_request": doc.material_request,
				"handling": "补采申请仅为草稿；原申请、订单和收货保留。负差额由采购人员核对未执行申请/订单后减量或关闭，已到货保持库存，退货另按真实业务办理。",
				"warnings": prepared.get("warnings", []),
			}
		)
		doc.db_set(
			{
				"material_request": doc.material_request,
				"purchase_change_summary": doc.purchase_change_summary,
			},
			update_modified=False,
		)
		week.add_comment(
			"Info",
			f"单餐变更 {doc.name} 已审核：{doc.meal_date} {doc.meal_type}，新计划人数 {doc.target_headcount}。原采购及收货记录保留。",
		)
	finally:
		_APPLYING.reset(token)


def _create_delta_request(adjustment, week, plan, rows):
	previous_user = frappe.session.user
	try:
		frappe.set_user(adjustment.owner)
		if not frappe.has_permission("Material Request", "create"):
			_fail("变更经办人没有采购申请草稿权限，请配置岗位后再审核。", permission=True)
		request = frappe.get_doc(
			{
				"doctype": "Material Request",
				"company": week.company,
				"material_request_type": "Purchase",
				"transaction_date": today(),
				"custom_meal_adjustment": adjustment.name,
				"items": [],
			}
		)
		for source, row in zip(plan.mr_items, rows, strict=True):
			if (
				source.item_code != row["item_code"]
				or source.warehouse != row["warehouse"]
				or Decimal(str(source.required_bom_qty)) != Decimal(row["required_qty"])
			):
				_fail("变更补采缺少原生生产计划来源。")
			if row["status"] != "purchase" or Decimal(row["purchase_qty"]) <= 0:
				continue
			request.append(
				"items",
				{
					"item_code": row["item_code"],
					"qty": float(Decimal(row["purchase_qty"])),
					"uom": row["purchase_uom"],
					"stock_uom": row["stock_uom"],
					"conversion_factor": float(Decimal(row["conversion_factor"])),
					"warehouse": row["warehouse"],
					"schedule_date": row["meal_date"],
					"production_plan": plan.name,
					"material_request_plan_item": source.name,
				},
			)
		request.run_method("set_missing_values")
		request.insert()
		return request
	finally:
		frappe.set_user(previous_user)


def before_cancel_adjustment(doc):
	_fail("已审核单餐变更会保留来源及采购事实；需要更正时请发起下一张变更，不取消历史。")


def before_update_after_submit_adjustment(doc):
	_fail("已审核单餐变更的来源及应用依据不能改写，请发起新的变更记录。")
