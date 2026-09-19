from __future__ import annotations

from datetime import timedelta
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, get_last_day, getdate, now_datetime, today


CONFIRMATION_DOCTYPE = "Tongjianyun Daily Meal Confirmation"
RECIPE_DOCTYPE = "Tongjianyun Recipe"
DISH_DOCTYPE = "Tongjianyun Recipe Dish"
INGREDIENT_DOCTYPE = "Tongjianyun Recipe Ingredient"

NUTRIENT_LABELS = {
    "energy": "能量",
    "protein": "蛋白质",
    "calcium": "钙",
    "iron": "铁",
    "zinc": "锌",
    "vitamin_a": "维生素A",
    "vitamin_c": "维生素C",
}


def _require_login() -> None:
    if frappe.session.user == "Guest":
        frappe.throw(_("请先登录"), frappe.AuthenticationError)


def _doctype_available(doctype: str) -> bool:
    try:
        return bool(frappe.db.exists("DocType", doctype) and frappe.db.table_exists(doctype))
    except Exception:
        return False


def _can_read(doctype: str) -> bool:
    if not _doctype_available(doctype):
        return False
    try:
        return bool(frappe.has_permission(doctype, "read"))
    except Exception:
        return False


def _safe_get_list(
    doctype: str,
    *,
    filters: Any = None,
    fields: list[str] | None = None,
    order_by: str | None = None,
    page_length: int = 0,
) -> list[dict[str, Any]]:
    if not _can_read(doctype):
        return []
    try:
        rows = frappe.get_list(
            doctype,
            filters=filters or {},
            fields=fields or ["name"],
            order_by=order_by,
            page_length=page_length,
        )
        return [dict(row) for row in rows]
    except Exception:
        return []


def _count_visible(doctype: str, filters: Any = None) -> int:
    return len(_safe_get_list(doctype, filters=filters, fields=["name"], page_length=0))


def _attendance_rate(enrolled: Any, absent: Any, leave: Any) -> float:
    total = max(int(enrolled or 0), 0)
    if not total:
        return 0.0
    unavailable = max(int(absent or 0), 0) + max(int(leave or 0), 0)
    present = max(total - unavailable, 0)
    return round(present / total * 100, 1)


def _class_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    enrolled = int(row.get("enrolled_count") or 0)
    absent = int(row.get("absent_count") or 0)
    leave = int(row.get("leave_count") or 0)
    present = max(enrolled - absent - leave, 0)
    rate = _attendance_rate(enrolled, absent, leave)
    status = "normal"
    if enrolled and rate < 85:
        status = "danger"
    elif enrolled and rate < 90:
        status = "warning"
    return {
        "student_group": row.get("student_group") or "",
        "class_name": row.get("class_name") or row.get("student_group") or "未命名班级",
        "enrolled": enrolled,
        "present": present,
        "lunch": int(row.get("lunch_count") or 0),
        "absent": absent,
        "leave": leave,
        "rate": rate,
        "status": status,
    }


def _operator_name() -> str:
    try:
        first_name = frappe.db.get_value("User", frappe.session.user, "first_name")
        if first_name:
            return str(first_name)
    except Exception:
        pass
    user = str(frappe.session.user or "")
    return user.split("@", 1)[0] if user else "园长"


