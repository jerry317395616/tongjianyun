"""ERP-backed meal reports and the standard recipe library."""
from tongjianyun.archive import LEGACY_DOCTYPES as _LEGACY_DOCTYPES

app_name = "tongjianyun"
app_title = "童健云"
app_publisher = "Local"
app_description = "ERP 周食谱与食谱分析"
app_email = "admin@example.com"
app_license = "mit"
required_apps = ["erpnext", "ione_core"]
app_home = "/desk/tongjianyun/query-report/Tongjianyun%20Weekly%20Menu"
app_logo_url = "/assets/tongjianyun/images/tongjianyun-logo-20261029.svg"
add_to_apps_screen = [{"name": app_name, "title": app_title, "route": app_home, "logo": app_logo_url}]
after_install = ["tongjianyun.reports_setup.install", "tongjianyun.standard_recipe_setup.install"]
after_migrate = after_install
doctype_js = {"BOM": "public/js/standard_recipes.js"}
doctype_list_js = {"BOM": "public/js/standard_recipe_list.js"}
doc_events = {
    "BOM": {
        "validate": "tongjianyun.standard_recipes.validate_recipe",
        "before_save": "tongjianyun.standard_recipes.save_draft",
        "before_submit": "tongjianyun.standard_recipes.publish_recipe",
    },
}

# Existing tables remain readable by administrators; no historical record can be mutated.
permission_query_conditions = {name: "tongjianyun.archive.query_condition" for name in _LEGACY_DOCTYPES}
has_permission = {name: "tongjianyun.archive.document_permission" for name in _LEGACY_DOCTYPES}
