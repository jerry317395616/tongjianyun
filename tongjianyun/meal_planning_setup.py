"""Explicit, narrowly scoped metadata setup; no recipes, users, stock or orders."""
# ruff: noqa: RUF001

import json
from pathlib import Path

import frappe


def install_meal_planning():
	if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
		frappe.throw("需要系统管理员配置食谱业务。", frappe.PermissionError)
	for role in ("食谱编排员", "食谱审核员", "膳食业务经办员"):
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert()
	for target in (
		"meal_plan_meal",
		"meal_kitchen_meal",
		"meal_kitchen_item",
		"meal_adjustment_dish",
		"meal_planning_week",
		"meal_kitchen_day",
		"meal_plan_adjustment",
	):
		frappe.reload_doc("i_one_ai", "doctype", target, force=True)
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	from tongjianyun.meal_population import STUDENT_BATCH_CUSTOM_FIELD

	definitions = json.loads((Path(__file__).parent / "meal_planning_fields.json").read_text())
	definitions += [
		STUDENT_BATCH_CUSTOM_FIELD,
		{
			"dt": "Production Plan",
			"fieldname": "custom_meal_week",
			"label": "食谱周计划",
			"fieldtype": "Link",
			"options": "Meal Planning Week",
			"insert_after": "custom_meal_batch",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"dt": "Production Plan",
			"fieldname": "custom_meal_headcount",
			"label": "计划供餐人数",
			"fieldtype": "Int",
			"insert_after": "custom_meal_week",
			"read_only": 1,
		},
		{
			"dt": "Item",
			"fieldname": "custom_meal_procurement_policy",
			"label": "食谱采购方式",
			"fieldtype": "Select",
			"options": "\n采购\n厨房用水\n厨房自产待配方",
			"insert_after": "is_purchase_item",
			"description": "食谱备料须明确采购方式；厨房用水不生成采购申请，自产配料需先补完整配方。",
		},
	]
	definitions += [
		{
			"dt": "Production Plan",
			"fieldname": "custom_meal_adjustment",
			"label": "食谱单餐变更",
			"fieldtype": "Link",
			"options": "Meal Plan Adjustment",
			"insert_after": "custom_meal_week",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"dt": "Stock Entry",
			"fieldname": "custom_meal_week",
			"label": "食谱周计划",
			"fieldtype": "Link",
			"options": "Meal Planning Week",
			"insert_after": "company",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"dt": "Stock Entry",
			"fieldname": "custom_meal_kitchen_day",
			"label": "厨房每日执行",
			"fieldtype": "Link",
			"options": "Meal Kitchen Day",
			"insert_after": "custom_meal_week",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"dt": "Stock Entry",
			"fieldname": "custom_meal_action",
			"label": "厨房业务",
			"fieldtype": "Select",
			"options": "\n领用\n退料\n耗用\n损耗",
			"insert_after": "custom_meal_kitchen_day",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"dt": "Stock Entry Detail",
			"fieldname": "custom_meal_issue_detail",
			"label": "领用明细来源",
			"fieldtype": "Data",
			"insert_after": "item_code",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"dt": "Stock Entry",
			"fieldname": "custom_meal_raw_claim_snapshot",
			"label": "膳食原料库存份额依据",
			"fieldtype": "Long Text",
			"insert_after": "custom_meal_action",
			"read_only": 1,
			"hidden": 1,
			"no_copy": 1,
		},
		{
			"dt": "Purchase Order",
			"fieldname": "custom_meal_week",
			"label": "食谱周计划",
			"fieldtype": "Link",
			"options": "Meal Planning Week",
			"insert_after": "company",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"dt": "Purchase Order",
			"fieldname": "custom_meal_quote_snapshot",
			"label": "食谱采购报价确认",
			"fieldtype": "Long Text",
			"insert_after": "custom_meal_week",
			"read_only": 1,
			"hidden": 1,
			"no_copy": 1,
		},
		{
			"dt": "Material Request",
			"fieldname": "custom_meal_adjustment",
			"label": "食谱单餐变更",
			"fieldtype": "Link",
			"options": "Meal Plan Adjustment",
			"insert_after": "company",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"dt": "Material Request",
			"fieldname": "custom_meal_superseded_by",
			"label": "已由采购申请替代",
			"fieldtype": "Link",
			"options": "Material Request",
			"insert_after": "custom_meal_adjustment",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"dt": "Material Request",
			"fieldname": "custom_meal_replaces",
			"label": "替代原采购申请",
			"fieldtype": "Link",
			"options": "Material Request",
			"insert_after": "custom_meal_superseded_by",
			"read_only": 1,
			"no_copy": 1,
		},
	]
	missing = {}
	for definition in definitions:
		item = dict(definition)
		dt = item.pop("dt")
		if not frappe.get_meta(dt).has_field(item["fieldname"]):
			missing.setdefault(dt, []).append(item)
	if missing:
		create_custom_fields(missing, update=False)
	frappe.reload_doc("i_one_ai", "report", "meal_ingredient_requirements", force=True)
	_install_operator_permissions()
	reservation_indexes = []
	for doctype in ("Production Plan", "Work Order"):
		if not frappe.db.sql(
			"SELECT INDEX_NAME FROM information_schema.STATISTICS "
			"WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s "
			"AND COLUMN_NAME='company' AND SEQ_IN_INDEX=1 LIMIT 1",
			(f"tab{doctype}",),
		):
			frappe.db.add_index(doctype, ["company"], index_name="meal_company")
			reservation_indexes.append(doctype)
	for source, translated in {
		"Meal Planning Week": "周食谱编排",
		"Meal Plan Meal": "食谱餐次",
		"Tongjianyun Weekly Menu": "周带量食谱",
		"Meal Ingredient Requirements": "食材备料需求",
		"Meal Kitchen Day": "厨房每日执行",
		"Meal Plan Adjustment": "食谱单餐变更",
		"Stock is based on the ledger and has not been represented as a physical stock count.": "库存依据为账面记录，尚未声明完成实物盘点。",
		"Some ingredients have no valid buying price. The request specifies quantity only; obtain quotations before placing orders.": "部分食材尚无有效采购价格。申请仅核定数量，请完成询价后再下单。",
		"Overdue or undated purchase orders are shown as unconfirmed and do not reduce this request.": "逾期或未注明到货日期的采购订单视为待确认，不抵扣本次采购需求。",
		"Overdue or undated material requests need review and do not reduce this request.": "逾期或未注明需求日期的采购申请需要核对，不抵扣本次采购需求。",
		"Meal week {0} has an unreconciled stock commitment. Reconcile it before requesting procurement for another week.": "周计划 {0} 的库存占用尚未完成核销，请核销后再生成另一周的采购需求。",
		"Stock, incoming supply, recipe, or procurement settings changed after review. Revise and review the meal week.": "库存、到货、配方或采购设置已发生变化，请修订并重新审核周食谱。",
	}.items():
		if not frappe.db.exists("Translation", {"language": "zh", "source_text": source}):
			frappe.get_doc(
				{
					"doctype": "Translation",
					"language": "zh",
					"source_text": source,
					"translated_text": translated,
				}
			).insert()
	for dt in (
		"Student",
		"Item",
		"Production Plan",
		"Meal Planning Week",
		"Stock Entry",
		"Material Request",
		"Purchase Order",
	):
		frappe.clear_cache(doctype=dt)
	return {
		"doctype": "Meal Planning Week",
		"created_fields": sum(map(len, missing.values())),
		"reservation_indexes_created": reservation_indexes,
		"reports": ["Tongjianyun Weekly Menu", "Meal Ingredient Requirements"],
	}


