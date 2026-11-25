"""Controlled meal purchase drafts and quotation review; native orders remain native.

No API in this module submits an order, receives goods, invents prices, commits a
transaction or silently overrides the requirement for a second quotation reviewer.
"""
# ruff: noqa: RUF001

from __future__ import annotations

import json
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar

import frappe
from frappe import _

from tongjianyun.meal_procurement import ZERO, _date, _decimal, _hash, _text, _today

_MANAGED = ContextVar("meal_purchase_managed", default=False)
_CONTROLLED = ("custom_meal_week", "custom_meal_quote_snapshot")
_REQUEST_LINKS = ("custom_meal_superseded_by", "custom_meal_replaces")


@contextmanager
def _managed():
	token = _MANAGED.set(True)
	try:
		yield
	finally:
		_MANAGED.reset(token)


def _json(value):
	if not value:
		return {}
	if isinstance(value, dict):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		frappe.throw(_("The meal purchase quotation confirmation is invalid."))


def _now():
	from frappe.utils import now_datetime

	return str(now_datetime())


def _manager():
	if frappe.session.user == "Guest" or not {"System Manager", "Purchase Manager"}.intersection(
		frappe.get_roles()
	):
		frappe.throw(
			_("Meal purchasing requires a Purchase Manager or System Manager."), frappe.PermissionError
		)


def _operator():
	if frappe.session.user == "Guest" or not {
		"System Manager",
		"Purchase Manager",
		"膳食业务经办员",
	}.intersection(frappe.get_roles()):
		frappe.throw(
			_("Meal purchase draft actions require an authorized meal purchaser."), frappe.PermissionError
		)


def _narrow_operator_only():
	roles = set(frappe.get_roles())
	return "膳食业务经办员" in roles and not roles.intersection(
		{"System Manager", "Purchase Manager", "Purchase User", "Stock Manager", "Stock User"}
	)


def _original_creator(doc, doctype, *, database=False):
	"""Keep the real creator immutable, including privileged and managed saves."""
	old = doc.get_doc_before_save()
	if old and doc.get("owner") != old.get("owner"):
		frappe.throw(_("膳食单据创建人不能修改；需要更换经办人时请使用受控重制操作。"))
	is_new = getattr(doc, "is_new", None)
	if callable(is_new) and is_new() and doc.get("owner") not in {None, frappe.session.user}:
		frappe.throw(_("新增膳食单据必须由当前实际经办人创建，不能指定其他创建人。"))
	if database:
		owner = frappe.db.get_value(doctype, doc.name, "owner", for_update=True)
		if not isinstance(owner, str) or not owner:
			frappe.throw(_("无法核实膳食单据的原始创建人，请刷新后重试。"))
		if doc.get("owner") != owner:
			frappe.throw(_("膳食单据创建人不能修改；需要更换经办人时请使用受控重制操作。"))
		return owner
	return old.get("owner") if old else doc.get("owner")


def validate_supplier_quotation(doc, method=None):
	"""Protect operators' real quotation authorship without changing unrelated quotes."""
	old = doc.get_doc_before_save()
	# Administrator inherits every role in Frappe; that does not make all of
	# its unrelated supplier quotations part of this meal workflow.
	users = {frappe.session.user, doc.get("owner"), old.get("owner") if old else None} - {
		None,
		"",
		"Administrator",
	}
	if not any("膳食业务经办员" in frappe.get_roles(user) for user in users):
		return
	_original_creator(doc, "Supplier Quotation", database=method == "before_submit")


def _week(value, *, for_update=False):
	if for_update:
		from tongjianyun.meal_stock_claims import lock_claim_scope

		initial = frappe.get_doc("Meal Planning Week", value) if isinstance(value, str) else value
		lock_claim_scope(initial.company)
	doc = (
		frappe.get_doc("Meal Planning Week", value if isinstance(value, str) else value.name, for_update=True)
		if for_update
		else frappe.get_doc("Meal Planning Week", value)
		if isinstance(value, str)
		else value
	)
	doc.check_permission("read")
	return doc


def _plan_names(week, *, for_update=False):
	if for_update:
		return {
			row.name
			for row in frappe.db.sql(
				"SELECT name FROM `tabProduction Plan` WHERE company=%s AND custom_meal_week=%s FOR UPDATE",
				(week.company, week.name),
				as_dict=True,
			)
		}
	rows = frappe.get_all(
		"Production Plan", filters={"company": week.company, "custom_meal_week": week.name}, pluck="name"
	)
	return set(rows)


def _source_request(row, *, for_update=False):
	if not row.get("material_request") or not row.get("material_request_item"):
		return None, None, None
	mr = frappe.get_doc("Material Request", row.material_request, for_update=for_update)
	items = [item for item in mr.get("items") if item.name == row.material_request_item]
	if len(items) != 1:
		frappe.throw(_("The purchase order has an invalid material request source."))
	item = items[0]
	if (
		item.item_code != row.item_code
		or not item.get("production_plan")
		or not item.get("material_request_plan_item")
	):
		return mr, item, None
	plan = frappe.get_doc("Production Plan", item.production_plan, for_update=for_update)
	sources = [source for source in plan.mr_items if source.name == item.material_request_plan_item]
	if len(sources) != 1 or sources[0].item_code != row.item_code or sources[0].warehouse != row.warehouse:
		frappe.throw(_("The purchase order does not match its native Production Plan material source."))
	return mr, item, plan


