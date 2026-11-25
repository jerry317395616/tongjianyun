import frappe
from frappe.model.document import Document


class IONEGrowthPlan(Document):
	def before_insert(self):
		self.owner_user = self.owner_user or frappe.session.user
