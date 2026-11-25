import json

WORKSPACE_NAME = "Education"
WORKSPACE_TITLE = "Education"

NUMBER_CARD_SPECS = (
	{
		"name": "教育在籍学生",
		"document_type": "Student",
		"filters_json": '[["Student","enabled","=",1]]',
		"show_percentage_stats": 1,
	},
	{
		"name": "教育在职教师",
		"document_type": "Instructor",
		"filters_json": '[["Instructor","status","=","Active"]]',
		"show_percentage_stats": 1,
	},
	{
		"name": "教育待审申请",
		"document_type": "Student Applicant",
		"filters_json": '[["Student Applicant","application_status","=","Applied"]]',
		"show_percentage_stats": 1,
	},
	{
		"name": "教育本月考勤",
		"document_type": "Student Attendance",
		"filters_json": '[["Student Attendance","date","Timespan","this month"]]',
		"show_percentage_stats": 1,
	},
)

DASHBOARD_CHART_SPECS = (
	{
		"name": "教育招生申请趋势",
		"chart_type": "Count",
		"document_type": "Student Applicant",
		"based_on": "application_date",
		"timespan": "Last Year",
		"time_interval": "Monthly",
		"timeseries": 1,
		"type": "Line",
		"show_values_over_chart": 1,
		"filters_json": "[]",
	},
	{
		"name": "教育招生状态分布",
		"chart_type": "Group By",
		"document_type": "Student Applicant",
		"group_by_type": "Count",
		"group_by_based_on": "application_status",
		"timespan": "Last Year",
		"time_interval": "Yearly",
		"type": "Donut",
		"filters_json": "[]",
	},
	{
		"name": "教育培养项目分布",
		"chart_type": "Group By",
		"document_type": "Program Enrollment",
		"group_by_type": "Count",
		"group_by_based_on": "program",
		"timespan": "Last Year",
		"time_interval": "Yearly",
		"type": "Bar",
		"filters_json": "[]",
	},
	{
		"name": "教育本月出勤状态",
		"chart_type": "Group By",
		"document_type": "Student Attendance",
		"group_by_type": "Count",
		"group_by_based_on": "status",
		"timespan": "Last Year",
		"time_interval": "Yearly",
		"type": "Donut",
		"filters_json": '[["Student Attendance","date","Timespan","this month"]]',
	},
)

SHORTCUT_SPECS = (
	("招生申请", "DocType", "Student Applicant", "Orange"),
	("学生档案", "DocType", "Student", "Blue"),
	("班级管理", "DocType", "Student Group", "Cyan"),
	("课程安排", "DocType", "Course Schedule", "Green"),
	("录入考勤", "DocType", "Student Attendance Tool", "Blue"),
	("考核计划", "DocType", "Assessment Plan", "Purple"),
	("收费记录", "DocType", "Fees", "Yellow"),
	("月度考勤表", "Report", "Student Monthly Attendance Sheet", "Grey"),
)

CARD_GROUPS = (
	(
		"招生与学籍",
		(
			("招生申请", "DocType", "Student Applicant"),
			("招生计划", "DocType", "Student Admission"),
			("学生档案", "DocType", "Student"),
			("培养项目注册", "DocType", "Program Enrollment"),
			("课程注册", "DocType", "Course Enrollment"),
			("监护人", "DocType", "Guardian"),
		),
	),
	(
		"教学与班级",
		(
			("学年", "DocType", "Academic Year"),
			("学期", "DocType", "Academic Term"),
			("培养项目", "DocType", "Program"),
			("课程", "DocType", "Course"),
			("学生班级", "DocType", "Student Group"),
			("课程安排", "DocType", "Course Schedule"),
		),
	),
	(
		"师资与资源",
		(
			("教师", "DocType", "Instructor"),
			("教室", "DocType", "Room"),
			("主题", "DocType", "Topic"),
			("文章", "DocType", "Article"),
			("视频", "DocType", "Video"),
			("测验", "DocType", "Quiz"),
		),
	),
	(
		"考勤与请假",
		(
			("学生考勤", "DocType", "Student Attendance"),
			("请假申请", "DocType", "Student Leave Application"),
			("考勤录入工具", "DocType", "Student Attendance Tool"),
			("缺勤学生报表", "Report", "Absent Student Report"),
			("月度考勤表", "Report", "Student Monthly Attendance Sheet"),
			("按批次考勤报表", "Report", "Student Batch-Wise Attendance"),
		),
	),
	(
		"考核与成绩",
		(
			("考核计划", "DocType", "Assessment Plan"),
			("考核标准", "DocType", "Assessment Criteria"),
			("考核结果", "DocType", "Assessment Result"),
			("评分等级", "DocType", "Grading Scale"),
			("课程考核报表", "Report", "Course wise Assessment Report"),
			("最终成绩报表", "Report", "Final Assessment Grades"),
		),
	),
	(
		"收费与报表",
		(
			("收费记录", "DocType", "Fees"),
			("收费标准", "DocType", "Fee Structure"),
			("收费类别", "DocType", "Fee Category"),
			("销售发票", "DocType", "Sales Invoice"),
			("学生收费报表", "Report", "Student Fee Collection"),
			("培养项目收费报表", "Report", "Program wise Fee Collection"),
		),
	),
)


