"""Confirm the human-defined recipe weight basis without inventing yield factors."""
# ruff: noqa: RUF001

from collections import defaultdict
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import now_datetime


def _number(value):
	try:
		number = Decimal(str(value or 0))
	except InvalidOperation, TypeError, ValueError:
		frappe.throw(_("食材数量无效。"))
	if not number.is_finite():
		frappe.throw(_("食材数量必须是有限数值。"))
	return number


@frappe.whitelist(methods=["POST"])
def confirm_requirement_weight_basis(week_name, basis="采购毛重"):
	from tongjianyun.meal_planning import _digest, _json, _week

	week = _week(week_name)
	if not {"System Manager", "Purchase Manager"}.intersection(frappe.get_roles()):
		frappe.throw(_("需要采购负责人确认原食谱计量口径。"), frappe.PermissionError)
	if basis != "采购毛重":
		frappe.throw(_("本阶段仅接受已确认的清洗去皮前采购毛重；不自动推断净料率。"))
	if week.docstatus == 2 or week.get("kitchen_reconciled"):
		frappe.throw(_("已取消或已核销周不能重新确认计量口径。"))
	frappe.db.sql("SELECT name FROM `tabMeal Planning Week` WHERE name=%s FOR UPDATE", (week.name,))
	week.reload()
	if week.docstatus == 2 or week.get("kitchen_reconciled"):
		frappe.throw(_("已取消或已核销周不能重新确认计量口径。"))
	population = _json(week.population_snapshot)
	if len(week.meals) != 25 or len(population.get("recipe_hashes", {})) != 25:
		frappe.throw(_("请先完整初始化本周25个餐次，再确认食谱重量口径。"))
	previous = _json(week.get("requirement_weight_snapshot"))
	if previous:
		verify_purchase_weight_basis(week)
		return {"name": week.name, "basis": basis, "already_confirmed": True}
	proof = {
		"version": 1,
		"week": week.name,
		"company": week.company,
		"basis": basis,
		"meaning": "清洗去皮前毛重；现有配方数量不再增加清洗去皮损耗",
		"confirmed_by": frappe.session.user,
		"confirmed_at": str(now_datetime()),
		"baseline_recipe_hashes": population.get("recipe_hashes", {}),
	}
	proof["proof_hash"] = _digest(proof)
	week.db_set(
		{"requirement_weight_basis": basis, "requirement_weight_snapshot": frappe.as_json(proof)},
		update_modified=True,
	)
	return {"name": week.name, "basis": basis, "already_confirmed": False}


def verify_purchase_weight_basis(week, material_requests=None):
	"""Validate a controlled gross-weight acknowledgement and native demand sources."""
	from tongjianyun.meal_adjustments import get_effective_meals
	from tongjianyun.meal_planning import _digest, _json, _recipe_signature

	if isinstance(week, str):
		week = frappe.get_doc("Meal Planning Week", week)
	week.check_permission("read")
	proof = _json(week.get("requirement_weight_snapshot"))
	claimed_hash = proof.get("proof_hash")
	content = {key: value for key, value in proof.items() if key != "proof_hash"}
	if (
		week.get("requirement_weight_basis") != "采购毛重"
		or proof.get("basis") != "采购毛重"
		or proof.get("week") != week.name
		or proof.get("company") != week.company
		or not proof.get("confirmed_by")
		or claimed_hash != _digest(content)
	):
		frappe.throw(_("请先由采购负责人确认原表采用清洗去皮前毛重。"))
	baseline = _json(week.population_snapshot).get("recipe_hashes", {})
	if proof.get("baseline_recipe_hashes") != baseline:
		frappe.throw(_("配方基线已变化，请重新核对采购计量口径。"))
	for meal in get_effective_meals(week):
		if meal.get("service_suspended") or not meal.planned_headcount:
			continue
		plan = frappe.get_doc("Production Plan", meal.production_plan)
		if _recipe_signature(plan) != meal.get("recipe_hash"):
			frappe.throw(_("当前菜品配方与已确认计量依据不一致。"))
	# Compare the source plan's frozen gross requirement, not purchase quantity:
	# purchase quantity legitimately excludes existing stock and committed supply.
	validated_plans = set()
	for request in material_requests or []:
		request = frappe.get_doc("Material Request", request) if isinstance(request, str) else request
		if request.company != week.company:
			frappe.throw(_("采购申请所属园所与计量确认不一致。"))
		for line in request.items:
			plan = frappe.get_doc("Production Plan", line.production_plan)
			if plan.get("custom_meal_week") != week.name:
				frappe.throw(_("采购申请包含不属于本周的生产计划。"))
			source = next((row for row in plan.mr_items if row.name == line.material_request_plan_item), None)
			if not source or source.item_code != line.item_code:
				frappe.throw(_("采购申请原料来源缺失。"))
			if plan.name in validated_plans:
				continue
			if plan.get("custom_meal_adjustment"):
				adjustment = frappe.get_doc("Meal Plan Adjustment", plan.custom_meal_adjustment)
				frozen = _json(adjustment.applied_snapshot).get("requirements", [])
				if adjustment.docstatus != 1 or adjustment.meal_week != week.name:
					frappe.throw(_("调整采购尚未完成审核。"))
			else:
				frozen = _json(week.procurement_snapshot).get("rows", [])
			expected, actual = defaultdict(Decimal), defaultdict(Decimal)
			for row in frozen:
				if row.get("production_plan") == plan.name:
					expected[(row["item_code"], row["warehouse"])] += _number(row.get("required_qty"))
			for row in plan.mr_items:
				actual[(row.item_code, row.warehouse)] += _number(row.required_bom_qty)
			if not expected or dict(expected) != dict(actual):
				frappe.throw(_("原生生产计划食材数量与确认的毛重需求不一致。"))
			validated_plans.add(plan.name)
	return {"confirmed": True, "basis": "采购毛重", "proof_hash": claimed_hash}
