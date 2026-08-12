import frappe


def execute():
    if not frappe.db.table_exists("Tongjianyun Recipe"):
        return
    columns = set(frappe.db.get_table_columns("Tongjianyun Recipe"))
    if "workflow_status" not in columns:
        return
    frappe.db.sql(
        """
        update `tabTongjianyun Recipe` recipe
           set recipe.workflow_status = case
               when exists (
                   select 1
                     from `tabTongjianyun Recipe Dish` dish
                    where dish.recipe = recipe.name
               ) then '已发布'
               else '草稿'
           end,
               recipe.all_student_groups = 1
        """
    )
