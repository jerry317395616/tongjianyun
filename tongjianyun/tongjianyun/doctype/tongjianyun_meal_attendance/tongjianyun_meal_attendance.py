from __future__ import annotations

from math import floor

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate, nowdate


CLASS_DOCTYPE = "Tongjianyun Class"
ATTENDANCE_DOCTYPE = "Tongjianyun Meal Attendance"


def _active_classes() -> list[dict]:
	if not frappe.db.table_exists(CLASS_DOCTYPE):
		return []
	return frappe.get_all(
		CLASS_DOCTYPE,
		filters={"status": "active"},
		fields=["class_id", "class_name", "sort_order"],
		order_by="sort_order asc, class_name asc",
	)


def _as_non_negative_int(value, label: str) -> int:
	try:
		number = int(value or 0)
	except (TypeError, ValueError):
		frappe.throw(_("{0}必须填写整数").format(label))
	if number < 0:
		frappe.throw(_("{0}不能小于 0").format(label))
	return number


class TongjianyunMealAttendance(Document):
	def before_validate(self):
		self._normalize_month()
		self._ensure_class_rows()
		self._normalize_rows()
		self._calculate_totals()
		if not self.prepared_by and frappe.session.user != "Guest":
			self.prepared_by = (
				frappe.db.get_value("User", frappe.session.user, "full_name")
				or frappe.session.user
			)

	def validate(self):
		duplicate = frappe.db.exists(
			ATTENDANCE_DOCTYPE,
			{"month": self.month, "name": ["!=", self.name or ""]},
		)
		if duplicate:
			frappe.throw(_("{0}已经存在就餐人数记录：{1}").format(self.month_label, duplicate))

	def _normalize_month(self):
		value = getdate(self.month or nowdate())
		self.month = value.replace(day=1)
		self.month_label = f"{value.year}年{value.month}月"

	def _ensure_class_rows(self):
		if self.details:
			return
		for row in _active_classes():
			self.append(
				"details",
				{
					"class_id": row.class_id,
					"class_name": row.class_name,
					"breakfast_count": 0,
					"lunch_count": 0,
					"dinner_count": 0,
					"sort_order": row.sort_order or 10,
				},
			)

	def _normalize_rows(self):
		seen: set[str] = set()
		for row in self.details:
			class_key = (row.class_id or row.class_name or "").strip()
			if not class_key:
				frappe.throw(_("就餐人数表中存在未指定班级的行"))
			if class_key in seen:
				frappe.throw(_("班级 {0} 重复出现").format(row.class_name or class_key))
			seen.add(class_key)
			row.breakfast_count = _as_non_negative_int(row.breakfast_count, f"{row.class_name}早餐人数")
			row.lunch_count = _as_non_negative_int(row.lunch_count, f"{row.class_name}午餐人数")
			row.dinner_count = _as_non_negative_int(row.dinner_count, f"{row.class_name}晚餐人数")

	def _calculate_totals(self):
		self.breakfast_total = sum(int(row.breakfast_count or 0) for row in self.details)
		self.lunch_total = sum(int(row.lunch_count or 0) for row in self.details)
		self.dinner_total = sum(int(row.dinner_count or 0) for row in self.details)
		self.total_meal_times = self.breakfast_total + self.lunch_total + self.dinner_total
		self.total_person_days = floor(self.total_meal_times / 3 + 0.5)


@frappe.whitelist()
def get_active_classes() -> list[dict]:
	if frappe.session.user == "Guest":
		frappe.throw(_("请先登录"), frappe.AuthenticationError)
	return [dict(row) for row in _active_classes()]


def _month_start(value=None):
	month = getdate(value or nowdate())
	return month.replace(day=1)


