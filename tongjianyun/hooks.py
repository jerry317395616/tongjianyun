"""ERP-backed meal reports and the standard recipe library."""
from tongjianyun.archive import LEGACY_DOCTYPES as _LEGACY_DOCTYPES
from tongjianyun.canteen_ops.common import MANAGED as _CANTEEN_DOCTYPES, PERMISSION_QUERIES as _CANTEEN_QUERIES

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
before_install = "tongjianyun.canteen_ops.setup.ensure_roles"
before_migrate = before_install
after_install = [
    before_install,
    "tongjianyun.reports_setup.install",
    "tongjianyun.nutrition_setup.install",
    "tongjianyun.standard_recipe_setup.install",
    "tongjianyun.ingredient_library_setup.install",
    "tongjianyun.special_orders.install",
]
after_migrate = after_install
scheduler_events = {"daily": ["tongjianyun.canteen_ops.reminders.send_expiry_reminders"]}
doctype_js = {
    "BOM": "public/js/standard_recipes.js",
    "Item": ["public/js/standard_dishes.js", "public/js/standard_ingredients.js"],
    "Meal Planning Week": ["public/js/weekly_menu_editor.js", "public/js/special_ingredients.js",
                           "public/js/special_orders.js", "public/js/canteen_forms.js"],
    "Meal Plan Adjustment": ["public/js/special_ingredients.js", "public/js/special_orders.js", "public/js/canteen_forms.js"],
    **{doctype: "public/js/canteen_forms.js" for doctype in (*_CANTEEN_DOCTYPES, "Meal Kitchen Day",
                                                           "Purchase Order", "Request for Quotation")},
}
doctype_list_js = {"BOM": "public/js/standard_recipe_list.js", "Item": "public/js/standard_dish_list.js",
                   "Tongjianyun Canteen Receiving": "public/js/canteen_receiving_list.js",
                   "Tongjianyun Food Sample": "public/js/canteen_sample_list.js"}
extend_doctype_class = {"Production Plan": ["tongjianyun.weekly_menu_editor.MealMenuDraftPlan"]}
doc_events = {
    "Item": {
        "before_insert": [
            "tongjianyun.dish_library.validate_new_dish",
            "tongjianyun.ingredient_library.set_ingredient_code",
        ],
        "validate": "tongjianyun.ingredient_library.validate_ingredient",
    },
    "Meal Planning Week": {
        "validate": "tongjianyun.weekly_menu_editor.validate_menu_for_submission",
        "before_submit": "tongjianyun.recipe_nutrition.freeze_week",
        "on_submit": "tongjianyun.special_ingredients.freeze",
    },
    "Meal Plan Adjustment": {
        "before_submit": "tongjianyun.recipe_nutrition.freeze_adjustment",
        "on_submit": "tongjianyun.special_ingredients.freeze",
    },
    "Material Request": {
        event: "tongjianyun.special_orders.check_request"
        for event in ("validate", "before_submit", "before_update_after_submit")
    },
    "Purchase Order": {
        "validate": "tongjianyun.special_orders.check_order",
        "before_submit": ["tongjianyun.special_orders.check_order", "tongjianyun.canteen_ops.purchasing.check_order"],
        "before_update_after_submit": ["tongjianyun.special_orders.check_order",
                                        "tongjianyun.canteen_ops.purchasing.check_order"],
    },
    "Purchase Receipt": {
        "validate": "tongjianyun.special_orders.check_receipt",
        "before_update_after_submit": "tongjianyun.special_orders.check_receipt",
        "before_submit": ["tongjianyun.canteen_ops.purchasing.check_receipt",
                          "tongjianyun.canteen_ops.inventory.on_purchase_return"],
        "before_cancel": "tongjianyun.canteen_ops.inventory.check_cancel",
    },
    "Stock Entry": {"before_submit": "tongjianyun.canteen_ops.inventory.check_stock_entry",
                    "before_cancel": "tongjianyun.canteen_ops.inventory.check_cancel"},
    "Purchase Invoice": {"before_submit": "tongjianyun.canteen_ops.finance.check_invoice"},
    "Journal Entry": {"before_submit": "tongjianyun.canteen_ops.finance.check_journal"},
    "BOM": {
        "validate": "tongjianyun.standard_recipes.validate_recipe",
        "before_save": "tongjianyun.standard_recipes.save_draft",
        "before_submit": ["tongjianyun.standard_recipes.publish_recipe", "tongjianyun.recipe_nutrition.freeze_recipe"],
        "on_update": "tongjianyun.dish_library.enroll_from_recipe",
        "on_submit": "tongjianyun.ingredient_library.enroll_from_recipe",
    },
}

# Existing tables remain readable by administrators; no historical record can be mutated.
permission_query_conditions = {name: "tongjianyun.archive.query_condition" for name in _LEGACY_DOCTYPES} | _CANTEEN_QUERIES
has_permission = {name: "tongjianyun.archive.document_permission" for name in _LEGACY_DOCTYPES} | {
    name: "tongjianyun.canteen_ops.common.scoped_permission" for name in _CANTEEN_DOCTYPES
}
