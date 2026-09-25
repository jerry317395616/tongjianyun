"""Permission-preserving read model for the eight-stop meal scene.

GETs never initialise daily confirmations, launch jobs, publish recipes, or
write ERP documents. A displayed preparation/dispatch scene is not telemetry.
"""
from __future__ import annotations

from datetime import date, timedelta
from math import isfinite
from uuid import uuid4
import json
import re

import frappe
from frappe.utils import now_datetime, today
from tongjianyun.workspace_entry import require_account, mark_private_response

RECIPE = 'Tongjianyun Recipe'
CLASS_MEAL = 'Tongjianyun Class Meal Confirmation'
MEALS = ('breakfast', 'morning_snack', 'lunch', 'afternoon_snack', 'dinner')
RECIPE_SLOTS = dict(zip(MEALS, ('breakfast', 'morningSnack', 'lunch', 'snack', 'dinner')))
RECIPE_LABELS = dict(zip(RECIPE_SLOTS.values(), ('早餐', '早点', '午餐', '午点', '晚餐')))


def can(doctype, action='read'):
    return bool(frappe.db.exists('DocType', doctype) and frappe.has_permission(doctype, action))


def has_access():
    """An entry is not a new role grant. A class teacher alone is not a caterer."""
    try:
        require_account()
    except frappe.PermissionError:
        return False
    return any(can(dt) for dt in (RECIPE, 'Purchase Order', 'Purchase Receipt')) or all(
        can(dt) for dt in ('Warehouse', 'Bin', 'Item'))


def require_access():
    require_account()
    mark_private_response()
    if not has_access():
        raise frappe.PermissionError('需要已有的食谱、采购、收货或库存业务权限；选择入口不会授予权限。')


def business_day(value=None):
    value = str(value or today())
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        frappe.throw('业务日期应为 YYYY-MM-DD')
    try:
        return date.fromisoformat(value)
    except ValueError:
        frappe.throw('无效业务日期')


def meal_key(value='lunch'):
    if value not in MEALS:
        frappe.throw('请选择已有的五个餐次之一')
    return value


def page_offset(value=0):
    try:
        offset = int(value)
    except (TypeError, ValueError):
        frappe.throw('分页参数无效')
    if not 0 <= offset <= 100000:
        frappe.throw('分页参数超出范围')
    return offset


def read_doc(doctype, name):
    doc = frappe.get_doc(doctype, name)
    doc.check_permission('read')
    return doc


def visible_rows(doctype, fields, filters=None, order='modified desc', offset=0, limit=20):
    """No unscoped counts; pagination totals are explicitly only visible pages."""
    if not can(doctype):
        return {'available': False, 'rows': [], 'has_more': False}
    rows = frappe.get_list(doctype, filters=filters or {}, fields=fields,
        order_by=order, limit_start=offset, limit_page_length=limit + 1)
    return {'available': True, 'rows': [dict(r) for r in rows[:limit]], 'has_more': len(rows) > limit}


def meal_summary(rows, total_groups):
    """Never turn a missing plan or partially confirmed set into actual totals."""
    plans = [r for r in rows if r['has_plan']]
    confirmed = [r for r in rows if r['confirmed']]
    return {'visible_groups': total_groups, 'planned_groups': len(plans),
        'confirmed_groups': len(confirmed), 'missing_groups': total_groups - len(plans),
        'expected': sum(r['expected'] for r in plans) if len(plans) == total_groups and total_groups else None,
        'actual': sum(r['actual'] for r in confirmed) if len(confirmed) == total_groups and total_groups else None,
        'confirmed_subtotal': sum(r['actual'] for r in confirmed) if confirmed else None,
        'scope_label': '当前可见班级，不将部分数据称为全园总量'}


