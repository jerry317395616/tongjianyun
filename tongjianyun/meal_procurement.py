"""Weekly meal procurement, backed by native Production Plan and Material Request.

The module allocates stock once across a week, freezes the calculation before
Production Plans are submitted, and creates one draft purchase request. It never
orders goods, records a receipt, changes stock, or commits a transaction.
"""
# ruff: noqa: RUF001

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from datetime import date, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation

import frappe
from frappe import _

WEEK_DOCTYPE = "Meal Planning Week"
POLICY_PURCHASE = "采购"
POLICY_WATER = "厨房用水"
POLICY_RECIPE = "厨房自产待配方"
ZERO = Decimal("0")


def _decimal(value) -> Decimal:
	try:
		result = Decimal(str(value if value is not None and value != "" else 0))
	except (InvalidOperation, TypeError, ValueError):
		frappe.throw(_("Invalid meal quantity: {0}").format(value))
	if not result.is_finite():
		frappe.throw(_("Meal quantities must be finite numbers."))
	return result


def _text(value: Decimal) -> str:
	return format(value.normalize(), "f") if value else "0"


def _date(value) -> date:
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	return date.fromisoformat(str(value)[:10])


def _today() -> date:
	from frappe.utils import today

	return _date(today())


def _quantity_precision() -> int:
	precision = frappe.get_precision("Material Request Plan Item", "quantity")
	return int(precision if precision is not None else 3)


def _purchase_quantity(stock_qty: Decimal, factor: Decimal, precision: int, whole=False) -> Decimal:
	"""Never round a positive shortage down to zero or below the stock requirement."""
	if stock_qty <= ZERO:
		return ZERO
	quantum = Decimal("1") if whole else Decimal(1).scaleb(-precision)
	return (stock_qty / factor).quantize(quantum, rounding=ROUND_CEILING)


def _hash(value) -> str:
	return hashlib.sha256(
		json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
	).hexdigest()


def _key(row):
	return (
		row.get("item_code"),
		row.get("warehouse"),
		row.get("uom"),
		row.get("from_bom") or "",
		row.get("main_item_code") or "",
	)


def _add_message(messages, message):
	if message not in messages:
		messages.append(message)


def _load_week(week_name):
	if not isinstance(week_name, str) or not week_name:
		frappe.throw(_("Please select a meal planning week."))
	week = frappe.get_doc(WEEK_DOCTYPE, week_name)
	week.check_permission("read")
	if week.docstatus == 2:
		frappe.throw(_("This meal planning week is cancelled."))
	return week


def _check_create_permission(week, plans):
	week.check_permission("read")
	roles = set(frappe.get_roles())
	if not {"System Manager", "Purchase Manager", "膳食业务经办员"}.intersection(roles):
		frappe.throw(
			_("Only a System Manager or Purchase Manager may create meal purchase requests."),
			frappe.PermissionError,
		)
	if not frappe.has_permission("Material Request", "create"):
		frappe.throw(
			_("You do not have permission to create purchase material requests."), frappe.PermissionError
		)
	for plan in plans:
		plan.check_permission("read" if "膳食业务经办员" in roles else "write")


def _verify_existing_request(week, existing, plans):
	"""A week link is not sufficient evidence that an arbitrary request belongs to it."""
	sources = {
		(name, source.name, source.item_code) for name, plan in plans.items() for source in plan.mr_items
	}
	if (
		existing.company != week.company
		or existing.material_request_type != "Purchase"
		or not existing.get("items")
		or any(
			(row.production_plan, row.material_request_plan_item, row.item_code) not in sources
			for row in existing.get("items")
		)
	):
		frappe.throw(
			_("The linked purchase request does not belong to this meal week's native source plans.")
		)


