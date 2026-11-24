import hashlib
import json
import secrets

import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils import today

from tongjianyun.canteen_ops.common import WEEK, require
from tongjianyun.canteen_ops.meal_operations import OPINION, PUBLIC, menu_lines


def _published(key):
    require(isinstance(key, str) and 32 <= len(key) <= 80, "查看码无效。")
    name = frappe.db.get_value(PUBLIC, {"public_key": key, "docstatus": 1})
    require(name, "这份公示已撤回或查看码无效。")
    pub = frappe.get_doc(PUBLIC, name)
    if pub.meal_week:
        require(frappe.db.get_value(WEEK, pub.meal_week, "docstatus") == 1, "来源食谱已撤回。")
    return pub


def refresh_publication(doc, method=None):
    for name in frappe.get_all(PUBLIC, filters={"meal_week": doc.meal_week, "docstatus": 1}, pluck="name"):
        pub = frappe.get_doc(PUBLIC, name, for_update=True)
        snapshot = menu_lines(pub)
        reason = "已撤回本次调整" if doc.docstatus == 2 else (
            doc.get("custom_tjy_family_notice") or ("调整本餐供餐安排" if doc.get("service_suspended") else "调整本餐菜单或带量"))
        pub.db_set({"public_menu": frappe.as_json(snapshot), "public_revision": (pub.public_revision or 1) + 1,
                    "change_notice": f"{doc.meal_date} {doc.meal_type} · {reason}"})



@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=8, seconds=600)
def send_opinion(key, category, opinion, menu_detail=None):
    from tongjianyun.canteen_ops.meal_operations import family_submission
    pub = _published(key)
    require(category in ("菜品与营养", "食品安全", "供餐服务") and isinstance(opinion, str)
            and 1 <= len(opinion.strip()) <= 1500, "请选择类别，并填写1500字以内的意见。")
    if menu_detail:
        valid = {f"{r['date']} · {r['slot']} · {r['menu']}" for r in json.loads(pub.public_menu or "[]")}
        require(menu_detail in valid, "请选择当前公示中的餐次或菜品。")
    token = secrets.token_urlsafe(32)
    doc = frappe.get_doc({"doctype": OPINION, "company": pub.company, "canteen": pub.canteen,
        "publication": pub.name, "service_date": today(), "category": category, "opinion": opinion.strip(), "menu_detail": menu_detail or None,
        "receipt_hash": hashlib.sha256(token.encode()).hexdigest()})
    context = family_submission.set(True)
    try:
        doc.insert(ignore_permissions=True)
    finally:
        family_submission.reset(context)
    return token


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=30, seconds=600)
def read_reply(key, receipt):
    pub = _published(key)
    require(isinstance(receipt, str) and 32 <= len(receipt) <= 80, "请输入有效回执码。")
    row = frappe.db.get_value(OPINION, {"receipt_hash": hashlib.sha256(receipt.encode()).hexdigest(),
        "publication": pub.name, "docstatus": ["<", 2]}, ["docstatus", "reply"], as_dict=True)
    require(row, "未找到该回执。")
    return row.reply if row.docstatus == 1 else "已收到，正在办理。"


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=60, seconds=600)
def current_revision(key):
    return _published(key).public_revision or 1


def public_view(key):
    pub = _published(key)
    return dict(company=pub.company, start=str(pub.week_start), operator=pub.operator_name, origins=pub.origins,
                revision=pub.public_revision or 1, change_notice=pub.change_notice, additives=pub.additives, meals=json.loads(pub.public_menu or "[]"))
