from frappe.model.document import Document
from tongjianyun import student_meals


class TongjianyunClassMealConfirmation(Document):
    def autoname(self):
        self.name = student_meals.record_name(self.meal_date, self.student_group)

    def validate(self):
        student_meals.validate(self)

    def on_update(self):
        from tongjianyun.daily_meals import refresh_confirmation
        refresh_confirmation(self.meal_date, force=True)
