import frappe
from frappe.utils import getdate

from tongjianyun.canteen_ops.common import TASK
from tongjianyun.canteen_ops.task_menus import WeekMenus
from tongjianyun.weekly_menu_setup import install_week_canteen


def execute():
    install_week_canteen()
    scopes = frappe.get_all(TASK, filters={"docstatus": 0}, fields=["company", "week_start"],
                            group_by="company, week_start", order_by="company, week_start")
    for row in scopes:
        monday = getdate(row.week_start)
        scope = WeekMenus(row.company, [monday], lock=True)
        # Before this migration a draft link could only have been explicitly supplied.
        for task in scope.tasks[monday]:
            if not task.docstatus and task.meal_week and not task.menu_confirmed:
                frappe.db.set_value(TASK, task.name, "menu_confirmed", 1, update_modified=False)
                task.menu_confirmed = 1
        scope.apply(monday)
