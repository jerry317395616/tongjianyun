"""Fail closed before native PP reservation writes in an old RR snapshot.

The deployed ERPNext reservation service reads open Production Plans' raw and
in-house subassembly requirements, and subtracts submitted Work Order raw
requirements by source warehouse with cross-warehouse allocation. This module
does not replace that algorithm or write Bin. It verifies and locks a superset
of its company-scoped inputs before the caller invokes the official method.
"""
# ruff: noqa: RUF001

import hashlib
import json

import frappe
from frappe import _

_PARENTS = ("Production Plan", "Work Order")
_CHILDREN = (
	("Material Request Plan Item", "Production Plan"),
	("Production Plan Sub Assembly Item", "Production Plan"),
	("Work Order Item", "Work Order"),
)


def _company_index(doctype):
	indexes = frappe.db.sql(
		"""SELECT INDEX_NAME AS index_name FROM information_schema.STATISTICS
		WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s
		AND COLUMN_NAME='company' AND SEQ_IN_INDEX=1 ORDER BY INDEX_NAME""",
		(f"tab{doctype}",),
		as_dict=True,
	)
	if not indexes:
		frappe.throw(
			_("{0} 缺少公司范围索引，请管理员完成库存核算索引配置后重试。").format(doctype)
		)
	return str(indexes[0]["index_name"]).replace("`", "``")


def _inputs(company, indexes, lock):
	result = {}
	for doctype in _PARENTS:
		# Force the company-leading range so the current read holds next-key
		# locks against new same-company parents, not only existing row IDs.
		result[doctype] = frappe.db.sql(
			f"SELECT * FROM `tab{doctype}` FORCE INDEX (`{indexes[doctype]}`) "
			"WHERE company=%s ORDER BY name" + (" FOR UPDATE" if lock else ""),
			(company,),
			as_dict=True,
		)
	for doctype, parent_type in _CHILDREN:
		parents = sorted(row["name"] for row in result[parent_type])
		result[doctype] = (
			frappe.db.sql(
				f"SELECT * FROM `tab{doctype}` WHERE parent IN %(parents)s "
				"ORDER BY parent,idx,name" + (" FOR UPDATE" if lock else ""),
				{"parents": parents},
				as_dict=True,
			)
			if parents
			else []
		)
	return result


def _fingerprint(rows):
	return hashlib.sha256(
		json.dumps(rows, sort_keys=True, default=str, ensure_ascii=False).encode()
	).hexdigest()


def ensure_current_native_reservation_inputs(company):
	"""Lock native reservation inputs or refuse a stale transaction without writes.

	Read all statuses and all columns conservatively: a concurrent transition
	from draft to submitted or from open to closed matters to the official
	queries. Parent company ranges and child-parent ranges remain locked until
	the caller's transaction ends. The caller's own writes appear in both views.
	No transaction is committed, isolation changed, or quantity recomputed here.
	"""
	if not isinstance(company, str) or not company.strip():
		frappe.throw(_("请提供原生库存核算所属园所。"))
	indexes = {doctype: _company_index(doctype) for doctype in _PARENTS}
	snapshot = _inputs(company, indexes, lock=False)
	current = _inputs(company, indexes, lock=True)
	if _fingerprint(snapshot) != _fingerprint(current):
		frappe.throw(
			_("并发业务已改变生产计划或工单库存依据；请刷新页面并重试，不沿用旧事务核算库存。")
		)
	return {"company": company, "locked": True, "input_hash": _fingerprint(current)}