def _serialize(doc: Document) -> dict:
	return {
		"name": doc.name if not doc.is_new() else "",
		"month": str(doc.month),
		"month_label": doc.month_label,
		"status": doc.status or "草稿",
		"prepared_by": doc.prepared_by or "",
		"remark": doc.remark or "",
		"breakfast_total": cint(doc.breakfast_total),
		"lunch_total": cint(doc.lunch_total),
		"dinner_total": cint(doc.dinner_total),
		"total_meal_times": cint(doc.total_meal_times),
		"total_person_days": cint(doc.total_person_days),
		"modified": str(doc.modified or ""),
		"details": [
			{
				"class_id": row.class_id,
				"class_name": row.class_name,
				"breakfast_count": cint(row.breakfast_count),
				"lunch_count": cint(row.lunch_count),
				"dinner_count": cint(row.dinner_count),
				"sort_order": cint(row.sort_order),
			}
			for row in doc.details
		],
	}


def _require_login():
	if frappe.session.user == "Guest":
		frappe.throw(_("请先登录"), frappe.AuthenticationError)


@frappe.whitelist()
def get_meal_attendance(month=None) -> dict:
	_require_login()
	month = _month_start(month)
	name = frappe.db.get_value(ATTENDANCE_DOCTYPE, {"month": month}, "name")
	if name:
		doc = frappe.get_doc(ATTENDANCE_DOCTYPE, name)
		doc.check_permission("read")
	else:
		doc = frappe.new_doc(ATTENDANCE_DOCTYPE)
		doc.month = month
		doc.status = "草稿"
		doc._normalize_month()
		doc._ensure_class_rows()
		doc._calculate_totals()
	return _serialize(doc)


@frappe.whitelist()
def list_meal_attendance(limit=24) -> list[dict]:
	_require_login()
	frappe.has_permission(ATTENDANCE_DOCTYPE, "read", throw=True)
	rows = frappe.get_all(
		ATTENDANCE_DOCTYPE,
		fields=[
			"name",
			"month",
			"month_label",
			"status",
			"prepared_by",
			"breakfast_total",
			"lunch_total",
			"dinner_total",
			"total_meal_times",
			"total_person_days",
			"modified",
		],
		order_by="month desc",
		limit_page_length=min(max(cint(limit), 1), 120),
	)
	return [{**dict(row), "month": str(row.month), "modified": str(row.modified)} for row in rows]


@frappe.whitelist(methods=["POST"])
def save_meal_attendance(record) -> dict:
	_require_login()
	record = frappe.parse_json(record) if isinstance(record, str) else record
	if not isinstance(record, dict):
		frappe.throw(_("就餐人数记录格式不正确"))

	name = (record.get("name") or "").strip()
	if name:
		doc = frappe.get_doc(ATTENDANCE_DOCTYPE, name)
		doc.check_permission("write")
	else:
		doc = frappe.new_doc(ATTENDANCE_DOCTYPE)
		doc.check_permission("create")

	doc.month = _month_start(record.get("month"))
	doc.status = record.get("status") if record.get("status") in ("草稿", "已确认") else "草稿"
	doc.remark = record.get("remark") or ""
	if record.get("prepared_by"):
		doc.prepared_by = str(record.get("prepared_by"))[:140]

	doc.set("details", [])
	for index, row in enumerate(record.get("details") or []):
		doc.append(
			"details",
			{
				"class_id": row.get("class_id") or "",
				"class_name": row.get("class_name") or "",
				"breakfast_count": row.get("breakfast_count") or 0,
				"lunch_count": row.get("lunch_count") or 0,
				"dinner_count": row.get("dinner_count") or 0,
				"sort_order": row.get("sort_order") or (index + 1) * 10,
			},
		)

	if doc.is_new():
		doc.insert()
	else:
		doc.save()
	return _serialize(doc)


@frappe.whitelist(methods=["POST"])
def delete_meal_attendance(name) -> dict:
	_require_login()
	doc = frappe.get_doc(ATTENDANCE_DOCTYPE, name)
	doc.check_permission("delete")
	result = {"name": doc.name, "month_label": doc.month_label}
	frappe.delete_doc(ATTENDANCE_DOCTYPE, doc.name)
	return result