def class_plans(day, meal):
    if not (can(CLASS_MEAL) and can('Student Group')):
        return {'available': False, 'rows': [], 'summary': None}
    from tongjianyun.attendance_scope import allowed_groups
    from tongjianyun.student_meals import meal_facts
    scope = allowed_groups()
    groups = frappe.get_list('Student Group', filters={'name': ['in', scope], 'disabled': 0},
        fields=['name', 'student_group_name'], order_by='student_group_name asc', limit_page_length=0) if scope else []
    records = frappe.get_list(CLASS_MEAL, filters={'student_group': ['in', scope], 'meal_date': str(day)},
        fields=['name', 'student_group'], limit_page_length=0) if scope else []
    index = {r.student_group: r.name for r in records}
    result = []
    for group in groups:
        doc = read_doc(CLASS_MEAL, index[group.name]) if group.name in index else None
        facts = meal_facts(doc.students)[meal] if doc else None
        confirmed = bool(facts and facts['complete'])
        result.append({'group': group.name, 'label': group.student_group_name or group.name,
            'record': doc.name if doc else None, 'has_plan': doc is not None, 'confirmed': confirmed,
            'expected': facts['expected'] if facts else None,
            'actual': facts['actual'] if facts else None,
            'status': facts['status'] if facts else '尚未保存预计',
            'modified': str(doc.modified) if doc else None})
    return {'available': True, 'rows': result, 'summary': meal_summary(result, len(groups)),
        'note': '名单取当前可见启用班级；已保存餐次使用当日快照。确认的是实际就餐，不是出餐或签收。'}


def purchase_rows(day, kind='order', offset=0):
    types = {'order': ('Purchase Order', 'transaction_date'), 'receipt': ('Purchase Receipt', 'posting_date')}
    if kind not in types:
        frappe.throw('单据种类无效')
    dt, date_field = types[kind]
    start = day - timedelta(days=6)
    result = visible_rows(dt, ['name', 'supplier_name', 'company', date_field, 'status', 'docstatus', 'grand_total', 'currency'],
        {date_field: ['between', [str(start), str(day)]], 'docstatus': ['<', 2]},
        f'{date_field} desc, modified desc', offset)
    return {**result, 'doctype': dt, 'date_field': date_field, 'start': str(start), 'end': str(day),
        'note': '所选日期向前七日的可见采购单据；并不全部来自食谱。收货单不是食品检验合格证明。'}


@frappe.whitelist()
def get_overview(day=None, meal='lunch'):
    require_access()
    day, meal = business_day(day), meal_key(meal)
    recipes = visible_rows(RECIPE, ['name', 'title', 'week_start', 'week_end', 'workflow_status', 'modified'],
        {'is_deleted': 0, 'workflow_status': ['!=', '已归档'], 'week_start': ['<=', str(day)], 'week_end': ['>=', str(day)]})
    return {'day': str(day), 'today': today(), 'meal': meal, 'generated_at': str(now_datetime()),
        'user_label': frappe.db.get_value('User', frappe.session.user, 'full_name') or '膳食工作空间',
        'recipes': recipes, 'plans': class_plans(day, meal),
        'orders': purchase_rows(day), 'receipts': purchase_rows(day, 'receipt'),
        'capabilities': {'recipe': can(RECIPE), 'recipe_write': can(RECIPE, 'write'),
            'recipe_create': can(RECIPE, 'create') and can(RECIPE, 'write'),
            'procurement': can('Material Request', 'create') and can('Material Request') and can(RECIPE),
            'order': can('Purchase Order'), 'receipt': can('Purchase Receipt'),
            'stock': all(can(dt) for dt in ('Bin', 'Item', 'Warehouse')),
            'meals': can(CLASS_MEAL) and can('Student Group'),
            'meals_write': can(CLASS_MEAL, 'write')},
        'unconnected': ['加工执行记录', '配送签收', '温度传感器', '留样消毒记录', '特殊餐执行闭环'],
        'scene': {'mode': 'illustrative', 'telemetry': False, 'workflow_order_not_completion': True}}


@frappe.whitelist()
def get_recipes(offset=0, keyword=''):
    require_access()
    filters = {'is_deleted': 0, 'workflow_status': ['!=', '已归档']}
    if keyword:
        filters['title'] = ['like', '%' + str(keyword)[:100] + '%']
    return visible_rows(RECIPE, ['name', 'title', 'week_start', 'week_end', 'workflow_status', 'modified'],
        filters, 'week_start desc, modified desc', page_offset(offset))


