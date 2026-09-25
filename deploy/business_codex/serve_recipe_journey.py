"""Explicit isolated upload -> real Codex/RQ -> native recipe -> SSE journey.

check is read-only. prepare records/restores only business_codex_enabled,
business_codex_scene_mode and the business queue config. No account, password,
role or share is changed. Every command requires an explicit run UUID.
The original browser, upload_file, login/CSRF, service.run_task, worker, model,
recipe adapter and transaction remain real. The worker guard only denies; a
trusted read observer records finite evidence after successful original reads.

Only the existing synthetic QA manager and one exact synthetic TXT are allowed.
One new draft in 2037-01-12..18 is allowed, with no ingredient rows (the native
empty-source check prevents a second ingredient-matching model job). The prior
2037-01-05..11 recipe must exist and all original records remain protected.
No execution, upload or task is retried automatically. Evidence and records are
retained. Backend/SSE byte evidence never claims the browser rendered a view.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from dataclasses import asdict
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import select
import signal
import socket
import stat
import sys
from urllib.parse import parse_qs
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import serve_business_journey as previous
import check_recipe_native as native

old, qa = previous.old, previous.qa
OWNER = native.MANAGER
DAY, END, MEAL = '2037-01-12', '2037-01-18', 'lunch'
PARENT_RECIPE = 'SCENE-20370105-7D6EEE8E82F4C13BE42E0A5A34FAAFE5'
PARENT_REVISION = '2026-09-26 00:07:19.740149'
DEPENDENCIES = qa.ROOT / 'python-deps-attachments-v1'
ROOT = qa.ROOT / 'recipe-journeys'
ACTIVE = qa.ROOT / 'recipe-journey-active.json'
LOCK = qa.ROOT / 'recipe-journey-management.lock'
PROFILE = 'recipe-journey-v1'
SOURCE_FILES = tuple(dict.fromkeys((*previous.SOURCE_FILES, *native.SOURCE_FILES,
    'tongjianyun/www/tongjianyun_meal_scene.py', 'deploy/business_codex/serve_recipe_journey.py')))
LOADED_HASHES = {name: hashlib.sha256((HERE.parent.parent / name).read_bytes()).hexdigest()
                 for name in SOURCE_FILES}
API = old.API
CONFIG_VALUES = {'business_codex_enabled': 1, 'business_codex_scene_mode': 'business'}
FILE_FIELDS = ('file_name', 'file_url', 'file_size', 'is_private', 'is_folder', 'owner',
               'attached_to_doctype', 'attached_to_name', 'attached_to_field', 'modified')


def digest(value):
    return previous.digest(value)


def folder(run_id):
    if not old.canonical(run_id):
        raise ValueError('Explicit canonical run UUID required')
    return qa.safe_target(ROOT / run_id)


def pin(record=None):
    current = {name: qa.digest_file(qa.SOURCE / name) for name in SOURCE_FILES}
    if current != LOADED_HASHES or record is not None and current != record['source_sha256']:
        raise PermissionError('Candidate changed; preserve the run and stop')
    return current


def environment():
    if os.name != 'posix' or os.geteuid() == 0 or sys.flags.optimize:
        raise PermissionError('Original non-root Linux site user required')
    if Path(__file__).resolve() != qa.SOURCE / 'deploy/business_codex/serve_recipe_journey.py':
        raise PermissionError('Fixed reviewed candidate only')
    os.environ.clear()
    os.environ.update(PATH='/usr/bin:/bin', LANG='C.UTF-8', PYTHONDONTWRITEBYTECODE='1')
    pin()
    previous.fixture.fixture_guard()
    dependency = qa.safe_target(DEPENDENCIES)
    info = dependency.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise PermissionError('Unsafe fixed QA parser dependency directory')
    sys.path.insert(0, str(dependency))  # Same trusted path in web AND real RQ process.
    return qa.runtime()


def load(run_id, *, ready=False):
    record = old.private_read(folder(run_id) / 'run.json')
    if (record.get('run_id') != run_id or record.get('site') != qa.SITE
            or record.get('owner') != OWNER or record.get('profile') != PROFILE
            or record.get('day') != DAY or record.get('week_end') != END):
        raise PermissionError('Invalid fixed recipe run identity')
    pin(record)
    if ready:
        config = qa.config_guard()
        if (record.get('state') != 'prepared' or old.private_read(ACTIVE) != {'run_id': run_id}
                or config.get('unified_browser_acceptance') != 1 or config.get('maintenance_mode')
                or any(config.get(key) != value for key, value in CONFIG_VALUES.items())
                or config.get('workers', {}).get(old.QUEUE) != {'timeout': -1}):
            raise PermissionError('Exact prepared recipe run required')
    return record


def filename(run_id):
    if not old.canonical(run_id):
        raise ValueError('Exact run UUID required')
    return 'recipe-journey-' + run_id + '.txt'


def payload(run_id):
    filename(run_id)
    return {'recipe': {'title': 'SYNTHETIC RECIPE ' + run_id, 'weekStart': DAY, 'weekEnd': END},
            'days': [{'date': DAY, 'day': '星期一', 'portions': [{'slot': MEAL,
                'dishes': ['合成验收菜品'], 'dishIngredientRows': []}]}]}


def upload_bytes(run_id):
    # Exact user-supplied data, not an instruction to the model or tool schema.
    value = payload(run_id)
    return ('合成食谱验收数据\n标题：' + value['recipe']['title']
        + '\n自然周开始：' + DAY + '\n自然周结束：' + END
        + '\n日期：' + DAY + '\n星期：星期一\n餐次：午餐\n菜品：合成验收菜品'
        + '\n食材明细：未填写（空列表，不代表用量为零）\n').encode('utf-8')


def requested_message(run_id):
    return ('读取上传文件并保存本周草稿，左侧显示。只新建 ' + DAY + ' 至 ' + END
        + ' 这一自然周，标题和唯一日期午餐菜品以附件为准，食材明细留空，不推测食材或数量。'
        + '先读取附件并检查本周，已有食谱则停止，不能覆盖或另存副本；不发布，不建档物料，不改旧周。'
        + '本次合成验收标识：' + str(uuid.UUID(run_id)) + '。')


def readonly(frappe, callback):
    from check_worker_live import readonly_adapter
    def guarded():
        native.account_guard(frappe, OWNER)
        return callback()
    return readonly_adapter(frappe).run_check(OWNER, guarded)


def week_rows(frappe, start=DAY, end=END):
    rows = frappe.db.sql('''SELECT name FROM `tabTongjianyun Recipe`
        WHERE week_start <= %s AND COALESCE(week_end, week_start) >= %s
        ORDER BY name LIMIT 1001''', (end, start))
    if len(rows) > 1000:
        raise PermissionError('Bounded recipe week exceeded')
    return [row[0] for row in rows]


def assert_empty(frappe):
    if week_rows(frappe) or frappe.db.exists('Tongjianyun Recipe Dish', {'meal_date': ['between', [DAY, END]]}):
        raise PermissionError('New synthetic week is not empty; never overwrite or select another week')


def protected_parent(frappe):
    from tongjianyun import meal_scene
    names = week_rows(frappe, native.DAY, native.END)
    if names != [PARENT_RECIPE]:
        raise PermissionError('The prior fixed synthetic week must have exactly one retained recipe')
    parent = meal_scene.get_recipe(names[0])
    doc = frappe.get_doc('Tongjianyun Recipe', names[0])
    if (parent['revision'] != PARENT_REVISION or doc.owner != OWNER or doc.workflow_status != '草稿' or doc.is_deleted
            or str(doc.week_start) != native.DAY or str(doc.week_end) != native.END
            or not str(doc.title).startswith('SYNTHETIC QA ')
            or not any(portion.get('dishes') for day in parent['payload']['days'] for portion in day['portions'])):
        raise PermissionError('Prior synthetic recipe is missing or not the preserved nonempty draft')
    return {'recipe': names[0], 'sha256': digest(parent['payload'])}


def snapshot(frappe):
    def read():
        recipes = native.baseline(frappe)
        files = {}
        names = frappe.get_all('File', pluck='name', order_by='name', limit_page_length=2001)
        if len(names) > 2000:
            raise PermissionError('File diagnostic bound exceeded')
        for name in names:
            doc = frappe.get_doc('File', name)
            files[name] = digest({key: doc.get(key) for key in FILE_FIELDS})
        user = frappe.get_doc('User', OWNER)
        # Never include passwords, reset tokens, cookies or session secrets.
        account = {key: user.get(key) for key in previous.USER_FIELDS}
        account['roles'] = [row.role for row in user.roles]
        account['block_modules'] = [row.module for row in user.block_modules]
        return {'site': qa.SITE, 'recipes': recipes, 'files': files,
                'account': previous.flatten(account), 'parent': protected_parent(frappe)}
    return readonly(frappe, read)


def difference(before, after, *, file_id=None, recipe=None):
    if before['site'] != qa.SITE or after['site'] != qa.SITE:
        raise PermissionError('QA baseline site mismatch')
    prior, current = before['files'], after['files']
    files_ok = (all(current.get(key) == value for key, value in prior.items())
        and set(current) - set(prior) == ({file_id} if file_id else set())
        and (file_id is None or file_id not in prior))
    fields = [name for name in set(before['account']) | set(after['account'])
              if before['account'].get(name) != after['account'].get(name)]
    auth = {'/' + name for name in previous.AUTH_FIELDS}
    unexpected = sorted(set(fields) - auth)
    recipes_ok = native.unchanged(before['recipes'], after['recipes'], {recipe} if recipe else set())
    parent_ok = before['parent'] == after['parent']
    return {'protected_passed': files_ok and recipes_ok and parent_ok and not unexpected,
            'files_only_expected_new': files_ok, 'recipes_only_expected_new': recipes_ok,
            'previous_recipe_unchanged': parent_ok, 'unexpected_account_fields': unexpected,
            'authentication_metadata_fields': sorted(set(fields) & auth)}


def manager_tasks():
    path = qa.SITES / qa.SITE / 'private/business-codex/tasks/business-tasks.sqlite3'
    with previous.read_db(path) as db:
        rows = db.execute('SELECT task_id FROM tasks WHERE owner=? ORDER BY task_id LIMIT 1001', (OWNER,)).fetchall()
    if len(rows) > 1000:
        raise PermissionError('Task history bound exceeded')
    return [row[0] for row in rows]


def registered_task(record):
    try:
        value = old.private_read(folder(record['run_id']) / 'attempt.json')
    except FileNotFoundError:
        return None
    if (value.get('owner') != OWNER or value.get('site') != qa.SITE or value.get('run_id') != record['run_id']
            or not old.canonical(value.get('request_id'))):
        raise PermissionError('Invalid reserved HTTP task')
    return value['request_id']


def history_allowed(record):
    task = registered_task(record)
    return set(manager_tasks()) <= ({task} if task else set())


def uploaded(record):
    value = old.private_read(folder(record['run_id']) / 'upload.json')
    if (value.get('run_id') != record['run_id'] or value.get('site') != qa.SITE or value.get('owner') != OWNER
            or value.get('filename') != filename(record['run_id'])
            or value.get('sha256') != hashlib.sha256(upload_bytes(record['run_id'])).hexdigest()
            or type(value.get('file_id')) is not str or not 1 <= len(value['file_id']) <= 140):
        raise PermissionError('Upload receipt is not this run\'s private synthetic File')
    return value


def selection_allowed(value):
    if isinstance(value, str):
        try:
            value = qa.unique_json(value)
        except (ValueError, TypeError):
            return False
    return (type(value) is dict and not set(value) - {'view', 'day', 'meal'}
            and value.get('view') == 'recipe_week' and value.get('day', DAY) == DAY
            and value.get('meal', MEAL) == MEAL)


def send_allowed(record, values):
    try:
        attachment = uploaded(record)
    except FileNotFoundError:
        return False
    return (type(values) is dict and set(values) == old.SEND_FIELDS | {'file_name'}
            and values.get('message') == requested_message(record['run_id'])
            and old.canonical(values.get('request_id')) and values.get('day') == DAY
            and values.get('meal') == MEAL and type(values.get('stream')) is int and values['stream'] == 1
            and values.get('file_name') == attachment['file_id'] and selection_allowed(values.get('view_context')))


def request_policy(record, command, values, method, environ):
    if environ.get('PATH_INFO') != '/api/method/' + command or 'cmd' in values:
        return False
    if command == 'login':
        return method == 'POST' and set(values) == {'usr', 'pwd'} and values['usr'] == OWNER and isinstance(values['pwd'], str)
    if command == 'logout':
        return method == 'POST' and not values
    if command == 'upload_file':
        return False  # Only the separately checked multipart path is admitted.
    if command.startswith(API):
        name = command[len(API):]
        if name == 'send_message':
            return method == 'POST' and send_allowed(record, values)
        if name == 'get_conversation':
            return method == 'GET' and not values and history_allowed(record)
        task = registered_task(record)
        if task is None or values.get('task_id') != task:
            return False
        if name == 'cancel_task':
            return method == 'POST' and set(values) == {'task_id'}
        if name not in {'get_events', 'stream_events'} or method != 'GET':
            return False  # Never retry_dispatch or any task-creation alias.
        return (not set(values) - {'task_id', 'after'} and old.cursor(values.get('after', '0'), task)
                and (not environ.get('HTTP_LAST_EVENT_ID') or old.cursor(environ['HTTP_LAST_EVENT_ID'], task)))
    if method != 'GET':
        return False
    if command == 'frappe.auth.get_logged_user':
        return not values
    if command in {'tongjianyun.scene_access.get_bootstrap', 'tongjianyun.meal_scene.get_overview'}:
        return not set(values) - {'day', 'meal'} and values.get('day', DAY) == DAY and values.get('meal', MEAL) == MEAL
    if command == 'tongjianyun.meal_views.get_view':
        return set(values) == {'selection_json'} and selection_allowed(values['selection_json'])
    if command == 'tongjianyun.meal_scene.get_recipe':
        try:
            name = committed_target(record)
        except (FileNotFoundError, PermissionError, ValueError):
            return False
        return set(values) == {'recipe'} and values['recipe'] == name
    return False


def multipart_allowed(record, environ):
    """Bound and replay original bytes. Never create a File or bypass native CSRF."""
    from werkzeug.wrappers import Request
    if (environ.get('PATH_INFO') != '/api/method/upload_file' or environ.get('REQUEST_METHOD') != 'POST'
            or environ.get('QUERY_STRING') or environ.get('HTTP_TRANSFER_ENCODING')
            or environ.get('CONTENT_TYPE', '').split(';')[0].strip().lower() != 'multipart/form-data'):
        return False
    try:
        size = int(environ.get('CONTENT_LENGTH') or 0)
    except (ValueError, TypeError):
        return False
    if not 1 <= size <= 16384:
        return False
    body = environ['wsgi.input'].read(size)
    environ['wsgi.input'] = io.BytesIO(body)
    if len(body) != size:
        return False
    request = Request({**environ, 'wsgi.input': io.BytesIO(body)})
    try:
        if (set(request.form) != {'is_private'} or request.form.getlist('is_private') != ['1']
                or set(request.files) != {'file'} or len(request.files.getlist('file')) != 1):
            return False
        item = request.files['file']
        return (item.filename == filename(record['run_id']) and item.content_type in {'text/plain', 'application/octet-stream'}
                and item.stream.read(4097) == upload_bytes(record['run_id']))
    finally:
        request.close()


def reserve_upload(record, frappe, *, http_id=None):
    run = folder(record['run_id'])
    with previous.lock(run / 'request.lock'):
        require_admission(record)
        if not old.canonical(http_id):
            raise PermissionError('Trusted native HTTP request identity required')
        if (run / 'upload-intent.json').exists() or registered_task(record):
            raise PermissionError('Exactly one native upload attempt; inspect unknown outcomes, never retry')
        def check():
            from frappe.core.doctype.file.utils import get_content_hash
            assert_empty(frappe)
            raw = upload_bytes(record['run_id'])
            if (frappe.db.exists('File', {'file_name': filename(record['run_id'])})
                    or frappe.db.exists('File', {'content_hash': get_content_hash(raw), 'is_private': 1})):
                raise PermissionError('Synthetic upload identity/content already exists; never deduplicate it')
            for name in (filename(record['run_id']), '.temp-' + filename(record['run_id'])):
                path = qa.safe_target(qa.SITES / qa.SITE / 'private/files' / name)
                if path.exists() or path.is_symlink():
                    raise PermissionError('Synthetic private upload or native temporary path is already occupied')
        readonly(frappe, check)
        before = snapshot(frappe)
        prepared = old.private_read(run / 'prepare-baseline.json')
        if not difference(prepared, before)['protected_passed']:
            raise PermissionError('Protected state changed before upload')
        old.exclusive_json(run / 'upload-intent.json', {'run_id': record['run_id'], 'owner': OWNER,
            'http_request_id': http_id,
            'site': qa.SITE, 'filename': filename(record['run_id']), 'sha256': hashlib.sha256(upload_bytes(record['run_id'])).hexdigest(),
            'baseline_sha256': digest(before), 'automatic_retry': False})


def verify_upload(record, frappe):
    run = folder(record['run_id'])
    def read():
        from tongjianyun import business_agent_attachments as attachments
        ids = frappe.get_list('File', filters={'file_name': filename(record['run_id'])}, pluck='name', limit_page_length=2)
        if len(ids) != 1:
            raise PermissionError('Native upload did not create exactly one visible File')
        doc = frappe.get_doc('File', ids[0])
        descriptor, raw = attachments._load(ids[0])
        if (doc.owner != OWNER or doc.is_private != 1 or doc.is_folder
                or doc.attached_to_doctype or doc.attached_to_name or doc.attached_to_field
                or doc.file_url != '/private/files/' + filename(record['run_id'])
                or raw != upload_bytes(record['run_id'])):
            raise PermissionError('Native upload differs from the single synthetic private source')
        return {'run_id': record['run_id'], 'site': qa.SITE, 'owner': OWNER, 'file_id': ids[0],
                'filename': descriptor['display_name'], 'sha256': descriptor['sha256'], 'descriptor': descriptor}
    value = readonly(frappe, read)
    after = snapshot(frappe)
    before = old.private_read(run / 'prepare-baseline.json')
    if not difference(before, after, file_id=value['file_id'])['protected_passed']:
        raise PermissionError('Upload changed protected records')
    with previous.lock(run / 'request.lock'):
        old.exclusive_json(run / 'upload.json', value)
    return value


def reserve(record, values, frappe, *, http_id=None):
    if not send_allowed(record, values):
        raise PermissionError('Only the fixed uploaded-recipe request is admitted')
    run = folder(record['run_id'])
    with previous.lock(run / 'request.lock'):
        require_admission(record)
        if not old.canonical(http_id):
            raise PermissionError('Trusted native HTTP request identity required')
        if registered_task(record) is not None:
            raise PermissionError('Only one HTTP submission; unknown outcomes are never replayed')
        if manager_tasks():
            raise PermissionError('Manager already owns another task; do not expose or adopt its history')
        readonly(frappe, lambda: assert_empty(frappe))
        attachment = uploaded(record)
        from tongjianyun.business_agent_attachments import _load
        readonly(frappe, lambda: _load(attachment['file_id'], attachment['descriptor']))
        before = snapshot(frappe)
        prepared = old.private_read(run / 'prepare-baseline.json')
        if not difference(prepared, before, file_id=attachment['file_id'])['protected_passed']:
            raise PermissionError('Protected state changed before Codex dispatch')
        old.exclusive_json(run / 'model-baseline.json', before)
        old.exclusive_json(run / 'attempt.json', {'run_id': record['run_id'], 'site': qa.SITE, 'owner': OWNER,
            'http_request_id': http_id,
            'request_id': values['request_id'], 'payload_sha256': digest(values), 'file_id': attachment['file_id'],
            'source_sha256': record['source_sha256'], 'model_baseline_sha256': digest(before), 'automatic_retry': False})


def tool_allowed(record, tool, arguments):
    if type(arguments) is not dict:
        return False
    if tool == 'attachment_read':
        return (not set(arguments) - {'file_id', 'offset', 'page_size'}
            and arguments.get('file_id') == uploaded(record)['file_id']
            and type(arguments.get('offset', 0)) is int and arguments.get('offset', 0) == 0
            and type(arguments.get('page_size', 50)) is int and 10 <= arguments.get('page_size', 50) <= 100)
    if tool in {'recipe_read', 'recipe_save'}:
        from tongjianyun.business_agent_recipes import normalize_arguments
        try:
            args = normalize_arguments(tool, arguments)
        except (ValueError, TypeError):
            return False
        if args['day'] != DAY:
            return False
        if tool == 'recipe_save':
            return args == {'day': DAY, 'recipe': None, 'revision': '', 'payload': payload(record['run_id'])}
        if args['offset'] != 0 or args.get('content_revision'):
            return False
        if 'recipe' not in args:
            return True
        try:
            name = committed_target(record)
        except (FileNotFoundError, PermissionError, ValueError):
            return False
        return args['recipe'] == name
    return False


def tool_guard(record, claim, tool, arguments):
    pin(record)
    run = folder(record['run_id'])
    valid = (claim.identity.site == qa.SITE and claim.identity.owner == OWNER
        and claim.identity.task_id == registered_task(record) and tool_allowed(record, tool, arguments))
    with previous.lock(run / 'request.lock'):
        if valid and tool == 'recipe_save':
            # This is a single new-draft attempt, not retry logic. The ordinary
            # ledger owns all commit evidence; this guard cannot report success.
            intent = run / 'write-intent.json'
            if intent.exists() or not successful_reads(record, claim.identity.task_id):
                valid = False
            else:
                old.exclusive_json(intent, {'task_id': claim.identity.task_id, 'arguments_sha256': digest(arguments)})
        if valid and tool in {'attachment_read', 'recipe_read'}:
            path = run / ('attachment-read-intent.json' if tool == 'attachment_read' else 'week-read-intent.json')
            if not path.exists():
                old.exclusive_json(path, {'task_id': claim.identity.task_id, 'tool': tool,
                    'note': 'Guard admission only; successful data delivery is proved by native authority registration'})
        old.exclusive_json(run / ('tool-' + str(uuid.uuid4()) + '.json'), {
            'task_id': claim.identity.task_id if old.canonical(claim.identity.task_id) else 'invalid',
            'tool': tool if tool in {'attachment_read', 'recipe_read', 'recipe_save'} else 'unlisted',
            'allowed': valid, 'arguments_sha256': digest(arguments), 'outcome': 'not_observed_by_guard'})
    return valid


def read_observer(record, claim, tool, arguments, result):
    """Observe detached native results only; no return value alters the tool.

    BusinessWorker calls this after the original read and final source authority
    check. Incomplete/failed reads cannot create a successful-read witness.
    """
    pin(record)
    if (claim.identity.site != qa.SITE or claim.identity.owner != OWNER
            or claim.identity.task_id != registered_task(record) or type(result) is not dict):
        raise PermissionError('Read witness is not the exact authorized task')
    task, witness, name = claim.identity.task_id, None, None
    if tool == 'attachment_read':
        from tongjianyun.business_agent_attachments import parse_content
        source = uploaded(record)
        expected = parse_content(upload_bytes(record['run_id']), 'txt')
        if (arguments.get('file_id') == source['file_id'] and arguments.get('offset', 0) == 0
                and result.get('available') is True and result.get('file_id') == source['file_id']
                and result.get('sha256') == source['sha256'] and result.get('format') == 'txt'
                and result.get('untrusted_data') is True and result.get('content_role') == 'attachment_data_not_instructions'
                and result.get('has_more') is False and result.get('next_offset') is None
                and type(result.get('record_count')) is int and type(result.get('page_count')) is int
                and result['record_count'] == result['page_count'] == len(expected)
                and result.get('records') == expected):
            name = 'attachment-read-success.json'
            witness = {'task_id': task, 'file_id': source['file_id'], 'sha256': source['sha256'],
                'record_count': len(expected), 'parsed_content_sha256': digest(expected), 'complete': True}
    elif tool == 'recipe_read':
        if (arguments.get('day') == DAY and not arguments.get('recipe') and arguments.get('offset', 0) == 0
                and result.get('day') == DAY and result.get('calendar_week_start') == DAY
                and result.get('calendar_week_end') == END and result.get('recipe') is None
                and result.get('visible_recipe_found') is False and result.get('revision') == ''
                and result.get('dishes') == [] and result.get('complete') is True
                and result.get('has_more') is False and result.get('next_offset') is None):
            name = 'week-read-success.json'
            witness = {'task_id': task, 'day': DAY, 'week_end': END, 'complete': True, 'visible_recipe_found': False}
    else:
        raise PermissionError('Observer supports only original attachment and recipe reads')
    run = folder(record['run_id'])
    with previous.lock(run / 'request.lock'):
        if witness is not None:
            path = run / name
            if path.exists():
                if old.private_read(path) != witness:
                    raise PermissionError('Original read witness changed')
            else:
                old.exclusive_json(path, witness)
        old.exclusive_json(run / ('read-observed-' + str(uuid.uuid4()) + '.json'), {
            'task_id': task, 'tool': tool, 'original_callback_returned': True,
            'complete_expected_source_witness': witness is not None})


def successful_reads(record, task):
    source = uploaded(record)
    run = folder(record['run_id'])
    try:
        attached = old.private_read(run / 'attachment-read-success.json')
        week = old.private_read(run / 'week-read-success.json')
    except FileNotFoundError:
        return False
    from tongjianyun.business_agent_attachments import parse_content
    expected = parse_content(upload_bytes(record['run_id']), 'txt')
    return (attached == {'task_id': task, 'file_id': source['file_id'], 'sha256': source['sha256'],
        'record_count': len(expected), 'parsed_content_sha256': digest(expected), 'complete': True}
        and week == {'task_id': task, 'day': DAY, 'week_end': END, 'complete': True, 'visible_recipe_found': False})


def authenticated_guard(record, frappe, original):
    def validate():
        original()  # Original authentication and request/CSRF path remain intact.
        if frappe.session.user not in {'Guest', OWNER}:
            raise frappe.PermissionError('Only the fixed existing synthetic manager may log in')
        path = frappe.request.path
        if path not in {'/', '/login', '/api/method/login', '/favicon.ico'} and not path.startswith('/assets/'):
            if frappe.session.user != OWNER:
                raise frappe.PermissionError('Original manager session required')
        if path == '/api/method/upload_file':
            item = frappe.request.files.get('file')
            if (set(frappe.request.files) != {'file'} or len(frappe.request.files.getlist('file')) != 1
                    or item.filename != filename(record['run_id']) or str(frappe.form_dict.get('is_private')) != '1'):
                raise frappe.PermissionError('Exact synthetic private upload required')
            position = item.stream.tell()
            raw = item.stream.read(4097)
            item.stream.seek(position)
            if raw != upload_bytes(record['run_id']):
                raise frappe.PermissionError('Synthetic upload content changed')
            reserve_upload(record, frappe, http_id=frappe.request.environ.get('tgy.recipe_request_id'))
        if path == '/api/method/' + API + 'send_message':
            reserve(record, {key: value for key, value in frappe.form_dict.items() if key != 'cmd'}, frappe,
                    http_id=frappe.request.environ.get('tgy.recipe_request_id'))
        if path == '/api/method/' + API + 'get_conversation' and not history_allowed(record):
            raise frappe.PermissionError('Only this run\'s registered task history is admitted')
    return validate


def audit(record, value):
    old.exclusive_json(folder(record['run_id']) / ('http-' + str(uuid.uuid4()) + '.json'), value)


def require_admission(record):
    """Call under request.lock immediately before reserving any native write."""
    if (folder(record['run_id']) / 'admission-closed.json').exists():
        raise PermissionError('This run is closing; no new upload or task may be admitted')


def close_admission(record):
    run = folder(record['run_id'])
    with previous.lock(run / 'request.lock'):
        path = run / 'admission-closed.json'
        expected = {'run_id': record['run_id'], 'site': qa.SITE, 'owner': OWNER, 'closed': True}
        if path.exists():
            if old.private_read(path) != expected:
                raise PermissionError('Admission fence belongs to another run')
        else:
            old.exclusive_json(path, expected)


def http_drained(record):
    run = folder(record['run_id'])
    with previous.lock(run / 'request.lock'):
        for intent, receipt in (('upload-intent.json', 'upload-drained.json'), ('attempt.json', 'submission-drained.json')):
            if (run / intent).exists():
                original = old.private_read(run / intent)
                value = old.private_read(run / receipt)  # Missing/unknown callback fails closed.
                if (not old.canonical(original.get('http_request_id'))
                        or value != {'run_id': record['run_id'], 'http_request_id': original['http_request_id'],
                                     'native_wsgi_completed_and_closed': True}):
                    raise PermissionError('Native HTTP callback is not demonstrably drained')


def mark_http_drained(record, receipt, http_id):
    if receipt not in {'upload-drained.json', 'submission-drained.json'}:
        raise ValueError('Fixed native callback receipt required')
    run = folder(record['run_id'])
    with previous.lock(run / 'request.lock'):
        intent = run / ('upload-intent.json' if receipt == 'upload-drained.json' else 'attempt.json')
        if (not old.canonical(http_id) or not intent.exists()
                or old.private_read(intent).get('http_request_id') != http_id):
            return False  # Another rejected HTTP callback cannot drain the real writer.
        expected = {'run_id': record['run_id'], 'http_request_id': http_id, 'native_wsgi_completed_and_closed': True}
        path = run / receipt
        if path.exists():
            if old.private_read(path) != expected:
                raise PermissionError('HTTP drainage receipt identity changed')
        else:
            old.exclusive_json(path, expected)
        return True


class StreamEvidence:
    def __init__(self):
        self.buffer, self.frames, self.kinds = b'', 0, set()
        self.closed, self.invalid = False, False

    def observe(self, chunk):
        self.buffer += chunk
        if len(self.buffer) > 131072:
            self.buffer, self.invalid = b'', True
            return
        while b'\n\n' in self.buffer:
            frame, self.buffer = self.buffer.split(b'\n\n', 1)
            self.frames += 1
            if self.frames > 20000:
                self.invalid = True
                return
            if b'event: closed' in frame:
                self.closed = True
            try:
                data = [line[5:].strip() for line in frame.splitlines() if line.startswith(b'data:')]
                if data:
                    value = json.loads(b'\n'.join(data))
                    kind = value.get('kind') if isinstance(value, dict) else None
                    if kind in {'status', 'message', 'progress', 'view', 'terminal', 'done', 'error'}:
                        self.kinds.add(kind)
            except (ValueError, TypeError):
                self.invalid = True


class Boundary:
    def __init__(self, record, application, frappe):
        self.record, self.native, self.frappe = record, application, frappe
        self.filtered = qa.QAFirewall(application,
            request_policy=lambda *args: request_policy(record, *args))

    def __call__(self, environ, start_response):
        record = load(self.record['run_id'], ready=True)
        path, method = environ.get('PATH_INFO', ''), environ.get('REQUEST_METHOD', 'GET')
        if (environ.get('HTTP_HOST') not in {f'{qa.SITE}:{qa.PORT}', f'127.0.0.1:{qa.PORT}', f'localhost:{qa.PORT}'}
                or environ.get('HTTP_X_FRAPPE_SITE_NAME', qa.SITE) != qa.SITE):
            return qa.reply(start_response, '403 Forbidden', {'message': 'Fixed isolated QA host only'})
        if path == '/__qa__/health' and method == 'GET':
            return qa.reply(start_response, '200 OK', {'profile': PROFILE, 'run_id': record['run_id'],
                'native_auth_required': True, 'one_request_only': True, 'browser_verified': False})
        allowed_path = (path in {'/', '/login', '/tongjianyun-entry', '/tongjianyun-meal-scene', '/favicon.ico'}
                        or path.startswith(('/assets/', '/api/method/')))
        if not allowed_path or '%' in path or '/..' in path:
            return qa.reply(start_response, '403 Forbidden', {'message': 'Outside this fixed journey'})
        if path == '/tongjianyun-meal-scene':
            query = parse_qs(environ.get('QUERY_STRING', ''), keep_blank_values=True)
            if query != {'day': [DAY], 'meal': [MEAL]}:
                return qa.reply(start_response, '403 Forbidden', {'message': 'Exact synthetic week scene required'})
        upload = path == '/api/method/upload_file'
        if upload and not multipart_allowed(record, environ):
            audit(record, {'route': 'upload_file', 'method': method, 'boundary': 'denied', 'status': 403})
            return qa.reply(start_response, '403 Forbidden', {'message': 'Only the exact synthetic private TXT is admitted'})
        route = path[len('/api/method/'):] if path.startswith('/api/method/') else 'page_or_asset'
        http_id = str(uuid.uuid4())
        environ['tgy.recipe_request_id'] = http_id  # Never read from a client header/parameter.
        known = {'upload_file', 'login', 'logout', 'tongjianyun.scene_access.get_bootstrap',
                 'tongjianyun.meal_scene.get_overview', 'tongjianyun.meal_scene.get_recipe',
                 'tongjianyun.meal_views.get_view', 'frappe.auth.get_logged_user',
                 *(API + name for name in ('send_message', 'get_conversation', 'get_events', 'stream_events', 'cancel_task'))}
        status = {}
        def capture(code, headers, exc_info=None):
            status.update(code=code, headers=headers, exc_info=exc_info)
            if not upload:
                return start_response(code, headers, exc_info) if exc_info else start_response(code, headers)
        try:
            response = (self.native if upload else self.filtered)(environ, capture)
        except BaseException as error:
            audit(record, {'route': route if route in known else 'unlisted', 'method': method,
                'outcome': 'unknown_preserve_no_retry', 'failure_type': type(error).__name__[:80]})
            raise
        if upload:
            # Complete the unchanged native response and independent readback
            # BEFORE the browser receives File.name and can issue send_message.
            completed = False
            try:
                chunks, size = [], 0
                for chunk in response:
                    size += len(chunk)
                    if size > 1024 * 1024:
                        raise PermissionError('Native upload response exceeds the finite bound')
                    chunks.append(chunk)
                completed = True
                if str(status.get('code', '')).startswith('200 '):
                    verify_upload(record, self.frappe)
                audit(record, {'route': 'upload_file', 'method': method,
                    'status': int(status['code'].split()[0]), 'response_bytes': size,
                    'native_file_verified': (folder(record['run_id']) / 'upload.json').exists()})
                start_response(status['code'], status['headers'])
                return chunks
            except BaseException as error:
                audit(record, {'route': 'upload_file', 'method': method,
                    'status': int(status.get('code', '500').split()[0]), 'native_file_verified': False,
                    'outcome': 'unknown_preserve_no_retry', 'failure_type': type(error).__name__[:80]})
                raise
            finally:
                if hasattr(response, 'close'):
                    response.close()
                if completed and (folder(record['run_id']) / 'upload-intent.json').exists():
                    mark_http_drained(record, 'upload-drained.json', http_id)
        stream = StreamEvidence() if route == API + 'stream_events' else None
        def observed():
            completed, size = False, 0
            try:
                for chunk in response:
                    size += len(chunk)
                    if stream:
                        stream.observe(chunk)
                    yield chunk
                completed = True
            finally:
                if hasattr(response, 'close'):
                    response.close()
                if (completed and route == API + 'send_message'
                        and (folder(record['run_id']) / 'attempt.json').exists()):
                    mark_http_drained(record, 'submission-drained.json', http_id)
                if route != 'page_or_asset':
                    value = {'route': route if route in known else 'unlisted', 'method': method,
                        'status': int(status.get('code', '500').split()[0]), 'response_bytes': size,
                        'response_complete': completed, 'browser_received_or_rendered': False}
                    if stream:
                        value.update(sse_frames=stream.frames, sse_kinds=sorted(stream.kinds),
                                     sse_closed=stream.closed, sse_parse_invalid=stream.invalid)
                    audit(record, value)
        return observed()


def config_before(site, common):
    workers = common.get('workers', {})
    if type(workers) is not dict:
        raise PermissionError('Invalid native worker configuration')
    return {**{key: {'present': key in site, 'value': site.get(key)} for key in CONFIG_VALUES},
            'workers': {'present': 'workers' in common},
            'queue': {'present': old.QUEUE in workers, 'value': workers.get(old.QUEUE)}}


def restore_fields(site, common, before):
    workers = common.get('workers', {})
    if type(workers) is not dict:
        raise PermissionError('Foreign worker config change')
    pairs = [(site, key, before[key], value) for key, value in CONFIG_VALUES.items()]
    pairs.append((workers, old.QUEUE, before['queue'], {'timeout': -1}))
    for target, key, original, installed in pairs:
        unchanged = (key in target) == original['present'] and target.get(key) == original['value']
        if not unchanged and (key not in target or target[key] != installed):
            raise PermissionError('Owned configuration changed; never overwrite another operator')
    for target, key, original, _ in pairs:
        if original['present']:
            target[key] = original['value']
        else:
            target.pop(key, None)
    if workers or before['workers']['present']:
        common['workers'] = workers
    else:
        common.pop('workers', None)


def port_absent():
    with socket.socket() as connection:
        connection.settimeout(1)
        if connection.connect_ex(('127.0.0.1', qa.PORT)) == 0:
            raise PermissionError('The exact QA port is still occupied')


def file_create_probe(frappe, run_id):
    """Read-only native permission check at Document.insert's ownership stage.

    Native insert sets the new document's owner from its current session before
    checking create permission. File's original custom permission uses that
    owner even for an unsaved private File; an ownerless probe is not equivalent
    to upload_file. This transient document is never inserted or saved.
    """
    if frappe.local.site != qa.SITE or frappe.session.user != OWNER:
        raise PermissionError('Exact current QA manager required for the native permission probe')
    probe = frappe.get_doc({'doctype': 'File', 'is_private': 1, 'file_name': filename(run_id),
                           'owner': frappe.session.user})
    if probe.has_permission('create') is not True:
        raise PermissionError('Existing manager lacks native private File creation')


def check(run_id):
    folder(run_id)
    frappe = environment()
    from tongjianyun.business_agent_worker import UnixLauncherRuntime
    from tongjianyun.business_agent_worker import BusinessWorker
    import inspect
    if 'read_observer' not in inspect.signature(BusinessWorker).parameters:
        raise PermissionError('Original worker success-read observer is not integrated')
    if UnixLauncherRuntime(site=qa.SITE, sites_path=str(qa.SITES)).ready() is not True:
        raise PermissionError('Fixed QA native launcher is unavailable')
    qa.verify_asset_evidence()
    previous.idle_queue(frappe)
    port_absent()
    if manager_tasks():
        raise PermissionError('Manager history is not empty; cannot expose other runs through native conversation')
    def capabilities():
        from tongjianyun import business_agent_recipes, meal_scene
        business_agent_recipes.check_projection()
        meal_scene.require_recipe_create()
        file_create_probe(frappe, run_id)
        assert_empty(frappe)
        for hook in ('write_file', 'before_write_file', 'after_file_upload', 'delete_file_data_content', 'ignore_file_permissions'):
            if frappe.get_hooks(hook):
                raise PermissionError('Custom File hooks require separate review')
        return True
    readonly(frappe, capabilities)
    return frappe, {'site': qa.SITE, 'owner': OWNER, 'profile': PROFILE, 'run_id': run_id,
        'day': DAY, 'week_end': END, 'source_sha256': pin(), 'baseline': snapshot(frappe),
        'model_started': False, 'native_permission_scope': 'Existing synthetic System Manager; not teacher authority'}


def prepare(run_id):
    environment()
    with previous.lock(LOCK, create=True):
        for active, root in ((ACTIVE, ROOT), (previous.ACTIVE, previous.ROOT)):
            if active.exists():
                earlier = old.private_read(root / old.private_read(active)['run_id'] / 'run.json')
                if earlier.get('site') != qa.SITE or earlier.get('state') != 'restored':
                    raise PermissionError('Restore the previous journey before this new run')
        frappe, checked = check(run_id)
        path = folder(run_id)
        if path.exists() or path.is_symlink():
            raise PermissionError('Run UUID already consumed; retain it, never resume or replace')
        ROOT.mkdir(mode=0o700, exist_ok=True)
        from tongjianyun.business_agent_transport import private_directory
        private_directory(ROOT)
        path.mkdir(mode=0o700)
        old.exclusive_json(path / 'request.lock', {})
        site_path, common_path = qa.SITES / qa.SITE / 'site_config.json', qa.SITES / 'common_site_config.json'
        site, common = old.private_read(site_path), old.private_read(common_path)
        before = config_before(site, common)
        record = {key: value for key, value in checked.items() if key != 'baseline'}
        record.update(version=1, state='preparing', before=before,
                      requested_message=requested_message(run_id), upload_filename=filename(run_id),
                      upload_sha256=hashlib.sha256(upload_bytes(run_id)).hexdigest())
        old.exclusive_json(path / 'prepare-baseline.json', checked['baseline'])
        old.exclusive_json(path / 'run.json', record)
        old.atomic_json(ACTIVE, {'run_id': run_id})
        file_path = qa.safe_target(path / filename(run_id))
        fd = os.open(file_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(upload_bytes(run_id))
            stream.flush()
            os.fsync(stream.fileno())
        site.update(CONFIG_VALUES)
        common['workers'] = {**common.get('workers', {}), old.QUEUE: {'timeout': -1}}
        old.atomic_json(site_path, site)
        old.atomic_json(common_path, common)
        old.atomic_json(path / 'run.json', {**record, 'state': 'prepared'})
        return {'run_id': run_id, 'prepared': True, 'model_started': False, 'upload_path': str(file_path),
            'upload_sha256': record['upload_sha256'], 'requested_message': requested_message(run_id),
            'url': f'{qa.ORIGIN}/tongjianyun-meal-scene?day={DAY}&meal={MEAL}'}


@contextmanager
def process_record(run_id, role):
    if role not in {'web', 'worker'}:
        raise ValueError('Fixed foreground role required')
    path, identity = folder(run_id) / (role + '.json'), previous.proc_identity(os.getpid())
    old.exclusive_json(path, {'identity': identity, 'running': True})
    try:
        yield
    finally:
        old.atomic_json(path, {'identity': identity, 'running': False})


def serve(run_id):
    frappe, record = environment(), load(run_id, ready=True)
    import frappe.app
    from werkzeug.serving import make_server, WSGIRequestHandler
    original = frappe.app.validate_auth
    frappe.app.validate_auth = authenticated_guard(record, frappe, original)
    frappe.app._site, frappe.app._sites_path = qa.SITE, str(qa.SITES)
    class Quiet(WSGIRequestHandler):
        def log(self, *args): pass
    try:
        with process_record(run_id, 'web'):
            server = make_server('127.0.0.1', qa.PORT, Boundary(record, frappe.app.application_with_statics(), frappe),
                                 threaded=True, request_handler=Quiet)
            try:
                server.serve_forever()
            finally:
                server.server_close()
    finally:
        frappe.app.validate_auth = original


def validate_job(record, job, queue_name, expected_queue):
    if (queue_name != expected_queue or job.origin != expected_queue or job.func_name != 'frappe.utils.background_jobs.execute_job'
            or job.args or job.timeout != -1 or job.retries_left not in (None, 0)
            or job._success_callback_name is not None or job._stopped_callback_name is not None
            or job._failure_callback_name != 'frappe.utils.background_jobs.truncate_failed_registry'):
        raise PermissionError('Unexpected native RQ job')
    values = job.kwargs
    if (type(values) is not dict or set(values) != {'site', 'user', 'method', 'event', 'job_name', 'is_async', 'kwargs'}
            or values['site'] != qa.SITE or values['user'] != OWNER or values['method'] != old.WORKER_METHOD
            or values['job_name'] != old.WORKER_METHOD or values['event'] is not None or values['is_async'] is not True
            or registered_task(record) is None
            or values['kwargs'] != {'owner': OWNER, 'task_id': registered_task(record)}):
        raise PermissionError('Only the exact manager HTTP-reserved original run_task can execute')


def worker(run_id):
    frappe, record = environment(), load(run_id, ready=True)
    from rq import Worker
    from frappe.utils.background_jobs import get_queue
    from tongjianyun import business_agent_worker as implementation
    Original = implementation.BusinessWorker
    class RestrictedWorker(Original):
        def __init__(self, *args, **kwargs):
            if kwargs.get('tool_guard') is not None or kwargs.get('read_observer') is not None:
                raise PermissionError('Unexpected second restriction')
            kwargs['tool_guard'] = lambda claim, tool, arguments: tool_guard(record, claim, tool, arguments)
            kwargs['read_observer'] = lambda claim, tool, arguments, result: read_observer(record, claim, tool, arguments, result)
            super().__init__(*args, **kwargs)
    implementation.BusinessWorker = RestrictedWorker
    frappe.init(site=qa.SITE, sites_path=str(qa.SITES))
    qa.guard(frappe.conf)
    queue = get_queue(old.QUEUE)
    expected_queue = queue.name
    frappe.destroy()
    class FixedQueueWorker(Worker):
        def execute_job(self, job, selected_queue):
            load(run_id, ready=True)
            validate_job(record, job, selected_queue.name, expected_queue)
            return super().execute_job(job, selected_queue)
    instance = FixedQueueWorker([queue], connection=queue.connection, name='tgy-recipe-journey-' + run_id)
    try:
        with process_record(run_id, 'worker'):
            logging.disable(logging.CRITICAL)
            with open(os.devnull, 'w') as quiet, redirect_stdout(quiet), redirect_stderr(quiet):
                instance.work(with_scheduler=False, logging_level='CRITICAL')
    finally:
        implementation.BusinessWorker = Original


def task_proof(task_id):
    from tongjianyun.business_agent_worker import UnixLauncherRuntime
    from tongjianyun.business_agent_tasks import TaskIdentity
    base = qa.SITES / qa.SITE / 'private/business-codex/tasks'
    with previous.read_db(base / 'business-tasks.sqlite3') as db:
        row = db.execute('SELECT owner,status,claim_id,sequence FROM tasks WHERE task_id=?', (task_id,)).fetchone()
        if row is None or row['owner'] != OWNER or not row['claim_id']:
            raise PermissionError('No exact manager native claimed task proof')
        events = [json.loads(value[0]) for value in db.execute(
            'SELECT payload FROM events WHERE task_id=? ORDER BY sequence LIMIT 10001', (task_id,))]
        scopes = [json.loads(value[0]) for value in db.execute('SELECT descriptor FROM authorities WHERE task_id=?', (task_id,))]
        if len(events) > 10000:
            raise PermissionError('Native event evidence too large')
    runtime = UnixLauncherRuntime(site=qa.SITE, sites_path=str(qa.SITES))
    observation = runtime.observe(TaskIdentity(qa.SITE, OWNER, task_id), row['claim_id'])
    with previous.read_db(base / 'business-writes.sqlite3') as db:
        gate = db.execute('SELECT owner,claim_id,closed FROM tasks WHERE task_id=?', (task_id,)).fetchone()
        if not gate or gate['owner'] != OWNER or gate['claim_id'] != row['claim_id']:
            raise PermissionError('No matching original host ledger gate')
        operations = db.execute('''SELECT DISTINCT o.operation_id,o.state,o.active FROM operations o
            JOIN aliases a ON a.operation_id=o.operation_id WHERE a.task_id=?''', (task_id,)).fetchall()
    return {'task_id': task_id, 'status': row['status'], 'native': asdict(observation),
        'host': {'closed': bool(gate['closed']), 'active': sum(value['active'] for value in operations),
                 'uncertain': sum(value['state'] in {'reserved', 'committing', 'uncertain'} for value in operations),
                 'committed': [value['operation_id'] for value in operations if value['state'] == 'committed']},
        'events': events, 'scopes': scopes}


def drained(proof):
    return (proof['status'] in {'completed', 'failed', 'cancelled'} and proof['native']['state'] == 'exited'
        and proof['native']['lease_closed'] is True and proof['native']['active_writes'] == 0
        and proof['host']['closed'] is True and proof['host']['active'] == proof['host']['uncertain'] == 0)


def committed_target(record):
    """Trust the live ledger commit, even while the model finishes its turn.

    No polling job, fabricated receipt, model ID or offline evidence command is
    needed for the original frontend's immediate get_recipe refresh.
    """
    from tongjianyun.business_agent_recipes import write_plan
    task = registered_task(record)
    if task is None:
        raise PermissionError('No reserved native HTTP task')
    proof = task_proof(task)
    if (proof['host']['active'] or proof['host']['uncertain'] or len(proof['host']['committed']) != 1):
        raise PermissionError('No single drained native commit yet')
    intent = old.private_read(folder(record['run_id']) / 'write-intent.json')
    arguments = {'day': DAY, 'recipe': None, 'revision': '', 'payload': payload(record['run_id'])}
    if intent != {'task_id': task, 'arguments_sha256': digest(arguments)}:
        raise PermissionError('Commit is not the exact authorized synthetic payload')
    return write_plan(qa.SITE, proof['host']['committed'][0], arguments).target_recipe


def drain_proof(record, frappe):
    http_drained(record)
    task = registered_task(record)
    if task is None:
        if manager_tasks():
            raise PermissionError('Unregistered manager task exists; preserve processes and config')
        return {'task_absent': True, 'native_started': False}
    proof = task_proof(task)
    if not drained(proof):
        raise PermissionError('Original native task or host writes are not demonstrably drained')
    previous.unit_proof(task)
    rq = previous.rq_proof(frappe, task)
    if rq['status'] not in {'finished', 'failed', 'stopped', 'canceled'}:
        raise PermissionError('Original RQ workhorse not terminal')
    return {'task_id': task, 'status': proof['status'], 'native': proof['native'], 'host': proof['host'], 'rq': rq}


def saved_recipe(record, frappe, proof):
    from tongjianyun.business_agent_recipes import write_plan
    if len(proof['host']['committed']) != 1:
        raise PermissionError('Exactly one acknowledged original recipe commit required')
    arguments = {'day': DAY, 'recipe': None, 'revision': '', 'payload': payload(record['run_id'])}
    name = write_plan(qa.SITE, proof['host']['committed'][0], arguments).target_recipe
    def read():
        from tongjianyun import meal_scene
        value = meal_scene.get_recipe(name)
        doc = frappe.get_doc('Tongjianyun Recipe', name)
        content = value['payload']
        expected = payload(record['run_id'])
        if (week_rows(frappe) != [name] or doc.owner != OWNER or doc.workflow_status != '草稿' or doc.is_deleted
                or doc.title != expected['recipe']['title'] or str(doc.week_start) != DAY or str(doc.week_end) != END
                or len(content['days']) != 1 or content['days'][0]['date'] != DAY
                or len(content['days'][0]['portions']) != 1
                or content['days'][0]['portions'][0]['slot'] != MEAL
                or content['days'][0]['portions'][0]['dishes'] != ['合成验收菜品']
                or content['days'][0]['portions'][0].get('dishIngredientRows')
                or frappe.db.count('Tongjianyun Recipe Ingredient', {'recipe': name}) != 0):
            raise PermissionError('Fresh native draft differs from the single synthetic request')
        return {'recipe': name, 'revision': value['revision'], 'payload_sha256': digest(content), 'fresh_native_read': True}
    return readonly(frappe, read)


def evidence(run_id):
    frappe, record = environment(), load(run_id)
    task = registered_task(record)
    if task is None:
        raise PermissionError('No browser-reserved task exists')
    drain = drain_proof(record, frappe)
    proof = task_proof(task)
    saved = saved_recipe(record, frappe, proof)
    run, attachment = folder(run_id), uploaded(record)
    path = run / 'saved-recipe.json'
    if path.exists():
        if old.private_read(path) != saved:
            raise PermissionError('Previously verified saved recipe changed')
    else:
        old.exclusive_json(path, saved)
    after = snapshot(frappe)
    delta = difference(old.private_read(run / 'prepare-baseline.json'), after,
                       file_id=attachment['file_id'], recipe=saved['recipe'])
    events, scopes = proof['events'], proof['scopes']
    source_ok = any(scope.get('kind') == 'attachment' and scope.get('descriptor') == attachment['descriptor'] for scope in scopes)
    read_witnesses = successful_reads(record, task)
    recipe_ok = any(scope == {'kind': 'recipe', 'recipe': saved['recipe']} for scope in scopes)
    view = any(value.get('kind') == 'view' and selection_allowed(value.get('selection')) for value in events)
    logs = [old.private_read(path) for path in sorted(run.glob('http-*.json'))]
    if len(logs) > 2000:
        raise PermissionError('HTTP evidence bound exceeded')
    sse = [value for value in logs if value.get('route') == API + 'stream_events']
    report = {'run_id': run_id, 'site': qa.SITE, 'owner': OWNER, 'source_sha256': pin(record),
        'execution': drain, 'fresh_recipe': saved, 'difference': delta, 'attachment_source_registered': source_ok,
        'successful_original_attachment_and_empty_week_reads': read_witnesses,
        'recipe_source_registered': recipe_ok, 'view_event_emitted': view,
        'sse_native_responses': sse, 'http_audit_count': len(logs), 'browser_sse_and_display_verified': False,
        'teacher_authority_proven': False, 'ingredient_matching_exercised': False,
        'backend_passed': bool(proof['status'] == 'completed' and proof['native']['exit_code'] == 0
            and source_ok and read_witnesses and recipe_ok and view and delta['protected_passed']
            and drain['rq'] == {'status': 'finished', 'started': True, 'result_status': 'completed'}),
        'note': 'Real native HTTP/RQ/model/commit evidence; browser delivery and left-pane rendering still require browser observation.'}
    receipt = str(uuid.uuid4())
    old.exclusive_json(run / ('after-' + receipt + '.json'), after)
    old.exclusive_json(run / ('evidence-' + receipt + '.json'), report)
    return report


def stop(run_id):
    frappe = environment()
    with previous.lock(LOCK):
        record, run = load(run_id), folder(run_id)
        close_admission(record)
        proof = drain_proof(record, frappe)  # BEFORE sending any signal.
        stopped = []
        for role in ('web', 'worker'):
            path = run / (role + '.json')
            if not path.exists():
                continue
            saved = old.private_read(path)
            identity = saved['identity']
            if previous.proc_identity(identity['pid']) != identity:
                stopped.append({'role': role, 'original_process_absent': True})
                continue
            if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
                raise PermissionError('Linux pidfd exact-process signaling required')
            fd = os.pidfd_open(identity['pid'])
            try:
                if previous.proc_identity(identity['pid']) != identity:
                    raise PermissionError('Recorded PID identity changed before stop')
                signal.pidfd_send_signal(fd, signal.SIGTERM)
                if not select.select([fd], [], [], 10)[0]:
                    raise PermissionError('Recorded process did not exit; no forced kill or restore')
            finally:
                os.close(fd)
            if previous.proc_identity(identity['pid']) == identity:
                raise PermissionError('Recorded process remains present')
            stopped.append({'role': role, 'original_process_absent': True})
        port_absent()
        receipt = {'run_id': run_id, 'drain_proof': proof, 'processes': stopped, 'port_absent': True}
        old.exclusive_json(run / ('stopped-' + str(uuid.uuid4()) + '.json'), receipt)
        return receipt


def restore(run_id):
    frappe = environment()
    with previous.lock(LOCK):
        record, run = load(run_id), folder(run_id)
        if old.private_read(ACTIVE) != {'run_id': run_id} or record['state'] not in {'prepared', 'preparing'}:
            raise PermissionError('Only the active run may restore its own configuration')
        close_admission(record)
        proof = drain_proof(record, frappe)
        for role in ('web', 'worker'):
            path = run / (role + '.json')
            if path.exists():
                saved = old.private_read(path)
                if previous.proc_identity(saved['identity']['pid']) == saved['identity']:
                    raise PermissionError('Stop the exact foreground process before restoring')
        port_absent()
        paths = qa.SITES / qa.SITE / 'site_config.json', qa.SITES / 'common_site_config.json'
        site, common = map(old.private_read, paths)
        restore_fields(site, common, record['before'])
        old.atomic_json(paths[0], site)
        old.atomic_json(paths[1], common)
        restored_site, restored_common = map(old.private_read, paths)
        if config_before(restored_site, restored_common) != record['before']:
            raise PermissionError('Readback did not verify exact owned config restoration')
        old.atomic_json(run / 'run.json', {**record, 'state': 'restored'})
        return {'run_id': run_id, 'restored': True, 'drain_proof': proof, 'all_records_and_evidence_retained': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'prepare', 'serve', 'worker', 'evidence', 'stop', 'restore-config'),
                        nargs='?', default='check')
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args(argv)
    if not old.canonical(args.run_id):
        parser.error('Explicit canonical --run-id UUID required')
    if args.command == 'check':
        _, result = check(args.run_id)
        result.pop('baseline')
        result['read_only'] = True
    elif args.command == 'restore-config':
        result = restore(args.run_id)
    else:
        result = globals()[args.command](args.run_id)
    if result is not None:
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


if __name__ == '__main__':
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print(json.dumps({'failed': type(error).__name__,
                          'detail': 'Recipe journey stopped; retain all records and evidence; no automatic retry'}), flush=True)
        raise SystemExit(1) from None
