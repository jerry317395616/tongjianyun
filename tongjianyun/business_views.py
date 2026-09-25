"""Permission-scoped projections with in-scene original business operation forms."""
from calendar import monthrange
from datetime import date, timedelta
from math import isfinite

import frappe
from frappe.model import get_permitted_fields

from tongjianyun.business_view_registry import REGISTRY, DOMAINS
from tongjianyun.meal_scene import business_day, meal_key
from tongjianyun.frappe_project_views import native_actions

VIEWS = {'business_catalog': '童健云常用业务', 'business_list': '业务记录',
         'business_record': '业务明细', 'stock': '当前库存', 'ingredient_nutrition': '食材营养统计',
         'classroom_day': '班级当日出勤', 'weekly_orders': '一周食谱采购'}
FIELDS = {'entity', 'record', 'keyword', 'period', 'start_date', 'end_date', 'status', 'company', 'warehouse', 'domain'}
PAGE_SIZE = 30
RECIPE = 'Tongjianyun Recipe'


def text_arg(value, key, limit=140):
    item = value[key]
    if not isinstance(item, str) or not item.strip() or len(item) > limit or any(ord(c) < 32 for c in item):
        frappe.throw('筛选参数无效：' + key)
    return item.strip()


def clean_selection(value, default_day, default_meal):
    view = value['view']
    allowed = {'view', 'components', 'day', 'meal'} | {
        'business_catalog': {'domain'},
        'business_list': {'entity', 'keyword', 'period', 'start_date', 'end_date', 'status', 'company', 'warehouse', 'group', 'offset'},
        'business_record': {'entity', 'record', 'offset'},
        'stock': {'warehouse', 'offset'},
        'ingredient_nutrition': {'recipe', 'offset'},
        'classroom_day': {'group', 'offset'},
        'weekly_orders': {'period', 'start_date', 'end_date', 'keyword', 'status', 'offset'},
    }[view]
    if set(value) - allowed:
        frappe.throw('该业务视图不支持这些筛选。')
    clean = {'day': str(business_day(value.get('day') or default_day)), 'meal': meal_key(value.get('meal') or default_meal)}
    for key in allowed - {'view', 'components', 'day', 'meal', 'offset', 'period'}:
        if key in value:
            clean[key] = text_arg(value, key, 80 if key == 'keyword' else 140)
    if 'offset' in allowed:
        offset = value.get('offset', 0)
        if isinstance(offset, bool) or not str(offset).isdigit() or not 0 <= int(offset) <= 100000:
            frappe.throw('分页位置无效。')
        clean['offset'] = int(offset)
    if view in {'business_list', 'business_record'}:
        if clean.get('entity') not in REGISTRY:
            frappe.throw('请指定已登记的业务类型，不支持任意数据表。')
        entry = REGISTRY[clean['entity']]
        if view == 'business_record' and not clean.get('record'):
            frappe.throw('请指定单据编号。')
        if view == 'business_list':
            period = value.get('period', entry.period)
            if period not in {'all', 'day', 'week', 'month'}:
                frappe.throw('时间范围无效。')
            clean['period'] = period
            if bool(clean.get('start_date')) != bool(clean.get('end_date')):
                frappe.throw('请同时提供开始和结束日期。')
            if not entry.date_field and (period != 'all' or clean.get('start_date')):
                frappe.throw('该业务不支持日期筛选。')
            if clean.get('start_date'):
                first, last = business_day(clean['start_date']), business_day(clean['end_date'])
                if first > last or (last - first).days > 3660:
                    frappe.throw('日期范围无效或超过十年。')
                clean.update(start_date=str(first), end_date=str(last))
    if 'domain' in clean and clean['domain'] not in DOMAINS:
        frappe.throw('业务分组无效。')
    if view == 'weekly_orders':
        checked = clean_selection({**value, 'view': 'business_list', 'entity': 'purchase_orders'}, default_day, default_meal)
        clean.update({k: v for k, v in checked.items() if k != 'entity'})
        if clean.get('status') and clean['status'] not in {'0', '1', '2'}:
            frappe.throw('食谱采购状态须为0草稿、1已提交或2已取消。')
    return clean


