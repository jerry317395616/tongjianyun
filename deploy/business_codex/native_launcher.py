"""Administrator-installed, fixed native business launcher (not installed by this file).

Wire format matches business_agent_worker.UnixLauncherRuntime: four-byte network
length then finite JSON, NOT JSONL. A bound control connection is the execution
lease. Its EOF, protocol failure or release revokes the relay, stops the exact
unit, and retains a root-owned task/claim tombstone. There is no reconnect/start,
shell command, environment, mount, credential-key or arbitrary path API.

seal_before_start is a cancellation/reconciliation primitive, not observation of
an exited process. Under the same state lock as bind/start it permanently seals
an entirely unregistered task+claim. A delayed worker can never bind/start it.
Previously bound/attempted tasks cannot receive this evidence. The caller must
already have persisted cancellation; this daemon knows site Unix identity, not
Frappe users or cancellation state. Unknown units alone are never exit proof.

Manual installation prerequisites, deliberately NOT performed here:
* this file and native_sandbox.py installed immutable/root-owned in /opt;
* /etc/tongjianyun-business-codex/launcher.json root-owned 0600, schema below;
* /var/lib/tongjianyun-business-codex/launcher root-owned 0700;
* /run/tongjianyun-business-codex root-owned 0711, tasks root-owned 0700;
* registered site accounts in the dedicated control_gid group (socket 0660).
No production chat is enabled by merely adding this source. --serve requires
the fixed tgy-business-codex-qa-launcher.service cgroup after administrator review;
do not invoke it manually. --check-config is read-only. Config schema:
{"version":1,"control_gid":1234,"sites":{"site.localhost":
 {"sites_path":"/absolute/sites","uid":1000,"gid":1000}},
 "runtime_sha256":{"codex":"64hex","native_sandbox.py":"64hex",
 "sandbox_entry.py":"64hex","business_tool.py":"64hex"}}.

The administrator must stop this service before replacing the shared runtime;
the existing manual installer is not a concurrent deployment protocol. Child
stdio is private memory only, stderr count-only, never logs. No model/task total
deadline: framing and shutdown have bounds; upstream Codex's idle timeout is
separate and is not changed here. This daemon does not open Frappe or a task DB.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import stat
import struct
import subprocess
import threading
import time
import types
import uuid

CONFIG = Path('/etc/tongjianyun-business-codex/launcher.json')
INSTALL = Path('/opt/tongjianyun-business-codex')
RUN = Path('/run/tongjianyun-business-codex')
INPUT = RUN / 'tasks'
CONTROL = RUN / 'control.sock'
STATE = Path('/var/lib/tongjianyun-business-codex/launcher')
PROFILE = 'business-native-v1'
REVISION = 'bwrap-ro-v2'
SERVICE = 'tgy-business-codex-qa-launcher.service'
RUNTIME_FILES = {'codex', 'native_sandbox.py', 'sandbox_entry.py', 'business_tool.py'}
MAX_FRAME = 384 * 1024
MAX_PROMPT = 131072
MAX_CHUNK = 65536
MAX_BUFFER = 1024 * 1024
MAX_OUTPUT = 64 * 1024 * 1024
MAX_STDERR = 16 * 1024 * 1024
MAX_RELAY_BYTES = 256 * 1024 * 1024
ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}
BASE_FIELDS = {'version', 'profile', 'op', 'site'}
TASK_FIELDS = BASE_FIELDS | {'task_id', 'claim_id'}
FIELDS = {'ready': BASE_FIELDS, 'bind': TASK_FIELDS, 'observe': TASK_FIELDS,
          'seal_before_start': TASK_FIELDS,
          'start': TASK_FIELDS | {'prompt', 'token', 'proxy_path'},
          'poll': TASK_FIELDS | {'wait_ms'}, 'stop': TASK_FIELDS, 'release': TASK_FIELDS}


def canonical(value):
    if type(value) is not str or str(uuid.UUID(value)) != value:
        raise ValueError('Canonical UUID required')
    return value


def unit(task_id):
    return 'tgy-business-codex-' + canonical(task_id) + '.service'


def finite_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON field')
            result[key] = value
        return result
    def bad_constant(_):
        raise ValueError('Nonfinite JSON')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)


def encoded(value):
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    if not 1 <= len(raw) <= MAX_FRAME:
        raise ValueError('Frame exceeds bound')
    return struct.pack('!I', len(raw)) + raw


def receive(sock):
    # Idle lease has no deadline. A partial frame must complete in 15 seconds.
    first = sock.recv(4)
    if not first:
        return None
    sock.settimeout(15)
    deadline = time.monotonic() + 15
    try:
        def exact(prefix, count):
            data = bytearray(prefix)
            while len(data) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Incomplete control frame')
                sock.settimeout(remaining)
                more = sock.recv(count - len(data))
                if not more:
                    raise ValueError('Truncated control frame')
                data.extend(more)
            return bytes(data)
        size = struct.unpack('!I', exact(first, 4))[0]
        if not 1 <= size <= MAX_FRAME:
            raise ValueError('Control frame exceeds bound')
        return finite_json(exact(b'', size))
    finally:
        sock.settimeout(None)


def root_path(path, *, directory=False, private=False):
    if not path.is_absolute():
        raise PermissionError('Absolute root-controlled path required')
    for current in (*reversed(path.parents), path):
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError('Path is not root controlled')
        if current != path and not stat.S_ISDIR(info.st_mode):
            raise PermissionError('Invalid path ancestor')
    info = path.lstat()
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise PermissionError('Invalid root path type')
    if private and stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600):
        raise PermissionError('Private root path required')
    return path


@dataclass(frozen=True)
class Site:
    name: str
    sites_path: Path
    uid: int
    gid: int

    def proxy_path(self, task_id):
        return self.sites_path / self.name / 'private/business-codex/tasks' / canonical(task_id) / 'proxy.sock'


def parse_config(value):
    if (type(value) is not dict or set(value) != {'version', 'control_gid', 'sites', 'runtime_sha256'}
            or type(value['version']) is not int or value['version'] != 1
            or type(value['control_gid']) is not int or not 1 <= value['control_gid'] < 61184
            or type(value['sites']) is not dict or not 1 <= len(value['sites']) <= 32
            or type(value['runtime_sha256']) is not dict or set(value['runtime_sha256']) != RUNTIME_FILES):
        raise ValueError('Invalid launcher configuration')
    if any(type(v) is not str or not re.fullmatch('[a-f0-9]{64}', v) for v in value['runtime_sha256'].values()):
        raise ValueError('Reviewed runtime hashes required')
    sites = {}
    for name, entry in value['sites'].items():
        if (type(name) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', name)
                or name in {'.', '..'} or type(entry) is not dict
                or set(entry) != {'sites_path', 'uid', 'gid'}
                or any(type(entry[k]) is not int or not 1 <= entry[k] < 61184 for k in ('uid', 'gid'))
                or type(entry['sites_path']) is not str):
            raise ValueError('Invalid site registration')
        path = Path(entry['sites_path'])
        if not path.is_absolute() or '..' in path.parts or str(path) != entry['sites_path']:
            raise ValueError('Canonical sites path required')
        sites[name] = Site(name, path, entry['uid'], entry['gid'])
    return sites


def load_config():
    root_path(CONFIG, private=True)
    if CONFIG.stat().st_size > 32768:
        raise ValueError('Configuration exceeds bound')
    value = finite_json(CONFIG.read_bytes())
    return value, parse_config(value)


def verify_runtime(configuration):
    root_path(Path(__file__).absolute())
    native_source = None
    for name, expected in configuration['runtime_sha256'].items():
        path = root_path(INSTALL / name)
        with path.open('rb') as stream:
            if name == 'native_sandbox.py':
                native_source = stream.read(1024 * 1024 + 1)
                digest = hashlib.sha256(native_source).hexdigest()
                if len(native_source) > 1024 * 1024:
                    raise PermissionError('Native profile source exceeds bound')
            else:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != expected:
                raise PermissionError('Reviewed runtime hash mismatch')
    for executable in ('/usr/bin/systemd-run', '/usr/bin/systemctl', '/usr/bin/python3', '/usr/bin/bwrap'):
        # Distribution python3 may be an immutable root-owned symlink.
        path = Path(executable)
        info = path.lstat()
        if info.st_uid != 0 or (not stat.S_ISLNK(info.st_mode) and info.st_mode & 0o022):
            raise PermissionError('Untrusted system executable')
        root_path(path.resolve(strict=True))
    # Execute exactly the hash-verified source, never an unreviewed .pyc cache.
    module = types.ModuleType('_tgy_fixed_native_sandbox')
    exec(compile(native_source, str(INSTALL / 'native_sandbox.py'), 'exec'), module.__dict__)
    if module.PROC_ISOLATION_REVISION != REVISION or module.INPUT_ROOT != INPUT:
        raise PermissionError('Native profile mismatch')
    return module


def validate_request(value, sites, peer):
    if (type(value) is not dict or value.get('op') not in FIELDS
            or set(value) != FIELDS[value['op']] or type(value.get('version')) is not int
            or value['version'] != 1 or value.get('profile') != PROFILE):
        raise ValueError('Invalid fixed protocol request')
    site = sites.get(value.get('site'))
    if site is None or peer[1:] != (site.uid, site.gid):
        raise PermissionError('Unregistered Unix peer')
    if value['op'] != 'ready':
        canonical(value['task_id'])
        canonical(value['claim_id'])
    if value['op'] == 'poll' and (type(value['wait_ms']) is not int or not 0 <= value['wait_ms'] <= 1000):
        raise ValueError('Invalid polling bound')
    if value['op'] == 'start':
        if (type(value['prompt']) is not str or not 1 <= len(value['prompt'].encode('utf-8')) <= MAX_PROMPT
                or type(value['token']) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', value['token'])
                or value['proxy_path'] != str(site.proxy_path(value['task_id']))):
            raise ValueError('Invalid fixed task credentials')
    return site


class PinnedProxy:
    """O_NOFOLLOW directory walk; retain fd/inode, no attacker-controlled reopen."""
    def __init__(self, site, task_id):
        self.site = site
        self.lock = threading.Lock()
        self.socket_fd = None
        self.path = site.proxy_path(task_id)
        self.fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            private = False
            for part in self.path.parent.parts[1:]:
                descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd)
                os.close(self.fd)
                self.fd = descriptor
                info = os.fstat(self.fd)
                if info.st_uid not in {0, site.uid} or info.st_mode & 0o022:
                    raise PermissionError('Unsafe site proxy ancestor')
                private = private or part == 'business-codex'
                if private and (info.st_uid != site.uid or stat.S_IMODE(info.st_mode) != 0o700):
                    raise PermissionError('Private site task directory required')
            info = os.stat('proxy.sock', dir_fd=self.fd, follow_symlinks=False)
            if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != site.uid
                    or stat.S_IMODE(info.st_mode) != 0o600):
                raise PermissionError('Private site task socket required')
            self.inode = (info.st_dev, info.st_ino)
            self.socket_fd = os.open('proxy.sock', os.O_PATH | os.O_NOFOLLOW, dir_fd=self.fd)
            pinned = os.fstat(self.socket_fd)
            if (pinned.st_dev, pinned.st_ino) != self.inode or not stat.S_ISSOCK(pinned.st_mode):
                raise PermissionError('Registered socket changed during validation')
        except BaseException:
            if self.socket_fd is not None:
                os.close(self.socket_fd)
            os.close(self.fd)
            raise

    def connect(self):
        with self.lock:
            return self._connect()

    def _connect(self):
        if self.fd is None:
            raise PermissionError('Proxy lease is closed')
        info = os.fstat(self.socket_fd)
        if (info.st_dev, info.st_ino) != self.inode or not stat.S_ISSOCK(info.st_mode):
            raise PermissionError('Registered proxy socket changed')
        result = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            result.settimeout(5)
            result.connect('/proc/self/fd/' + str(self.socket_fd))
            peer = struct.unpack('3i', result.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if peer[1:] != (self.site.uid, self.site.gid):
                raise PermissionError('Proxy peer mismatch')
            result.settimeout(None)
            return result
        except BaseException:
            result.close()
            raise

    def close(self):
        with self.lock:
            if self.fd is not None:
                os.close(self.socket_fd)
                self.socket_fd = None
                os.close(self.fd)
                self.fd = None


class Relay:
    """Bounded byte relay to one pinned Unix socket, no destination protocol."""
    def __init__(self, path, pinned):
        self.path, self.pinned = path, pinned
        self.closed = threading.Event()
        self.lock = threading.Lock()
        self.connections = set()
        self.slots = threading.BoundedSemaphore(8)
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(path))
        path.chmod(0o666)  # Parent root0700; only the exact inode is sandbox-bound.
        self.listener.listen(8)
        self.listener.settimeout(0.25)
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self.closed.is_set():
            try:
                incoming, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self.slots.acquire(blocking=False):
                incoming.close()
                continue
            with self.lock:
                self.connections.add(incoming)
            threading.Thread(target=self._copy, args=(incoming,), daemon=True).start()

    def _copy(self, incoming):
        outgoing = None
        try:
            if self.closed.is_set():
                return
            outgoing = self.pinned.connect()
            with self.lock:
                if self.closed.is_set():
                    return
                self.connections.add(outgoing)
            incoming.setblocking(False)
            outgoing.setblocking(False)
            peers = {incoming: outgoing, outgoing: incoming}
            buffers = {incoming: bytearray(), outgoing: bytearray()}
            reading = set(peers)
            total = 0
            while not self.closed.is_set() and (reading or any(buffers.values())):
                can_read = [s for s in reading if len(buffers[peers[s]]) < MAX_CHUNK]
                can_write = [s for s in peers if buffers[s]]
                ready, writable, _ = select.select(can_read, can_write, [], 0.25)
                for source in ready:
                    data = source.recv(min(16384, MAX_CHUNK - len(buffers[peers[source]])))
                    if not data:
                        reading.remove(source)
                        if not buffers[peers[source]]:
                            peers[source].shutdown(socket.SHUT_WR)
                    else:
                        total += len(data)
                        if total > MAX_RELAY_BYTES:
                            raise ValueError('Relay bytes exceed bound')
                        buffers[peers[source]].extend(data)
                for target in writable:
                    sent = target.send(buffers[target])
                    del buffers[target][:sent]
                    if not buffers[target] and peers[target] not in reading:
                        target.shutdown(socket.SHUT_WR)
        except Exception:
            pass  # Never log HTTP content, headers, tokens, paths or exceptions.
        finally:
            for item in (incoming, outgoing):
                if item is not None:
                    with self.lock:
                        self.connections.discard(item)
                    item.close()
            self.slots.release()

    def close(self):
        self.closed.set()
        self.listener.close()
        with self.lock:
            for item in tuple(self.connections):
                try:
                    item.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                item.close()
        self.pinned.close()


def write_private(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


class Tombstones:
    """Root-private permanent reservations; no token, prompt or model text."""
    def __init__(self, directory=STATE):
        self.directory = directory

    def path(self, task):
        return self.directory / (canonical(task) + '.json')

    def load(self, task):
        path = self.path(task)
        root_path(path, private=True)
        if path.stat().st_size > 4096:
            raise ValueError('Invalid tombstone')
        value = finite_json(path.read_bytes())
        if (type(value) is not dict or set(value) != {'version', 'site', 'task_id', 'claim_id', 'stage', 'proof'}
                or value['version'] != 1 or value['task_id'] != task
                or value['stage'] not in {'bound', 'starting', 'started', 'closed', 'unresolved',
                                          'never_started_and_sealed'}):
            raise ValueError('Invalid tombstone schema')
        canonical(value['claim_id'])
        if (value['stage'] == 'never_started_and_sealed'
                and value['proof'] != sealed_proof(task, value['claim_id'])):
            raise ValueError('Invalid never-started evidence')
        if value['stage'] == 'never_started_and_sealed':
            # A prior acknowledgement may have been lost, or fsync may have
            # raised after creating the inode. Never acknowledge an existing
            # seal without reestablishing file + directory durability.
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
            self._sync()
        return value

    def reserve(self, site, task, claim, *, sealed=False):
        record = {'version': 1, 'site': site, 'task_id': task, 'claim_id': claim,
                  'stage': 'never_started_and_sealed' if sealed else 'bound',
                  'proof': sealed_proof(task, claim) if sealed else None}
        write_private(self.path(task), encoded(record)[4:])
        self._sync()
        return record

    def update(self, record):
        target = self.path(record['task_id'])
        temp = self.directory / ('.state-' + str(uuid.uuid4()))
        write_private(temp, encoded(record)[4:])
        os.replace(temp, target)
        self._sync()

    def _sync(self):
        descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def system_unit(task_id, *, timeout=5):
    """Bounded trusted systemctl query plus cgroup-v2 populated evidence."""
    name = unit(task_id)
    result = subprocess.run(['/usr/bin/systemctl', 'show', name, '--no-pager',
                             '--property=LoadState,ActiveState,ControlGroup,MainPID'],
                            env=ENV, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=False)
    if len(result.stdout) > 8192 or result.returncode not in (0, 1, 4):
        raise RuntimeError('Unit evidence unavailable')
    values = {}
    for line in result.stdout.decode('ascii', 'strict').splitlines():
        key, separator, value = line.partition('=')
        if not separator or key in values:
            raise RuntimeError('Invalid unit evidence')
        values[key] = value
    if set(values) != {'LoadState', 'ActiveState', 'ControlGroup', 'MainPID'}:
        raise RuntimeError('Incomplete unit evidence')
    expected = '/system.slice/' + name
    if values['ControlGroup'] not in {'', expected} or not values['MainPID'].isdigit():
        raise RuntimeError('Unexpected native unit cgroup')
    cgroup = Path('/sys/fs/cgroup' + expected)
    if cgroup.exists():
        events = dict(line.split() for line in (cgroup / 'cgroup.events').read_text('ascii').splitlines())
        empty = events.get('populated') == '0'
    else:
        empty = True
    inactive = (values['LoadState'] == 'not-found' or values['ActiveState'] in {'inactive', 'failed'})
    return {'inactive': inactive, 'empty': empty and values['MainPID'] == '0',
            'missing': values['LoadState'] == 'not-found'}


def fixed_stop(task_id, *, timeout=20):
    # No terminate(Popen) shortcut: kill the service cgroup, including descendants.
    subprocess.run(['/usr/bin/systemctl', 'stop', unit(task_id)], env=ENV,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=timeout, check=False)


def launch_command(native, task_id):
    """Only QA-daemon tasks depend on this service; shared runtime stays intact."""
    command = native.build_systemd_command(task_id)
    executable = ['/usr/bin/python3', '-I', (INSTALL / 'native_sandbox.py').as_posix(), '--task-id', task_id]
    if (command[:1] != ['/usr/bin/systemd-run'] or command[-5:] != executable
            or '--' in command or command.count('/usr/bin/python3') != 1):
        raise PermissionError('Unexpected fixed native launch command')
    # The reviewed builder has no -- separator; insert our fixed dependencies
    # and an explicit separator before the native executable, never after it.
    return command[:-5] + ['--property=BindsTo=' + SERVICE, '--property=After=' + SERVICE,
                          '--', *executable]


class Task:
    def __init__(self, site, record, ledger, native, *, state_lock=None):
        self.site, self.record, self.ledger, self.native = site, record, ledger, native
        self.task_id, self.claim_id = record['task_id'], record['claim_id']
        self.directory = INPUT / self.task_id
        self.process = self.relay = None
        self.lock = threading.RLock()
        self.state_lock = state_lock or threading.RLock()
        self.stopping = threading.Lock()
        self.closing = threading.Lock()
        self.changed = threading.Event()
        self.finished = threading.Event()
        self.stdout = bytearray()
        self.stderr_pending = self.stderr_total = self.stdout_total = 0
        self.stdout_eof = self.stderr_eof = False
        self.failed = False
        self.exit_code = None
        self.terminal_proof = None
        self.lease_closed = False
        self.allow_start = True

    def start(self, request):
        admitted = False
        try:
            with self.state_lock:
                if not self.allow_start or self.record['stage'] != 'bound':
                    raise PermissionError('Task launch cannot be replayed')
                admitted = True
                return self._start(request)
        except BaseException:
            # Do not await the stopping lock while holding the shared state
            # lock: a monitor may already be stopping this same task.
            if admitted:
                self.failed = True
                self.stop()
            raise

    def _start(self, request):
        if not self.allow_start or self.record['stage'] != 'bound':
            raise PermissionError('Task launch cannot be replayed')
        # Reserve before any process/input creation; failures remain tombstoned.
        self.record['stage'] = 'starting'
        self.ledger.update(self.record)
        pinned = None
        try:
            self.directory.mkdir(mode=0o700)
            pinned = PinnedProxy(self.site, self.task_id)
            write_private(self.directory / 'token', request['token'].encode('ascii'))
            write_private(self.directory / 'prompt.txt', request['prompt'].encode('utf-8'))
            self.relay = Relay(self.directory / 'proxy.sock', pinned)
            pinned = None
            self.process = subprocess.Popen(launch_command(self.native, self.task_id),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=ENV, close_fds=True, start_new_session=True, bufsize=0)
            for pipe, is_stdout in ((self.process.stdout, True), (self.process.stderr, False)):
                threading.Thread(target=self._drain, args=(pipe, is_stdout), daemon=True).start()
            threading.Thread(target=self._monitor, daemon=True).start()
            self.record['stage'] = 'started'
            self.ledger.update(self.record)
        except BaseException:
            if pinned is not None:
                pinned.close()
            raise

    def _drain(self, pipe, stdout):
        try:
            while True:
                data = pipe.read(16384)
                if not data:
                    break
                with self.lock:
                    if stdout:
                        self.stdout_total += len(data)
                        if self.stdout_total > MAX_OUTPUT or len(self.stdout) + len(data) > MAX_BUFFER:
                            self.failed = True
                        elif not self.failed:
                            self.stdout.extend(data)
                    else:
                        self.stderr_total += len(data)
                        self.stderr_pending += len(data)
                        if self.stderr_total > MAX_STDERR:
                            self.failed = True
                    self.changed.set()
        except OSError:
            self.failed = True
        finally:
            pipe.close()
            with self.lock:
                if stdout:
                    self.stdout_eof = True
                else:
                    self.stderr_eof = True
                self.changed.set()

    def _monitor(self):
        while not self.finished.wait(0.2):
            if self.failed:
                self.stop()
                return
            if self.process.poll() is not None:
                # Query actual service/cgroup, not merely the systemd-run client.
                if self.proof()['state'] == 'exited':
                    return

    def proof(self, *, timeout=5):
        with self.lock:
            if self.terminal_proof is not None:
                result = dict(self.terminal_proof)
                result['stdout_eof'] = not self.stdout
                result['lease_closed'] = self.lease_closed
                return result
            process_exit = self.process.poll() if self.process is not None else self.exit_code
            pipes_closed = self.stdout_eof and self.stderr_eof
        state = 'unknown'
        empty = False
        try:
            actual = system_unit(self.task_id, timeout=timeout)
            empty = actual['empty']
            if self.process is not None and process_exit is None:
                state = 'running'
            elif actual['inactive'] and empty and pipes_closed and process_exit is not None:
                state = 'exited'
            elif not actual['inactive']:
                state = 'running'
        except Exception:
            pass
        result = {'ok': True, 'unit': unit(self.task_id), 'claim_id': self.claim_id,
                  'state': state, 'exit_code': process_exit, 'cgroup_empty': empty,
                  'stdout_eof': pipes_closed and not self.stdout,
                  'lease_closed': self.lease_closed and state == 'exited'}
        # Preserve unread buffered output: poll reports EOF only after delivering
        # the last chunk; raw proof may still establish actual process drainage.
        if state == 'exited':
            with self.lock:
                self.terminal_proof = result
                self.record['proof'] = result
                self.ledger.update(self.record)
                self.finished.set()
        return dict(result)

    def poll(self, wait_ms):
        self.changed.wait(wait_ms / 1000)
        with self.lock:
            data = bytes(self.stdout[:MAX_CHUNK])
            del self.stdout[:MAX_CHUNK]
            stderr = min(self.stderr_pending, MAX_STDERR)
            self.stderr_pending -= stderr
            pending = bool(self.stdout)
            if not pending:
                self.changed.clear()
        proof = self.proof()
        if pending:
            proof['stdout_eof'] = False
            if proof['state'] == 'exited':
                proof['state'] = 'running'
        return {'ok': True, 'stdout': base64.b64encode(data).decode('ascii'),
                'stderr_bytes': stderr, 'execution': proof}

    def stop(self):
        deadline = time.monotonic() + 24
        if not self.stopping.acquire(timeout=24):
            return unknown_proof(self.task_id, self.claim_id)
        try:
            with self.state_lock:
                if self.record['stage'] == 'never_started_and_sealed':
                    return dict(self.record['proof'])
                if self.record['stage'] == 'bound' and self.process is None and self.relay is None:
                    actual = system_unit(self.task_id, timeout=max(0.1, min(5, deadline - time.monotonic())))
                    work = Path('/run') / ('tgy-business-' + self.task_id)
                    if (actual != {'inactive': True, 'empty': True, 'missing': True}
                            or os.path.lexists(self.directory) or os.path.lexists(work)):
                        return unknown_proof(self.task_id, self.claim_id)
                    # Unlike an external seal request, this is the existing
                    # control lease's stop. Permanently revoke its start right
                    # before acknowledging no execution ever occurred.
                    proof = sealed_proof(self.task_id, self.claim_id)
                    record = dict(self.record, stage='never_started_and_sealed', proof=proof)
                    self.ledger.update(record)
                    self.record = record
                    self.terminal_proof = proof
                    self.lease_closed = True
                    self.stdout_eof = self.stderr_eof = True
                    self.finished.set()
                    return dict(proof)
            if self.relay is not None:
                self.relay.close()  # Revoke capability before systemd stop.
                self.relay = None
            try:
                fixed_stop(self.task_id, timeout=max(0.1, min(18, deadline - time.monotonic())))
            except Exception:
                pass
            if self.process is None:
                # A missing Popen handle after starting was persisted does not
                # prove the child never existed. Stop its unit, but never invent
                # an exit code or completed pipe observation.
                return self.proof(timeout=max(0.1, min(5, deadline - time.monotonic())))
            with self.lock:
                self.stdout.clear()  # Cancellation may discard raw pending JSONL.
            result = unknown_proof(self.task_id, self.claim_id)
            while time.monotonic() < deadline:
                result = self.proof(timeout=max(0.1, min(5, deadline - time.monotonic())))
                if result['state'] == 'exited':
                    return result
                time.sleep(0.05)
            return result  # Never add another blocking query beyond deadline.
        finally:
            self.stopping.release()

    def close(self):
        with self.closing:
            return self._close()

    def _close(self):
        proof = self.stop()
        if proof['state'] not in {'exited', 'never_started_and_sealed'}:
            self.record['stage'] = 'unresolved'
            self.ledger.update(self.record)
            return False
        # Delete only our exact private credentials/socket. Never recurse.
        if self.directory.exists():
            root_path(self.directory, directory=True, private=True)
            for name in ('token', 'prompt.txt', 'proxy.sock'):
                path = self.directory / name
                if path.exists():
                    path.unlink()
            self.directory.rmdir()
        work = Path('/run') / ('tgy-business-' + self.task_id)
        if work.exists() or not system_unit(self.task_id)['missing']:
            return False
        self.lease_closed = True
        self.record['proof'] = self.proof()
        if proof['state'] != 'never_started_and_sealed':
            self.record['stage'] = 'closed'
        self.ledger.update(self.record)
        return True


class Launcher:
    def __init__(self, sites, native, ledger=None):
        self.sites, self.native, self.ledger = sites, native, ledger or Tombstones()
        self.lock = threading.RLock()
        self.shutting_down = False
        self.tasks = {}
        self.leases = {}

    def request(self, request, peer, lease):
        site = validate_request(request, self.sites, peer)
        operation = request['op']
        if operation == 'ready':
            return {'ok': True, 'version': 1, 'profile': PROFILE, 'native_revision': REVISION,
                    'ready': not self.shutting_down}
        task_id, claim = request['task_id'], request['claim_id']
        if operation == 'bind':
            with self.lock:
                if self.shutting_down or lease in self.leases or len(self.leases) >= 16:
                    raise PermissionError('Lease already bound or capacity reached')
                if not system_unit(task_id)['missing'] or (INPUT / task_id).exists():
                    raise PermissionError('Task unit/input already exists')
                record = self.ledger.reserve(site.name, task_id, claim)
                task = Task(site, record, self.ledger, self.native, state_lock=self.lock)
                self.tasks[task_id] = task
                self.leases[lease] = task_id
            return {'ok': True, 'unit': unit(task_id), 'bound': True}
        if operation == 'seal_before_start':
            return self.seal(site, task_id, claim)
        task = self.tasks.get(task_id)
        if operation == 'observe':
            if task is None:
                record = self.ledger.load(task_id)
                if record['site'] != site.name or record['claim_id'] != claim:
                    raise PermissionError('Task scope mismatch')
                return record['proof'] or unknown_proof(task_id, claim)
        if (task is None or task.site != site or task.claim_id != claim
                or (operation != 'observe' and self.leases.get(lease) != task_id)):
            raise PermissionError('Task lease mismatch')
        if operation == 'observe':
            return task.proof()
        if operation == 'start':
            with self.lock:
                # Start admission, bind and seal are serialized. A permanently
                # sealed UUID has no live Task, and can never reach this call.
                if (self.shutting_down or self.tasks.get(task_id) is not task
                        or self.leases.get(lease) != task_id):
                    raise PermissionError('Task no longer owns a launch lease')
            # Task.start holds this same state lock throughout admission; its
            # failure cleanup releases it before stopping the process group.
            task.start(request)
            return {'ok': True, 'unit': unit(task_id), 'started': True}
        if operation == 'poll':
            return task.poll(request['wait_ms'])
        if operation == 'stop':
            return task.stop()
        if operation == 'release':
            cleaned = task.close()
            if cleaned:
                with self.lock:
                    self.leases.pop(lease, None)
                    self.tasks.pop(task_id, None)
            return {'ok': True, 'unit': unit(task_id), 'cleaned': cleaned}
        raise ValueError('Unknown operation')

    def seal(self, site, task_id, claim):
        with self.lock:
            task = self.tasks.get(task_id)
            if task is not None:
                if task.site != site or task.claim_id != claim:
                    raise PermissionError('Task scope mismatch')
                return task.proof()  # Even an idle bound lease must not be sealed.
            try:
                record = self.ledger.load(task_id)
            except FileNotFoundError:
                record = None
            if record is not None:
                if record['site'] != site.name or record['claim_id'] != claim:
                    raise PermissionError('Task scope mismatch')
                # Immutable seal is idempotent; all prior launch/bind attempts
                # keep their original evidence, including unknown outcomes.
                return record['proof'] or unknown_proof(task_id, claim)
            if task_id in self.leases.values():
                raise PermissionError('Task still owns a live lease')
            actual = system_unit(task_id)
            work = Path('/run') / ('tgy-business-' + task_id)
            if (actual != {'inactive': True, 'empty': True, 'missing': True}
                    or os.path.lexists(INPUT / task_id) or os.path.lexists(work)):
                raise PermissionError('Never-started state is not provable')
            # Atomic exclusive creation + file/directory fsync occurs while
            # holding the same lock as bind and start. Missing unit is only a
            # prerequisite; this permanent reservation is the actual evidence.
            record = self.ledger.reserve(site.name, task_id, claim, sealed=True)
            return record['proof']

    def disconnect(self, lease):
        with self.lock:
            task_id = self.leases.pop(lease, None)
        if task_id is not None:
            try:
                if self.tasks[task_id].close():
                    with self.lock:
                        self.tasks.pop(task_id, None)
            except Exception:
                pass  # Retain tombstone/credentials if drainage is unverified.

    def shutdown(self, *, timeout=40):
        """Parallel stop with one deadline; PID1 BindsTo covers hard daemon death."""
        deadline = time.monotonic() + timeout
        self.shutting_down = True
        if not self.lock.acquire(timeout=max(0, deadline - time.monotonic())):
            return False
        try:
            tasks = tuple(self.tasks.values())
            for task in tasks:
                task.allow_start = False
        finally:
            self.lock.release()
        results = {}
        def close(task):
            try:
                results[task.task_id] = task.close()
            except Exception:
                results[task.task_id] = False
        threads = [threading.Thread(target=close, args=(task,), daemon=True) for task in tasks]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))
        return (len(results) == len(tasks) and all(results.values())
                and not any(thread.is_alive() for thread in threads))


def unknown_proof(task_id, claim):
    return {'ok': True, 'unit': unit(task_id), 'claim_id': claim, 'state': 'unknown',
            'exit_code': None, 'cgroup_empty': False, 'stdout_eof': False, 'lease_closed': False}


def sealed_proof(task_id, claim):
    return {'ok': True, 'unit': unit(task_id), 'claim_id': canonical(claim),
            'state': 'never_started_and_sealed', 'exit_code': None,
            'cgroup_empty': True, 'stdout_eof': True, 'lease_closed': True}


def recover(ledger):
    """Daemon restart never resumes execution or synthesizes a successful exit."""
    for path in ledger.directory.iterdir():
        if path.name.startswith('.') or path.name == 'daemon.lock':
            continue  # Interrupted atomic update retained, never executed.
        if path.suffix != '.json':
            raise ValueError('Unexpected launcher state file')
        record = ledger.load(canonical(path.stem))
        if record['stage'] not in {'closed', 'never_started_and_sealed'}:
            fixed_stop(record['task_id'])
            record['stage'] = 'unresolved'
            record['proof'] = unknown_proof(record['task_id'], record['claim_id'])
            ledger.update(record)


def serve_connection(connection, launcher):
    lease = object()
    try:
        peer = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if not any(peer[1:] == (site.uid, site.gid) for site in launcher.sites.values()):
            raise PermissionError('Unregistered Unix peer')
        while True:
            request = receive(connection)
            if request is None:
                break
            reply = launcher.request(request, peer, lease)
            connection.settimeout(15)
            connection.sendall(encoded(reply))
            connection.settimeout(None)
    except Exception:
        try:
            connection.settimeout(1)
            connection.sendall(encoded({'ok': False, 'error': 'operation_refused'}))
        except OSError:
            pass
    finally:
        connection.close()
        launcher.disconnect(lease)


def main(serve=False):
    if os.name != 'posix' or os.geteuid() != 0 or not hasattr(socket, 'SO_PEERCRED'):
        raise PermissionError('Linux root system service required')
    os.umask(0o077)
    config, sites = load_config()
    native = verify_runtime(config)
    root_path(RUN, directory=True)
    root_path(INPUT, directory=True, private=True)
    root_path(STATE, directory=True, private=True)
    if stat.S_IMODE(RUN.stat().st_mode) != 0o711:
        raise PermissionError('Explicit administrator control-directory setup required')
    if not serve:
        return {'configuration_valid': True, 'daemon_started': False, 'production_chat_enabled': False}
    if ('0::/system.slice/' + SERVICE) not in Path('/proc/self/cgroup').read_text('ascii').splitlines():
        raise PermissionError('Launcher must run within the fixed QA system service')
    import fcntl
    # Prevent another daemon unlinking a live endpoint or racing a reservation.
    lock_fd = os.open(STATE / 'daemon.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    ledger = Tombstones()
    recover(ledger)
    if CONTROL.exists():
        info = CONTROL.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != 0:
            raise PermissionError('Unsafe stale control socket')
        CONTROL.unlink()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(CONTROL))
    os.chown(CONTROL, 0, config['control_gid'])
    CONTROL.chmod(0o660)
    listener.listen(32)
    listener.settimeout(0.5)
    launcher = Launcher(sites, native, ledger)
    stopping = threading.Event()
    sockets = set()
    sockets_lock = threading.Lock()
    capacity = threading.BoundedSemaphore(32)
    def stop_signal(*_):
        stopping.set()
    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    def handle(connection):
        try:
            serve_connection(connection, launcher)
        finally:
            with sockets_lock:
                sockets.discard(connection)
            capacity.release()
    try:
        while not stopping.is_set():
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            if not capacity.acquire(blocking=False):
                connection.close()
                continue
            with sockets_lock:
                sockets.add(connection)
            threading.Thread(target=handle, args=(connection,), daemon=True).start()
    finally:
        listener.close()
        with sockets_lock:
            for connection in tuple(sockets):
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        cleaned = launcher.shutdown(timeout=40)
        CONTROL.unlink(missing_ok=True)
        os.close(lock_fd)
    return {'daemon_stopped': True, 'cleanup_verified': cleaned}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--serve', action='store_true')
    mode.add_argument('--check-config', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(main(serve=args.serve)))
    except Exception:
        print('{"ok":false,"error":"launcher_not_ready"}')
        raise SystemExit(1) from None
