"""Read-only projection of the existing weekly nutrition sheet for the canvas."""
from math import isfinite

import frappe

from tongjianyun.meal_scene import RECIPE, get_recipe, read_doc, visible_rows
from tongjianyun.nutrition_population import AUTO_MODE, MANUAL_MODE
from tongjianyun.nutrition_sheet import get_nutrition_sheet
from tongjianyun.nutrition_canvas_sheet import spreadsheet_component

FIELDS = {'recipe', 'garden_ratio', 'standard_mode', 'student_groups', 'age_group', 'gender'}
NUTRIENTS = [('energy', '热量', 'kcal'), ('protein', '蛋白质', 'g'), ('calcium', '钙', 'mg'),
             ('vitamin_a', '维生素A', 'μg RAE'), ('vitamin_b1', '维生素B1', 'mg'),
             ('vitamin_b2', '维生素B2', 'mg'), ('vitamin_c', '维生素C', 'mg'),
             ('vitamin_e', '维生素E', 'mg α-TE'), ('niacin', '烟酸', 'mg NE'),
             ('potassium', '钾', 'mg'), ('magnesium', '镁', 'mg'), ('iron', '铁', 'mg'),
             ('zinc', '锌', 'mg'), ('phosphorus', '磷', 'mg'), ('selenium', '硒', 'μg')]
CATEGORIES = dict(zip(
    ('fine_grain', 'coarse_grain', 'pastry', 'dry_bean', 'soy', 'non_green_veg', 'green_veg',
     'fruit', 'dairy', 'egg', 'meat', 'liver', 'fish', 'sugar', 'oil', 'water'),
    ('细粮', '杂粮', '糕点', '干豆类', '豆制品', '非绿蔬菜', '绿橙蔬菜', '水果', '乳类',
     '蛋类', '肉类', '肝', '鱼', '糖类', '油脂', '水')))
BASIS = '按食谱食材分类代表值估算的周日均每生供给量，不是所选单餐或实际摄入量；需结合可食部、烹调损耗与实际就餐复核。'


def nutrition_selection(value):
    clean = {}
    if 'recipe' in value:
        recipe = value['recipe']
        if not isinstance(recipe, str) or not recipe.strip() or len(recipe) > 140:
            frappe.throw('食谱编号无效。')
        clean['recipe'] = recipe.strip()
    try:
        ratio = float(value.get('garden_ratio', 80))
    except (TypeError, ValueError):
        frappe.throw('园内供给目标应为30%—100%。')
    if not isfinite(ratio) or not 30 <= ratio <= 100:
        frappe.throw('园内供给目标应为30%—100%。')
    clean['garden_ratio'] = ratio
    for key, default, choices in (
        ('standard_mode', AUTO_MODE, (AUTO_MODE, MANUAL_MODE)),
        ('age_group', '4–6岁平均', ('4–6岁平均', '4岁', '5岁', '6岁')),
        ('gender', '男女平均', ('男女平均', '男', '女')),
    ):
        item = value.get(key, default)
        if not isinstance(item, str) or item not in choices:
            frappe.throw('营养标准筛选无效。')
        clean[key] = item
    groups = value.get('student_groups', [])
    if (not isinstance(groups, list) or len(groups) > 100
            or any(not isinstance(g, str) or not g.strip() or len(g) > 140 for g in groups)):
        frappe.throw('统计班级筛选无效。')
    clean['student_groups'] = list(dict.fromkeys(g.strip() for g in groups))
    return clean


def number(value, digits=2):
    if value is None:
        return None
    try:
        result = float(value)
        return round(result, digits) if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def percent(value):
    value = number(value, 1)
    return f'{value:g}%' if value is not None else '—'


def table(title, columns, rows, collapsed=False):
    return {'type': 'table', 'title': title, 'columns': columns, 'rows': rows, 'collapsed': collapsed}


def notice(text, warning=False):
    return {'type': 'notice', 'text': text, 'warning': warning}


def nutrition_view(choice):
    recipe = choice.get('recipe')
    if not recipe:
        candidates = visible_rows(RECIPE, ['name', 'title', 'week_start', 'week_end', 'workflow_status'],
                                  {'is_deleted': 0, 'workflow_status': ['!=', '已归档'], 'week_start': ['<=', choice['day']],
                                   'week_end': ['>=', choice['day']]})
        if not candidates['available']:
            raise frappe.PermissionError('没有食谱查看权限。')
        rows = candidates['rows']
        if len(rows) != 1 or candidates['has_more']:
            message = ('该日期没有可见食谱，请先上传或选择对应食谱。' if not rows else
                       '该日期有多份可见食谱，请点选要分析的一份，不自动混合或采用最近一份。')
            components = [notice(message, True)]
            if rows:
                components.append(table('选择要分析的食谱', ['食谱', '开始日期', '结束日期', '状态'], [
                    {'cells': [row['title'] or row['name'], str(row['week_start']), str(row['week_end']), row['workflow_status']],
                     'action': {'label': '分析这份食谱', 'selection': {**choice, 'recipe': row['name']}}} for row in rows]))
            if candidates['has_more']:
                components.append(notice('这里只展示前20份可见食谱，可在对话中指定食谱编号。'))
            return {'title': '周食谱营养分析', 'subtitle': choice['day'], 'components': components,
                    'source': '当前日期的可见食谱，尚未进行营养计算',
                    'summary': {'available': False, 'answer': message}}
        recipe = rows[0]['name']
    check_recipe_scope(recipe, choice['student_groups'])
    doc = read_doc(RECIPE, recipe)
    result = get_nutrition_sheet(recipe=recipe, **{key: choice[key] for key in FIELDS - {'recipe'}})
    choice['recipe'] = recipe
    return project_sheet(result, choice, doc.workflow_status)


