"""Explicit second-generation QA journey. No old marker or report is replaced.

Default check is read-only. prepare is an explicit local management action;
serve/worker never manufacture a task or a login. Each run admits one fixed
natural-language request through native HTTP -> native RQ -> BusinessWorker.
The worker adds a construction-only reject guard, never substitutes a business
transaction, identity, commit, model result, or permission check.

business-save tests ONE original attendance save plus its native daily-summary
side effect. catalog tests real catalog discovery/display separately. Neither
profile enables attachments, proposals, generic CRUD, or arbitrary model writes.
Field-level diagnostic hashes cover the declared business tables, not every
table in the database. Authentication metadata differences remain visible and
are not retrospectively blamed for the old failed run's unexplained digest.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from dataclasses import asdict
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import signal
import socket
import sqlite3
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import serve_business_browser as old

qa, fixture = old.qa, old.fixture
DAY, MEAL = '2026-09-18', 'lunch'
OLD_TASK = 'd714bd66-acf9-4408-9ee9-abdb739995a9'
OLD_REPORT_HASH = 'e6496051aa44aeabf55e9f48fbe024c99e6f8567c50bb83d3222831ef5d4613a'
OLD_ATTEMPT_HASH = '439d5bfe015c733faa8284a786b9631f6c0588f8b21768079dad7e9e21ab764c'
ROOT = qa.ROOT / 'business-journeys'
ACTIVE = qa.ROOT / 'business-journey-active.json'
LOCK = qa.ROOT / 'business-journey-management.lock'
PROFILES = ('business-save', 'catalog')
BUSINESS_TABLES = ('Student', 'Student Group', 'Student Attendance', 'Student Leave Application',
    'Tongjianyun Class Meal Confirmation', 'Tongjianyun Daily Meal Confirmation',
    'Tongjianyun Daily Meal Adjustment')
AUTH_FIELDS = frozenset({'last_login', 'last_active', 'last_ip'})
USER_FIELDS = ('enabled', 'user_type', 'last_login', 'last_active', 'last_ip', 'modified',
               'modified_by', 'roles', 'block_modules')
SOURCE_FILES = tuple(dict.fromkeys((*old.SOURCE_FILES,
    'deploy/business_codex/serve_business_journey.py',
    *(str(path.relative_to(HERE.parent.parent)).replace('\\', '/')
      for path in sorted((HERE.parent.parent / 'tongjianyun').glob('business_agent*.py'))))))
LOADED_HASHES = {name: hashlib.sha256((HERE.parent.parent / name).read_bytes()).hexdigest()
                 for name in SOURCE_FILES}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, default=str).encode()).hexdigest()


def folder(run_id):
    if not old.canonical(run_id):
        raise ValueError('Exact run UUID required')
    return qa.safe_target(ROOT / run_id)


def pin(record=None):
    current = {name: qa.digest_file(qa.SOURCE / name) for name in SOURCE_FILES}
    if current != LOADED_HASHES or record is not None and record['source_sha256'] != current:
        raise PermissionError('Candidate changed: stop the run; never hot-replace its evidence')
    return current


def environment():
    if os.name != 'posix' or os.geteuid() == 0 or sys.flags.optimize:
        raise PermissionError('Existing site OS user, Linux and unoptimized Python required')
    if Path(__file__).resolve() != qa.SOURCE / 'deploy/business_codex/serve_business_journey.py':
        raise PermissionError('Only the fixed reviewed candidate is allowed')
    os.environ.clear()
    os.environ.update(PATH='/usr/bin:/bin', LANG='C.UTF-8', PYTHONDONTWRITEBYTECODE='1')
    pin()
    fixture.fixture_guard()
    return qa.runtime()


@contextmanager
def lock(path, *, create=False):
    import fcntl
    qa.safe_target(path)
    flags = os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0)
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not __import__('stat').S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_nlink != 1:
            raise PermissionError('Unsafe private lock')
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def load(run_id, *, ready=False):
    record = old.private_read(folder(run_id) / 'run.json')
    if record.get('run_id') != run_id or record.get('site') != qa.SITE or record.get('profile') not in PROFILES:
        raise PermissionError('Invalid run binding')
    pin(record)
    if ready:
        config = qa.config_guard()
        if (record.get('state') != 'prepared' or old.private_read(ACTIVE).get('run_id') != run_id
                or config.get('business_codex_enabled') != 1
                or config.get('workers', {}).get(old.QUEUE) != {'timeout': -1}):
            raise PermissionError('This exact run is not explicitly prepared')
    return record


def flatten(value, prefix=''):
    """Private per-field fingerprints; raw pupil/role/session values are not saved."""
    result = {}
    if isinstance(value, dict):
        result[prefix + '/@keys'] = digest(sorted(value))
        for key, child in sorted(value.items()):
            result.update(flatten(child, prefix + '/' + str(key).replace('~', '~0').replace('/', '~1')))
    elif isinstance(value, list):
        result[prefix + '/@length'] = digest(len(value))
        for index, child in enumerate(value):
            result.update(flatten(child, prefix + '/' + str(index)))
    else:
        result[prefix or '/'] = digest(value)
    return result


def snapshot(frappe):
    """Fresh independent READ ONLY diagnostic connection, never a model tool."""
    from check_worker_live import readonly_adapter
    def read():
        fixture.account_guard(frappe)
        previous = frappe.session.user
        try:
            # Existing QA diagnostic privilege only, in a separate enforced RO
            # transaction; never injected into HTTP/RQ/business transactions.
            frappe.set_user('Administrator')
            records = {}
            for doctype in (*BUSINESS_TABLES, 'Comment', 'Version'):
                filters = ({'reference_doctype': ['in', list(BUSINESS_TABLES)]} if doctype == 'Comment'
                           else {'ref_doctype': ['in', list(BUSINESS_TABLES)]} if doctype == 'Version' else {})
                names = frappe.get_all(doctype, filters=filters, pluck='name', order_by='name', limit_page_length=2001)
                if len(names) > 2000:
                    raise PermissionError('Diagnostic table bound exceeded; do not truncate baseline')
                for name in names:
                    data = frappe.get_doc(doctype, name).as_dict()
                    scope = {key: str(data.get(key) or '') for key in (
                        'student_group', 'student', 'date', 'meal_date', 'status',
                        'reference_doctype', 'reference_name', 'ref_doctype', 'docname', 'comment_type')}
                    records[doctype + ':' + name] = {'doctype': doctype, 'name': name,
                        'fields': flatten(data), 'scope': scope}
            user = frappe.get_doc('User', fixture.TEACHER)
            # Do not serialize credentials or password/reset fields even as hashes.
            data = {key: user.get(key) for key in USER_FIELDS}
            data['roles'] = [row.role for row in user.roles]
            data['block_modules'] = [row.module for row in user.block_modules]
            records['User:' + fixture.TEACHER] = {'doctype': 'User', 'name': fixture.TEACHER,
                                                'fields': flatten(data), 'scope': {}}
            return {'version': 1, 'site': qa.SITE, 'tables': list(BUSINESS_TABLES),
                    'scope': 'Declared business tables (all rows), their comments/versions, and fixed teacher nonsecret fields; not a whole-database audit',
                    'records': records, 'sha256': digest(records)}
        finally:
            frappe.set_user(previous)
    return readonly_adapter(frappe).run_check(fixture.TEACHER, read)


def difference(before, after, profile):
    if profile not in PROFILES or before['site'] != qa.SITE or after['site'] != qa.SITE:
        raise PermissionError('Snapshot binding mismatch')
    prior, current = before['records'], after['records']
    expected, unexpected, metadata = [], [], []
    new_targets = set()
    for key in sorted(set(current) - set(prior)):
        row, good = current[key], False
        scope = row['scope']
        if profile == 'business-save':
            good = (row['doctype'] == 'Student Attendance' and scope.get('student_group') == fixture.GROUP
                and scope.get('student') == fixture.STUDENTS[0] and scope.get('date') == DAY and scope.get('status') == 'Present')
            good |= row['doctype'] == 'Tongjianyun Daily Meal Confirmation' and scope.get('meal_date') == DAY
        if good:
            new_targets.add((row['doctype'], row['name']))
    for key in sorted(set(prior) | set(current)):
        left, right = prior.get(key), current.get(key)
        if left == right:
            continue
        fields = sorted(path for path in set((left or {}).get('fields', {})) | set((right or {}).get('fields', {}))
                        if (left or {}).get('fields', {}).get(path) != (right or {}).get('fields', {}).get(path))
        item = {'record': key, 'change': 'added' if left is None else 'deleted' if right is None else 'changed', 'fields': fields}
        if left is not None and right is not None and right['doctype'] == 'User':
            meta = [path for path in fields if path in {'/' + name for name in AUTH_FIELDS}]
            if meta:
                metadata.append({**item, 'fields': meta, 'attribution': 'authentication metadata; actor not inferred'})
            fields = [path for path in fields if path not in meta]
            item['fields'] = fields
            if not fields:
                continue
        good = left is None and right is not None and (right['doctype'], right['name']) in new_targets
        if left is None and right is not None and right['doctype'] in {'Comment', 'Version'}:
            scope = right['scope']
            reference = (scope.get('reference_doctype'), scope.get('reference_name')) if right['doctype'] == 'Comment' else (scope.get('ref_doctype'), scope.get('docname'))
            good = reference in new_targets and (right['doctype'] != 'Comment' or scope.get('comment_type') == 'Info')
        (expected if good else unexpected).append(item)
    return {'expected': expected, 'unexpected': unexpected, 'authentication_metadata': metadata,
            'raw_unchanged': before['sha256'] == after['sha256'], 'protected_passed': not unexpected,
            'scope': after['scope'], 'historical_digest_difference_explained': False}


def assert_empty(frappe):
    from check_worker_live import readonly_adapter
    def read():
        from tongjianyun import classroom
        fixture.account_guard(frappe)
        if not classroom._capabilities(classroom._day(DAY))['attendance_write']:
            raise PermissionError('Native teacher/date capability forbids save')
        for doctype, filters in (
            ('Student Attendance', {'date': DAY}),
            ('Student Leave Application', {'from_date': ['<=', DAY], 'to_date': ['>=', DAY]}),
            ('Tongjianyun Class Meal Confirmation', {'meal_date': DAY}),
            ('Tongjianyun Daily Meal Confirmation', {'meal_date': DAY}),
            ('Tongjianyun Daily Meal Adjustment', {'meal_date': DAY})):
            if frappe.db.exists(doctype, filters):
                raise PermissionError('Fixed new date is not empty; no overwrite or date-search retry')
        return True
    return readonly_adapter(frappe).run_check(fixture.TEACHER, read)


@contextmanager
def read_db(path):
    # No TaskStore/Ledger constructor: those perform schema/identity writes.
    qa.safe_target(path)
    info = path.lstat()
    import stat
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_nlink != 1:
        raise PermissionError('Unsafe private SQLite evidence')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        yield db
    finally:
        db.close()


def task_proof(task_id):
    from tongjianyun.business_agent_worker import UnixLauncherRuntime
    from tongjianyun.business_agent_tasks import TaskIdentity
    base = qa.SITES / qa.SITE / 'private/business-codex/tasks'
    with read_db(base / 'business-tasks.sqlite3') as db:
        row = db.execute('SELECT owner,status,claim_id,sequence FROM tasks WHERE task_id=?', (task_id,)).fetchone()
        if row is None or row['owner'] != fixture.TEACHER or not row['claim_id']:
            raise PermissionError('No exact ordinary teacher claimed task')
        events = [json.loads(item[0]) for item in db.execute('SELECT payload FROM events WHERE task_id=? ORDER BY sequence LIMIT 10001', (task_id,))]
        if len(events) > 10000:
            raise PermissionError('Event evidence exceeds its bound')
        scopes = [json.loads(item[0]) for item in db.execute('SELECT descriptor FROM authorities WHERE task_id=?', (task_id,))]
    native = UnixLauncherRuntime(site=qa.SITE, sites_path=str(qa.SITES)).observe(
        TaskIdentity(qa.SITE, fixture.TEACHER, task_id), row['claim_id'])
    host = {'present': False, 'closed': False, 'active': 0, 'uncertain': 0, 'committed': 0}
    path = base / 'business-writes.sqlite3'
    if path.exists():
        with read_db(path) as db:
            gate = db.execute('SELECT owner,claim_id,closed FROM tasks WHERE task_id=?', (task_id,)).fetchone()
            if gate:
                if gate['owner'] != fixture.TEACHER or gate['claim_id'] != row['claim_id']:
                    raise PermissionError('Host write claim mismatch')
                operations = db.execute('SELECT DISTINCT o.operation_id,o.state,o.active FROM operations o JOIN aliases a ON a.operation_id=o.operation_id WHERE a.task_id=?', (task_id,)).fetchall()
                host = {'present': True, 'closed': bool(gate['closed']), 'active': sum(value['active'] for value in operations),
                        'uncertain': sum(value['state'] in {'reserved', 'committing', 'uncertain'} for value in operations),
                        'committed': sum(value['state'] == 'committed' for value in operations)}
    return {'task_id': task_id, 'status': row['status'], 'claim_id': row['claim_id'], 'sequence': row['sequence'],
            'native': asdict(native), 'host': host, 'events': events,
            'scope_count': len(scopes), 'doctype_scope_count': sum(scope.get('kind') == 'doctype' for scope in scopes),
            'student_source_ids_exact': {scope.get('document') for scope in scopes if scope.get('kind') == 'document' and scope.get('doctype') == 'Student'} == set(fixture.STUDENTS)}


def unit_proof(task_id):
    if not old.canonical(task_id):
        raise ValueError('Exact unit UUID required')
    completed = subprocess.run(['/usr/bin/systemctl', 'show', 'tgy-business-codex-' + task_id + '.service',
        '--property=LoadState,ActiveState,SubState,MainPID,ControlGroup'], capture_output=True, text=True, timeout=10, check=False)
    if completed.returncode or len(completed.stdout) > 4096:
        raise PermissionError('Cannot inspect exact unit')
    value = dict(line.split('=', 1) for line in completed.stdout.splitlines() if '=' in line)
    if value.get('ActiveState') not in {'inactive', 'failed'} or value.get('MainPID') != '0' or value.get('ControlGroup'):
        raise PermissionError('Exact native unit may still execute')
    return value


def prior_proof():
    names = {'report': qa.ROOT / ('business-browser-result-' + OLD_TASK + '.json'), 'attempt': old.ATTEMPT}
    hashes = {key: qa.digest_file(path) for key, path in names.items()}
    if hashes != {'report': OLD_REPORT_HASH, 'attempt': OLD_ATTEMPT_HASH}:
        raise PermissionError('Original failed evidence changed; explicit human review required')
    if old.private_read(old.CONFIG_STATE).get('state') != 'restored':
        raise PermissionError('Restore the previous owned config first')
    processes = {}
    for key, path in (('web', old.WEB_STATE), ('worker', old.WORKER_STATE)):
        value = old.private_read(path)
        if value.get('running') is not False or Path('/proc/' + str(int(value['pid']))).exists():
            raise PermissionError('Prior recorded process not proven absent')
        processes[key] = {'pid': value['pid'], 'absent': True, 'evidence_sha256': qa.digest_file(path)}
    proof = task_proof(OLD_TASK)
    native, host = proof['native'], proof['host']
    if (proof['status'] != 'failed' or native['state'] != 'exited' or native['lease_closed'] is not True
            or native['active_writes'] != 0 or host['active'] or host['uncertain']
            or host['present'] and not host['closed']):
        raise PermissionError('Prior native/host execution not demonstrably drained')
    # This exact hash-pinned old attempt predated the host write adapter. Its
    # absent ledger is recorded, NEVER accepted for any new journey task.
    proof.pop('events')
    with socket.socket() as connection:
        connection.settimeout(1)
        if connection.connect_ex(('127.0.0.1', qa.PORT)) == 0:
            raise PermissionError('QA listener still in use')
    return {'previous_task_id': OLD_TASK, 'hashes': hashes, 'processes': processes,
            'execution': proof, 'unit': unit_proof(OLD_TASK), 'port_absent': True,
            'old_failure_retained': True, 'historical_digest_difference_unattributed': True}


def requested_message(profile):
    if profile == 'business-save':
        return (f'请实际登记 {DAY} 本班学生 {fixture.STUDENTS[0]} 到园（Present），只改这一名，另一名保持未登记。'
                '请先读取最新名单和修订，保存后重新核对，并在左侧显示这一天的班级出勤。不登记用餐，不改其他日期。')
    if profile == 'catalog':
        return '请查询我当前有权限使用的业务目录，并在左侧显示业务目录第一页。只查询，不新增或修改任何业务。'
    raise ValueError('Fixed profile required')


def selection_allowed(value, profile):
    if isinstance(value, str):
        try:
            value = qa.unique_json(value)
        except (TypeError, ValueError):
            return False
    if type(value) is not dict or value.get('day', DAY) != DAY or value.get('meal', MEAL) != MEAL:
        return False
    view = value.get('view')
    if view in {'classroom_day', 'class_students', 'students'}:
        fields = {'view', 'day', 'meal', 'group'} | ({'presentation'} if view == 'students' else {'offset'})
        return (not set(value) - fields and value.get('group', fixture.GROUP) == fixture.GROUP
            and value.get('presentation', 'table') == 'table'
            and type(value.get('offset', 0)) is int and value.get('offset', 0) == 0)
    if profile == 'catalog' and view == 'frappe_catalog':
        return (not set(value) - {'view', 'day', 'meal', 'app', 'module', 'keyword', 'kind', 'offset'}
            and all(value.get(key, '') == '' for key in ('app', 'module', 'keyword'))
            and value.get('kind', 'doctype') == 'doctype' and type(value.get('offset', 0)) is int and value.get('offset', 0) == 0)
    return False


def send_allowed(values, profile):
    return (set(values) == old.SEND_FIELDS and old.canonical(values.get('request_id'))
        and values.get('message', '').strip() == requested_message(profile)
        and values.get('day') == DAY and values.get('meal') == MEAL
        and type(values.get('stream')) is int and values['stream'] == 1
        and selection_allowed(values.get('view_context'), profile))


def request_policy(record, command, values, method, environ):
    if environ.get('PATH_INFO') != '/api/method/' + command or 'cmd' in values:
        return False
    profile = record['profile']
    if command == 'login':
        return method == 'POST' and set(values) == {'usr', 'pwd'} and values['usr'] == fixture.TEACHER and isinstance(values['pwd'], str)
    if command == 'logout':
        return method == 'POST' and not values
    if command.startswith(old.API):
        name = command[len(old.API):]
        if old.BUSINESS.get(name) != method:
            return False
        if name == 'send_message':
            return send_allowed(values, profile)
        if name == 'get_conversation':
            return not values  # No access to arbitrary history pages in this QA.
        try:
            attempt = old.private_read(folder(record['run_id']) / 'attempt.json')
        except FileNotFoundError:
            return False
        task = attempt['request_id']
        if values.get('task_id') != task:
            return False
        if name in {'cancel_task', 'retry_dispatch'}:
            return set(values) == {'task_id'}
        return (not set(values) - {'task_id', 'after'} and old.cursor(values.get('after', '0'), task)
            and (not environ.get('HTTP_LAST_EVENT_ID') or old.cursor(environ['HTTP_LAST_EVENT_ID'], task)))
    if command not in old.READS or method != 'GET':
        return False
    if command == 'frappe.auth.get_logged_user':
        return not values
    if command == 'tongjianyun.meal_views.get_view':
        return set(values) == {'selection_json'} and selection_allowed(values['selection_json'], profile)
    return (not set(values) - {'day', 'meal', 'group'} and values.get('day', DAY) == DAY
            and values.get('meal', MEAL) == MEAL and values.get('group', fixture.GROUP) == fixture.GROUP)


def tool_allowed(profile, tool, args):
    if type(args) is not dict:
        return False
    if tool == 'business_view':
        return set(args) == {'selection'} and selection_allowed(args['selection'], profile)
    if tool == 'business_catalog_read':
        return profile == 'catalog' and not set(args) - {'page_size'} and type(args.get('page_size', 20)) is int and 1 <= args.get('page_size', 20) <= 20
    if profile != 'business-save':
        return False
    if tool == 'scene_bootstrap':
        return not set(args) - {'day', 'meal', 'page_size'} and args.get('day') == DAY and args.get('meal', MEAL) == MEAL and type(args.get('page_size', 25)) is int and 1 <= args.get('page_size', 25) <= 25
    if tool == 'class_students_read':
        return not set(args) - {'group', 'page_size'} and args.get('group') == fixture.GROUP and type(args.get('page_size', 25)) is int and 1 <= args.get('page_size', 25) <= 25
    if tool == 'classroom_read':
        return args == {'group': fixture.GROUP, 'day': DAY}
    if tool == 'attendance_save':
        return (set(args) == {'group', 'day', 'changes', 'revision'} and args['group'] == fixture.GROUP and args['day'] == DAY
            and isinstance(args['revision'], str) and re.fullmatch('[a-f0-9]{64}', args['revision']) is not None
            and args['changes'] in ([{'student': fixture.STUDENTS[0], 'status': 'Present'}],
                [{'student': fixture.STUDENTS[0], 'status': 'Present', 'leave_reason': ''}]))
    return False


def tool_guard(record, claim, tool, arguments):
    run = folder(record['run_id'])
    pin(record)
    attempt = old.private_read(run / 'attempt.json')
    if (claim.identity.site != qa.SITE or claim.identity.owner != fixture.TEACHER
            or claim.identity.task_id != attempt['request_id'] or not tool_allowed(record['profile'], tool, arguments)):
        return False
    if tool == 'attendance_save':
        from tongjianyun.business_agent_writes import _arguments
        payload = digest(_arguments(tool, arguments))
        # A second revision is a second intent, even if it sets Present again.
        # Reserve BEFORE dispatch; failed/uncertain never receives automatic retry.
        with lock(run / 'request.lock'):
            path = run / 'write-intent.json'
            if path.exists():
                return old.private_read(path) == {'task_id': claim.identity.task_id, 'digest': payload}
            old.exclusive_json(path, {'task_id': claim.identity.task_id, 'digest': payload})
    return True


def reserve(record, values, frappe):
    if not send_allowed(values, record['profile']):
        raise PermissionError('Only the explicit fixed natural-language scenario is admitted')
    run = folder(record['run_id'])
    expected = {'request_id': values['request_id'], 'payload_sha256': digest(values), 'site': qa.SITE, 'owner': fixture.TEACHER}
    with lock(run / 'request.lock'):
        if (run / 'attempt.json').exists():
            actual = old.private_read(run / 'attempt.json')
            if any(actual.get(key) != value for key, value in expected.items()):
                raise PermissionError('One request per run; previous attempt is retained')
            return
        if record['profile'] == 'business-save':
            assert_empty(frappe)
        baseline = snapshot(frappe)
        prepare_baseline = old.private_read(run / 'prepare-baseline.json')
        delta = difference(prepare_baseline, baseline, 'catalog')
        if not delta['protected_passed']:
            raise PermissionError('Protected state changed since preparation; do not reset the baseline')
        # A crash between either exclusive write fails closed, not re-baselines.
        old.exclusive_json(run / 'model-baseline.json', baseline)
        old.exclusive_json(run / 'attempt.json', {**expected, 'run_id': record['run_id'],
            'source_sha256': record['source_sha256'], 'model_baseline_sha256': baseline['sha256'],
            'prepare_delta': delta, 'automatic_retry': False})


def check(profile):
    if profile not in PROFILES:
        raise ValueError('Explicit fixed profile required')
    frappe = environment()
    from tongjianyun.business_agent_worker import UnixLauncherRuntime, BusinessWorker
    import inspect
    if 'tool_guard' not in inspect.signature(BusinessWorker).parameters:
        raise PermissionError('Construction-only rejection guard is not installed in this candidate')
    if UnixLauncherRuntime(site=qa.SITE, sites_path=str(qa.SITES)).ready() is not True:
        raise PermissionError('Fixed QA native launcher unavailable')
    qa.verify_asset_evidence()
    previous = prior_proof()
    if profile == 'business-save':
        assert_empty(frappe)
    return frappe, {'site': qa.SITE, 'profile': profile, 'source_sha256': pin(), 'previous': previous,
                    'baseline': snapshot(frappe), 'model_started': False}


def idle_queue(frappe):
    """Read-only preflight: no competing business consumer, pending task or job."""
    from frappe.utils.background_jobs import generate_qname, get_redis_conn
    from rq import Queue
    from rq.registry import StartedJobRegistry
    from rq.worker_registration import get_keys
    base = qa.SITES / qa.SITE / 'private/business-codex/tasks'
    with read_db(base / 'business-tasks.sqlite3') as db:
        if db.execute("SELECT 1 FROM tasks WHERE status NOT IN ('completed','failed','cancelled') LIMIT 1").fetchone():
            raise PermissionError('Another business task is unresolved; never supersede it')
    frappe.init(site=qa.SITE, sites_path=str(qa.SITES))
    qa.guard(frappe.conf)
    try:
        # get_queue validates the *configured* queue list. Preparation must
        # inspect the real Redis namespace BEFORE installing this custom queue.
        # Constructing Queue is local only; its count property is native LLEN.
        queue = Queue(generate_qname(old.QUEUE), connection=get_redis_conn())
        # Registry.count cleans expired jobs; Worker.all removes stale worker
        # registrations. Neither mutation belongs in an idle proof. Even stale
        # entries are retained and require separate management investigation.
        if queue.count or StartedJobRegistry(queue=queue).get_job_count(cleanup=False):
            raise PermissionError('Business RQ queue still has pending/started jobs')
        if get_keys(queue=queue):  # Native per-queue SMEMBERS only; no cleanup.
            raise PermissionError('A worker registration still advertises this exact business queue')
    finally:
        frappe.destroy()


def prepare(run_id, profile):
    if profile not in PROFILES:
        raise ValueError('Explicit fixed profile required')
    environment()  # Refuse root/foreign paths BEFORE creating even a lock file.
    with lock(LOCK, create=True):
        if ACTIVE.exists():
            prior = old.private_read(ACTIVE)
            # A new reviewed revision can follow a fully restored earlier run;
            # only the new active run is source-pinned. Never rewrite the old run.
            earlier = old.private_read(folder(prior['run_id']) / 'run.json')
            if earlier.get('run_id') != prior['run_id'] or earlier.get('site') != qa.SITE or earlier.get('state') != 'restored':
                raise PermissionError('Restore the active journey before preparing another run')
        frappe, checked = check(profile)
        idle_queue(frappe)
        path = folder(run_id)
        if path.exists():
            raise PermissionError('Run UUID has already been used; never overwrite it')
        ROOT.mkdir(mode=0o700, exist_ok=True)
        from tongjianyun.business_agent_transport import private_directory
        private_directory(ROOT)
        path.mkdir(mode=0o700)
        old.exclusive_json(path / 'request.lock', {})
        site_path, common_path = qa.SITES / qa.SITE / 'site_config.json', qa.SITES / 'common_site_config.json'
        site, common = old.private_read(site_path), old.private_read(common_path)
        workers = common.get('workers', {})
        if type(workers) is not dict:
            raise PermissionError('Invalid native worker config')
        before = {'business_codex_enabled': {'present': 'business_codex_enabled' in site, 'value': site.get('business_codex_enabled')},
                  'workers': {'present': 'workers' in common}, 'queue': {'present': old.QUEUE in workers, 'value': workers.get(old.QUEUE)}}
        record = {key: value for key, value in checked.items() if key != 'baseline'}
        record.update(version=1, run_id=run_id, state='preparing', before=before, day=DAY,
                      tool_guard='construction-only reject restriction; actual original worker and transactions',
                      requested_message=requested_message(profile))
        old.exclusive_json(path / 'prepare-baseline.json', checked['baseline'])
        old.exclusive_json(path / 'run.json', record)
        old.atomic_json(ACTIVE, {'run_id': run_id})
        site['business_codex_enabled'] = 1
        common['workers'] = {**workers, old.QUEUE: {'timeout': -1}}
        old.atomic_json(site_path, site)
        old.atomic_json(common_path, common)
        old.atomic_json(path / 'run.json', {**record, 'state': 'prepared'})
        return {'run_id': run_id, 'profile': profile, 'prepared': True, 'model_started': False,
                'requested_message': requested_message(profile), 'url': f'{qa.ORIGIN}/tongjianyun-meal-scene?day={DAY}&meal={MEAL}'}


def proc_identity(pid):
    path = Path('/proc') / str(pid)
    try:
        raw = (path / 'stat').read_text()
        return {'pid': pid, 'start_ticks': raw.rsplit(')', 1)[1].split()[19],
                'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'cmdline_sha256': hashlib.sha256((path / 'cmdline').read_bytes()).hexdigest()}
    except FileNotFoundError:
        return None


@contextmanager
def process_record(run_id, role):
    path = folder(run_id) / (role + '.json')
    identity = proc_identity(os.getpid())
    old.exclusive_json(path, {'identity': identity, 'running': True})
    try:
        yield
    finally:
        old.atomic_json(path, {'identity': identity, 'running': False})


def authenticated_guard(record, frappe, native_auth):
    def validate():
        native_auth()
        if frappe.session.user not in {'Guest', fixture.TEACHER}:
            raise frappe.PermissionError('Synthetic ordinary teacher only')
        path = frappe.request.path
        if path == '/tongjianyun-meal-scene' or path.startswith('/api/method/' + old.API):
            if frappe.session.user != fixture.TEACHER:
                raise frappe.PermissionError('Native teacher session required')
        if path == '/api/method/' + old.API + 'send_message':
            reserve(record, {key: value for key, value in frappe.form_dict.items() if key != 'cmd'}, frappe)
    return validate


class Boundary:
    def __init__(self, record, application):
        self.record = record
        self.application = qa.QAFirewall(application, request_policy=lambda *args: request_policy(record, *args))

    def __call__(self, environ, start_response):
        load(self.record['run_id'], ready=True)
        path = environ.get('PATH_INFO', '')
        if (environ.get('HTTP_HOST') not in {f'{qa.SITE}:{qa.PORT}', f'127.0.0.1:{qa.PORT}', f'localhost:{qa.PORT}'}
                or environ.get('HTTP_X_FRAPPE_SITE_NAME', qa.SITE) != qa.SITE):
            return qa.reply(start_response, '403 Forbidden', {'message': 'QA site only'})
        if path == '/__qa__/health' and environ.get('REQUEST_METHOD') == 'GET':
            return qa.reply(start_response, '200 OK', {'profile': 'business-journey-v1', 'run_id': self.record['run_id'],
                'scenario': self.record['profile'], 'native_auth_required': True, 'one_request_only': True,
                'business_save_allowed': self.record['profile'] == 'business-save', 'browser_verified': False})
        if path not in {'/', '/login', '/tongjianyun-entry', '/tongjianyun-meal-scene', '/favicon.ico'} and not path.startswith(('/assets/', '/api/method/')):
            return qa.reply(start_response, '403 Forbidden', {'message': 'Outside the QA journey'})
        return self.application(environ, start_response)


def serve(run_id):
    frappe, record = environment(), load(run_id, ready=True)
    import frappe.app
    from werkzeug.serving import make_server, WSGIRequestHandler
    frappe.app.validate_auth = authenticated_guard(record, frappe, frappe.app.validate_auth)
    frappe.app._site, frappe.app._sites_path = qa.SITE, str(qa.SITES)
    class Quiet(WSGIRequestHandler):
        def log(self, *args):
            pass
    with process_record(run_id, 'web'):
        server = make_server('127.0.0.1', qa.PORT, Boundary(record, frappe.app.application_with_statics()), threaded=True, request_handler=Quiet)
        try:
            server.serve_forever()
        finally:
            server.server_close()


def validate_job(record, job, queue_name, expected_queue):
    if (queue_name != expected_queue or job.origin != expected_queue or job.func_name != 'frappe.utils.background_jobs.execute_job'
            or job.args or job.timeout != -1 or job.retries_left not in (None, 0)
            or job._success_callback_name is not None or job._stopped_callback_name is not None
            or job._failure_callback_name != 'frappe.utils.background_jobs.truncate_failed_registry'):
        raise PermissionError('Unexpected native RQ job')
    values = job.kwargs
    if (type(values) is not dict or set(values) != {'site', 'user', 'method', 'event', 'job_name', 'is_async', 'kwargs'}
            or values['site'] != qa.SITE or values['user'] != fixture.TEACHER or values['method'] != old.WORKER_METHOD
            or values['job_name'] != old.WORKER_METHOD or values['event'] is not None or values['is_async'] is not True):
        raise PermissionError('Only original native business run_task may execute')
    attempt = old.private_read(folder(record['run_id']) / 'attempt.json')
    if values['kwargs'] != {'owner': fixture.TEACHER, 'task_id': attempt['request_id']}:
        raise PermissionError('Job was not reserved by this native HTTP request')


def worker(run_id):
    frappe, record = environment(), load(run_id, ready=True)
    from rq import Worker
    from frappe.utils.background_jobs import get_queue
    from tongjianyun import business_agent_worker as implementation
    Original = implementation.BusinessWorker
    # Fixed process-local constructor restriction only. Native service.run_task
    # imports this class; original run/dispatch/store/transactions are inherited.
    # No old harness global or evidence path is patched.
    class RestrictedBusinessWorker(Original):
        def __init__(self, *args, **kwargs):
            if kwargs.get('tool_guard') is not None:
                raise PermissionError('Unexpected second guard')
            kwargs['tool_guard'] = lambda claim, tool, values: tool_guard(record, claim, tool, values)
            super().__init__(*args, **kwargs)
    implementation.BusinessWorker = RestrictedBusinessWorker
    frappe.init(site=qa.SITE, sites_path=str(qa.SITES))
    qa.guard(frappe.conf)
    queue = get_queue(old.QUEUE)
    expected_queue = queue.name
    frappe.destroy()
    class FixedWorker(Worker):
        def execute_job(self, job, selected_queue):
            load(run_id, ready=True)
            validate_job(record, job, selected_queue.name, expected_queue)
            return super().execute_job(job, selected_queue)
    instance = FixedWorker([queue], connection=queue.connection, name='tgy-business-journey-' + run_id)
    try:
        with process_record(run_id, 'worker'):
            logging.disable(logging.CRITICAL)
            with open(os.devnull, 'w') as quiet, redirect_stdout(quiet), redirect_stderr(quiet):
                instance.work(with_scheduler=False, logging_level='CRITICAL')
    finally:
        implementation.BusinessWorker = Original


def rq_proof(frappe, task_id):
    from frappe.utils.background_jobs import get_job
    frappe.init(site=qa.SITE, sites_path=str(qa.SITES))
    qa.guard(frappe.conf)
    try:
        # Same pinned TaskStore.job_id encoding, without its schema-writing
        # constructor. get_job adds Frappe's ordinary site prefix itself.
        job_id = 'business-codex-' + hashlib.sha256(qa.SITE.encode()).hexdigest()[:16] + '-' + task_id
        job = get_job(job_id)
        status = getattr(job.get_status(refresh=True), 'value', None) if job else None
        result = job.return_value(refresh=True) if job and status == 'finished' else None
        return {'status': status, 'started': isinstance(result, dict) and result.get('started') is True,
                'result_status': result.get('status') if isinstance(result, dict) else None}
    finally:
        frappe.destroy()


def fresh_readback(frappe, profile):
    from check_worker_live import readonly_adapter
    def read():
        fixture.account_guard(frappe)
        if profile == 'business-save':
            from tongjianyun import classroom
            result = classroom._attendance(classroom._scope(fixture.GROUP), classroom._day(DAY))
            statuses = {item['student']: item['status'] for item in result['students']}
            return {'fresh_connection': True, 'native_revision_sha256': result['revision'],
                    'counts': result['counts'], 'passed': statuses == {fixture.STUDENTS[0]: 'Present', fixture.STUDENTS[1]: 'Unknown'}}
        from tongjianyun.meal_views import get_view
        view = get_view({'view': 'frappe_catalog', 'day': DAY, 'meal': MEAL, 'kind': 'doctype', 'offset': 0})
        summary = view.get('summary', {})
        entries = summary.get('page_entries', [])
        return {'fresh_connection': True, 'view': view['selection'], 'title': view['title'],
                'native_page_sha256': digest(entries), 'page_entry_count': len(entries),
                'passed': summary.get('display_level') == 'entries' and bool(entries)
                          and all(item.get('kind') == 'doctype' for item in entries)}
    return readonly_adapter(frappe).run_check(fixture.TEACHER, read)


def evidence(run_id):
    frappe, record = environment(), load(run_id)
    run = folder(run_id)
    attempt = old.private_read(run / 'attempt.json')
    proof = task_proof(attempt['request_id'])
    native, host, events = proof['native'], proof['host'], proof.pop('events')
    if proof['status'] not in {'completed', 'failed', 'cancelled'} or native['state'] != 'exited' or native['lease_closed'] is not True or native['active_writes'] != 0 or host['active'] or host['uncertain'] or not host['present'] or not host['closed']:
        raise PermissionError('Do not take a final baseline until native and host writes are drained')
    after = snapshot(frappe)
    baseline = old.private_read(run / 'model-baseline.json')
    delta = difference(baseline, after, record['profile'])
    target_view = 'classroom_day' if record['profile'] == 'business-save' else 'frappe_catalog'
    published = any(event.get('kind') == 'view' and event.get('selection', {}).get('view') == target_view
                    and selection_allowed(event['selection'], record['profile']) for event in events)
    rq = rq_proof(frappe, attempt['request_id'])
    readback = fresh_readback(frappe, record['profile'])
    count = sum(row['doctype'] == 'Student Attendance' and row['scope'].get('date') == DAY
                for row in after['records'].values())
    summaries = sum(row['doctype'] == 'Tongjianyun Daily Meal Confirmation' and row['scope'].get('meal_date') == DAY
                    for row in after['records'].values())
    writes_ok = (count == 1 and summaries == 1 and host['committed'] == 1) if record['profile'] == 'business-save' else host['committed'] == 0
    sources_ok = proof.get('student_source_ids_exact') is True if record['profile'] == 'business-save' else proof.get('doctype_scope_count', 0) > 0
    report = {'run_id': run_id, 'profile': record['profile'], 'task_id': attempt['request_id'], 'source_sha256': pin(record),
        'previous': record['previous'], 'execution': proof, 'rq': rq, 'difference': delta,
        'fresh_native_readback': readback, 'registered_sources_verified': sources_ok,
        'event_count': len(events), 'event_kinds': sorted({event.get('kind') for event in events}),
        'view_requested': published, 'expected_write_count_verified': writes_ok,
        'browser_sse_and_display_verified': False, 'backend_passed': bool(proof['status'] == 'completed'
            and native['exit_code'] == 0 and native['active_writes'] == 0 and delta['protected_passed'] and writes_ok
            and readback.get('passed') is True and sources_ok
            and rq == {'status': 'finished', 'started': True, 'result_status': 'completed'}
            and published and any(event.get('kind') == 'message' for event in events)),
        'note': 'Backend evidence is not browser/SSE evidence; original failure remains unexplained and unchanged.'}
    receipt_id = str(uuid.uuid4())
    old.exclusive_json(run / ('after-' + receipt_id + '.json'), after)
    old.exclusive_json(run / ('evidence-' + receipt_id + '.json'), report)
    return report


def restore(run_id):
    frappe = environment()
    with lock(LOCK):
        record, run = load(run_id), folder(run_id)
        if old.private_read(ACTIVE).get('run_id') != run_id or record['state'] not in {'preparing', 'prepared'}:
            raise PermissionError('Only the exact active run can restore its own fields')
        for role in ('web', 'worker'):
            path = run / (role + '.json')
            if path.exists():
                saved = old.private_read(path)
                current = proc_identity(saved['identity']['pid'])
                if current is not None and current == saved['identity']:
                    raise PermissionError('Stop the exact recorded foreground process first')
        if (run / 'attempt.json').exists():
            task = old.private_read(run / 'attempt.json')['request_id']
            proof = task_proof(task)
            if (proof['status'] not in {'completed', 'failed', 'cancelled'} or proof['native']['state'] != 'exited'
                    or proof['native']['lease_closed'] is not True or proof['native']['active_writes'] != 0 or not proof['host']['present']
                    or not proof['host']['closed'] or proof['host']['active'] or proof['host']['uncertain']):
                raise PermissionError('Task or write outcome remains unresolved; preserve all fences')
            unit_proof(task)
            if rq_proof(frappe, task)['status'] not in {'finished', 'failed', 'stopped', 'canceled'}:
                raise PermissionError('Native RQ workhorse has not finished')
        with socket.socket() as connection:
            if connection.connect_ex(('127.0.0.1', qa.PORT)) == 0:
                raise PermissionError('QA listener remains')
        paths = qa.SITES / qa.SITE / 'site_config.json', qa.SITES / 'common_site_config.json'
        site, common = map(old.private_read, paths)
        old.restore_fields(site, common, record['before'])
        old.atomic_json(paths[0], site)
        old.atomic_json(paths[1], common)
        old.atomic_json(run / 'run.json', {**record, 'state': 'restored'})
        return {'run_id': run_id, 'restored': True, 'business_records_and_all_evidence_retained': True}


def verify(run_id):
    """Readiness only: never enqueue a task or certify a browser interaction."""
    frappe, record = environment(), load(run_id, ready=True)
    from tongjianyun.business_agent_service import available
    from urllib.request import urlopen
    frappe.init(site=qa.SITE, sites_path=str(qa.SITES))
    qa.guard(frappe.conf)
    frappe.connect(set_admin_as_user=False)
    try:
        frappe.set_user(fixture.TEACHER)
        if available() is not True:
            raise PermissionError('Native isolated runtime or ordinary RQ worker unavailable')
    finally:
        frappe.destroy()
    with urlopen(f'http://127.0.0.1:{qa.PORT}/__qa__/health', timeout=5) as response:
        health = json.load(response)
    if health.get('profile') != 'business-journey-v1' or health.get('run_id') != run_id:
        raise PermissionError('Wrong foreground QA run')
    return {'run_id': run_id, 'scenario': record['profile'], 'http_rq_ready': True,
            'browser_sse_and_display_verified': False, 'model_started': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'prepare', 'serve', 'worker', 'verify', 'evidence', 'restore-config'), nargs='?', default='check')
    parser.add_argument('--run-id')
    parser.add_argument('--profile', choices=PROFILES)
    args = parser.parse_args()
    if args.command != 'check' and not old.canonical(args.run_id):
        parser.error('Explicit new or existing --run-id UUID is required')
    if args.command == 'prepare' and args.profile is None:
        parser.error('prepare requires an explicit --profile business-save or catalog')
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    if args.command == 'check':
        _, result = check(args.profile or 'catalog')
        result.pop('baseline')
        result['read_only'] = True
    elif args.command == 'prepare':
        result = prepare(args.run_id, args.profile)
    elif args.command == 'restore-config':
        result = restore(args.run_id)
    else:
        result = globals()[args.command](args.run_id)
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, default=str), flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        print(json.dumps({'ok': False, 'error_class': type(error).__name__, 'message': 'QA journey stopped; retained evidence must be reviewed.'}), flush=True)
        raise SystemExit(1)
