from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class TongjianyunNutritionRuleRevision(Document):
    def validate(self) -> None:
        if not self.is_new() and not getattr(self.flags, "nutrition_rule_audit", False):
            frappe.throw(_("营养规则审计记录不可修改。"))

    def on_trash(self) -> None:
        if not getattr(self.flags, "nutrition_rule_audit", False):
            frappe.throw(_("营养规则审计记录不可删除。"))
