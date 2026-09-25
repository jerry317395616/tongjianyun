"""Site-wide business discovery and native Frappe views, without copying business data.

The canvas receives same-origin routes, never arbitrary URLs, HTML, SQL or credentials.
Native forms/reports keep Frappe's own permissions, validations, workflows and actions.
"""
from pathlib import Path
from urllib.parse import quote

import frappe

ROOT = Path('/home/zyd/frappe')
VIEWS = {'project_catalog': '项目总览', 'frappe_catalog': '全部 Frappe 业务',
         'frappe_doctype': '业务单据', 'frappe_document': '业务详情',
         'frappe_report': '业务报表', 'frappe_page': '业务页面', 'frappe_workspace': '业务工作区'}
FIELDS = {'app', 'module', 'doctype', 'document', 'report', 'page', 'workspace', 'kind'}
KINDS = {'doctype': '单据与资料', 'report': '报表', 'page': '业务页面', 'workspace': '工作区'}
PAGE_SIZE = 30


def label(value):
    # Reuse the existing I-ONE/site Chinese translations, not another local dictionary.
    return frappe._(str(value or ''), lang='zh')


def selection(value, default_day=None, default_meal='lunch'):
    from tongjianyun.business_views import text_arg
    from tongjianyun.meal_scene import business_day, meal_key
    allowed = {'view', 'day', 'meal', 'components'} | {
        'project_catalog': set(), 'frappe_catalog': {'app', 'module', 'kind', 'keyword', 'offset'},
        'frappe_doctype': {'doctype'}, 'frappe_document': {'doctype', 'document'},
        'frappe_report': {'report'}, 'frappe_page': {'page'}, 'frappe_workspace': {'workspace'},
    }[value['view']]
    if set(value) - allowed:
        frappe.throw('此项目视图不接受这些参数。')
    clean = {'day': str(business_day(value.get('day') or default_day)), 'meal': meal_key(value.get('meal') or default_meal)}
    for key in allowed - {'view', 'day', 'meal', 'components', 'offset'}:
        if key in value:
            clean[key] = text_arg(value, key)
    for key in {'frappe_doctype': ('doctype',), 'frappe_document': ('doctype', 'document'),
                'frappe_report': ('report',), 'frappe_page': ('page',), 'frappe_workspace': ('workspace',)}.get(value['view'], ()):
        if key not in clean:
            frappe.throw('请从业务目录选择目标，不要猜测业务编号。')
    if clean.get('kind') and clean['kind'] not in KINDS:
        frappe.throw('业务类型无效。')
    if value['view'] == 'frappe_catalog':
        offset = value.get('offset', 0)
        if isinstance(offset, bool) or not str(offset).isdigit() or not 0 <= int(offset) <= 100000:
            frappe.throw('分页位置无效。')
        clean['offset'] = int(offset)
    return clean


def _action(label, choice):
    return {'label': label, 'selection': choice}


def _table(title, columns, rows):
    return {'type': 'table', 'title': title, 'columns': columns, 'rows': rows}


def _notice(text, warning=False):
    return {'type': 'notice', 'text': text, 'warning': warning}


def _context(choice):
    return {k: choice[k] for k in ('day', 'meal') if k in choice}


def module_apps():
    from frappe.app_state import get_disabled_modules
    apps = set(frappe.get_installed_apps())
    disabled = set(get_disabled_modules())
    blocked = set(frappe.get_cached_doc('User', frappe.session.user).get_blocked_modules())
    return {r.name: r.app_name for r in frappe.get_all('Module Def', fields=['name', 'app_name'])
            if r.app_name in apps and r.name not in disabled and r.name not in blocked}


def _doctype(name, modules):
    meta = frappe.get_meta(name)
    if meta.module not in modules or meta.istable or not frappe.has_permission(name, 'read'):
        raise frappe.PermissionError('业务不存在、未启用或无读取权限。')
    return meta


def _report(name, modules):
    doc = frappe.get_doc('Report', name)
    if doc.disabled or doc.module not in modules or not doc.is_permitted():
        raise frappe.PermissionError('无权查看此报表。')
    if doc.ref_doctype:
        _doctype(doc.ref_doctype, modules)
        if not frappe.has_permission(doc.ref_doctype, 'report'):
            raise frappe.PermissionError('没有对应报表权限。')
    # Resolve and check Custom Reports through the original Report implementation too.
    from frappe.desk.query_report import get_report_doc
    get_report_doc(name)
    return doc


