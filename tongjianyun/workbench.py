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
PURCHASE_DOCTYPE = "Tongjianyun Food Purchase"
NUTRITION_RULE_DOCTYPE = "Tongjianyun Nutrition Rule Set"

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
    purchase_total = _count(PURCHASE_DOCTYPE)
    purchase_open = _open_count(PURCHASE_DOCTYPE)

    group_ready = group_count > 0
    student_ready = student_count > 0
    setup_ready = group_ready and student_ready
    setup_status = _status(setup_ready, attention=not setup_ready)
    attendance_done = bool(confirmation and confirmation.get("status") in {"已确认", "已锁定"})
    attendance_status = _status(
        attendance_done,
        attention=bool(setup_ready and confirmation and not attendance_done),
    )
    recipe_status = _status(bool(recipe and dish_count))
    purchase_status = _status(bool(purchase_total), attention=bool(purchase_open))

    if not group_ready:
        setup_action_label = "补全班级信息"
        setup_route = "Student Group"
        setup_secondary_action = {
            "label": "补全学生信息",
            "route_type": "DocType",
            "route": "Student",
        }
    elif not student_ready:
        setup_action_label = "补全学生信息"
        setup_route = "Student"
        setup_secondary_action = {
            "label": "查看班级信息",
            "route_type": "DocType",
            "route": "Student Group",
        }
    else:
        setup_action_label = "查看班级信息"
        setup_route = "Student Group"
        setup_secondary_action = {
            "label": "查看学生信息",
            "route_type": "DocType",
            "route": "Student",
        }

    steps = [
        {
            "id": "setup",
            "number": "01",
            "kicker": "启用童健云的第一步",
            "title": "补全班级和学生信息",
            "description": "先在教育管理中建立班级并录入学生档案，童健云才能自动计算就餐人数并生成后续膳食任务。",
            "status": setup_status[0],
            "status_label": setup_status[1],
            "action_label": setup_action_label,
            "route_type": "DocType",
            "route": setup_route,
            "secondary_action": setup_secondary_action,
        },
        {
            "id": "attendance",
            "number": "02",
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
            "number": "03",
            "title": "编制本周食谱",
            "description": "根据就餐人数和年龄段安排每日菜品、餐次与食材用量。",
            "status": recipe_status[0],
            "status_label": recipe_status[1],
            "action_label": "打开食谱",
            "route_type": "Page",
            "route": "tongjianyun-recipe-workbench",
        },
        {
            "id": "purchase",
            "number": "04",
            "title": "执行食材采购",
            "description": "依据食谱和确认人数形成采购任务，跟踪食材、数量与完成状态。",
            "status": purchase_status[0],
            "status_label": purchase_status[1],
            "action_label": "处理采购",
            "route_type": "DocType",
            "route": PURCHASE_DOCTYPE,
        },
    ]
    next_step = next((step for step in steps if step["status"] in {"attention", "pending"}), steps[-1])
    if recipe:
        recipe["dish_count"] = dish_count

    alerts = []
    if not group_ready:
        alerts.append(
            {
                "tone": "warning",
                "title": "班级信息尚未建立",
                "description": "请先建立园所班级，这是录入学生和计算就餐人数的基础。",
                "route_type": "DocType",
                "route": "Student Group",
            }
        )
    if not student_ready:
        alerts.append(
            {
                "tone": "warning",
                "title": "学生信息尚未建立",
                "description": "请录入在园学生档案，系统将据此汇总各班就餐人数。",
                "route_type": "DocType",
                "route": "Student",
            }
        )
    if setup_ready:
        if not attendance_done:
            alerts.append(
                {
                    "tone": "warning",
                    "title": "今日就餐人数尚未确认",
                    "description": "确认班级考勤与请假数据后再安排备餐。",
                    "route_type": "DocType",
                    "route": CONFIRMATION_DOCTYPE,
                }
            )
        if not recipe or not dish_count:
            alerts.append(
                {
                    "tone": "warning",
                    "title": "本周食谱仍需完善",
                    "description": "补齐每日餐次、菜品与食材明细，确保后续采购可执行。",
                    "route_type": "Page",
                    "route": "tongjianyun-recipe-workbench",
                }
            )
    if not alerts:
        alerts.append(
            {
                "tone": "success",
                "title": "今日业务运行正常",
                "description": "关键任务均已完成，当前没有待处理事项。",
                "route_type": "Page",
                "route": "tongjianyun-workbench",
            }
        )

    return {
        "generated_at": str(now_datetime()),
        "date_label": getdate(today()).strftime("%Y年%m月%d日"),
        "recipe": recipe,
        "confirmation": confirmation,
        "setup_required": not setup_ready,
        "setup": {
            "ready": setup_ready,
            "group_ready": group_ready,
            "student_ready": student_ready,
            "group_count": group_count,
            "student_count": student_count,
        },
        "steps": steps,
        "next_step": next_step,
        "alerts": alerts,
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
                "label": "本周菜品",
                "value": dish_count,
                "suffix": "道",
                "hint": (recipe or {}).get("title") or "等待编制本周食谱",
            },
            {
                "label": "待完成采购",
                "value": purchase_open,
                "suffix": "项",
                "hint": "采购任务均已完成" if not purchase_open else "请继续处理采购任务",
            },
        ],
        "supporting": {
            "purchase_count": purchase_total,
            "purchase_open": purchase_open,
            "dish_count": dish_count,
            "group_count": group_count,
            "done_count": sum(1 for step in steps if step["status"] == "done"),
            "attention_count": sum(1 for step in steps if step["status"] == "attention"),
        },
    }