def _scope(po, *, for_update=False):
	"""Resolve scope through native MR -> PP sources, never through a custom flag alone."""
	resolved = []
	week_names = set()
	for row in po.get("items") or []:
		mr, source, plan = _source_request(row)
		name = plan.get("custom_meal_week") if plan else None
		if name:
			week_names.add(name)
		resolved.append((row, mr, source, plan, name))
	claimed = po.get("custom_meal_week")
	if not week_names:
		if claimed:
			frappe.throw(_("A meal week label alone is not a valid procurement source."))
		return None, []
	if len(week_names) != 1:
		frappe.throw(_("One meal purchase order cannot mix different meal weeks."))
	name = next(iter(week_names))
	if claimed and claimed != name:
		frappe.throw(_("The purchase order's meal week does not match its native sources."))
	week = _week(name, for_update=for_update)
	if for_update:
		# The initial read only identifies the serialization key. After waiting
		# for it, re-resolve every native source with current locking reads.
		resolved = []
		for row in po.get("items") or []:
			mr, source, plan = _source_request(row, for_update=True)
			resolved.append((row, mr, source, plan, plan.get("custom_meal_week") if plan else None))
	if week.company != po.company or week.docstatus != 1:
		frappe.throw(_("Meal purchase orders require a submitted week in the same company."))
	for row, mr, source, _plan, owner in resolved:
		if (
			owner != name
			or mr.company != week.company
			or mr.material_request_type != "Purchase"
			or mr.docstatus != 1
		):
			frappe.throw(
				_("A meal purchase order must contain only approved native sources from its own week.")
			)
		if mr.get("custom_meal_adjustment") != _plan.get("custom_meal_adjustment"):
			frappe.throw(_("The request's adjustment reference disagrees with its native Production Plan."))
		if source.get("sales_order") or row.get("sales_order"):
			frappe.throw(_("Sales-order-reserved supplies cannot be reassigned to meal purchasing."))
	return week, resolved


def _factor(item, uom):
	if uom == item.stock_uom:
		return _decimal(1)
	factors = {_decimal(row.conversion_factor) for row in item.uoms if row.uom == uom}
	if len(factors) != 1 or next(iter(factors)) <= ZERO:
		frappe.throw(_("Item {0} needs a verified purchase unit conversion.").format(item.item_name))
	return next(iter(factors))


def _weight_proof(week, requests):
	# The planning controller owns weight-basis confirmation and any resulting
	# adjustment requests. Do not reinterpret a frozen legacy week's quantities.
	from tongjianyun.meal_planning import verify_purchase_weight_basis

	proof = verify_purchase_weight_basis(week, requests)
	if not isinstance(proof, dict) or proof.get("confirmed") is not True:
		frappe.throw(_("Confirm the recipe's purchase weight basis before reviewing or submitting an order."))
	return proof


def _quotation(quote_name, po):
	quote = frappe.get_doc("Supplier Quotation", quote_name, for_update=True)
	quote.check_permission("read")
	if (
		quote.docstatus != 1
		or quote.supplier != po.supplier
		or quote.company != po.company
		or quote.currency != po.currency
	):
		frappe.throw(
			_("The quotation must be submitted and match the order's supplier, company and currency.")
		)
	if _date(quote.transaction_date) > _date(po.transaction_date):
		frappe.throw(_("The order cannot precede its supplier quotation."))
	if not quote.get("valid_till") or _date(quote.valid_till) < max(_today(), _date(po.transaction_date)):
		frappe.throw(_("The supplier quotation needs an explicit, unexpired validity date."))
	return quote


def _validate_order_caps(po, sources):
	current, caps = defaultdict(lambda: ZERO), {}
	for row, _mr, source, _plan, _owner in sources:
		current[source.name] += _decimal(row.qty) * _decimal(row.conversion_factor)
		caps[source.name] = _decimal(source.stock_qty)
	others = (
		frappe.db.sql(
			"""SELECT i.material_request_item,i.qty,i.received_qty,i.conversion_factor,i.closed,
		p.docstatus,p.status FROM `tabPurchase Order Item` i JOIN `tabPurchase Order` p ON p.name=i.parent
		WHERE p.docstatus<2 AND p.name!=%(name)s AND i.material_request_item IN %(sources)s FOR UPDATE""",
			{"name": po.name, "sources": sorted(caps)},
			as_dict=True,
		)
		if caps
		else []
	)
	for row in others:
		quantity = (
			_decimal(row.received_qty)
			if row.docstatus == 1 and (row.status == "Closed" or row.closed)
			else _decimal(row.qty)
		)
		current[row.material_request_item] += quantity * _decimal(row.conversion_factor)
	if any(quantity > caps[name] for name, quantity in current.items()):
		frappe.throw(
			_("Draft and submitted meal orders together exceed the approved material request quantity.")
		)