def _page(name, modules):
    doc = frappe.get_doc('Page', name)
    if doc.module not in modules or not doc.is_permitted():
        raise frappe.PermissionError('没有此页面的使用权限。')
    return doc


def _workspaces(modules):
    from frappe.desk.desktop import get_workspaces
    # Publishing switches from a CLI principal to the task owner. Frappe's
    # request_cache is not cleared by set_user; never reuse another actor's result.
    fresh = getattr(get_workspaces, '__wrapped__', get_workspaces)()
    return [row for row in fresh['pages'] if row.module in modules
            and not row.get('is_hidden') and not row.get('external_link')
            and row.get('type') not in {'Link', 'URL'}]


def entry_selection(kind, name, choice):
    return {'view': 'frappe_' + kind, kind: name, **_context(choice)}


def catalog_entries(choice, modules):
    """Metadata only. Re-check permissions per actor; no shared actor-result cache."""
    entries = []
    kinds = [choice['kind']] if choice.get('kind') else list(KINDS)
    keyword = (choice.get('keyword') or '').casefold()
    def matches(name, module, title=''):
        return module in modules and (not keyword or keyword in ' '.join((name, title or '', label(name), module, label(module))).casefold())
    if 'doctype' in kinds:
        for row in frappe.get_all('DocType', filters={'istable': 0}, fields=['name', 'module', 'issingle']):
            if not matches(row.name, row.module):
                continue
            try:
                _doctype(row.name, modules)
            except frappe.PermissionError:
                continue
            entries.append({'kind': 'doctype', 'name': row.name, 'title': label(row.name), 'module': row.module,
                            'note': '原生设置表单' if row.issingle else '原生列表、表单及工作流'})
    if 'report' in kinds:
        for row in frappe.get_all('Report', filters={'disabled': 0}, fields=['name', 'module']):
            if not matches(row.name, row.module):
                continue
            try:
                _report(row.name, modules)
            except (frappe.PermissionError, frappe.DoesNotExistError):
                continue
            entries.append({'kind': 'report', 'name': row.name, 'title': label(row.name), 'module': row.module, 'note': '原生报表及筛选'})
    if 'page' in kinds:
        for row in frappe.get_all('Page', fields=['name', 'title', 'module']):
            if not matches(row.name, row.module, row.title):
                continue
            try:
                _page(row.name, modules)
            except frappe.PermissionError:
                continue
            entries.append({'kind': 'page', 'name': row.name, 'title': label(row.title or row.name), 'module': row.module, 'note': '原应用页面'})
    if 'workspace' in kinds:
        for row in _workspaces(modules):
            if matches(row.name, row.module, row.get('title')):
                entries.append({'kind': 'workspace', 'name': row.name, 'title': label(row.name), 'module': row.module, 'note': '原应用工作区'})
    return sorted(entries, key=lambda r: (modules[r['module']], r['module'], r['kind'], r['name']))


