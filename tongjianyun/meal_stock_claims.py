"""Week-owned physical food stock, proved by frozen allocations and native SLE.

These claims replace managed meal PP gross reservations in meal calculations;
they never replace ERPNext's reservation algorithm or write Bin. Future MR/PO
quantities are not physical stock. Callers own the transaction and its commit.
"""
# ruff: noqa: RUF001

import json
from collections import defaultdict

import frappe
from frappe import _

from tongjianyun.meal_procurement import ZERO, _date, _decimal, _hash, _text, _today

EPSILON = _decimal("0.000000001")


def _fail(message):
	frappe.throw(_(message))


def _json(value):
	try:
		result = json.loads(value or "{}") if isinstance(value, str) else value or {}
	except (TypeError, ValueError):
		_fail("食材实物认领依据格式无效，请管理员核对。")
	if not isinstance(result, dict):
		_fail("食材实物认领依据必须为对象。")
	return result


def _rows(query, parameters, lock):
	return frappe.db.sql(query + (" FOR UPDATE" if lock else ""), parameters, as_dict=True)


def _doc(doctype, name, lock):
	return frappe.get_doc(doctype, name, for_update=lock)


def lock_claim_scope(company):
	"""Take the shared food-allocation mutex BEFORE Week / Day / native locks."""
	if not isinstance(company, str) or not company:
		_fail("食材实物认领需要明确所属园所。")
	if not _rows("SELECT name FROM `tabCompany` WHERE name=%s", (company,), True):
		_fail("食材实物认领所属园所不存在。")
	return {"company": company, "locked": True}


def _frozen_rows(week):
	snapshot = _json(week.get("procurement_snapshot"))
	if not snapshot.get("rows"):
		if any(not row.get("service_suspended") for row in week.meals):
			_fail("已审核周缺少冻结原料依据，不能释放或重新分配库存。")
		return [], 2
	keys = ("version", "company", "week_start", "week_end", "rows", "bom_sources")
	if snapshot.get("version") not in (1, 2) or snapshot.get("basis_hash") != _hash(
		{key: snapshot.get(key) for key in keys}
	):
		_fail("周食谱冻结原料依据校验失败。")
	if (
		snapshot.get("company") != week.company
		or str(snapshot.get("week_start")) != str(week.week_start)
		or str(snapshot.get("week_end")) != str(week.week_end)
	):
		_fail("周食谱冻结原料依据与所属园所或日期不一致。")
	return snapshot["rows"], snapshot["version"]


def _opening(rows, version, valid_plans):
	result = defaultdict(lambda: ZERO)
	for row in rows:
		if row.get("production_plan") not in valid_plans:
			_fail("冻结现货认领来源不属于已核实的周生产计划。")
		allocated = _decimal(row.get("allocated_stock_qty"))
		quantity = _decimal(row.get("new_physical_claim_qty")) if version == 2 else allocated
		if version == 2 and (
			(allocated > ZERO and "new_physical_claim_qty" not in row)
			or _decimal(row.get("allocated_owned_stock_qty")) < ZERO
			or quantity + _decimal(row.get("allocated_owned_stock_qty")) != allocated
		):
			_fail("冻结现货分池明细不完整或重复认领。")
		if (
			quantity < ZERO
			or allocated < ZERO
			or quantity > allocated
			or allocated > _decimal(row.get("required_qty"))
		):
			_fail("冻结现货认领量超出已分配的实际库存。")
		result[(row["item_code"], row["warehouse"])] += quantity
	return result


def _sle(voucher_type, voucher, detail, item, warehouse, expected, lock):
	rows = _rows(
		"""SELECT name,item_code,warehouse,actual_qty FROM `tabStock Ledger Entry`
		WHERE voucher_type=%s AND voucher_no=%s AND voucher_detail_no=%s AND is_cancelled=0 ORDER BY name""",
		(voucher_type, voucher, detail),
		lock,
	)
	if not rows or any(row.item_code != item for row in rows):
		_fail("食材到货缺少匹配的原生库存流水。")
	actual = sum((_decimal(row.actual_qty) for row in rows if row.warehouse == warehouse), ZERO)
	if abs(actual - expected) > EPSILON or any(row.warehouse != warehouse for row in rows):
		_fail("食材到货数量或仓库与原生库存流水不一致。")
	return [row.name for row in rows]


