"""Permission-checked, read-only data for the conversation's business canvas.

Codex selects a registered view/presentation, never supplies HTML, SQL or values.
SSE stores only the selection; data is read again as the viewer on every open.
"""
from __future__ import annotations

import json
from datetime import date

import frappe
from frappe.utils import now_datetime

from tongjianyun.attendance_scope import allowed_groups
from tongjianyun.classroom import _scope, _roster
from tongjianyun.meal_scene import business_day, meal_key, class_plans

VIEWS = {'students': '在园学生', 'class_students': '班级学生',
         'meal_counts': '用餐人数', 'recipe_week': '本周食谱', 'recipe_nutrition': '周食谱营养分析'}
LABELS = dict(zip(('breakfast', 'morning_snack', 'lunch', 'afternoon_snack', 'dinner'),
                  ('早餐', '早点', '午餐', '午点', '晚餐')))
PAGE_SIZE = 50
COMPONENTS = {'students': {'stats', 'table', 'bars', 'notice'},
              'class_students': {'stats', 'table', 'notice'},
              'meal_counts': {'stats', 'table', 'notice'}, 'recipe_week': {'recipe_week'},
              'recipe_nutrition': {'stats', 'table', 'notice'}}


def selection(value, default_day=None, default_meal='lunch'):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            frappe.throw('展示指令格式无效。')
    from tongjianyun.meal_nutrition_view import FIELDS, nutrition_selection
    if not isinstance(value, dict) or set(value) - ({'view', 'presentation', 'group', 'day', 'meal', 'offset', 'components'} | FIELDS):
        frappe.throw('展示指令含不支持的内容。')
    view = value.get('view')
    if not isinstance(view, str) or view not in VIEWS:
        frappe.throw('暂不支持这种业务视图。')
    clean = {'view': view}
    if view != 'recipe_nutrition' and set(value) & FIELDS:
        frappe.throw('这些筛选仅用于周食谱营养分析。')
    if view == 'recipe_nutrition':
        clean.update(nutrition_selection(value))
    if 'components' in value:
        blocks = value['components']
        if (not isinstance(blocks, list) or not 1 <= len(blocks) <= 4
                or any(not isinstance(block, str) or block not in COMPONENTS[view] for block in blocks)
                or len(set(blocks)) != len(blocks) or set(blocks) == {'notice'}):
            frappe.throw('组件组合无效，请使用已支持的数字、表格或条形图。')
        clean['components'] = blocks
    if view == 'students':
        presentation = value.get('presentation', 'table')
        if not isinstance(presentation, str) or presentation not in {'table', 'bars'}:
            frappe.throw('展示方式无效。')
        clean['presentation'] = presentation
    if view == 'class_students':
        group = value.get('group')
        if not isinstance(group, str) or not group.strip() or len(group) > 140:
            frappe.throw('请指定要查看的班级。')
        try:
            offset = int(value.get('offset', 0))
        except (ValueError, TypeError):
            frappe.throw('名单分页位置无效。')
        if not 0 <= offset <= 100000:
            frappe.throw('名单分页位置无效。')
        clean.update(group=group.strip(), offset=offset)
    if view in {'meal_counts', 'recipe_week', 'recipe_nutrition'}:
        clean.update(day=str(business_day(value.get('day') or default_day)),
                     meal=meal_key(value.get('meal') or default_meal))
    return clean


def _action(label, choice):
    return {'label': label, 'selection': choice}


def _stats(items):
    return {'type': 'stats', 'items': [{'label': label, 'value': value, 'unit': unit}
                                      for label, value, unit in items]}


def _notice(text, warning=False):
    return {'type': 'notice', 'text': text, 'warning': warning}


def _table(title, columns, rows):
    return {'type': 'table', 'title': title, 'columns': columns, 'rows': rows}


def _groups():
    frappe.has_permission('Student Group', 'read', throw=True)
    names = allowed_groups()
    return frappe.get_list('Student Group', filters={'name': ['in', names], 'disabled': 0},
                           fields=['name', 'student_group_name', 'academic_year'],
                           order_by='student_group_name asc, name asc', limit_page_length=0) if names else []


