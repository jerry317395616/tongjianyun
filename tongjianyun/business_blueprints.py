"""Reviewable, data-only business extensions for the conversation canvas.

Proposals are private File records, not executable model output. Activation is a
separate POST from the visible preview, bound to its digest. Existing DocTypes,
roles and records are never overwritten. Complex integrations remain source
changes with tests, rather than Server Scripts or arbitrary SQL.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid

import frappe
from frappe.model.base_document import RESERVED_KEYWORDS
from frappe.model.document import Document

PREFIX = 'Tongjianyun Extension '
FILE_PREFIX = 'business-blueprint-'
TYPES = {'Data', 'Small Text', 'Date', 'Datetime', 'Int', 'Float', 'Currency', 'Check', 'Select', 'Link'}
RESERVED = {'name', 'owner', 'creation', 'modified', 'modified_by', 'docstatus', 'idx', 'doctype',
            'parent', 'parenttype', 'parentfield', 'amended_from', 'title', 'flags', 'meta'}
RESERVED |= set(dir(Document)) | set(RESERVED_KEYWORDS)
BLOCKED_LINKS = {'User', 'Role', 'Has Role', 'DocType', 'DocField', 'DocPerm', 'File',
                 'Server Script', 'Client Script', 'Custom Field', 'Property Setter'}
MAX_BYTES = 32768
MAX_KEY = 61 - len(PREFIX)  # MariaDB table name is "tab" + DocType, at most 64.


def _text(value, label, maximum=140, optional=False):
    if optional and value in (None, ''):
        return ''
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError('无效的' + label)
    return value.strip()


def validate_spec(value):
    """Pure schema validation. No expressions, field code, defaults or HTML."""
    if isinstance(value, str):
        if len(value.encode('utf-8')) > MAX_BYTES:
            raise ValueError('业务方案过大')
        value = json.loads(value)
    if not isinstance(value, dict) or set(value) - {'key', 'title', 'description', 'fields'}:
        raise ValueError('业务方案只接受 key、title、description、fields')
    key = value.get('key')
    if not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]{2,' + str(MAX_KEY - 1) + '}', key):
        raise ValueError(f'业务键须为 3–{MAX_KEY} 位小写字母、数字或下划线')
    clean = {'key': key, 'title': _text(value.get('title'), '业务名称', 80),
             'description': _text(value.get('description'), '业务说明', 1000), 'fields': []}
    fields = value.get('fields')
    if not isinstance(fields, list) or not 1 <= len(fields) <= 24:
        raise ValueError('业务需包含 1–24 个字段')
    names = set(RESERVED)
    for field in fields:
        if not isinstance(field, dict) or set(field) - {'fieldname', 'label', 'fieldtype', 'reqd', 'options'}:
            raise ValueError('字段含不支持的设置，不能包含代码、权限或计算表达式')
        name, kind = field.get('fieldname'), field.get('fieldtype')
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', name) or name in names:
            raise ValueError('字段名称重复、保留或无效')
        if not isinstance(kind, str) or kind not in TYPES:
            raise ValueError('不支持的字段类型；复杂表格、自动计算或审批请走源码扩展')
        if field.get('reqd', 0) not in (0, 1, False, True):
            raise ValueError('必填标记无效')
        names.add(name)
        item = {'fieldname': name, 'label': _text(field.get('label'), '字段标签', 80),
                'fieldtype': kind, 'reqd': int(bool(field.get('reqd', 0)))}
        options = field.get('options', '')
        if kind == 'Select':
            if not isinstance(options, str):
                raise ValueError('选项须为逐行文本')
            values = options.splitlines()
            if not 1 <= len(values) <= 30 or len(set(values)) != len(values):
                raise ValueError('选项须为 1–30 项且不能重复')
            item['options'] = '\n'.join(_text(v, '选项', 80) for v in values)
        elif kind == 'Link':
            item['options'] = _text(options, '关联业务')
            if item['options'] in BLOCKED_LINKS:
                raise ValueError('不能关联系统权限、脚本或配置类型')
        elif options:
            raise ValueError('该字段不接受选项或表达式')
        clean['fields'].append(item)
    if len(json.dumps(clean, ensure_ascii=False).encode('utf-8')) > MAX_BYTES:
        raise ValueError('业务方案过大')
    return clean


def revision(spec):
    return hashlib.sha256(json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def doctype_name(spec):
    return PREFIX + spec['key']


def _access():
    from tongjianyun.meal_chat import require_chat_access
    require_chat_access()


def _validate_links(spec):
    from tongjianyun.frappe_project_views import module_apps, _doctype
    modules = module_apps()
    for field in spec['fields']:
        if field['fieldtype'] == 'Link':
            _doctype(field['options'], modules)


def _load(proposal_id):
    _access()
    file = frappe.get_doc('File', _text(proposal_id, '业务方案编号'))
    file.check_permission('read')
    # Even system managers only activate their own proposal. CLI takes the owner
    # from the task, never a caller-provided actor argument.
    if (file.owner != frappe.session.user or not file.is_private
            or not re.fullmatch(r'business-blueprint-[0-9a-f]{32}\.json', file.file_name or '')
            or not str(file.file_url or '').startswith('/private/files/')):
        raise frappe.PermissionError('这不是当前用户的私有业务方案。')
    raw = file.get_content()
    if len(raw) > MAX_BYTES * 2:
        frappe.throw('业务方案文件过大。')
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get('version') != 1 or payload.get('site') != frappe.local.site or payload.get('actor') != frappe.session.user:
        raise frappe.PermissionError('业务方案的站点或创建者不匹配。')
    return validate_spec(payload.get('spec'))


def _definition(spec):
    return {'doctype': 'DocType', 'name': doctype_name(spec), 'module': 'Tongjianyun',
            'custom': 1, 'is_submittable': 0, 'track_changes': 1, 'autoname': 'hash',
            'title_field': 'title', 'search_fields': 'title',
            'description': 'Business blueprint ' + revision(spec) + '\n' + spec['title'] + '：' + spec['description'],
            'fields': [{'fieldname': 'title', 'label': '名称', 'fieldtype': 'Data', 'reqd': 1,
                        'in_list_view': 1},
                       *[{**field, 'in_list_view': int(index < 3)} for index, field in enumerate(spec['fields'])]],
            'permissions': [{'role': 'System Manager', 'read': 1, 'write': 1, 'create': 1,
                             'report': 1, 'export': 1, 'print': 1, 'email': 0, 'delete': 0}]}


def _state(spec):
    name = doctype_name(spec)
    if not frappe.db.exists('DocType', name):
        return 'proposed'
    # Frappe commits metadata before MariaDB DDL. Metadata alone may therefore
    # survive a failed CREATE/ALTER and must never count as a usable business.
    if not frappe.db.table_exists(name):
        return 'conflict'
    meta = frappe.get_meta(name, cached=False)
    # Do not claim an unrelated pre-existing type is the activated proposal.
    expected = _definition(spec)
    actual_fields = [{k: f.get(k) or (0 if k in {'reqd', 'in_list_view'} else '')
                      for k in ('fieldname', 'label', 'fieldtype', 'reqd', 'options', 'in_list_view')}
                     for f in meta.fields]
    expected_fields = [{k: f.get(k) or (0 if k in {'reqd', 'in_list_view'} else '')
                        for k in ('fieldname', 'label', 'fieldtype', 'reqd', 'options', 'in_list_view')}
                       for f in expected['fields']]
    required_columns = {'name', 'owner', 'creation', 'modified', 'modified_by', 'docstatus', 'idx'} | {
        field['fieldname'] for field in expected['fields']}
    if not required_columns.issubset(set(frappe.db.get_table_columns(name))):
        return 'conflict'
    permissions = list(meta.permissions or [])
    if len(permissions) != 1 or permissions[0].get('role') != 'System Manager':
        return 'conflict'
    for key in ('read', 'write', 'create', 'report', 'export', 'print', 'email', 'delete',
                'submit', 'cancel', 'amend', 'if_owner', 'permlevel'):
        if int(permissions[0].get(key) or 0) != int(expected['permissions'][0].get(key) or 0):
            return 'conflict'
    return 'active' if (meta.custom and meta.module == 'Tongjianyun' and meta.track_changes
                        and not meta.is_submittable and meta.autoname == 'hash' and meta.title_field == 'title'
                        and meta.search_fields == 'title'
                        and meta.description == expected['description'] and actual_fields == expected_fields) else 'conflict'


def preview(proposal_id):
    spec = _load(proposal_id)
    _validate_links(spec)
    state = _state(spec)
    can_activate = state == 'proposed' and bool(frappe.has_permission('DocType', 'create'))
    warnings = ['启用将新增独立业务数据表；不会修改已有类型或自动生成业务记录。',
                '初始仅系统管理员可用；保留修改历史，不授予删除权限。',
                '这是登记类业务：不自动扣库存、付款、发送消息或建立专业审批规则。']
    if state == 'conflict':
        warnings.append('同名业务已经存在且与方案不一致，不能覆盖。请先核对原业务或换业务键。')
    if state == 'proposed' and not can_activate:
        warnings.append('当前账号没有创建业务类型的权限，无法启用。')
    component = {'type': 'business_blueprint', 'proposal_id': proposal_id, 'revision': revision(spec),
                 'title': spec['title'], 'description': spec['description'], 'fields': _definition(spec)['fields'],
                 'state': state, 'doctype': doctype_name(spec), 'warnings': warnings, 'can_activate': can_activate}
    return {'title': '新业务方案：' + spec['title'], 'subtitle': '先核对字段，再决定是否启用',
            'components': [component], 'source': '当前用户私有方案；未启用不改变数据库结构',
            'actions': ([{'label': '打开业务', 'selection': {'view': 'frappe_doctype', 'doctype': doctype_name(spec)}}]
                        if state == 'active' else []),
            'summary': {'proposal_id': proposal_id, 'revision': revision(spec), 'state': state,
                        'title': spec['title'], 'doctype': doctype_name(spec), 'can_activate': can_activate}}


def propose(spec):
    _access()
    spec = validate_spec(spec)
    _validate_links(spec)
    if frappe.db.exists('DocType', doctype_name(spec)):
        frappe.throw('同名业务已经存在；请复用原业务，不创建副本。')
    payload = {'version': 1, 'site': frappe.local.site, 'actor': frappe.session.user, 'spec': spec}
    file = frappe.get_doc({'doctype': 'File', 'file_name': FILE_PREFIX + uuid.uuid4().hex + '.json',
                          'is_private': 1, 'content': json.dumps(payload, ensure_ascii=False),
                          'folder': 'Home'}).insert()
    return {'proposal_id': file.name, 'revision': revision(spec), 'doctype': doctype_name(spec), 'state': 'proposed'}


@frappe.whitelist(methods=['POST'])
def activate(proposal_id, revision):
    """Explicit preview confirmation; never called automatically by the agent."""
    spec = _load(proposal_id)
    expected = globals()['revision'](spec)
    if not isinstance(revision, str) or not hmac.compare_digest(revision, expected):
        frappe.throw('业务方案已变化，请重新预览后确认。')
    frappe.has_permission('DocType', 'create', throw=True)
    _validate_links(spec)
    from tongjianyun.extension_policy import evaluate_extension_change
    if not evaluate_extension_change('add-custom-business', explicitly_confirmed=True).allowed:
        frappe.throw('当前策略不允许启用新业务。')
    lock = 'business-blueprint:' + frappe.local.site + ':' + doctype_name(spec)
    with frappe.cache().lock(lock, timeout=120, blocking_timeout=5):
        state = _state(spec)
        if state == 'conflict':
            frappe.throw('同名业务已存在且结构不同，不能覆盖。')
        if state == 'proposed':
            doc = frappe.get_doc(_definition(spec)).insert()
            doc.add_comment('Comment', text='由统一业务场景启用。私有方案：' + proposal_id + '；校验：' + expected)
            # Schema DDL is not reliably transactional; verify before reporting
            # success. A retry checks the exact existing schema, never drops it.
            if _state(spec) != 'active':
                frappe.throw('结构核验未通过，不能宣布启用成功。请管理员检查，不要重复创建。')
        frappe.db.commit()
    return {'state': 'active', 'doctype': doctype_name(spec), 'proposal_id': proposal_id,
            'selection': {'view': 'frappe_doctype', 'doctype': doctype_name(spec)}}


def propose_for_task(task_id, spec):
    from tongjianyun.meal_chat import TaskStore, SESSION_RE, ACTIVE
    from tongjianyun.meal_views import publish_for_task
    if not SESSION_RE.fullmatch(str(task_id or '')):
        raise ValueError('Invalid task id')
    store = TaskStore()
    task = store.read(task_id)
    if task.get('status') not in ACTIVE or task.get('cancel_requested') == '1':
        raise ValueError('Task is no longer active')
    actor = frappe.session.user
    try:
        frappe.set_user(task['owner'])
        result = propose(spec)
        current = store.read(task_id)
        if current.get('status') not in ACTIVE or current.get('cancel_requested') == '1':
            frappe.db.rollback()
            raise ValueError('Task is no longer active')
        # SSE consumer runs on another connection; make the proposal visible
        # before emitting its view. A committed proposal is not an active type.
        frappe.db.commit()
        published = publish_for_task(task_id, {'view': 'business_blueprint', 'proposal_id': result['proposal_id']})
        return {**result, 'display_requested': bool(published.get('display_requested', published.get('displayed'))),
                'answer': '方案已保存并请求展示，等待用户在左侧确认启用；尚未创建业务类型。'}
    finally:
        frappe.set_user(actor)