def _receipt_owner(row, weeks, plans, lock):
	if not row.purchase_order or not row.purchase_order_item:
		return None
	order = _doc("Purchase Order", row.purchase_order, lock)
	lines = [line for line in order.items if line.name == row.purchase_order_item]
	if len(lines) != 1:
		_fail("采购到货的原生订单来源缺失。")
	line = lines[0]
	if not line.get("material_request") or not line.get("material_request_item"):
		if order.get("custom_meal_week"):
			_fail("标记为膳食采购的到货缺少原生申请来源。")
		return None
	request = _doc("Material Request", line.material_request, lock)
	sources = [source for source in request.items if source.name == line.material_request_item]
	if len(sources) != 1:
		_fail("采购到货的原生申请明细缺失。")
	source = sources[0]
	if not source.get("production_plan"):
		if order.get("custom_meal_week"):
			_fail("膳食到货来源没有原生生产计划。")
		return None
	plan = plans.get(source.production_plan)
	if not plan:
		candidate = _doc("Production Plan", source.production_plan, lock)
		if candidate.get("custom_meal_week"):
			_fail("膳食到货关联未核实或未审核的食谱周。")
		return None
	week_name = plan.custom_meal_week
	week = weeks[week_name]
	material = [part for part in plan.mr_items if part.name == source.get("material_request_plan_item")]
	if (
		order.docstatus != 1
		or request.docstatus != 1
		or request.material_request_type != "Purchase"
		or order.company != week.company
		or request.company != week.company
		or len(material) != 1
		or any(
			part.item_code != row.item_code or part.warehouse != row.warehouse
			for part in (line, source, material[0])
		)
		or (row.get("material_request") and row.material_request != request.name)
		or (row.get("material_request_item") and row.material_request_item != source.name)
		or order.get("custom_meal_week") not in (None, "", week_name)
		or request.get("custom_meal_adjustment") != plan.get("custom_meal_adjustment")
		or source.get("sales_order")
		or line.get("sales_order")
	):
		_fail("膳食到货的申请、订单、原料及周归属链不一致。")
	return week_name


def _issue_free_claim(entry, quantities, warehouse):
	proof = _json(entry.get("custom_meal_raw_claim_snapshot"))
	if not proof:
		return {}
	content = {key: value for key, value in proof.items() if key != "proof_hash"}
	if (
		proof.get("proof_hash") != _hash(content)
		or proof.get("entry") != entry.name
		or proof.get("week") != entry.custom_meal_week
		or proof.get("warehouse") != warehouse
		or proof.get("version") != 1
	):
		_fail("厨房领用的现货归属确认依据无效。")
	parts = proof.get("items") or []
	if len(parts) != len(quantities) or len({row.get("item_code") for row in parts}) != len(parts):
		_fail("厨房领用的现货归属明细不完整。")
	result = {}
	for row in parts:
		code = row.get("item_code")
		own, free = _decimal(row.get("own_taken")), _decimal(row.get("free_taken"))
		if (
			code not in quantities
			or own < ZERO
			or free < ZERO
			or _decimal(row.get("qty")) != quantities[code]
			or own + free != quantities[code]
		):
			_fail("厨房领用数量与现货归属确认不一致。")
		result[code] = free
	return result