def _quote_basis(po, week, sources):
	if not po.supplier:
		frappe.throw(_("Select the actual supplier before quotation review."))
	supplier = frappe.get_cached_doc("Supplier", po.supplier)
	if supplier.disabled:
		frappe.throw(_("The selected supplier is disabled."))
	if not po.currency or _decimal(po.conversion_rate) <= ZERO:
		frappe.throw(_("The order needs a valid currency and exchange rate."))
	proof = _weight_proof(week, sorted({mr.name for _row, mr, _source, _plan, _owner in sources}))
	quotes = {}
	rows = []
	for row, mr, source, _plan, _owner in sources:
		item = frappe.get_cached_doc("Item", row.item_code)
		factor = _factor(item, row.uom)
		if (
			row.stock_uom != item.stock_uom
			or _decimal(row.conversion_factor) != factor
			or _decimal(row.qty) <= ZERO
		):
			frappe.throw(
				_("Purchase quantity, stock unit or unit conversion is not valid for {0}.").format(
					item.item_name
				)
			)
		if _decimal(row.rate) <= ZERO or row.get("is_free_item"):
			frappe.throw(
				_(
					"Every meal order line must have a confirmed positive price; zero or free prices cannot be submitted."
				)
			)
		if row.get("net_rate") is not None and _decimal(row.net_rate) <= ZERO:
			frappe.throw(
				_("A meal order cannot have a zero or negative effective unit price after discounts.")
			)
		if not row.get("supplier_quotation") or not row.get("supplier_quotation_item"):
			frappe.throw(_("Every meal order line must reference an actual submitted Supplier Quotation."))
		if row.supplier_quotation not in quotes:
			quotes[row.supplier_quotation] = _quotation(row.supplier_quotation, po)
		quote = quotes[row.supplier_quotation]
		matches = [entry for entry in quote.get("items") if entry.name == row.supplier_quotation_item]
		if len(matches) != 1:
			frappe.throw(_("A supplier quotation source row is missing."))
		quoted = matches[0]
		if (
			quoted.item_code != row.item_code
			or quoted.uom != row.uom
			or _decimal(quoted.conversion_factor) != factor
		):
			frappe.throw(_("The quotation's item or unit conversion does not match the purchase order."))
		if _decimal(quoted.rate) <= ZERO or _decimal(quoted.rate) != _decimal(row.rate):
			frappe.throw(_("The purchase price differs from the approved supplier quotation."))
		if (
			quoted.get("net_rate") is not None
			and row.get("net_rate") is not None
			and _decimal(quoted.net_rate) != _decimal(row.net_rate)
		):
			frappe.throw(
				_("The effective purchase price after discounts differs from the supplier quotation.")
			)
		rows.append(
			{
				"name": row.name,
				"item_code": row.item_code,
				"material_request": mr.name,
				"material_request_item": source.name,
				"production_plan": source.production_plan,
				"material_request_plan_item": source.material_request_plan_item,
				"warehouse": row.warehouse,
				"schedule_date": str(row.schedule_date),
				"qty": _text(_decimal(row.qty)),
				"uom": row.uom,
				"stock_uom": row.stock_uom,
				"conversion_factor": _text(factor),
				"rate": _text(_decimal(row.rate)),
				"price_list_rate": _text(_decimal(row.get("price_list_rate"))),
				"discount_percentage": _text(_decimal(row.get("discount_percentage"))),
				"discount_amount": _text(_decimal(row.get("discount_amount"))),
				"quotation": quote.name,
				"quotation_item": quoted.name,
				"quotation_date": str(quote.transaction_date),
				"valid_till": str(quote.valid_till),
			}
		)
	_validate_order_caps(po, sources)
	if po.get("grand_total") is not None and _decimal(po.grand_total) <= ZERO:
		frappe.throw(_("A formal meal purchase order must have a positive total amount."))
	return {
		"version": 1,
		"week_name": week.name,
		"supplier": po.supplier,
		"company": po.company,
		"currency": po.currency,
		"conversion_rate": _text(_decimal(po.conversion_rate)),
		"transaction_date": str(po.transaction_date),
		"rows": rows,
		"amounts": {
			field: _text(_decimal(po.get(field)))
			for field in (
				"net_total",
				"grand_total",
				"rounded_total",
				"rounding_adjustment",
				"discount_amount",
				"additional_discount_percentage",
			)
		},
		"apply_discount_on": po.get("apply_discount_on") or "",
		"shipping_rule": po.get("shipping_rule") or "",
		"taxes_and_charges": po.get("taxes_and_charges") or "",
		"taxes": [
			{
				field: str(tax.get(field) or "")
				for field in (
					"charge_type",
					"account_head",
					"add_deduct_tax",
					"category",
					"rate",
					"tax_amount",
					"included_in_print_rate",
					"cost_center",
				)
			}
			for tax in po.get("taxes") or []
		],
		"weight_basis": {
			key: value for key, value in proof.items() if key not in {"checked_at", "confirmed_at"}
		},
	}


def _protected_fields(po):
	old = po.get_doc_before_save()
	if _MANAGED.get():
		return
	for field in _CONTROLLED:
		if str(po.get(field) or "") != str(old.get(field) or "" if old else ""):
			frappe.throw(
				_(
					"Meal purchase source and quotation confirmation are maintained through the controlled actions."
				)
			)


def validate_purchase_order(doc, method=None):
	"""Register on PO validate and before_update_after_submit; unrelated POs pass through."""
	_protected_fields(doc)
	week, sources = _scope(doc, for_update=True)
	old = doc.get_doc_before_save()
	if old:
		previous_week, _previous_sources = _scope(old)
		if previous_week and (not week or previous_week.name != week.name):
			frappe.throw(_("A meal purchase order cannot be detached from its native source week."))
	if not week:
		if _narrow_operator_only():
			frappe.throw(
				_("Meal business operators may only maintain verified meal purchase orders."),
				frappe.PermissionError,
			)
		return
	_original_creator(doc, "Purchase Order")
	if not doc.get("custom_meal_week"):
		doc.custom_meal_week = week.name
	snapshot = _json(doc.get("custom_meal_quote_snapshot"))
	if snapshot and doc.docstatus == 0 and not _MANAGED.get():
		try:
			current = _quote_basis(doc, week, sources)
			unchanged = snapshot.get("basis_hash") == _hash(current)
		except Exception:
			unchanged = False
		if not unchanged:
			doc.custom_meal_quote_snapshot = None
	if method == "before_update_after_submit":
		# Editing business quantities/prices after order placement requires native
		# cancellation/amendment and another review, not a stale confirmation.
		basis = _quote_basis(doc, week, sources)
		if snapshot.get("basis_hash") != _hash(basis):
			frappe.throw(
				_("Amend and re-review the meal order before changing its confirmed purchase details.")
			)