def _native_demands(week, *, for_update=False):
	"""Read native full-demand BOM expansion; never persist or invoke a create method."""
	from erpnext.manufacturing.doctype.production_plan.services.material_request import (
		get_items_for_material_requests,
	)

	plans = {}
	demands = []
	blockers = []
	seen_meals = set()
	start, end = _date(week.week_start), _date(week.week_end)
	if end < start:
		frappe.throw(_("The meal week end cannot precede its start."))
	if not week.meals:
		frappe.throw(_("The meal week has no meal plans."))
	for meal in sorted(week.meals, key=lambda row: (_date(row.meal_date), row.idx)):
		meal_date = _date(meal.meal_date)
		if not start <= meal_date <= end:
			frappe.throw(_("A meal date is outside the selected week."))
		meal_key = (meal_date, meal.meal_type)
		if meal_key in seen_meals:
			frappe.throw(_("A meal date and meal type cannot occur twice."))
		seen_meals.add(meal_key)
		headcount = _decimal(meal.planned_headcount)
		if meal.get("service_suspended") in (True, 1, "1"):
			if headcount != ZERO or not str(meal.get("suspension_reason") or "").strip():
				frappe.throw(_("A suspended meal needs zero headcount and an explicit suspension reason."))
			continue
		if headcount <= ZERO or headcount != headcount.to_integral_value():
			frappe.throw(_("Every meal must have a positive whole student headcount."))
		if not meal.production_plan:
			frappe.throw(_("Every meal must reference a Production Plan."))
		if meal.production_plan in plans:
			frappe.throw(_("A Production Plan cannot be assigned to more than one meal."))
		plan = frappe.get_doc("Production Plan", meal.production_plan, for_update=for_update)
		plan.check_permission("read")
		if plan.company != week.company or plan.docstatus == 2:
			frappe.throw(_("A meal Production Plan has an invalid company or is cancelled."))
		if not plan.po_items or any(_decimal(row.planned_qty) != headcount for row in plan.po_items):
			frappe.throw(
				_("Production Plan {0} does not match the meal's student headcount.").format(plan.name)
			)
		if plan.get("reserve_stock"):
			frappe.throw(_("Meal procurement currently requires stock reservation to be disabled."))
		warehouse = plan.get("for_warehouse")
		if week.get("raw_material_warehouse") and warehouse != week.raw_material_warehouse:
			frappe.throw(_("Every meal Production Plan must use the week's raw material warehouse."))
		if not warehouse:
			_add_message(blockers, _("Production Plan {0} needs a raw material warehouse.").format(plan.name))
			continue
		warehouse_doc = frappe.get_cached_doc("Warehouse", warehouse)
		if warehouse_doc.company != week.company or warehouse_doc.is_group or warehouse_doc.disabled:
			frappe.throw(
				_("A meal raw material warehouse is disabled, a group, or belongs to another company.")
			)
		plans[plan.name] = plan
		data = plan.as_dict()
		# In this ERPNext release, 1 enables projected stock deduction. Use 0 to
		# expand full demand, then allocate verified dated supply once below.
		data.update(ignore_existing_ordered_qty=0, include_safety_stock=0, consider_minimum_order_qty=0)
		for native in get_items_for_material_requests(data):
			native = dict(native)
			native.update(warehouse=warehouse, schedule_date=meal_date.isoformat(), requested_qty=0)
			demands.append(
				{
					"meal_date": meal_date.isoformat(),
					"meal_type": meal.meal_type,
					"meal_index": meal.idx,
					"production_plan": plan.name,
					"headcount": _text(headcount),
					"native": native,
				}
			)
	return plans, demands, blockers