def _attendance_summary(target_date) -> dict[str, Any]:
    student_total = _count_visible("Student", {"enabled": 1})
    group_total = _count_visible("Student Group", {"disabled": 0})
    confirmation_rows = _safe_get_list(
        CONFIRMATION_DOCTYPE,
        filters={"meal_date": target_date},
        fields=[
            "name",
            "meal_date",
            "status",
            "total_enrolled_count",
            "total_absent_count",
            "total_leave_count",
            "total_lunch_count",
            "modified",
        ],
        page_length=1,
    )
    confirmation = confirmation_rows[0] if confirmation_rows else None
    classes: list[dict[str, Any]] = []

    if confirmation:
        enrolled = int(confirmation.get("total_enrolled_count") or student_total)
        absent = int(confirmation.get("total_absent_count") or 0)
        leave = int(confirmation.get("total_leave_count") or 0)
        lunch = int(confirmation.get("total_lunch_count") or 0)
        try:
            doc = frappe.get_doc(CONFIRMATION_DOCTYPE, confirmation["name"])
            doc.check_permission("read")
            classes = [_class_snapshot(dict(row.as_dict())) for row in (doc.details or [])]
        except Exception:
            classes = []
        record_count = enrolled
        # The confirmation document is generated from Education attendance/leave
        # aggregation. Its own workflow status describes meal confirmation, not
        # whether attendance data is available for the director dashboard.
        complete = bool(classes or enrolled)
    else:
        attendance_rows = _safe_get_list(
            "Student Attendance",
            filters={"date": target_date, "docstatus": ["!=", 2]},
            fields=["student", "status", "student_group", "modified"],
            order_by="modified desc",
            page_length=0,
        )
        by_student: dict[str, dict[str, Any]] = {}
        for row in attendance_rows:
            student = str(row.get("student") or "")
            if student and student not in by_student:
                by_student[student] = row

        absent_students = {
            student for student, row in by_student.items() if row.get("status") == "Absent"
        }
        leave_students = {
            student for student, row in by_student.items() if row.get("status") == "Leave"
        }
        leave_rows = _safe_get_list(
            "Student Leave Application",
            filters={
                "from_date": ["<=", target_date],
                "to_date": [">=", target_date],
                "docstatus": ["!=", 2],
                "mark_as_present": 0,
            },
            fields=["student"],
            page_length=0,
        )
        leave_students.update(
            str(row.get("student") or "") for row in leave_rows if row.get("student")
        )
        leave_students -= absent_students

        enrolled = student_total
        absent = len(absent_students)
        leave = len(leave_students)
        lunch = max(enrolled - absent - leave, 0)
        record_count = len(by_student)
        complete = bool(enrolled and record_count >= enrolled)

    rate = _attendance_rate(enrolled, absent, leave)
    present = max(enrolled - absent - leave, 0)
    return {
        "available": bool(_can_read("Student") or confirmation),
        "student_total": student_total,
        "group_total": group_total,
        "enrolled": enrolled,
        "present": present,
        "absent": absent,
        "leave": leave,
        "rate": rate,
        "lunch": lunch,
        "record_count": record_count,
        "attendance_complete": complete,
        "confirmation": confirmation,
        "confirmation_status": (confirmation or {}).get("status") or "未生成",
        "meal_confirmed": bool(
            confirmation and confirmation.get("status") in {"已确认", "已锁定"}
        ),
        "classes": classes,
    }


def _recipe_summary(target_date) -> dict[str, Any]:
    rows = _safe_get_list(
        RECIPE_DOCTYPE,
        filters={
            "is_deleted": 0,
            "week_start": ["<=", target_date],
            "week_end": [">=", target_date],
        },
        fields=[
            "name",
            "recipe_id",
            "title",
            "workflow_status",
            "week_start",
            "week_end",
            "modified",
        ],
        order_by="modified desc",
        page_length=1,
    )
    recipe = rows[0] if rows else None
    if not recipe:
        return {
            "available": _can_read(RECIPE_DOCTYPE),
            "recipe": None,
            "dish_count": 0,
            "ingredient_count": 0,
            "published": False,
        }

    dish_count = 0
    ingredient_count = 0
    try:
        if _doctype_available(DISH_DOCTYPE):
            dish_count = int(frappe.db.count(DISH_DOCTYPE, {"recipe": recipe["name"]}) or 0)
        if _doctype_available(INGREDIENT_DOCTYPE):
            ingredient_count = int(
                frappe.db.count(INGREDIENT_DOCTYPE, {"recipe": recipe["name"]}) or 0
            )
    except Exception:
        pass

    return {
        "available": True,
        "recipe": recipe,
        "dish_count": dish_count,
        "ingredient_count": ingredient_count,
        "published": recipe.get("workflow_status") == "已发布",
    }


def _nutrition_payload(sheet: dict[str, Any] | None) -> dict[str, Any]:
    if not sheet:
        return {
            "available": False,
            "suitable": 0,
            "total": 0,
            "attention": [],
            "items": [],
            "conclusion": "暂无可用营养分析",
            "profile": "",
        }
    analysis = dict(sheet.get("analysis") or {})
    evaluations = dict(analysis.get("nutrient_evaluations") or {})
    items = []
    suitable = 0
    for key, label in NUTRIENT_LABELS.items():
        row = dict(evaluations.get(key) or {})
        if not row:
            continue
        status = str(row.get("status") or "")
        if status == "适宜":
            suitable += 1
        items.append(
            {
                "key": key,
                "label": label,
                "status": status or "待分析",
                "percent": round(flt(row.get("percent")), 1),
            }
        )
    attention = [item for item in items if item["status"] != "适宜"]
    standard = dict(analysis.get("standard") or {})
    return {
        "available": bool(items),
        "suitable": suitable,
        "total": len(items),
        "attention": attention[:4],
        "items": items,
        "conclusion": str(analysis.get("conclusion") or "暂无营养结论"),
        "profile": str(standard.get("profile") or ""),
    }


