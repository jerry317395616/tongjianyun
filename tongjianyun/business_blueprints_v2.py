"""Controlled line-item/review extensions; no model code or evaluated expressions.

The manifest lives in owned DocType metadata, independently of its proposer's
private File. Every write verifies the complete schema and workflow. A partial
DDL install is a conflict, never an invitation to overwrite or silently repair.
"""
from __future__ import annotations

import base64
import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import frappe

from tongjianyun import business_blueprints as bp

MARKER = 'Business blueprint v2 '
ROW_PREFIX = 'TGY Extension Row '
NUMERIC = {'Int', 'Float', 'Currency'}
STATES = [('扩展·草稿', 0), ('扩展·待复核', 0), ('扩展·退回', 0), ('扩展·通过', 1), ('扩展·撤销', 2)]
TRANSITIONS = [(0, '扩展·送审', 1, 1), (2, '扩展·重新送审', 1, 1),
               (1, '扩展·撤回送审', 0, 1), (1, '扩展·退回修改', 2, 0),
               (1, '扩展·复核通过', 3, 0), (3, '扩展·撤销通过', 4, 0)]
FIELD_KEYS = ('fieldname', 'label', 'fieldtype', 'reqd', 'options', 'in_list_view',
              'read_only', 'allow_on_submit', 'default', 'hidden', 'no_copy', 'precision',
              'depends_on', 'mandatory_depends_on', 'read_only_depends_on', 'fetch_from',
              'permlevel', 'unique', 'set_only_once')
PERM_KEYS = ('role', 'read', 'write', 'create', 'report', 'export', 'print', 'email', 'delete',
             'submit', 'cancel', 'amend', 'if_owner', 'permlevel', 'share')


def validate_spec(value):
    if set(value) - {'version', 'key', 'title', 'description', 'fields', 'tables', 'calculations', 'workflow'}:
        raise ValueError('复杂方案含不支持的设置')
    clean = bp.validate_spec({k: value.get(k) for k in ('key', 'title', 'description', 'fields')})
    clean['version'] = 2
    names = set(bp.RESERVED) | {'workflow_state'} | {f['fieldname'] for f in clean['fields']}
    if 'workflow_state' in {f['fieldname'] for f in clean['fields']}:
        raise ValueError('workflow_state 由固定复核模板管理')
    tables = value.get('tables', [])
    if not isinstance(tables, list) or len(tables) > 2:
        raise ValueError('最多允许 2 张明细表')
    clean['tables'] = []
    for table in tables:
        if not isinstance(table, dict) or set(table) - {'fieldname', 'label', 'fields', 'reqd'}:
            raise ValueError('明细表不支持脚本、权限或嵌套表')
        header = bp.validate_spec({**clean_base(clean), 'fields': [{
            'fieldname': table.get('fieldname'), 'label': table.get('label'),
            'fieldtype': 'Data', 'reqd': table.get('reqd', 0)}]})['fields'][0]
        if header['fieldname'] in names:
            raise ValueError('明细表名称重复或保留')
        names.add(header['fieldname'])
        fields = bp.validate_spec({**clean_base(clean), 'fields': table.get('fields')})['fields']
        if len(fields) > 12 or any(f['fieldname'] == 'workflow_state' for f in fields):
            raise ValueError('每张明细表限 1–12 个普通字段')
        clean['tables'].append({k: header[k] for k in ('fieldname', 'label', 'reqd')} | {'fields': fields})
    calculations = value.get('calculations', [])
    if not isinstance(calculations, list) or len(calculations) > 8:
        raise ValueError('最多允许 8 项固定计算')
    fields_by_table = {t['fieldname']: {f['fieldname']: f for f in t['fields']} for t in clean['tables']}
    parent = {f['fieldname']: f for f in clean['fields']}
    outputs, clean['calculations'] = set(), []
    for calc in calculations:
        if not isinstance(calc, dict) or calc.get('op') not in ('multiply', 'sum'):
            raise ValueError('只支持明细乘法与主表汇总，不执行表达式')
        multiply = calc['op'] == 'multiply'
        if set(calc) != ({'op', 'table', 'target', 'sources'} if multiply else {'op', 'table', 'target', 'source'}):
            raise ValueError('计算设置无效')
        table = calc['table']
        if not isinstance(table, str) or table not in fields_by_table:
            raise ValueError('计算引用未知明细表')
        fields = fields_by_table[table]
        target = calc['target']
        targets = fields if multiply else parent
        if not isinstance(target, str) or target not in targets or targets[target]['fieldtype'] != 'Currency' or targets[target]['reqd']:
            raise ValueError('计算结果须为非必填金额字段（固定两位小数）')
        output = (table if multiply else '', target)
        if output in outputs:
            raise ValueError('计算结果重复')
        outputs.add(output)
        sources = calc.get('sources') if multiply else [calc.get('source')]
        if not isinstance(sources, list) or len(sources) != (2 if multiply else 1):
            raise ValueError('乘法须有两个数值来源，汇总须有一个来源')
        if any(not isinstance(s, str) or s not in fields or fields[s]['fieldtype'] not in NUMERIC for s in sources):
            raise ValueError('计算来源必须为同一明细表的数值字段')
        clean['calculations'].append(dict(calc))
    for calc in clean['calculations']:
        if calc['op'] == 'multiply' and any((calc['table'], s) in outputs for s in calc['sources']):
            raise ValueError('乘法不能引用计算结果，防止循环与顺序依赖')
    workflow = value.get('workflow')
    if workflow not in (None, {'template': 'review'}):
        raise ValueError('只支持固定 review 复核模板，不接受权限、条件或动作脚本')
    clean['workflow'] = workflow
    if not clean['tables'] and not workflow:
        raise ValueError('简单登记请使用原登记方案；v2 需明细表或复核模板')
    if len(json.dumps(clean, ensure_ascii=False).encode()) > bp.MAX_BYTES:
        raise ValueError('业务方案过大')
    return clean