def _load_context(week, demands, include_draft_requests=False, *, for_update=False):
	for_update = bool(for_update or include_draft_requests)
	locking = " FOR UPDATE" if for_update else ""
	codes = sorted({row["native"]["item_code"] for row in demands})
	warehouses = sorted({row["native"]["warehouse"] for row in demands})
	items = {
		code: frappe.get_doc("Item", code, for_update=True)
		if for_update
		else frappe.get_cached_doc("Item", code)
		for code in codes
	}
	if not codes:
		return {
			"items": {},
			"bins": {},
			"purchase_orders": [],
			"requests": [],
			"prices": [],
			"whole_uoms": {},
			"own_plan_reservations": {},
			"has_linked_work_orders": False,
			"owned_plan_names": set(),
			"excluded_supply": [],
		}
	plan_names = sorted({row["production_plan"] for row in demands if row.get("production_plan")})
	# Adjustments can replace a meal's active PP while its original source
	# requests and orders still belong to this week. Retain their native scope.
	linked_names = (
		[
			row.name
			for row in frappe.db.sql(
				"SELECT name FROM `tabProduction Plan` WHERE company=%s AND custom_meal_week=%s FOR UPDATE",
				(week.company, week.name),
				as_dict=True,
			)
		]
		if for_update
		else frappe.get_all(
			"Production Plan", filters={"company": week.company, "custom_meal_week": week.name}, pluck="name"
		)
	)
	owned_plan_names = sorted(set(plan_names) | set(linked_names))
	own_plan_reservations = {}
	has_linked_work_orders = False
	if owned_plan_names:
		has_linked_work_orders = (
			bool(
				frappe.db.sql(
					"SELECT name FROM `tabWork Order` WHERE production_plan IN %s AND docstatus<2 FOR UPDATE",
					(owned_plan_names,),
					as_dict=True,
				)
			)
			if for_update
			else bool(
				frappe.db.exists(
					"Work Order", {"production_plan": ["in", owned_plan_names], "docstatus": ["<", 2]}
				)
			)
		)
		if not has_linked_work_orders:
			# PP.on_submit updates this Bin counter even when reserve_stock=0.
			# The week's own open plans are the demand being allocated, so remove
			# precisely their native contribution, while retaining other plans'.
			reservation_rows = frappe.db.sql(
				"""SELECT i.item_code, i.warehouse, i.required_bom_qty AS reserved_qty
					FROM `tabMaterial Request Plan Item` i
					JOIN `tabProduction Plan` p ON p.name=i.parent
					WHERE p.name IN %(plans)s AND p.docstatus=1
					AND p.status NOT IN ('Completed','Closed')
					"""
				+ locking,
				{"plans": owned_plan_names},
				as_dict=True,
			)
			own_plan_reservations = defaultdict(lambda: ZERO)
			for row in reservation_rows:
				own_plan_reservations[(row.item_code, row.warehouse)] += _decimal(row.reserved_qty)
	bin_fields = [
		"item_code",
		"warehouse",
		"actual_qty",
		"reserved_qty",
		"reserved_qty_for_production",
		"reserved_qty_for_sub_contract",
		"reserved_qty_for_production_plan",
	]
	bin_rows = (
		frappe.db.sql(
			"SELECT "
			+ ",".join(bin_fields)
			+ " FROM `tabBin` WHERE item_code IN %(codes)s AND warehouse IN %(warehouses)s FOR UPDATE",
			{"codes": codes, "warehouses": warehouses},
			as_dict=True,
		)
		if for_update
		else frappe.get_all(
			"Bin",
			filters={"item_code": ["in", codes], "warehouse": ["in", warehouses]},
			fields=bin_fields,
		)
	)
	bins = {(row.item_code, row.warehouse): row for row in bin_rows}
	orders = frappe.db.sql(
		"""SELECT i.name, i.item_code, i.warehouse, i.schedule_date, i.qty,
		i.received_qty, i.conversion_factor, p.name AS purchase_order,
		i.sales_order, mri.production_plan, src.parent AS source_plan_parent,
		src.item_code AS source_item_code, src.warehouse AS source_warehouse
		FROM `tabPurchase Order Item` i JOIN `tabPurchase Order` p ON p.name=i.parent
		LEFT JOIN `tabMaterial Request Item` mri
		ON mri.name=i.material_request_item AND mri.parent=i.material_request AND mri.docstatus=1
		LEFT JOIN `tabMaterial Request Plan Item` src
		ON src.name=mri.material_request_plan_item AND src.parent=mri.production_plan
		WHERE p.company=%(company)s AND p.docstatus=1
		AND p.status NOT IN ('Closed', 'Cancelled', 'Completed')
		AND COALESCE(i.closed,0)=0 AND COALESCE(i.delivered_by_supplier,0)=0
		AND i.item_code IN %(codes)s AND i.warehouse IN %(warehouses)s
		ORDER BY i.schedule_date, p.name, i.idx"""
		+ locking,
		{"company": week.company, "codes": codes, "warehouses": warehouses},
		as_dict=True,
	)
	requests = frappe.db.sql(
		"""SELECT i.name, i.item_code, i.warehouse, i.schedule_date, i.stock_qty,
		i.ordered_qty, i.received_qty, m.name AS material_request, m.docstatus,
		i.sales_order, i.production_plan, src.parent AS source_plan_parent,
		src.item_code AS source_item_code, src.warehouse AS source_warehouse
		FROM `tabMaterial Request Item` i JOIN `tabMaterial Request` m ON m.name=i.parent
		LEFT JOIN `tabMaterial Request Plan Item` src
		ON src.name=i.material_request_plan_item AND src.parent=i.production_plan
		WHERE m.company=%(company)s AND (m.docstatus=1 OR (%(include_drafts)s=1 AND m.docstatus=0))
		AND m.material_request_type='Purchase'
		AND m.status NOT IN ('Stopped', 'Cancelled', 'Ordered', 'Received')
		AND i.item_code IN %(codes)s AND i.warehouse IN %(warehouses)s
		ORDER BY i.schedule_date, m.name, i.idx"""
		+ locking,
		{
			"company": week.company,
			"codes": codes,
			"warehouses": warehouses,
			"include_drafts": int(include_draft_requests),
		},
		as_dict=True,
	)
	price_list = frappe.db.get_single_value("Buying Settings", "buying_price_list")
	prices = (
		frappe.get_all(
			"Item Price",
			filters={"item_code": ["in", codes], "buying": 1, "price_list": price_list},
			fields=["item_code", "uom", "price_list_rate", "valid_from", "valid_upto", "currency"],
		)
		if price_list
		else []
	)
	uoms = sorted(
		{item.stock_uom for item in items.values()}
		| {item.purchase_uom for item in items.values() if item.purchase_uom}
	)
	whole_uoms = {
		row.name: bool(row.must_be_whole_number)
		for row in frappe.get_all(
			"UOM", filters={"name": ["in", uoms]}, fields=["name", "must_be_whole_number"]
		)
	}
	from tongjianyun.meal_stock_claims import build_claim_context

	claims = build_claim_context(week, codes, warehouses, for_update=for_update)
	return {
		"items": items,
		"bins": bins,
		"purchase_orders": orders,
		"requests": requests,
		"prices": prices,
		"whole_uoms": whole_uoms,
		"own_plan_reservations": own_plan_reservations,
		"has_linked_work_orders": has_linked_work_orders,
		"owned_plan_names": set(owned_plan_names),
		"excluded_supply": [],
		"for_update": for_update,
		"claims": claims,
	}


