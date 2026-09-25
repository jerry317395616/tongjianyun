"""Finite, source-registered discovery of this actor's installed Frappe business.

Only entry metadata is returned, never native-view summaries, records, routes,
capabilities, HTML or project paths. The trusted worker supplies its own claim;
model arguments cannot choose a user/site. Publishing requests a supported
selection: the browser must independently read it under the current user.

The original catalog reader owns metadata/permission filtering. A page and its
lookahead come from ONE such result. Only those entries contribute to this
page's values/has_more and all receive persistent DocType read scopes. No global
catalog digest/count or hidden entry identifiers are put in a cursor. Keyset
pagination is a fresh read, not a snapshot across permission/schema changes.
"""
from __future__ import annotations

import base64
from datetime import date
import hashlib
import json
import re

from tongjianyun.business_agent_tasks import WorkerClaim, MAX_SCOPES

DEFAULT_PAGE = 20
MAX_PAGE = 30
MAX_CATALOG_ENTRIES = 20000
NATIVE_VIEWS = frozenset({'frappe_catalog', 'frappe_doctype', 'frappe_document', 'frappe_new'})
MEALS = frozenset({'breakfast', 'morning_snack', 'lunch', 'afternoon_snack', 'dinner'})
TOOL_INSTRUCTIONS = {
    'business_catalog_read': (
        'business_catalog_read 参数为 {app?:应用名,module?:模块名,keyword?:关键字,cursor?:上页next_cursor,page_size?:1到30}。'
        '从当前站点实际安装的Frappe应用中，按当前账号原权限发现可用业务，不局限于班级。'
        '结果只是非控制类DocType入口元数据，page_count或visible_entry_count不是单据数、人数或金额。'
        '只有首个完整页的visible_entry_count非null时才可报告当前筛选可见入口总数。'
        '用next_cursor继续，筛选保持不变；跨页为实时读取，不保证目录快照。'
        'scope_budget_exhausted不是空目录，应在新任务继续。使用返回selection调用business_view打开入口；'
        '报表、独立Page/Workspace和服务器项目暂不由此工具开放。'),
    'business_view': (
        'business_view 参数仅为 {selection:{view:"frappe_catalog"|"frappe_doctype"|"frappe_document"|"frappe_new",...}}。'
        '优先使用目录返回的selection，不猜业务编号。目录可带app/module/keyword/kind:"doctype"/offset；'
        'doctype/new必须带doctype，document必须带doctype和已有document；可带day/meal但不把膳食日期当业务筛选。'
        '服务端保留原读取、行权限及新建权限。只请求左侧打开原生目录/列表/详情/新建表单，'
        '不创建、编辑、审批或提交单据，也不代表浏览器已加载；不要把display_requested当业务成功。'),
}


def _services():
    # Lazy imports keep finite schema/cursor tests independent of a Frappe
    # installation. Production always uses these existing native implementations.
    import frappe
    from tongjianyun import business_agent_authority, frappe_project_views
    return frappe, business_agent_authority, frappe_project_views


