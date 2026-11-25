import frappe
from frappe import _
from frappe.model.document import Document

from tongjianyun.flow_policy import MODE_ALL, MODE_CONFIRM, MODE_SELECTED


class IONEFlowExecutionPolicy(Document):
	def validate(self):
		if self.execution_mode not in {MODE_CONFIRM, MODE_SELECTED, MODE_ALL}:
			frappe.throw(_("请选择有效的执行模式。"))

		if self.execution_mode == MODE_SELECTED and not self.auto_approved_tools:
			frappe.throw(_("“指定工具自动执行”模式至少需要选择一个自动执行工具。"))

		tools = [row.tool for row in self.auto_approved_tools if row.tool]
		if len(tools) != len(set(tools)):
			frappe.throw(_("自动执行工具不能重复。"))

		if self.department and frappe.db.exists("Department", self.department):
			company = frappe.db.get_value("Department", self.department, "company")
			if company:
				self.company = company