def before_submit_purchase_order(doc, method=None):
	week, sources = _scope(doc, for_update=True)
	if not week:
		return
	creator = _original_creator(doc, "Purchase Order", database=True)
	_manager()
	basis = _quote_basis(doc, week, sources)
	snapshot = _json(doc.get("custom_meal_quote_snapshot"))
	if snapshot.get("confirmed") is not True or snapshot.get("basis_hash") != _hash(basis):
		frappe.throw(
			_("A second purchaser must confirm the current quotation before the meal order can be submitted.")
		)
	if not snapshot.get("confirmed_by") or snapshot["confirmed_by"] == creator:
		frappe.throw(_("The quotation reviewer must be different from the purchase order creator."))
	user = frappe.get_cached_doc("User", snapshot["confirmed_by"])
	if not user.enabled or not {"System Manager", "Purchase Manager"}.intersection(
		frappe.get_roles(snapshot["confirmed_by"])
	):
		frappe.throw(_("The quotation reviewer is no longer an active authorized purchaser."))


def _draft_order(po_name, review=False):
	_manager() if review else _operator()
	po = frappe.get_doc("Purchase Order", po_name)
	po.check_permission("write")
	if po.docstatus != 0:
		frappe.throw(_("Only a saved draft purchase order can be reviewed."))
	week, sources = _scope(po, for_update=True)
	if not week:
		frappe.throw(_("This order is not associated with a controlled meal week."))
	return po, week, sources


@frappe.whitelist(methods=["POST"])
def create_purchase_order_draft(week_name, supplier, material_request_items=None, material_request=None):
	_operator()
	week = _week(week_name)
	if week.docstatus != 1 or not (material_request or week.get("material_request")):
		frappe.throw(_("The meal week needs a submitted procurement request first."))
	if not frappe.has_permission("Purchase Order", "create"):
		frappe.throw(_("You do not have permission to create purchase orders."), frappe.PermissionError)
	from tongjianyun.meal_stock_claims import lock_claim_scope

	lock_claim_scope(week.company)
	frappe.db.sql("SELECT name FROM `tabMeal Planning Week` WHERE name=%s FOR UPDATE", (week.name,))
	week = _week(week.name, for_update=True)
	mr = frappe.get_doc("Material Request", material_request or week.material_request, for_update=True)
	mr.check_permission("read")
	frappe.db.sql("SELECT name FROM `tabMaterial Request` WHERE name=%s FOR UPDATE", (mr.name,))
	if (
		mr.docstatus != 1
		or mr.material_request_type != "Purchase"
		or mr.company != week.company
		or mr.status == "Stopped"
	):
		frappe.throw(_("The material request must be an active submitted purchase request in this company."))
	supplier_doc = frappe.get_doc("Supplier", supplier)
	supplier_doc.check_permission("read")
	if supplier_doc.disabled:
		frappe.throw(_("The supplier is disabled."))
	selected = frappe.parse_json(material_request_items) if material_request_items else None
	if selected is not None and (
		not isinstance(selected, list)
		or not selected
		or any(not isinstance(value, str) for value in selected)
	):
		frappe.throw(_("Select material request source row names."))
	requested = set(selected or [row.name for row in mr.items])
	owned = _plan_names(week, for_update=True)
	items = [row for row in mr.items if row.name in requested]
	if len(items) != len(requested):
		frappe.throw(_("Some selected rows do not belong to this material request."))
	for row in items:
		if row.production_plan not in owned:
			frappe.throw(_("The request contains a source outside this meal week."))
	requested = {
		row.name
		for row in items
		if _decimal(row.stock_qty) > max(_decimal(row.ordered_qty), _decimal(row.received_qty))
	}
	if not requested:
		frappe.throw(_("All selected material request quantities have already been ordered."))
	# Native ordered_qty excludes draft orders. Locking the MR and inspecting
	# existing drafts prevents two clicks or suppliers from ordering them twice.
	drafts = frappe.db.sql(
		"""SELECT p.name,p.supplier,i.material_request_item
		FROM `tabPurchase Order` p JOIN `tabPurchase Order Item` i ON i.parent=p.name
		WHERE p.docstatus=0 AND i.material_request=%s ORDER BY p.name,i.idx FOR UPDATE""",
		(mr.name,),
		as_dict=True,
	)
	by_order = defaultdict(set)
	for row in drafts:
		by_order[(row.name, row.supplier)].add(row.material_request_item)
	for (name, owner), existing_rows in by_order.items():
		if not existing_rows.intersection(requested):
			continue
		if existing_rows == requested and owner == supplier:
			existing = frappe.get_doc("Purchase Order", name, for_update=True)
			existing.check_permission("read")
			_scope(existing, for_update=True)
			return {"purchase_order": name, "created": False}
		frappe.throw(
			_(
				"Selected request rows already belong to draft order {0}; review it before creating another order."
			).format(name)
		)
	from erpnext.stock.doctype.material_request.mapper import make_purchase_order

	po = make_purchase_order(mr.name, args={"supplier": supplier, "filtered_children": sorted(requested)})
	if not po.items:
		frappe.throw(_("All selected material request quantities have already been ordered."))
	# The native mapper may still use a transaction snapshot. Use the locked
	# request's current fulfilment quantities at the native document boundary.
	current_items = {row.name: row for row in mr.items}
	for row in po.items:
		source = current_items[row.material_request_item]
		remaining = _decimal(source.stock_qty) - max(
			_decimal(source.ordered_qty), _decimal(source.received_qty)
		)
		row.qty = float(remaining / _decimal(source.conversion_factor))
		row.stock_qty = float(remaining)
	with _managed():
		po.custom_meal_week = week.name
		po.custom_meal_quote_snapshot = None
		_scope(po, for_update=True)
		po.insert()
	return {"purchase_order": po.name, "created": True}