def clean_base(spec):
    return {k: spec[k] for k in ('key', 'title', 'description')}


def row_name(spec, table):
    return ROW_PREFIX + hashlib.sha256((spec['key'] + ':' + table['fieldname']).encode()).hexdigest()[:24]


def manifest(spec):
    data = json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return MARKER + bp.revision(spec) + '\n' + base64.urlsafe_b64encode(data).decode()


def definitions(spec):
    computed = {(c['table'] if c['op'] == 'multiply' else '', c['target']) for c in spec['calculations']}
    def fields(items, table=''):
        return [{**f, 'in_list_view': int(i < 4), **(
            {'read_only': 1, 'precision': '2'} if (table, f['fieldname']) in computed else {})}
            for i, f in enumerate(items)]
    result = []
    for table in spec['tables']:
        result.append({'doctype': 'DocType', 'name': row_name(spec, table), 'module': 'Tongjianyun',
            'custom': 1, 'istable': 1, 'editable_grid': 1, 'autoname': '', 'track_changes': 0,
            'description': MARKER + bp.revision(spec) + ':' + table['fieldname'],
            'fields': fields(table['fields'], table['fieldname']), 'permissions': []})
    parent = bp._definition_v1({**clean_base(spec), 'fields': spec['fields']})
    parent['name'] = bp.doctype_name(spec)
    parent['permissions'][0]['share'] = 0
    parent['description'] = manifest(spec)
    parent['fields'] = [parent['fields'][0], *fields(spec['fields']), *[
        {'fieldname': t['fieldname'], 'label': t['label'], 'fieldtype': 'Table', 'options': row_name(spec, t), 'reqd': t['reqd']}
        for t in spec['tables']]]
    if spec['workflow']:
        parent['is_submittable'] = 1
        parent['permissions'][0].update(submit=1, cancel=1)
        parent['fields'].append({'fieldname': 'workflow_state', 'label': '复核状态', 'fieldtype': 'Link',
            'options': 'Workflow State', 'read_only': 1, 'allow_on_submit': 1, 'no_copy': 1,
            'default': STATES[0][0], 'in_list_view': 1})
        # Frappe injects this into submittable types; make it part of the preview
        # and exact schema rather than accepting an unreviewed extra field.
        parent['fields'].append({'fieldname': 'amended_from', 'label': 'Amended From', 'fieldtype': 'Link',
                                 'options': bp.doctype_name(spec), 'read_only': 1, 'no_copy': 1})
    result.append(parent)
    return result


def workflow_definition(spec):
    if not spec['workflow']:
        return None
    return {'doctype': 'Workflow', 'workflow_name': 'TGY Review ' + spec['key'],
        'document_type': bp.doctype_name(spec), 'is_active': 1, 'send_email_alert': 0,
        'workflow_state_field': 'workflow_state', 'states': [
            {'state': state, 'doc_status': str(status), 'allow_edit': 'System Manager', 'send_email': 0}
            for state, status in STATES], 'transitions': [
            {'state': STATES[a][0], 'action': action, 'next_state': STATES[b][0],
             'allowed': 'System Manager', 'allow_self_approval': own, 'send_email_to_creator': 0}
            for a, action, b, own in TRANSITIONS]}


def _values(row, keys):
    return [str(row.get(k) or '') for k in keys]