def build_claim_context(week, codes, warehouses, *, for_update=False, exclude_entry=None):
	"""Rebuild ownership using current/read-only native facts, never future supply."""
	codes, warehouses = sorted(set(codes)), sorted(set(warehouses))
	if for_update:
		lock_claim_scope(week.company)
	week_rows = _rows(
		"SELECT name FROM `tabMeal Planning Week` WHERE company=%s AND docstatus=1 ORDER BY name",
		(week.company,),
		for_update,
	)
	weeks, valid_plans, openings, released = {}, {}, {}, set()
	from tongjianyun.meal_adjustments import _APPLYING, get_effective_meals

	for selected in week_rows:
		document = _doc("Meal Planning Week", selected.name, for_update)
		get_effective_meals(document, lock=for_update)  # Independently check the adjustment chain.
		base, version = _frozen_rows(document)
		plan_names = {row.production_plan for row in document.meals if row.production_plan}
		adjustments = _rows(
			"SELECT name,replacement_plan,applied_snapshot FROM `tabMeal Plan Adjustment` WHERE meal_week=%s AND docstatus=1 ORDER BY creation,name",
			(document.name,),
			for_update,
		)
		adjustment_rows = []
		for adjustment in adjustments:
			if adjustment.name == _APPLYING.get():
				continue
			proof = _json(adjustment.applied_snapshot)
			if proof.get("week") != document.name or proof.get("adjustment") != adjustment.name:
				_fail("单餐变更缺少有效的现货认领来源。")
			if adjustment.replacement_plan:
				plan_names.add(adjustment.replacement_plan)
			for row in proof.get("requirements", []):
				if "new_physical_claim_qty" not in row and _decimal(row.get("allocated_stock_qty")) > ZERO:
					_fail("历史单餐变更的现货认领尚未确认，不能推断或重复分配。")
			adjustment_rows.extend(proof.get("requirements", []))
		weeks[document.name] = document
		opening = _opening(base, version, plan_names)
		for key, value in _opening(adjustment_rows, 2, plan_names).items():
			opening[key] += value
		openings[document.name] = opening
		for name in sorted(plan_names):
			plan = _doc("Production Plan", name, for_update)
			if (
				plan.company != week.company
				or plan.get("custom_meal_week") != document.name
				or plan.docstatus == 2
			):
				_fail("食材现货认领的原生生产计划归属无效。")
			if plan.get("reserve_stock"):
				_fail("食谱实物认领暂不支持同时启用原生库存预留，请先核实配置。")
			valid_plans[name] = plan
		if document.get("kitchen_reconciled"):
			from tongjianyun.meal_kitchen import verify_week_kitchen_reconciled

			if verify_week_kitchen_reconciled(document, lock=for_update).get("reconciled") is not True:
				_fail("已核销周的实际库存与采购依据未通过复核。")
			released.add(document.name)
	managed = defaultdict(lambda: ZERO)
	if valid_plans:
		work_orders = _rows(
			"SELECT name FROM `tabWork Order` WHERE production_plan IN %s AND docstatus<2 ORDER BY name",
			(sorted(valid_plans),),
			for_update,
		)
		if work_orders:
			_fail("食谱生产计划已关联工单，须先核实原生库存占用接管，不能自动分配。")
	for plan in valid_plans.values():
		if plan.docstatus != 1 or plan.status in ("Closed", "Completed"):
			continue
		for row in plan.mr_items:
			managed[(row.item_code, row.warehouse)] += _decimal(row.required_bom_qty)
		for row in plan.get("sub_assembly_items") or []:
			if row.type_of_manufacturing == "In House":
				managed[(row.production_item, row.fg_warehouse)] += _decimal(row.required_qty)
	balances = {name: defaultdict(lambda: ZERO, values) for name, values in openings.items()}
	evidence = {"receipts": [], "stock_entries": [], "released_weeks": sorted(released)}
	if codes and warehouses:
		receipts = _rows(
			"""SELECT r.name,r.is_return,i.name AS detail,i.item_code,i.warehouse,i.stock_qty,
		i.purchase_order,i.purchase_order_item,i.material_request,i.material_request_item
		FROM `tabPurchase Receipt` r JOIN `tabPurchase Receipt Item` i ON i.parent=r.name
		WHERE r.company=%(company)s AND r.docstatus=1 AND i.item_code IN %(codes)s AND i.warehouse IN %(warehouses)s
		ORDER BY r.name,i.idx""",
			{"company": week.company, "codes": codes, "warehouses": warehouses},
			for_update,
		)
		for row in receipts:
			owner = _receipt_owner(row, weeks, valid_plans, for_update)
			if not owner:
				continue
			quantity = _decimal(row.stock_qty)
			if (quantity < ZERO) != bool(row.is_return) or quantity == ZERO:
				_fail("采购到货或退货的实物数量方向无效。")
			sle = _sle(
				"Purchase Receipt", row.name, row.detail, row.item_code, row.warehouse, quantity, for_update
			)
			balances[owner][(row.item_code, row.warehouse)] += quantity
			evidence["receipts"].append(
				{
					"week": owner,
					"name": row.name,
					"detail": row.detail,
					"item_code": row.item_code,
					"warehouse": row.warehouse,
					"qty": _text(quantity),
					"sle": sle,
				}
			)
	if weeks and codes and warehouses:
		entries = _rows(
			"""SELECT DISTINCT s.name FROM `tabStock Entry` s JOIN `tabStock Entry Detail` i ON i.parent=s.name
		WHERE s.company=%(company)s AND s.docstatus=1 AND s.custom_meal_week IN %(weeks)s
		AND i.item_code IN %(codes)s AND (i.s_warehouse IN %(warehouses)s OR i.t_warehouse IN %(warehouses)s)
		ORDER BY s.name""",
			{"company": week.company, "weeks": sorted(weeks), "codes": codes, "warehouses": warehouses},
			for_update,
		)
		verified_days = set()
		for selected in entries:
			if selected.name == exclude_entry:
				continue
			entry = _doc("Stock Entry", selected.name, for_update)
			owner = entry.custom_meal_week
			document = weeks[owner]
			daily = _doc("Meal Kitchen Day", entry.custom_meal_kitchen_day, for_update)
			if (
				daily.meal_week != owner
				or daily.company != week.company
				or daily.source_warehouse != document.raw_material_warehouse
			):
				_fail("原料仓出入库与厨房实际归属周不一致。")
			if daily.name not in verified_days:
				from tongjianyun.meal_kitchen import _ledger

				_ledger(daily, lock=for_update, verify_sle=True)
				verified_days.add(daily.name)
			quantities = defaultdict(lambda: ZERO)
			movements = defaultdict(lambda: ZERO)
			for row in entry.items:
				quantity = _decimal(row.transfer_qty)
				if quantity <= ZERO:
					_fail("原料仓实际出入库数量必须为正。")
				if (
					entry.custom_meal_action == "领用"
					and row.s_warehouse == document.raw_material_warehouse
					and row.t_warehouse == daily.kitchen_warehouse
				):
					quantities[row.item_code] += quantity
					movements[(row.item_code, row.s_warehouse)] -= quantity
				elif entry.custom_meal_action == "退料" and row.s_warehouse == daily.kitchen_warehouse:
					quantities[row.item_code] -= quantity
					movements[(row.item_code, row.t_warehouse)] += quantity
				else:
					_fail("原料仓出入库必须是经核实的厨房领用或退料。")
			if entry.custom_meal_action == "领用":
				free = _issue_free_claim(entry, quantities, document.raw_material_warehouse)
				for code, quantity in free.items():
					balances[owner][(code, document.raw_material_warehouse)] += quantity
			for key, quantity in movements.items():
				balances[owner][key] += quantity
			evidence["stock_entries"].append(
				{
					"week": owner,
					"name": entry.name,
					"day": daily.name,
					"action": entry.custom_meal_action,
					"raw_out": {code: _text(quantity) for code, quantity in quantities.items()},
				}
			)
	own, other = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
	for owner, values in balances.items():
		for key, quantity in values.items():
			if key[0] not in codes or key[1] not in warehouses:
				continue
			if quantity < -EPSILON:
				_fail("原料仓按周实物认领出现负余额，请核实到货、领用与退货来源。")
			if owner not in released:
				(own if owner == week.name else other)[key] += max(ZERO, quantity)
	prior = sorted(
		name
		for name, document in weeks.items()
		if name != week.name
		and name not in released
		and document.raw_material_warehouse in warehouses
		and _date(document.week_start) < _date(week.week_start)
	)
	return {
		"own": dict(own),
		"other": dict(other),
		"managed_reservations": dict(managed),
		"advance": bool(_today() < _date(week.week_start) and prior),
		"prior_unsettled_weeks": prior,
		"evidence": evidence,
		"week_documents": weeks,
		"plan_documents": valid_plans,
		"balances_by_week": balances,
		"released_weeks": released,
	}


