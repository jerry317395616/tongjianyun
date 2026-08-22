from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime, today

from tongjianyun.nutrition_rules import (
    NUTRIENT_KEYS,
    default_rule_set,
    normalize_rule_set,
)
from tongjianyun.recipe_analysis import analyze_recipe_payload
from tongjianyun.recipe_storage import get_recipe_detail


RULE_SET_DOCTYPE = "Tongjianyun Nutrition Rule Set"
REVISION_DOCTYPE = "Tongjianyun Nutrition Rule Revision"
EDITOR_ROLES = {"System Manager", "Tongjianyun Administrator", "Tongjianyun Nutrition"}
PUBLISHER_ROLES = {"System Manager", "Tongjianyun Administrator"}


def document_to_rule_set(document: Any) -> dict[str, Any]:
    return {
        "rule_code": document.get("rule_code") or document.get("name"),
        "title": document.get("title"),
        "version": document.get("version"),
        "status": document.get("status"),
        "source": document.get("source"),
        "rules": [
            {
                "nutrient": row.get("nutrient"),
                "unit": row.get("unit"),
                "formula": row.get("formula"),
                "edible_ratio": row.get("edible_ratio"),
                "retention_rate": row.get("retention_rate"),
                "lower_percent": row.get("lower_percent"),
                "upper_percent": row.get("upper_percent"),
                "enabled": row.get("enabled"),
            }
            for row in document.get("rules") or []
        ],
        "macro_factors": {
            "carbohydrate": document.get("carbohydrate_energy_factor"),
            "fat": document.get("fat_energy_factor"),
            "protein": document.get("protein_energy_factor"),
        },
        "macro_ranges": {
            "carbohydrate": [
                document.get("carbohydrate_energy_low"),
                document.get("carbohydrate_energy_high"),
            ],
            "fat": [document.get("fat_energy_low"), document.get("fat_energy_high")],
            "protein": [
                document.get("protein_energy_low"),
                document.get("protein_energy_high"),
            ],
        },
        "animal_protein_target": document.get("animal_protein_target"),
        "animal_soy_protein_target": document.get("animal_soy_protein_target"),
    }


def get_active_rule_set(on_date: str | None = None) -> dict[str, Any]:
    if not _rule_doctype_available():
        return normalize_rule_set(default_rule_set())
    target_date = getdate(on_date or today())
    candidates = frappe.get_all(
        RULE_SET_DOCTYPE,
        filters={"status": "已发布"},
        fields=["name", "effective_from", "modified"],
        order_by="effective_from desc, modified desc",
    )
    for candidate in candidates:
        if (
            not candidate.effective_from
            or getdate(candidate.effective_from) <= target_date
        ):
            return normalize_rule_set(
                document_to_rule_set(frappe.get_doc(RULE_SET_DOCTYPE, candidate.name))
            )
    return normalize_rule_set(default_rule_set())


def get_rule_set_config(
    rule_set: str, *, check_permission: bool = True
) -> dict[str, Any]:
    document = frappe.get_doc(RULE_SET_DOCTYPE, rule_set)
    if check_permission:
        document.check_permission("read")
    return normalize_rule_set(document_to_rule_set(document))


@frappe.whitelist()
def list_rule_sets(status: str | None = None, limit: int = 20) -> dict[str, Any]:
    filters = {"status": status} if status else None
    rows = frappe.get_list(
        RULE_SET_DOCTYPE,
        filters=filters,
        fields=[
            "name",
            "rule_code",
            "title",
            "version",
            "status",
            "effective_from",
            "rule_hash",
            "modified",
        ],
        order_by="modified desc",
        limit_page_length=min(max(int(limit or 20), 1), 100),
    )
    active = get_active_rule_set()
    return {"active": _rule_summary(active), "rules": rows}