@frappe.whitelist(methods=["POST"])
def apply_supplier_quotation(po_name, quotation_name):
	po, week, _sources = _draft_order(po_name)
	quote = _quotation(quotation_name, po)
	by_key = defaultdict(list)
	for row in quote.items:
		by_key[(row.item_code, row.uom)].append(row)
	for row in po.items:
		matching = by_key[(row.item_code, row.uom)]
		if len(matching) != 1:
			frappe.throw(
				_("The quotation must contain one unambiguous row for each order item and purchase unit.")
			)
		quoted = matching[0]
		factor = _factor(frappe.get_cached_doc("Item", row.item_code), row.uom)
		if (
			_decimal(quoted.rate) <= ZERO
			or _decimal(quoted.conversion_factor) != factor
			or _decimal(row.conversion_factor) != factor
		):
			frappe.throw(_("The quotation needs positive prices and the item's verified unit conversion."))
		for field in ("rate", "price_list_rate", "discount_percentage", "discount_amount"):
			row.set(field, float(_decimal(quoted.get(field))))
		row.supplier_quotation = quote.name
		row.supplier_quotation_item = quoted.name
	with _managed():
		po.custom_meal_week = week.name
		po.custom_meal_quote_snapshot = None
		po.save()
	return {"purchase_order": po.name, "quotation": quote.name, "needs_confirmation": True}


@frappe.whitelist(methods=["POST"])
def confirm_purchase_order_quote(po_name):
	po, week, sources = _draft_order(po_name, review=True)
	if frappe.session.user == po.owner:
		frappe.throw(
			_(
				"A different authorized purchaser must review the creator's quotation; administrators cannot self-approve."
			)
		)
	frappe.db.sql("SELECT name FROM `tabPurchase Order` WHERE name=%s FOR UPDATE", (po.name,))
	po.flags.for_update = True
	po.reload()
	creator = _original_creator(po, "Purchase Order", database=True)
	if po.docstatus != 0 or frappe.session.user == creator:
		frappe.throw(
			_("The order must still be a draft owned by a different purchaser at confirmation time.")
		)
	week, sources = _scope(po, for_update=True)
	basis = _quote_basis(po, week, sources)
	snapshot = {
		"confirmed": True,
		"confirmed_by": frappe.session.user,
		"confirmed_at": _now(),
		"quotation_names": sorted({row["quotation"] for row in basis["rows"]}),
		"basis_hash": _hash(basis),
		"basis": basis,
	}
	with _managed():
		po.custom_meal_week = week.name
		po.custom_meal_quote_snapshot = frappe.as_json(snapshot)
		po.save()
	return {
		"purchase_order": po.name,
		"confirmed": True,
		"reviewed_by": snapshot["confirmed_by"],
		"reviewed_at": snapshot["confirmed_at"],
	}


def _request_scope(doc, *, for_update=False):
	resolved, names = [], set()
	for row in doc.get("items") or []:
		plan = frappe.get_doc("Production Plan", row.production_plan) if row.get("production_plan") else None
		week_name = plan.get("custom_meal_week") if plan else None
		if week_name:
			names.add(week_name)
		resolved.append((row, plan, week_name))
	if not names:
		if doc.get("custom_meal_week"):
			frappe.throw(_("A meal request label alone is not a native meal procurement source."))
		return None, []
	if len(names) != 1:
		frappe.throw(_("A meal material request cannot mix different weeks."))
	week_name = next(iter(names))
	week = _week(week_name, for_update=for_update)
	if for_update:
		resolved = []
		for row in doc.get("items") or []:
			plan = (
				frappe.get_doc("Production Plan", row.production_plan, for_update=True)
				if row.get("production_plan")
				else None
			)
			resolved.append((row, plan, plan.get("custom_meal_week") if plan else None))
	if week.company != doc.company or week.docstatus != 1 or doc.material_request_type != "Purchase":
		frappe.throw(
			_("Meal procurement requires a submitted week and a purchase request in the same company.")
		)
	if doc.get("custom_meal_week") and doc.custom_meal_week != week.name:
		frappe.throw(_("The material request's meal week disagrees with its native sources."))
	result = []
	for row, plan, name in resolved:
		if name != week.name or plan.company != week.company or row.get("sales_order"):
			frappe.throw(_("A meal request must contain only verified native sources from its own week."))
		if doc.get("custom_meal_adjustment") != plan.get("custom_meal_adjustment"):
			frappe.throw(_("The material request adjustment must match its native Production Plan."))
		sources = [source for source in plan.mr_items if source.name == row.get("material_request_plan_item")]
		if len(sources) != 1:
			frappe.throw(_("The native material request plan source row is missing."))
		result.append((row, plan, sources[0]))
	return week, result