@frappe.whitelist()
def get_recipe(recipe):
    require_access()
    doc = read_doc(RECIPE, recipe)
    if doc.is_deleted:
        frappe.throw('食谱已移入回收站，请重新选择')
    # Existing payload helper reads all recipe rows. Check full row visibility
    # before delegating, so a new scene cannot widen the original permissions.
    for dt in ('Tongjianyun Recipe Dish', 'Tongjianyun Recipe Ingredient'):
        frappe.has_permission(dt, 'read', throw=True)
        rows = frappe.get_list(dt, filters={'recipe': recipe}, pluck='name', limit_page_length=0)
        if len(rows) != frappe.db.count(dt, {'recipe': recipe}):
            raise frappe.PermissionError('不能读取完整食谱明细')
    from tongjianyun.recipe_storage import get_recipe_detail
    payload = get_recipe_detail(doc.name)
    return {'name': doc.name, 'revision': str(doc.modified), 'payload': payload,
        'edit': recipe_edit_policy(doc, payload)}


def recipe_edit_policy(doc, payload):
    """Edit the same weekly identity; locked dates are checked during saving."""
    if not can(RECIPE, 'write'):
        return {'mode': 'none', 'reason': '当前账号没有修改食谱的权限。'}
    if doc.get('is_deleted') or doc.workflow_status == '已归档' or not doc.recipe_id:
        return {'mode': 'none', 'reason': '这份食谱仅供历史查阅，请编辑本周当前食谱。'}
    return {'mode': 'update', 'reason': '保存到同一份周食谱，保留修改历史；已锁定日期不可改动，不覆盖采购或用餐记录。'}


def editable_day_content(day):
    """Compare only fields this editor exposes; derived metadata is not user input."""
    return [(portion.get('slot'), list(portion.get('dishes') or []),
        [(row.get('dishName'), row.get('ingredient'), float(row.get('amount') or 0), row.get('unit') or 'g')
            for row in portion.get('dishIngredientRows') or []])
        for portion in day.get('portions') or []]


def require_recipe_create():
    require_access()
    if not (can(RECIPE, 'create') and can(RECIPE, 'write')):
        raise frappe.PermissionError('当前账号没有新建食谱草稿的权限')


def new_draft_payload(value):
    """Accept only bounded recipe content; identity and lifecycle are server-owned."""
    raw = json.loads(value) if isinstance(value, str) else value
    if not isinstance(raw, dict) or len(json.dumps(raw, ensure_ascii=False)) > 512000:
        frappe.throw('食谱内容无效或过大')
    source = raw.get('recipe') or {}
    days = raw.get('days') or []
    if not isinstance(source, dict) or not isinstance(days, list) or not 1 <= len(days) <= 7:
        frappe.throw('请提供一至七天的食谱')
    title = str(source.get('title') or '').strip()
    if not title or len(title) > 140:
        frappe.throw('请填写不超过 140 字的食谱名称')
    clean_days = []
    seen_dates = set()
    ingredient_count = 0
    for index, row in enumerate(days):
        if not isinstance(row, dict):
            frappe.throw('食谱日期内容无效')
        if not row.get('date'):
            frappe.throw('食谱日期不能为空')
        day_date = business_day(row['date'])
        if day_date in seen_dates:
            frappe.throw('食谱日期不能重复')
        seen_dates.add(day_date)
        portions = row.get('portions') or []
        if not isinstance(portions, list) or len(portions) > 5:
            frappe.throw('每个日期最多五个餐次')
        clean_portions = []
        seen_slots = set()
        for portion in portions:
            if not isinstance(portion, dict) or portion.get('slot') not in RECIPE_SLOTS.values():
                frappe.throw('食谱餐次无效')
            slot = portion['slot']
            if slot in seen_slots:
                frappe.throw('同一天的餐次不能重复')
            seen_slots.add(slot)
            dishes = portion.get('dishes') or []
            rows = portion.get('dishIngredientRows') or []
            if not isinstance(dishes, list) or not isinstance(rows, list) or len(dishes) > 20:
                frappe.throw('单餐菜品过多或格式无效')
            names = [str(name).strip() for name in dishes]
            if any(not name or len(name) > 140 for name in names) or len(set(names)) != len(names):
                frappe.throw('菜品名称不能为空、重复或超过 140 字')
            clean_rows = []
            for item in rows:
                if not isinstance(item, dict):
                    frappe.throw('食材明细格式无效')
                dish_name = str(item.get('dishName') or '').strip()
                ingredient = str(item.get('ingredient') or '').strip()
                unit = str(item.get('unit') or 'g').strip()
                try:
                    amount = float(item.get('amount') or 0)
                except (TypeError, ValueError):
                    frappe.throw('食材用量必须是数字')
                if dish_name not in names or not ingredient or len(ingredient) > 140 or not unit or len(unit) > 12 or not isfinite(amount) or not 0 <= amount <= 100000:
                    frappe.throw('请核对食材所属菜品、名称、用量和单位')
                clean_rows.append({'dishName': dish_name, 'ingredient': ingredient, 'amount': amount, 'unit': unit})
                ingredient_count += 1
                if ingredient_count > 300:
                    frappe.throw('食材明细超过 300 项，请拆分食谱')
            clean_portions.append({'slot': slot, 'label': RECIPE_LABELS[slot],
                'dishes': names, 'dishIngredientRows': clean_rows})
        clean_days.append({'id': f'DAY-{index + 1}', 'date': str(day_date), 'day': str(row.get('day') or '')[:20],
            'version': 1, 'portions': clean_portions})
    clean_days.sort(key=lambda row: row['date'])
    for index, row in enumerate(clean_days):
        row['id'] = f'DAY-{index + 1}'
    start = business_day(source.get('weekStart') or clean_days[0]['date'])
    end = business_day(source.get('weekEnd') or clean_days[-1]['date'])
    if end < start or (end - start).days > 6 or any(not start <= date.fromisoformat(row['date']) <= end for row in clean_days):
        frappe.throw('食谱日期须位于同一周的起止范围内')
    recipe_id = f'SCENE-{start:%Y%m%d}-{uuid4().hex.upper()}'
    return {'recipe': {'recipeId': recipe_id, 'title': title, 'weekStart': str(start),
        'weekEnd': str(end), 'workflowStatus': '草稿'}, 'days': clean_days}