def _supply_purpose(row, context):
	"""Only a verified native source owned by this week is promised to it.

	An unlinked PO is not proof of free warehouse replenishment, and another
	request is not a physical arrival. Such supply can be reviewed separately;
	when received, its unreserved stock follows normal shared-stock allocation.
	"""
	if row.get("sales_order"):
		return "reserved_for_sales_order"
	owner = row.get("source_plan_parent")
	if not owner:
		return "unassigned_or_unverified_source"
	if owner not in context.get("owned_plan_names", set()):
		return "another_production_plan"
	if row.get("source_item_code") != row.item_code or row.get("source_warehouse") != row.warehouse:
		return "source_item_or_warehouse_mismatch"
	return "this_week"


def _record_excluded_supply(row, context, doctype, quantity, reason, warnings):
	context.setdefault("excluded_supply", []).append(
		{
			"doctype": doctype,
			"name": row.get("purchase_order") if doctype == "Purchase Order" else row.get("material_request"),
			"source_item": row.name,
			"item_code": row.item_code,
			"warehouse": row.warehouse,
			"remaining_stock_qty": _text(quantity),
			"reason": reason,
		}
	)
	_add_message(
		warnings,
		_(
			"Incoming orders and requests for other purposes or without verified meal sources do not reduce this week's procurement."
		),
	)


def _prepare_supply(context, as_of, warnings, exclude_request=None):
	stock = {}
	claims = context.get("claims")
	if claims is not None:
		from tongjianyun.meal_stock_claims import physical_pools

		own, free, public = physical_pools(claims, context["bins"])
		context["own_stock_remaining"] = dict(own)
		context["stock_claims_public"] = public
		stock = {key: own.get(key, ZERO) + free.get(key, ZERO) for key in set(own) | set(free)}
		if claims["advance"]:
			_add_message(warnings, _("提前采购不预支旧周余量，可能多备，请采购人员核对。"))
	for key, row in context["bins"].items():
		if claims is not None:
			continue
		other_plan_reserved = max(
			ZERO,
			_decimal(row.get("reserved_qty_for_production_plan"))
			- context.get("own_plan_reservations", {}).get(key, ZERO),
		)
		reserved = (
			sum(
				(
					_decimal(row.get(field))
					for field in (
						"reserved_qty",
						"reserved_qty_for_production",
						"reserved_qty_for_sub_contract",
					)
				),
				ZERO,
			)
			+ other_plan_reserved
		)
		stock[key] = max(ZERO, _decimal(row.actual_qty) - reserved)
	orders, requests = defaultdict(list), defaultdict(list)
	for row in context["purchase_orders"]:
		qty = max(
			ZERO, (_decimal(row.qty) - _decimal(row.received_qty)) * _decimal(row.conversion_factor or 1)
		)
		if qty <= ZERO:
			continue
		purpose = _supply_purpose(row, context)
		if purpose != "this_week":
			_record_excluded_supply(row, context, "Purchase Order", qty, purpose, warnings)
			continue
		if not row.schedule_date or _date(row.schedule_date) < as_of:
			_add_message(
				warnings,
				_(
					"Overdue or undated purchase orders are shown as unconfirmed and do not reduce this request."
				),
			)
			continue
		orders[(row.item_code, row.warehouse)].append(
			{"date": _date(row.schedule_date), "qty": qty, "source": row.name}
		)
	for row in context["requests"]:
		if row.material_request == exclude_request:
			continue
		if row.get("docstatus") == 0:
			from tongjianyun.meal_purchasing import is_verified_superseded_request

			if is_verified_superseded_request(
				frappe.get_doc(
					"Material Request", row.material_request, for_update=bool(context.get("for_update"))
				)
			):
				continue
		# ordered_qty and received_qty describe overlapping fulfilment, not two
		# independent supplies. The corresponding PO is accounted for above.
		qty = max(ZERO, _decimal(row.stock_qty) - max(_decimal(row.ordered_qty), _decimal(row.received_qty)))
		if qty <= ZERO:
			continue
		purpose = _supply_purpose(row, context)
		if purpose != "this_week":
			_record_excluded_supply(row, context, "Material Request", qty, purpose, warnings)
			continue
		if not row.schedule_date or _date(row.schedule_date) < as_of:
			_add_message(
				warnings,
				_("Overdue or undated material requests need review and do not reduce this request."),
			)
			continue
		requests[(row.item_code, row.warehouse)].append(
			{"date": _date(row.schedule_date), "qty": qty, "source": row.name}
		)
	return stock, orders, requests


