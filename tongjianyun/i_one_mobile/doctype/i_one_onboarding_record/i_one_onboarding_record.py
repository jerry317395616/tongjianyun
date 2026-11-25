import frappe
from frappe.model.document import Document


class IONEOnboardingRecord(Document):
	def before_insert(self):
		self.user = self.user or frappe.session.user
		self.status = self.status or "未开始"

	def validate(self):
		if self.user == "Guest":
			frappe.throw("访客不能创建引导记录")
		if self.is_new() and frappe.db.exists(
			"I-ONE Onboarding Record",
			{"user": self.user, "flow": self.flow, "name": ["!=", self.name]},
		):
			frappe.throw("该用户已经存在此引导流程的记录")
