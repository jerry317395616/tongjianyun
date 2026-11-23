"""Install native tabs for the weekly meal planning form."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

WEEK = "Meal Planning Week"
BASIC_TAB = "custom_tjy_week_basic_tab"
CALENDAR_TAB = "custom_tjy_week_calendar_tab"
CALENDAR_FIELD = "custom_tjy_week_calendar"


def install():
    saved_only = "eval:!doc.__islocal"
    create_custom_fields({WEEK: [
        {"fieldname": BASIC_TAB, "fieldtype": "Tab Break", "label": "基本信息",
         "module": "Tongjianyun"},
        {"fieldname": CALENDAR_TAB, "fieldtype": "Tab Break", "label": "供餐周历",
         "insert_after": "amended_from", "depends_on": saved_only, "module": "Tongjianyun"},
        {"fieldname": CALENDAR_FIELD, "fieldtype": "HTML", "label": "周历",
         "insert_after": CALENDAR_TAB, "depends_on": saved_only, "module": "Tongjianyun"},
    ]})