def roster_facts(visible_students, groups):
    """Global total is unique; memberships may overlap and never imply attendance."""
    visible = set(visible_students)
    assigned = set()
    membership_total = 0
    rows = []
    for group, members in groups:
        students = set(members) & visible
        assigned.update(students)
        membership_total += len(students)
        rows.append({'group': group['name'], 'label': group.get('student_group_name') or group['name'],
                     'academic_year': group.get('academic_year') or '未登记', 'count': len(students)})
    return {'total': len(visible), 'groups': rows, 'unassigned': len(visible - assigned),
            'overlap': membership_total - len(assigned)}


def students_view(choice):
    frappe.has_permission('Student', 'read', throw=True)
    visible = frappe.get_list('Student', filters={'enabled': 1}, pluck='name', limit_page_length=0)
    memberships = []
    for group in _groups():
        doc = frappe.get_doc('Student Group', group.name)
        doc.check_permission('read')
        members = [row.student for row in doc.get('students', []) if row.get('active') and row.get('student')]
        memberships.append((group, members))
    facts = roster_facts(visible, memberships)
    components = [_stats([('可见启用学生（去重）', facts['total'], '人'),
                          ('可见启用班级', len(facts['groups']), '个')])]
    if facts['unassigned']:
        components.append(_notice(f"有 {facts['unassigned']} 名可见启用学生不在上述班级的有效名单中，已计入学生总数。"))
    if facts['overlap']:
        components.append(_notice('存在跨班或跨学年重复归属，班级人数之和不等于去重学生总数。', True))
    wanted = set(choice.get('components') or ['stats', choice['presentation'], 'notice'])
    if 'bars' in wanted:
        components.append({'type': 'bars', 'title': '各班学生人数', 'rows': [
            {'label': row['label'], 'value': row['count'], 'action': _action('查看班级',
             {'view': 'class_students', 'group': row['group']})} for row in facts['groups']]})
    if 'table' in wanted:
        components.append(_table('各班学生人数', ['班级', '学年', '学生人数'], [
            {'cells': [row['label'], row['academic_year'], row['count']],
             'action': _action('查看班级', {'view': 'class_students', 'group': row['group']})}
            for row in facts['groups']]))
    return {'title': '在园学生', 'subtitle': '当前账号可见范围 · 当前启用学籍，不是历史人数或用餐人数',
            'components': components, 'source': '学生档案（启用）、班级有效名单；按当前账号权限读取',
            'summary': {'student_count': facts['total'], 'group_count': len(facts['groups']),
                        'not_in_visible_groups': facts['unassigned'], 'scope': '当前账号可见启用学生',
                        'groups': facts['groups']}}


def class_students_view(choice):
    groups = _groups()
    matches = [g for g in groups if g.name == choice['group']]
    if not matches:
        matches = [g for g in groups if g.student_group_name == choice['group']]
    if len(matches) != 1:
        frappe.throw('未找到唯一且有权查看的班级，请提供班级编号或完整名称。')
    group = matches[0]
    doc = _scope(group.name)
    roster = _roster(doc)
    choice['group'] = group.name
    offset = choice['offset']
    if offset and offset >= len(roster):
        frappe.throw('名单已变化，请返回班级第一页。')
    page = roster[offset:offset + PAGE_SIZE]
    actions = [_action('学生总览', {'view': 'students'})]
    if offset:
        actions.append(_action('上一页', {**choice, 'offset': max(0, offset - PAGE_SIZE)}))
    if offset + PAGE_SIZE < len(roster):
        actions.append(_action('下一页', {**choice, 'offset': offset + PAGE_SIZE}))
    return {'title': (group.student_group_name or group.name) + ' · 学生明细',
            'subtitle': '当前账号可见的有效班级名单 · 仅显示姓名、编号和学籍状态',
            'components': [_stats([('可见启用学生', len(roster), '人')]),
                _table('学生名单', ['姓名', '学生编号', '学籍状态'], [
                    {'cells': [r['student_name'], r['student'], '启用']} for r in page]),
                _notice(f'显示第 {offset + 1 if roster else 0}—{offset + len(page)} 条，共 {len(roster)} 条。')],
            'actions': actions, 'source': '班级有效名单与有权查看的启用学生档案',
            'summary': {'group': group.name, 'label': group.student_group_name or group.name,
                        'student_count': len(roster), 'scope': '当前可见有效名单；姓名不回传模型'}}


