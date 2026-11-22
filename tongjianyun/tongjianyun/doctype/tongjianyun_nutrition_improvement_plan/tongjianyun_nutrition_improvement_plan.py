from frappe.model.document import Document
from tongjianyun import special_ingredients


class TongjianyunNutritionImprovementPlan(Document):
    def validate(self):
        special_ingredients.validate_plan(self)

    def before_submit(self):
        special_ingredients.activate_plan(self)

    def before_cancel(self):
        special_ingredients._lock_company(self.company)
