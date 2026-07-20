from __future__ import annotations

import json

import frappe
from frappe.utils.print_utils import get_print


ATTENDANCE_DOCTYPE = "Tongjianyun Meal Attendance"
PRINT_FORMAT_NAME = "就餐人数记录表"
WORKSPACE_NAME = "童健云"
SERVICE_ROLE = "Tongjianyun Service"
SERVICE_USERS = ("tongjianyun.service@myyr.top",)


PRINT_HTML = r"""
<div class="tjy-meal-attendance-print">
  <div class="tjy-print-heading">
    <div class="tjy-print-meta">
      <div>儿童营养表3</div>
      <div>{{ doc.month_label or frappe.utils.formatdate(doc.month, "yyyy年M月") }}</div>
    </div>
    <h1>就餐人数记录表</h1>
    <div></div>
  </div>

  <table class="tjy-print-table">
    <thead>
      <tr>
        <th>班级</th>
        <th>早餐</th>
        <th>午餐</th>
        <th>晚餐</th>
      </tr>
    </thead>
    <tbody>
      {% for row in doc.details %}
      <tr>
        <td>{{ row.class_name }}</td>
        <td>{{ row.breakfast_count or 0 }}</td>
        <td>{{ row.lunch_count or 0 }}</td>
        <td>{{ row.dinner_count or 0 }}</td>
      </tr>
      {% endfor %}
      <tr class="tjy-total-row">
        <td>合计</td>
        <td>{{ doc.breakfast_total or 0 }}</td>
        <td>{{ doc.lunch_total or 0 }}</td>
        <td>{{ doc.dinner_total or 0 }}</td>
      </tr>
      <tr class="tjy-total-row">
        <td>总人次数</td>
        <td colspan="3">{{ doc.total_meal_times or 0 }}</td>
      </tr>
      <tr class="tjy-total-row">
        <td>总人日数</td>
        <td colspan="3">{{ doc.total_person_days or 0 }}</td>
      </tr>
    </tbody>
  </table>

  {% if doc.remark %}
  <div class="tjy-print-remark">备注：{{ doc.remark }}</div>
  {% endif %}
</div>
"""


PRINT_CSS = r"""
@page {
  size: A4 landscape;
  margin: 10mm 12mm;
}

.print-format {
  padding: 0 !important;
  font-family: "Noto Serif SC", "Songti SC", "SimSun", serif;
  color: #111;
}

.tjy-meal-attendance-print {
  width: 100%;
}

.tjy-print-heading {
  display: grid;
  grid-template-columns: 1fr 2fr 1fr;
  align-items: start;
  margin-bottom: 14px;
}

.tjy-print-meta {
  font-size: 12pt;
  line-height: 1.65;
}

.tjy-print-heading h1 {
  margin: 20px 0 0;
  text-align: center;
  font-size: 22pt;
  font-weight: 700;
  letter-spacing: 5px;
}

.tjy-print-table {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
  border: 1.6pt solid #111;
  font-size: 12pt;
}

.tjy-print-table th,
.tjy-print-table td {
  height: 34px;
  padding: 4px 8px;
  text-align: center;
  vertical-align: middle;
  border: 0.8pt solid #111;
}

.tjy-print-table th {
  font-weight: 700;
}

.tjy-print-table th:first-child,
.tjy-print-table td:first-child {
  width: 28%;
}

.tjy-total-row td {
  font-weight: 700;
}

.tjy-print-remark {
  margin-top: 8px;
  font-size: 10.5pt;
}
"""


def install():
	"""Install database-backed records that accompany the standard DocTypes."""
	install_service_role()
	install_print_format()
	install_workspace_entry()
	frappe.clear_cache()
	frappe.db.commit()


def install_service_role():
	if not frappe.db.exists("Role", SERVICE_ROLE):
		role = frappe.new_doc("Role")
		role.role_name = SERVICE_ROLE
		role.desk_access = 0
		role.insert(ignore_permissions=True)

	for user_name in SERVICE_USERS:
		if not frappe.db.exists("User", user_name):
			continue
		user = frappe.get_doc("User", user_name)
		if SERVICE_ROLE not in frappe.get_roles(user_name):
			user.add_roles(SERVICE_ROLE)


def install_print_format():
	if frappe.db.exists("Print Format", PRINT_FORMAT_NAME):
		print_format = frappe.get_doc("Print Format", PRINT_FORMAT_NAME)
	else:
		print_format = frappe.new_doc("Print Format")
		print_format.name = PRINT_FORMAT_NAME

	print_format.update(
		{
			"print_format_for": "DocType",
			"doc_type": ATTENDANCE_DOCTYPE,
			"module": "Tongjianyun",
			"standard": "No",
			"custom_format": 1,
			"print_format_type": "Jinja",
			"html": PRINT_HTML,
			"css": PRINT_CSS,
			"disabled": 0,
			"margin_top": 10,
			"margin_bottom": 10,
			"margin_left": 12,
			"margin_right": 12,
		}
	)
	print_format.save(ignore_permissions=True)

	if frappe.get_meta("DocType").has_field("default_print_format"):
		frappe.db.set_value("DocType", ATTENDANCE_DOCTYPE, "default_print_format", PRINT_FORMAT_NAME)


