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
from tongjianyun.business_views import VIEWS as BUSINESS_VIEWS, FIELDS as BUSINESS_FIELDS, clean_selection, get_business_view
from tongjianyun.frappe_project_views import VIEWS as PROJECT_VIEWS, FIELDS as PROJECT_FIELDS, selection as project_selection, get_view as project_view
from tongjianyun.business_proposal_views import VIEWS as PROPOSAL_VIEWS, FIELDS as PROPOSAL_FIELDS

VIEWS = {'students': '在园学生', 'class_students': '班级学生',
         'meal_counts': '用餐人数', 'recipe_week': '本周食谱', 'recipe_nutrition': '周食谱营养分析',
         'business_blueprint': '新业务方案', 'business_proposal': '我的新业务方案',
         'stock_reconciliation': '库存核对', **BUSINESS_VIEWS, **PROJECT_VIEWS, **PROPOSAL_VIEWS}
LABELS = dict(zip(('breakfast', 'morning_snack', 'lunch', 'afternoon_snack', 'dinner'),
                  ('早餐', '早点', '午餐', '午点', '晚餐')))
PAGE_SIZE = 50
COMPONENTS = {'students': {'stats', 'table', 'bars', 'notice'},
              'class_students': {'stats', 'table', 'notice'},
              'meal_counts': {'stats', 'table', 'notice'}, 'recipe_week': {'recipe_week'},
              'recipe_nutrition': {'stats', 'table', 'notice'},
              **{key: {'stats', 'table', 'notice'} for key in BUSINESS_VIEWS},
              **{key: {'table', 'notice', 'frappe_frame'} for key in PROJECT_VIEWS}}


def selection(value, default_day=None, default_meal='lunch'):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            frappe.throw('展示指令格式无效。')
    from tongjianyun.meal_nutrition_view import FIELDS, nutrition_selection
    from tongjianyun.stock_reconciliation import FIELDS as STOCK_FIELDS, selection as stock_selection
    if not isinstance(value, dict) or set(value) - ({'view', 'presentation', 'group', 'day', 'meal', 'offset', 'components', 'proposal_id', 'revision'} | FIELDS | BUSINESS_FIELDS | PROJECT_FIELDS | STOCK_FIELDS | PROPOSAL_FIELDS):
        frappe.throw('展示指令含不支持的内容。')
    view = value.get('view')
    if not isinstance(view, str) or view not in VIEWS:
        frappe.throw('暂不支持这种业务视图。')
    clean = {'view': view}
    if view in PROPOSAL_VIEWS:
        from tongjianyun.business_proposal_views import selection as proposal_selection
        return proposal_selection(value)
    if set(value) & PROPOSAL_FIELDS:
        frappe.throw('交接筛选仅用于方案交接视图。')
    if view == 'business_proposal':
        from tongjianyun.business_agent_proposals import canonical_selection
        return canonical_selection(value)
    if 'revision' in value:
        frappe.throw('方案版本仅用于我的新业务方案视图。')
    if view == 'stock_reconciliation':
        return stock_selection(value)
    if set(value) & STOCK_FIELDS:
        frappe.throw('来源单据参数仅用于库存核对。')
    if view == 'business_blueprint':
        from tongjianyun.business_views import text_arg
        if set(value) - {'view', 'proposal_id', 'day', 'meal'} or not value.get('proposal_id'):
            frappe.throw('请指定已保存的业务方案；不支持临时脚本或组件。')
        return {**clean, 'proposal_id': text_arg(value, 'proposal_id')}
    if 'proposal_id' in value:
        frappe.throw('业务方案编号仅用于新业务方案视图。')
    if view in PROJECT_VIEWS:
        if 'components' in value:
            frappe.throw('原生业务保持完整页面，不支持裁剪权限提示或操作组件。')
        return {**clean, **project_selection(value, default_day, default_meal)}
    if set(value) & PROJECT_FIELDS:
        frappe.throw('这些参数仅用于全项目业务视图。')
    if view in BUSINESS_VIEWS:
        clean.update(clean_selection(value, default_day, default_meal))
    elif set(value) & BUSINESS_FIELDS:
        frappe.throw('这些筛选仅用于对应业务视图。')
    if view not in {'recipe_nutrition', 'ingredient_nutrition'} and set(value) & FIELDS:
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
    if view == 'meal_counts' and value.get('group'):
        from tongjianyun.business_views import text_arg
        clean['group'] = text_arg(value, 'group')
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
    if choice.get('group'):
        return meal_register_view(choice)
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
        {'cells': [row['label'], row['expected'], row['actual'], row.get('status') or
                   ('已确认' if row['confirmed'] else '待确认' if row['has_plan'] else '尚未保存预计')],
         'action': _action('核对本餐', {**choice, 'group': row['group']})}
        for row in result['rows']]))
    return {'title': '用餐人数', 'subtitle': f"{choice['day']} · {LABELS[choice['meal']]} · 仅当前可见班级",
            'components': components, 'source': '班级餐次确认记录；未自动创建、确认或修改记录',
            'summary': {**summary, 'day': choice['day'], 'meal': LABELS[choice['meal']], 'final': final,
                        'answer': answer}}