def table(title, columns, rows, collapsed=False):
    return {'type': 'table', 'title': title, 'columns': columns, 'rows': rows, 'collapsed': collapsed}


def notice(text, warning=False):
    return {'type': 'notice', 'text': text, 'warning': warning}


def action(label, choice):
    return {'label': label, 'selection': choice}


def stats(items):
    return {'type': 'stats', 'items': [{'label': k, 'value': v, 'unit': u} for k, v, u in items]}


def date_range(choice, entry):
    if choice.get('start_date'):
        return choice['start_date'], choice['end_date']
    day = date.fromisoformat(choice['day'])
    period = choice.get('period', entry.period)
    if period == 'all' or not entry.date_field:
        return None
    if period == 'week':
        first = day - timedelta(days=day.weekday())
        return str(first), str(first + timedelta(days=6))
    if period == 'month':
        return str(day.replace(day=1)), str(day.replace(day=monthrange(day.year, day.month)[1]))
    return str(day), str(day)


def guard(entry):
    if not frappe.db.exists('DocType', entry.doctype):
        raise frappe.DoesNotExistError('该业务尚未安装，无法读取。')
    if entry.doctype == 'Tongjianyun Student Health':
        from tongjianyun.health_registration import access
        access()
    if entry.doctype.startswith('Tongjianyun Video ') or entry.doctype == 'Tongjianyun Teacher Face':
        from tongjianyun.video_attendance.api import require_manager
        require_manager()
    required = {entry.doctype}
    meta = frappe.get_meta(entry.doctype)
    for field, doctype in (('student', 'Student'), ('employee', 'Employee'), ('student_group', 'Student Group')):
        if meta.has_field(field):
            required.add(doctype)
    if entry.doctype in {'Tongjianyun Recipe Dish', 'Tongjianyun Recipe Ingredient', 'Tongjianyun Recipe Day'}:
        required.add(RECIPE)
    if entry.doctype in {'Stock Ledger Entry', 'Batch', 'Item Price'}:
        required.add('Item')
    if entry.doctype == 'Stock Ledger Entry':
        required.add('Warehouse')
    for doctype in required:
        if not frappe.has_permission(doctype, 'read'):
            raise frappe.PermissionError('无权查看此业务及其关联资料：' + entry.title)


def visible_fields(entry):
    return set(get_permitted_fields(entry.doctype, permission_type='read', ignore_virtual=True))


def scope_filters(entry, fields):
    """Retain domain restrictions in addition to Frappe row permissions."""
    filters = []
    if entry.doctype == RECIPE:
        filters.append(['is_deleted', '=', 0])
        filters.append(['workflow_status', '!=', '已归档'])
    if entry.doctype in {'Tongjianyun Recipe Dish', 'Tongjianyun Recipe Ingredient', 'Tongjianyun Recipe Day'}:
        frappe.has_permission(RECIPE, 'read', throw=True)
        names = frappe.get_list(RECIPE, filters={'is_deleted': 0}, pluck='name', limit_page_length=0)
        filters.append(['recipe', 'in', names or ['']])
    meta = frappe.get_meta(entry.doctype)
    if meta.has_field('student_group'):
        from tongjianyun.attendance_scope import allowed_groups
        filters.append(['student_group', 'in', allowed_groups() or ['']])
    for field, doctype in (('student', 'Student'), ('employee', 'Employee')):
        if meta.has_field(field):
            frappe.has_permission(doctype, 'read', throw=True)
            names = frappe.get_list(doctype, pluck='name', limit_page_length=0)
            filters.append([field, 'in', names or ['']])
    if entry.doctype in {'Stock Ledger Entry', 'Batch', 'Item Price'}:
        field = 'item' if entry.doctype == 'Batch' else 'item_code'
        frappe.has_permission('Item', 'read', throw=True)
        filters.append([field, 'in', frappe.get_list('Item', pluck='name', limit_page_length=0) or ['']])
    if entry.doctype == 'Stock Ledger Entry':
        frappe.has_permission('Warehouse', 'read', throw=True)
        filters.append(['warehouse', 'in', frappe.get_list('Warehouse', pluck='name', limit_page_length=0) or ['']])
        filters.append(['is_cancelled', '=', 0])
    return filters