def check_recipe_scope(recipe, groups):
    # Shared by read and explicit export; re-check permissions after rendering.
    get_recipe(recipe)
    if groups:
        # Do not let the existing service silently drop a requested inaccessible class.
        visible = set(frappe.get_list('Student Group', filters={'name': ['in', groups], 'disabled': 0},
                                     pluck='name', limit_page_length=0))
        if visible != set(groups):
            raise frappe.PermissionError('部分统计班级不存在、已停用或无权查看。')


@frappe.whitelist(methods=['POST'])
def export_view(selection_json):
    """Explicit user action only; preserve the original export and attachment flow."""
    from tongjianyun.meal_views import selection
    from tongjianyun.scene_access import require_scene_account, require_view_access
    from tongjianyun.nutrition_sheet import export_nutrition_sheet
    require_scene_account()
    choice = selection(selection_json)
    if choice['view'] != 'recipe_nutrition' or not choice.get('recipe'):
        frappe.throw('请先选择并读取要导出的食谱。')
    require_view_access('recipe_nutrition')
    check_recipe_scope(choice['recipe'], choice['student_groups'])
    # The original export may freeze a population snapshot and save a File.
    # Never invoke it during view loading or return another recipe's attachment.
    return export_nutrition_sheet(**{key: choice[key] for key in FIELDS})


def project_sheet(result, choice, status):
    """Use service-provided evaluations, not a second nutrient formula."""
    analysis, recipe = result['analysis'], result['recipe']
    standard = analysis['standard']
    evaluations = analysis.get('nutrient_evaluations') or {}
    nutrients = analysis.get('nutrients') or {}
    population = standard.get('population') or {}
    rule = analysis.get('calculation_rule') or {}
    ingredients = analysis.get('ingredients') or []
    has_amounts = bool(ingredients) and all(number(item.get('grams')) is not None and number(item.get('grams')) >= 0 for item in ingredients) and any(
        number(item.get('grams')) > 0 for item in ingredients)
    def assessment(key):
        value = evaluations.get(key) or {}
        actual = number(value.get('actual', nutrients.get(key))) if has_amounts else None
        target = number(value.get('garden_target'))
        valid = actual is not None and target is not None and target > 0 and value.get('status') in ('适宜', '偏低', '偏高')
        return {**value, 'actual': actual, 'status': value.get('status') if valid else '未评价',
                'percent': value.get('percent') if valid else None}
    assessed = {key: assessment(key) for key, _, _ in NUTRIENTS}
    attention = [{'nutrient': label, 'status': assessed[key]['status']} for key, label, _ in NUTRIENTS
                 if assessed[key]['status'] in ('偏低', '偏高')]
    unknown = [label for key, label, _ in NUTRIENTS if assessed[key]['status'] == '未评价']
    warnings = list(population.get('warnings') or [])
    if status != '已发布':
        warnings.insert(0, f'食谱状态：{status or "待核对"}。本次仅分析，不发布食谱或创建采购单。')
    if not str(recipe.get('week_start', '')) <= choice['day'] <= str(recipe.get('week_end', '')):
        warnings.append('指定食谱不覆盖顶部业务日期；以下分析以标题中的食谱日期为准。')
    if not has_amounts:
        warnings.append('食材用量缺失或不完整，暂不能评价营养；未填写不代表实际摄入为零。')
    if unknown:
        warnings.append('部分营养素未配置评价或缺少数据，以“— / 未评价”标示，不当作零或偏低。')
    components = []
    if warnings:
        components.append(notice(' '.join(warnings), True))
    items = []
    for key, label, unit in NUTRIENTS[:3]:
        evaluation = assessed[key]
        items.append({'label': label, 'value': evaluation['actual'], 'unit': unit,
                      'target': number(evaluation.get('garden_target')), 'status': evaluation['status']})
    headline = ('先补充食材用量，再做营养分析' if not has_amounts else
                f'{len(attention)} 项指标需要关注' if attention else
                '部分指标还需核对' if unknown else '已评价指标处于参考范围')
    components.append({'type': 'nutrition_overview', 'mode': 'sheet', 'headline': headline,
                       'state': 'unknown' if not has_amounts else 'attention' if attention else 'unknown' if unknown else 'good',
                       'items': items, 'attention': attention, 'unknown_count': len(unknown),
                       'ingredient_count': len(ingredients), 'day_count': analysis.get('day_count'),
                       'selection': dict(choice), 'can_export': has_amounts})
    components.append(spreadsheet_component(analysis, assessed, has_amounts))
    components.append(table(f'全部食材与计算口径 · {len(ingredients)} 种（含表外油脂、水）', ['食材', '分类', '日均每生用量（g）', '数据口径'], [
        {'cells': [item['name'], CATEGORIES.get(item['category'], item['category']), number(item.get('grams')), item.get('basis') or '分类代表值']}
        for item in ingredients], True))
    components.append(notice(BASIS))
    return {'title': '周食谱营养分析',
            'subtitle': f'{recipe.get("title") or recipe["name"]} · {recipe.get("week_start")} — {recipe.get("week_end")} · {status} · {standard.get("profile", "未标明标准")} · 园内目标 {percent(choice["garden_ratio"])}',
            'components': components, 'source': f'原周食谱营养分析服务 · {standard.get("source", "")}；按当前账号权限读取',
            'summary': {'available': True, 'recipe': recipe['name'], 'day_count': analysis.get('day_count'),
                        'attention': attention, 'unknown_nutrients': unknown, 'analysis_ready': has_amounts,
                        'basis': BASIS, 'warnings': warnings,
                        'answer': '已展示整周营养估算；' + ('需关注：' + '、'.join(item['nutrient'] + item['status'] for item in attention) if attention else '请查看指标与计算口径。')}}
