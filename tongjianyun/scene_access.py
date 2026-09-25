"""The unified scene is an account entry, never an administrator execution grant.

Read-only bootstrap is a UI hint. Each business view and original write service
must still check the current actor's document and row permissions on every call.
"""
import frappe

from tongjianyun.workspace_entry import require_account, mark_private_response


# Audited native DocType routes retain their own Frappe permissions. Individual
# report SQL, page RPCs and workspace content still need scope acceptance; their
# unified-scene entries remain behind the existing administrator gate.
BUSINESS_VIEWS = frozenset({
    'students', 'class_students', 'classroom_day', 'meal_counts',
    'frappe_catalog', 'frappe_doctype', 'frappe_document', 'frappe_new',
})


def require_scene_account():
    require_account()
    mark_private_response()


def can_manage_projects():
    try:
        require_scene_account()
    except frappe.PermissionError:
        return False
    return frappe.session.user == 'Administrator' or 'System Manager' in frappe.get_roles(frappe.session.user)


def require_project_access():
    require_scene_account()
    if not can_manage_projects():
        raise frappe.PermissionError('服务器项目目录仅向系统管理员开放。')


def can_read_calendar():
    from tongjianyun.meal_scene import has_access, can, RECIPE
    return bool(has_access() and can(RECIPE))


def can_use_admin_chat():
    from tongjianyun.meal_scene import has_access
    return bool(can_manage_projects() and has_access())


def require_view_access(view):
    require_scene_account()
    if view == 'project_catalog':
        require_project_access()
    elif view == 'recipe_week':
        if not can_read_calendar():
            raise frappe.PermissionError('当前账号没有周食谱读取权限。')
    elif view not in BUSINESS_VIEWS:
        # Do not broaden the root runner, schema activation or unaudited views.
        from tongjianyun.meal_chat import require_chat_access
        require_chat_access()


@frappe.whitelist(methods=['GET'])
def get_bootstrap(day=None, meal='lunch', group=None):
    require_scene_account()
    from tongjianyun.meal_scene import business_day, meal_key, can, CLASS_MEAL
    from tongjianyun.attendance_scope import allowed_groups

    day, meal = str(business_day(day)), meal_key(meal)
    context = {'day': day, 'meal': meal}
    roster = all(can(dt) for dt in ('Student', 'Student Group'))
    groups = allowed_groups() if roster else []
    if group is not None:
        if not isinstance(group, str) or not group or len(group) > 140 or group not in groups:
            raise frappe.PermissionError('该班级不在当前可见的任教范围内。')
    selected = group or (groups[0] if len(groups) == 1 else None)
    class_context = {**context, **({'group': selected} if selected else {})}
    calendar = can_read_calendar()
    attendance = roster and bool(groups) and all(can(dt) for dt in ('Student Attendance', 'Student Leave Application'))
    meals = roster and bool(groups) and can(CLASS_MEAL)
    chat = can_use_admin_chat()
    navigation = []
    if calendar:
        navigation.append({'label': '周食谱', 'selection': {'view': 'recipe_week', **context}})
    if attendance:
        navigation.append({'label': '本班点名', 'selection': {'view': 'classroom_day', **class_context}})
    if meals:
        navigation.append({'label': '核对用餐', 'selection': {'view': 'meal_counts', **class_context}})
    if roster:
        navigation.append({'label': '学生与班级', 'selection': {'view': 'students'}})
    navigation.append({'label': '可用业务', 'selection': {'view': 'frappe_catalog', **context}})
    return {
        'version': 1, 'user': frappe.session.user,
        'user_label': frappe.db.get_value('User', frappe.session.user, 'full_name') or frappe.session.user,
        **context, 'recipe_calendar': calendar,
        'chat': {'allowed': chat, 'mode': 'admin_project' if chat else 'unavailable',
                 'reason': '' if chat else '当前账号的业务对话尚未开通，可先在左侧办理已有权限的业务。'},
        'default_view': navigation[0]['selection'], 'navigation': navigation,
        'scope': {'group_count': len(groups), 'selected_group': selected},
        'phase': 'views_only_for_non_admin',
        'coverage': 'audited_classroom_and_native_doctypes' if not chat else 'administrator_business_views',
    }