def query_filters(choice, entry, fields):
    filters = scope_filters(entry, fields)
    for key, field in (('company', 'company'), ('warehouse', 'warehouse'), ('group', 'student_group')):
        if key in choice:
            if field not in fields:
                frappe.throw('此业务不支持或无权使用筛选：' + key)
            filters.append([field, '=', choice[key]])
    if choice.get('status'):
        field = 'workflow_status' if entry.doctype == RECIPE else 'status'
        if field not in fields:
            frappe.throw('此业务不支持或无权使用状态筛选。')
        filters.append([field, '=', choice['status']])
    period = date_range(choice, entry)
    if period:
        if entry.date_field not in fields or (entry.end_field and entry.end_field not in fields):
            raise frappe.PermissionError('无权读取此业务的日期字段，不能据此筛选。')
        first, last = period
        kind = frappe.get_meta(entry.doctype).get_field(entry.date_field).fieldtype
        if kind == 'Datetime':
            # Half-open local datetime interval includes the entire final day.
            filters += [[entry.date_field, '>=', first + ' 00:00:00'],
                        [entry.date_field, '<', str(date.fromisoformat(last) + timedelta(days=1)) + ' 00:00:00']]
        elif entry.end_field:
            filters += [[entry.date_field, '<=', last], [entry.end_field, '>=', first]]
        else:
            filters.append([entry.date_field, 'between', [first, last]])
    or_filters = []
    if choice.get('keyword'):
        # Search fixed visible text columns, never arbitrary operators or SQL.
        meta = frappe.get_meta(entry.doctype)
        for field, _ in entry.columns:
            df = meta.get_field(field)
            if field in fields and (field == 'name' or (df and df.fieldtype in {'Data', 'Link', 'Select'})):
                or_filters.append([field, 'like', '%' + choice['keyword'].replace('%', '\\%').replace('_', '\\_') + '%'])
    return filters, or_filters


def cell(value, field, meta):
    if value is None or value == '':
        return None
    if field == 'docstatus':
        return {0: '草稿', 1: '已提交', 2: '已取消'}.get(value, '未知')
    df = meta.get_field(field)
    if df and df.fieldtype == 'Check':
        return '是' if value else '否'
    if isinstance(value, (int, float)):
        return round(value, 4) if isfinite(value) else None
    return str(value)[:1000]


def columns_for(entry, fields):
    columns = [(key, label) for key, label in entry.columns if key in fields]
    if frappe.get_meta(entry.doctype).is_submittable and 'docstatus' in fields:
        columns.append(('docstatus', '单据状态'))
    return columns


def pager(choice, has_more, step=PAGE_SIZE):
    offset = choice.get('offset', 0)
    actions = [action('常用业务', {'view': 'business_catalog', 'day': choice['day'], 'meal': choice['meal']})]
    if offset:
        actions.append(action('上一页', {**choice, 'offset': max(0, offset - step)}))
    if has_more:
        actions.append(action('下一页', {**choice, 'offset': offset + step}))
    return actions