def catalog_view(choice):
    modules = module_apps()
    if choice.get('app'):
        if choice['app'] not in frappe.get_installed_apps():
            frappe.throw('该应用没有安装到当前站点；源码存在不等于业务可用。')
        modules = {k: v for k, v in modules.items() if v == choice['app']}
    if choice.get('module'):
        if choice['module'] not in modules:
            raise frappe.PermissionError('模块不存在、已停用或不在所选应用的可见范围。')
        modules = {choice['module']: modules[choice['module']]}
    entries = catalog_entries(choice, modules)
    ctx = _context(choice)
    components = [_notice('这里覆盖当前站点已安装应用的原生业务，不局限于童健云。打开业务后，原系统继续校验权限；目录数量是入口数，不是业务记录数。')]
    actions = [_action('所有应用', {'view': 'frappe_catalog', **ctx}), _action('服务器项目', {'view': 'project_catalog', **ctx})]
    displayed = {}
    if not any(choice.get(k) for k in ('app', 'module', 'keyword', 'kind')):
        apps = sorted(frappe.get_installed_apps())
        displayed = {'display_level': 'applications', 'displayed_apps': apps}
        components.append(_table('选择应用', ['应用', '可见业务入口', '可见模块'], [
            {'cells': [app, sum(1 for e in entries if modules[e['module']] == app), sum(1 for a in modules.values() if a == app)],
             'action': _action('查看应用', {'view': 'frappe_catalog', 'app': app, **ctx})} for app in apps]))
    elif choice.get('app') and not any(choice.get(k) for k in ('module', 'keyword', 'kind')):
        displayed = {'display_level': 'modules', 'displayed_modules': sorted(modules)}
        components.append(_table('选择模块', ['模块', '名称', '可见业务入口'], [
            {'cells': [label(name), name, sum(1 for e in entries if e['module'] == name)],
             'action': _action('查看模块', {'view': 'frappe_catalog', 'app': choice['app'], 'module': name, **ctx})} for name in sorted(modules)]))
    else:
        page = entries[choice['offset']:choice['offset'] + PAGE_SIZE]
        displayed = {'display_level': 'entries', 'page_entries': [
            {'kind': e['kind'], 'name': e['name'], 'module': e['module']} for e in page]}
        components.append(_table('可用业务', ['业务', '原始名称', '类型', '模块', '打开方式'], [
            {'cells': [e['title'], e['name'], KINDS[e['kind']], label(e['module']), e['note']],
             'action': _action('打开业务', entry_selection(e['kind'], e['name'], choice))} for e in page]))
        if choice['offset']:
            actions.append(_action('上一页', {**choice, 'offset': max(0, choice['offset'] - PAGE_SIZE)}))
        if choice['offset'] + PAGE_SIZE < len(entries):
            actions.append(_action('下一页', {**choice, 'offset': choice['offset'] + PAGE_SIZE}))
        components.append(_notice(f'当前筛选共 {len(entries)} 个可见入口，本页 {len(page)} 个。没有入口可能是权限或模块状态原因，不代表业务数量为零。'))
    return {'title': '全部 Frappe 业务', 'subtitle': ' · '.join([frappe.local.site] + [choice[k] for k in ('app', 'module', 'keyword') if choice.get(k)]),
            'components': components, 'actions': actions, 'source': '当前站点已安装应用、Module Def、DocType、Report、Page 与原工作区权限',
            'summary': {'installed_apps': frappe.get_installed_apps(), 'visible_entry_count': len(entries),
                        **displayed,
                        'basis': '仅业务入口元数据，不包含单据、人员或密钥值'}}


def slug(name):
    return quote(name.lower().replace(' ', '-'), safe='')


def native_view(choice):
    modules = module_apps()
    view = choice['view']
    if view in {'frappe_doctype', 'frappe_document'}:
        doc = _doctype(choice['doctype'], modules)
        route = '/desk/' + slug(doc.name)
        if view == 'frappe_document':
            record = frappe.get_doc(doc.name, choice['document'])
            record.check_permission('read')
            route += '/' + quote(record.name, safe='')
        title = label(doc.name)
        module = doc.module
    elif view == 'frappe_report':
        doc = _report(choice['report'], modules)
        route = ('/desk/' + slug(doc.ref_doctype) + '/view/report/' if doc.report_type == 'Report Builder' else '/desk/query-report/') + quote(doc.name, safe='')
        title, module = label(doc.name), doc.module
    elif view == 'frappe_page':
        doc = _page(choice['page'], modules)
        route = '/desk/' + quote(doc.name, safe='')
        title, module = label(doc.title or doc.name), doc.module
    else:
        matches = [r for r in _workspaces(modules) if r.name == choice['workspace']]
        if len(matches) != 1:
            raise frappe.PermissionError('此工作区不可用。')
        doc = matches[0]
        route = '/desk/' + ('' if doc.public else 'private/') + slug(doc.name)
        title, module = label(doc.name), doc.module
    return {'title': title, 'subtitle': f'{frappe.local.site} · {modules[module]} · {label(module)}',
            'components': [_notice('原生业务界面：新建、编辑、审批等继续使用原系统权限与校验。顶部膳食日期不自动作为此业务的筛选条件。'),
                           {'type': 'frappe_frame', 'route': route, 'title': title}],
            'actions': [_action('返回模块', {'view': 'frappe_catalog', 'app': modules[module], 'module': module, **_context(choice)})],
            'source': '原 Frappe 应用页面；只打开页面，不代表已经查询完毕或执行任何业务操作',
            'summary': {'opened': True, 'app': modules[module], 'module': module, 'title': title,
                        'answer': '已打开原生业务页面；未自动新建、编辑、审批或执行查询。'}}