def install() -> None:
    if not frappe.db.exists("Workspace", WORKSPACE_NAME):
        return
    previous_patch_flag = frappe.flags.in_patch
    frappe.flags.in_patch = True
    try:
        workspace = frappe.get_doc("Workspace", WORKSPACE_NAME)

        # Update sidebar_items
        workspace.set("sidebar_items", [])
        for item in _sidebar_items():
            workspace.append("sidebar_items", item)

        # Update shortcuts
        workspace.set("shortcuts", [])
        for item in _shortcuts():
            workspace.append("shortcuts", item)

        # Update shortcuts section in content
        workspace.set("links", [])
        for item in _workspace_links():
            workspace.append("links", item)

        workspace.save(ignore_permissions=True)
        frappe.db.commit()
    finally:
        frappe.flags.in_patch = previous_patch_flag
    frappe.clear_cache()


def _sidebar_items() -> list[dict[str, Any]]:
    return [
        _sidebar_link("首页", "Workspace", WORKSPACE_NAME, "home", default=1),
        _sidebar_link("业务工作台", "Page", "tongjianyun-workbench", "layout-dashboard"),
        _section("出勤管理", "calendar-check"),
        _sidebar_link("今日出勤（教师端）", "Page", "meal-attendance-teacher", child=1),
        _sidebar_link("今日备餐（厨房端）", "Page", "meal-kitchen-dashboard", child=1),
        _sidebar_link("今日就餐确认", "DocType", CONFIRMATION_DOCTYPE, child=1),
        _sidebar_link("就餐调整记录", "DocType", "Tongjianyun Daily Meal Adjustment", child=1),
        _sidebar_link("月度结算", "Page", "meal-finance-settlement", child=1),
        _sidebar_link("月度就餐统计", "DocType", "Tongjianyun Meal Attendance", child=1),
        _sidebar_link("园长看板", "Page", "director-dashboard", child=1),
        _section("膳食营养", "salad"),
        _sidebar_link("食谱计划", "Page", "tongjianyun-recipe-workbench", child=1),
        _sidebar_link("周食谱营养分析", "Page", "weekly-recipe-nutrition-sheet", child=1),
        _sidebar_link("食材营养统计", "Report", "Ingredient Nutrition Statistics", child=1),
        _sidebar_link("营养计算规则", "DocType", NUTRITION_RULE_DOCTYPE, child=1),
        _section("食安执行", "shield-check"),
        _sidebar_link("一周采购订单", "Page", "weekly-orders", child=1),
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
        "keep_closed": 0,
        "show_arrow": 1,
    }


def _shortcuts() -> list[dict[str, Any]]:
    return [
        {"type": "Page", "link_to": "tongjianyun-workbench", "label": "业务工作台", "color": "Green", "stats_filter": "[]"},
        {"type": "Page", "link_to": "meal-attendance-teacher", "doc_view": "", "label": "今日出勤", "color": "Blue", "stats_filter": "[]"},
        {"type": "Page", "link_to": "meal-kitchen-dashboard", "doc_view": "", "label": "今日备餐", "color": "Orange", "stats_filter": "[]"},
        {"type": "DocType", "link_to": CONFIRMATION_DOCTYPE, "doc_view": "List", "label": "今日就餐确认", "color": "Blue", "stats_filter": "[]"},
        {"type": "Page", "link_to": "tongjianyun-recipe-workbench", "label": "食谱计划", "color": "Green", "stats_filter": "[]"},
        {"type": "Page", "link_to": "meal-finance-settlement", "doc_view": "", "label": "月度结算", "color": "Purple", "stats_filter": "[]"},
    ]


def _workspace_content() -> list[dict[str, Any]]:
    return [
        {"id": "tjyWorkbench", "type": "shortcut", "data": {"shortcut_name": "业务工作台", "col": 3}},
        {"id": "tjyTeacherAttendance", "type": "shortcut", "data": {"shortcut_name": "今日出勤", "col": 3}},
        {"id": "tjyKitchenDashboard", "type": "shortcut", "data": {"shortcut_name": "今日备餐", "col": 3}},
        {"id": "tjyAttendance", "type": "shortcut", "data": {"shortcut_name": "今日就餐确认", "col": 3}},
        {"id": "tjyRecipe", "type": "shortcut", "data": {"shortcut_name": "食谱计划", "col": 3}},
        {"id": "tjyFinanceSettlement", "type": "shortcut", "data": {"shortcut_name": "月度结算", "col": 3}},
        {"id": "tjySpacer", "type": "spacer", "data": {"col": 12}},
        {"id": "tjyAttendanceCard", "type": "card", "data": {"card_name": "就餐管理", "col": 4}},
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
            "膳食营养",
            [
                ("食谱计划", "Page", "tongjianyun-recipe-workbench"),
                ("周食谱营养分析", "Page", "weekly-recipe-nutrition-sheet"),
                ("食材营养统计", "Report", "Ingredient Nutrition Statistics"),
                ("营养计算规则", "DocType", NUTRITION_RULE_DOCTYPE),
            ],
        ),
        (
            "食安执行",
            [
                ("一周采购订单", "Page", "weekly-orders"),
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
