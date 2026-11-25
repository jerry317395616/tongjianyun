import frappe
from frappe.model.document import Document


class IONEExperience(Document):
	def before_insert(self):
		self.author_user = self.author_user or frappe.session.user