def records_view(choice):
    entry = REGISTRY[choice['entity']]
    guard(entry)
    fields = visible_fields(entry)
    columns = columns_for(entry, fields)
    filters, or_filters = query_filters(choice, entry, fields)
    rows = frappe.get_list(entry.doctype, fields=list(dict.fromkeys(['name'] + [c[0] for c in columns])),
        filters=filters, or_filters=or_filters, order_by='modified desc, name asc',
        limit_start=choice['offset'], limit_page_length=PAGE_SIZE + 1)
    more, rows = len(rows) > PAGE_SIZE, rows[:PAGE_SIZE]
    count = frappe.get_list(entry.doctype, filters=filters, or_filters=or_filters, fields=[{'COUNT': 'name', 'as': 'total'}])[0].total
    period = date_range(choice, entry)
    scope = (f'{period[0]} — {period[1]}' if period else '全部日期') + ' · 当前账号可见记录'
    chips = [f'{k}={choice[k]}' for k in ('keyword', 'status', 'company', 'warehouse', 'group') if choice.get(k)]
    meta = frappe.get_meta(entry.doctype)
    blocks = [stats([('符合筛选的记录', count, '条')]), table(entry.title, [c[1] for c in columns], [
        {'cells': [cell(row.get(k), k, meta) for k, _ in columns],
         'action': action('查看明细', {'view': 'business_record', 'entity': choice['entity'], 'record': row.name,
                                     'day': choice['day'], 'meal': choice['meal']})} for row in rows])]
    if entry.note:
        blocks.append(notice(entry.note))
    blocks.append(notice(f"显示 {choice['offset'] + 1 if rows else 0}—{choice['offset'] + len(rows) if rows else 0} 条。记录数不等于人数、数量或金额；无记录不等于业务未发生。"))
    if len(columns) < len(entry.columns):
        blocks.append(notice('部分字段按当前账号权限隐藏。'))
    if choice['offset'] and not rows:
        blocks.append(notice('记录或筛选已变化，请回到第一页。', True))
    actions = native_actions(entry.doctype, choice) + pager(choice, more)
    if period:
        unbounded = {k: v for k, v in choice.items() if k not in {'start_date', 'end_date'}}
        actions.append(action('查看全部日期', {**unbounded, 'period': 'all', 'offset': 0}))
    return {'title': entry.title, 'subtitle': scope + (' · ' + '，'.join(chips) if chips else ''),
            'components': blocks, 'actions': actions, 'source': entry.doctype + ' · 原单据及行级权限 · 只读',
            'summary': {'entity': choice['entity'], 'record_count': count, 'page_count': len(rows), 'has_more': more,
                        'scope': scope, 'filters': chips, 'basis': entry.note, 'answer': f'已展示{entry.title}；当前筛选有 {count} 条可见记录。'}}


def record_view(choice):
    entry = REGISTRY[choice['entity']]
    guard(entry)
    fields = visible_fields(entry)
    filters = scope_filters(entry, fields) + [['name', '=', choice['record']]]
    if not frappe.get_list(entry.doctype, filters=filters, pluck='name', limit_page_length=1):
        raise frappe.PermissionError('单据不存在或不在当前可见范围。')
    doc = frappe.get_doc(entry.doctype, choice['record'])
    doc.check_permission('read')
    operation_actions = native_actions(entry.doctype, choice, doc)
    doc.apply_fieldlevel_read_permissions()
    columns = columns_for(entry, fields)
    components = [table('单据资料', ['项目', '内容'], [
        {'cells': [label, cell(doc.get(key), key, doc.meta)]} for key, label in columns])]
    max_children = 0
    for field, label, specification in entry.children:
        # Child records inherit the checked parent's permission; do not query them as unscoped tables.
        df = doc.meta.get_field(field)
        # SQL column permissions deliberately exclude Table fields in Frappe.
        # Check the actual parent table field and its permlevel, then child columns.
        if not df or df.fieldtype != 'Table' or (df.permlevel and frappe.session.user != 'Administrator'
                and not doc.has_permlevel_access_to(field, permission_type='read')):
            continue
        childtype = df.options
        child_fields = set(get_permitted_fields(childtype, parenttype=entry.doctype, permission_type='read', ignore_virtual=True))
        childmeta = frappe.get_meta(childtype)
        cols = [c.split(':', 1) for c in specification.split('|') if c.split(':', 1)[0] in child_fields]
        rows = doc.get(field) or []
        # Student memberships must not leak names outside the current Student read scope.
        if childmeta.has_field('student'):
            frappe.has_permission('Student', 'read', throw=True)
            visible = set(frappe.get_list('Student', pluck='name', limit_page_length=0))
            rows = [r for r in rows if r.get('student') in visible]
        for group_field in ('student_group', 'class_id'):
            if childmeta.has_field(group_field):
                from tongjianyun.attendance_scope import allowed_groups
                visible = set(allowed_groups())
                rows = [r for r in rows if r.get(group_field) in visible]
        max_children = max(max_children, len(rows))
        page = rows[choice['offset']:choice['offset'] + PAGE_SIZE]
        components.append(table(label + (f' · {doc.currency}' if doc.get('currency') else ''), [c[1] for c in cols],
            [{'cells': [cell(r.get(k), k, childmeta) for k, _ in cols]} for r in page]))
        components.append(notice(f'可见明细共 {len(rows)} 条，本页 {len(page)} 条；不跨单位或币种求和。'))
    if entry.note:
        components.append(notice(entry.note))
    actions = operation_actions + [action('返回列表（全部日期）', {'view': 'business_list', 'entity': choice['entity'], 'day': choice['day'], 'meal': choice['meal'], 'period': 'all'})]
    actions += pager(choice, choice['offset'] + PAGE_SIZE < max_children)
    if choice['entity'] == 'recipes':
        actions += [action('周营养分析', {'view': 'recipe_nutrition', 'recipe': doc.name, 'day': choice['day'], 'meal': choice['meal']}),
                    action('食材营养统计', {'view': 'ingredient_nutrition', 'recipe': doc.name, 'day': choice['day'], 'meal': choice['meal']})]
        actions += [action(label, {'view': 'business_list', 'entity': entity, 'keyword': doc.name, 'period': 'all', 'day': choice['day'], 'meal': choice['meal']})
                    for label, entity in (('菜品明细', 'recipe_dishes'), ('食材用量', 'recipe_ingredients'))]
    return {'title': entry.title + ' · 明细', 'subtitle': doc.name, 'components': components, 'actions': actions,
            'source': entry.doctype + ' · 已核验原单据及字段权限 · 只读',
            'summary': {'entity': choice['entity'], 'answer': '单据已展示；个人资料和单据明细不回传模型。'}}


