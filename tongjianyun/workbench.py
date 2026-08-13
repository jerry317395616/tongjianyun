from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime, today


WORKSPACE_NAME = "童健云"
RECIPE_DOCTYPE = "Tongjianyun Recipe"
DISH_DOCTYPE = "Tongjianyun Recipe Dish"
CONFIRMATION_DOCTYPE = "Tongjianyun Daily Meal Confirmation"
SPECIAL_DIET_DOCTYPE = "Tongjianyun Special Diet"
PURCHASE_DOCTYPE = "Tongjianyun Food Purchase"
SUPPLIER_DOCTYPE = "Tongjianyun Food Supplier"
SAMPLE_DOCTYPE = "Tongjianyun Food Sample"
TRACE_DOCTYPE = "Tongjianyun Food Trace Event"

CLOSED_STATUSES = ("完成", "已完成", "关闭", "已关闭", "closed", "completed", "done")


def _require_login() -> None:
    if frappe.session.user == "Guest":
        frappe.throw(_("Not logged in."), frappe.AuthenticationError)


def _can_read(doctype: str) -> bool:
    return bool(frappe.db.table_exists(doctype) and frappe.has_permission(doctype, "read"))


def _count(doctype: str, filters: Any = None) -> int:
    if not _can_read(doctype):
        return 0
    return int(frappe.db.count(doctype, filters=filters or {}) or 0)


def _current_recipe() -> dict[str, Any] | None:
    if not _can_read(RECIPE_DOCTYPE):
        return None
    current_day = getdate(today())
    rows = frappe.get_list(
        RECIPE_DOCTYPE,
        filters={"week_start": ["<=", current_day], "week_end": [">=", current_day]},
        fields=["name", "recipe_id", "title", "week_start", "week_end", "modified"],
        order_by="modified desc",
        page_length=1,
    )
    return dict(rows[0]) if rows else None


def _today_confirmation() -> dict[str, Any] | None:
    if not _can_read(CONFIRMATION_DOCTYPE):
        return None
    rows = frappe.get_list(
        CONFIRMATION_DOCTYPE,
        filters={"meal_date": getdate(today())},
        fields=[
            "name",
            "meal_date",
            "status",
            "total_enrolled_count",
            "total_lunch_count",
            "total_special_diet_count",
            "modified",
        ],
        page_length=1,
    )
    return dict(rows[0]) if rows else None


def _open_count(doctype: str) -> int:
    if not _can_read(doctype):
        return 0
    return sum(
        1
        for row in frappe.get_list(doctype, fields=["status"], page_length=0)
        if str(row.status or "").strip().lower() not in CLOSED_STATUSES
    )


def _status(done: bool, *, attention: bool = False) -> tuple[str, str]:
    if attention:
        return "attention", "需要处理"
    if done:
        return "done", "已完成"
    return "pending", "待开始"