def _schema_matches(definition):
    name = definition['name']
    if not frappe.db.table_exists(name, cached=False):
        return False
    meta = frappe.get_meta(name, cached=False)
    for key in ('custom', 'istable', 'is_submittable', 'track_changes', 'module', 'autoname',
                'title_field', 'search_fields', 'description', 'is_virtual', 'issingle'):
        if str(meta.get(key) or '') != str(definition.get(key) or ''):
            return False
    if [_values(f, FIELD_KEYS) for f in meta.fields] != [_values(f, FIELD_KEYS) for f in definition['fields']]:
        return False
    if [_values(p, PERM_KEYS) for p in meta.permissions] != [_values(p, PERM_KEYS) for p in definition['permissions']]:
        return False
    columns = {'name', 'owner', 'creation', 'modified', 'modified_by', 'docstatus', 'idx'}
    if definition.get('istable'):
        columns |= {'parent', 'parenttype', 'parentfield'}
    columns |= {f['fieldname'] for f in definition['fields'] if f['fieldtype'] != 'Table'}
    # describe queries this exact physical table; Frappe's general column API
    # caches results and cannot prove that a failed DDL has actually completed.
    return columns.issubset({row[0] for row in frappe.db.describe(name)})


def _workflow_matches(spec):
    expected = workflow_definition(spec)
    existing = frappe.get_all('Workflow', filters={'document_type': bp.doctype_name(spec)}, pluck='name')
    if not expected:
        return not existing
    if existing != [expected['workflow_name']]:
        return False
    actual = frappe.get_doc('Workflow', existing[0])
    keys = ('document_type', 'is_active', 'send_email_alert', 'workflow_state_field', 'override_status')
    if _values(actual, keys) != _values(expected, keys):
        return False
    for kind, keys in [('states', ('state', 'doc_status', 'allow_edit', 'send_email', 'update_field', 'update_value',
        'evaluate_as_expression', 'is_optional_state', 'next_action_email_template')),
        ('transitions', ('state', 'action', 'next_state', 'allowed', 'allow_self_approval', 'send_email_to_creator',
                         'condition', 'transition_tasks'))]:
        if [_values(r, keys) for r in actual.get(kind)] != [_values(r, keys) for r in expected[kind]]:
            return False
    return True


def state(spec):
    expected = definitions(spec)
    exists = [bool(frappe.db.exists('DocType', d['name'])) for d in expected]
    workflows = frappe.db.exists('Workflow', {'document_type': bp.doctype_name(spec)})
    if not any(exists) and not workflows:
        return 'conflict' if any(frappe.db.table_exists(d['name'], cached=False) for d in expected) else 'proposed'
    if not all(exists) or not all(_schema_matches(d) for d in expected) or not _workflow_matches(spec):
        return 'conflict'
    return 'active'


def install(spec, proposal_id):
    workflow = workflow_definition(spec)
    # Check the entire permission bundle before the first nontransactional DDL.
    for doctype in ['DocType', *(['Workflow', 'Workflow State', 'Workflow Action Master'] if workflow else [])]:
        frappe.has_permission(doctype, 'create', throw=True)
    if workflow:
        if frappe.db.exists('Workflow', workflow['workflow_name']):
            frappe.throw('同名复核流程已存在，不能覆盖。')
        for name, kind, key in [(r['state'], 'Workflow State', 'workflow_state_name') for r in workflow['states']] + [
            (r['action'], 'Workflow Action Master', 'workflow_action_name') for r in workflow['transitions']]:
            if not frappe.db.exists(kind, name):
                frappe.get_doc({'doctype': kind, key: name}).insert()
    for definition in definitions(spec):
        doc = frappe.get_doc(definition).insert()
        doc.add_comment('Comment', text='统一场景受控业务；方案：' + proposal_id + '；校验：' + bp.revision(spec))
    if workflow:
        frappe.get_doc(workflow).insert()


def preview_extra(spec):
    workflow = workflow_definition(spec)
    return {'tables': [{**t, 'fields': definitions(spec)[i]['fields']} for i, t in enumerate(spec['tables'])],
            'calculations': spec['calculations'],
            'workflow': {'template': 'review', 'states': workflow['states'], 'transitions': workflow['transitions']} if workflow else None}


def _runtime_spec(doc):
    if doc.doctype.startswith(ROW_PREFIX):
        frappe.throw('明细只能随所属业务单据保存。')
    if not doc.doctype.startswith(bp.OWNED_PREFIXES):
        return None
    meta = frappe.get_meta(doc.doctype, cached=False)
    description = meta.description or ''
    if (doc.doctype.startswith(bp.PREFIX) and description.startswith('Business blueprint ') and not description.startswith(MARKER)
            and not meta.is_submittable and not any(f.fieldtype == 'Table' for f in meta.fields)):
        return None  # Existing v1 registrations have no calculations/workflow.
    try:
        header, encoded = description.split('\n', 1)
        if not header.startswith(MARKER) or len(encoded) > bp.MAX_BYTES * 2:
            raise ValueError('missing manifest')
        spec = bp.validate_spec(json.loads(base64.b64decode(encoded, altchars=b'-_', validate=True)))
        if spec.get('version') != 2 or bp.doctype_name(spec) != doc.doctype or header != MARKER + bp.revision(spec):
            raise ValueError('manifest mismatch')
        if state(spec) != 'active':
            raise ValueError('schema/workflow mismatch')
        return spec
    except (ValueError, TypeError, KeyError, UnicodeError):
        frappe.throw('扩展业务结构、复核流程或清单不完整；请管理员核对，当前不能写入。')


