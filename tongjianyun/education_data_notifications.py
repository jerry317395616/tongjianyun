from __future__ import annotations

import frappe
from frappe.desk.doctype.notification_log.notification_log import make_notification_logs
from frappe.utils import today


RECIPIENT_ROLES = (
    "Tongjianyun Administrator",
    "园长",
    "教育管理员",
)

EDUCATION_DATA = (
    ("Student Group", "班级信息", "student-group"),
    ("Student", "学生信息", "student"),
)


def get_missing_education_data() -> list[dict[str, str]]:
    """Return the education masters that currently have no records."""
    return [
        {"doctype": doctype, "label": label, "route": route}
        for doctype, label, route in EDUCATION_DATA
        if frappe.db.count(doctype) == 0
    ]


def get_notification_recipients() -> list[str]:
    """Return active system-user email addresses for scoped management roles."""
    user_names = set(
        frappe.get_all(
            "Has Role",
            filters={"parenttype": "User", "role": ["in", RECIPIENT_ROLES]},
            pluck="parent",
        )
    )
    if not user_names:
        return []

    users = frappe.get_all(
        "User",
        filters={
            "name": ["in", sorted(user_names)],
            "enabled": 1,
            "user_type": "System User",
        },
        fields=["email"],
    )
    return sorted({user.email for user in users if user.email})


def notify_missing_education_data(doc=None, method=None) -> dict:
    """Create one in-app alert per missing-data state and day.

    This runs daily and immediately after Student or Student Group deletion. The
    Frappe Alert notification type is deliberately used because it never sends
    email; it only appears in the Desk notification panel.
    """
    missing = get_missing_education_data()
    if not missing:
        return {"notified": False, "reason": "education_data_complete"}

    recipients = get_notification_recipients()
    if not recipients:
        return {
            "notified": False,
            "reason": "no_active_recipients",
            "missing": [item["label"] for item in missing],
        }

    labels = [item["label"] for item in missing]
    missing_key = "+".join(item["route"] for item in missing)
    notification_key = f"missing-education-data:{today()}:{missing_key}"
    link = f'/desk/{missing[0]["route"]}'

    notification = frappe._dict(
        {
            "type": "Alert",
            "title": f"童健云基础资料缺失：{'、'.join(labels)}",
            "description": (
                f"系统检测到尚未建立<b>{'、'.join(labels)}</b>。"
                "请进入教育管理完成基础资料维护，以确保就餐确认、食谱计划和营养分析正常使用。"
            ),
            "app": "tongjianyun",
            "link": link,
            "document_name": notification_key,
            "from_user": "Administrator",
            "dedupe_on": ["type", "app", "document_name", "title"],
        }
    )
    make_notification_logs(notification, recipients)

    return {
        "notified": True,
        "missing": labels,
        "recipients": recipients,
        "notification_key": notification_key,
    }
