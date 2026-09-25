"""Explicit recovery ONLY for an uploaded recipe request never accepted as a task.

The original source-pinned journey is not changed. check is read-only; finalize
first closes its original admission fence and proves the completed native HTTP
callbacks, absent task/outbox/events/authority/host/RQ/native state, and unchanged
protected data. Only then may it stop the two original exact processes and
restore the three originally owned config fields. No task is retried, cancelled,
sealed, fabricated, deleted or declared exited. The native upload is retained.

The sole privileged operation is the existing codex-deepseek-admin app-server's
command/exec API running a fixed Python -I/-B read-only lstat probe of the
original launcher's exact task paths. No thread/turn/model command is sent. The
probe imports only stdlib, reads no record contents or credentials and refuses
any existing task path. All other work uses the original non-root site user.
Unknown evidence fails closed; no sudo rule, launcher or daemon is installed.
If the native Python lacks pidfd APIs, a fixed /usr/bin/python3 standard-library
child performs the same exact-PID checks as the same non-root UID. Its bounded
JSON input is checked against this run's original web/worker record and fence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import select
import selectors
import signal
import subprocess
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import serve_recipe_journey as j

SELF = 'deploy/business_codex/finalize_unaccepted_recipe_journey.py'
ADMIN_ARGV = ('/usr/bin/sudo', '-n', '/usr/local/sbin/codex-deepseek-admin', 'app-server')
ROOT_PROBE = r'''import json, os, pathlib, stat, sys, uuid
task = sys.argv[1]
if os.geteuid() != 0 or str(uuid.UUID(task)) != task:
    raise PermissionError('Exact root observation identity required')
bases = (pathlib.Path('/var/lib/tongjianyun-business-codex/launcher'),
         pathlib.Path('/run/tongjianyun-business-codex/tasks'), pathlib.Path('/run'),
         pathlib.Path('/sys/fs/cgroup/system.slice'))
for base in bases:
    if base.resolve(strict=True) != base:
        raise PermissionError('Root observation path changed')
    for part in (base, *base.parents):
        info = part.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError('Unsafe root observation directory')
paths = (bases[0] / (task + '.json'), bases[1] / task, bases[2] / ('tgy-business-' + task),
         bases[3] / ('tgy-business-codex-' + task + '.service'))
for path in paths:
    try:
        path.lstat()
    except FileNotFoundError:
        continue
    raise PermissionError('Original native task evidence exists; preserve it')
print(json.dumps({'task_id': task, 'root_lstat': True,
                  'tombstone_absent': True, 'input_absent': True, 'work_absent': True,
                  'cgroup_absent': True}))
'''
PIDFD_STOP_PROBE = r'''import hashlib, json, os, pathlib, re, select, signal, stat, sys, time, uuid
def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate input field')
        value[key] = item
    return value
def decode(raw):
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite input')))
raw = sys.stdin.buffer.read(4097)
if not 1 <= len(raw) <= 4096:
    raise PermissionError('Bounded exact process input required')
value = decode(raw)
if type(value) is not dict or set(value) != {'run_id', 'role', 'identity', 'uid'}:
    raise PermissionError('Exact process input fields required')
run_id, role, expected, uid = value['run_id'], value['role'], value['identity'], value['uid']
if (type(uid) is not int or uid <= 0 or os.geteuid() != uid or os.getuid() != uid
        or type(run_id) is not str or str(uuid.UUID(run_id)) != run_id or role not in ('web', 'worker')):
    raise PermissionError('Original non-root UID and exact run/role required')
if (type(expected) is not dict or set(expected) != {'pid', 'start_ticks', 'boot_id', 'cmdline_sha256'}
        or type(expected['pid']) is not int or expected['pid'] <= 1 or expected['pid'] == os.getpid()
        or type(expected['start_ticks']) is not str or not re.fullmatch('[0-9]+', expected['start_ticks'])
        or type(expected['boot_id']) is not str or str(uuid.UUID(expected['boot_id'])) != expected['boot_id']
        or type(expected['cmdline_sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', expected['cmdline_sha256'])):
    raise PermissionError('Complete original process identity required')
root = pathlib.Path('/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925/recipe-journeys')
run = root / run_id
if run.resolve(strict=True) != run:
    raise PermissionError('Original run path changed')
info = run.lstat()
if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
    raise PermissionError('Original private run directory required')
def original(name):
    path = run / name
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_nlink != 1
                or info.st_mode & 0o077 or not 1 <= info.st_size <= 131072):
            raise PermissionError('Original private process evidence required')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(131073)
        if len(raw) != info.st_size:
            raise PermissionError('Original process evidence changed')
        return decode(raw)
    finally:
        os.close(fd)
record = original('run.json')
site = 'unified-business-acceptance.localhost'
owner = 'browser-manager-02e16a31d7@example.invalid'
if (record.get('run_id') != run_id or record.get('site') != site or record.get('owner') != owner
        or record.get('profile') != 'recipe-journey-v1' or record.get('state') != 'prepared'
        or original('admission-closed.json') != {'run_id': run_id, 'site': site, 'owner': owner, 'closed': True}
        or original(role + '.json').get('identity') != expected):
    raise PermissionError('Input is not the original fenced process record')
pid = expected['pid']
def identity():
    path = pathlib.Path('/proc') / str(pid)
    try:
        if path.stat().st_uid != uid:
            raise PermissionError('Original process UID changed')
        raw = (path / 'stat').read_text()
        return {'pid': pid, 'start_ticks': raw.rsplit(')', 1)[1].split()[19],
                'boot_id': pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'cmdline_sha256': hashlib.sha256((path / 'cmdline').read_bytes()).hexdigest()}
    except FileNotFoundError:
        return None
current = identity()
sent = False
if current is not None:
    if current != expected:
        raise PermissionError('Original PID was reused or identity changed')
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise PermissionError('Fixed system Python lacks exact pidfd APIs')
    fd = os.pidfd_open(pid)
    try:
        if identity() != expected:
            raise PermissionError('Original process changed after pidfd open')
        signal.pidfd_send_signal(fd, signal.SIGTERM)
        sent = True
        if not select.select([fd], [], [], 10)[0]:
            raise PermissionError('Original process did not exit; no force kill')
    finally:
        os.close(fd)
# pidfd readiness may briefly precede the SSH parent's wait/reap. Allow at most
# one second of read-only observation, only for the same original zombie; no
# additional signal is sent and a reused/live identity immediately fails.
deadline = time.monotonic() + 1
while True:
    current = identity()
    if current is None:
        break
    try:
        fields = (pathlib.Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
    except FileNotFoundError:
        continue
    if (not sent or current['boot_id'] != expected['boot_id']
            or current['start_ticks'] != expected['start_ticks'] or fields[19] != expected['start_ticks']
            or fields[0] not in ('Z', 'X')
            or current['cmdline_sha256'] not in (expected['cmdline_sha256'], hashlib.sha256(b'').hexdigest())):
        raise PermissionError('Original PID identity changed or remains live; preserve and inspect')
    if time.monotonic() >= deadline:
        raise PermissionError('Original PID remains present; preserve and inspect')
    time.sleep(0.02)
print(json.dumps({'run_id': run_id, 'role': role, 'pid': pid,
                  'original_process_absent': True, 'term_sent': sent, 'pidfd_verified': sent}))
'''


def canonical(value):
    if not j.old.canonical(value):
        raise ValueError('Explicit canonical UUID required')
    return value


def environment(expected_sha256):
    if (not isinstance(expected_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_sha256)
            or Path(__file__).resolve() != j.qa.SOURCE / SELF
            or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != expected_sha256):
        raise PermissionError('Exact reviewed recovery helper hash and path required')
    return j.environment()  # Original QA/site/user/dependency/source safety checks.


def load(run_id, task_id):
    canonical(run_id)
    canonical(task_id)
    record = j.load(run_id)
    if (record.get('state') != 'prepared'
            or j.old.private_read(j.ACTIVE) != {'run_id': run_id}
            or j.registered_task(record) != task_id):
        raise PermissionError('Only the active original unaccepted request can be finalized')
    attempt = j.old.private_read(j.folder(run_id) / 'attempt.json')
    before = j.old.private_read(j.folder(run_id) / 'model-baseline.json')
    if (attempt.get('source_sha256') != record['source_sha256']
            or attempt.get('model_baseline_sha256') != j.digest(before)
            or attempt.get('automatic_retry') is not False
            or attempt.get('file_id') != j.uploaded(record)['file_id']):
        raise PermissionError('Original attempt evidence no longer matches the pinned run')
    return record


def absent_rows(database, task_id, *, host=False):
    """Read-only connections include SQLite WAL; no Store/Ledger constructors."""
    tables = ('tasks', 'aliases') if host else ('tasks', 'outbox', 'events', 'authorities')
    with j.previous.read_db(database) as db:
        identity = db.execute('SELECT site FROM identity WHERE id=1').fetchone()
        if identity is None or identity[0] != j.qa.SITE:
            raise PermissionError('Original durable store belongs to another site')
        counts = {table: db.execute('SELECT COUNT(*) FROM ' + table + ' WHERE task_id=?',
                                  (task_id,)).fetchone()[0] for table in tables}
        owner_count = db.execute('SELECT COUNT(*) FROM tasks WHERE owner=?', (j.OWNER,)).fetchone()[0]
        if any(counts.values()) or owner_count:
            raise PermissionError('Original manager task or task-associated durable evidence exists')
    return {'tables': counts, 'owner_history_count': owner_count}


def durable_absence(task_id):
    base = j.qa.SITES / j.qa.SITE / 'private/business-codex/tasks'
    return {'task_store': absent_rows(base / 'business-tasks.sqlite3', task_id),
            'host_ledger': absent_rows(base / 'business-writes.sqlite3', task_id, host=True)}


def text_id(value):
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='strict')
    if isinstance(value, str):
        return value
    raise PermissionError('Unknown Redis identifier representation')


def matching_job(value, backend_id):
    value = text_id(value)
    # RQ 2 started registries may use job_id:execution_id composite members.
    return value == backend_id or value.startswith(backend_id + ':')


def queue_absence(frappe, task_id):
    from frappe.utils.background_jobs import create_job_id, generate_qname, get_redis_conn
    from rq import Queue
    from rq.registry import (StartedJobRegistry, DeferredJobRegistry, ScheduledJobRegistry,
                             FailedJobRegistry, FinishedJobRegistry, CanceledJobRegistry)
    from rq.worker_registration import get_keys
    frappe.init(site=j.qa.SITE, sites_path=str(j.qa.SITES))
    j.qa.guard(frappe.conf)
    try:
        logical = 'business-codex-' + hashlib.sha256(j.qa.SITE.encode()).hexdigest()[:16] + '-' + task_id
        backend_id = create_job_id(logical)
        if backend_id != j.qa.SITE + '||' + logical:
            raise PermissionError('Native RQ job identity encoding changed')
        connection = get_redis_conn()
        queue = Queue(generate_qname(j.old.QUEUE), connection=connection)
        # Raw read commands, never get_job/Worker.all/registry cleanup methods.
        if (connection.exists('rq:job:' + backend_id)
                or connection.exists('rq:executions:' + backend_id)):
            raise PermissionError('Original exact RQ job or execution registry exists')
        cursor = 0
        for _ in range(1000):
            cursor, entries = connection.scan(cursor=cursor, match='rq:execution:' + backend_id + ':*', count=100)
            if entries:
                raise PermissionError('Original RQ execution entity exists')
            if cursor == 0:
                break
        else:
            raise PermissionError('Bounded RQ execution inspection incomplete')
        count = connection.llen(queue.key)
        if count or connection.llen(queue.key + ':intermediate'):
            raise PermissionError('Business queue or intermediate queue is not empty; preserve all processes')
        registries = {}
        for cls in (StartedJobRegistry, DeferredJobRegistry, ScheduledJobRegistry,
                    FailedJobRegistry, FinishedJobRegistry, CanceledJobRegistry):
            registry = cls(queue=queue)
            count = connection.zcard(registry.key)
            if count > 10000:
                raise PermissionError('RQ registry inspection bound exceeded')
            members = connection.zrange(registry.key, 0, -1)
            if len(members) != count or any(matching_job(value, backend_id) for value in members):
                raise PermissionError('Original RQ registry contains this task or changed during inspection')
            if cls is StartedJobRegistry and count:
                raise PermissionError('Business workhorse still has active registry entries')
            registries[cls.__name__] = {'exact_task_absent': True, 'entry_count': count}
        keys = list(get_keys(queue=queue))  # SMEMBERS only; no stale-worker cleanup.
        if len(keys) > 100:
            raise PermissionError('RQ worker inspection bound exceeded')
        for key in keys:
            state, current = connection.hmget(key, 'state', 'current_job')
            if state is None or text_id(state) != 'idle' or current not in (None, b'', ''):
                raise PermissionError('A registered worker is not demonstrably idle')
        return {'logical_job_id': logical, 'exact_job_absent': True, 'execution_entities_absent': True,
                'queue_count': 0, 'intermediate_queue_count': 0,
                'registries': registries, 'idle_registered_workers': len(keys)}
    finally:
        frappe.destroy()


def admin_frames(task_id):
    canonical(task_id)
    return ({'id': 1, 'method': 'initialize', 'params': {
                'clientInfo': {'name': 'qa_readonly_recovery', 'version': '1'}}},
            {'method': 'initialized', 'params': {}},
            {'id': 2, 'method': 'command/exec', 'params': {
                'command': ['/usr/bin/python3', '-I', '-B', '-c', ROOT_PROBE, task_id],
                'cwd': '/', 'sandboxPolicy': {'type': 'dangerFullAccess'}, 'timeoutMs': 10000}})


class AdminProtocol:
    """Bounded JSON-RPC response reader; no server message ever triggers a tool."""
    def __init__(self):
        self.buffer, self.stdout_bytes, self.stderr_bytes, self.frames = b'', 0, 0, 0

    def response(self, source, chunk, expected_id):
        if source == 'stderr':
            self.stderr_bytes += len(chunk)
            if self.stderr_bytes > 16384:
                raise PermissionError('Administrator channel stderr bound exceeded')
            return None
        self.stdout_bytes += len(chunk)
        self.buffer += chunk
        if self.stdout_bytes > 131072 or len(self.buffer) > 65536:
            raise PermissionError('Administrator response bound exceeded')
        while b'\n' in self.buffer:
            raw, self.buffer = self.buffer.split(b'\n', 1)
            value = j.qa.unique_json(raw.decode('utf-8'))
            self.frames += 1
            if self.frames > 100 or type(value) is not dict:
                raise PermissionError('Invalid administrator protocol response')
            if 'id' not in value:
                if (set(value) - {'method', 'params', 'jsonrpc', 'emittedAtMs'}
                        or not isinstance(value.get('method'), str) or not 1 <= len(value['method']) <= 128
                        or value.get('jsonrpc', '2.0') != '2.0'
                        or ('emittedAtMs' in value and (type(value['emittedAtMs']) is not int
                            or not 0 <= value['emittedAtMs'] <= 9007199254740991))):
                    raise PermissionError('Unexpected administrator channel frame')
                continue  # Bounded notifications are ignored, never executed or disclosed.
            if (type(value['id']) is not int or value['id'] != expected_id
                    or set(value) - {'id', 'result', 'jsonrpc'} or type(value.get('result')) is not dict
                    or value.get('jsonrpc', '2.0') != '2.0'):
                raise PermissionError('Unexpected administrator JSON-RPC result')
            return value['result']
        return None


def admin_probe(task_id):
    initialize, initialized, command = admin_frames(task_id)
    process = subprocess.Popen(list(ADMIN_ARGV), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, bufsize=0, cwd='/',
                               env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
    protocol = AdminProtocol()
    deadline = time.monotonic() + 25
    input_closed = False
    def close_input():
        nonlocal input_closed
        if not input_closed:
            input_closed = True
            try:
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
    def send(value):
        raw = (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
        if process.stdin.write(raw) != len(raw):
            raise PermissionError('Administrator request frame was not completely written')
        process.stdin.flush()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
            selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
            def receive(expected):
                while time.monotonic() < deadline:
                    result = protocol.response('stdout', b'', expected)
                    if result is not None:
                        return result
                    for key, _ in selector.select(min(0.5, max(0, deadline - time.monotonic()))):
                        chunk = os.read(key.fileobj.fileno(), 4096)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            if key.data == 'stdout':
                                raise PermissionError('Administrator channel ended without exact response')
                            continue
                        result = protocol.response(key.data, chunk, expected)
                        if result is not None:
                            return result
                raise PermissionError('Administrator read-only command deadline exceeded')
            send(initialize)
            receive(1)
            send(initialized)
            send(command)
            result = receive(2)
            if (set(result) != {'exitCode', 'stdout', 'stderr'} or type(result['exitCode']) is not int
                    or result['exitCode'] != 0 or not isinstance(result['stdout'], str)
                    or len(result['stdout'].encode()) > 4096 or result['stderr'] != ''):
                raise PermissionError('Administrator command did not return exact successful bounded output')
            # A successful first response is insufficient: consume both pipes to
            # EOF, including already-buffered frames. Only bounded notifications
            # may follow; duplicate responses, server requests and partial JSON
            # cannot be hidden behind the accepted command result.
            close_input()
            protocol.response('stdout', b'', None)
            closing_deadline = time.monotonic() + 10
            while selector.get_map():
                if time.monotonic() >= closing_deadline:
                    raise PermissionError('Administrator channel did not drain to both pipe EOFs')
                for key, _ in selector.select(min(0.5, max(0, closing_deadline - time.monotonic()))):
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        if key.data == 'stdout' and protocol.buffer:
                            raise PermissionError('Administrator stdout ended with partial JSON')
                        continue
                    protocol.response(key.data, chunk, None)
            return result['stdout']
    finally:
        close_input()  # Native app-server exits on EOF; never start a thread or turn.
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()  # Only this newly created management transport, never QA/native tasks.
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                raise PermissionError('Read-only administrator transport did not close; inspect it explicitly') from None
            raise PermissionError('Read-only administrator transport required termination; preserve the run') from None
        finally:
            process.stdout.close()
            process.stderr.close()
        if process.returncode != 0:
            raise PermissionError('Read-only administrator transport did not exit cleanly')


def native_absence(task_id):
    canonical(task_id)
    output = admin_probe(task_id)
    expected = {'task_id': task_id, 'root_lstat': True, 'tombstone_absent': True,
                'input_absent': True, 'work_absent': True, 'cgroup_absent': True}
    observed = j.qa.unique_json(output)
    if (type(observed) is not dict or set(observed) != set(expected)
            or observed.get('task_id') != task_id
            or any(observed.get(key) is not True for key in expected if key != 'task_id')):
        raise PermissionError('Unexpected root observation evidence')
    unit = j.previous.unit_proof(task_id)
    if (unit.get('LoadState') != 'not-found' or unit.get('ActiveState') != 'inactive'
            or unit.get('SubState') != 'dead'):
        raise PermissionError('Original native task unit has evidence; preserve it')
    return {**expected, 'unit': unit, 'native_state': 'never_accepted_not_exit_evidence'}


def protected_delta(record, frappe):
    upload = j.uploaded(record)
    def fresh():
        from tongjianyun.business_agent_attachments import _load
        j.assert_empty(frappe)
        _load(upload['file_id'], upload['descriptor'])
    j.readonly(frappe, fresh)
    after = j.snapshot(frappe)
    before = j.old.private_read(j.folder(record['run_id']) / 'prepare-baseline.json')
    delta = j.difference(before, after, file_id=upload['file_id'])
    if not delta['protected_passed']:
        raise PermissionError('Protected recipe/account/File baseline changed beyond the native upload')
    return {'difference': delta, 'after_snapshot_sha256': j.digest(after),
            'retained_native_file': upload['file_id'], 'native_file_verified': True}


def collect(record, frappe, task_id, *, fenced):
    j.pin(record)
    if fenced:
        expected = {'run_id': record['run_id'], 'site': j.qa.SITE, 'owner': j.OWNER, 'closed': True}
        if j.old.private_read(j.folder(record['run_id']) / 'admission-closed.json') != expected:
            raise PermissionError('No exact persistent original admission fence')
    j.http_drained(record)
    if j.registered_task(record) != task_id:
        raise PermissionError('Original HTTP request identity changed')
    durable = durable_absence(task_id)
    queue = queue_absence(frappe, task_id)
    native = native_absence(task_id)
    protected = protected_delta(record, frappe)
    # Recheck durable/RQ evidence after independent database/native reads.
    if durable_absence(task_id) != durable or queue_absence(frappe, task_id) != queue:
        raise PermissionError('Absence evidence changed while collecting recovery proof')
    return {'run_id': record['run_id'], 'request_id': task_id, 'site': j.qa.SITE, 'owner': j.OWNER,
            'source_sha256': record['source_sha256'], 'admission_closed': fenced,
            'native_http_completed_and_closed': True, 'durable': durable, 'rq': queue,
            'native': native, 'protected': protected, 'classification': 'never_accepted',
            'business_journey_passed': False, 'task_retried': False, 'records_retained': True}


def stop_processes(record):
    stopped = []
    for role in ('web', 'worker'):
        # Both process records are mandatory for this specific live-run recovery.
        saved = j.old.private_read(j.folder(record['run_id']) / (role + '.json'))
        identity = saved['identity']
        pid = identity['pid']
        if type(pid) is not int or pid <= 1 or pid == os.getpid():
            raise PermissionError('Invalid original process identity')
        current = j.previous.proc_identity(pid)
        if current != identity:
            if current is not None:
                raise PermissionError('Original PID was reused; preserve and inspect')
            stopped.append({'role': role, 'original_process_absent': True})
            continue
        if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
            stopped.append(system_pidfd_stop(record, role, identity))
            continue
        fd = os.pidfd_open(pid)
        try:
            if j.previous.proc_identity(pid) != identity:
                raise PermissionError('Original process changed before signal')
            signal.pidfd_send_signal(fd, signal.SIGTERM)
            if not select.select([fd], [], [], 10)[0]:
                raise PermissionError('Original process did not exit; no force kill or config restoration')
        finally:
            os.close(fd)
        if j.previous.proc_identity(pid) is not None:
            raise PermissionError('Original process PID still present; preserve and inspect')
        stopped.append({'role': role, 'original_process_absent': True})
    j.port_absent()
    return stopped


def system_pidfd_stop(record, role, identity):
    """Only an explicit verified absence proof reaches this non-root helper."""
    if role not in {'web', 'worker'} or os.geteuid() <= 0:
        raise PermissionError('Original non-root process role required')
    canonical(record['run_id'])
    payload = {'run_id': record['run_id'], 'role': role, 'identity': identity, 'uid': os.geteuid()}
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    if len(raw) > 4096:
        raise PermissionError('Exact process input bound exceeded')
    result = subprocess.run(['/usr/bin/python3', '-I', '-B', '-c', PIDFD_STOP_PROBE],
                            input=raw, capture_output=True, timeout=15, check=False, cwd='/',
                            env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
    if result.returncode != 0 or result.stderr or len(result.stdout) > 4096:
        raise PermissionError('Fixed non-root pidfd helper did not verify process exit')
    value = j.qa.unique_json(result.stdout.decode('utf-8'))
    expected = {'run_id': record['run_id'], 'role': role, 'pid': identity['pid'],
                'original_process_absent': True}
    if (type(value) is not dict or set(value) != set(expected) | {'term_sent', 'pidfd_verified'}
            or any(value.get(key) != item for key, item in expected.items())
            or value.get('original_process_absent') is not True
            or type(value.get('term_sent')) is not bool or value.get('pidfd_verified') is not value['term_sent']
            or j.previous.proc_identity(identity['pid']) is not None):
        raise PermissionError('Fixed non-root pidfd proof differs from the original process')
    return {'role': role, 'original_process_absent': True, 'same_uid_system_pidfd_helper': True,
            'term_sent': value['term_sent']}


def restore_owned(record):
    for role in ('web', 'worker'):
        identity = j.old.private_read(j.folder(record['run_id']) / (role + '.json'))['identity']
        if j.previous.proc_identity(identity['pid']) is not None:
            raise PermissionError('A recorded PID is present; config must remain unchanged')
    j.port_absent()
    paths = j.qa.SITES / j.qa.SITE / 'site_config.json', j.qa.SITES / 'common_site_config.json'
    site, common = map(j.old.private_read, paths)
    j.restore_fields(site, common, record['before'])
    j.old.atomic_json(paths[0], site)
    j.old.atomic_json(paths[1], common)
    restored_site, restored_common = map(j.old.private_read, paths)
    if j.config_before(restored_site, restored_common) != record['before']:
        raise PermissionError('Exact owned config restoration readback failed')
    j.old.atomic_json(j.folder(record['run_id']) / 'run.json', {**record, 'state': 'restored'})


def execute(command, run_id, task_id, expected_sha256):
    frappe = environment(expected_sha256)
    with j.previous.lock(j.LOCK):
        record = load(run_id, task_id)
        if command == 'check':
            return {**collect(record, frappe, task_id, fenced=False), 'read_only': True,
                    'finalization_authorized_by_this_check': False}
        if command != 'finalize':
            raise ValueError('Explicit check or finalize required')
        j.close_admission(record)  # Same persistent lock/fence used by live HTTP guards.
        proof = collect(record, frappe, task_id, fenced=True)
        receipt_id = str(uuid.uuid4())
        proof['recovery_source_sha256'] = expected_sha256
        proof['privileged_probe_sha256'] = hashlib.sha256(ROOT_PROBE.encode()).hexdigest()
        proof['same_uid_pidfd_probe_sha256'] = hashlib.sha256(PIDFD_STOP_PROBE.encode()).hexdigest()
        run = j.folder(run_id)
        j.old.exclusive_json(run / ('never-accepted-' + receipt_id + '.json'), proof)
        stopped = stop_processes(record)
        # The worker registration legitimately disappears during stop. Re-prove
        # every invariant, but do not demand byte-equality to the earlier count.
        final_proof = collect(record, frappe, task_id, fenced=True)
        restore_owned(record)
        result = {**final_proof, 'recovery_source_sha256': expected_sha256,
                  'processes': stopped, 'port_absent': True, 'configuration_restored': True,
                  'receipt_id': receipt_id, 'automatic_retry': False}
        j.old.exclusive_json(run / ('never-accepted-finalized-' + receipt_id + '.json'), result)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'finalize'), nargs='?', default='check')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--request-id', required=True)
    parser.add_argument('--source-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        canonical(args.run_id)
        canonical(args.request_id)
        if not re.fullmatch('[0-9a-f]{64}', args.source_sha256):
            raise ValueError('Exact reviewed lowercase helper SHA-256 required')
    except (ValueError, TypeError):
        parser.error('Explicit canonical run/request UUIDs and reviewed source SHA-256 required')
    result = execute(args.command, args.run_id, args.request_id, args.source_sha256)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'failed': type(error).__name__, 'detail':
                          'Preserve this run and all evidence; no retry, seal, forced kill or overwrite'}), flush=True)
        raise SystemExit(1) from None