def meal_register_view(choice):
    from tongjianyun.classroom import get_meals, _capabilities
    groups = _groups()
    matches = [g for g in groups if g.name == choice['group']] or [g for g in groups if g.student_group_name == choice['group']]
    if len(matches) != 1:
        frappe.throw('未找到唯一可见班级，请通过班级列表选择。')
    group = matches[0]
    choice['group'] = group.name
    day, meal = business_day(choice['day']), choice['meal']
    data = get_meals(group.name, str(day))
    capabilities = _capabilities(day)
    facts = dict(data['meals'][meal])
    has_plan = bool(data['revision'])
    if not has_plan:
        facts.update(actual=None, complete=False, status='尚未保存预计')
    editable = bool(capabilities['meals_write'] and not capabilities['future'] and data['record'].get('students'))
    rows = [{'student': row['student'], 'student_name': row['student_name'],
             'value': {'已就餐': '就餐', '未就餐': '不就餐', '不供餐': '不供餐'}.get(row.get(meal), '未确认'),
             'expected': bool(row.get(meal + '_expected'))} for row in data['record'].get('students', [])]
    return {'title': '核对本餐实际用餐', 'subtitle': f'{group.student_group_name or group.name} · {day} · {LABELS[meal]}',
            'components': [_notice('只确认当前班级这一餐。预计人数不是实际就餐；其他餐次和出勤不会随之确认。'),
                {'type': 'meal_register', 'student_group': group.name, 'group_label': group.student_group_name or group.name,
                 'day': str(day), 'meal': meal, 'meal_label': LABELS[meal], 'revision': data['revision'],
                 'editable': editable, 'confirmed': bool(facts['complete']), 'has_plan': has_plan,
                 'requires_change_reason': any(row.get(meal) in {'已就餐', '未就餐'} for row in data['record'].get('students', [])),
                 'facts': facts,
                 'reason': ('未来日期不能确认实际就餐' if capabilities['future'] else
                            '' if editable else '当前权限、锁定状态或空名单不允许确认'), 'rows': rows}],
            'actions': [_action('返回用餐汇总', {'view': 'meal_counts', 'day': str(day), 'meal': meal})],
            'source': '原班级就餐服务；保存后逐餐回读，无需再做每日二次确认',
            'summary': {'day': str(day), 'meal': LABELS[meal], 'group': group.name, 'facts': facts,
                        'answer': '已读取本班本餐待核对名单；打开页面不表示已经确认，学生姓名不回传模型。'}}