@frappe.whitelist()
def create_rule_draft(
    title: str,
    changes: str | dict[str, Any],
    base_rule_set: str | None = None,
    change_reason: str | None = None,
) -> dict[str, Any]:
    _require_roles(EDITOR_ROLES, "您没有创建营养规则草稿的权限。")
    if not str(title or "").strip():
        frappe.throw(_("规则名称不能为空。"))
    parsed_changes = _parse_changes(changes)
    base = (
        get_rule_set_config(base_rule_set) if base_rule_set else get_active_rule_set()
    )
    candidate = _merge_changes(base, parsed_changes)
    timestamp = now_datetime()
    candidate["rule_code"] = (
        f"NR-{timestamp:%Y%m%d-%H%M%S}-{frappe.generate_hash(length=4).upper()}"
    )
    candidate["title"] = str(title).strip()
    candidate["version"] = str(
        parsed_changes.get("version") or f"{timestamp:%Y.%m.%d.%H%M%S}"
    )
    candidate["status"] = "草稿"
    if "source" in parsed_changes:
        candidate["source"] = str(parsed_changes.get("source") or "")
    candidate = normalize_rule_set(candidate)
    document = _new_rule_document(
        candidate,
        previous_version=base_rule_set or _database_rule_name(base.get("rule_code")),
        change_reason=change_reason
        or parsed_changes.get("change_reason")
        or "由 IONE Harness 创建规则草稿",
    )
    document.insert()
    _record_revision(
        document.name, "创建草稿", "", document.rule_hash, candidate, parsed_changes
    )
    return {
        "rule_set": document.name,
        "status": document.status,
        "rule_hash": document.rule_hash,
        "version": document.version,
    }


@frappe.whitelist()
def preview_rule_set(rule_set: str, recipe: str | None = None) -> dict[str, Any]:
    draft_document = frappe.get_doc(RULE_SET_DOCTYPE, rule_set)
    draft_document.check_permission("read")
    recipe_name = recipe or _latest_recipe()
    if not recipe_name:
        frappe.throw(_("暂无可用于试算的食谱。"))
    recipe_document = frappe.get_doc("Tongjianyun Recipe", recipe_name)
    recipe_document.check_permission("read")
    payload = get_recipe_detail(recipe_document.name)
    active = get_active_rule_set()
    candidate = normalize_rule_set(document_to_rule_set(draft_document))
    before = analyze_recipe_payload(payload, rule_set=active)
    after = analyze_recipe_payload(payload, rule_set=candidate)
    differences = []
    for nutrient in NUTRIENT_KEYS:
        old_value = float(before["nutrients"].get(nutrient, 0) or 0)
        new_value = float(after["nutrients"].get(nutrient, 0) or 0)
        differences.append(
            {
                "nutrient": nutrient,
                "before": old_value,
                "after": new_value,
                "change": new_value - old_value,
                "change_percent": (new_value - old_value) / old_value * 100
                if old_value
                else (100.0 if new_value else 0.0),
                "before_status": before.get("nutrient_evaluations", {})
                .get(nutrient, {})
                .get("status"),
                "after_status": after.get("nutrient_evaluations", {})
                .get(nutrient, {})
                .get("status"),
            }
        )
    result = {
        "recipe": recipe_document.name,
        "active_rule": _rule_summary(active),
        "candidate_rule": _rule_summary(candidate),
        "differences": differences,
        "before_conclusion": before["conclusion"],
        "after_conclusion": after["conclusion"],
    }
    _record_revision(
        draft_document.name,
        "试算",
        active.get("rule_hash", ""),
        candidate.get("rule_hash", ""),
        candidate,
        {"recipe": recipe_document.name, "differences": differences},
    )
    return result


@frappe.whitelist()
def submit_rule_set(rule_set: str) -> dict[str, Any]:
    _require_roles(EDITOR_ROLES, "您没有提交营养规则的权限。")
    document = frappe.get_doc(RULE_SET_DOCTYPE, rule_set)
    document.check_permission("write")
    if document.status != "草稿":
        frappe.throw(_("只有草稿规则可以提交审核。"))
    if not frappe.db.exists(
        REVISION_DOCTYPE,
        {"rule_set": document.name, "action": "试算", "to_hash": document.rule_hash},
    ):
        frappe.throw(_("提交审核前必须使用当前规则指纹完成至少一次真实食谱试算。"))
    old_hash = document.rule_hash
    document.status = "待审核"
    document.flags.nutrition_rule_transition = True
    document.save()
    _record_revision(
        document.name,
        "提交审核",
        old_hash,
        document.rule_hash,
        document_to_rule_set(document),
        {},
    )
    return {
        "rule_set": document.name,
        "status": document.status,
        "rule_hash": document.rule_hash,
    }


