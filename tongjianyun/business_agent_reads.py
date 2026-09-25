"""Source-aware, paginated ordinary-business discovery and roster tools.

No RPC decorator, owner argument, generic dispatch, writes or model calls. The
trusted worker constructs BusinessReads(authority, store), then passes its own
WorkerClaim to dispatch. Original native assignment, list/document and field
permissions are rechecked before data and selection-only events leave here.

Pagination never turns a page size into a school total. The task's persistent
scope budget is real: when exhausted, start another task rather than dropping
old sources or releasing unregistered data. Cursors contain only a roster
revision and scan position, not identities/credentials/inaccessible student IDs.
"""
from __future__ import annotations

import base64
import json
import re

import frappe

from tongjianyun import business_agent_authority as gates
from tongjianyun.business_agent_tasks import WorkerClaim, MAX_SCOPES
from tongjianyun.business_agent_tools import _validate_arguments

DEFAULT_PAGE = 25
MAX_PAGE = 50
TOOL_INSTRUCTIONS = {
    'scene_bootstrap': (
        'scene_bootstrap 参数为 {day:"YYYY-MM-DD",meal?:"lunch",after?:上次next_after,page_size?:1到50}。'
        '未知班级编号时先调用，按当前账号的原生任教及读取权限分页取得真实班级编号和名称。'
        '只把visible_group_count非null作为当前可见班级总数；page_count不是全园班数。'
        'has_more=true时可用next_after继续，不猜班级编号；本工具不授予开发或管理员能力。'),
    'class_students_read': (
        'class_students_read 参数为 {group:已知班级编号,cursor?:上次next_cursor,page_size?:1到50}。'
        '读取原班级有效成员中当前账号有权查看的启用学生，顺序与原名单一致。'
        '仅visible_class_count非null时才获得该班当前可见启用人数；page_count不是总人数，学籍不是出勤或就餐。'
        'has_more=null表示扫描未完成，不能说没有其他学生。按next_cursor继续，名单变更后从第一页重查。'
        'scope_budget_exhausted不是空名单，应说明本次读取额度已到，需要新任务继续。'
        '工具会请求左侧打开本班名单，不代表浏览器已加载，不在聊天重复学生姓名表。'),
    'meal_read': (
        'meal_read 参数仅为 {group:已知班级编号,day:"YYYY-MM-DD"}，读取原服务本班当日五餐的真实保存状态。'
        'meals中expected是预计，actual=null是实际未知，不能报为0，也不能把预计或到园人数当实际就餐。'
        '本工具只读，不保存、不确认、不修订。会请求左侧打开本班用餐核对视图；仅代表展示请求，'
        '不在对话重复姓名名单。来源权限额度不足时说明无法完整读取，不能用部分名单核餐。'),
}


def _text(value, maximum=140):
    if (not isinstance(value, str) or not 1 <= len(value) <= maximum or value != value.strip()
            or any(ord(c) < 32 for c in value)):
        raise ValueError('Invalid bounded business text')
    return value