@frappe.whitelist()
def get_overview() -> dict[str, Any]:
    _require_login()
    recipe = _current_recipe()
    confirmation = _today_confirmation()
    dish_count = _count(DISH_DOCTYPE, {"recipe": recipe["name"]}) if recipe else 0
    student_count = _count("Student", {"enabled": 1})
    group_count = _count("Student Group", {"disabled": 0})
    special_diet_count = _count(SPECIAL_DIET_DOCTYPE, {"status": "生效中"})
    purchase_total = _count(PURCHASE_DOCTYPE)
    purchase_open = _open_count(PURCHASE_DOCTYPE)
    sample_total = _count(SAMPLE_DOCTYPE)
    trace_open = _open_count(TRACE_DOCTYPE)
    supplier_total = _count(SUPPLIER_DOCTYPE)

    attendance_done = bool(confirmation and confirmation.get("status") in {"已确认", "已锁定"})
    attendance_status = _status(attendance_done, attention=bool(confirmation and not attendance_done))
    recipe_status = _status(bool(recipe and dish_count))
    purchase_status = _status(bool(purchase_total), attention=bool(purchase_open))
    sample_status = _status(bool(sample_total))
    trace_status = _status(not bool(trace_open), attention=bool(trace_open))

    steps = [
        {
            "id": "attendance",
            "number": "01",
            "title": "确认今日就餐人数",
            "description": "系统自动读取教育管理中的班级、考勤和请假数据，在此核对就餐人数与例外调整。",
            "status": attendance_status[0],
            "status_label": attendance_status[1],
            "action_label": "确认今日人数",
            "route_type": "DocType",
            "route": CONFIRMATION_DOCTYPE,
        },
        {
            "id": "recipe",
            "number": "02",
            "title": "编制本周食谱",
            "description": "根据就餐人数、年龄段和特殊膳食安排每日菜品与食材用量。",
            "status": recipe_status[0],
            "status_label": recipe_status[1],
            "action_label": "打开食谱",
            "route_type": "Page",
            "route": "tongjianyun-recipe-workbench",
        },
        {
            "id": "purchase",
            "number": "03",
            "title": "执行食材采购",
            "description": "依据食谱和确认人数形成采购任务，跟踪供应商、数量与状态。",
            "status": purchase_status[0],
            "status_label": purchase_status[1],
            "action_label": "处理采购",
            "route_type": "DocType",
            "route": PURCHASE_DOCTYPE,
        },
        {
            "id": "sample",
            "number": "04",
            "title": "完成供餐与留样",
            "description": "供餐后登记留样信息，保留日期、餐次、菜品和责任记录。",
            "status": sample_status[0],
            "status_label": sample_status[1],
            "action_label": "登记留样",
            "route_type": "DocType",
            "route": SAMPLE_DOCTYPE,
        },
        {
            "id": "trace",
            "number": "05",
            "title": "风险追溯闭环",
            "description": "发现异常时登记追溯事件，持续处理直至风险关闭。",
            "status": trace_status[0],
            "status_label": "运行正常" if not trace_open else trace_status[1],
            "action_label": "查看追溯",
            "route_type": "DocType",
            "route": TRACE_DOCTYPE,
        },
    ]
    next_step = next((step for step in steps if step["status"] in {"attention", "pending"}), steps[-1])
    return {
        "generated_at": str(now_datetime()),
        "date_label": getdate(today()).strftime("%Y年%m月%d日"),
        "recipe": recipe,
        "confirmation": confirmation,
        "steps": steps,
        "next_step": next_step,
        "metrics": [
            {
                "label": "在园幼儿",
                "value": student_count,
                "suffix": "人",
                "hint": f"共 {group_count} 个班级",
            },
            {
                "label": "今日午餐",
                "value": int((confirmation or {}).get("total_lunch_count") or 0),
                "suffix": "人",
                "hint": (confirmation or {}).get("status") or "等待考勤数据",
            },
            {
                "label": "特殊膳食",
                "value": special_diet_count,
                "suffix": "人",
                "hint": "过敏与饮食禁忌需重点核对",
            },
            {
                "label": "待处理风险",
                "value": trace_open,
                "suffix": "项",
                "hint": "全部风险已闭环" if not trace_open else "请优先完成风险处置",
            },
        ],
        "supporting": {
            "supplier_count": supplier_total,
            "sample_count": sample_total,
        },
    }


def install() -> None:
    if not frappe.db.exists("Workspace", WORKSPACE_NAME):
        return
    workspace = frappe.get_doc("Workspace", WORKSPACE_NAME)
    workspace.set("sidebar_items", [])
    for item in _sidebar_items():
        workspace.append("sidebar_items", item)
    workspace.set("shortcuts", [])
    for item in _shortcuts():
        workspace.append("shortcuts", item)
    workspace.set("links", [])
    for item in _workspace_links():
        workspace.append("links", item)
    workspace.content = json.dumps(_workspace_content(), ensure_ascii=False, separators=(",", ":"))
    workspace.save(ignore_permissions=True)
    frappe.clear_cache()


def _sidebar_items() -> list[dict[str, Any]]:
    return [
        _sidebar_link("业务工作台", "Page", "tongjianyun-workbench", "layout-dashboard", default=1),
        _section("就餐管理", "calendar-check"),
        _sidebar_link("今日就餐确认", "DocType", CONFIRMATION_DOCTYPE, child=1),
        _sidebar_link("就餐调整记录", "DocType", "Tongjianyun Daily Meal Adjustment", child=1),
        _section("健康管理", "heart-pulse"),
        _sidebar_link("幼儿健康档案", "DocType", "Tongjianyun Child Health Profile", child=1),
        _sidebar_link("生长测量", "DocType", "Tongjianyun Growth Measurement", child=1),
        _sidebar_link("特殊膳食", "DocType", SPECIAL_DIET_DOCTYPE, child=1),
        _section("膳食营养", "salad"),
        _sidebar_link("食谱计划", "Page", "tongjianyun-recipe-workbench", child=1),
        _sidebar_link("班级膳食设置", "DocType", "Tongjianyun Class Meal Setting", child=1),
        _section("食安执行", "shield-check"),
        _sidebar_link("食材采购", "DocType", PURCHASE_DOCTYPE, child=1),
        _sidebar_link("供应商", "DocType", SUPPLIER_DOCTYPE, child=1),
        _sidebar_link("验收与留样", "DocType", SAMPLE_DOCTYPE, child=1),
        _sidebar_link("追溯事件", "DocType", TRACE_DOCTYPE, child=1),
    ]


