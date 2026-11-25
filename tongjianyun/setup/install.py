import frappe

ROLES = (
	("I-ONE User", 1),
	("I-ONE Manager", 1),
	("I-ONE AI Operator", 1),
	("I-ONE Auditor", 1),
	("I-ONE AI Employee", 1),
)


def ensure_roles():
	for role_name, desk_access in ROLES:
		if frappe.db.exists("Role", role_name):
			if frappe.db.get_value("Role", role_name, "desk_access") != desk_access:
				frappe.db.set_value("Role", role_name, "desk_access", desk_access, update_modified=False)
			continue
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": desk_access,
				"is_custom": 0,
			}
		).insert(ignore_permissions=True)


def ensure_default_agent():
	if not frappe.db.exists("DocType", "I-ONE Agent"):
		return
	if frappe.db.exists("I-ONE Agent", {"agent_code": "ione-general"}):
		return

	frappe.get_doc(
		{
			"doctype": "I-ONE Agent",
			"agent_code": "ione-general",
			"agent_name": "I-ONE 通用助理",
			"agent_type": "综合助理",
			"status": "草稿",
			"description": "负责跨应用信息查询、任务拆解和受控业务执行。",
			"responsibilities": "负责跨应用信息查询、任务拆解和受控业务执行。",
			"operating_mode": "辅助",
			"allowed_modules": "ERPNext\nCRM\nHR\nHelpdesk\nDrive\nLearning\nGameplan\nInsights",
		}
	).insert(ignore_permissions=True)


def ensure_default_onboarding_flow():
	if not frappe.db.exists("DocType", "I-ONE Onboarding Flow"):
		return
	if frappe.db.exists("I-ONE Onboarding Flow", "mobile-default"):
		return

	from tongjianyun.onboarding_defaults import get_default_onboarding_flow_data

	frappe.get_doc(get_default_onboarding_flow_data()).insert(ignore_permissions=True)


def before_install():
	ensure_roles()


def after_install():
	set_chinese_locale_defaults()
	ensure_roles()
	ensure_default_agent()
	ensure_default_onboarding_flow()
	ensure_flow_tools()
	ensure_education_workspace()
	ensure_healthcare_workspace()
	ensure_slides_integration()
	ensure_video_integration()
	sync_translation_overrides()
	install_translation_bundle()
	ensure_dingtalk_employee_field()


def after_migrate():
	ensure_roles()
	migrate_agent_fields()
	ensure_default_agent()
	ensure_default_onboarding_flow()
	ensure_flow_tools()
	ensure_education_workspace()
	ensure_healthcare_workspace()
	ensure_slides_integration()
	ensure_video_integration()
	ensure_runtime_config()
	sync_translation_overrides()
	install_translation_bundle()
	ensure_dingtalk_employee_field()


def ensure_unified_navigation():
	from tongjianyun.setup.unified_navigation import ensure_unified_navigation as configure

	return configure()


def after_app_install(app_name):
	if app_name == "wiki":
		install_translation_bundle()


def set_chinese_locale_defaults():
	"""Make a newly installed I-ONE site use the packaged Chinese catalog."""
	frappe.db.set_single_value("System Settings", "language", "zh")
	if frappe.db.exists("User", "Administrator"):
		frappe.db.set_value(
			"User",
			"Administrator",
			"language",
			"zh",
			update_modified=False,
		)


def sync_translation_overrides():
	from tongjianyun.translation_overrides import sync_translation_overrides as sync

	return sync()


def install_translation_bundle():
	from tongjianyun.translation_bundle import install_translation_bundle as install

	return install()


def ensure_desktop_app_labels():
	from tongjianyun.desktop_i18n import ensure_desktop_app_labels as ensure

	return ensure()


def ensure_runtime_config():
	from tongjianyun.runtime_config import ensure_web_request_timeout

	ensure_web_request_timeout()


def ensure_flow_tools():
	from tongjianyun.setup.flow_tools import ensure_frappe_document_tool

	ensure_frappe_document_tool()


def ensure_education_workspace():
	from tongjianyun.setup.education_workspace import ensure_education_workspace as ensure

	return ensure()


def ensure_healthcare_workspace():
	from tongjianyun.setup.healthcare_workspace import ensure_healthcare_workspace as ensure

	return ensure()


def ensure_slides_integration():
	from tongjianyun.setup.slides_integration import ensure_deal_presentation_field

	return ensure_deal_presentation_field()


def ensure_video_integration():
	from tongjianyun.setup.video_integration import ensure_deal_video_field

	return ensure_deal_video_field()



def ensure_dingtalk_employee_field():
	from tongjianyun.dingtalk_attendance import ensure_dingtalk_employee_field as ensure

	return ensure()

def migrate_agent_fields():
	if not frappe.db.exists("DocType", "I-ONE Agent"):
		return
	frappe.db.sql(
		"""
		update `tabI-ONE Agent`
		set status = case
			when status = '启用' then '在职'
			when status = '停用' then '离职'
			else coalesce(nullif(status, ''), '草稿')
		end
		"""
	)
	default_model = None
	if "flow" in frappe.get_installed_apps() and frappe.db.exists("DocType", "Flow Model"):
		default_model = frappe.db.get_value(
			"Flow Model",
			{"enabled": 1},
			"name",
			order_by="creation asc",
		)
	if default_model:
		frappe.db.sql(
			"""
			update `tabI-ONE Agent`
			set flow_model = %s
			where ifnull(flow_model, '') = ''
			""",
			default_model,
		)