def meal_counts_view(choice):
    result = class_plans(date.fromisoformat(choice['day']), choice['meal'])
    if not result['available']:
        raise frappe.PermissionError('没有班级用餐人数查看权限。')
    summary = result['summary']
    total = summary['visible_groups']
    pending = total - summary['confirmed_groups']
    final = total > 0 and pending == 0
    components = [_stats([('已确认用餐总数' if final else '已确认用餐小计',
                          summary['actual'] if final else summary['confirmed_subtotal'], '人'),
                         ('待确认班级', pending, '个')])]
    if not total:
        components.append(_notice('当前没有可见启用班级，不能据此认定全园人数为零。', True))
        answer = '当前没有可见启用班级，用餐人数未知，不能报为零。'
    elif not final:
        components.append(_notice('班级确认尚未齐全，小计不能当作最终人数；未确认不记为零。', True))
        answer = (f'可见 {total} 个班级均尚未确认，实际用餐人数未知，不能报为 0 人。'
                  if summary['confirmed_subtotal'] is None else
                  f"已确认 {summary['confirmed_groups']} 个班，小计 {summary['confirmed_subtotal']} 人；还有 {pending} 个班待确认，最终人数未知。")
    else:
        answer = f"可见 {total} 个班均已确认，本餐实际用餐人数为 {summary['actual']} 人。"
    components.append(_table('班级确认情况', ['班级', '预计用餐', '已确认实际', '状态'], [
        {'cells': [row['label'], row['expected'], row['actual'],
                   '已确认' if row['confirmed'] else '待确认' if row['has_plan'] else '尚未保存预计']}
        for row in result['rows']]))
    return {'title': '用餐人数', 'subtitle': f"{choice['day']} · {LABELS[choice['meal']]} · 仅当前可见班级",
            'components': components, 'source': '班级餐次确认记录；未自动创建、确认或修改记录',
            'summary': {**summary, 'day': choice['day'], 'meal': LABELS[choice['meal']], 'final': final,
                        'answer': answer}}


@frappe.whitelist()
def get_view(selection_json):
    from tongjianyun.meal_chat import require_chat_access
    from tongjianyun.meal_nutrition_view import nutrition_view
    require_chat_access()
    choice = selection(selection_json)
    if choice['view'] == 'recipe_week':
        result = {'title': '本周食谱', 'subtitle': choice['day'],
                  'components': [{'type': 'recipe_week'}],
                  'source': '当前工作台周历；保留原食谱权限和读取规则',
                  'summary': {'day': choice['day'], 'meal': LABELS[choice['meal']]}}
    else:
        result = {'students': students_view, 'class_students': class_students_view,
                  'meal_counts': meal_counts_view, 'recipe_nutrition': nutrition_view}[choice['view']](choice)
    if choice.get('components'):
        # Required warnings cannot be hidden by a model's presentation choice.
        blocks = result['components']
        result['components'] = [block for kind in choice['components'] for block in blocks if block['type'] == kind]
        if 'notice' not in choice['components']:
            result['components'].extend(block for block in blocks if block['type'] == 'notice')
    return {'version': 1, 'selection': choice, 'generated_at': str(now_datetime()).split('.')[0], **result}


