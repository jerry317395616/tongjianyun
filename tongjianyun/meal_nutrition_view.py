"""Read-only projection of the existing weekly nutrition sheet for the canvas."""
from math import isfinite

import frappe

from tongjianyun.meal_scene import RECIPE, get_recipe, read_doc, visible_rows
from tongjianyun.nutrition_population import AUTO_MODE, MANUAL_MODE
from tongjianyun.nutrition_sheet import get_nutrition_sheet

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
    # Preserve the scene's row-level checks, then call the original calculation.
    get_recipe(recipe)
    doc = read_doc(RECIPE, recipe)
    groups = choice['student_groups']
    if groups:
        # Do not let the existing service silently drop a requested inaccessible class.
        visible = set(frappe.get_list('Student Group', filters={'name': ['in', groups], 'disabled': 0},
                                     pluck='name', limit_page_length=0))
        if visible != set(groups):
            raise frappe.PermissionError('部分统计班级不存在、已停用或无权查看。')
    result = get_nutrition_sheet(recipe=recipe, **{key: choice[key] for key in FIELDS - {'recipe'}})
    choice['recipe'] = recipe
    return project_sheet(result, choice, doc.workflow_status)


def project_sheet(result, choice, status):
    """Use service-provided evaluations, not a second nutrient formula."""
    analysis, recipe = result['analysis'], result['recipe']
    standard = analysis['standard']
    evaluations = analysis.get('nutrient_evaluations') or {}
    nutrients = analysis.get('nutrients') or {}
    population = standard.get('population') or {}
    rule = analysis.get('calculation_rule') or {}
    warnings = list(population.get('warnings') or [])
    if status != '已发布':
        warnings.insert(0, f'食谱状态：{status or "待核对"}。本次仅分析，不发布食谱或创建采购单。')
    if not str(recipe.get('week_start', '')) <= choice['day'] <= str(recipe.get('week_end', '')):
        warnings.append('指定食谱不覆盖顶部业务日期；以下分析以标题中的食谱日期为准。')
    if not analysis.get('ingredients'):
        warnings.append('食谱尚无可分析的食材带量，不能把零估算值认定为实际摄入为零。')
    if any(key not in evaluations for key, _, _ in NUTRIENTS):
        warnings.append('部分营养素未配置评价或缺少数据，以“— / 未评价”标示，不当作零或偏低。')
    components = []
    if warnings:
        components.append(notice(' '.join(warnings), True))
    items = []
    for key, label, unit in NUTRIENTS[:3]:
        evaluation = evaluations.get(key, {})
        items.append({'label': label + ' · 日均每生估算', 'value': number(evaluation.get('actual', nutrients.get(key))),
                      'unit': unit, 'note': evaluation.get('status') or '未评价'})
    items.append({'label': '纳入自动标准计算', 'value': population.get('student_count'), 'unit': '人',
                  'note': '按学生档案计算' if population else '当前为手动估算口径'})
    components.append({'type': 'stats', 'items': items})
    components.append(notice(analysis.get('conclusion') or '暂无结论。'))
    rows = []
    for key, label, unit in NUTRIENTS:
        e = evaluations.get(key, {})
        state = e.get('status') or '未评价'
        rows.append({'cells': [f'{label}（{unit}）', number(e.get('full_target')), number(e.get('garden_target')),
                               number(e.get('actual', nutrients.get(key))), percent(e.get('percent')), state],
                     'evaluation': state})
    components.append(table('营养素对照 · 日均每生', ['营养素', '全日标准', '在园目标', '食谱估算供给', '目标占比', '评价'], rows))
    macro_rows = []
    for key, label in (('carbohydrate', '碳水化合物供能'), ('fat', '脂肪供能'), ('protein', '蛋白质供能')):
        actual = number((analysis.get('macro_energy_ratio') or {}).get(key))
        bounds = (rule.get('macro_ranges') or {}).get(key) or standard.get(key + '_energy_range')
        state = '未评价' if actual is None or not bounds else '偏低' if actual < bounds[0] else '偏高' if actual > bounds[1] else '适宜'
        macro_rows.append({'cells': [label, f'{bounds[0]}%—{bounds[1]}%' if bounds else '—', percent(actual), state], 'evaluation': state})
    protein = number(nutrients.get('protein'))
    for key, label, target_key in (('animal_protein', '动物蛋白占总蛋白', 'animal_protein_target'),
                                   ('animal_soy_protein', '动豆蛋白占总蛋白', 'animal_soy_protein_target')):
        actual = number(analysis.get(key))
        ratio = actual / protein * 100 if protein and actual is not None else None
        target = number(rule.get(target_key))
        state = '未评价' if ratio is None or target is None else '适宜' if ratio >= target else '偏低'
        macro_rows.append({'cells': [label, f'≥{percent(target)}' if target is not None else '—', percent(ratio), state], 'evaluation': state})
    components.append(table('供能结构与蛋白质构成', ['项目', '参考比例', '食谱估算比例', '评价'], macro_rows, True))
    components.append(table('各餐热量分配', ['餐次', '原分析参考比例', '食谱估算比例'], [
        {'cells': [label, percent((analysis.get('meal_standard') or {}).get(slot)), percent((analysis.get('meal_ratio') or {}).get(slot))]}
        for slot, label in zip(('breakfast', 'morningSnack', 'lunch', 'snack', 'dinner'), ('早餐', '早点', '午餐', '午点', '晚餐'))], True))
    components.append(table('食物分类用量 · 日均每生（g）', ['食物分类', '估算用量'], [
        {'cells': [CATEGORIES.get(key, key), number(value)]} for key, value in (analysis.get('category_totals') or {}).items()], True))
    ingredients = analysis.get('ingredients') or []
    components.append(table(f'食材明细 · {len(ingredients)} 种', ['食材', '分类', '日均每生用量（g）', '数据口径'], [
        {'cells': [item['name'], CATEGORIES.get(item['category'], item['category']), number(item.get('grams')), item.get('basis') or '分类代表值']}
        for item in ingredients], True))
    components.append(table('补充指标与计算口径', ['项目', '结果'], [
        {'cells': ['钙/磷比例', number(analysis.get('calcium_phosphorus_ratio'))]},
        *[{'cells': [label, number(nutrients.get(key))]} for key, label in
          (('carotene', '胡萝卜素（μg）'), ('fiber', '膳食纤维（g）'), ('cholesterol', '胆固醇（mg）'))],
        {'cells': ['分析天数', analysis.get('day_count')]},
        {'cells': ['原报告总人日数（非实际就餐确认）', analysis.get('person_days')]},
        {'cells': ['标准参考日期', population.get('reference_date') or recipe.get('week_start')]},
        {'cells': ['计算规则', f'{rule.get("title", "未标明")} · {rule.get("version", "—")}']},
    ], True))
    components.append(notice(BASIS))
    attention = [{'nutrient': label, 'status': evaluations[key]['status']} for key, label, _ in NUTRIENTS
                 if evaluations.get(key, {}).get('status') not in (None, '适宜')]
    return {'title': '周食谱营养分析',
            'subtitle': f'{recipe.get("title") or recipe["name"]} · {recipe.get("week_start")} — {recipe.get("week_end")} · {status} · {standard.get("profile", "未标明标准")} · 园内目标 {percent(choice["garden_ratio"])}',
            'components': components, 'source': f'原周食谱营养分析服务 · {standard.get("source", "")}；按当前账号权限读取',
            'summary': {'available': True, 'recipe': recipe['name'], 'day_count': analysis.get('day_count'),
                        'attention': attention, 'basis': BASIS, 'warnings': warnings,
                        'answer': '已展示整周营养估算；' + ('需关注：' + '、'.join(item['nutrient'] + item['status'] for item in attention) if attention else '请查看指标与计算口径。')}}