def _request_signature(doc):
	return sorted(
		(
			row.production_plan,
			row.material_request_plan_item,
			row.item_code,
			row.warehouse,
			str(_date(row.schedule_date)),
			row.uom,
			row.stock_uom,
			_text(_decimal(row.qty)),
			_text(_decimal(row.conversion_factor)),
		)
		for row in doc.get("items") or []
	)


def is_verified_superseded_request(doc, pending_new=None, seen=None, *, lock=True):
	"""A readonly marker excludes stock commitments only with a real matching chain."""
	name = doc.get("custom_meal_superseded_by")
	if not name:
		return False
	seen = set(seen or ())
	if doc.name in seen or name == doc.name or len(seen) > 20:
		frappe.throw(_("The meal request replacement chain is cyclic or invalid."))
	seen.add(doc.name)
	if pending_new is not None and pending_new.name == name:
		new = pending_new
	else:
		new = frappe.get_doc("Material Request", name, for_update=lock)
	if (
		doc.docstatus != 0
		or new.docstatus == 2
		or new.get("custom_meal_replaces") != doc.name
		or new.company != doc.company
		or new.material_request_type != doc.material_request_type
		or not new.owner
		or new.owner == doc.owner
		or _request_signature(doc) != _request_signature(new)
	):
		frappe.throw(_("The superseded meal request has no verified identical replacement."))
	if new.get("custom_meal_superseded_by"):
		is_verified_superseded_request(new, pending_new=pending_new, seen=seen, lock=lock)
	return True


def _same_source_value(field, left, right):
	if field == "conversion_factor":
		return _decimal(left) == _decimal(right)
	if field == "schedule_date" and left and right:
		return _date(left) == _date(right)
	return str(left or "") == str(right or "")


def validate_material_request(doc, method=None):
	"""Register on native MR validate/before_update_after_submit; enforce frozen caps."""
	old = doc.get_doc_before_save()
	if old and (
		doc.get("custom_meal_replaces")
		or doc.get("custom_meal_superseded_by")
		or any(row.get("production_plan") for row in old.get("items") or [])
	):
		_original_creator(doc, "Material Request")
	if not _MANAGED.get():
		for field in _REQUEST_LINKS:
			if str(doc.get(field) or "") != str(old.get(field) or "" if old else ""):
				frappe.throw(
					_("Meal request replacement links can only be set through the controlled reissue action.")
				)
	if doc.get("custom_meal_superseded_by"):
		if not _MANAGED.get():
			frappe.throw(_("This meal request is superseded; use its replacement instead."))
		is_verified_superseded_request(doc)
		return
	if doc.get("custom_meal_replaces"):
		prior = frappe.get_doc("Material Request", doc.custom_meal_replaces)
		if not is_verified_superseded_request(prior, pending_new=doc):
			frappe.throw(_("The reissued meal request has an invalid original source."))
	week, sources = _request_scope(doc, for_update=True)
	if old:
		old_week, _old_sources = _request_scope(old)
		if old_week and (not week or old_week.name != week.name):
			frappe.throw(_("An existing meal request cannot be detached from its native week."))
	if not week or doc.docstatus == 2:
		if not week and _narrow_operator_only():
			frappe.throw(
				_("Meal business operators may only maintain verified meal material requests."),
				frappe.PermissionError,
			)
		return
	_original_creator(doc, "Material Request")
	current = defaultdict(lambda: ZERO)
	source_docs = {}
	old_rows = {row.name: row for row in old.get("items") or []} if old else {}
	protected = (
		"item_code",
		"production_plan",
		"material_request_plan_item",
		"warehouse",
		"schedule_date",
		"uom",
		"stock_uom",
		"conversion_factor",
	)
	for row, plan, source in sources:
		if plan.docstatus != 1 or plan.status in {"Closed", "Completed"}:
			frappe.throw(_("New meal procurement cannot use a draft, closed or completed production plan."))
		previous = old_rows.get(row.name)
		if previous and any(
			not _same_source_value(field, row.get(field), previous.get(field)) for field in protected
		):
			frappe.throw(
				_("A meal request's frozen source, item, warehouse, date and units cannot be edited.")
			)
		if row.item_code != source.item_code or row.warehouse != source.warehouse or row.uom != source.uom:
			frappe.throw(_("The request item, warehouse or purchase unit differs from its frozen source."))
		if (
			not row.schedule_date
			or not source.schedule_date
			or _date(row.schedule_date) != _date(source.schedule_date)
		):
			frappe.throw(_("The meal material request date differs from its frozen requirement date."))
		factor = _decimal(source.conversion_factor)
		item = frappe.get_cached_doc("Item", row.item_code)
		if (
			factor <= ZERO
			or _decimal(row.conversion_factor) != factor
			or _factor(item, row.uom) != factor
			or row.stock_uom != item.stock_uom
		):
			frappe.throw(_("The material request unit conversion is not the verified frozen conversion."))
		quantity = _decimal(row.qty)
		if quantity <= ZERO:
			frappe.throw(_("Meal material request quantities must be positive."))
		stock_qty = quantity * factor
		if row.get("stock_qty") is not None and _decimal(row.stock_qty) != stock_qty:
			frappe.throw(_("The material request stock quantity does not match its purchase quantity."))
		current[source.name] += stock_qty
		source_docs[source.name] = source
	allocated = (
		frappe.db.sql(
			"""SELECT m.name,i.material_request_plan_item,i.stock_qty AS allocated_qty
		FROM `tabMaterial Request Item` i JOIN `tabMaterial Request` m ON m.name=i.parent
		WHERE m.docstatus<2 AND m.name!=%(name)s AND i.material_request_plan_item IN %(sources)s
		FOR UPDATE""",
			{"name": doc.name or "", "sources": sorted(source_docs)},
			as_dict=True,
		)
		if source_docs
		else []
	)
	other = defaultdict(lambda: ZERO)
	for row in allocated:
		prior = frappe.get_doc("Material Request", row.name, for_update=True)
		if is_verified_superseded_request(prior, pending_new=doc):
			continue
		other[row.material_request_plan_item] += _decimal(row.allocated_qty)
	for name, stock_qty in current.items():
		source = source_docs[name]
		cap = _decimal(source.quantity) * _decimal(source.conversion_factor)
		if stock_qty + other.get(name, ZERO) > cap:
			frappe.throw(
				_(
					"All draft and submitted requests together exceed frozen procurement quantity for source {0}."
				).format(name)
			)