def _take(pool, needed, meal_date):
	used = ZERO
	for supply in pool:
		if supply["date"] > meal_date or needed <= ZERO:
			continue
		qty = min(supply["qty"], needed)
		supply["qty"] -= qty
		needed -= qty
		used += qty
	return used


def _conversion(item):
	uom = item.purchase_uom or item.stock_uom
	if uom == item.stock_uom:
		return uom, Decimal("1")
	factors = {_decimal(row.conversion_factor) for row in item.uoms if row.uom == uom}
	if len(factors) != 1 or next(iter(factors)) <= ZERO:
		return uom, None
	return uom, next(iter(factors))


def _has_price(prices, item, uom, meal_date):
	return any(
		row.item_code == item.name
		and row.uom in (uom, item.stock_uom)
		and _decimal(row.price_list_rate) > ZERO
		and (not row.valid_from or _date(row.valid_from) <= meal_date)
		and (not row.valid_upto or _date(row.valid_upto) >= meal_date)
		for row in prices
	)


def _allocate(week, demands, context, blockers=None):
	"""Decimal allocation, deliberately independent from ERPNext's float netting."""
	warnings = [_("Stock is based on the ledger and has not been represented as a physical stock count.")]
	blockers = list(blockers or [])
	stock, orders, requests = _prepare_supply(context, _today(), warnings, week.get("material_request"))
	precision = _quantity_precision()
	rows = []
	planned_surplus = defaultdict(lambda: ZERO)
	for demand in demands:
		native = demand["native"]
		item = context["items"][native["item_code"]]
		policy = item.get("custom_meal_procurement_policy") or ""
		uom, factor = _conversion(item)
		required = _decimal(native.get("required_bom_qty"))
		if required <= ZERO:
			frappe.throw(_("BOM expansion returned an invalid ingredient quantity."))
		status = "purchase"
		if item.disabled:
			status = "needs_item_review"
			_add_message(blockers, _("Ingredient {0} is disabled.").format(item.item_name))
		elif policy == POLICY_WATER:
			status = "kitchen_water"
		elif policy == POLICY_RECIPE:
			status = "needs_recipe"
			_add_message(
				blockers, _("Ingredient {0} needs its kitchen-made recipe confirmed.").format(item.item_name)
			)
		elif policy != POLICY_PURCHASE:
			status = "needs_policy"
			_add_message(
				blockers, _("Ingredient {0} needs an explicit procurement policy.").format(item.item_name)
			)
		elif not item.is_purchase_item:
			status = "needs_item_review"
			_add_message(blockers, _("Ingredient {0} is not enabled for purchase.").format(item.item_name))
		elif factor is None:
			status = "needs_conversion"
			_add_message(
				blockers, _("Ingredient {0} has no verified purchase unit conversion.").format(item.item_name)
			)
		elif item.get("has_batch_no") or item.get("has_serial_no"):
			status = "needs_batch_review"
			_add_message(
				blockers,
				_(
					"Ingredient {0} needs usable batch or serial stock verified before automated allocation."
				).format(item.item_name),
			)
		elif _decimal(item.get("min_order_qty")) > ZERO:
			status = "needs_minimum_order_review"
			_add_message(
				blockers,
				_("Ingredient {0} needs its minimum order allocation confirmed.").format(item.item_name),
			)
		stock_used = own_stock_used = new_claim = order_used = requested_used = surplus_used = (
			purchase_qty
		) = ZERO
		key = (item.name, native["warehouse"])
		meal_date = _date(demand["meal_date"])
		if status == "purchase":
			remaining = required
			stock_used = min(remaining, stock.get(key, ZERO))
			stock[key] = stock.get(key, ZERO) - stock_used
			if context.get("claims") is not None:
				own_stock_used = min(stock_used, context["own_stock_remaining"].get(key, ZERO))
				context["own_stock_remaining"][key] = (
					context["own_stock_remaining"].get(key, ZERO) - own_stock_used
				)
				new_claim = stock_used - own_stock_used
			remaining -= stock_used
			order_used = _take(orders[key], remaining, meal_date)
			remaining -= order_used
			requested_used = _take(requests[key], remaining, meal_date)
			remaining -= requested_used
			surplus_used = min(remaining, planned_surplus[key])
			planned_surplus[key] -= surplus_used
			remaining -= surplus_used
			purchase_qty = _purchase_quantity(
				remaining, factor, precision, context["whole_uoms"].get(uom, False)
			)
			planned_surplus[key] += purchase_qty * factor - remaining
		price_status = "available" if _has_price(context["prices"], item, uom, meal_date) else "unquoted"
		public = {key: demand[key] for key in ("meal_date", "meal_type", "production_plan", "headcount")}
		public.update(
			item_code=item.name,
			item_name=item.item_name,
			policy=policy,
			status=status,
			warehouse=native["warehouse"],
			stock_uom=item.stock_uom,
			purchase_uom=uom,
			conversion_factor=_text(factor) if factor is not None else None,
			required_qty=_text(required),
			allocated_stock_qty=_text(stock_used),
			expected_receipt_qty=_text(order_used),
			already_requested_qty=_text(requested_used),
			planned_surplus_used_qty=_text(surplus_used),
			purchase_qty=_text(purchase_qty),
			purchase_stock_qty=_text(purchase_qty * factor) if factor is not None else "0",
			price_status=price_status,
		)
		if context.get("claims") is not None:
			public.update(
				allocated_owned_stock_qty=_text(own_stock_used), new_physical_claim_qty=_text(new_claim)
			)
		rows.append({"public": public, "native": native})
	if any(
		row["public"]["price_status"] == "unquoted" and row["public"]["status"] == "purchase" for row in rows
	):
		_add_message(
			warnings,
			_(
				"Some ingredients have no valid buying price. The request specifies quantity only; obtain quotations before placing orders."
			),
		)
	return rows, warnings, blockers


