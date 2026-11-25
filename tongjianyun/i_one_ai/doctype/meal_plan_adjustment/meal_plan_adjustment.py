from frappe.model.document import Document

from tongjianyun import meal_adjustments


class MealPlanAdjustment(Document):
	def validate(self):
		return meal_adjustments.validate_adjustment(self)

	def before_submit(self):
		return meal_adjustments.before_submit_adjustment(self)

	def on_submit(self):
		return meal_adjustments.on_submit_adjustment(self)

	def before_cancel(self):
		return meal_adjustments.before_cancel_adjustment(self)

	def before_update_after_submit(self):
		return meal_adjustments.before_update_after_submit_adjustment(self)
