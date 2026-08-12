from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import get_first_day, getdate, now_datetime, today

WORKSPACE_NAME = "童健云"
RECIPE_DOCTYPE = "Tongjianyun Recipe"
DISH_DOCTYPE = "Tongjianyun Recipe Dish"
ATTENDANCE_DOCTYPE = "Tongjianyun Meal Attendance"
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


def _current_attendance() -> dict[str, Any] | None:
    if not _can_read(ATTENDANCE_DOCTYPE):
        return None
    month_start = get_first_day(today())
    rows = frappe.get_list(
        ATTENDANCE_DOCTYPE,
        filters={"month": month_start},
        fields=["name", "month_label", "status", "total_person_days", "total_meal_times", "modified"],
        order_by="modified desc",
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
    """Return permission-aware operating signals for the Tongjianyun workflow page."""

    _require_login()
    recipe = _current_recipe()
    attendance = _current_attendance()
    dish_count = _count(DISH_DOCTYPE, {"recipe": recipe["name"]}) if recipe else 0
    purchase_total = _count(PURCHASE_DOCTYPE)
    purchase_open = _open_count(PURCHASE_DOCTYPE)
    sample_total = _count(SAMPLE_DOCTYPE)
    trace_open = _open_count(TRACE_DOCTYPE)
    supplier_total = _count(SUPPLIER_DOCTYPE)

    attendance_status = _status(bool(attendance))
    recipe_status = _status(bool(recipe and dish_count))
    purchase_status = _status(bool(purchase_total), attention=bool(purchase_open))
    sample_status = _status(bool(sample_total))
    trace_status = _status(not bool(trace_open), attention=bool(trace_open))

    steps = [
        {
            "id": "attendance",
            "number": "01",
            "title": "核对就餐人数",
            "description": "按月维护各班早餐、午餐和晚餐人数，形成备餐基数。",
            "status": attendance_status[0],
            "status_label": attendance_status[1],
            "action_label": "填写人数",
            "route_type": "DocType",
            "route": ATTENDANCE_DOCTYPE,
        },
        {
            "id": "recipe",
            "number": "02",
            "title": "编制本周食谱",
            "description": "安排每日餐次、菜品和每人食材用量，确认后进入采购。",
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
            "description": "依据食谱和就餐人数形成采购任务，跟踪供应商与采购状态。",
            "status": purchase_status[0],
            "status_label": purchase_status[1],
            "action_label": "处理采购",
            "route_type": "DocType",
            "route": PURCHASE_DOCTYPE,
        },
        {
            "id": "sample",
            "number": "04",
            "title": "完成供餐留样",
            "description": "供餐后登记留样信息，保留日期、餐次和责任记录。",
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
        "attendance": attendance,
        "steps": steps,
        "next_step": next_step,
        "metrics": [
            {
                "label": "本周菜品",
                "value": dish_count,
                "suffix": "道",
                "hint": recipe.get("title") if recipe else "本周尚未编制食谱",
            },
            {
                "label": "本月就餐人日",
                "value": int((attendance or {}).get("total_person_days") or 0),
                "suffix": "人日",
                "hint": (attendance or {}).get("month_label") or "本月尚未填报",
            },
            {
                "label": "待处理采购",
                "value": purchase_open,
                "suffix": "项",
                "hint": f"共有 {purchase_total} 条采购记录",
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
    """Make the workflow page and authored sidebar the canonical Tongjianyun entry."""

    if not frappe.db.exists("Workspace", WORKSPACE_NAME):
        return
    workspace = frappe.get_doc("Workspace", WORKSPACE_NAME)
    workspace.set("sidebar_items", [])
    for item in _sidebar_items():
        workspace.append("sidebar_items", item)
    workspace.set("shortcuts", [])
    for item in _shortcuts():
        workspace.append("shortcuts", item)
    workspace.content = json.dumps(_workspace_content(), ensure_ascii=False, separators=(",", ":"))
    workspace.save(ignore_permissions=True)
    frappe.clear_cache()


def _sidebar_items() -> list[dict[str, Any]]:
    return [
        _sidebar_link("业务工作台", "Page", "tongjianyun-workbench", "layout-dashboard", default=1),
        _section("计划与备餐", "calendar-range"),
        _sidebar_link("就餐人数", "DocType", ATTENDANCE_DOCTYPE, child=1),
        _sidebar_link("食谱计划", "Page", "tongjianyun-recipe-workbench", child=1),
        _section("采购与供餐", "shopping-basket"),
        _sidebar_link("食安采购", "DocType", PURCHASE_DOCTYPE, child=1),
        _sidebar_link("供应商", "DocType", SUPPLIER_DOCTYPE, child=1),
        _sidebar_link("留样记录", "DocType", SAMPLE_DOCTYPE, child=1),
        _section("风险与复盘", "shield-alert"),
        _sidebar_link("追溯事件", "DocType", TRACE_DOCTYPE, child=1),
    ]


def _sidebar_link(
    label: str,
    link_type: str,
    link_to: str,
    icon: str = "",
    *,
    child: int = 0,
    default: int = 0,
) -> dict[str, Any]:
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


def _section(label: str, icon: str) -> dict[str, Any]:
    return {
        "type": "Section Break",
        "label": label,
        "link_type": "DocType",
        "icon": icon,
        "child": 0,
        "open_in_new_tab": 0,
        "collapsible": 1,
        "indent": 1,
        "keep_closed": 0,
        "show_arrow": 1,
    }


def _shortcuts() -> list[dict[str, Any]]:
    return [
        {"type": "Page", "link_to": "tongjianyun-workbench", "label": "业务工作台", "color": "Green", "stats_filter": "[]"},
        {"type": "DocType", "link_to": ATTENDANCE_DOCTYPE, "doc_view": "List", "label": "就餐人数", "color": "Blue", "stats_filter": "[]"},
        {"type": "Page", "link_to": "tongjianyun-recipe-workbench", "label": "食谱计划", "color": "Green", "stats_filter": "[]"},
        {"type": "DocType", "link_to": PURCHASE_DOCTYPE, "doc_view": "List", "label": "食安采购", "color": "Orange", "stats_filter": "[]"},
    ]


def _workspace_content() -> list[dict[str, Any]]:
    return [
        {"id": "tjyWorkbench", "type": "shortcut", "data": {"shortcut_name": "业务工作台", "col": 3}},
        {"id": "tjyAttendance", "type": "shortcut", "data": {"shortcut_name": "就餐人数", "col": 3}},
        {"id": "tjyRecipe", "type": "shortcut", "data": {"shortcut_name": "食谱计划", "col": 3}},
        {"id": "tjyPurchase", "type": "shortcut", "data": {"shortcut_name": "食安采购", "col": 3}},
        {"id": "tjySpacer", "type": "spacer", "data": {"col": 12}},
        {"id": "tjyPlanCard", "type": "card", "data": {"card_name": "计划与备餐", "col": 4}},
        {"id": "tjySupplyCard", "type": "card", "data": {"card_name": "采购与供餐", "col": 4}},
        {"id": "tjyRiskCard", "type": "card", "data": {"card_name": "风险与复盘", "col": 4}},
    ]