@frappe.whitelist(methods=['POST'])
def create_recipe_draft(payload, import_id=''):
    require_recipe_create()
    from tongjianyun.recipe_storage import save_recipe_payload
    clean = new_draft_payload(payload)
    if import_id:
        from tongjianyun.recipe_import import get_recipe_import_status
        imported = get_recipe_import_status(import_id)
        if imported.get('status') != 'completed':
            frappe.throw('导入任务尚未完成，请先校对识别结果')
        source = (imported.get('result') or {}).get('payload') or {}
        source_recipe = source.get('recipe') or {}
        clean['recipe']['sourceFileName'] = str(imported.get('source_file') or '')[:140]
        clean['recipe']['parser'] = str(source_recipe.get('parser') or '')[:140]
        clean['recipe']['relationSource'] = str(source_recipe.get('relationSource') or '')[:140]
    result = save_recipe_payload(clean)
    return {'name': result['erp_sync']['recipe'], 'title': clean['recipe']['title'],
        'status': '草稿', 'sync': result['erp_sync']}


@frappe.whitelist(methods=['POST'])
def save_recipe_edit(recipe, revision, payload):
    """Update one weekly master, retaining a full prior-version snapshot."""
    require_access()
    from tongjianyun.recipe_week import lock_recipe_writes
    lock_recipe_writes()
    snapshot = get_recipe(recipe)
    if not revision or str(revision) != snapshot['revision']:
        frappe.throw('食谱已被其他人修改，请刷新后重新核对。')
    from tongjianyun.recipe_storage import save_recipe_payload
    # Lock the parent through the whole save, including the rebuilt detail rows.
    rows = frappe.db.sql('SELECT `modified` FROM `tabTongjianyun Recipe` WHERE `name` = %s FOR UPDATE',
        (recipe,), as_dict=True)
    if not rows or str(rows[0]['modified']) != str(revision):
        frappe.throw('食谱已被其他人修改，请刷新后重新核对。')
    doc = read_doc(RECIPE, recipe)
    doc.check_permission('write')
    policy = recipe_edit_policy(doc, snapshot['payload'])
    if policy['mode'] == 'none':
        raise frappe.PermissionError(policy['reason'])
    clean = new_draft_payload(payload)
    if policy['mode'] == 'update':
        if (clean['recipe']['weekStart'] != str(doc.week_start)
                or clean['recipe']['weekEnd'] != str(doc.week_end)):
            frappe.throw('直接编辑草稿不能改变日期范围，请另建食谱。')
        if frappe.db.exists(RECIPE, {'recipe_id': doc.recipe_id}) != doc.name:
            frappe.throw('食谱标识不唯一，不能在此直接覆盖，请联系管理员核对。')
        clean['recipe']['recipeId'] = doc.recipe_id
        clean['recipe']['revision'] = str(revision)
        for key, attr in (('sourceFileName', 'source_file_name'), ('parser', 'parser'),
                ('relationSource', 'relation_source'), ('importedAt', 'imported_at')):
            clean['recipe'][key] = str(getattr(doc, attr, '') or '')
        previous = {day['date']: day for day in snapshot['payload'].get('days') or []}
        for day in clean['days']:
            old = previous.get(day['date'])
            if old:
                for key in ('id', 'score', 'risk', 'updatedAt', 'updatedBy', 'editReason', 'version'):
                    if key in old:
                        day[key] = old[key]
                previous_portions = {portion['slot']: portion for portion in old.get('portions') or []}
                for portion in day['portions']:
                    original = previous_portions.get(portion['slot'])
                    if original and editable_day_content({'portions': [original]}) == editable_day_content({'portions': [portion]}):
                        for key in ('amountPerChild', 'totalAmount'):
                            if key in original:
                                portion[key] = original[key]
                if editable_day_content(old) != editable_day_content(day):
                    day.update({'score': 0, 'risk': 'normal', 'updatedAt': str(now_datetime()),
                        'updatedBy': frappe.session.user, 'editReason': '',
                        'version': int(old.get('version') or 1) + 1})
        result = save_recipe_payload(clean)
    return {'name': result['erp_sync']['recipe'], 'title': clean['recipe']['title'],
        'status': '草稿', 'mode': policy['mode'], 'source': doc.name, 'sync': result['erp_sync']}