def before_submit_material_request(doc, method=None):
	if doc.get("custom_meal_superseded_by"):
		frappe.throw(_("A superseded meal material request cannot be submitted."))
	week, _sources = _request_scope(doc, for_update=True)
	if not week:
		return
	creator = _original_creator(doc, "Material Request", database=True)
	_manager()
	if not creator or frappe.session.user == creator:
		frappe.throw(
			_(
				"A different authorized purchaser must approve the material request; administrators cannot self-approve."
			)
		)
	validate_material_request(doc, method)


@frappe.whitelist(methods=["POST"])
def reissue_material_request_draft(week_name):
	"""Recreate another creator's untouched draft, preserving the entire audit trail."""
	_operator()
	if not frappe.has_permission("Material Request", "create"):
		frappe.throw(_("You do not have permission to create material requests."), frappe.PermissionError)
	week = _week(week_name)
	if week.docstatus != 1 or not week.get("material_request"):
		frappe.throw(_("The submitted week has no material request draft to reissue."))
	from tongjianyun.meal_stock_claims import lock_claim_scope

	lock_claim_scope(week.company)
	frappe.db.sql("SELECT name FROM `tabMeal Planning Week` WHERE name=%s FOR UPDATE", (week.name,))
	week = _week(week.name, for_update=True)
	old = frappe.get_doc("Material Request", week.material_request, for_update=True)
	old.check_permission("write")
	frappe.db.sql("SELECT name FROM `tabMaterial Request` WHERE name=%s FOR UPDATE", (old.name,))
	resolved, _sources = _request_scope(old)
	if not resolved or resolved.name != week.name:
		frappe.throw(_("The request does not belong to this meal week."))
	if old.docstatus != 0 or old.owner == frappe.session.user or old.get("custom_meal_superseded_by"):
		frappe.throw(_("Only another creator's active draft request can be reissued."))
	if frappe.db.exists("Purchase Order Item", {"material_request": old.name}) or frappe.db.exists(
		"Purchase Receipt Item", {"material_request": old.name}
	):
		frappe.throw(
			_("The original request already has downstream purchase documents and cannot be reissued.")
		)
	new = frappe.copy_doc(old)
	new.owner = frappe.session.user
	new.custom_meal_superseded_by = None
	new.custom_meal_replaces = old.name
	from frappe.model.naming import set_new_name

	set_new_name(new)
	with _managed():
		# Set reciprocal names in this same transaction. Validation of the new
		# draft is given its in-memory candidate until insert makes it durable.
		old.db_set("custom_meal_superseded_by", new.name)
		new.insert(set_name=new.name)
		week.db_set("material_request", new.name)
	old.add_comment(
		"Info",
		_(
			"Reissued unchanged as {0} by the current meal purchaser; the original creator is preserved."
		).format(new.name),
	)
	new.add_comment(
		"Info",
		_(
			"This is an identical reissue of draft {0}; its original creator and record remain preserved."
		).format(old.name),
	)
	return {"material_request": new.name, "name": new.name, "replaces": old.name, "created": True}