def _link(label, link_type, link_to, *, icon="", child=0):
	return {
		"type": "Link",
		"label": label,
		"link_type": link_type,
		"link_to": link_to,
		"icon": icon,
		"default_workspace": 0,
		"child": child,
		"open_in_new_tab": 0,
		"collapsible": 1,
		"indent": 0,
		"keep_closed": 0,
		"show_arrow": 0,
	}


def _section(label, icon):
	return {
		"type": "Section Break",
		"label": label,
		"link_type": "DocType",
		"link_to": "",
		"icon": icon,
		"default_workspace": 0,
		"child": 0,
		"open_in_new_tab": 0,
		"collapsible": 1,
		"indent": 1,
		"keep_closed": 1,
		"show_arrow": 0,
	}


def build_sidebar_items():
	items = [
		_link("主页", "Workspace", WORKSPACE_NAME, icon="house"),
		_link("招生申请", "DocType", "Student Applicant", icon="user-plus"),
		_link("学生档案", "DocType", "Student", icon="users"),
		_link("班级管理", "DocType", "Student Group", icon="users-round"),
		_link("课程安排", "DocType", "Course Schedule", icon="calendar-days"),
		_link("学生考勤", "DocType", "Student Attendance Tool", icon="clipboard-check"),
		_link("考核计划", "DocType", "Assessment Plan", icon="clipboard-list"),
		_link("收费管理", "DocType", "Fees", icon="wallet-cards"),
	]
	sections = (
		(
			"招生与学籍",
			"user-round-plus",
			(
				("招生计划", "DocType", "Student Admission"),
				("培养项目注册", "DocType", "Program Enrollment"),
				("培养项目批量注册", "DocType", "Program Enrollment Tool"),
				("课程注册", "DocType", "Course Enrollment"),
				("监护人", "DocType", "Guardian"),
				("学生日志", "DocType", "Student Log"),
				("学生报告生成", "DocType", "Student Report Generation Tool"),
				("学生及监护人联系方式", "Report", "Student and Guardian Contact Details"),
			),
		),
		(
			"教学管理",
			"book-open",
			(
				("学年", "DocType", "Academic Year"),
				("学期", "DocType", "Academic Term"),
				("培养项目", "DocType", "Program"),
				("课程", "DocType", "Course"),
				("主题", "DocType", "Topic"),
				("课程活动", "DocType", "Course Activity"),
				("教师", "DocType", "Instructor"),
				("教室", "DocType", "Room"),
				("班级创建工具", "DocType", "Student Group Creation Tool"),
				("课程排课工具", "DocType", "Course Scheduling Tool"),
			),
		),
		(
			"考勤与请假",
			"calendar-check",
			(
				("学生考勤记录", "DocType", "Student Attendance"),
				("请假申请", "DocType", "Student Leave Application"),
				("缺勤学生报表", "Report", "Absent Student Report"),
				("月度考勤表", "Report", "Student Monthly Attendance Sheet"),
				("按批次考勤报表", "Report", "Student Batch-Wise Attendance"),
			),
		),
		(
			"考核与成绩",
			"chart-no-axes-column",
			(
				("考核标准", "DocType", "Assessment Criteria"),
				("考核组", "DocType", "Assessment Group"),
				("考核结果", "DocType", "Assessment Result"),
				("评分等级", "DocType", "Grading Scale"),
				("考核结果工具", "DocType", "Assessment Result Tool"),
				("课程考核报表", "Report", "Course wise Assessment Report"),
				("最终成绩报表", "Report", "Final Assessment Grades"),
				("考核计划状态", "Report", "Assessment Plan Status"),
			),
		),
		(
			"收费与财务",
			"badge-dollar-sign",
			(
				("收费标准", "DocType", "Fee Structure"),
				("收费类别", "DocType", "Fee Category"),
				("收费计划", "DocType", "Fee Schedule"),
				("销售发票", "DocType", "Sales Invoice"),
				("销售订单", "DocType", "Sales Order"),
				("学生收费报表", "Report", "Student Fee Collection"),
				("培养项目收费报表", "Report", "Program wise Fee Collection"),
			),
		),
		(
			"基础设置",
			"settings",
			(
				("教育设置", "DocType", "Education Settings"),
				("学生类别", "DocType", "Student Category"),
				("学生批次", "DocType", "Student Batch Name"),
				("院舍", "DocType", "School House"),
				("文章", "DocType", "Article"),
				("视频", "DocType", "Video"),
				("测验", "DocType", "Quiz"),
			),
		),
	)
	for label, icon, links in sections:
		items.append(_section(label, icon))
		items.extend(
			_link(item_label, link_type, link_to, child=1) for item_label, link_type, link_to in links
		)
	return items