def _compute(week, include_draft_requests=False, *, for_update=False):
	for_update = bool(for_update or include_draft_requests)
	if for_update:
		from tongjianyun.meal_stock_claims import lock_claim_scope

		lock_claim_scope(week.company)
	plans, demands, blockers = _native_demands(week, for_update=for_update)
	context = _load_context(
		week, demands, include_draft_requests=include_draft_requests, for_update=for_update
	)
	if context.get("has_linked_work_orders"):
		_add_message(
			blockers,
			_(
				"This meal week already has linked Work Orders. Reconcile their stock reservations before using weekly procurement."
			),
		)
	rows, warnings, blockers = _allocate(week, demands, context, blockers)
	public_rows = [row["public"] for row in rows]
	# No document status / child names / requested_qty fields: native submission
	# may update these without changing the frozen procurement calculation.
	basis = {
		"version": 2 if context.get("claims") is not None else 1,
		"company": week.company,
		"week_start": str(week.week_start),
		"week_end": str(week.week_end),
		"rows": public_rows,
		"bom_sources": [
			{
				"production_plan": name,
				"items": [
					{
						"item_code": row.item_code,
						"bom_no": row.bom_no,
						"planned_qty": _text(_decimal(row.planned_qty)),
					}
					for row in plan.po_items
				],
			}
			for name, plan in sorted(plans.items())
		],
	}
	snapshot = dict(basis, basis_hash=_hash(basis))
	preview = {
		"week_name": week.name,
		"company": week.company,
		"week_start": str(week.week_start),
		"week_end": str(week.week_end),
		"stock_reviewed": int(week.get("stock_reviewed") or 0),
		"material_request": week.get("material_request"),
		"rows": public_rows,
		"basis_hash": snapshot["basis_hash"],
		"warnings": warnings,
		"blockers": blockers,
		"excluded_supply": context.get("excluded_supply", []),
		"advance_purchase_mode": bool((context.get("claims") or {}).get("advance")),
		"advance_purchase_note": _("提前采购不预支旧周余量，可能多备，请采购人员核对。")
		if (context.get("claims") or {}).get("advance")
		else "",
		"stock_claims": context.get("stock_claims_public", []),
		"totals": {
			"advance_purchase_mode": bool((context.get("claims") or {}).get("advance")),
			"new_claim_item_count": len(
				{
					row["item_code"]
					for row in public_rows
					if _decimal(row.get("new_physical_claim_qty")) > ZERO
				}
			),
			"ingredient_count": len({row["item_code"] for row in public_rows}),
			"need_quote_count": len(
				{
					row["item_code"]
					for row in public_rows
					if row["status"] == "purchase" and row["price_status"] == "unquoted"
				}
			),
			"blocked_count": len(blockers),
			"purchase_row_count": sum(_decimal(row["purchase_qty"]) > ZERO for row in public_rows),
		},
	}
	return plans, rows, snapshot, preview