def _nutrition_summary(recipe: dict[str, Any]) -> dict[str, Any]:
    recipe_row = recipe.get("recipe")
    if not recipe_row:
        return _nutrition_payload(None)
    try:
        from tongjianyun.nutrition_sheet import get_nutrition_sheet

        return _nutrition_payload(get_nutrition_sheet(recipe_row["name"]))
    except Exception:
        return _nutrition_payload(None)


def _tongjianyun_material_request_names() -> list[str]:
    """Return only ERPNext demands created by the formal Tongjianyun recipe flow."""
    rows = _safe_get_list(
        "Material Request",
        filters={
            "title": ["like", "童健云食谱采购 · %"],
            "material_request_type": "Purchase",
            "docstatus": ["<", 2],
        },
        fields=["name"],
        page_length=0,
    )
    return [str(row["name"]) for row in rows if row.get("name")]


def _linked_parent_names(
    child_doctype: str,
    link_field: str,
    values: list[str],
) -> list[str]:
    """Resolve ERPNext child links, then permission-filter the parent later."""
    if not values or not _doctype_available(child_doctype):
        return []
    try:
        rows = frappe.get_all(
            child_doctype,
            filters={link_field: ["in", values]},
            fields=["parent"],
            page_length=0,
        )
    except Exception:
        return []
    return sorted({str(row.parent) for row in rows if row.get("parent")})


def _tongjianyun_purchase_order_names() -> list[str]:
    if not _can_read("Purchase Order"):
        return []
    return _linked_parent_names(
        "Purchase Order Item",
        "material_request",
        _tongjianyun_material_request_names(),
    )


def _procurement_summary(target_date) -> dict[str, Any]:
    week_start = target_date - timedelta(days=target_date.weekday())
    week_end = week_start + timedelta(days=6)
    linked_orders = _tongjianyun_purchase_order_names()
    orders = (
        _safe_get_list(
            "Purchase Order",
            filters={
                "name": ["in", linked_orders],
                "transaction_date": ["between", [week_start, week_end]],
                "docstatus": ["<", 2],
            },
            fields=[
                "name",
                "transaction_date",
                "schedule_date",
                "supplier",
                "docstatus",
                "status",
                "grand_total",
                "per_received",
            ],
            order_by="transaction_date asc, creation asc",
            page_length=100,
        )
        if linked_orders
        else []
    )
    draft_count = sum(1 for row in orders if int(row.get("docstatus") or 0) == 0)
    unreceived_count = sum(
        1
        for row in orders
        if int(row.get("docstatus") or 0) == 1 and flt(row.get("per_received")) < 99.99
    )

    order_names = [str(row["name"]) for row in orders if row.get("name")]
    receipt_names = _linked_parent_names(
        "Purchase Receipt Item",
        "purchase_order",
        order_names,
    )
    receipts = (
        _safe_get_list(
            "Purchase Receipt",
            filters={
                "name": ["in", receipt_names],
                "posting_date": target_date,
                "docstatus": 1,
            },
            fields=["name"],
            page_length=0,
        )
        if receipt_names
        else []
    )
    return {
        "available": _can_read("Purchase Order"),
        "week_start": str(week_start),
        "week_end": str(week_end),
        "order_count": len(orders),
        "draft_count": draft_count,
        "unreceived_count": unreceived_count,
        "receipt_count_today": len(receipts),
        "amount": round(sum(flt(row.get("grand_total")) for row in orders), 2),
    }