def physical_pools(claims, bins):
	"""Disjoint own / unassigned pools, retaining non-meal reservations."""
	own, free, public = {}, {}, []
	keys = set(bins) | set(claims["own"]) | set(claims["other"])
	for key in sorted(keys):
		row = bins.get(key) or {}
		physical = _decimal(row.get("actual_qty"))
		managed = claims["managed_reservations"].get(key, ZERO)
		native_plan = _decimal(row.get("reserved_qty_for_production_plan"))
		if managed > native_plan + EPSILON:
			_fail("原生生产计划库存占用与食谱来源不一致，请刷新并核对。")
		reserved = max(ZERO, native_plan - managed) + sum(
			(
				_decimal(row.get(field))
				for field in ("reserved_qty", "reserved_qty_for_production", "reserved_qty_for_sub_contract")
			),
			ZERO,
		)
		available = physical - reserved
		owned, others = claims["own"].get(key, ZERO), claims["other"].get(key, ZERO)
		if owned + others > ZERO and owned + others > available + EPSILON:
			_fail("按周认领的食材实物超过账面可用库存，不能挪用他周已到货食材。")
		unassigned = max(ZERO, available - owned - others)
		own[key] = owned
		free[key] = ZERO if claims["advance"] else unassigned
		public.append(
			{
				"item_code": key[0],
				"warehouse": key[1],
				"physical_qty": _text(physical),
				"own_claim_qty": _text(owned),
				"other_week_claim_qty": _text(others),
				"free_qty": _text(unassigned),
				"available_free_qty": _text(free[key]),
			}
		)
	return own, free, public


