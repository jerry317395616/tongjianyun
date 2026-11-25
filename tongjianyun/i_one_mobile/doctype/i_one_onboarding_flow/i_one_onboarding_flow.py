import json

import frappe
from frappe.model.document import Document
from frappe.utils import cint

from tongjianyun.onboarding_ordering import normalize_step_order


class IONEOnboardingFlow(Document):
	def validate(self):
		previous = self.get_doc_before_save()
		if previous and self.status == "已发布" and cint(self.version) <= cint(previous.version):
			self.version = max(cint(previous.version), 1) + 1

		self.set(
			"steps",
			normalize_step_order(self.steps, previous.steps if previous else None),
		)

		step_codes = [row.step_code for row in self.steps]
		if len(step_codes) != len(set(step_codes)):
			frappe.throw("步骤编码不能重复")

		valid_steps = set(step_codes)
		option_keys = set()
		for row in self.options:
			if row.step_code not in valid_steps:
				frappe.throw(f"选项 {row.label} 对应的步骤编码不存在")
			key = (row.step_code, row.option_code)
			if key in option_keys:
				frappe.throw(f"步骤 {row.step_code} 中的选项编码不能重复")
			option_keys.add(key)
			for fieldname in ("strengths_json", "team_json", "automation_json", "manual_json"):
				value = row.get(fieldname)
				if value:
					try:
						json.loads(value)
					except (TypeError, ValueError):
						frappe.throw(f"选项 {row.label} 的{row.meta.get_label(fieldname)}不是有效 JSON")

		for fieldname in (
			"default_strengths_json",
			"default_team_json",
			"default_automation_json",
			"default_manual_json",
		):
			value = self.get(fieldname)
			if value:
				try:
					json.loads(value)
				except (TypeError, ValueError):
					frappe.throw(f"{self.meta.get_label(fieldname)}不是有效 JSON")

	def on_update(self):
		if self.is_default:
			frappe.db.set_value(
				"I-ONE Onboarding Flow",
				{"name": ["!=", self.name], "is_default": 1},
				"is_default",
				0,
				update_modified=False,
			)