def catalog_view(choice):
    groups = {domain: [] for domain in DOMAINS if not choice.get('domain') or choice['domain'] == domain}
    available = 0
    for key, entry in REGISTRY.items():
        if entry.domain not in groups:
            continue
        try:
            guard(entry)
            enabled = True
        except frappe.PermissionError:
            enabled = False
        except frappe.DoesNotExistError:
            enabled = False
        installed = frappe.db.exists('DocType', entry.doctype)
        row = {'cells': [entry.title, '可查看' if enabled else '无查看权限' if installed else '尚未安装', entry.note or '原业务记录 · 只读']}
        if enabled:
            available += 1
            row['action'] = action('查看', {'view': 'business_list', 'entity': key, 'day': choice['day'], 'meal': choice['meal']})
        groups[entry.domain].append(row)
    blocks = [notice('直接在右侧说要办理什么，也可以点业务名称。列表与统计为只读；通过“办理 / 编辑”“新建”在本场景内使用原业务表单，权限及校验不变。')]
    blocks.extend(table(domain, ['业务', '当前权限', '说明'], rows, collapsed=domain == '基础资料') for domain, rows in groups.items())
    blocks.append(notice('这里是常用业务摘要，不是全部能力清单。厨房加工、配送签收、食品留样、体格测量或过敏配餐等需求，先由助手检索全部已安装业务；确实缺少时再创建新业务。库存单或健康登记不能代替这些专门记录。'))
    return {'title': '童健云常用业务', 'subtitle': '童健云及已使用的教育、采购、库存、人事模块', 'components': blocks,
            'actions': [action('在园学生', {'view': 'students'}), action('用餐人数', {'view': 'meal_counts', 'day': choice['day'], 'meal': choice['meal']}),
                        action('班级当日出勤', {'view': 'classroom_day', 'day': choice['day'], 'meal': choice['meal']}),
                        action('一周食谱采购', {'view': 'weekly_orders', 'day': choice['day'], 'meal': choice['meal']}),
                        action('当前库存', {'view': 'stock', 'day': choice['day'], 'meal': choice['meal']}),
                        action('周营养分析', {'view': 'recipe_nutrition', 'day': choice['day'], 'meal': choice['meal']}),
                        action('食材营养统计', {'view': 'ingredient_nutrition', 'day': choice['day'], 'meal': choice['meal']})],
            'source': '已审核业务目录；不包含系统管理、密钥、人脸模板及未使用的 ERP 模块',
            'summary': {'registered': len(REGISTRY), 'available_in_selected_domains': available, 'domains': list(groups)}}