def build_workspace_links():
	items = []
	for label, links in CARD_GROUPS:
		items.append(
			{
				"type": "Card Break",
				"label": label,
				"hidden": 0,
				"link_type": "DocType",
				"link_count": len(links),
				"onboard": 0,
				"is_query_report": 0,
			}
		)
		for item_label, link_type, link_to in links:
			items.append(
				{
					"type": "Link",
					"label": item_label,
					"hidden": 0,
					"link_type": link_type,
					"link_to": link_to,
					"link_count": 0,
					"onboard": 0,
					"is_query_report": 0,
				}
			)
	return items


def build_workspace_content():
	blocks = [
		{
			"id": "education-overview-header",
			"type": "header",
			"data": {"text": '<span class="h4"><b>教育运营总览</b></span>', "col": 12},
		}
	]
	for index, spec in enumerate(NUMBER_CARD_SPECS, 1):
		blocks.append(
			{
				"id": f"education-number-card-{index}",
				"type": "number_card",
				"data": {"number_card_name": spec["name"], "col": 3},
			}
		)
	chart_widths = (8, 4, 6, 6)
	for index, (spec, width) in enumerate(zip(DASHBOARD_CHART_SPECS, chart_widths, strict=True), 1):
		blocks.append(
			{
				"id": f"education-chart-{index}",
				"type": "chart",
				"data": {"chart_name": spec["name"], "col": width},
			}
		)
	blocks.extend(
		[
			{"id": "education-shortcut-spacer", "type": "spacer", "data": {"col": 12}},
			{
				"id": "education-shortcut-header",
				"type": "header",
				"data": {"text": '<span class="h4"><b>快捷操作</b></span>', "col": 12},
			},
		]
	)
	for index, spec in enumerate(SHORTCUT_SPECS, 1):
		blocks.append(
			{
				"id": f"education-shortcut-{index}",
				"type": "shortcut",
				"data": {"shortcut_name": spec[0], "col": 3},
			}
		)
	blocks.extend(
		[
			{"id": "education-card-spacer", "type": "spacer", "data": {"col": 12}},
			{
				"id": "education-card-header",
				"type": "header",
				"data": {"text": '<span class="h4"><b>业务中心</b></span>', "col": 12},
			},
		]
	)
	for index, group in enumerate(CARD_GROUPS, 1):
		blocks.append(
			{
				"id": f"education-card-{index}",
				"type": "card",
				"data": {"card_name": group[0], "col": 4},
			}
		)
	return json.dumps(blocks, ensure_ascii=False, separators=(",", ":"))


def _upsert_document(frappe, values):
	doctype = values["doctype"]
	name = values["name"]
	# Education v17 removes a few legacy DocTypes (for example
	# ``Program Enrollment``).  Dashboard metadata is optional, so do not
	# abort the whole site migration when a legacy chart points at one.
	document_type = values.get("document_type")
	if document_type and not frappe.db.exists("DocType", document_type):
		return "skipped_missing_document_type"
	try:
		if frappe.db.exists(doctype, name):
			doc = frappe.get_doc(doctype, name)
			doc.update(values)
			doc.save(ignore_permissions=True)
			return "updated"
		frappe.get_doc(values).insert(ignore_permissions=True)
		return "inserted"
	except Exception as exc:
		raise RuntimeError(f"Unable to configure {doctype} {name}: {exc}") from exc