@frappe.whitelist()
def publish_rule_set(rule_set: str, confirmation: str) -> dict[str, Any]:
    _require_roles(PUBLISHER_ROLES, "只有童健云管理员或系统管理员可以发布营养规则。")
    if confirmation != "确认发布":
        frappe.throw(_("发布营养规则需要明确传入“确认发布”。"))
    document = frappe.get_doc(RULE_SET_DOCTYPE, rule_set)
    document.check_permission("write")
    if document.status != "待审核":
        frappe.throw(_("只有待审核规则可以发布。"))
    if document.effective_from and getdate(document.effective_from) > getdate(today()):
        frappe.throw(
            _("当前版本暂不支持未来日期自动切换，请将生效日期设置为今天或更早。")
        )

    frappe.db.sql(
        f"select name from `tab{RULE_SET_DOCTYPE}` where status = %s for update",
        ("已发布",),
    )
    previous_active = get_active_rule_set()
    for active_name in frappe.get_all(
        RULE_SET_DOCTYPE, filters={"status": "已发布"}, pluck="name"
    ):
        if active_name == document.name:
            continue
        active_document = frappe.get_doc(RULE_SET_DOCTYPE, active_name)
        active_document.status = "已停用"
        active_document.flags.nutrition_rule_transition = True
        active_document.save(ignore_permissions=True)
        _record_revision(
            active_document.name,
            "停用",
            active_document.rule_hash,
            active_document.rule_hash,
            document_to_rule_set(active_document),
            {"replacement": document.name},
        )

    document.status = "已发布"
    document.effective_from = document.effective_from or today()
    document.approved_by = frappe.session.user
    document.approved_at = now_datetime()
    document.published_by = frappe.session.user
    document.published_at = now_datetime()
    document.flags.nutrition_rule_transition = True
    document.save()
    config = normalize_rule_set(document_to_rule_set(document))
    _record_revision(
        document.name,
        "发布",
        previous_active.get("rule_hash", ""),
        document.rule_hash,
        config,
        {},
    )
    frappe.clear_cache(doctype=RULE_SET_DOCTYPE)
    return {
        "rule_set": document.name,
        "status": document.status,
        "rule_hash": document.rule_hash,
        "effective_from": document.effective_from,
    }


@frappe.whitelist()
def rollback_rule_set(
    target_rule_set: str, confirmation: str, change_reason: str | None = None
) -> dict[str, Any]:
    _require_roles(PUBLISHER_ROLES, "只有童健云管理员或系统管理员可以回滚营养规则。")
    if confirmation != "确认回滚":
        frappe.throw(_("回滚营养规则需要明确传入“确认回滚”。"))
    target_document = frappe.get_doc(RULE_SET_DOCTYPE, target_rule_set)
    target_document.check_permission("read")
    target = normalize_rule_set(document_to_rule_set(target_document))
    active = get_active_rule_set()
    timestamp = now_datetime()
    target.update(
        {
            "rule_code": f"NR-RB-{timestamp:%Y%m%d-%H%M%S}-{frappe.generate_hash(length=4).upper()}",
            "title": f"回滚至 {target_document.title}",
            "version": f"rollback-{timestamp:%Y.%m.%d.%H%M%S}",
            "status": "草稿",
        }
    )
    target = normalize_rule_set(target)
    document = _new_rule_document(
        target,
        previous_version=_database_rule_name(active.get("rule_code")),
        change_reason=change_reason or f"回滚至规则 {target_document.name}",
    )
    document.insert()
    _record_revision(
        document.name,
        "回滚",
        active.get("rule_hash", ""),
        document.rule_hash,
        target,
        {"target": target_document.name},
    )
    document.status = "待审核"
    document.flags.nutrition_rule_transition = True
    document.save()
    return publish_rule_set(document.name, "确认发布")


def _merge_changes(
    base: Mapping[str, Any], changes: Mapping[str, Any]
) -> dict[str, Any]:
    candidate = deepcopy(dict(base))
    for key in ("source", "animal_protein_target", "animal_soy_protein_target"):
        if key in changes:
            candidate[key] = changes[key]
    for group in ("macro_factors", "macro_ranges"):
        if isinstance(changes.get(group), Mapping):
            candidate[group].update(deepcopy(dict(changes[group])))

    supplied_rules = changes.get("rules") or {}
    if isinstance(supplied_rules, list):
        supplied_rules = {str(row.get("nutrient") or ""): row for row in supplied_rules}
    if not isinstance(supplied_rules, Mapping):
        frappe.throw(_("rules 必须是以营养指标为键的对象或规则数组。"))
    for nutrient, row in supplied_rules.items():
        if nutrient not in NUTRIENT_KEYS:
            frappe.throw(_("不支持的营养指标：{0}").format(nutrient))
        if not isinstance(row, Mapping):
            frappe.throw(_("营养指标 {0} 的规则必须是对象。").format(nutrient))
        candidate["rules"][nutrient].update(deepcopy(dict(row)))
        candidate["rules"][nutrient]["nutrient"] = nutrient
    return normalize_rule_set(candidate)