def _finance_summary(target_date, student_total: int) -> dict[str, Any]:
    month_start = getdate(get_first_day(target_date))
    month_end = getdate(get_last_day(target_date))
    linked_orders = _tongjianyun_purchase_order_names()
    invoice_names = _linked_parent_names(
        "Purchase Invoice Item",
        "purchase_order",
        linked_orders,
    )
    documents = (
        _safe_get_list(
            "Purchase Invoice",
            filters={
                "name": ["in", invoice_names],
                "posting_date": ["between", [month_start, month_end]],
                "docstatus": 1,
            },
            fields=["name", "grand_total", "posting_date"],
            page_length=0,
        )
        if invoice_names
        else []
    )
    source = "童健云采购发票"
    if not documents:
        documents = (
            _safe_get_list(
                "Purchase Order",
                filters={
                    "name": ["in", linked_orders],
                    "transaction_date": ["between", [month_start, month_end]],
                    "docstatus": 1,
                },
                fields=["name", "grand_total", "transaction_date"],
                page_length=0,
            )
            if linked_orders
            else []
        )
        source = "童健云采购订单"

    spend = round(sum(flt(row.get("grand_total")) for row in documents), 2)
    per_capita = round(spend / student_total, 2) if spend and student_total else 0.0
    return {
        "available": bool(_can_read("Purchase Invoice") or _can_read("Purchase Order")),
        "month": target_date.strftime("%Y-%m"),
        "month_label": target_date.strftime("%Y年%m月"),
        "spend": spend,
        "per_capita": per_capita,
        "budget_percent": None,
        "budget_label": "未配置预算",
        "source": source,
        "document_count": len(documents),
    }


def _trend_summary(target_date) -> list[dict[str, Any]]:
    start = target_date - timedelta(days=6)
    rows = _safe_get_list(
        CONFIRMATION_DOCTYPE,
        filters={"meal_date": ["between", [start, target_date]]},
        fields=[
            "meal_date",
            "total_enrolled_count",
            "total_absent_count",
            "total_leave_count",
            "total_lunch_count",
        ],
        order_by="meal_date asc",
        page_length=20,
    )
    by_date = {str(row.get("meal_date")): row for row in rows}
    result = []
    current = start
    while current <= target_date:
        row = by_date.get(str(current))
        result.append(
            {
                "date": str(current),
                "label": current.strftime("%m/%d"),
                "rate": (
                    _attendance_rate(
                        row.get("total_enrolled_count"),
                        row.get("total_absent_count"),
                        row.get("total_leave_count"),
                    )
                    if row
                    else None
                ),
                "lunch": int(row.get("total_lunch_count") or 0) if row else None,
            }
        )
        current += timedelta(days=1)
    return result


def _scene_nav() -> list[dict[str, Any]]:
    return [
        {"id": "overview", "label": "今日概览", "icon": "▦", "route": None},
        {
            "id": "attendance",
            "label": "考勤管理",
            "icon": "◷",
            "route": ["List", "Student Attendance"],
        },
        {
            "id": "teacher_attendance",
            "label": "教师考勤",
            "icon": "◎",
            "route": ["List", "Employee Checkin"],
        },
        {
            "id": "nutrition",
            "label": "膳食营养",
            "icon": "♨",
            "route": ["weekly-recipe-nutrition-sheet"],
        },
        {"id": "procurement", "label": "采购管理", "icon": "🛒", "route": ["weekly-orders"]},
        {
            "id": "finance",
            "label": "财务结算",
            "icon": "¥",
            "route": ["List", "Purchase Invoice"],
        },
        {
            "id": "safety",
            "label": "安全管理",
            "icon": "◇",
            "route": ["List", "Purchase Receipt"],
        },
    ]


