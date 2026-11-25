import json

WORKSPACE_NAME = "Healthcare"
WORKSPACE_TITLE = "医疗管理"
APP_DESKTOP_ICON_NAME = "Marley Health"
APP_DESKTOP_TITLE = "医疗健康"

NUMBER_CARD_NAMES = (
	"Total Patients",
	"Total Patients Admitted",
	"Open Appointments",
	"Appointments to Bill",
)

CHART_NAMES = ("Department wise Patient Appointments",)

SIDEBAR_WORKSPACES = (
	("医疗管理", WORKSPACE_NAME, "heart-pulse"),
	("门诊管理", "Outpatient", "stethoscope"),
	("住院管理", "Inpatient", "bed"),
	("检验诊断", "Diagnostics", "microscope"),
	("康复治疗", "Rehabilitation", "heart-pulse"),
	("医保结算", "Insurance", "shield-check"),
	("急诊管理", "Emergency", "siren"),
	("基础设置", "Setup", "settings"),
)

WORKSPACE_SIDEBAR_SPECS = {
	WORKSPACE_NAME: (
		("工作台", "Workspace", WORKSPACE_NAME, "house"),
		("患者档案", "DocType", "Patient", "users"),
		("预约管理", "DocType", "Patient Appointment", "calendar-days"),
		("医务人员", "DocType", "Healthcare Practitioner", "user-round-plus"),
		("医疗科室", "DocType", "Medical Department", "building-2"),
		("医疗服务单元", "DocType", "Healthcare Service Unit", "hospital"),
		("患者病历", "Page", "patient_history", "history"),
	),
	"Outpatient": (
		("工作台", "Workspace", "Outpatient", "house"),
		("患者档案", "DocType", "Patient", "users"),
		("预约管理", "DocType", "Patient Appointment", "calendar-days"),
		("门诊接诊", "DocType", "Patient Encounter", "stethoscope"),
		("生命体征", "DocType", "Vital Signs", "activity"),
		("临床诊疗", "DocType", "Clinical Procedure", "clipboard-plus"),
		("服务申请", "DocType", "Service Request", "file-plus-2"),
		("用药申请", "DocType", "Medication Request", "pill"),
		("销售发票", "DocType", "Sales Invoice", "receipt"),
		("患者病历", "Page", "patient_history", "history"),
	),
	"Inpatient": (
		("工作台", "Workspace", "Inpatient", "house"),
		("住院登记", "DocType", "Inpatient Record", "bed"),
		("住院医嘱", "DocType", "Inpatient Medication Order", "file-heart"),
		("住院给药", "DocType", "Inpatient Medication Entry", "syringe"),
		("护理任务", "DocType", "Nursing Task", "clipboard-check"),
		("医疗活动", "DocType", "Healthcare Activity", "activity"),
		("患者进展", "Page", "patient-progress", "chart-no-axes-column"),
		("患者病历", "Page", "patient_history", "history"),
	),
	"Diagnostics": (
		("工作台", "Workspace", "Diagnostics", "house"),
		("服务申请", "DocType", "Service Request", "file-plus-2"),
		("样本采集", "DocType", "Sample Collection", "test-tube"),
		("检验检查", "DocType", "Lab Test", "microscope"),
		("诊断报告", "DocType", "Diagnostic Report", "file-search"),
		("观察记录", "DocType", "Observation", "clipboard-list"),
		("检验报告", "Report", "Lab Test Report", "file-chart-column"),
		("诊断趋势", "Report", "Diagnosis Trends", "chart-line"),
		("患者病历", "Page", "patient_history", "history"),
	),
	"Rehabilitation": (
		("工作台", "Workspace", "Rehabilitation", "house"),
		("治疗计划", "DocType", "Therapy Plan", "clipboard-list"),
		("治疗记录", "DocType", "Therapy Session", "heart-pulse"),
		("患者评估", "DocType", "Patient Assessment", "clipboard-check"),
		("治疗类型", "DocType", "Therapy Type", "list-tree"),
		("运动类型", "DocType", "Exercise Type", "dumbbell"),
		("患者进展", "Page", "patient-progress", "chart-no-axes-column"),
		("患者病历", "Page", "patient_history", "history"),
	),
	"Insurance": (
		("工作台", "Workspace", "Insurance", "house"),
		("患者医保保单", "DocType", "Patient Insurance Policy", "shield-check"),
		("医保理赔", "DocType", "Insurance Claim", "badge-dollar-sign"),
		("医保支付方", "DocType", "Insurance Payor", "building-2"),
		("支付方合同", "DocType", "Insurance Payor Contract", "file-signature"),
		("患者医保保障", "DocType", "Patient Insurance Coverage", "umbrella"),
		("医保项目资格", "DocType", "Item Insurance Eligibility", "list-checks"),
		("医保资格计划", "DocType", "Insurance Payor Eligibility Plan", "notebook-tabs"),
		("销售发票", "DocType", "Sales Invoice", "receipt"),
	),
	"Emergency": (
		("工作台", "Workspace", "Emergency", "house"),
		("急诊记录", "DocType", "Emergency Record", "siren"),
		("急诊分诊队列", "Report", "Emergency Triage Queue", "list-ordered"),
		("分诊级别", "DocType", "Triage Level", "badge-alert"),
		("门诊接诊", "DocType", "Patient Encounter", "stethoscope"),
		("服务申请", "DocType", "Service Request", "file-plus-2"),
		("用药申请", "DocType", "Medication Request", "pill"),
		("医疗服务单元", "DocType", "Healthcare Service Unit", "hospital"),
	),
	"Setup": (
		("工作台", "Workspace", "Setup", "house"),
		("医疗设置", "DocType", "Healthcare Settings", "settings"),
		("患者病历设置", "DocType", "Patient History Settings", "file-cog"),
		("医疗科室", "DocType", "Medical Department", "building-2"),
		("医务人员", "DocType", "Healthcare Practitioner", "user-round-plus"),
		("医务人员排班", "DocType", "Practitioner Schedule", "calendar-clock"),
		("医疗服务单元", "DocType", "Healthcare Service Unit", "hospital"),
		("服务单元类型", "DocType", "Healthcare Service Unit Type", "network"),
		("预约类型", "DocType", "Appointment Type", "calendar-range"),
		("临床诊疗模板", "DocType", "Clinical Procedure Template", "clipboard-plus"),
		("检验模板", "DocType", "Lab Test Template", "microscope"),
	),
}

