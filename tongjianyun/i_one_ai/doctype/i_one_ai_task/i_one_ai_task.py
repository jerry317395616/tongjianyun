import frappe
from frappe.model.document import Document
from frappe.utils import add_to_date, now_datetime


class IONEAITask(Document):
	def before_insert(self):
		self.requested_by = self.requested_by or frappe.session.user
		self.status = self.status or ("待审批" if self.approval_required else "草稿")

	def after_insert(self):
		if not self.approval_required or self.approval:
			return
		settings = frappe.get_single("I-ONE Settings")
		agent_approver = (
			frappe.db.get_value("I-ONE Agent", self.assigned_agent, "default_approver")
			if self.assigned_agent
			else None
		)
		approver = agent_approver or settings.default_approver or "Administrator"
		approval = frappe.get_doc(
			{
				"doctype": "I-ONE Approval Request",
				"owner": self.owner,
				"task": self.name,
				"requested_by": self.requested_by,
				"approver": approver,
				"status": "待审批",
				"risk_level": self.risk_level or "中",
				"request_summary": self.title,
				"expires_at": add_to_date(now_datetime(), hours=24),
			}
		).insert(ignore_permissions=True)
		self.db_set("approval", approval.name, update_modified=False)
