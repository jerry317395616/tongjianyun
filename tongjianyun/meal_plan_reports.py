"""Permission-checked, read-only per-child views of unbound meal plans."""
# ruff: noqa: RUF001

from datetime import timedelta
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import getdate

SLOTS = ("早餐", "早点", "午餐", "午点", "晚餐")


def _fail(message):
	frappe.throw(_(message))


def _positive(value):
	try:
		number = Decimal(str(value))
	except (InvalidOperation, ValueError, TypeError):
		_fail("历史配方数量无效，请核对生产计划及物料清单。")
	if not number.is_finite() or number <= 0:
		_fail("历史配方数量必须为正数。")
	return number


def plan_details(plan):
	"""Read only the selected plan's recipe; its basis quantity is not attendance."""
	plan.check_permission("read")
	if plan.docstatus not in (0, 1) or not plan.get("custom_is_meal_plan") or plan.get("custom_meal_week"):
		_fail("请选择未关联正式周计划的有效食谱；已编排餐次请通过周计划查看。")
	if plan.custom_meal_type not in SLOTS or not plan.po_items:
		_fail("历史生产计划缺少有效餐次或配方。")
	data = []
	for dish in plan.po_items:
		bom = frappe.get_doc("BOM", dish.bom_no)
		bom.check_permission("read")
		if (
			bom.docstatus != 1
			or not bom.is_active
			or bom.company != plan.company
			or bom.item != dish.item_code
			or _positive(bom.quantity) != 1
		):
			_fail("历史食谱须使用本园所已提交、有效、每名幼儿为基准的配方。")
		item = frappe.get_doc("Item", dish.item_code)
		item.check_permission("read")
		if item.disabled or item.is_purchase_item:
			_fail("历史餐次组合物料已停用或不属于配方菜品。")
		for ingredient in bom.items:
			raw = frappe.get_doc("Item", ingredient.item_code)
			raw.check_permission("read")
			quantity = _positive(ingredient.qty) / _positive(bom.quantity)
			data.append(
				{
					"week_name": None,
					"plan_batch": plan.custom_meal_batch,
					"source_kind": "production_plans",
					"meal_date": str(getdate(plan.custom_meal_date)),
					"meal_type": plan.custom_meal_type,
					"dish_name": item.item_name,
					"ingredient_code": ingredient.item_code,
					"ingredient_name": raw.item_name,
					"per_child_qty": float(quantity),
					"uom": ingredient.uom,
					"headcount": None,
					"total_qty": None,
					"plan_name": plan.name,
					"bom_no": bom.name,
				}
			)
	return data


def resolve_report_filters(filters):
	"""Resolve a date-only report link without guessing among visible schedules."""
	filters = frappe._dict(filters or {})
	if filters.get("week_name") or filters.get("plan_batch") or not filters.get("week_start"):
		return filters
	if frappe.session.user == "Guest":
		frappe.throw(_("请先登录。"), frappe.AuthenticationError)
	start = getdate(filters.week_start)
	if start.weekday() != 0:
		_fail("请选择星期一作为周开始日期。")
	weeks = frappe.get_list(
		"Meal Planning Week", filters={"week_start": start, "docstatus": ["<", 2]},
		pluck="name", limit_page_length=2,
	)
	plans = frappe.get_list(
		"Production Plan", filters={"custom_meal_date": start, "custom_is_meal_plan": 1, "docstatus": ["<", 2]},
		fields=["custom_meal_batch", "custom_meal_week"], limit_page_length=26,
	)
	batches = {row.custom_meal_batch for row in plans if row.custom_meal_batch and not row.custom_meal_week}
	choices = [{"week_name": name} for name in weeks] + [{"plan_batch": batch} for batch in sorted(batches)]
	if not choices:
		_fail("所选周暂无可查看的食谱，请核对日期及查看权限。")
	if len(choices) != 1:
		_fail("所选周有多个可查看的食谱，请明确选择周食谱或生产计划批次。")
	filters.update(choices[0])
	return filters


def report_context(filters):
	"""A batch must contain one complete, readable five-day schedule."""
	if frappe.session.user == "Guest":
		frappe.throw(_("请先登录。"), frappe.AuthenticationError)
	filters = frappe._dict(filters or {})
	batch = filters.get("plan_batch")
	if not batch:
		return None
	if not isinstance(batch, str) or not batch.strip() or len(batch) > 140:
		_fail("请选择有效的生产计划批次。")
	if filters.get("week_name"):
		_fail("请选择周计划或生产计划批次中的一种。")
	visible = frappe.get_list(
		"Production Plan",
		filters={"custom_meal_batch": batch, "custom_is_meal_plan": 1, "docstatus": ["<", 2]},
		pluck="name",
		order_by="custom_meal_date asc, name asc",
		limit_page_length=26,
	)
	if not visible:
		frappe.throw(_("该批次没有可查看的历史生产计划。"), frappe.PermissionError)
	if len(visible) != 25:
		_fail("完整周表需要五天五餐，共25张可读取的有效生产计划。")
	plans = [frappe.get_doc("Production Plan", name) for name in visible]
	for plan in plans:
		plan.check_permission("read")
		if plan.get("custom_meal_week") or plan.docstatus not in (0, 1) or plan.custom_meal_batch != batch:
			_fail("历史报表不能代替正式周计划或读取不同批次的餐次。")
	if len({plan.company for plan in plans}) != 1:
		_fail("同一周表不能混合不同园所。")
	start = min(getdate(plan.custom_meal_date) for plan in plans)
	if start.weekday() != 0:
		_fail("历史周表的开始日期必须是星期一。")
	if filters.get("week_start") and getdate(filters.week_start) != start:
		_fail("所选周开始日期与生产计划批次不一致。")
	dates = [start + timedelta(days=index) for index in range(5)]
	by_meal = {(getdate(plan.custom_meal_date), plan.custom_meal_type): plan for plan in plans}
	if len(by_meal) != 25 or set(by_meal) != {(date, slot) for date in dates for slot in SLOTS}:
		_fail("历史生产计划存在重复或遗漏的日期、餐次。")
	details = [row for date in dates for slot in SLOTS for row in plan_details(by_meal[date, slot])]
	data = []
	for slot in SLOTS:
		for kind in ("菜品", "带量"):
			record = {
				"week_name": None,
				"plan_batch": batch,
				"week_start": str(start),
				"source_kind": "production_plans",
				"meal_type": slot,
				"row_kind": kind,
			}
			for index, date in enumerate(dates):
				plan = by_meal[date, slot]
				record.update({f"date_{index}": str(date), f"plan_{index}": plan.name, f"headcount_{index}": None})
				if kind == "菜品":
					record[f"day_{index}"] = plan.custom_meal_menu or "、".join(
						frappe.get_doc("Item", line.item_code).item_name for line in plan.po_items
					)
				else:
					quantities = {}
					for row in details:
						if row["plan_name"] == plan.name:
							key = (row["ingredient_code"], row["ingredient_name"], row["uom"])
							quantities[key] = quantities.get(key, Decimal(0)) + Decimal(str(row["per_child_qty"]))
					labels = {"Millilitre": "ml", "Gram": "g"}
					record[f"day_{index}"] = "；".join(
						f"{name}{quantity.normalize():f}{labels.get(uom, uom)}"
						for (_code, name, uom), quantity in quantities.items()
					)
			data.append(record)
	return {"dates": dates, "details": details, "rows": data}