def _number(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number >= Decimal('1000000000000'):
            raise ValueError
        return number
    except (InvalidOperation, ValueError):
        frappe.throw('计算数据须为非负有限数值，且小于一万亿；请补齐数量和单价。')


def _source_number(row, name, fields):
    value = _number(row.get(name))
    if fields[name]['fieldtype'] == 'Int':
        if value != value.to_integral_value():
            frappe.throw('整数计算字段不能填写小数。')
        row.set(name, int(value))
    else:
        # MariaDB stores these numeric fields at 9 decimal places. Normalize
        # operands before computing so persisted values reproduce the result.
        value = _number(value.quantize(Decimal('.000000001'), rounding=ROUND_HALF_UP))
        # Match Frappe's persisted float conversion, including its boundary
        # rounding, before calculating rather than trusting the JSON spelling.
        value = _number(Decimal(str(float(value))))
        row.set(name, float(value))
    return value


def _calculate(doc, spec):
    for table in spec['tables']:
        rows = doc.get(table['fieldname']) or []
        fields = {f['fieldname']: f for f in table['fields']}
        if len(rows) > 500:
            frappe.throw('每张明细表最多 500 行。')
        names = set()
        for row in rows:
            if row.doctype != row_name(spec, table) or (row.name and row.name in names):
                frappe.throw('明细类型或行编号无效。')
            names.add(row.name)
            if row.name:
                stored = frappe.db.get_value(row.doctype, row.name, ['parent', 'parenttype', 'parentfield'], as_dict=True)
                if stored and (stored.parent != doc.name or stored.parenttype != doc.doctype or stored.parentfield != table['fieldname']):
                    frappe.throw('不能引用其他单据的明细行。')
                if not stored and not doc.is_new() and not row.is_new():
                    frappe.throw('明细行已不存在或编号无效，请重新读取单据；不要沿用失效的行编号。')
        for calc in spec['calculations']:
            if calc['op'] != 'multiply' or calc['table'] != table['fieldname']:
                continue
            for row in rows:
                value = _source_number(row, calc['sources'][0], fields) * _source_number(row, calc['sources'][1], fields)
                row.set(calc['target'], float(_number(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)))
    for calc in spec['calculations']:
        if calc['op'] == 'sum':
            fields = {f['fieldname']: f for t in spec['tables'] if t['fieldname'] == calc['table'] for f in t['fields']}
            value = sum((_source_number(row, calc['source'], fields) for row in doc.get(calc['table']) or []), Decimal(0))
            doc.set(calc['target'], float(_number(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)))


def _payload(doc, spec):
    return {**{f['fieldname']: doc.get(f['fieldname']) for f in spec['fields']}, 'title': doc.title,
            **{t['fieldname']: [{f['fieldname']: r.get(f['fieldname']) for f in t['fields']}
                               for r in doc.get(t['fieldname']) or []] for t in spec['tables']}}


def validate_document(doc, method=None):
    spec = _runtime_spec(doc)
    if not spec:
        return
    if frappe.session.user == 'Guest' or not frappe.db.get_value('User', frappe.session.user, 'enabled'):
        raise frappe.PermissionError('请使用已启用且具有业务权限的账号。')
    _calculate(doc, spec)
    if not spec['workflow']:
        return
    from frappe.model.workflow import get_transitions, has_approval_access
    old = doc.get_doc_before_save()
    current = old.get('workflow_state') if old else STATES[0][0]
    next_state = doc.get('workflow_state') or STATES[0][0]
    statuses = dict(STATES)
    if next_state not in statuses or int(doc.docstatus or 0) != statuses[next_state]:
        frappe.throw('请使用对应复核动作，不得直接跳过流程提交或撤销。')
    doc.workflow_state = next_state
    if old and doc.owner != old.owner:
        frappe.throw('不能改变业务单据的创建人。')
    if current != next_state:
        transitions = get_transitions(old) if old else []
        allowed = [t for t in transitions if t.next_state == next_state and has_approval_access(frappe.session.user, old, t)]
        if not allowed:
            raise frappe.PermissionError('当前账号不能执行这项复核转换；普通复核人不能审核自己创建的单据。')
    if old and current not in (STATES[0][0], STATES[2][0]) and _payload(doc, spec) != _payload(old, spec):
        frappe.throw('待复核、已通过或已撤销的内容不可直接修改；请先按流程退回。')
    if old and old.docstatus == 2:
        frappe.throw('已撤销单据不可再修改。')