def project_directories(root=ROOT):
    result = []
    candidates = [(p, '顶层项目/目录') for p in root.iterdir() if p.is_dir() and (not p.name.startswith('.') or p.name == '.codex-deepseek')]
    apps = root / 'native-bench' / 'apps'
    if apps.is_dir():
        candidates += [(p, 'Frappe 应用源码') for p in apps.iterdir() if p.is_dir()]
    for path, kind in sorted(candidates, key=lambda r: str(r[0])):
        if not path.resolve().is_relative_to(root.resolve()):
            continue
        repo = (path / '.git').exists()
        result.append({'name': path.name, 'path': str(path), 'kind': kind,
                       'status': 'Git 项目' if repo else '目录（运行状态未核验）'})
    return result


def projects_view(choice):
    projects = project_directories()
    return {'title': 'Frappe 项目总览', 'subtitle': str(ROOT) + ' · Codex 项目根目录',
            'components': [_notice('Codex 可按你的需求处理此目录下各项目。先识别目标项目和站点，再读取对应规则及接口；备份、配置、日志目录只列索引，不扫描或公开内容。'),
                           _table('项目与目录', ['项目', '类别', '路径', '源码状态'], [
                               {'cells': [p['name'], p['kind'], p['path'], p['status']]} for p in projects]),
                           _notice('当前网页业务身份只对应当前 Frappe 站点。其他项目仅有源码不等于已安装业务；跨站点账号和数据不自动共用。', True)],
            'actions': [_action('全部 Frappe 业务', {'view': 'frappe_catalog', **_context(choice)})],
            'source': '固定项目根目录及 native-bench/apps 的只读目录索引；不读取配置、仓库凭据或文件内容',
            'summary': {'root': str(ROOT), 'site': frappe.local.site, 'installed_apps': frappe.get_installed_apps(), 'projects': projects}}


def get_view(choice):
    if choice['view'] == 'project_catalog':
        return projects_view(choice)
    if choice['view'] == 'frappe_catalog':
        return catalog_view(choice)
    return native_view(choice)


def tool_instruction():
    return ('\n【全部 Frappe 项目与业务】服务器工作根目录为 /home/zyd/frappe，不局限于童健云。'
            '先 --view project_catalog 查看项目目录；用户说“全部业务”时必须用 --view frappe_catalog 查看当前站点全部已安装应用，不再使用只含常用业务的 business_catalog。'
            '--view frappe_catalog [--app erpnext|hrms|education|frappe|ione_core|ione_agent|tongjianyun] '
            '[--module 模块原名] [--kind doctype|report|page|workspace] [--keyword 关键词] [--offset 0]。'
            '目录会回传原始名称，找不到中文名称时可用英文业务术语搜索；不能只因不在童健云52项清单就说不支持。'
            '打开现有业务：--view frappe_doctype --doctype 原始类型名；--view frappe_document --doctype 类型 --document 精确编号；'
            '--view frappe_report --report 报表原名；--view frappe_page --page 页面名；--view frappe_workspace --workspace 工作区原名。'
            '名称必须从实际元数据确认；报表需用户/代理填原生筛选，不把页面打开误说为数据已统计或操作已完成。'
            '已有童健云专用视图仍优先使用；其他业务使用原生模块，不临时拼假报表。'
            '执行用户要求的业务写操作时，使用对应应用的原服务/Document校验与工作流，按当前登录用户权限核验；'
            '不得用root权限、ignore_permissions或直接SQL绕过业务权限。删除、取消、付款、批量覆盖等高影响操作先核对目标并取得明确指令。'
            '开发跨项目功能前读取该目录的AGENTS.md及父级规则，保留未提交改动；不得因全项目范围就直接修改所有应用。'
            '当前Native Bench业务定制仍通过童健云扩展点，数据库结构变更另行确认。'
            '配置、密钥、银行/医疗/生物特征原文不能写入对话或发送到模型。跨站点不冒用当前网页身份。')