def publish_for_task(task_id, requested):
    """CLI-only capability: task owner is read from Redis, never from Codex args."""
    from tongjianyun.meal_chat import TaskStore, SESSION_RE, ACTIVE
    if not SESSION_RE.fullmatch(str(task_id or '')):
        raise ValueError('Invalid task id')
    store = TaskStore()
    task = store.read(task_id)
    if task.get('status') not in ACTIVE or task.get('cancel_requested') == '1':
        raise ValueError('Task is no longer active')
    original_user = frappe.session.user
    try:
        frappe.set_user(task['owner'])
        choice = selection(requested, task['day'], task['meal'])
        result = get_view(choice)
        # Cancellation while the query was running must not publish a late view.
        current = store.read(task_id)
        if current.get('status') not in ACTIVE or current.get('cancel_requested') == '1':
            raise ValueError('Task is no longer active')
        store.emit(task_id, {'kind': 'view', 'version': 1, 'selection': result['selection'],
                             'title': result['title']})
        return {'displayed': True, 'title': result['title'], 'summary': result['summary']}
    finally:
        frappe.set_user(original_user)


def tool_instruction(task_id, site, context=None):
    import shlex
    command = ('/home/zyd/frappe/native-bench/env/bin/python -m tongjianyun.meal_view_tool'
               f' --site {shlex.quote(site)} --task {shlex.quote(task_id)}')
    return ('\n【左侧业务视图】询问学生人数、班级名单、用餐人数、周食谱、周食谱营养分析时，必须调用下面的只读展示工具，'
            '它按当前网页用户权限查真实数据并通过 SSE 切换左侧。不要临时改页面代码、不要只口头声称已切换。'
            '工具回传 displayed=true 才能说已展示；失败则说明原因，不能编造数字。'
            '给用户的答复只说简短结论、范围和是否已展示；不要输出 displayed=true、内部 view 名、'
            '工具参数或代码，不要在聊天中重复整张班级表格。'
            '用餐结果含 summary.answer 时应沿用这个事实表述：null 表示未知而不是 0；'
            '已确认班级为 0 个也不能说已确认人数为 0 人。只有真实已确认记录中的数字 0 才能说 0 人。'
            '查询学生人数不要自行 SQL 或以班级人数之和当去重总数。名单不需要重复在对话中输出。'
            '支持 --view students [--presentation table|bars]；--view class_students --group 班级编号或唯一名称；'
            '--view meal_counts [--day YYYY-MM-DD --meal lunch]；--view recipe_week [--day YYYY-MM-DD --meal lunch]；'
            '--view recipe_nutrition [--day YYYY-MM-DD] [--recipe 食谱编号] [--garden-ratio 80]。'
            '周营养分析自动选择覆盖业务日期的唯一可见食谱；有多份时展示可点击选择，不要猜编号。'
            '分析全周日均每生估算，不是当前单餐或实测摄入；复用原周食谱营养分析，不自行计算或更改营养规则。'
            '默认按学生档案计算标准。只有用户明确要求手动估算时传 --standard-mode 手动估算，'
            '可选 --age-group 4岁|5岁|6岁|4–6岁平均 和 --gender 男|女|男女平均。'
            '可用 --student-groups 班级编号1 班级编号2 指定班级。参数仅影响本次只读分析，不保存标准设置。'
            '分析失败不得隐瞒错误或自动降级手动口径。展示结果 summary.available=false 时说明需选择/补充食谱。'
            '营养视图的后续调整应沿用当前左侧选择里的食谱、供给目标和标准筛选，除非用户要求变更。'
            '未指定日期餐次则沿用本轮页面选择。当前是实际用餐请用 meal_counts，不要用学籍数替代。'
            '用户只问学生数量时使用 students；图表需求可选 bars。'
            '若用户要求组合或调整布局，可加 --components stats bars table（按顺序显示数字、图表、表格）；'
            '只有 students 支持 bars，其余非食谱视图可组合 stats table。默认沿用简洁布局，不主动堆叠。'
            '用户说“这个班”时参考下面左侧选择。涉及其他业务照常使用已有业务服务，不要新增未经测试的展示类型。'
            '\n工具命令：' + command + '\n当前左侧选择：' + json.dumps(context or {'view': 'recipe_week'}, ensure_ascii=False))