def _same_procurement_business_basis(frozen, current):
	"""A submitted week's own claim reclassifies free stock without buying it twice."""
	if frozen.get("version") not in (1, 2) or current.get("version") != 2:
		return False

	def business(snapshot):
		return {
			"company": snapshot.get("company"),
			"week_start": snapshot.get("week_start"),
			"week_end": snapshot.get("week_end"),
			"bom_sources": snapshot.get("bom_sources"),
			"rows": [
				{
					key: value
					for key, value in row.items()
					if key not in {"new_physical_claim_qty", "allocated_owned_stock_qty"}
				}
				for row in snapshot.get("rows", [])
			],
		}

	return business(frozen) == business(current)


def _other_stock_commitments(week, *, for_update=False):
	"""Do not allocate the same unissued stock independently to consecutive weeks.

	A completed request or receipt does not prove kitchen consumption. This first
	phase intentionally requires a separate reconciliation before another frozen
	week can procure; ordinary draft menu editing remains available.
	"""
	other_weeks = (
		frappe.db.sql(
			"SELECT name,procurement_snapshot FROM `tabMeal Planning Week` WHERE company=%s AND docstatus=1 AND name!=%s FOR UPDATE",
			(week.company, week.name),
			as_dict=True,
		)
		if for_update
		else frappe.get_all(
			WEEK_DOCTYPE,
			filters={"company": week.company, "docstatus": 1, "name": ["!=", week.name]},
			fields=["name", "procurement_snapshot"],
		)
	)
	result = []
	for other in other_weeks:
		try:
			snapshot = json.loads(other.procurement_snapshot or "{}")
		except (ValueError, TypeError):
			snapshot = {}
		if snapshot.get("rows"):
			try:
				from tongjianyun.meal_kitchen import verify_week_kitchen_reconciled

				proof = verify_week_kitchen_reconciled(other.name)
				if not proof or proof.get("reconciled") is not True:
					result.append(other.name)
			except Exception:
				# Fail closed: only independently revalidated SE/SLE, purchasing
				# and native PP closure evidence releases an earlier commitment.
				result.append(other.name)
	return result


@frappe.whitelist()
def get_procurement_preview(week_name):
	"""Read-only dated demand and stock allocation for an authorized meal week."""
	week = _load_week(week_name)
	return _compute(week)[3]


def prepare_procurement_rows(week_doc):
	"""Called before PP submission; return native rows for the caller to save.

	The week controller owns the transaction and persists these rows while the
	Production Plans are drafts. This function does not save or submit anything.
	"""
	week_doc.check_permission("read")
	plans, rows, snapshot, preview = _compute(week_doc, for_update=True)
	prepared = {name: [] for name in plans}
	for row in rows:
		public, native = row["public"], dict(row["native"])
		native.update(
			quantity=float(_decimal(public["purchase_qty"])),
			required_bom_qty=float(_decimal(public["required_qty"])),
			uom=public["purchase_uom"],
			conversion_factor=float(_decimal(public["conversion_factor"] or "1")),
			material_request_type="Purchase",
			requested_qty=0,
		)
		prepared[public["production_plan"]].append(native)
	return {
		"plans": prepared,
		"snapshot": snapshot,
		"warnings": preview["warnings"],
		"blockers": preview["blockers"],
	}


def prepare_adjustment_procurement(week_proxy):
	"""Plan the remaining effective meals without buying a prior draft twice.

	The adjustment controller supplies every not-yet-closed effective meal,
	including its replacement draft PP, with material_request=None. Existing
	verified requests from this same week are commitments, including drafts;
	they are never represented as physical stock or actual arrivals.
	"""
	week_proxy.check_permission("read")
	if week_proxy.get("material_request"):
		frappe.throw(
			_("Adjustment procurement must evaluate all of the week's existing request commitments.")
		)
	plans, rows, snapshot, preview = _compute(week_proxy, include_draft_requests=True)
	prepared = {name: [] for name in plans}
	for row in rows:
		public, native = row["public"], dict(row["native"])
		native.update(
			quantity=float(_decimal(public["purchase_qty"])),
			required_bom_qty=float(_decimal(public["required_qty"])),
			uom=public["purchase_uom"],
			conversion_factor=float(_decimal(public["conversion_factor"] or "1")),
			material_request_type="Purchase",
			requested_qty=0,
		)
		prepared[public["production_plan"]].append(native)
	return {
		"plans": prepared,
		"snapshot": snapshot,
		"warnings": preview["warnings"],
		"blockers": preview["blockers"],
		"excluded_supply": preview.get("excluded_supply", []),
	}