def _install_operator_permissions():
	"""Preserve native role rules and give operators their own unsubmitted drafts."""
	from frappe.permissions import add_permission

	role = "膳食业务经办员"
	for doctype in ("Stock Entry", "Material Request", "Purchase Order", "Supplier Quotation"):
		if not frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0}):
			add_permission(doctype, role)
		rule = frappe.get_doc(
			"Custom DocPerm",
			frappe.db.get_value("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0}, "name"),
		)
		for ptype in ("read", "write", "create", "report", "print", "export"):
			rule.set(ptype, 1)
		for ptype in ("submit", "cancel", "amend", "delete", "share", "email"):
			rule.set(ptype, 0)
		rule.if_owner = 1
		rule.save()
		frappe.clear_cache(doctype=doctype)
	# These are links and recipe masters needed to enter the authorized drafts.
	for doctype in (
		"Item",
		"BOM",
		"Warehouse",
		"Company",
		"Supplier",
		"UOM",
		"Price List",
		"Currency",
		"Academic Year",
		"Academic Term",
	):
		if not frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0}):
			add_permission(doctype, role)
		frappe.clear_cache(doctype=doctype)
	# Native Supplier Quotation / Purchase Order currency validation checks the
	# supplier's payable Account permission. This is a link master, not a ledger
	# transaction permission; native Company User Permissions remain applicable.
	account_filters = {"parent": "Account", "role": role, "permlevel": 0}
	if not frappe.db.exists("Custom DocPerm", account_filters):
		add_permission("Account", role)
	account_rule = frappe.get_doc(
		"Custom DocPerm", frappe.db.get_value("Custom DocPerm", account_filters, "name")
	)
	for ptype in ("read", "select"):
		account_rule.set(ptype, 1)
	for ptype in (
		"write",
		"create",
		"submit",
		"cancel",
		"amend",
		"delete",
		"report",
		"print",
		"export",
		"import",
		"share",
		"email",
	):
		account_rule.set(ptype, 0)
	account_rule.if_owner = 0
	account_rule.save()
	frappe.clear_cache(doctype="Account")