def install_workspace_entry():
	if not frappe.db.exists("Workspace", WORKSPACE_NAME):
		return

	workspace = frappe.get_doc("Workspace", WORKSPACE_NAME)
	changed = False

	if not any(row.link_to == ATTENDANCE_DOCTYPE for row in workspace.links):
		new_link = workspace.append(
			"links",
			{
				"type": "Link",
				"label": "就餐人数记录",
				"hidden": 0,
				"link_type": "DocType",
				"link_to": ATTENDANCE_DOCTYPE,
				"link_count": 0,
				"onboard": 0,
				"is_query_report": 0,
			},
		)
		workspace.links.remove(new_link)
		insert_at = len(workspace.links)
		for index, row in enumerate(workspace.links):
			if row.type == "Card Break" and row.label == "膳食营养":
				insert_at = index + int(row.link_count or 0) + 1
				row.link_count = int(row.link_count or 0) + 1
				break
		workspace.links.insert(insert_at, new_link)
		for index, row in enumerate(workspace.links, start=1):
			row.idx = index
		changed = True

	if not any(row.link_to == ATTENDANCE_DOCTYPE for row in workspace.shortcuts):
		workspace.append(
			"shortcuts",
			{
				"type": "DocType",
				"link_to": ATTENDANCE_DOCTYPE,
				"doc_view": "List",
				"label": "就餐人数记录",
				"color": "Green",
				"stats_filter": "[]",
			},
		)
		changed = True

	if not any(row.link_to == ATTENDANCE_DOCTYPE for row in workspace.sidebar_items):
		workspace.append(
			"sidebar_items",
			{
				"type": "Link",
				"label": "就餐人数记录",
				"link_type": "DocType",
				"link_to": ATTENDANCE_DOCTYPE,
				"icon": "circle-dot",
				"default_workspace": 0,
				"child": 0,
				"open_in_new_tab": 0,
				"collapsible": 1,
				"indent": 0,
				"keep_closed": 0,
				"show_arrow": 0,
			},
		)
		changed = True

	content = json.loads(workspace.content or "[]")
	if not any(
		block.get("type") == "shortcut"
		and block.get("data", {}).get("shortcut_name") == "就餐人数记录"
		for block in content
	):
		new_block = {
			"id": "tjyMealAttendance",
			"type": "shortcut",
			"data": {"shortcut_name": "就餐人数记录", "col": 3},
		}
		insert_at = next(
			(index + 1 for index, block in enumerate(content) if block.get("data", {}).get("shortcut_name") == "膳食营养"),
			len(content),
		)
		content.insert(insert_at, new_block)
		workspace.content = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
		changed = True

	if changed:
		workspace.save(ignore_permissions=True)


def verify():
	"""Create, render and remove a temporary document to verify the full workflow."""
	if not frappe.db.exists("DocType", ATTENDANCE_DOCTYPE):
		frappe.throw(f"{ATTENDANCE_DOCTYPE} is not installed")
	if not frappe.db.exists("Print Format", PRINT_FORMAT_NAME):
		frappe.throw(f"{PRINT_FORMAT_NAME} is not installed")

	test_month = "2099-12-01"
	old_test = frappe.db.get_value(ATTENDANCE_DOCTYPE, {"month": test_month}, "name")
	if old_test:
		frappe.delete_doc(ATTENDANCE_DOCTYPE, old_test, force=True, ignore_permissions=True)

	doc = frappe.new_doc(ATTENDANCE_DOCTYPE)
	doc.month = test_month
	doc.status = "草稿"
	doc.insert(ignore_permissions=True)
	if not doc.details:
		doc.append(
			"details",
			{
				"class_id": "VERIFY",
				"class_name": "验证班级",
				"breakfast_count": 0,
				"lunch_count": 0,
				"dinner_count": 0,
				"sort_order": 1,
			},
		)

	for row in doc.details:
		row.breakfast_count = 1
		row.lunch_count = 2
		row.dinner_count = 3
	doc.save(ignore_permissions=True)

	row_count = len(doc.details)
	expected = {
		"breakfast_total": row_count,
		"lunch_total": row_count * 2,
		"dinner_total": row_count * 3,
		"total_meal_times": row_count * 6,
		"total_person_days": row_count * 2,
	}
	actual = {fieldname: int(doc.get(fieldname) or 0) for fieldname in expected}
	if actual != expected:
		frappe.throw(f"Total verification failed: expected {expected}, got {actual}")

	html = get_print(
		doctype=ATTENDANCE_DOCTYPE,
		name=doc.name,
		print_format=PRINT_FORMAT_NAME,
		as_pdf=False,
		no_letterhead=1,
	)
	print_ok = all(marker in html for marker in ("就餐人数记录表", "验证班级" if row_count == 1 else "总人次数"))
	name = doc.name
	frappe.delete_doc(ATTENDANCE_DOCTYPE, name, force=True, ignore_permissions=True)
	frappe.db.commit()
	if not print_ok:
		frappe.throw("Print HTML verification failed")

	return {
		"doctype": ATTENDANCE_DOCTYPE,
		"print_format": PRINT_FORMAT_NAME,
		"workspace": WORKSPACE_NAME,
		"class_rows": row_count,
		"totals": actual,
		"print_html_bytes": len(html.encode("utf-8")),
		"temporary_document_removed": not frappe.db.exists(ATTENDANCE_DOCTYPE, name),
	}