@frappe.whitelist()
def get_view(selection_json):
    from tongjianyun.scene_access import require_scene_account, require_view_access
    from tongjianyun.meal_nutrition_view import nutrition_view
    require_scene_account()
    choice = selection(selection_json)
    require_view_access(choice['view'])
    if choice['view'] == 'recipe_week':
        result = {'title': '本周食谱', 'subtitle': choice['day'],
                  'components': [{'type': 'recipe_week'}],
                  'source': '当前工作台周历；保留原食谱权限和读取规则',
                  'summary': {'day': choice['day'], 'meal': LABELS[choice['meal']]}}
    elif choice['view'] == 'business_blueprint':
        from tongjianyun.business_blueprints import preview
        result = preview(choice['proposal_id'])
    elif choice['view'] == 'business_proposal':
        from tongjianyun.business_agent_service import application
        app, _ = application(require_ready=False)
        if app.proposals is None:
            raise frappe.PermissionError('新业务方案存储尚未配置，未启用任何业务结构。')
        result = app.proposals.preview_owned(app.viewer(), choice['proposal_id'], choice['revision'])
        result['actions'] = [_action('查看交接记录', {'view': 'business_proposal_inbox', 'folder': 'sent', 'state': 'all'})]
        result['summary'] = {'answer': '已读取当前账号的指定方案版本；草稿未代表业务已启用。'}
    elif choice['view'] in PROPOSAL_VIEWS:
        from tongjianyun.business_proposal_views import get_view as proposal_view
        result = proposal_view(choice)
    elif choice['view'] == 'stock_reconciliation':
        from tongjianyun.stock_reconciliation import get_view as stock_view
        result = stock_view(choice)
    else:
        result = project_view(choice) if choice['view'] in PROJECT_VIEWS else get_business_view(choice) if choice['view'] in BUSINESS_VIEWS else {
            'students': students_view, 'class_students': class_students_view,
            'meal_counts': meal_counts_view, 'recipe_nutrition': nutrition_view}[choice['view']](choice)
    if choice.get('components'):
        # Required warnings cannot be hidden by a model's presentation choice.
        blocks = result['components']
        result['components'] = [block for kind in choice['components'] for block in blocks if block['type'] == kind]
        if 'notice' not in choice['components']:
            result['components'].extend(block for block in blocks if block['type'] == 'notice')
        result['components'].extend(block for block in blocks if block['type'] in {'attendance_register', 'meal_register'})
    return {'version': 1, 'selection': choice, 'generated_at': str(now_datetime()).split('.')[0], **result}


def publish_for_task(task_id, requested):
    """CLI-only capability: task owner is read from Redis, never from Codex args."""
    from tongjianyun.meal_chat import TaskStore, SESSION_RE, ACTIVE, require_chat_access
    if not SESSION_RE.fullmatch(str(task_id or '')):
        raise ValueError('Invalid task id')
    store = TaskStore()
    task = store.read(task_id)
    if task.get('status') not in ACTIVE or task.get('cancel_requested') == '1':
        raise ValueError('Task is no longer active')
    original_user = frappe.session.user
    try:
        frappe.set_user(task['owner'])
        # This CLI belongs to the existing administrator runner. Opening views
        # to ordinary accounts must not make a revoked/root task publishable.
        require_chat_access()
        choice = selection(requested, task['day'], task['meal'])
        if choice['view'] in PROPOSAL_VIEWS:
            # A CLI task identity is not a live browser Viewer. Never invent a
            # session or hand its SID to Codex to query private handoffs. Emit
            # only the exact navigation choice; the user's actual GET performs
            # recipient/owner checks and reads the records in the browser.
            result = {'selection': choice, 'title': VIEWS[choice['view']],
                      'summary': {'data_read': False, 'activation_verified': False,
                                  'answer': '正在请求左侧打开方案交接；浏览器将按当前账号核权读取，尚未查询记录或执行接收。'}}
        else:
            result = get_view(choice)
        # Cancellation while the query was running must not publish a late view.
        current = store.read(task_id)
        if current.get('status') not in ACTIVE or current.get('cancel_requested') == '1':
            raise ValueError('Task is no longer active')
        store.emit(task_id, {'kind': 'view', 'version': 1, 'selection': result['selection'],
                             'title': result['title']})
        return {'display_requested': True, 'title': result['title'], 'summary': result['summary'],
                'delivery': '已发送视图指令；浏览器会报告实际加载结果，不代表业务操作完成。'}
    finally:
        frappe.set_user(original_user)


