import frappe
from frappe.model.document import Document


class IONESmartRecord(Document):
	def before_insert(self):
		self.submitted_by = self.submitted_by or frappe.session.user
		self.status = self.status or "草稿"

	def validate(self):
		if not self.raw_text and not self.attachment:
			frappe.throw("原始内容和附件不能同时为空")