def verify_week_procurement_settled(week, *, lock=True):
	"""Read-only proof for kitchen reconciliation; unresolved native documents raise."""
	week = _week(week, for_update=lock)
	plans = _plan_names(week, for_update=lock)
	locking = " FOR UPDATE" if lock else ""
	if not plans:
		frappe.throw(_("The meal week has no native production sources to reconcile."))
	request_rows = frappe.db.sql(
		"""SELECT m.name,m.company,m.docstatus,m.status,m.material_request_type,
		i.name AS source_item,i.item_code,i.warehouse,i.schedule_date,i.stock_qty,i.ordered_qty,i.received_qty,
		i.production_plan,i.material_request_plan_item,src.parent AS source_parent,
		src.item_code AS source_item_code,src.warehouse AS source_warehouse
		FROM `tabMaterial Request` m JOIN `tabMaterial Request Item` i ON i.parent=m.name
		LEFT JOIN `tabMaterial Request Plan Item` src ON src.name=i.material_request_plan_item AND src.parent=i.production_plan
		WHERE i.production_plan IN %(plans)s OR m.name=%(main_request)s ORDER BY m.name,i.idx"""
		+ locking,
		{"plans": sorted(plans), "main_request": week.get("material_request") or ""},
		as_dict=True,
	)
	blockers = []
	requests, orders, receipts, closed = [], [], [], []
	request_names = set()
	request_sources = {}
	for row in request_rows:
		request_names.add(row.name)
		request_sources[row.source_item] = row
		if row.docstatus == 2:
			continue
		if row.docstatus == 0:
			original = frappe.get_doc("Material Request", row.name, for_update=lock)
			if is_verified_superseded_request(original, lock=lock):
				requests.append(
					{
						"name": row.name,
						"source_item": row.source_item,
						"docstatus": 0,
						"superseded_by": original.custom_meal_superseded_by,
						"stock_qty": _text(_decimal(row.stock_qty)),
						"excluded_as_verified_superseded": True,
					}
				)
				continue
		valid = (
			row.company == week.company
			and row.material_request_type == "Purchase"
			and row.source_parent in plans
			and row.item_code == row.source_item_code
			and row.warehouse == row.source_warehouse
		)
		if not valid:
			blockers.append(_("Request {0} has an unverified meal source.").format(row.name))
		remaining = max(
			ZERO, _decimal(row.stock_qty) - max(_decimal(row.ordered_qty), _decimal(row.received_qty))
		)
		fact = {
			"name": row.name,
			"source_item": row.source_item,
			"docstatus": row.docstatus,
			"status": row.status,
			"item_code": row.item_code,
			"warehouse": row.warehouse,
			"production_plan": row.production_plan,
			"material_request_plan_item": row.material_request_plan_item,
			"stock_qty": _text(_decimal(row.stock_qty)),
			"ordered_qty": _text(_decimal(row.ordered_qty)),
			"received_qty": _text(_decimal(row.received_qty)),
			"remaining_stock_qty": _text(remaining),
		}
		requests.append(fact)
		if row.docstatus == 0:
			blockers.append(_("Draft material request {0} is still pending.").format(row.name))
		elif row.status == "Stopped":
			closed.append({"doctype": "Material Request", **fact})
		elif remaining > ZERO:
			blockers.append(_("Material request {0} still has unordered quantities.").format(row.name))
	if request_names:
		order_rows = frappe.db.sql(
			"""SELECT p.name,p.company,p.docstatus,p.status,i.name AS source_item,i.item_code,i.warehouse,
			i.qty,i.received_qty,i.conversion_factor,i.material_request,i.material_request_item,i.closed
			FROM `tabPurchase Order` p JOIN `tabPurchase Order Item` i ON i.parent=p.name
			WHERE i.material_request IN %(requests)s ORDER BY p.name,i.idx"""
			+ locking,
			{"requests": sorted(request_names)},
			as_dict=True,
		)
		order_names = set()
		order_sources = {}
		for row in order_rows:
			order_names.add(row.name)
			order_sources[row.source_item] = row
			if row.docstatus == 2:
				continue
			if row.company != week.company:
				blockers.append(_("Order {0} has a company mismatch.").format(row.name))
			request = request_sources.get(row.material_request_item)
			if (
				not request
				or request.docstatus != 1
				or request.name != row.material_request
				or request.item_code != row.item_code
				or request.warehouse != row.warehouse
			):
				blockers.append(_("Order {0} has an invalid native meal request source.").format(row.name))
			remaining = max(
				ZERO, (_decimal(row.qty) - _decimal(row.received_qty)) * _decimal(row.conversion_factor)
			)
			fact = {
				"name": row.name,
				"source_item": row.source_item,
				"docstatus": row.docstatus,
				"status": row.status,
				"item_code": row.item_code,
				"warehouse": row.warehouse,
				"material_request": row.material_request,
				"material_request_item": row.material_request_item,
				"qty": _text(_decimal(row.qty)),
				"received_qty": _text(_decimal(row.received_qty)),
				"conversion_factor": _text(_decimal(row.conversion_factor)),
				"remaining_stock_qty": _text(remaining),
				"line_closed": bool(row.closed),
			}
			orders.append(fact)
			if row.docstatus == 0:
				blockers.append(_("Draft purchase order {0} is still pending.").format(row.name))
			elif row.status == "Closed" or row.closed:
				closed.append({"doctype": "Purchase Order", **fact})
			elif remaining > ZERO:
				blockers.append(_("Purchase order {0} still has unreceived quantities.").format(row.name))
		if order_names:
			receipts = frappe.db.sql(
				"""SELECT r.name,r.docstatus,r.is_return,r.return_against,i.name AS source_item,
				i.purchase_order,i.purchase_order_item,i.item_code,i.warehouse,i.stock_qty
				FROM `tabPurchase Receipt` r JOIN `tabPurchase Receipt Item` i ON i.parent=r.name
				WHERE i.purchase_order IN %(orders)s ORDER BY r.name,i.idx"""
				+ locking,
				{"orders": sorted(order_names)},
				as_dict=True,
			)
			for row in receipts:
				row.stock_qty = _text(_decimal(row.stock_qty))
				if row.docstatus == 0:
					blockers.append(_("Draft purchase receipt {0} is still pending.").format(row.name))
				elif row.docstatus == 1:
					order = order_sources.get(row.purchase_order_item)
					if (
						not order
						or order.docstatus != 1
						or order.name != row.purchase_order
						or order.item_code != row.item_code
						or order.warehouse != row.warehouse
					):
						blockers.append(
							_("Receipt {0} has an invalid native meal order source.").format(row.name)
						)
	if blockers:
		frappe.throw("\n".join(dict.fromkeys(blockers)))
	return {
		"settled": True,
		"week_name": week.name,
		"checked_at": _now(),
		"material_requests": requests,
		"purchase_orders": orders,
		"purchase_receipts": receipts,
		"manually_closed_sources": closed,
	}
