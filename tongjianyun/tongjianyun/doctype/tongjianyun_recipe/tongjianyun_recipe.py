import frappe
from frappe import _
from frappe.model.document import Document


class TongjianyunRecipe(Document):
    def validate(self):
        if self.week_start and self.week_end and self.week_start > self.week_end:
            frappe.throw(_("结束日期不能早于开始日期。"))
        from tongjianyun.recipe_week import validate_weekly_recipe
        validate_weekly_recipe(self)
