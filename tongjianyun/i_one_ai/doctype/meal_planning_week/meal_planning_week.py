from frappe.model.document import Document


class MealPlanningWeek(Document):
    def validate(self):
        from tongjianyun.meal_planning import validate_week

        validate_week(self)

    def before_submit(self):
        from tongjianyun.meal_planning import submit_week

        submit_week(self)

    def before_update_after_submit(self):
        from tongjianyun.meal_planning import validate_week

        validate_week(self)

    def before_cancel(self):
        from tongjianyun.meal_planning import validate_week

        validate_week(self)

    def on_cancel(self):
        from tongjianyun.meal_planning import cancel_week

        cancel_week(self)