def _focus_items(
    attendance: dict[str, Any],
    recipe: dict[str, Any],
    procurement: dict[str, Any],
) -> list[dict[str, Any]]:
    confirmation_exists = bool(attendance.get("confirmation"))
    meal_confirmed = bool(attendance.get("meal_confirmed"))
    recipe_exists = bool(recipe.get("recipe"))
    orders_exist = int(procurement.get("order_count") or 0) > 0
    unreceived = int(procurement.get("unreceived_count") or 0)

    return [
        {
            "id": "attendance",
            "label": "考勤情况检查",
            "status": (
                "done"
                if attendance.get("attendance_complete")
                else ("attention" if attendance.get("record_count") else "pending")
            ),
            "status_label": (
                "已完成"
                if attendance.get("attendance_complete")
                else ("需核查" if attendance.get("record_count") else "待开始")
            ),
            "route": ["List", "Student Attendance"],
        },
        {
            "id": "meal",
            "label": "就餐人数确认",
            "status": "done" if meal_confirmed else ("attention" if confirmation_exists else "pending"),
            "status_label": "已完成" if meal_confirmed else ("需确认" if confirmation_exists else "待生成"),
            "route": ["List", CONFIRMATION_DOCTYPE],
        },
        {
            "id": "recipe",
            "label": "今日食谱发布",
            "status": "done" if recipe.get("published") else ("attention" if recipe_exists else "pending"),
            "status_label": "已完成" if recipe.get("published") else ("待发布" if recipe_exists else "待编制"),
            "route": ["tongjianyun-recipe-workbench"],
        },
        {
            "id": "purchase",
            "label": "食材采购进度",
            "status": (
                "done"
                if orders_exist and not procurement.get("draft_count")
                else ("attention" if orders_exist else "pending")
            ),
            "status_label": (
                "已下单"
                if orders_exist and not procurement.get("draft_count")
                else ("进行中" if orders_exist else "待采购")
            ),
            "route": ["weekly-orders"],
        },
        {
            "id": "receipt",
            "label": "食材收货验收",
            "status": "done" if orders_exist and not unreceived else ("attention" if unreceived else "pending"),
            "status_label": "已完成" if orders_exist and not unreceived else ("待处理" if unreceived else "待开始"),
            "route": ["List", "Purchase Receipt"],
        },
        {
            "id": "kitchen",
            "label": "厨房备餐准备",
            "status": "done" if meal_confirmed else "pending",
            "status_label": "可执行" if meal_confirmed else "等待人数确认",
            "route": ["List", CONFIRMATION_DOCTYPE],
        },
    ]


def _dashboard_tasks(
    attendance: dict[str, Any],
    recipe: dict[str, Any],
    procurement: dict[str, Any],
    nutrition: dict[str, Any],
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []

    if not attendance.get("meal_confirmed"):
        tasks.append(
            {
                "priority": "urgent" if attendance.get("confirmation") else "important",
                "title": "今日就餐人数尚未确认",
                "description": "请完成考勤核查并确认今日实际就餐人数。",
                "action": "去确认",
                "route": ["List", CONFIRMATION_DOCTYPE],
            }
        )

    if attendance.get("enrolled") and attendance.get("rate", 0) < 90:
        tasks.append(
            {
                "priority": "urgent" if attendance.get("rate", 0) < 85 else "important",
                "title": "今日全园出勤率偏低",
                "description": f"当前出勤率 {attendance.get('rate', 0):.1f}%，请关注班级缺勤情况。",
                "action": "查看考勤",
                "route": ["List", "Student Attendance"],
            }
        )

    for row in attendance.get("classes") or []:
        if row.get("status") == "danger":
            tasks.append(
                {
                    "priority": "urgent",
                    "title": f"{row.get('class_name')}出勤异常",
                    "description": (
                        f"班级出勤率 {row.get('rate', 0):.1f}%，"
                        f"缺勤/请假 {row.get('absent', 0) + row.get('leave', 0)} 人。"
                    ),
                    "action": "查看班级",
                    "route": ["List", "Student Attendance"],
                }
            )
            if len(tasks) >= 5:
                break

    if not recipe.get("published"):
        tasks.append(
            {
                "priority": "important",
                "title": "本周食谱尚未发布" if recipe.get("recipe") else "本周食谱尚未编制",
                "description": "完成食谱后，营养分析和采购计划才能形成闭环。",
                "action": "处理食谱",
                "route": ["tongjianyun-recipe-workbench"],
            }
        )

    if procurement.get("draft_count"):
        tasks.append(
            {
                "priority": "important",
                "title": "采购订单尚未全部提交",
                "description": f"本周还有 {procurement.get('draft_count')} 张采购订单处于草稿状态。",
                "action": "处理采购",
                "route": ["weekly-orders"],
            }
        )
    elif procurement.get("unreceived_count"):
        tasks.append(
            {
                "priority": "important",
                "title": "食材收货尚未完成",
                "description": f"还有 {procurement.get('unreceived_count')} 张采购订单未完成收货。",
                "action": "查看收货",
                "route": ["List", "Purchase Receipt"],
            }
        )

    if nutrition.get("available") and nutrition.get("attention"):
        labels = "、".join(item.get("label") for item in nutrition["attention"][:3])
        tasks.append(
            {
                "priority": "important",
                "title": "本周营养指标需要关注",
                "description": f"{labels}等指标偏离参考范围，请查看周食谱营养分析。",
                "action": "查看营养",
                "route": ["weekly-recipe-nutrition-sheet"],
            }
        )

    if not tasks:
        tasks.append(
            {
                "priority": "normal",
                "title": "今日关键业务运行正常",
                "description": "当前未发现需要园长立即处理的关键事项。",
                "action": "查看概览",
                "route": None,
            }
        )
    return tasks[:6]


def _business_cards(
    attendance: dict[str, Any],
    recipe: dict[str, Any],
    procurement: dict[str, Any],
    finance: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            "id": "classes",
            "icon": "👥",
            "title": "班级管理",
            "description": (
                f"{attendance.get('group_total', 0)} 个班级 · "
                f"{attendance.get('student_total', 0)} 名在园幼儿"
            ),
            "route": ["List", "Student Group"],
            "tone": "green",
        },
        {
            "id": "teacher_attendance",
            "icon": "🧑‍🏫",
            "title": "教师考勤",
            "description": "查看教职工上下班打卡记录",
            "route": ["List", "Employee Checkin"],
            "tone": "cyan",
        },
        {
            "id": "nutrition",
            "icon": "🥣",
            "title": "膳食营养",
            "description": f"本周 {recipe.get('dish_count', 0)} 道菜 · 查看营养分析",
            "route": ["weekly-recipe-nutrition-sheet"],
            "tone": "orange",
        },
        {
            "id": "purchase",
            "icon": "🛒",
            "title": "采购管理",
            "description": (
                f"本周 {procurement.get('order_count', 0)} 张订单 · "
                f"¥{procurement.get('amount', 0):,.0f}"
            ),
            "route": ["weekly-orders"],
            "tone": "blue",
        },
        {
            "id": "finance",
            "icon": "◉",
            "title": "财务结算",
            "description": (
                f"{finance.get('month_label', '')}采购支出 · "
                f"¥{finance.get('spend', 0):,.0f}"
            ),
            "route": ["List", "Purchase Invoice"],
            "tone": "purple",
        },
    ]


