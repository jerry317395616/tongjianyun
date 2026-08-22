from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from tongjianyun.nutrition_rule_service import document_to_rule_set
from tongjianyun.nutrition_rules import NutritionFormulaError, normalize_rule_set


class TongjianyunNutritionRuleSet(Document):
    def validate(self) -> None:
        previous = self.get_doc_before_save()
        service_transition = bool(
            getattr(self.flags, "nutrition_rule_transition", False)
        )
        if (
            self.is_new()
            and self.status in {"待审核", "已发布", "已停用"}
            and not service_transition
        ):
            frappe.throw(_("待审核或已发布规则必须通过受控流程创建。"))
        if (
            previous
            and previous.status in {"待审核", "已发布", "已停用"}
            and not service_transition
        ):
            frappe.throw(
                _("待审核、已发布或已停用的规则不可直接修改，请基于该版本创建新草稿。")
            )
        if (
            previous
            and self.status in {"待审核", "已发布", "已停用"}
            and self.status != previous.status
            and not service_transition
        ):
            frappe.throw(_("规则送审、发布和停用必须通过受控流程完成。"))
        try:
            normalized = normalize_rule_set(document_to_rule_set(self))
        except NutritionFormulaError as exc:
            frappe.throw(str(exc))
        self.rule_hash = normalized["rule_hash"]

    def on_trash(self) -> None:
        if self.status == "已发布":
            frappe.throw(_("当前生效规则不能删除。请先发布其他规则，再停用本规则。"))
