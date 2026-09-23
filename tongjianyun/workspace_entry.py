"""Role-aware entry, not role assignment or an impersonation mechanism.

The teacher workspace intersects active teaching assignments with existing
Frappe read permissions. Choosing it never grants rights or changes roles.
"""
from __future__ import annotations

from urllib.parse import urlencode

import frappe

ENTRY = "/tongjianyun-entry"
CLASSROOM = "/tongjianyun-classroom"
WORKBENCH = "/desk/tongjianyun-workbench"
MULTI_WORK_ROLES = {"System Manager", "Education Manager", "Tongjianyun Health Manager"}


def require_account():
    user = frappe.session.user
    if user == "Guest":
        raise frappe.PermissionError("请先登录")
    account = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
    if not account or not account.enabled or account.user_type != "System User":
        raise frappe.PermissionError("请使用已启用的园内工作账号")


def teaching_assignment():
    """Only current-user identity links are read internally; no pupil data."""
    require_account()
    employees = frappe.get_all("Employee", filters={"user_id": frappe.session.user, "status": "Active"}, pluck="name")
    instructors = frappe.get_all("Instructor", filters={"employee": ["in", employees], "status": "Active"}, pluck="name") if employees else []
    parents = frappe.get_all("Student Group Instructor", filters={
        "instructor": ["in", instructors], "parenttype": "Student Group", "parentfield": "instructors",
    }, pluck="parent") if instructors else []
    can_read = all(frappe.has_permission(dt, "read") for dt in ("Student Group", "Student"))
    groups = frappe.get_list("Student Group", filters={"name": ["in", sorted(set(parents))], "disabled": 0},
        fields=["name", "student_group_name"], order_by="student_group_name asc, name asc", limit_page_length=0
    ) if parents and can_read else []
    return {"employee_linked": bool(employees), "instructor_linked": bool(instructors),
            "class_linked": bool(parents), "can_read_classroom": bool(can_read),
            "groups": [dict(g) for g in groups]}


def teacher_groups():
    return [g["name"] for g in teaching_assignment()["groups"]]


def can_open_workbench():
    # Use the actual Page's custom/native role checks, not a duplicated allowlist.
    try:
        page = frappe.get_doc("Page", "tongjianyun-workbench")
        return bool(page.is_permitted())
    except (frappe.DoesNotExistError, frappe.PermissionError):
        return False


def choose_profiles(user, roles, assignment, workbench_available):
    """Pure classification. Business Operator alone is not a teaching identity."""
    roles = set(roles)
    teacher = "Instructor" in roles or assignment["instructor_linked"]
    profiles = []
    if teacher:
        if not assignment["employee_linked"]:
            detail = "尚未关联启用的员工档案，请由管理员核对员工的用户账号。"
        elif not assignment["instructor_linked"]:
            detail = "尚未关联在岗教师档案，请核对教师与员工的关联。"
        elif not assignment["can_read_classroom"]:
            detail = "缺少学生或班级读取权限，请管理员按原权限流程核对。"
        elif not assignment["groups"]:
            detail = "尚无可见的启用任教班级，请核对班级教师关联与班级读取范围。"
        else:
            detail = "进入本人任教班级，在 3D 教室中点名、核餐和记录成长。"
        profiles.append({"id": "teacher", "label": "班级教师", "description": detail,
                         "enabled": bool(assignment["groups"]), "class_count": len(assignment["groups"])})
    # The school's broad Business Operator role is a base grant, not evidence of
    # being a director. Explicit non-teaching roles retain their existing entry.
    if workbench_available and (not teacher or user == "Administrator" or roles & MULTI_WORK_ROLES):
        profiles.append({"id": "business", "label": "业务工作台", "enabled": True,
                         "description": "沿用当前账号已有的管理、膳食及其他业务入口。", "class_count": 0})
    return profiles


def entry_model():
    assignment = teaching_assignment()
    business = can_open_workbench()
    profiles = choose_profiles(frappe.session.user, frappe.get_roles(), assignment, business)
    from tongjianyun.meal_scene import has_access as can_open_meal_scene
    teacher_only = profiles and all(p["id"] == "teacher" for p in profiles)
    if not teacher_only and can_open_meal_scene():
        profiles.append({"id": "meals", "label": "膳食全流程场景", "enabled": True,
            "description": "按业务顺序核对食谱、采购、到货、库存与实际用餐；不增加原账号权限。", "class_count": 0})
    return {"profiles": profiles, "groups": assignment["groups"],
            "checks": {k: v for k, v in assignment.items() if k != "groups"},
            "business_available": business,
            "user_label": frappe.db.get_value("User", frappe.session.user, "full_name") or "老师"}


def resolve_entry(model, profile=None, group=None, choose=False):
    """Return one allowlisted local destination or a selection screen."""
    enabled = [p for p in model["profiles"] if p["enabled"]]
    available = {p["id"]: p for p in model["profiles"]}
    if profile and profile not in available:
        raise frappe.PermissionError("当前账号没有该工作入口")
    profile = profile or (enabled[0]["id"] if len(enabled) == 1 and len(available) == 1 else None)
    if group and profile != "teacher":
        raise frappe.PermissionError("请从教师入口选择任教班级")
    if profile == "teacher":
        valid = {g["name"] for g in model["groups"]}
        if group and group not in valid:
            raise frappe.PermissionError("该班级不在当前可见的任教范围内")
        if not available["teacher"]["enabled"]:
            return {"destination": None, "view": "setup", "profile": "teacher"}
        selected = group or (model["groups"][0]["name"] if len(valid) == 1 and not choose else None)
        if selected:
            return {"destination": CLASSROOM + "?" + urlencode({"workspace": "teacher", "class": selected}),
                    "view": "redirect", "profile": "teacher"}
        return {"destination": None, "view": "classes", "profile": "teacher"}
    if profile == "meals" and available["meals"]["enabled"] and not choose:
        return {"destination": "/tongjianyun-meal-scene", "view": "redirect", "profile": "meals"}
    if profile == "business" and not choose:
        return {"destination": WORKBENCH, "view": "redirect", "profile": "business"}
    return {"destination": None, "view": "profiles" if enabled else "setup", "profile": profile}


def temporary_redirect(destination):
    frappe.local.flags.redirect_location = destination
    # Never issue a browser-cacheable 301 for a user-dependent landing choice.
    raise frappe.Redirect(http_status_code=303)


def mark_private_response():
    frappe.local.no_cache = 1
    # Native Frappe app.process_response consumes response_headers, not the
    # JSON response payload. Apply to selection pages AND personal redirects.
    headers = dict(getattr(frappe.local, "response_headers", {}) or {})
    vary = {v.strip() for v in headers.get("Vary", "").split(",") if v.strip()}
    vary.add("Cookie")
    headers.update({"Cache-Control": "private, no-store, max-age=0", "Vary": ", ".join(sorted(vary))})
    frappe.local.response_headers = headers


@frappe.whitelist()
def get_options():
    mark_private_response()
    return entry_model()