def _new_rule_document(
    config: Mapping[str, Any], *, previous_version: str | None, change_reason: str
) -> Any:
    document = frappe.new_doc(RULE_SET_DOCTYPE)
    document.rule_code = config["rule_code"]
    document.title = config["title"]
    document.version = config["version"]
    document.status = config["status"]
    document.previous_version = previous_version
    document.source = config.get("source")
    document.change_reason = change_reason
    document.carbohydrate_energy_factor = config["macro_factors"]["carbohydrate"]
    document.fat_energy_factor = config["macro_factors"]["fat"]
    document.protein_energy_factor = config["macro_factors"]["protein"]
    document.carbohydrate_energy_low, document.carbohydrate_energy_high = config[
        "macro_ranges"
    ]["carbohydrate"]
    document.fat_energy_low, document.fat_energy_high = config["macro_ranges"]["fat"]
    document.protein_energy_low, document.protein_energy_high = config["macro_ranges"][
        "protein"
    ]
    document.animal_protein_target = config["animal_protein_target"]
    document.animal_soy_protein_target = config["animal_soy_protein_target"]
    for nutrient in NUTRIENT_KEYS:
        row = config["rules"][nutrient]
        document.append(
            "rules",
            {
                "nutrient": nutrient,
                "unit": row["unit"],
                "formula": row["formula"],
                "edible_ratio": row["edible_ratio"],
                "retention_rate": row["retention_rate"],
                "lower_percent": row["lower_percent"],
                "upper_percent": row["upper_percent"] or 0,
                "enabled": row["enabled"],
            },
        )
    return document


def _record_revision(
    rule_set: str,
    action: str,
    from_hash: str,
    to_hash: str,
    snapshot: Mapping[str, Any],
    comparison: Mapping[str, Any],
) -> None:
    revision = frappe.new_doc(REVISION_DOCTYPE)
    revision.update(
        {
            "rule_set": rule_set,
            "action": action,
            "acted_by": frappe.session.user,
            "acted_at": now_datetime(),
            "from_hash": from_hash,
            "to_hash": to_hash,
            "snapshot": json.dumps(
                snapshot, ensure_ascii=False, sort_keys=True, default=str
            ),
            "comparison": json.dumps(
                comparison, ensure_ascii=False, sort_keys=True, default=str
            ),
        }
    )
    revision.flags.nutrition_rule_audit = True
    revision.insert(ignore_permissions=True)


def _parse_changes(changes: str | dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = frappe.parse_json(changes) if isinstance(changes, str) else changes
    except Exception as exc:
        frappe.throw(_("规则变更不是有效 JSON：{0}").format(exc))
    if not isinstance(parsed, Mapping):
        frappe.throw(_("规则变更必须是 JSON 对象。"))
    allowed = {
        "version",
        "source",
        "change_reason",
        "rules",
        "macro_factors",
        "macro_ranges",
        "animal_protein_target",
        "animal_soy_protein_target",
    }
    unknown = set(parsed).difference(allowed)
    if unknown:
        frappe.throw(
            _("规则变更包含不支持的字段：{0}").format(", ".join(sorted(unknown)))
        )
    return dict(parsed)


def _require_roles(allowed: set[str], message: str) -> None:
    if not allowed.intersection(frappe.get_roles(frappe.session.user)):
        frappe.throw(_(message), frappe.PermissionError)


def _latest_recipe() -> str | None:
    return frappe.db.get_value(
        "Tongjianyun Recipe",
        {"is_deleted": 0},
        "name",
        order_by="week_start desc, modified desc",
    )


def _rule_doctype_available() -> bool:
    return bool(frappe.db.exists("DocType", RULE_SET_DOCTYPE))


def _database_rule_name(rule_code: Any) -> str | None:
    code = str(rule_code or "")
    if not code or code == "DEFAULT-V1" or not _rule_doctype_available():
        return None
    return frappe.db.get_value(RULE_SET_DOCTYPE, {"rule_code": code}, "name")


def _rule_summary(config: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "rule_code": config.get("rule_code"),
        "title": config.get("title"),
        "version": config.get("version"),
        "status": config.get("status"),
        "rule_hash": config.get("rule_hash"),
    }