def _find_source_rows(plans, rows):
	available = {}
	for name, plan in plans.items():
		if plan.docstatus != 1:
			frappe.throw(_("All meal Production Plans must be submitted before requesting procurement."))
		queues = defaultdict(deque)
		for source in plan.mr_items:
			queues[_key(source)].append(source)
		available[name] = queues
	result = []
	for row in rows:
		public = row["public"]
		key = _key(dict(row["native"], uom=public["purchase_uom"]))
		sources = available[public["production_plan"]][key]
		if not sources:
			frappe.throw(_("A native material source row is missing. Revise and review the meal week."))
		source = sources.popleft()
		if _decimal(source.quantity) != _decimal(public["purchase_qty"]) or _decimal(
			source.required_bom_qty
		) != _decimal(public["required_qty"]):
			frappe.throw(
				_(
					"Frozen Production Plan quantities differ from the procurement calculation. Revise the meal week."
				)
			)
		if _decimal(source.get("requested_qty")) > ZERO:
			frappe.throw(_("A Production Plan source row has already been requested outside this meal week."))
		if public["status"] == "purchase" and _decimal(public["purchase_qty"]) > ZERO:
			result.append((public, source))
	return result


@frappe.whitelist(methods=["POST"])
def create_material_request(week_name):
	"""Create one native draft request, atomically linked to a frozen meal week."""
	week = _load_week(week_name)
	_check_create_permission(week, [])
	from tongjianyun.meal_stock_claims import lock_claim_scope

	lock_claim_scope(week.company)
	# Lock is transaction scoped. Frappe commits the successful POST together
	# with the native draft and link; any exception rolls the entire action back.
	frappe.db.sql("SELECT name FROM `tabMeal Planning Week` WHERE name=%s FOR UPDATE", (week.name,))
	week = frappe.get_doc(WEEK_DOCTYPE, week.name, for_update=True)
	if week.docstatus != 1 or not week.get("stock_reviewed"):
		frappe.throw(
			_("Submit the meal week with its ledger stock review before creating a purchase request.")
		)
	if not frappe.has_permission("Material Request", "create"):
		frappe.throw(
			_("You do not have permission to create purchase material requests."), frappe.PermissionError
		)
	if week.get("material_request"):
		plans = {
			row.production_plan: frappe.get_doc("Production Plan", row.production_plan, for_update=True)
			for row in week.meals
		}
		_check_create_permission(week, plans.values())
		existing = frappe.get_doc("Material Request", week.material_request, for_update=True)
		existing.check_permission("read")
		_verify_existing_request(week, existing, plans)
		if existing.docstatus == 2:
			frappe.throw(
				_("The linked purchase request is cancelled. Revise the meal week before requesting again.")
			)
		return {"material_request": existing.name, "name": existing.name, "created": False}
	plans, rows, snapshot, preview = _compute(week, for_update=True)
	_check_create_permission(week, plans.values())
	if preview["blockers"]:
		frappe.throw("\n".join(preview["blockers"]))
	try:
		frozen = json.loads(week.get("procurement_snapshot") or "{}")
	except (TypeError, ValueError):
		frozen = {}
	if frozen.get("basis_hash") != snapshot["basis_hash"] and not _same_procurement_business_basis(
		frozen, snapshot
	):
		frappe.throw(
			_(
				"Stock, incoming supply, recipe, or procurement settings changed after review. Revise and review the meal week."
			)
		)
	sources = _find_source_rows(plans, rows)
	if not sources:
		return {
			"material_request": None,
			"name": None,
			"created": False,
			"no_purchase_required": True,
			"preview": preview,
		}
	if any(_date(public["meal_date"]) < _today() for public, _source in sources):
		frappe.throw(
			_("Purchase requests cannot use past meal requirement dates. Create a future meal week.")
		)
	mr = frappe.new_doc("Material Request")
	mr.update(
		{
			"company": week.company,
			"material_request_type": "Purchase",
			"transaction_date": _today().isoformat(),
		}
	)
	if mr.meta.has_field("title"):
		mr.title = _("Meal procurement {0} - {1}").format(week.week_start, week.week_end)
	for public, source in sources:
		mr.append(
			"items",
			{
				"item_code": public["item_code"],
				# Calculations/public JSON retain Decimal strings. Native hooks do
				# arithmetic directly on Float fields before saving, so cross this
				# document boundary with numbers, not display strings.
				"qty": float(_decimal(public["purchase_qty"])),
				"uom": public["purchase_uom"],
				"stock_uom": public["stock_uom"],
				"conversion_factor": float(_decimal(public["conversion_factor"])),
				"warehouse": public["warehouse"],
				"schedule_date": public["meal_date"],
				"production_plan": public["production_plan"],
				"material_request_plan_item": source.name,
			},
		)
	mr.run_method("set_missing_values")
	mr.insert()
	week.db_set({"material_request": mr.name, "status": "采购申请已生成"}, update_modified=False)
	return {"material_request": mr.name, "name": mr.name, "created": True, "preview": preview}
