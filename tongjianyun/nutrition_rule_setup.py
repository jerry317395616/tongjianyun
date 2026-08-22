from __future__ import annotations

import frappe
from frappe.utils import now_datetime, today

from tongjianyun.nutrition_rule_service import (
    REVISION_DOCTYPE,
    RULE_SET_DOCTYPE,
    _append_reference_rows,
    _new_rule_document,
    _record_revision,
    document_to_rule_set,
)
from tongjianyun.nutrition_rules import default_rule_set, normalize_rule_set


def install() -> None:
    """Create the immutable default V1 record once the rule DocTypes exist."""
    if not frappe.db.exists("DocType", RULE_SET_DOCTYPE):
        return
    if frappe.db.exists(RULE_SET_DOCTYPE, "DEFAULT-V1"):
        _backfill_reference_standards()
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


def _backfill_reference_standards() -> None:
    """Move legacy hard-coded standards into every existing version once."""
    for name in frappe.get_all(RULE_SET_DOCTYPE, pluck="name"):
        document = frappe.get_doc(RULE_SET_DOCTYPE, name)
        if document.get("reference_standards"):
            continue
        previous_hash = document.rule_hash or ""
        config = normalize_rule_set(document_to_rule_set(document))
        _append_reference_rows(document, config)
        document.flags.nutrition_rule_transition = True
        document.save(ignore_permissions=True)
        if frappe.db.exists("DocType", REVISION_DOCTYPE):
            _record_revision(
                document.name,
                "迁移标准",
                previous_hash,
                document.rule_hash,
                config,
                {"source": "after_migrate", "reference_standards": "backfilled"},
            )