@frappe.whitelist(methods=['POST'])
def start_recipe_import(file_url):
    require_recipe_create()
    from tongjianyun.recipe_import import start_recipe_import as original
    return original(file_url)


@frappe.whitelist()
def get_recipe_import_status(import_id):
    require_recipe_create()
    from tongjianyun.recipe_import import get_recipe_import_status as original
    return original(import_id)


@frappe.whitelist()
def nutrition(recipe, garden_ratio=80):
    require_access()
    get_recipe(recipe)
    from tongjianyun.nutrition_sheet import get_nutrition_sheet
    result = get_nutrition_sheet(recipe=recipe, garden_ratio=garden_ratio)
    # This surface does not need pupil demographics/population rows.
    analysis = result['analysis']
    return {'recipe': result['recipe'], 'nutrients': analysis['nutrients'],
        'evaluations': analysis['nutrient_evaluations'], 'rule': analysis['calculation_rule'],
        'standard_label': analysis['standard'].get('profile'), 'garden_ratio': result['filters']['garden_ratio'],
        'conclusion': analysis['conclusion'],
        'basis': '按食谱食材分类代表值估算的周日均每生供给量；不是实测摄入量，也不是食品安全合格率。'}


@frappe.whitelist()
def get_documents(day=None, kind='order', offset=0):
    require_access()
    return purchase_rows(business_day(day), kind, page_offset(offset))


