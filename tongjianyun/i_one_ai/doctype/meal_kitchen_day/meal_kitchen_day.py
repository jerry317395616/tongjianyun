from frappe.model.document import Document

from tongjianyun import meal_kitchen


class MealKitchenDay(Document):
	def validate(self):
		return meal_kitchen.validate_day(self)

	def before_submit(self):
		return meal_kitchen.before_submit_day(self)

	def on_submit(self):
		return meal_kitchen.on_submit_day(self)

	def before_cancel(self):
		return meal_kitchen.before_cancel_day(self)

	def before_update_after_submit(self):
		return meal_kitchen.before_update_after_submit_day(self)