@frappe.whitelist()
def get_dashboard(date: str | None = None) -> dict[str, Any]:
    _require_login()
    target_date = getdate(date or today())

    attendance = _attendance_summary(target_date)
    recipe = _recipe_summary(target_date)
    procurement = _procurement_summary(target_date)
    finance = _finance_summary(target_date, int(attendance.get("student_total") or 0))
    nutrition = _nutrition_summary(recipe)
    trend = _trend_summary(target_date)

    focus = _focus_items(attendance, recipe, procurement)
    tasks = _dashboard_tasks(attendance, recipe, procurement, nutrition)
    warning_count = sum(
        1 for task in tasks if task.get("priority") in {"urgent", "important"}
    )

    return {
        "generated_at": str(now_datetime()),
        "date": str(target_date),
        "date_label": target_date.strftime("%Y年%m月%d日"),
        "operator_name": _operator_name(),
        "headline": (
            "今日运行正常" if warning_count == 0 else f"有 {warning_count} 项需要关注"
        ),
        "warning_count": warning_count,
        "scenes": _scene_nav(),
        "metrics": {
            "students": {
                "label": "在园幼儿",
                "value": int(attendance.get("present") or 0),
                "total": int(attendance.get("enrolled") or 0),
                "suffix": "人",
                "hint": (
                    f"{attendance.get('absent', 0)} 人缺勤 · "
                    f"{attendance.get('leave', 0)} 人请假"
                ),
                "tone": "green",
            },
            "attendance": {
                "label": "出勤率",
                "value": flt(attendance.get("rate")),
                "suffix": "%",
                "hint": (
                    "考勤已核查"
                    if attendance.get("attendance_complete")
                    else "考勤数据待核查"
                ),
                "tone": "blue",
            },
            "meals": {
                "label": "今日就餐",
                "value": int(attendance.get("lunch") or 0),
                "suffix": "人",
                "hint": attendance.get("confirmation_status") or "未生成",
                "tone": "orange",
            },
            "warnings": {
                "label": "今日预警",
                "value": warning_count,
                "suffix": "项",
                "hint": (
                    "当前无关键异常" if warning_count == 0 else "请优先处理关键事项"
                ),
                "tone": "red",
            },
        },
        "attendance": attendance,
        "recipe": recipe,
        "procurement": procurement,
        "finance": finance,
        "nutrition": nutrition,
        "focus": focus,
        "tasks": tasks,
        "business_cards": _business_cards(attendance, recipe, procurement, finance),
        "trend": trend,
    }
