app_name = "tongjianyun"
app_title = "\u7ae5\u5065\u4e91"
app_publisher = "Local"
app_description = "\u7ae5\u5065\u4e91 Frappe \u540e\u53f0\u5e94\u7528"
app_email = "admin@example.com"
app_license = "mit"
use_json_request_body = True
required_apps = ["education"]

# Register the domain-specific nutrition rule tools on I-ONE Core's MCP endpoint.
ione_mcp_tool_modules = ["tongjianyun.mcp_tools"]

app_home = "/desk/tongjianyun-workbench"
app_logo_url = "/assets/tongjianyun/images/tongjianyun-logo.svg"
app_include_js = ["/assets/tongjianyun/js/page_cache_buster.js?v=20260911-recipe-defaults-2"]

add_to_apps_screen = [
    {
        "name": app_name,
        "title": app_title,
        "route": app_home,
        "logo": app_logo_url,
    }
]

before_migrate = "tongjianyun.education_integration.before_migrate"

after_migrate = [
    "tongjianyun.education_integration.install",
    "tongjianyun.student_identity.install",
    "tongjianyun.meal_attendance_setup.install",
    "tongjianyun.recipe_storage.install",
    "tongjianyun.nutrition_rule_setup.install",
    "tongjianyun.workbench.install",
    "tongjianyun.patches.v1_0.add_recipe_price_fields.execute",
    "tongjianyun.meal_attendance_roles.install",
]

override_doctype_class = {
    "Student": "tongjianyun.education_integration.TongjianyunStudent",
}

doctype_js = {
    "Student": "public/js/student.js",
    "Student Group": "public/js/student_group.js",
    "Tongjianyun Recipe Ingredient": "public/js/recipe_ingredient_price.js",
}

override_whitelisted_methods = {
    "education.education.doctype.student_group.student_group.get_students": (
        "tongjianyun.education_integration.get_unassigned_students_for_group"
    ),
}

doc_events = {
    "Material Request": {"before_validate": "tongjianyun.procurement_precision.before_validate"},
    "Purchase Order": {"before_validate": "tongjianyun.procurement_precision.before_validate"},
    "Purchase Receipt": {"before_validate": "tongjianyun.procurement_precision.before_validate"},
    "Purchase Invoice": {"before_validate": "tongjianyun.procurement_precision.before_validate"},
    "Student": {
        "after_delete": "tongjianyun.education_data_notifications.notify_missing_education_data",
    },
    "Student Group": {
        "after_delete": "tongjianyun.education_data_notifications.notify_missing_education_data",
    },
    "Student Attendance": {
        "after_insert": "tongjianyun.daily_meals.refresh_confirmation_from_event",
        "on_update": "tongjianyun.daily_meals.refresh_confirmation_from_event",
        "on_submit": "tongjianyun.daily_meals.refresh_confirmation_from_event",
        "on_cancel": "tongjianyun.daily_meals.refresh_confirmation_from_event",
    },
    "Student Leave Application": {
        "after_insert": "tongjianyun.daily_meals.refresh_confirmations_from_leave",
        "on_update": "tongjianyun.daily_meals.refresh_confirmations_from_leave",
        "on_submit": "tongjianyun.daily_meals.refresh_confirmations_from_leave",
        "on_cancel": "tongjianyun.daily_meals.refresh_confirmations_from_leave",
    },
    "Tongjianyun Daily Meal Adjustment": {
        "after_insert": "tongjianyun.daily_meals.refresh_confirmation_from_adjustment",
        "on_update": "tongjianyun.daily_meals.refresh_confirmation_from_adjustment",
        "on_trash": "tongjianyun.daily_meals.refresh_confirmation_from_adjustment",
    },
}

scheduler_events = {
    "daily": [
        "tongjianyun.daily_meals.prepare_today_confirmation",
        "tongjianyun.education_data_notifications.notify_missing_education_data",
    ],
}

# Application-level teacher row restrictions; no DocType permission metadata changes.
permission_query_conditions = {
    doctype: "tongjianyun.teacher_permissions.query_condition"
    for doctype in ("Student Group", "Student", "Student Attendance", "Student Leave Application")
}
has_permission = {
    doctype: "tongjianyun.teacher_permissions.document_permission"
    for doctype in ("Student Group", "Student", "Student Attendance", "Student Leave Application")
}