def stock_view(choice):
    from tongjianyun.meal_scene import get_stock
    result = get_stock(choice.get('warehouse'), choice['offset'])
    if result.get('warehouse'):
        choice['warehouse'] = result['warehouse']
    rows = result['rows']
    blocks = [notice(result.get('basis') or '当前没有可见可用仓库，库存未知。', not result.get('warehouse')),
              table('库存明细', ['物料', '物料编号', '账面数量', '预计数量', '订货数量', '单位'], [
                  {'cells': [r.get(k) for k in ('item_name', 'item_code', 'actual_qty', 'projected_qty', 'ordered_qty', 'stock_uom')]} for r in rows]),
              table('选择仓库', ['仓库', '组织'], [{'cells': [w['name'], w['company']],
                    'action': action('切换仓库', {**choice, 'warehouse': w['name'], 'offset': 0})} for w in result['warehouses']], True)]
    return {'title': '当前库存', 'subtitle': (result.get('warehouse') or '未选择仓库') + ' · 实时账面，不按顶部日期回溯',
            'components': blocks, 'actions': pager(choice, result['has_more'], 20), 'source': '原库存查询服务；仓库、物料和库存权限交集',
            'summary': {'warehouse': result.get('warehouse'), 'page_count': len(rows), 'has_more': result['has_more'], 'basis': result.get('basis')}}


def ingredient_view(choice):
    from tongjianyun.meal_scene import get_recipe, read_doc, visible_rows
    from tongjianyun.tongjianyun.report.ingredient_nutrition_statistics.ingredient_nutrition_statistics import execute
    if not choice.get('recipe'):
        candidates = visible_rows(RECIPE, ['name', 'title', 'week_start', 'week_end'],
                                 {'is_deleted': 0, 'workflow_status': ['!=', '已归档'], 'week_start': ['<=', choice['day']], 'week_end': ['>=', choice['day']]})
        if not candidates['available']:
            raise frappe.PermissionError('没有食谱查看权限。')
        rows = candidates['rows']
        if len(rows) != 1 or candidates['has_more']:
            return {'title': '食材营养统计', 'subtitle': choice['day'], 'components': [notice('请选择对应食谱；若没有记录，请先上传食谱。', True),
                table('选择食谱（最多20份）', ['食谱', '开始', '结束'], [{'cells': [r['title'], str(r['week_start']), str(r['week_end'])],
                       'action': action('查看统计', {**choice, 'recipe': r['name']})} for r in rows])],
                'source': '当前可见且覆盖业务日期的食谱', 'summary': {'available': False}}
        choice['recipe'] = rows[0]['name']
    get_recipe(choice['recipe'])
    doc = read_doc(RECIPE, choice['recipe'])
    result = execute({'recipe': doc.name, 'value_basis': '日均每人贡献', 'nutrient_scope': '全部指标'})
    columns, rows = result[:2]
    page = rows[choice['offset']:choice['offset'] + PAGE_SIZE]
    blocks = [notice('日均每生估算，按分类代表值计算，并非检验值、实际摄入或采购总量。食谱状态：' + str(doc.workflow_status or '未知'), True),
              table('食材营养明细 · 日均每生', [c['label'] for c in columns],
                    [{'cells': [round(r[c['fieldname']], 4) if isinstance(r.get(c['fieldname']), (int, float)) else r.get(c['fieldname']) for c in columns]} for r in page]),
              notice(f'共 {len(rows)} 种食材，本页 {len(page)} 种；全部营养指标可横向滚动查看。')]
    return {'title': '食材营养统计', 'subtitle': f'{doc.title} · {doc.week_start} — {doc.week_end}',
            'components': blocks, 'actions': pager(choice, choice['offset'] + PAGE_SIZE < len(rows)),
            'source': '原 Ingredient Nutrition Statistics 报表 · 日均每人贡献 · 所有指标',
            'summary': {'available': True, 'ingredient_count': len(rows), 'basis': '分类代表值估算；日均每生'}}


def get_business_view(choice):
    return {'business_catalog': catalog_view, 'business_list': records_view, 'business_record': record_view,
            'stock': stock_view, 'ingredient_nutrition': ingredient_view,
            'classroom_day': classroom_view, 'weekly_orders': weekly_orders_view}[choice['view']](choice)


