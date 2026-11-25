import frappe
from frappe.model.document import Document
from frappe.utils import get_first_day, getdate


class IONEOperatingTarget(Document):
	def validate(self):
		self.target_month = get_first_day(getdate(self.target_month))
		for fieldname in ("revenue_target", "profit_target", "customer_target"):
			if (self.get(fieldname) or 0) < 0:
				frappe.throw("经营目标不能小于 0")

		duplicate = frappe.db.exists(
			"I-ONE Operating Target",
			{
				"company": self.company,
				"target_month": self.target_month,
				"name": ["!=", self.name or ""],
			},
		)
		if duplicate:
			frappe.throw("该公司本月已经设置经营目标")
