"""Install native tabs for the weekly meal planning form."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from tongjianyun.meal_portions import PENDING, SCOPE, SOURCE

WEEK = "Meal Planning Week"
BASIC_TAB = "custom_tjy_week_basic_tab"
CALENDAR_TAB = "custom_tjy_week_calendar_tab"
CALENDAR_FIELD = "custom_tjy_week_calendar"


def install_week_canteen():
    create_custom_fields({WEEK: [{"fieldname": "custom_tjy_canteen", "fieldtype": "Link", "label": "食堂",
                                  "options": "Tongjianyun Canteen", "insert_after": "company",
                                  "module": "Tongjianyun"}]})


def install():
    install_week_canteen()
    saved_only = "eval:!doc.__islocal"
    create_custom_fields({WEEK: [
        {"fieldname": BASIC_TAB, "fieldtype": "Tab Break", "label": "基本信息",
         "module": "Tongjianyun"},
        {"fieldname": CALENDAR_TAB, "fieldtype": "Tab Break", "label": "供餐周历",
         "insert_after": "amended_from", "depends_on": saved_only, "module": "Tongjianyun"},
        {"fieldname": CALENDAR_FIELD, "fieldtype": "HTML", "label": "周历",
         "insert_after": CALENDAR_TAB, "depends_on": saved_only, "module": "Tongjianyun"},
    ], "BOM": [
        {"fieldname": SOURCE, "fieldtype": "Link", "options": "BOM", "label": "本餐来源配方",
         "insert_after": "item", "hidden": 1, "read_only": 1, "no_copy": 1, "module": "Tongjianyun"},
        {"fieldname": SCOPE, "fieldtype": "Data", "label": "本餐用量归属", "insert_after": SOURCE,
         "hidden": 1, "read_only": 1, "no_copy": 1, "module": "Tongjianyun"},
    ], "Meal Plan Adjustment": [
        {"fieldname": PENDING, "fieldtype": "Long Text", "label": "本餐带量调整", "insert_after": "dishes",
         "hidden": 1, "read_only": 1, "no_copy": 1, "module": "Tongjianyun"},
    ]})
