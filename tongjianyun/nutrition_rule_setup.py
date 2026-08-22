from __future__ import annotations

import frappe
from frappe.utils import now_datetime, today

from tongjianyun.nutrition_rule_service import (
    REVISION_DOCTYPE,
    RULE_SET_DOCTYPE,
    _new_rule_document,
    _record_revision,
)
from tongjianyun.nutrition_rules import default_rule_set, normalize_rule_set


def install() -> None:
    """Create the immutable default V1 record once the rule DocTypes exist."""
    if not frappe.db.exists("DocType", RULE_SET_DOCTYPE):
        return
    if frappe.db.exists(RULE_SET_DOCTYPE, "DEFAULT-V1"):
        return

    config = default_rule_set()
    config["status"] = "已发布"
    config = normalize_rule_set(config)
    document = _new_rule_document(
        config,
        previous_version=None,
        change_reason="系统初始化：保持现有周食谱营养分析计算口径",
    )
    document.effective_from = today()
    document.approved_by = frappe.session.user
    document.approved_at = now_datetime()
    document.published_by = frappe.session.user
    document.published_at = now_datetime()
    document.flags.nutrition_rule_transition = True
    document.insert(ignore_permissions=True)
    if frappe.db.exists("DocType", REVISION_DOCTYPE):
        _record_revision(
            document.name, "发布", "", document.rule_hash, config, {"source": "install"}
        )