def tool_instruction(task_id, site, context=None):
    import shlex
    from tongjianyun.business_view_registry import catalog_instruction
    from tongjianyun.frappe_project_views import tool_instruction as project_instruction
    command = ('/home/zyd/frappe/native-bench/env/bin/python -m tongjianyun.meal_view_tool'
               f' --site {shlex.quote(site)} --task {shlex.quote(task_id)}')
    return ('\n【左侧业务视图】询问学生、班级、考勤、健康登记、膳食、采购、库存、财务、教职工或以下目录中的业务时，必须调用下面的只读展示工具，'
            '它按当前网页用户权限查真实数据并通过 SSE 切换左侧。不要临时改页面代码、不要只口头声称已切换。'
            '工具回传 display_requested=true 只表示已发送展示指令，不表示浏览器已加载；请说“已查询，正在左侧打开”，失败则说明原因，不能编造数字。'
            '例外：summary.data_read=false 时尚未读取记录，只能说“正在请求左侧打开”，不能说已查询、已接收或已启用。'
            '给用户的答复只说简短结论、范围和是否已展示；不要输出 displayed=true、内部 view 名、'
            '工具参数或代码，不要在聊天中重复整张班级表格。'
            '用餐结果含 summary.answer 时应沿用这个事实表述：null 表示未知而不是 0；'
            '已确认班级为 0 个也不能说已确认人数为 0 人。只有真实已确认记录中的数字 0 才能说 0 人。'
            '查询学生人数不要自行 SQL 或以班级人数之和当去重总数。名单不需要重复在对话中输出。'
            '支持 --view students [--presentation table|bars]；--view class_students --group 班级编号或唯一名称；'
            '--view business_proposal_inbox --folder received 查看明确交给当前账号的待处理新业务方案，'
            '可用 --state all 查看全部接收记录；--folder sent 查看自己交出的方案。'
            '具体交接用 --view business_proposal_handoff --handoff-id 已读取的交接编号 展示。'
            '用户在左侧明确接收，再核对启用；只读展示不表示接受、启用或授予权限。'
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
            '用户说“这个班/这些记录”时参考下面左侧选择。'
            '童健云常用业务目录：--view business_catalog [--domain 分组中文名]；全项目全部业务使用后文 frappe_catalog。'
            '业务列表：--view business_list --entity 业务键 [--day YYYY-MM-DD] [--period all|day|week|month] '
            '[--start-date YYYY-MM-DD --end-date YYYY-MM-DD] [--keyword 关键词] [--status 原单据状态] '
            '[--group 班级编号] [--company 组织编号] [--warehouse 仓库编号] [--offset 0]。'
            '筛选仅在该业务字段及权限支持时可用，不支持会明确报错，不可偷偷忽略。学生人数用 students，不要用档案记录数替代。'
            '采购默认本周，财务默认本月，考勤默认当日，主数据默认全部日期；日期以页面选择为准。'
            '跨期请假按时间交集筛选。库存是当前值，不是历史快照。用户问全部历史须明确传 --period all。'
            '单据明细：--view business_record --entity 业务键 --record 精确编号；不猜单据编号，先展示可点击列表。'
            '库存：--view stock [--warehouse 仓库编号]；食材营养统计：--view ingredient_nutrition [--recipe 食谱编号]。'
            '库存流水与汇总核对：--view stock_reconciliation --source-doctype "Purchase Receipt"或"Stock Entry" --source-name 精确单据编号；'
            '先核实原单据，不猜编号。该工具只核对；当前生产环境仅开放诊断，原生修复仍限隔离验收，不得声称已经修好。'
            '隔离验收的修复按钮也要求用户明确确认，复用原生重算，不改流水或来源单。'
            '不得替用户调用repair_stock或伪造确认；待重估/失败重估、无修复权限或不支持估值法时说明阻断原因。'
            '班级当日出勤及登记表：--view classroom_day [--group 班级编号或唯一名称] [--day YYYY-MM-DD]；'
            '核对本餐实际用餐：--view meal_counts --group 班级编号 --day YYYY-MM-DD --meal 餐次；左侧直接办理，无需另做每日二次确认。'
            '一周食谱采购：--view weekly_orders [--period week|all] [--day YYYY-MM-DD] [--status 0|1|2]；'
            '此视图按订单标题中的食谱日期，与普通采购订单按交易日期筛选不同。'
            '业务键目录：' + catalog_instruction() + '。'
            '展示工具本身只读；左侧原生表单和登记组件可按原权限办理，但不能把展示成功说成已创建、确认、发布、付款或已完成业务。'
            '统计记录数不是去重人数、人次、金额或物料总量。没有记录不能推断没发生业务；无权限不能报0。'
            '目录里没有的业务先检索全部已安装应用，不得假装已有记录。确需新业务时使用下面的新业务方案工具；复杂业务通过源码扩展、测试、部署实现，不在浏览器执行模型代码。'
            '后续沿用左侧筛选，除非用户要求调整。其他写操作仍使用原有业务服务与审批。'
            + project_instruction()
            + '\n【未知业务创建】用户明确要求新增业务而当前目录没有合适类型时，可生成数据方案 JSON，'
            '再使用同一命令 --propose-business /绝对路径/方案.json（不要同时传 --view）。'
            'JSON 仅含 key(小写英文业务键)、title(中文名)、description(用途)、fields 数组；'
            '字段仅接受 fieldname、label、fieldtype、reqd、options。'
            'fieldtype 支持 Data、Small Text、Date、Datetime、Int、Float、Currency、Check、Select、Link；'
            'Select.options 是换行选项；Link.options 必须是已核实的现有类型。自动加入必填名称字段 title，无需重复提供。'
            '方案将作为私有文件保存并展示；用户在左侧点击“确认启用”后才创建独立自定义类型、启用历史记录并进入全站目录。'
            '初始只有 System Manager 可访问，不开放删除权限；不是完整专业审批、库存或会计模块。'
            '不得替用户调用 activate、伪造确认、直接修改元数据或将方案状态说成启用成功。'
            '简单明细/复核可用 version:2：仍含上述基础字段，可加 tables(最多2项，每项fieldname,label,reqd,fields，最多12字段)、'
            'calculations(最多8项，仅明细乘法{op:"multiply",table,target,sources:[数量字段,单价字段]}与主表汇总{op:"sum",table,target,source})，'
            '计算target必须为非必填Currency，结果固定两位小数，来源仅非负有限Int/Float/Currency；乘法不能引用计算结果。'
            '可选workflow:{template:"review"}，固定草稿/送审/退回/通过/撤销；System Manager复核，普通账号不能自审，Administrator有原生例外。'
            '此模板只建立独立估算/登记/复核数据，不自动付款、扣库存或复制原专业流程；全部结构仍须左侧明确确认后启用。'
            '更复杂计算、外部集成、多级或专业审批继续以 Tongjianyun 源码扩展实现：先复用原服务，补测试、验证权限与回滚，再发布到左侧。'
            '使用ERP映射器后按原生网页方式从mapped.as_dict()重新构造Document再保存，避免退货等构造状态遗漏。'
            '采购/收货/退货/取消完成后必须回读来源单、有效流水和Bin的数量及库存价值；docstatus成功不代表整条链路一致。'
            '当前ERP取消后可能库存价值滞后；先读取原生重估状态和差异，不得谎报一致或未经核对直接改金额。'
            '优先复用已有类型；不能借新业务复制每周食谱、绕过原审批或创建敏感权限表。'
            '\n工具命令：' + command + '\n当前左侧选择：' + json.dumps(context or {'view': 'recipe_week'}, ensure_ascii=False))