@frappe.whitelist()
def get_stock(warehouse=None, offset=0):
    require_access()
    if not all(can(dt) for dt in ('Bin', 'Warehouse', 'Item')):
        raise frappe.PermissionError('需要库存、仓库及物料读取权限')
    warehouses = frappe.get_list('Warehouse', filters={'disabled': 0, 'is_group': 0},
        fields=['name', 'company'], order_by='name asc', limit_page_length=0)
    valid = {w.name for w in warehouses}
    if warehouse and warehouse not in valid:
        raise frappe.PermissionError('仓库不在当前可见范围')
    selected = warehouse or (warehouses[0].name if warehouses else None)
    if not selected:
        return {'warehouses': [], 'warehouse': None, 'rows': [], 'has_more': False}
    # Filter by readable Item keys before paging Bin: forbidden stock cannot
    # leak through names, quantities, or page counters.
    items = frappe.get_list('Item', filters={'disabled': 0}, fields=['name', 'item_name'], limit_page_length=0)
    names = {r.name: r.item_name for r in items}
    result = visible_rows('Bin', ['name', 'item_code', 'warehouse', 'actual_qty', 'projected_qty', 'ordered_qty', 'stock_uom'],
        {'warehouse': selected, 'item_code': ['in', list(names)]}, 'item_code asc', page_offset(offset)) if names else {'rows': [], 'has_more': False, 'available': True}
    for row in result['rows']:
        row['item_name'] = names[row['item_code']]
    return {**result, 'warehouses': [dict(w) for w in warehouses], 'warehouse': selected,
        'generated_at': str(now_datetime()), 'basis': '当前账面库存，不随业务日期回溯；不等于实物盘点、可用保质期或采购净缺口。不同单位不合计。'}


@frappe.whitelist()
def prepare_demand(recipe):
    require_access()
    get_recipe(recipe)
    from tongjianyun import recipe_procurement as service
    scope = service.default_scope(recipe)
    prepared = service.prepare(recipe, scope['company'])
    impact = service.revision_impact(recipe)
    return {'scope': scope, 'prepared': prepared, 'impact': impact}


def demand_arguments(recipe, mappings, meals):
    from tongjianyun import recipe_procurement as service
    scope = service.default_scope(recipe)
    mappings = frappe.parse_json(mappings) if isinstance(mappings, str) else mappings
    meals = frappe.parse_json(meals) if isinstance(meals, str) else meals
    if not isinstance(mappings, dict) or not isinstance(meals, dict):
        frappe.throw('请重新核对食材匹配与餐次人数')
    if len(mappings) > 500 or len(meals) > 500:
        frappe.throw('本次预览范围过大，请在专业工作台处理')
    return dict(recipe=recipe, company=scope['company'], warehouse=scope['warehouse'], mappings=mappings, meals=meals, include_history=0)


@frappe.whitelist()
def preview_demand(recipe, mappings, meals):
    require_access()
    get_recipe(recipe)
    from tongjianyun.recipe_procurement import preview
    return preview(**demand_arguments(recipe, mappings, meals))


@frappe.whitelist(methods=['POST'])
def create_demand(recipe, mappings, meals, token, confirmed=0):
    """Only a demand DRAFT, never order/receipt/invoice/payment completion."""
    require_access()
    if str(confirmed) != '1':
        frappe.throw('请明确确认采购需求草稿；本操作不下单、不收货、不付款')
    doc = read_doc(RECIPE, recipe)
    frappe.db.get_value(RECIPE, doc.name, 'name', for_update=True)
    from tongjianyun import recipe_procurement as service
    args = demand_arguments(recipe, mappings, meals)
    preview = service.preview(**args)
    if token != preview['token']:
        frappe.throw('食谱、人数或映射已变化，请重新预览')
    impact = service.revision_impact(recipe)
    if impact['requests']:
        frappe.throw('已有采购需求，请打开原单核对，不重复生成，也不覆盖已提交记录')
    return service.create_request(**args, token=token, confirmed=1)


@frappe.whitelist()
def get_meals(student_group, day=None):
    require_access()
    from tongjianyun.classroom import get_meals as original, _capabilities
    day = business_day(day)
    result = original(student_group, str(day), workspace='business')
    return {**result, 'editable': _capabilities(day)['meals_write']}


@frappe.whitelist(methods=['POST'])
def save_meals(student_group, day, students, revision='', confirm=0, change_reason=''):
    require_access()
    from tongjianyun.classroom import save_meals as original
    return original(student_group, str(business_day(day)), students, revision, confirm, change_reason, workspace='business')


@frappe.whitelist()
def recipe_trace(recipe):
    require_access()
    get_recipe(recipe)
    from tongjianyun.recipe_procurement import revision_impact
    return {'impact': revision_impact(recipe) if can('Material Request') else None,
        'note': '仅展示现有食谱与业务单据关联；不是产地、检验、批次或冷链全链路溯源。'}