def _filter_available_links(frappe, items):
	"""Drop links to legacy Education DocTypes removed in newer app versions."""
	return [
		item
		for item in items
		if item.get("type") != "Link"
		or not item.get("link_to")
		or frappe.db.exists(item.get("link_type"), item.get("link_to"))
	]


def ensure_education_workspace():
	import frappe

	if "education" not in frappe.get_installed_apps() or not frappe.db.exists("Workspace", WORKSPACE_NAME):
		return {"status": "skipped", "reason": "Education is not installed"}

	results = {"number_cards": {}, "charts": {}}
	for spec in NUMBER_CARD_SPECS:
		values = {
			"doctype": "Number Card",
			"name": spec["name"],
			"label": spec["name"],
			"module": "I ONE AI",
			"is_standard": 0,
			"is_public": 1,
			"type": "Document Type",
			"function": "Count",
			"report_function": "Sum",
			"document_type": spec["document_type"],
			"show_percentage_stats": spec.get("show_percentage_stats", 0),
			"stats_time_interval": "Monthly",
			"filters_json": spec["filters_json"],
			"dynamic_filters_json": "[]",
		}
		results["number_cards"][spec["name"]] = _upsert_document(frappe, values)

	for spec in DASHBOARD_CHART_SPECS:
		values = {
			"doctype": "Dashboard Chart",
			"name": spec["name"],
			"chart_name": spec["name"],
			"module": "I ONE AI",
			"is_standard": 0,
			"is_public": 1,
			"chart_type": spec["chart_type"],
			"document_type": spec["document_type"],
			"based_on": spec.get("based_on", ""),
			"group_by_type": spec.get("group_by_type", ""),
			"group_by_based_on": spec.get("group_by_based_on", ""),
			"timespan": spec["timespan"],
			"time_interval": spec["time_interval"],
			"timeseries": spec.get("timeseries", 0),
			"type": spec["type"],
			"show_values_over_chart": spec.get("show_values_over_chart", 0),
			"filters_json": spec["filters_json"],
			"dynamic_filters_json": "[]",
		}
		results["charts"][spec["name"]] = _upsert_document(frappe, values)

	workspace = frappe.get_doc("Workspace", WORKSPACE_NAME)
	workspace.update(
		{
			"title": WORKSPACE_TITLE,
			"label": WORKSPACE_TITLE,
			"type": "Workspace",
			"icon": "graduation-cap",
			"app": "education",
			"public": 1,
			"content": build_workspace_content(),
		}
	)
	workspace.set("shortcuts", [])
	for label, link_type, link_to, color in SHORTCUT_SPECS:
		if link_type == "DocType" and not frappe.db.exists("DocType", link_to):
			continue
		if link_type == "Report" and not frappe.db.exists("Report", link_to):
			continue
		workspace.append(
			"shortcuts",
			{
				"type": link_type,
				"link_to": link_to,
				"doc_view": "List" if link_type == "DocType" else "",
				"label": label,
				"color": color,
				"stats_filter": "[]",
			},
		)
	workspace.set("links", _filter_available_links(frappe, build_workspace_links()))
	workspace.set("sidebar_items", _filter_available_links(frappe, build_sidebar_items()))
	available_number_cards = [
		spec for spec in NUMBER_CARD_SPECS if frappe.db.exists("DocType", spec["document_type"])
	]
	available_charts = [
		spec for spec in DASHBOARD_CHART_SPECS if frappe.db.exists("DocType", spec["document_type"])
	]
	workspace.set(
		"number_cards",
		[{"number_card_name": spec["name"], "label": spec["name"]} for spec in available_number_cards],
	)
	workspace.set(
		"charts",
		[{"chart_name": spec["name"], "label": spec["name"]} for spec in available_charts],
	)
	previous_in_migrate = frappe.flags.in_migrate
	frappe.flags.in_migrate = True
	try:
		workspace.save(ignore_permissions=True)
	except Exception as exc:
		raise RuntimeError(f"Unable to configure Workspace {WORKSPACE_NAME}: {exc}") from exc
	finally:
		frappe.flags.in_migrate = previous_in_migrate
	workspace_fields = {"label": WORKSPACE_TITLE, "title": WORKSPACE_TITLE, "type": "Workspace"}
	if frappe.get_meta("Workspace").has_field("app"):
		workspace_fields["app"] = "education"
	frappe.db.set_value(
		"Workspace",
		WORKSPACE_NAME,
		workspace_fields,
		update_modified=False,
	)
	results["status"] = "updated"
	results["workspace"] = WORKSPACE_NAME
	return results