def _text(value, limit=140):
    if (not isinstance(value, str) or not 1 <= len(value) <= limit or value != value.strip()
            or any(ord(character) < 32 for character in value)):
        raise ValueError('Invalid bounded catalog text')
    return value


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def _arguments(tool, value):
    if type(value) is not dict:
        raise ValueError('Expected finite catalog arguments')
    try:
        encoded = _json(value)
        if len(encoded.encode()) > 8192:
            raise ValueError('Catalog arguments exceed bound')
    except (TypeError, UnicodeError, RecursionError) as error:
        raise ValueError('Catalog arguments must be finite JSON') from error
    args = json.loads(encoded)
    if tool == 'business_catalog_read':
        if set(args) - {'app', 'module', 'keyword', 'cursor', 'page_size'}:
            raise ValueError('Unexpected catalog argument')
        size = args.setdefault('page_size', DEFAULT_PAGE)
        if type(size) is not int or not 1 <= size <= MAX_PAGE:
            raise ValueError('Invalid catalog page size')
        for name in ('app', 'module', 'keyword'):
            if name in args:
                _text(args[name])
        if 'cursor' in args:
            _decode_cursor(args['cursor'], _filter_digest(args))
    elif tool == 'business_view':
        if set(args) != {'selection'}:
            raise ValueError('Only a business selection may be published')
        choice = args['selection']
        if type(choice) is not dict or not isinstance(choice.get('view'), str) or choice['view'] not in NATIVE_VIEWS:
            raise ValueError('Native business view is not supported')
        fields = {'frappe_catalog': {'app', 'module', 'keyword', 'kind', 'offset'},
                  'frappe_doctype': {'doctype'}, 'frappe_document': {'doctype', 'document'},
                  'frappe_new': {'doctype'}}[choice['view']]
        if set(choice) - ({'view', 'day', 'meal'} | fields):
            raise ValueError('Unsupported native selection field')
        required = {'doctype', 'document'} if choice['view'] == 'frappe_document' else ({'doctype'} if choice['view'] != 'frappe_catalog' else set())
        if not required <= set(choice):
            raise ValueError('Select an existing native business entry')
        for key in set(choice) - {'view', 'day', 'meal', 'offset'}:
            _text(choice[key])
        if 'day' in choice:
            if not isinstance(choice['day'], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', choice['day']):
                raise ValueError('Invalid business date')
            date.fromisoformat(choice['day'])
        if 'meal' in choice and (not isinstance(choice['meal'], str) or choice['meal'] not in MEALS):
            raise ValueError('Invalid meal context')
        if 'offset' in choice and (type(choice['offset']) is not int or not 0 <= choice['offset'] <= 100000):
            raise ValueError('Invalid catalog offset')
        if choice['view'] == 'frappe_catalog':
            if choice.get('kind', 'doctype') != 'doctype':
                raise ValueError('Only ordinary DocType entries are audited here')
            choice['kind'] = 'doctype'
    else:
        raise ValueError('Unknown finite catalog tool')
    return args


def _filter_digest(arguments):
    return hashlib.sha256(_json({key: arguments[key] for key in ('app', 'module', 'keyword') if key in arguments}).encode()).hexdigest()


def _encode_cursor(key, filters):
    return base64.urlsafe_b64encode(_json({'v': 1, 'after': list(key), 'filters': filters}).encode()).decode().rstrip('=')


def _decode_cursor(value, filters):
    _text(value, 1024)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('Invalid catalog cursor')
    try:
        raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
        cursor = json.loads(raw)
        if (type(cursor) is not dict or set(cursor) != {'v', 'after', 'filters'}
                or type(cursor['v']) is not int or cursor['v'] != 1 or cursor['filters'] != filters
                or type(cursor['after']) is not list or len(cursor['after']) != 3):
            raise ValueError('Invalid catalog cursor binding')
        key = tuple(_text(value) for value in cursor['after'])
        if _encode_cursor(key, filters) != value:
            raise ValueError('Noncanonical catalog cursor')
        return key
    except (ValueError, UnicodeError, TypeError, KeyError) as error:
        raise ValueError('Invalid or differently filtered catalog cursor') from error


def _budget_result():
    return {'available': False, 'error': 'scope_budget_exhausted', 'retry': 'new_task',
            'message': '本次任务来源权限额度不足，无法完整登记这一页；这不是空目录，请在新任务继续。'}


class BusinessCatalog:
    def __init__(self, authority, store):
        if authority.site != store.site:
            raise PermissionError('Catalog authority belongs to a different site')
        self.authority, self.store = authority, store

    def _active(self, claim):
        if not isinstance(claim, WorkerClaim) or claim.identity.site != self.authority.site:
            raise PermissionError('A trusted same-site worker claim is required')
        expected = {'site': claim.identity.site, 'owner': claim.identity.owner, 'task_id': claim.identity.task_id,
                    'mode': 'business', 'status': 'running', 'cancel_requested': '0'}
        if self.store.binding_state(claim) != expected:
            raise PermissionError('The business task is no longer active')

    def _budget(self, claim, sources):
        old = self.store.required_scopes(claim.identity)
        return MAX_SCOPES - len({_json(scope) for scope in (*old, *sources)})

    def _context(self, claim):
        context = self.store.task(claim.identity)['context']
        return {key: context[key] for key in ('day', 'meal') if context.get(key)}

    def dispatch(self, claim, tool, arguments):
        args = _arguments(tool, arguments)
        self._active(claim)
        if tool == 'business_catalog_read':
            return self._catalog(claim, args)
        return self._view(claim, args['selection'])

    def _canonical(self, claim, choice):
        _, gates, native = _services()
        context = self._context(claim)
        def resolve():
            gates._account(claim.identity.owner, claim.identity.site)
            return {'view': choice['view'], **native.selection(choice, context.get('day'), context.get('meal', 'lunch'))}
        return self.authority.run_check(claim.identity.owner, resolve)

    def _catalog(self, claim, args):
        frappe, gates, native = _services()
        choice = self._canonical(claim, {'view': 'frappe_catalog', 'kind': 'doctype',
            **{key: args[key] for key in ('app', 'module', 'keyword') if key in args}})
        base = (*self.authority.view_scopes(claim.identity, choice), gates._capability(gates.SCENE))
        # One DocType scope per entry, plus the complete has_more lookahead.
        size = max(0, min(args['page_size'], self._budget(claim, base) - 1))
        if not size:
            self._active(claim)
            return _budget_result()
        filters = _filter_digest(args)
        after = _decode_cursor(args['cursor'], filters) if args.get('cursor') else None
        def read():
            gates._account(claim.identity.owner, claim.identity.site)
            gates._projection(gates.CATALOG)
            modules = native.module_apps()
            if choice.get('app'):
                if choice['app'] not in frappe.get_installed_apps():
                    raise PermissionError('The requested application is not installed on this site')
                modules = {name: app for name, app in modules.items() if app == choice['app']}
            if choice.get('module'):
                if choice['module'] not in modules:
                    raise PermissionError('The requested module is not available to this actor')
                modules = {choice['module']: modules[choice['module']]}
            # Reuse native metadata selection, installed-module/user filters and
            # per-type permissions; do not invent a separate module inventory.
            rows = native.catalog_entries(choice, modules)
            if type(rows) is not list or len(rows) > MAX_CATALOG_ENTRIES:
                raise ValueError('Native catalog exceeds the bounded metadata reader')
            visible, names = [], set()
            for row in rows:
                if type(row) is not dict or row.get('kind') != 'doctype':
                    raise ValueError('Unexpected native catalog entry type')
                name, module = _text(row.get('name')), _text(row.get('module'))
                if name in names or module not in modules:
                    raise ValueError('Inconsistent native catalog source')
                names.add(name)
                if name in gates.CONTROL_DOCTYPES:
                    continue  # Never expose control types, even for admin business tasks.
                key = (_text(modules[module]), module, name)
                if after is not None and key <= after:
                    continue
                visible.append((key, row))
            visible.sort(key=lambda value: value[0])
            observed = visible[:size + 1]
            dependencies = list(base)
            for key, row in observed:
                meta = gates._doctype(key[2], ['read'])
                if meta.module != key[1]:
                    raise PermissionError('Native entry module changed during the read')
                dependencies.append(gates._read(key[2]))
            page = observed[:size]
            entries = [{'app': key[0], 'module': key[1], 'doctype': key[2], 'title': _text(row['title'], 240),
                        'selection': native.entry_selection('doctype', key[2], choice)} for key, row in page]
            has_more = len(observed) > size
            return ({'available': True, 'entries': entries, 'page_count': len(entries), 'has_more': has_more,
                'next_cursor': _encode_cursor(page[-1][0], filters) if has_more else None,
                'visible_entry_count': len(entries) if after is None and not has_more else None,
                'budget_limited': size < args['page_size'],
                'scope': '当前站点已安装且当前账号可读的非控制类DocType入口；不是业务记录、人员或金额统计',
                'pagination': '实时读取，不保证跨页目录快照；权限或模块改变时重新查询',
                'excluded_kinds': ['report', 'page', 'workspace', 'project']}, gates.ReadSet(tuple(dependencies)))
        result, sources = self.authority.run_check(claim.identity.owner, read)
        self.authority.register_read(self.store, claim, sources)
        self._active(claim)
        return result

    def _view(self, claim, selection):
        _, gates, native = _services()
        choice = self._canonical(claim, selection)
        # Admission is independently native: doctype uses original permissions;
        # a document uses BOTH original document and list/row permission checks.
        dependencies = (*self.authority.view_scopes(claim.identity, choice), gates._capability(gates.SCENE))
        if choice['view'] == 'frappe_new':
            def validate_new():
                gates._account(claim.identity.owner, claim.identity.site)
                meta = gates._doctype(choice['doctype'], ['read', 'create'])
                if meta.issingle or meta.name == 'Tongjianyun Recipe':
                    raise PermissionError('Use the existing settings or weekly recipe workflow')
            self.authority.run_check(claim.identity.owner, validate_new)
        if self._budget(claim, dependencies) < 0:
            self._active(claim)
            return _budget_result()
        self.authority.register_read(self.store, claim, gates.ReadSet(tuple(dependencies)))
        self._active(claim)
        title = {'frappe_catalog': '可用业务', 'frappe_doctype': '业务单据',
                 'frappe_document': '业务详情', 'frappe_new': '新建业务表单'}[choice['view']]
        self.store.emit(claim, {'kind': 'view', 'version': 1, 'selection': choice, 'title': title})
        self._active(claim)
        return {'available': True, 'selection': choice, 'display_requested': True,
                'executed_business_operation': False,
                'display_note': '已请求左侧按当前账号权限打开原生业务视图；未核实浏览器加载，未创建、编辑、提交或执行任何业务操作。'}