def assert_week_raw_stock_available(week, quantities, exclude_entry=None):
	"""Bind a real issue to own/free physical stock before native submission."""
	if isinstance(week, str):
		week = frappe.get_doc("Meal Planning Week", week)
	week.check_permission("read")
	lock_claim_scope(week.company)
	claims = build_claim_context(
		week, list(quantities), [week.raw_material_warehouse], for_update=True, exclude_entry=exclude_entry
	)
	rows = _rows(
		"SELECT * FROM `tabBin` WHERE warehouse=%s AND item_code IN %s ORDER BY item_code,name",
		(week.raw_material_warehouse, sorted(quantities)),
		True,
	)
	bins = {(row.item_code, row.warehouse): row for row in rows}
	own, free, _public = physical_pools(claims, bins)
	items = []
	for code, value in sorted(quantities.items()):
		quantity = _decimal(value)
		key = (code, week.raw_material_warehouse)
		if quantity <= ZERO or quantity > own.get(key, ZERO) + free.get(key, ZERO):
			_fail("本周可领用实物不足，不能领走其他周已认领或专属到货的食材。")
		taken = min(quantity, own.get(key, ZERO))
		items.append(
			{
				"item_code": code,
				"qty": _text(quantity),
				"own_taken": _text(taken),
				"free_taken": _text(quantity - taken),
			}
		)
	proof = {
		"version": 1,
		"week": week.name,
		"entry": exclude_entry,
		"warehouse": week.raw_material_warehouse,
		"items": items,
	}
	proof["proof_hash"] = _hash(proof)
	return proof


def _receipt_changes(doc, cancel=False):
	"""Project native receipt changes against disjoint physical ownership pools."""
	lock_claim_scope(doc.company)
	quantities = defaultdict(lambda: ZERO)
	for row in doc.items:
		if row.get("warehouse") and row.get("item_code"):
			quantities[(row.item_code, row.warehouse)] += _decimal(row.stock_qty) * (-1 if cancel else 1)
		if row.get("rejected_warehouse") and _decimal(row.get("rejected_qty")):
			quantities[(row.item_code, row.rejected_warehouse)] += (
				_decimal(row.rejected_qty) * _decimal(row.conversion_factor) * (-1 if cancel else 1)
			)
		if row.get("from_warehouse"):
			# Internal native receipts also remove the source leg. The native
			# helper applies the receipt's precision and bundle/rejection rules;
			# projecting only the accepted warehouse would miss this withdrawal.
			source_qty = _decimal(row.stock_qty)
			if callable(getattr(doc, "get_source_warehouse_qty", None)):
				source_qty = _decimal(doc.get_source_warehouse_qty(row, float(source_qty)))
			elif _decimal(row.get("rejected_qty")):
				_fail("内部收货的拒收调出量无法核实，不能绕过膳食实物归属核对。")
			quantities[(row.item_code, row.from_warehouse)] -= source_qty * (-1 if cancel else 1)
	if not quantities:
		return
	anchor = frappe._dict(name="", company=doc.company, week_start=_today())
	claims = build_claim_context(
		anchor, [key[0] for key in quantities], [key[1] for key in quantities], for_update=True
	)
	if not claims["week_documents"]:
		return
	rows = _rows(
		"SELECT * FROM `tabBin` WHERE item_code IN %s AND warehouse IN %s ORDER BY item_code,warehouse,name",
		(sorted({key[0] for key in quantities}), sorted({key[1] for key in quantities})),
		True,
	)
	bins = {(row.item_code, row.warehouse): dict(row) for row in rows}
	physical_pools(claims, bins)  # Refuse an already inconsistent ownership pool.
	new_claims = dict(claims, own=dict(claims["own"]), other=dict(claims["other"]))
	owner_changes = defaultdict(lambda: ZERO)
	for item in doc.items:
		serialize = getattr(item, "as_dict", None)
		row = frappe._dict(serialize() if callable(serialize) else dict(item))
		owner = _receipt_owner(row, claims["week_documents"], claims["plan_documents"], True)
		if owner:
			if (
				_decimal(item.get("rejected_qty"))
				or item.get("from_warehouse")
				or doc.get("is_subcontracted")
			):
				_fail("膳食实物认领暂不支持混合拒收、内部调拨或委外收货，请先拆分并核对原生库存来源。")
			if owner in claims["released_weeks"]:
				_fail("已核销周的到货或退货需先按正式流程更正周结。")
			if not cancel and _date(doc.posting_date) > _today():
				_fail("未来日期不能登记为已实际到货的膳食库存。")
			owner_changes[(owner, item.item_code, item.warehouse)] += _decimal(item.stock_qty) * (
				-1 if cancel else 1
			)
	for (owner, code, warehouse), change in owner_changes.items():
		key = (code, warehouse)
		if claims["balances_by_week"][owner].get(key, ZERO) + change < -EPSILON:
			_fail("本周剩余归属实物不足以退货或取消收货，不能使用其他周库存补退。")
		new_claims["other"][key] = new_claims["other"].get(key, ZERO) + change
	for key, change in quantities.items():
		row = bins.setdefault(key, {})
		row["actual_qty"] = _decimal(row.get("actual_qty")) + change
	physical_pools(new_claims, bins)