def classroom_view(choice):
    from tongjianyun.meal_views import _groups
    from tongjianyun.classroom import _scope, _attendance, _capabilities
    groups = _groups()
    group = choice.get('group')
    if not group:
        return {'title': '班级当日出勤', 'subtitle': choice['day'], 'components': [
            notice('请选择班级，查看已登记出勤、请假和待登记人数。'),
            table('选择班级', ['班级', '学年'], [{'cells': [g.student_group_name or g.name, g.academic_year],
                'action': action('查看', {**choice, 'group': g.name, 'offset': 0})} for g in groups])],
            'source': '当前可见启用班级', 'summary': {'available': False, 'class_count': len(groups)}}
    matches = [g for g in groups if g.name == group] or [g for g in groups if g.student_group_name == group]
    if len(matches) != 1:
        frappe.throw('未找到唯一可见班级，请通过班级列表选择。')
    group = matches[0]
    choice['group'] = group.name
    for doctype in ('Student Attendance', 'Student Leave Application'):
        frappe.has_permission(doctype, 'read', throw=True)
    data = _attendance(_scope(group.name), business_day(choice['day']))
    capabilities = _capabilities(business_day(choice['day']))
    counts = data['counts']
    rows = data['students'][choice['offset']:choice['offset'] + PAGE_SIZE]
    return {'title': '班级当日出勤', 'subtitle': f'{group.student_group_name or group.name} · {choice["day"]}',
            'components': [stats([('已登记出勤', counts['Present'], '人'), ('已登记缺勤', counts['Absent'], '人'),
                                 ('请假', counts['Leave'], '人'), ('尚未登记', counts['Unknown'], '人')]),
                           notice('仅原考勤及请假记录。未登记不算出勤或缺勤；统计范围为当前可见有效名单，历史日期不重建历史学籍。', True),
                           {'type': 'attendance_register', 'student_group': group.name,
                            'group_label': group.student_group_name or group.name, 'day': choice['day'],
                            'revision': data['revision'], 'editable': bool(capabilities['attendance_write']),
                            'reason': ('未来日期不能登记实际出勤' if capabilities['future'] else
                                       '该日考勤已确认或锁定，请先通过原流程核对' if capabilities['attendance_lock'] else
                                       '' if capabilities['attendance_write'] else '当前账号没有出勤修改权限'),
                            'rows': rows}],
            'actions': pager(choice, choice['offset'] + PAGE_SIZE < len(data['students'])), 'source': data['source'] + ' · 班级原业务权限',
            'summary': {'available': True, 'day': choice['day'], 'counts': {k: counts[k] for k in ('Present', 'Absent', 'Leave', 'Unknown')},
                        'basis': '登记事实，未登记不是出勤；没有写入考勤'}}


def weekly_orders_view(choice):
    from tongjianyun.purchase_browser import search
    period = date_range(choice, REGISTRY['purchase_orders'])
    rows = search(scope='all', start_date=period[0] if period else None, end_date=period[1] if period else None,
                  status=choice.get('status'), keyword=choice.get('keyword'), offset=choice['offset'])
    return {'title': '一周食谱采购', 'subtitle': ' — '.join(period) if period else '全部食谱日期',
            'components': [notice('沿用原“一周采购订单”口径，按订单标题中的食谱日期筛选，不按交易日期。'),
                table('食谱采购订单', ['食谱采购单', '供餐日期', '供应商', '金额', '币种', '单据状态'], [
                    {'cells': [r.get('title'), r.get('recipe_date'), r.get('supplier_name'), r.get('grand_total'), r.get('currency'),
                               {0: '草稿', 1: '已提交', 2: '已取消'}.get(r.get('docstatus'), '未知')],
                     'action': action('采购明细', {'view': 'business_record', 'entity': 'purchase_orders', 'record': r['name'],
                                                 'day': choice['day'], 'meal': choice['meal']})} for r in rows['orders']]),
                notice('本页记录数不是全量订单数；金额不跨币种合计。')],
            'actions': pager(choice, rows['has_more'], 20), 'source': '原 purchase_browser.search · 可见食谱日期标记采购单',
            'summary': {'page_count': len(rows['orders']), 'has_more': rows['has_more'], 'period': period,
                        'basis': '按订单标题中的食谱日期，不是交易日期'}}
