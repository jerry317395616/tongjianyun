"""Service hooks transferred from the former I-ONE Core site app."""

doctype_list_js = {
	"Production Plan": "public/js/meal_production_plan_list.js",
	"Role": "public/js/role_list.js",
	"Data Import": "public/js/data_import_list.js",
	"Employee Checkin": "public/js/dingtalk_employee_checkin_list.js",
}

doctype_js = {'Production Plan': 'public/js/meal_production_plan.js',
 'Role': 'public/js/role.js',
 'User': 'public/js/user.js',
 'Student': 'public/js/student.js',
 'Purchase Order': 'public/js/meal_purchase_order.js'}

boot_session = "tongjianyun.desktop_i18n.localize_app_titles"

before_request = []

after_request = [
	"tongjianyun.web_injection.ensure_utf8_private_file_response",
	"tongjianyun.web_injection.inject_crm_i18n",
]

before_install = "tongjianyun.setup.install.before_install"

after_install = "tongjianyun.setup.install.after_install"

after_migrate = "tongjianyun.setup.install.after_migrate"

after_app_install = "tongjianyun.setup.install.after_app_install"

fixtures = [
	{"dt": "Role", "filters": [["role_name", "like", "I-ONE %"]]},
]

permission_query_conditions = {'I-ONE Smart Record': 'tongjianyun.permissions.owner_query', 'I-ONE AI Task': 'tongjianyun.permissions.owner_query', 'I-ONE AI Run Log': 'tongjianyun.permissions.owner_query', 'I-ONE Approval Request': 'tongjianyun.permissions.approval_query', 'I-ONE Growth Plan': 'tongjianyun.permissions.owner_user_query', 'I-ONE Evidence': 'tongjianyun.permissions.owner_query', 'I-ONE Experience': 'tongjianyun.permissions.experience_query', 'I-ONE Publish Job': 'tongjianyun.permissions.owner_query', 'I-ONE Evaluation': 'tongjianyun.permissions.owner_query', 'I-ONE Achievement': 'tongjianyun.permissions.achievement_query', 'I-ONE Expert Conversation': 'tongjianyun.permissions.owner_user_query', 'I-ONE Expert Message': 'tongjianyun.permissions.owner_query', 'I-ONE Onboarding Record': 'tongjianyun.permissions.user_query', 'Student': 'tongjianyun.education_teacher_privacy.query_condition', 'Student Group': 'tongjianyun.education_teacher_privacy.query_condition', 'Student Attendance': 'tongjianyun.education_teacher_privacy.query_condition', 'Student Leave Application': 'tongjianyun.education_teacher_privacy.query_condition'}

has_permission = {'I-ONE Smart Record': 'tongjianyun.permissions.owner_permission', 'I-ONE AI Task': 'tongjianyun.permissions.owner_permission', 'I-ONE AI Run Log': 'tongjianyun.permissions.owner_permission', 'I-ONE Approval Request': 'tongjianyun.permissions.approval_permission', 'I-ONE Growth Plan': 'tongjianyun.permissions.owner_user_permission', 'I-ONE Evidence': 'tongjianyun.permissions.owner_permission', 'I-ONE Experience': 'tongjianyun.permissions.experience_permission', 'I-ONE Publish Job': 'tongjianyun.permissions.owner_permission', 'I-ONE Evaluation': 'tongjianyun.permissions.owner_permission', 'I-ONE Achievement': 'tongjianyun.permissions.achievement_permission', 'I-ONE Expert Conversation': 'tongjianyun.permissions.owner_user_permission', 'I-ONE Expert Message': 'tongjianyun.permissions.owner_permission', 'I-ONE Onboarding Record': 'tongjianyun.permissions.user_permission', 'Student': 'tongjianyun.education_teacher_privacy.document_permission', 'Student Group': 'tongjianyun.education_teacher_privacy.document_permission', 'Student Attendance': 'tongjianyun.education_teacher_privacy.document_permission', 'Student Leave Application': 'tongjianyun.education_teacher_privacy.document_permission'}

doc_events = {'Production Plan': {'validate': 'tongjianyun.meal_planning.validate_production_plan', 'before_submit': 'tongjianyun.meal_planning.validate_production_plan', 'before_cancel': 'tongjianyun.meal_planning.validate_production_plan', 'before_update_after_submit': 'tongjianyun.meal_planning.validate_production_plan'}, 'Flow Run': {'on_update': 'tongjianyun.ai.sync_task_from_flow_run'}, 'Stock Entry': {'validate': 'tongjianyun.meal_kitchen.validate_stock_entry', 'before_update_after_submit': 'tongjianyun.meal_kitchen.validate_stock_entry', 'before_cancel': 'tongjianyun.meal_kitchen.before_cancel_stock_entry'}, 'Material Request': {'validate': 'tongjianyun.meal_purchasing.validate_material_request', 'before_submit': 'tongjianyun.meal_purchasing.before_submit_material_request', 'before_update_after_submit': 'tongjianyun.meal_purchasing.validate_material_request', 'before_validate': 'tongjianyun.legacy_meal_precision.before_validate'}, 'Purchase Order': {'validate': 'tongjianyun.meal_purchasing.validate_purchase_order', 'before_submit': 'tongjianyun.meal_purchasing.before_submit_purchase_order', 'before_update_after_submit': 'tongjianyun.meal_purchasing.validate_purchase_order', 'before_validate': 'tongjianyun.legacy_meal_precision.before_validate'}, 'Supplier Quotation': {'validate': 'tongjianyun.meal_purchasing.validate_supplier_quotation', 'before_submit': 'tongjianyun.meal_purchasing.validate_supplier_quotation', 'before_update_after_submit': 'tongjianyun.meal_purchasing.validate_supplier_quotation'}, 'Purchase Receipt': {'before_submit': 'tongjianyun.meal_stock_claims.before_submit_purchase_receipt', 'before_cancel': 'tongjianyun.meal_stock_claims.before_cancel_purchase_receipt', 'before_update_after_submit': 'tongjianyun.meal_stock_claims.validate_purchase_receipt', 'before_validate': 'tongjianyun.legacy_meal_precision.before_validate'}, 'Purchase Invoice': {'before_validate': 'tongjianyun.legacy_meal_precision.before_validate'}}

override_whitelisted_methods = {
	"flow.api.start_run": "tongjianyun.flow_policy.start_run",
	"flow.api.api.start_run": "tongjianyun.flow_policy.start_run",
	"frappe.desk.doctype.dashboard_chart.dashboard_chart.get": "tongjianyun.dashboard.get_dashboard_chart",
}

scheduler_events = {
	"hourly": ["tongjianyun.ai.expire_pending_approvals"],
	"cron": {
		"0 18 * * *": ["tongjianyun.dingtalk_attendance.sync_dingtalk_attendance_job"],
		"5-59/10 * * * *": ["tongjianyun.dingtalk_attendance.sync_dingtalk_attendance_catchup_job"],
	},
}

extend_doctype_class = {'Shift Schedule Assignment': ['tongjianyun.hrms_compat.shift_schedule_assignment.PreserveShiftCycleBoundaryMixin'], 'Purchase Receipt': ['tongjianyun.native_asset_history.PreserveAssetHistory'], 'Purchase Invoice': ['tongjianyun.native_asset_history.PreserveAssetHistory']}