def _sidebar_link(label, link_type, link_to, icon="", *, child=0, default=0):
    return {
        "type": "Link",
        "label": label,
        "link_type": link_type,
        "link_to": link_to,
        "icon": icon,
        "default_workspace": default,
        "child": child,
        "open_in_new_tab": 0,
        "collapsible": 1,
        "indent": 0,
        "keep_closed": 0,
        "show_arrow": 0,
    }


def _section(label: str, icon: str):
    return {
        "type": "Section Break",
        "label": label,
        "link_type": "DocType",
        "icon": icon,
        "child": 0,
        "open_in_new_tab": 0,
        "collapsible": 1,
        "indent": 1,
        "keep_closed": 1,
        "show_arrow": 1,
    }


def _shortcuts() -> list[dict[str, Any]]:
    return [
        {"type": "Page", "link_to": "tongjianyun-workbench", "label": "业务工作台", "color": "Green", "stats_filter": "[]"},
        {"type": "DocType", "link_to": CONFIRMATION_DOCTYPE, "doc_view": "List", "label": "今日就餐确认", "color": "Blue", "stats_filter": "[]"},
        {"type": "Page", "link_to": "tongjianyun-recipe-workbench", "label": "食谱计划", "color": "Green", "stats_filter": "[]"},
        {"type": "DocType", "link_to": PURCHASE_DOCTYPE, "doc_view": "List", "label": "食材采购", "color": "Orange", "stats_filter": "[]"},
    ]


def _workspace_content() -> list[dict[str, Any]]:
    return [
        {"id": "tjyWorkbench", "type": "shortcut", "data": {"shortcut_name": "业务工作台", "col": 3}},
        {"id": "tjyAttendance", "type": "shortcut", "data": {"shortcut_name": "今日就餐确认", "col": 3}},
        {"id": "tjyRecipe", "type": "shortcut", "data": {"shortcut_name": "食谱计划", "col": 3}},
        {"id": "tjyPurchase", "type": "shortcut", "data": {"shortcut_name": "食材采购", "col": 3}},
        {"id": "tjySpacer", "type": "spacer", "data": {"col": 12}},
        {"id": "tjyAttendanceCard", "type": "card", "data": {"card_name": "就餐管理", "col": 4}},
        {"id": "tjyHealthCard", "type": "card", "data": {"card_name": "健康管理", "col": 4}},
        {"id": "tjyMealCard", "type": "card", "data": {"card_name": "膳食营养", "col": 4}},
        {"id": "tjyFoodSafetyCard", "type": "card", "data": {"card_name": "食安执行", "col": 4}},
    ]


def _workspace_links() -> list[dict[str, Any]]:
    groups = [
        (
            "就餐管理",
            [
                ("今日就餐确认", "DocType", CONFIRMATION_DOCTYPE),
                ("就餐调整记录", "DocType", "Tongjianyun Daily Meal Adjustment"),
            ],
        ),
        (
            "健康管理",
            [
                ("幼儿健康档案", "DocType", "Tongjianyun Child Health Profile"),
                ("生长测量", "DocType", "Tongjianyun Growth Measurement"),
                ("特殊膳食", "DocType", SPECIAL_DIET_DOCTYPE),
            ],
        ),
        (
            "膳食营养",
            [
                ("食谱计划", "Page", "tongjianyun-recipe-workbench"),
                ("班级膳食设置", "DocType", "Tongjianyun Class Meal Setting"),
            ],
        ),
        (
            "食安执行",
            [
                ("食材采购", "DocType", PURCHASE_DOCTYPE),
                ("供应商", "DocType", SUPPLIER_DOCTYPE),
                ("验收与留样", "DocType", SAMPLE_DOCTYPE),
                ("追溯事件", "DocType", TRACE_DOCTYPE),
            ],
        ),
    ]
    links = []
    for label, items in groups:
        links.append(
            {
                "type": "Card Break",
                "label": label,
                "link_type": "DocType",
                "link_count": len(items),
                "hidden": 0,
                "onboard": 0,
                "is_query_report": 0,
            }
        )
        for item_label, link_type, link_to in items:
            links.append(
                {
                    "type": "Link",
                    "label": item_label,
                    "link_type": link_type,
                    "link_to": link_to,
                    "hidden": 0,
                    "link_count": 0,
                    "onboard": 0,
                    "is_query_report": int(link_type == "Report"),
                }
            )
    return links