def _arguments(tool, arguments):
    if type(arguments) is not dict:
        raise ValueError('Expected finite tool arguments')
    raw = json.dumps(arguments, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    if len(raw.encode()) > 8192:
        raise ValueError('Tool arguments exceed bound')
    args = json.loads(raw)
    if tool == 'meal_read':
        return _validate_arguments(tool, args)
    keys = ({'day', 'meal', 'after', 'page_size'} if tool == 'scene_bootstrap' else
            {'group', 'cursor', 'page_size'} if tool == 'class_students_read' else None)
    required = {'day'} if tool == 'scene_bootstrap' else {'group'}
    if keys is None or set(args) - keys or not required <= set(args):
        raise ValueError('Unsupported source-aware tool arguments')
    size = args.setdefault('page_size', DEFAULT_PAGE)
    if type(size) is not int or not 1 <= size <= MAX_PAGE:
        raise ValueError('Invalid page size')
    if tool == 'scene_bootstrap':
        context = _validate_arguments('scene_bootstrap', {key: args[key] for key in ('day', 'meal') if key in args})
        args.update(context)
        if 'after' in args:
            _text(args['after'])
    else:
        _text(args['group'])
        if 'cursor' in args:
            _decode_cursor(args['cursor'])
    return args


def _encode_cursor(index, revision):
    raw = json.dumps({'v': 1, 'index': index, 'revision': revision}, separators=(',', ':')).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def _decode_cursor(value):
    _text(value, 512)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('Invalid roster cursor')
    try:
        raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
        cursor = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ValueError('Invalid roster cursor') from None
    if (type(cursor) is not dict or set(cursor) != {'v', 'index', 'revision'}
            or type(cursor['v']) is not int or cursor['v'] != 1
            or type(cursor['index']) is not int or not 0 <= cursor['index'] <= 1000000
            or not isinstance(cursor['revision'], str) or not re.fullmatch('[a-f0-9]{64}', cursor['revision'])
            or _encode_cursor(cursor['index'], cursor['revision']) != value):
        raise ValueError('Invalid roster cursor')
    return cursor['index'], cursor['revision']


def _scope_key(scope):
    return json.dumps(scope, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _budget_result():
    return {'available': False, 'error': 'scope_budget_exhausted', 'retry': 'new_task',
            'message': '本次任务的来源权限额度已满，无法继续读取；这不表示没有班级或学生。请在新任务中继续。'}


class BusinessReads:
    def __init__(self, authority, store):
        if authority.site != store.site:
            raise PermissionError('Business reader site mismatch')
        self.authority, self.store = authority, store

    def _active(self, claim):
        if not isinstance(claim, WorkerClaim):
            gates._deny()
        gates._identity(claim.identity, self.authority.site)
        state = self.store.binding_state(claim)
        if (state.get('site') != claim.identity.site or state.get('owner') != claim.identity.owner
                or state.get('task_id') != claim.identity.task_id or state.get('mode') != 'business'
                or state.get('status') != 'running' or state.get('cancel_requested') not in (False, 0, '0')):
            gates._deny()

    def _page_budget(self, claim, base, requested, per_row, reserve=0):
        old = self.store.required_scopes(claim.identity)
        union = {_scope_key(value) for value in (*old, *base)}
        remaining = MAX_SCOPES - len(union) - reserve
        # Reserve one lookahead's complete dependency set, not just public rows.
        return max(0, min(requested, remaining // per_row - 1))

    def dispatch(self, claim, tool, arguments):
        args = _arguments(tool, arguments)
        self._active(claim)
        if tool == 'scene_bootstrap':
            return self._bootstrap(claim, args)
        if tool == 'meal_read':
            return self._meals(claim, args)
        return self._students(claim, args)

    def _meals(self, claim, args):
        # The reader owns complete same-query registration. No raw legacy
        # get_meals document or permission-bypassing convenience result escapes.
        try:
            result = self.authority.read_meals(self.store, claim, **args)
        except gates.MealReadScopeLimit as error:
            self._active(claim)
            return {'available': False, 'error': 'scope_budget_exhausted',
                    'retry': 'use_business_view' if error.single_read else 'new_task',
                    'message': ('本班完整核对所需来源超过读取额度，不能用部分名单核餐，请在原业务视图核对。'
                                if error.single_read else '本次任务来源额度不足，无法完整读取本班核餐名单；请在新任务中读取。')}
        self._active(claim)
        selection = {'view': 'meal_counts', 'group': args['group'], 'day': args['day']}
        context = self.store.task(claim.identity)['context']
        meal = context.get('meal') or context.get('selection', {}).get('meal') or 'lunch'
        from tongjianyun.business_agent_tools import MEALS
        if not isinstance(meal, str) or meal not in MEALS:
            raise ValueError('Trusted task context has no valid meal selection')
        selection['meal'] = meal
        self.store.register_authority(claim, {'kind': 'view', 'selection': selection})
        self._active(claim)
        self.store.emit(claim, {'kind': 'view', 'version': 1, 'selection': selection, 'title': '核对本班用餐'})
        self._active(claim)
        return result  # Keep the existing meal_read projection contract unchanged.

    def _bootstrap(self, claim, args):
        base = (gates._capability(gates.SCENE), gates._capability(gates.GROUPS))
        size = self._page_budget(claim, base, args['page_size'], 2, reserve=3)
        if not size:
            self._active(claim)
            return _budget_result()
        def read():
            from tongjianyun.attendance_scope import allowed_groups
            from tongjianyun.scene_access import require_scene_account
            from tongjianyun.meal_scene import business_day, meal_key
            gates._account(claim.identity.owner, claim.identity.site)
            require_scene_account()
            day, meal = str(business_day(args['day'])), meal_key(args.get('meal', 'lunch'))
            try:
                gates._projection(gates.GROUPS)
            except (frappe.PermissionError, frappe.DoesNotExistError):
                return ({'available': True, 'day': day, 'meal': meal, 'groups_available': False,
                    'page_count': None, 'visible_group_count': None, 'has_more': None,
                    'scope': '当前账号没有班级发现所需的原生字段或单据权限；不能推断班级数为零',
                    'navigation': [], 'supported_tools': ['scene_bootstrap']},
                    gates.ReadSet((gates._capability(gates.SCENE),)))
            names = allowed_groups()  # Native identity links are authorization, not exposed employee data.
            filters = [['Student Group', 'disabled', '=', 0], ['Student Group', 'name', 'in', names]]
            if args.get('after'):
                filters.append(['Student Group', 'name', '>', args['after']])
            rows = frappe.get_list('Student Group', filters=filters,
                fields=['name', 'student_group_name', 'academic_year'], order_by='name asc',
                limit_page_length=size + 1) if names else []
            if len(rows) > size + 1 or len({r.name for r in rows}) != len(rows) or any(r.name not in names for r in rows):
                raise ValueError('Unexpected native class projection')
            dependencies = list(base)
            navigation = []
            supported = ['scene_bootstrap']
            for capability, tool, label in ((gates.ROSTER, 'class_students_read', '班级学生'),
                                             (gates.ATTENDANCE, 'classroom_read', '本班点名'),
                                             (gates.MEALS, 'meal_read', '本班用餐')):
                try:
                    gates._projection(capability)
                except (frappe.PermissionError, frappe.DoesNotExistError):
                    continue
                dependencies.append(gates._capability(capability))
                supported.append(tool)
                navigation.append({'label': label, 'tool': tool, 'requires_group': True})
            for row in rows:  # Includes lookahead used by has_more, not just the displayed page.
                dependencies.extend((gates._class(row.name), gates._read('Student Group', row.name)))
            page = rows[:size]
            return ({'available': True, 'groups_available': True, 'day': day, 'meal': meal,
                'groups': [{'group': r.name, 'label': r.student_group_name or r.name,
                            'academic_year': r.academic_year or None} for r in page],
                'page_count': len(page), 'has_more': len(rows) > size,
                'next_after': page[-1].name if len(rows) > size else None,
                'visible_group_count': len(page) if not args.get('after') and len(rows) <= size else None,
                'scope': '当前账号通过原生任教与单据权限可见的启用班级，不是全园班级总数',
                'budget_limited': size < args['page_size'],
                'navigation': navigation, 'supported_tools': supported},
                gates.ReadSet(tuple(dependencies)))
        result, sources = self.authority.run_check(claim.identity.owner, read)
        self.authority.register_read(self.store, claim, sources)
        self._active(claim)
        return result

    def _students(self, claim, args):
        group = args['group']
        # The browser gets its native class view (with its own independent UI
        # pagination), not the model's opaque scan cursor or a raw document.
        selection = {'view': 'class_students', 'group': group, 'offset': 0}
        base = (gates._capability(gates.SCENE), gates._capability(gates.ROSTER), gates._class(group),
                gates._read('Student Group', group), {'kind': 'view', 'selection': selection})
        size = self._page_budget(claim, base, args['page_size'], 1)
        if not size:
            self._active(claim)
            return _budget_result()
        start, revision = _decode_cursor(args['cursor']) if args.get('cursor') else (0, None)
        def read():
            from tongjianyun import classroom
            gates._account(claim.identity.owner, claim.identity.site)
            gates._projection(gates.ROSTER)
            doc = classroom._scope(group)
            captured = []
            raw = classroom._roster_page(doc, start=start, revision=revision, page_size=size,
                                          source_observer=captured.append)
            if (len(captured) != 1 or not isinstance(captured[0], classroom.RosterPageReadSources)
                    or captured[0].group != group or captured[0].revision != raw['revision']
                    or type(captured[0].students) is not tuple or len(captured[0].students) > size + 1
                    or not {r['student'] for r in raw['rows']} <= set(captured[0].students)):
                gates._deny()
            dependencies = (*base, *(gates._read('Student', name) for name in captured[0].students))
            return ({'available': True, 'group': group, 'label': doc.student_group_name or group,
                'students': raw['rows'], 'page_count': len(raw['rows']),
                'visible_class_count': raw['visible_class_count'], 'has_more': raw['has_more'],
                'next_cursor': _encode_cursor(raw['next_index'], raw['revision']) if raw['next_index'] is not None else None,
                'scan_limited': raw['scan_limited'], 'budget_limited': size < args['page_size'],
                'scope': '本班有效且当前账号有权查看的启用学生；当前读取，不是历史、出勤、就餐或全园人数'},
                gates.ReadSet(dependencies))
        result, sources = self.authority.run_check(claim.identity.owner, read)
        self.authority.register_read(self.store, claim, sources)
        self._active(claim)
        self.store.emit(claim, {'kind': 'view', 'version': 1, 'selection': selection, 'title': '班级学生名单'})
        self._active(claim)
        return {**result, 'display_requested': True,
                'display_note': '已请求左侧打开本班原生名单，浏览器会重新核权读取；不代表已经加载。'}
