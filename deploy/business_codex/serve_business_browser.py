"""Explicit, QA-only HTTP -> RQ -> native business Codex browser acceptance.

``check`` is read-only; ``prepare`` does not start a model and changes
only two guarded QA config fields, recording their previous values. ``serve``
and ``worker`` are separate foreground, non-root processes. Only a native login
as the existing synthetic teacher can reserve ONE durable browser request_id.
The worker may consume that already authenticated, reserved request; it never
creates a task itself. The ordinary business_chat/service/worker remain the actual implementation.
There is no administrator runner, upload, synthetic cookie or authorization
bypass. ``restore-config`` requires the foreground processes to be stopped and
every synthetic teacher task terminal; it retains task/attempt evidence.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import signal
import sys
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'unified_business'))
import serve_isolated_browser as qa
sys.path.insert(0, str(HERE))
import check_live_codex as fixture

API = 'tongjianyun.business_chat.'
WORKER_METHOD = 'tongjianyun.business_agent_service.run_task'
QUEUE = 'business_codex'
CONFIG_STATE = qa.ROOT / 'business-browser-config.json'
ATTEMPT = qa.ROOT / 'business-browser-attempt.json'
WEB_STATE = qa.ROOT / 'business-browser-web.json'
WORKER_STATE = qa.ROOT / 'business-browser-worker.json'
SOURCE_FILES = ('deploy/business_codex/serve_business_browser.py',
    'deploy/unified_business/serve_isolated_browser.py',
    'deploy/business_codex/check_live_codex.py', 'deploy/business_codex/check_worker_live.py',
    'tongjianyun/business_chat.py', 'tongjianyun/business_agent_service.py',
    'tongjianyun/business_agent_worker.py', 'tongjianyun/business_agent_reads.py',
    'tongjianyun/business_agent_catalog.py', 'tongjianyun/business_agent_execution.py',
    'tongjianyun/business_agent_writes.py', 'tongjianyun/business_agent_write_adapter.py',
    'tongjianyun/frappe_project_views.py',
    'tongjianyun/business_agent_tasks.py', 'tongjianyun/business_agent_authority.py',
    'tongjianyun/business_agent_transport.py', 'tongjianyun/business_agent_events.py',
    'tongjianyun/business_agent_tools.py', 'tongjianyun/classroom.py', 'tongjianyun/attendance_scope.py',
    'tongjianyun/scene_access.py', 'tongjianyun/meal_views.py', 'tongjianyun/meal_chat_events.py',
    'tongjianyun/business_views.py', 'tongjianyun/meal_scene.py', 'tongjianyun/student_meals.py', 'tongjianyun/daily_meals.py',
    'tongjianyun/workspace_entry.py', 'tongjianyun/www/tongjianyun-meal-scene.html',
    *(f'tongjianyun/public/{name}' for name in qa.CRITICAL_ASSETS))
# Capture THIS process's source revision, not a later disk revision. All imports
# stay inside the fixed trusted candidate; change it only after stopping both
# acceptance processes and doing a new explicit preparation.
LOADED_SOURCE_SHA256 = {name: hashlib.sha256((HERE.parent.parent / name).read_bytes()).hexdigest()
                        for name in SOURCE_FILES}
READS = {'frappe.auth.get_logged_user', 'tongjianyun.scene_access.get_bootstrap',
         'tongjianyun.meal_views.get_view', 'tongjianyun.classroom.get_overview'}
BUSINESS = {'send_message': 'POST', 'retry_dispatch': 'POST', 'cancel_task': 'POST',
            'get_conversation': 'GET', 'get_events': 'GET', 'stream_events': 'GET'}
SEND_FIELDS = {'message', 'request_id', 'day', 'meal', 'stream', 'view_context'}


def canonical(value):
    return isinstance(value, str) and bool(re.fullmatch(
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', value)) and str(uuid.UUID(value)) == value


def cursor(value, task):
    return value == '0' or isinstance(value, str) and bool(re.fullmatch(re.escape(task) + r':[1-9][0-9]{0,12}', value))


def selection_allowed(value):
    if isinstance(value, str):
        try:
            value = qa.unique_json(value)
        except (ValueError, TypeError):
            return False
    if type(value) is not dict or value.get('view') not in {'students', 'class_students', 'classroom_day'}:
        return False
    allowed = {'view', 'day', 'meal', 'group'} | ({'presentation'} if value['view'] == 'students' else {'offset'})
    return (not set(value) - allowed
            and ('offset' not in value or type(value['offset']) is int and value['offset'] == 0)
            and ('presentation' not in value or value['presentation'] == 'table')
            and value.get('day', fixture.DAY) == fixture.DAY
            and value.get('meal', fixture.MEAL) == fixture.MEAL
            and value.get('group', fixture.GROUP) == fixture.GROUP)


def send_allowed(values):
    return (set(values) == SEND_FIELDS and canonical(values.get('request_id'))
            and isinstance(values.get('message'), str) and 1 <= len(values['message'].strip()) <= 8000
            and '\0' not in values['message'] and values.get('day') == fixture.DAY
            and values.get('meal') == fixture.MEAL and type(values.get('stream')) is int
            and values['stream'] == 1 and selection_allowed(values.get('view_context')))


def request_policy(command, values, method, environ):
    """Additional parser boundary; native auth/CSRF still run unchanged after it."""
    # Only the actual frontend's canonical route, not form-cmd/v2/slash aliases.
    if environ.get('PATH_INFO') != '/api/method/' + command or 'cmd' in values:
        return False
    if command == 'login':
        return (method == 'POST' and not set(values) - {'usr', 'pwd'}
                and values.get('usr') == fixture.TEACHER and isinstance(values.get('pwd'), str))
    if command == 'logout':
        return method == 'POST' and not values
    if command.startswith(API):
        name = command[len(API):]
        if BUSINESS.get(name) != method:
            return False
        if name == 'send_message':
            return send_allowed(values)
        if name == 'get_conversation':
            return not set(values) - {'before'} and ('before' not in values or canonical(values['before']))
        if not canonical(values.get('task_id')):
            return False
        if name in {'retry_dispatch', 'cancel_task'}:
            return set(values) == {'task_id'}
        if set(values) - {'task_id', 'after'} or not cursor(values.get('after', '0'), values['task_id']):
            return False
        return (name != 'stream_events' or not environ.get('HTTP_LAST_EVENT_ID')
                or cursor(environ['HTTP_LAST_EVENT_ID'], values['task_id']))
    if command not in READS or method != 'GET':
        return False
    if command == 'frappe.auth.get_logged_user':
        return not values
    if command == 'tongjianyun.meal_views.get_view':
        return set(values) == {'selection_json'} and selection_allowed(values['selection_json'])
    if set(values) - {'day', 'meal', 'group'}:
        return False
    return (values.get('day', fixture.DAY) == fixture.DAY and values.get('meal', fixture.MEAL) == fixture.MEAL
            and values.get('group', fixture.GROUP) == fixture.GROUP)


def private_read(path):
    qa.safe_target(path)
    info = path.stat(follow_symlinks=False)
    if not path.is_file() or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_nlink != 1:
        raise PermissionError('Unsafe QA evidence file')
    return json.loads(path.read_text())


def exclusive_json(path, value):
    qa.safe_target(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w', closefd=False) as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, value):
    """Private same-directory replace; interrupted preparation remains recoverable."""
    qa.safe_target(path)
    temporary = path.parent / ('.' + path.name + '.' + str(uuid.uuid4()) + '.tmp')
    exclusive_json(temporary, value)
    try:
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temporary.exists():
            temporary.unlink()  # Only this uniquely created, exact temporary file.


def verified_sources(*, prepared=False):
    current = {name: qa.digest_file(qa.SOURCE / name) for name in SOURCE_FILES}
    if current != LOADED_SOURCE_SHA256:
        raise PermissionError('Candidate changed after this QA process loaded; stop before replacing source')
    if prepared and private_read(CONFIG_STATE).get('source_sha256') != current:
        raise PermissionError('Candidate differs from the explicitly prepared QA revision')
    return current


def reserve_request(values, *, before_model):
    if not send_allowed(values):
        raise PermissionError('Only the fixed QA request shape is accepted')
    expected = {'site': qa.SITE, 'owner': fixture.TEACHER, 'request_id': values['request_id'],
                'payload_sha256': hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False,
                    separators=(',', ':')).encode()).hexdigest()}
    hashes = verified_sources(prepared=True)
    def same_attempt():
        actual = private_read(ATTEMPT)
        if any(actual.get(key) != value for key, value in expected.items()):
            raise PermissionError('This browser acceptance already reserved another request; do not replay')
    if ATTEMPT.exists():
        same_attempt()
        return  # Do not replace the model-before baseline on an HTTP retry.
    baseline = before_model()
    if not isinstance(baseline, str) or not re.fullmatch('[0-9a-f]{64}', baseline):
        raise PermissionError('Missing private pre-model business baseline')
    try:
        exclusive_json(ATTEMPT, {**expected, 'automatic_retry': False,
            'source_sha256': hashes, 'model_pre_digest': baseline})
    except FileExistsError:
        same_attempt()


def protected_digest(frappe):
    # This private acceptance-only diagnostic is never a model tool or public
    # response. The existing helper reads only the fixed synthetic fixture in a
    # separate read-only Frappe context, preserving the native request context.
    from check_worker_live import readonly_adapter
    return readonly_adapter(frappe).run_check(fixture.TEACHER, lambda: fixture.protected_digest(frappe))


def authenticated_guard(frappe, original):
    """App-local wrapper adds a QA restriction AFTER native session+CSRF auth."""
    def validate():
        original()
        user = frappe.session.user
        if user not in {'Guest', fixture.TEACHER}:
            raise frappe.PermissionError('This browser QA only admits its synthetic teacher')
        path = frappe.request.path
        if path.startswith('/api/method/' + API) or path == '/tongjianyun-meal-scene':
            if user != fixture.TEACHER:
                raise frappe.PermissionError('Native synthetic teacher login is required')
        if path == '/api/method/' + API + 'send_message':
            values = {key: value for key, value in frappe.form_dict.items() if key != 'cmd'}
            reserve_request(values, before_model=lambda: protected_digest(frappe))
    return validate


def environment():
    if sys.flags.optimize or os.name != 'posix' or os.geteuid() == 0:
        raise PermissionError('Run unoptimized Python as the existing site user, never root')
    # Do not inherit administrator auth, proxy or Frappe override environment.
    keep = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}
    os.environ.clear()
    os.environ.update(keep)
    fixture.fixture_guard()
    if Path(__file__).resolve() != qa.SOURCE / 'deploy/business_codex/serve_business_browser.py':
        raise PermissionError('Run only the fixed, reviewed QA source script')
    verified_sources()
    frappe = qa.runtime()
    return frappe


def check(*, ready=False):
    frappe = environment()
    from check_worker_live import readonly_adapter
    from tongjianyun.business_agent_worker import UnixLauncherRuntime
    from tongjianyun.business_agent_service import _model_key
    adapter = readonly_adapter(frappe)
    adapter.run_check(fixture.TEACHER, lambda: fixture.account_guard(frappe))
    # Validates credential location/mode without exposing, passing or storing it.
    _model_key()
    native = UnixLauncherRuntime(site=qa.SITE, sites_path=str(qa.SITES))
    if native.ready() is not True:
        raise PermissionError('The fixed QA-only native launcher is unavailable')
    assets = qa.verify_asset_evidence()
    if ready:
        saved = private_read(CONFIG_STATE)
        config = qa.config_guard()
        if (saved.get('state') != 'prepared' or config.get('business_codex_enabled') != 1
                or config.get('workers', {}).get(QUEUE) != {'timeout': -1}):
            raise PermissionError('Explicit QA preparation is required')
        verified_sources(prepared=True)
    return frappe, {'site': qa.SITE, 'teacher_verified': True, 'native_launcher_ready': True,
                    'source_sha256': verified_sources(),
                    'critical_sha256': assets['critical_sha256'], 'model_started': False}


def prepare():
    frappe, report = check()
    paths = {'site': qa.SITES / qa.SITE / 'site_config.json', 'common': qa.SITES / 'common_site_config.json'}
    configs = {name: private_read(path) for name, path in paths.items()}
    if CONFIG_STATE.exists():
        check(ready=True)
        return {**report, 'prepared': True, 'already_prepared': True}
    workers = configs['common'].get('workers', {})
    if type(workers) is not dict:
        raise PermissionError('Invalid QA custom worker configuration')
    baseline = protected_digest(frappe)
    record = {'site': qa.SITE, 'state': 'preparing', 'before': {
        'business_codex_enabled': {'present': 'business_codex_enabled' in configs['site'],
                                  'value': configs['site'].get('business_codex_enabled')},
        'workers': {'present': 'workers' in configs['common']},
        'queue': {'present': QUEUE in workers, 'value': workers.get(QUEUE)}},
        'source_sha256': report['source_sha256'], 'prepare_protected_business_digest': baseline}
    exclusive_json(CONFIG_STATE, record)
    configs['site']['business_codex_enabled'] = 1
    configs['common']['workers'] = {**workers, QUEUE: {'timeout': -1}}
    for name, path in paths.items():
        atomic_json(path, configs[name])
    record['state'] = 'prepared'
    atomic_json(CONFIG_STATE, record)
    qa.config_guard()
    return {**report, 'prepared': True, 'processes_started': False}


def process_state(path, running, **extra):
    qa.private_json(path, {'site': qa.SITE, 'pid': os.getpid(), 'running': running, **extra})


class BrowserBoundary:
    def __init__(self, application):
        self.application = qa.QAFirewall(application, request_policy=request_policy)

    def __call__(self, environ, start_response):
        qa.config_guard()
        verified_sources(prepared=True)
        path = environ.get('PATH_INFO', '')
        if (environ.get('HTTP_HOST') not in {f'{qa.SITE}:{qa.PORT}', f'127.0.0.1:{qa.PORT}', f'localhost:{qa.PORT}'}
                or environ.get('HTTP_X_FRAPPE_SITE_NAME', qa.SITE) != qa.SITE):
            return qa.reply(start_response, '403 Forbidden', {'message': 'QA site only'})
        if path == '/__qa__/health' and environ.get('REQUEST_METHOD') == 'GET':
            return qa.reply(start_response, '200 OK', {'site': qa.SITE, 'profile': 'business-browser-v1',
                'admin_execution_blocked': True, 'uploads_blocked': True, 'native_auth_required': True,
                'business_readonly_allowed': True, 'one_request_only': True, 'threaded': True})
        if (path not in {'/', '/login', '/tongjianyun-entry', '/tongjianyun-meal-scene', '/favicon.ico'}
                and not path.startswith(('/assets/', '/api/method/'))):
            return qa.reply(start_response, '403 Forbidden', {'message': 'Outside the browser QA surface'})
        return self.application(environ, start_response)


def serve():
    frappe, report = check(ready=True)
    import frappe.app
    from werkzeug.serving import WSGIRequestHandler, make_server
    frappe.app.validate_auth = authenticated_guard(frappe, frappe.app.validate_auth)
    frappe.app._site, frappe.app._sites_path = qa.SITE, str(qa.SITES)
    class Quiet(WSGIRequestHandler):
        def log(self, *args):
            pass
    # Threaded WSGI is necessary: one SSE request must not block cancellation,
    # view reads or other sessions. FreshFrappeChecks uses isolated contexts.
    server = make_server('127.0.0.1', qa.PORT, BrowserBoundary(frappe.app.application_with_statics()),
                         threaded=True, request_handler=Quiet)
    process_state(WEB_STATE, True, port=qa.PORT)
    print(json.dumps({**report, 'web_ready': True, 'port': qa.PORT}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        process_state(WEB_STATE, False, port=qa.PORT)


def validate_job(job, queue_name, expected_queue):
    """Inspect RQ metadata before executing its function, never trust queue name alone."""
    if (queue_name != expected_queue or job.origin != expected_queue
            or job.func_name != 'frappe.utils.background_jobs.execute_job' or job.args
            or job.timeout != -1 or job.retries_left not in (None, 0)
            or job._success_callback_name is not None or job._stopped_callback_name is not None
            or job._failure_callback_name != 'frappe.utils.background_jobs.truncate_failed_registry'):
        raise PermissionError('Unrecognized QA queue job')
    values = job.kwargs
    if (type(values) is not dict or set(values) != {'site', 'user', 'method', 'event', 'job_name', 'is_async', 'kwargs'}
            or values['site'] != qa.SITE or values['user'] != fixture.TEACHER
            or values['method'] != WORKER_METHOD or values['job_name'] != WORKER_METHOD
            or values['event'] is not None or values['is_async'] is not True):
        raise PermissionError('Only the actual business service job is admitted')
    payload = values['kwargs']
    if (type(payload) is not dict or set(payload) != {'owner', 'task_id'}
            or payload['owner'] != fixture.TEACHER or not canonical(payload['task_id'])):
        raise PermissionError('Invalid synthetic teacher job binding')
    attempt = private_read(ATTEMPT)
    if (attempt.get('site') != qa.SITE or attempt.get('owner') != fixture.TEACHER
            or attempt.get('request_id') != payload['task_id']):
        raise PermissionError('This task was not reserved through the QA native HTTP request')


def worker():
    frappe, report = check(ready=True)
    from rq import Worker
    from frappe.utils.background_jobs import get_queue
    # This connection is only to obtain the exact queue. The real native job
    # establishes its own site/user context; no Administrator is substituted.
    frappe.init(site=qa.SITE, sites_path=str(qa.SITES))
    qa.guard(frappe.conf)
    queue = get_queue(QUEUE)
    expected_queue = queue.name
    frappe.destroy()
    class FixedWorker(Worker):
        def execute_job(self, job, selected_queue):
            qa.config_guard()
            verified_sources(prepared=True)
            validate_job(job, selected_queue.name, expected_queue)
            return super().execute_job(job, selected_queue)
    instance = FixedWorker([queue], connection=queue.connection, name='tgy-business-browser-qa-' + str(os.getpid()))
    process_state(WORKER_STATE, True, queue=expected_queue)
    print(json.dumps({**report, 'worker_ready': True, 'queue': expected_queue, 'scheduler': False}), flush=True)
    try:
        # RQ/Frappe exception logging can contain request values. Evidence is the
        # private task store/public sanitized events, not raw process output.
        logging.disable(logging.CRITICAL)
        with open(os.devnull, 'w') as quiet, redirect_stdout(quiet), redirect_stderr(quiet):
            instance.work(with_scheduler=False, logging_level='CRITICAL')
    finally:
        process_state(WORKER_STATE, False, queue=expected_queue)


def verify():
    frappe, report = check(ready=True)
    from tongjianyun.business_agent_service import available
    from urllib.request import urlopen
    frappe.init(site=qa.SITE, sites_path=str(qa.SITES))
    qa.guard(frappe.conf)
    frappe.connect()
    try:
        frappe.set_user(fixture.TEACHER)
        admitted = available()
    finally:
        frappe.destroy()
    with urlopen(f'http://127.0.0.1:{qa.PORT}/__qa__/health', timeout=5) as response:
        health = json.load(response)
    if health.get('profile') != 'business-browser-v1' or not admitted:
        raise PermissionError('HTTP, native launcher and exact RQ worker must all be ready')
    return {**report, 'http_rq_native_ready': True, 'attempt_reserved': ATTEMPT.exists(),
            'url': f'{qa.ORIGIN}/tongjianyun-meal-scene?day={fixture.DAY}&meal={fixture.MEAL}'}


def evidence():
    """Read-only backend receipt; NEVER substitutes for a real browser assertion."""
    frappe, source = check(ready=True)
    attempt, config = private_read(ATTEMPT), private_read(CONFIG_STATE)
    task_id = attempt.get('request_id')
    if (attempt.get('site') != qa.SITE or attempt.get('owner') != fixture.TEACHER or not canonical(task_id)
            or attempt.get('source_sha256') != source['source_sha256']):
        raise PermissionError('No exact source-bound HTTP attempt to observe')
    from tongjianyun.business_agent_service import application
    from tongjianyun.business_agent_tasks import TaskIdentity
    from frappe.utils.background_jobs import get_job
    frappe.init(site=qa.SITE, sites_path=str(qa.SITES))
    qa.guard(frappe.conf)
    frappe.connect()
    try:
        frappe.set_user(fixture.TEACHER)
        app, runtime = application()
        identity = TaskIdentity(qa.SITE, fixture.TEACHER, task_id)
        task = app.store.task(identity)
        row = app.store._owned(identity)
        job = get_job(app.store.job_id(identity))
        status = getattr(job.get_status(refresh=True), 'value', None) if job is not None else None
        if job is not None and status is None:
            status = str(job.get_status(refresh=True))
        job_result = job.return_value(refresh=True) if job is not None and status == 'finished' else None
        events, after = [], '0'
        while len(events) < 10000:
            page = app.store.events(identity, after, limit=100)
            events.extend(page)
            if len(page) < 100:
                break
            after = page[-1]['id']
        else:
            raise PermissionError('QA public event evidence exceeds its bound')
        scopes = app.store.required_scopes(identity)
        native = runtime.observe(identity, row['claim_id']) if row['claim_id'] else None
        scope_students = {scope.get('document') for scope in scopes
                          if scope.get('kind') == 'document' and scope.get('doctype') == 'Student'}
        after_digest = protected_digest(frappe)
        report = {'site': qa.SITE, 'task_id': task_id, 'source_sha256': source['source_sha256'],
            'rq_status': status, 'rq_result_started': isinstance(job_result, dict) and job_result.get('started') is True,
            'rq_result_status': job_result.get('status') if isinstance(job_result, dict) else None,
            'task_status': task['status'], 'event_count': len(events),
            'event_kinds': sorted({event['kind'] for event in events}),
            'message_present': any(event['kind'] == 'message' for event in events),
            'classroom_view_event': any(event['kind'] == 'view' and event.get('selection', {}).get('view') == 'classroom_day'
                and event.get('selection', {}).get('group') == fixture.GROUP
                and event.get('selection', {}).get('day') == fixture.DAY for event in events),
            'source_student_scope_count': len(scope_students),
            'source_students_exactly_synthetic': scope_students == set(fixture.STUDENTS),
            'native_exit_verified': bool(native and native.state == 'exited' and native.exit_code == 0
                and native.active_writes == 0 and native.lease_closed),
            'prepare_raw_digest_unchanged': config['prepare_protected_business_digest'] == after_digest,
            'model_protected_digest_unchanged': attempt['model_pre_digest'] == after_digest,
            'digest_difference_requires_review': attempt['model_pre_digest'] != after_digest,
            'browser_sse_and_display_verified': False,
            'note': 'Backend receipt only. Native login may change the prepare digest; do not mask pre-model changes.'}
        report['backend_passed'] = (report['rq_status'] == 'finished' and report['rq_result_started']
            and report['rq_result_status'] == 'completed' and report['task_status'] == 'completed'
            and report['message_present'] and report['classroom_view_event']
            and report['source_students_exactly_synthetic'] and report['native_exit_verified']
            and report['model_protected_digest_unchanged'])
        # No student names, messages, model key, raw job error or worker token.
        atomic_json(qa.ROOT / ('business-browser-result-' + task_id + '.json'), report)
        return report
    finally:
        frappe.destroy()


def restore_config():
    frappe = environment()
    for path in (WEB_STATE, WORKER_STATE):
        if path.exists():
            saved = private_read(path)
            try:
                os.kill(int(saved['pid']), 0)
            except ProcessLookupError:
                pass
            else:
                raise PermissionError('Stop the recorded QA foreground processes first')
    from tongjianyun.business_agent_service import application
    frappe.init(site=qa.SITE, sites_path=str(qa.SITES))
    qa.guard(frappe.conf)
    frappe.connect()
    try:
        frappe.set_user(fixture.TEACHER)
        app, _ = application()
        if app.store.active_task(fixture.TEACHER):
            raise PermissionError('Cancel and verify task termination before restoring configuration')
    finally:
        frappe.destroy()
    record = private_read(CONFIG_STATE)
    if record.get('site') != qa.SITE or record.get('state') not in {'preparing', 'prepared'}:
        raise PermissionError('No exact prepared QA configuration to restore')
    site_path, common_path = qa.SITES / qa.SITE / 'site_config.json', qa.SITES / 'common_site_config.json'
    site, common = private_read(site_path), private_read(common_path)
    before = record['before']
    restore_fields(site, common, before)
    atomic_json(site_path, site)
    atomic_json(common_path, common)
    atomic_json(CONFIG_STATE, {**record, 'state': 'restored'})
    return {'site': qa.SITE, 'config_restored': True, 'task_and_attempt_evidence_retained': True}


def restore_fields(site, common, before):
    """Only own two keys; each may still be before or after an interrupted write."""
    workers = common.get('workers', {})
    if type(workers) is not dict:
        raise PermissionError('Foreign custom-worker configuration change')
    pairs = ((site, 'business_codex_enabled', before['business_codex_enabled'], 1),
             (workers, QUEUE, before['queue'], {'timeout': -1}))
    for target, key, old, installed in pairs:
        original = (key in target) == old['present'] and target.get(key) == old['value']
        if not original and (key not in target or target[key] != installed):
            raise PermissionError('Configuration changed after preparation; refuse to overwrite')
    for target, key, old, installed in pairs:
        if old['present']:
            target[key] = old['value']
        else:
            target.pop(key, None)
    if workers or before['workers']['present']:
        common['workers'] = workers
    else:
        common.pop('workers', None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'prepare', 'serve', 'worker', 'verify', 'evidence', 'restore-config'), nargs='?', default='check')
    args = parser.parse_args()
    # Graceful termination gets through finally; it never kills native units by
    # PID or treats a missing foreground worker as proof a model has exited.
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        result = globals()[args.command.replace('-', '_')]()
        if args.command == 'check':
            result = result[1]
        if result is not None:
            print(json.dumps(result), flush=True)
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps({'ok': False, 'command': args.command, 'error_type': type(error).__name__,
            'detail': 'QA stopped; no automatic model retry; retain original task evidence'}), flush=True)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