SHORTCUT_SPECS = (
	("预约管理", "DocType", "Patient Appointment", "Orange"),
	("患者档案", "DocType", "Patient", "Blue"),
	("门诊接诊", "DocType", "Patient Encounter", "Cyan"),
	("住院登记", "DocType", "Inpatient Record", "Purple"),
	("检验检查", "DocType", "Lab Test", "Blue"),
	("康复治疗", "DocType", "Therapy Session", "Green"),
	("医保理赔", "DocType", "Insurance Claim", "Yellow"),
	("患者病历", "Page", "patient_history", "Grey"),
)

CARD_GROUPS = (
	(
		"患者与预约",
		(
			("患者档案", "DocType", "Patient"),
			("预约管理", "DocType", "Patient Appointment"),
			("医务人员", "DocType", "Healthcare Practitioner"),
			("医务人员排班", "DocType", "Practitioner Schedule"),
			("医疗科室", "DocType", "Medical Department"),
			("医疗服务单元", "DocType", "Healthcare Service Unit"),
		),
	),
	(
		"门诊诊疗",
		(
			("门诊接诊", "DocType", "Patient Encounter"),
			("生命体征", "DocType", "Vital Signs"),
			("临床诊疗", "DocType", "Clinical Procedure"),
			("服务申请", "DocType", "Service Request"),
			("用药申请", "DocType", "Medication Request"),
			("收费有效期", "DocType", "Fee Validity"),
		),
	),
	(
		"住院与护理",
		(
			("住院登记", "DocType", "Inpatient Record"),
			("住院医嘱", "DocType", "Inpatient Medication Order"),
			("住院给药", "DocType", "Inpatient Medication Entry"),
			("护理任务", "DocType", "Nursing Task"),
			("医疗活动", "DocType", "Healthcare Activity"),
			("护理清单模板", "DocType", "Nursing Checklist Template"),
		),
	),
	(
		"检验与诊断",
		(
			("检验检查", "DocType", "Lab Test"),
			("样本采集", "DocType", "Sample Collection"),
			("诊断报告", "DocType", "Diagnostic Report"),
			("观察记录", "DocType", "Observation"),
			("检验报告", "Report", "Lab Test Report"),
			("诊断趋势", "Report", "Diagnosis Trends"),
		),
	),
	(
		"康复治疗",
		(
			("治疗计划", "DocType", "Therapy Plan"),
			("治疗记录", "DocType", "Therapy Session"),
			("患者评估", "DocType", "Patient Assessment"),
			("治疗类型", "DocType", "Therapy Type"),
			("运动类型", "DocType", "Exercise Type"),
			("治疗计划模板", "DocType", "Therapy Plan Template"),
		),
	),
	(
		"医保与结算",
		(
			("患者医保保单", "DocType", "Patient Insurance Policy"),
			("医保理赔", "DocType", "Insurance Claim"),
			("医保支付方", "DocType", "Insurance Payor"),
			("医保支付方合同", "DocType", "Insurance Payor Contract"),
			("患者医保保障", "DocType", "Patient Insurance Coverage"),
			("销售发票", "DocType", "Sales Invoice"),
		),
	),
	(
		"病历与报表",
		(
			("患者病历", "Page", "patient_history"),
			("患者进展", "Page", "patient-progress"),
			("患者医疗记录", "DocType", "Patient Medical Record"),
			("预约分析", "Report", "Patient Appointment Analytics"),
			("检验报告", "Report", "Lab Test Report"),
			("诊断趋势", "Report", "Diagnosis Trends"),
		),
	),
	(
		"基础资料与设置",
		(
			("医疗设置", "DocType", "Healthcare Settings"),
			("患者病历设置", "DocType", "Patient History Settings"),
			("预约类型", "DocType", "Appointment Type"),
			("医疗服务单元类型", "DocType", "Healthcare Service Unit Type"),
			("临床诊疗模板", "DocType", "Clinical Procedure Template"),
			("检验模板", "DocType", "Lab Test Template"),
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


def build_sidebar_items(workspace_name=WORKSPACE_NAME):
	return [
		_link(label, link_type, link_to, icon=icon)
		for label, link_type, link_to, icon in WORKSPACE_SIDEBAR_SPECS[workspace_name]
	]


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
					"is_query_report": link_type == "Report",
				}
			)
	return items


def build_workspace_content():
	blocks = [
		{
			"id": "healthcare-overview-header",
			"type": "header",
			"data": {"text": '<span class="h4"><b>医疗运营总览</b></span>', "col": 12},
		}
	]
	for index, name in enumerate(NUMBER_CARD_NAMES, 1):
		blocks.append(
			{
				"id": f"healthcare-number-card-{index}",
				"type": "number_card",
				"data": {"number_card_name": name, "col": 3},
			}
		)
	blocks.append(
		{
			"id": "healthcare-appointment-chart",
			"type": "chart",
			"data": {"chart_name": CHART_NAMES[0], "col": 12},
		}
	)
	blocks.extend(
		[
			{"id": "healthcare-shortcut-spacer", "type": "spacer", "data": {"col": 12}},
			{
				"id": "healthcare-shortcut-header",
				"type": "header",
				"data": {"text": '<span class="h4"><b>快捷操作</b></span>', "col": 12},
			},
		]
	)
	for index, spec in enumerate(SHORTCUT_SPECS, 1):
		blocks.append(
			{
				"id": f"healthcare-shortcut-{index}",
				"type": "shortcut",
				"data": {"shortcut_name": spec[0], "col": 3},
			}
		)
	blocks.extend(
		[
			{"id": "healthcare-card-spacer", "type": "spacer", "data": {"col": 12}},
			{
				"id": "healthcare-card-header",
				"type": "header",
				"data": {"text": '<span class="h4"><b>业务中心</b></span>', "col": 12},
			},
		]
	)
	for index, group in enumerate(CARD_GROUPS, 1):
		blocks.append(
			{
				"id": f"healthcare-card-{index}",
				"type": "card",
				"data": {"card_name": group[0], "col": 4},
			}
		)
	return json.dumps(blocks, ensure_ascii=False, separators=(",", ":"))


def ensure_healthcare_workspace():
	import frappe

	if "healthcare" not in frappe.get_installed_apps() or not frappe.db.exists("Workspace", WORKSPACE_NAME):
		return {"status": "skipped", "reason": "Healthcare is not installed"}

	missing = []
	for _label, workspace_name, _icon in SIDEBAR_WORKSPACES:
		if not frappe.db.exists("Workspace", workspace_name):
			missing.append(f"Workspace:{workspace_name}")
	for name in NUMBER_CARD_NAMES:
		if not frappe.db.exists("Number Card", name):
			missing.append(f"Number Card:{name}")
	for name in CHART_NAMES:
		if not frappe.db.exists("Dashboard Chart", name):
			missing.append(f"Dashboard Chart:{name}")
	configured_links = {entry for group in CARD_GROUPS for entry in group[1]} | {
		spec[:3] for spec in SHORTCUT_SPECS
	}
	configured_links |= {
		entry[:3]
		for sidebar_items in WORKSPACE_SIDEBAR_SPECS.values()
		for entry in sidebar_items
		if entry[1] != "Workspace"
	}
	for _label, link_type, link_to in configured_links:
		if link_type == "DocType" and not frappe.db.exists("DocType", link_to):
			missing.append(f"DocType:{link_to}")
		elif link_type == "Report" and not frappe.db.exists("Report", link_to):
			missing.append(f"Report:{link_to}")
		elif link_type == "Page" and not frappe.db.exists("Page", link_to):
			missing.append(f"Page:{link_to}")
	if missing:
		raise RuntimeError(f"Healthcare workspace has unavailable links: {', '.join(sorted(missing))}")

	workspace = frappe.get_doc("Workspace", WORKSPACE_NAME)
	workspace.update(
		{
			"title": WORKSPACE_TITLE,
			"label": WORKSPACE_TITLE,
			"type": "Workspace",
			"icon": "heart-pulse",
			"app": "healthcare",
			"public": 1,
			"content": build_workspace_content(),
		}
	)
	workspace.set("shortcuts", [])
	for label, link_type, link_to, color in SHORTCUT_SPECS:
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
	workspace.set("links", build_workspace_links())
	workspace.set(
		"number_cards",
		[{"number_card_name": name, "label": name} for name in NUMBER_CARD_NAMES],
	)
	workspace.set(
		"charts",
		[{"chart_name": name, "label": name} for name in CHART_NAMES],
	)
	previous_in_migrate = frappe.flags.in_migrate
	frappe.flags.in_migrate = True
	try:
		if frappe.db.exists("Desktop Icon", APP_DESKTOP_ICON_NAME):
			frappe.db.set_value(
				"Desktop Icon",
				APP_DESKTOP_ICON_NAME,
				"label",
				APP_DESKTOP_TITLE,
				update_modified=False,
			)
		for workspace_label, workspace_name, workspace_icon in SIDEBAR_WORKSPACES:
			current_workspace = (
				workspace if workspace_name == WORKSPACE_NAME else frappe.get_doc("Workspace", workspace_name)
			)
			current_workspace.update(
				{
					"label": workspace_label,
					"title": workspace_label,
					"icon": workspace_icon,
				}
			)
			current_workspace.set("sidebar_items", build_sidebar_items(workspace_name))
			current_workspace.save(ignore_permissions=True)
			if frappe.db.exists("Desktop Icon", workspace_name):
				frappe.db.set_value(
					"Desktop Icon",
					workspace_name,
					{"label": workspace_label, "icon": workspace_icon},
					update_modified=False,
				)
	except Exception as exc:
		raise RuntimeError(f"Unable to configure Healthcare workspace navigation: {exc}") from exc
	finally:
		frappe.flags.in_migrate = previous_in_migrate
	frappe.db.set_value(
		"Workspace",
		WORKSPACE_NAME,
		{
			"label": WORKSPACE_TITLE,
			"title": WORKSPACE_TITLE,
			"type": "Workspace",
			"app": "healthcare",
		},
		update_modified=False,
	)
	return {
		"status": "updated",
		"workspace": WORKSPACE_NAME,
		"sidebars": list(WORKSPACE_SIDEBAR_SPECS),
	}