def before_submit_purchase_receipt(doc, method=None):
	"""Unmapped arrivals remain free; returns cannot take another week's stock."""
	_receipt_changes(doc)


def before_cancel_purchase_receipt(doc, method=None):
	lock_claim_scope(doc.company)
	stored = _doc("Purchase Receipt", doc.name, True)
	if _receipt_signature(stored) != _receipt_signature(doc):
		_fail("取消收货前不能改写原始食材数量、仓库或采购来源。")
	_receipt_changes(stored, cancel=True)


def _receipt_signature(doc):
	fields = (
		"name",
		"item_code",
		"warehouse",
		"stock_uom",
		"uom",
		"conversion_factor",
		"qty",
		"stock_qty",
		"received_qty",
		"rejected_qty",
		"rejected_warehouse",
		"from_warehouse",
		"serial_and_batch_bundle",
		"rejected_serial_and_batch_bundle",
		"serial_no",
		"batch_no",
		"purchase_order",
		"purchase_order_item",
		"material_request",
		"material_request_item",
	)
	return {
		"header": {
			field: _text(_decimal(doc.get(field)))
			if field in {"conversion_rate", "set_posting_time", "is_return"}
			else str(doc.get(field) or "")
			for field in (
				"company",
				"supplier",
				"currency",
				"conversion_rate",
				"posting_date",
				"posting_time",
				"set_posting_time",
				"is_return",
				"return_against",
				"owner",
				"creation",
				"set_warehouse",
				"set_from_warehouse",
				"rejected_warehouse",
				"is_subcontracted",
				"supplier_warehouse",
			)
		},
		"items": sorted(
			tuple(
				_text(_decimal(row.get(field)))
				if field in {"conversion_factor", "qty", "stock_qty", "received_qty", "rejected_qty"}
				else str(row.get(field) or "")
				for field in fields
			)
			for row in doc.items
		),
	}


def validate_purchase_receipt(doc, method=None):
	"""Keep submitted inventory/source facts immutable; native billing fields pass."""
	old = doc.get_doc_before_save()
	if not old or old.docstatus != 1 or _receipt_signature(old) == _receipt_signature(doc):
		return
	# Only the claimed meal chain is protected here; ordinary receipt edits keep
	# their existing native rules. Current reads prevent swapping the scope out.
	lock_claim_scope(doc.company)
	anchor = frappe._dict(name="", company=doc.company, week_start=_today())
	claims = build_claim_context(
		anchor, [row.item_code for row in old.items], [row.warehouse for row in old.items], for_update=True
	)
	if any(
		_receipt_owner(row, claims["week_documents"], claims["plan_documents"], True) for row in old.items
	):
		_fail("已提交膳食收货的食材、数量、仓库及原生采购来源已冻结。")
