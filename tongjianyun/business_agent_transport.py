"""Trusted, task-local transport outside the business Codex sandbox.

No web whitelist, generic HTTP proxy, model key delivery or framework bypass.
The caller supplies an authenticated immutable task binding and fresh authority
checks; only a per-task Unix socket and disposable bearer enter the sandbox.
Database connections/transactions are owned by the caller, never HTTP threads.
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import re
import socketserver
import sqlite3
import ssl
import stat
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler


MAX_REQUEST = 2 * 1024 * 1024
MAX_RESULT = 512 * 1024
CALL_ID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
DIGEST = re.compile(r'[a-f0-9]{64}\Z')
MODEL = 'deepseek-v4-pro'
MODEL_HOST = 'api.deepseek.com'


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result

    def invalid(_):
        raise ValueError('Non-finite JSON')

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('Invalid JSON') from exc


def private_directory(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError('Expected a real absolute private directory')
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Symlink directory is not permitted')
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or (os.name == 'posix' and (
            info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077)):
        raise ValueError('Broker directory must be private to its trusted owner')
    return path


def _private_directory_fd(path):
    """Pin a validated Linux directory without following any path component."""
    expected = path.stat(follow_symlinks=False)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open('/', flags)
    try:
        for component in path.parts[1:]:
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        info = os.fstat(descriptor)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077
                or (info.st_dev, info.st_ino) != (expected.st_dev, expected.st_ino)):
            raise ValueError('Broker directory changed or is not private')
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


class DurableWriteLedger:
    """Intent-before-write; an uncertain intent can never execute again.

The SQLite ledger is NOT an atomic distributed transaction with Frappe. If a
process stops between Frappe commit and receipt persistence, the durable intent
stays uncertain. Repeated IDs and new IDs with the same operation digest return
the saved receipt or uncertainty, not another operation. Fresh business
revisions distinguish later legitimate edits. The ledger remains outside all
sandbox mounts, including after task completion.
"""
    def __init__(self, directory, identity, *, validate, commit, rollback, outcome):
        self.directory = private_directory(directory)
        self.path = self.directory / 'writes.sqlite3'
        if self.path.exists() and (self.path.is_symlink() or not self.path.is_file()):
            raise ValueError('Invalid write ledger')
        if set(identity) != {'site', 'owner', 'task_id', 'mode'} or identity['mode'] != 'business':
            raise ValueError('Invalid ledger identity')
        if any(not isinstance(v, str) or not v for v in identity.values()):
            raise ValueError('Invalid ledger identity')
        self.identity = dict(identity)
        self.validate, self.commit, self.rollback, self.outcome = validate, commit, rollback, outcome
        self.lock = threading.Lock()
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        info = os.fstat(descriptor)
        os.close(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (os.name == 'posix' and (
                info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077)):
            raise ValueError('Ledger must be a private single-link file')
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS identity (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)')
            encoded = json.dumps(identity, sort_keys=True)
            found = db.execute('SELECT value FROM identity WHERE id=1').fetchone()
            if found and found[0] != encoded:
                raise ValueError('Ledger belongs to another task')
            db.execute('INSERT OR IGNORE INTO identity VALUES (1, ?)', (encoded,))
            db.execute('CREATE TABLE IF NOT EXISTS writes (call_id TEXT PRIMARY KEY, digest TEXT NOT NULL UNIQUE, '
                       'state TEXT NOT NULL, result TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS call_alias (call_id TEXT PRIMARY KEY, digest TEXT NOT NULL)')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('PRAGMA journal_mode=DELETE')
            with db:
                yield db
        finally:
            db.close()

    def __call__(self, binding, call_id, digest, operation):
        if (not isinstance(call_id, str) or not CALL_ID.fullmatch(call_id)
                or not isinstance(digest, str) or not DIGEST.fullmatch(digest)):
            raise ValueError('Invalid write identity')
        if any(getattr(binding, key, None) != self.identity[key] for key in ('site', 'owner', 'task_id')):
            raise PermissionError('Write binding does not match ledger')
        with self.lock:
            self.validate(binding)
            with self._connect() as db:
                db.execute('BEGIN IMMEDIATE')
                alias = db.execute('SELECT digest FROM call_alias WHERE call_id=?', (call_id,)).fetchone()
                if alias and alias[0] != digest:
                    raise ValueError('A call ID cannot be reused for another operation')
                row = db.execute('SELECT digest, state, result FROM writes WHERE call_id=?', (call_id,)).fetchone()
                if row and row[0] != digest:
                    raise ValueError('A call ID cannot be reused for another operation')
                db.execute('INSERT OR IGNORE INTO call_alias VALUES (?, ?)', (call_id, digest))
                row = row or db.execute('SELECT digest, state, result FROM writes WHERE digest=?', (digest,)).fetchone()
                if row:
                    self.validate(binding)
                    return self.outcome('committed' if row[1] == 'committed' else 'uncertain',
                                        strict_json(row[2]) if row[1] == 'committed' else None, replayed=True)
                db.execute('INSERT INTO writes VALUES (?, ?, ?, NULL)', (call_id, digest, 'intent'))
            commit_started = False
            try:
                self.validate(binding)
                result = operation()
                encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
                if len(encoded.encode()) > MAX_RESULT:
                    raise ValueError('Write readback exceeds result limit')
                self.validate(binding)
                commit_started = True
                self.commit()
            except BaseException as exc:
                # Even a known validation failure is never automatically replayed.
                # An interrupted commit may already have reached the database.
                rollback_failed = False
                try:
                    self.rollback()
                except Exception:
                    rollback_failed = True
                finally:
                    with self._connect() as db:
                        db.execute('UPDATE writes SET state=? WHERE call_id=?', ('uncertain', call_id))
                if isinstance(exc, Exception) and (commit_started or rollback_failed):
                    return self.outcome('uncertain')
                raise
            try:
                with self._connect() as db:
                    db.execute('UPDATE writes SET state=?, result=? WHERE call_id=?', ('committed', encoded, call_id))
            except Exception:
                return self.outcome('uncertain')
            return self.outcome('committed', result)


def model_payload(value):
    """One fixed model endpoint; no hosted network/MCP/code tools or files."""
    if type(value) is not dict or value.get('model') != MODEL or value.get('stream') is not True:
        raise ValueError('Unsupported model request')
    if value.get('background') or any(value.get(key) is not None for key in (
            'previous_response_id', 'conversation', 'prompt')):
        raise ValueError('Cross-request hosted state is not permitted')
    tools = value.get('tools', [])
    if not isinstance(tools, list) or len(tools) > 100:
        raise ValueError('Invalid model tools')
    if any(type(tool) is not dict or tool.get('type') not in {'function', 'custom'} for tool in tools):
        raise ValueError('Only locally executed model tools are allowed')
    # Remote image/file URLs and hosted file IDs must not create a second egress
    # surface. Attachments require a separate, audited scoped-file pipeline.
    def inspect(node, depth=0):
        if depth > 40:
            raise ValueError('Model input too deeply nested')
        if isinstance(node, dict):
            if node.get('type') == 'item_reference':
                raise ValueError('Hosted item references are not permitted')
            if node.get('type') in {'input_image', 'input_file', 'computer_screenshot'}:
                raise ValueError('This runner has no attachment capability yet')
            for item in node.values():
                inspect(item, depth + 1)
        elif isinstance(node, list):
            for item in node:
                inspect(item, depth + 1)
    inspect(value)
    value = dict(value)
    value['store'] = False
    if 'max_output_tokens' in value and (type(value['max_output_tokens']) is not int
                                        or not 1 <= value['max_output_tokens'] <= 32768):
        raise ValueError('Invalid output limit')
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()


# Importable on Windows for ledger/schema tests; there is no TCP fallback.
class _Server(socketserver.ThreadingMixIn, getattr(socketserver, 'UnixStreamServer', socketserver.BaseServer)):
    daemon_threads = True
    block_on_close = False
    request_queue_size = 8

    def handle_error(self, request, client_address):
        # Network parser failures must not dump request data or framework traces.
        pass

    def process_request(self, request, address):
        if not self.owner.slots.acquire(blocking=False):
            request.close()
            return
        super().process_request(request, address)

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.owner.slots.release()


class TaskProxy:
    """Per-task Unix HTTP listener with exact routes and no secret logging.

authorize() must freshly inspect task/account authority. tool_handler must
create/destroy its own Frappe context in the calling thread. Socket access is
not authentication: every request needs this task's random bearer as well.
"""
    def __init__(self, directory, token, *, authorize, tool_handler, model_key=None,
                 max_model_calls=128, connection_factory=None, credential_mount=False):
        if not hasattr(socketserver, 'UnixStreamServer'):
            raise OSError('Unix transport is required; TCP fallback is not supported')
        self.directory = private_directory(directory)
        if type(credential_mount) is not bool or (credential_mount and os.geteuid() != 0):
            raise PermissionError('Credential-mount mode requires the trusted system broker')
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', token):
            raise ValueError('Expected a high-entropy task bearer')
        if type(max_model_calls) is not int or not 1 <= max_model_calls <= 1024:
            raise ValueError('Invalid model call limit')
        self.token, self.authorize, self.tool_handler, self.model_key = token, authorize, tool_handler, model_key
        self.max_model_calls, self.model_calls = max_model_calls, 0
        self.connection_factory = connection_factory or self._upstream
        self.path = self.directory / 'proxy.sock'
        self.slots = threading.BoundedSemaphore(8)
        self.lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._tools_condition = threading.Condition()
        self._active_tools = 0
        self.connections = set()
        self.stream_sockets = set()
        self.closed = threading.Event()
        self.thread = None
        self.server = None
        self._directory_fd = self._socket_fd = None
        self._socket_identity = None
        self._disposed = False
        try:
            self._directory_identity = self.directory.stat(follow_symlinks=False)
            if sys.platform == 'linux':
                self._directory_fd = _private_directory_fd(self.directory)
                # sun_path is at most 108 bytes on Linux. The canonical path
                # remains public for launcher validation; only bind uses this
                # short, inode-pinned spelling. Never change process cwd.
                bind_path = f'/proc/self/fd/{self._directory_fd}/proxy.sock'
            else:
                bind_path = str(self.path)
            try:
                self._socket_stat()
            except FileNotFoundError:
                pass
            else:
                raise ValueError('Socket path already exists; never replace a live task')
            self.server = _Server(bind_path, _Handler, bind_and_activate=False)
            self.server.owner = self
            self.server.server_bind()
            if self._directory_fd is not None:
                self._socket_fd = os.open('proxy.sock', os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC,
                                          dir_fd=self._directory_fd)
                info = os.fstat(self._socket_fd)
            else:
                info = self._socket_stat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
                raise ValueError('Invalid bound socket inode')
            self._socket_identity = (info.st_dev, info.st_ino)
            # The private directory is not exposed to the DynamicUser. Only
            # credential-mount mode exposes the pinned socket with mode 0666;
            # every request still requires its disposable task bearer.
            chmod_path = (f'/proc/self/fd/{self._socket_fd}' if self._socket_fd is not None
                          else self.path)
            os.chmod(chmod_path, 0o666 if credential_mount else 0o600)
            self.server.server_activate()
        except BaseException:
            if self.server is not None:
                self.server.server_close()
            self._dispose_socket()
            raise

    def _socket_stat(self):
        if self._directory_fd is not None:
            return os.stat('proxy.sock', dir_fd=self._directory_fd, follow_symlinks=False)
        return self.path.stat(follow_symlinks=False)

    def _dispose_socket(self):
        try:
            if self._socket_identity is not None:
                try:
                    info = self._socket_stat()
                    same_directory = self._directory_fd is not None
                    if not same_directory:
                        parent = self.directory.stat(follow_symlinks=False)
                        same_directory = ((parent.st_dev, parent.st_ino) ==
                                          (self._directory_identity.st_dev, self._directory_identity.st_ino))
                    if (same_directory and stat.S_ISSOCK(info.st_mode)
                            and (info.st_dev, info.st_ino) == self._socket_identity):
                        if self._directory_fd is not None:
                            os.unlink('proxy.sock', dir_fd=self._directory_fd)
                        else:
                            self.path.unlink()
                except FileNotFoundError:
                    pass
        finally:
            # Keep O_PATH open until after the identity comparison: an unlinked
            # socket inode cannot be recycled into a replacement during cleanup.
            for name in ('_socket_fd', '_directory_fd'):
                descriptor = getattr(self, name)
                if descriptor is not None:
                    os.close(descriptor)
                    setattr(self, name, None)
            self._socket_identity = None

    @staticmethod
    def _upstream():
        # No environment proxy, destination arguments or redirect handling.
        return http.client.HTTPSConnection(MODEL_HOST, 443, timeout=15, context=ssl.create_default_context())

    def permitted(self):
        if self.closed.is_set():
            return False
        try:
            return self.authorize() is True
        except Exception:
            return False

    def start(self):
        if self.thread is not None or self.closed.is_set():
            raise RuntimeError('Task proxy already started')
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
        self.thread.start()
        return self

    def dispatch_tool(self, tool, arguments, call_id):
        # Admission and callback counting share the close lock. Closing sockets
        # does not stop a host DB transaction; the queue worker must drain these
        # callbacks before its process exits. The durable ledger remains the
        # authority after a worker crash, not this in-memory counter.
        with self._tools_condition:
            if self.closed.is_set():
                raise PermissionError('Task proxy tool admission is closed')
            self._active_tools += 1
        try:
            if not self.permitted():
                raise PermissionError('Task proxy authority changed')
            return self.tool_handler(tool, arguments, call_id)
        finally:
            with self._tools_condition:
                self._active_tools -= 1
                self._tools_condition.notify_all()

    def wait_for_tools(self, timeout=0.2):
        """One bounded observation; False is live work, not an expired task."""
        if type(timeout) not in (int, float) or not 0 <= timeout <= 1:
            raise ValueError('Invalid host callback observation interval')
        with self._tools_condition:
            if self._active_tools or not self.closed.is_set():
                self._tools_condition.wait(timeout)
            return self.closed.is_set() and self._active_tools == 0

    def close(self):
        with self._close_lock:
            if self._disposed:
                return
            try:
                self._close()
            finally:
                self._disposed = True

    def _close(self):
        with self._tools_condition:
            self.closed.set()
            self._tools_condition.notify_all()
        with self.lock:
            pending = list(self.connections)
            sockets = list(self.stream_sockets)
        # HTTPConnection drops .sock for Connection: close, while HTTPResponse
        # keeps its makefile alive. Retain the original socket for cancellation.
        for stream in sockets:
            try:
                stream.shutdown(2)
            except OSError:
                pass
        for connection in pending:
            try:
                if connection.sock:
                    connection.sock.shutdown(2)
                connection.close()
            except OSError:
                pass
        if self.thread:
            self.server.shutdown()
            self.thread.join(timeout=5)
        self.server.server_close()
        # Anchored to the directory we opened, not a possibly replaced pathname.
        # Never unlink another socket that has replaced this instance's inode.
        self._dispose_socket()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'TaskProxy'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(15)  # request framing only, not a job deadline

    def log_message(self, *_):
        pass

    def send_error(self, code, message=None, explain=None):
        self._json(code, {'error': 'Request rejected', 'code': code})

    def _json(self, code, value):
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
        if len(raw) > MAX_RESULT:
            code, raw = 502, b'{"error":"Response too large"}'
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def handle_expect_100(self):
        self.send_error(417)
        return False

    def do_POST(self):
        proxy = self.server.owner
        self.close_connection = True
        auth = self.headers.get_all('Authorization', [])
        if (len(auth) != 1 or not hmac.compare_digest(auth[0].encode(), ('Bearer ' + proxy.token).encode())
                or not proxy.permitted()):
            self.send_error(403)
            return
        if self.path not in {'/tools/call', '/v1/responses'}:
            self.send_error(404)
            return
        lengths = self.headers.get_all('Content-Length', [])
        if (self.headers.get_all('Transfer-Encoding') or len(lengths) != 1
                or not re.fullmatch(r'[0-9]{1,8}', lengths[0])
                or not 0 < int(lengths[0]) <= MAX_REQUEST
                or len(self.headers.get_all('Content-Type', [])) != 1
                or self.headers.get_content_type() != 'application/json'):
            self.send_error(400)
            return
        try:
            raw = self.rfile.read(int(lengths[0]))
            if len(raw) != int(lengths[0]):
                raise ValueError('Incomplete body')
            payload = strict_json(raw)
            if not proxy.permitted():
                self.send_error(403)
                return
            if self.path == '/tools/call':
                if (type(payload) is not dict or set(payload) != {'tool', 'arguments', 'call_id'}
                        or not isinstance(payload['tool'], str) or not CALL_ID.fullmatch(payload['tool'])
                        or not isinstance(payload['call_id'], str) or not CALL_ID.fullmatch(payload['call_id'])
                        or type(payload['arguments']) is not dict):
                    raise ValueError('Invalid tool envelope')
                result = proxy.dispatch_tool(payload['tool'], payload['arguments'], payload['call_id'])
                if not proxy.permitted():
                    self.send_error(403)
                    return
                self._json(200, {'result': result})
            else:
                self._model(model_payload(payload))
        except (ValueError, TypeError, RecursionError):
            self.send_error(400)
        except PermissionError:
            self.send_error(403)
        except (BrokenPipeError, ConnectionError, TimeoutError):
            pass
        except Exception:
            # Never return SQL errors, credentials, absolute paths or tracebacks.
            self.send_error(502)

    def _model(self, payload):
        proxy = self.server.owner
        if not callable(proxy.model_key):
            self.send_error(503)
            return
        with proxy.lock:
            if proxy.model_calls >= proxy.max_model_calls:
                self.send_error(429)
                return
            proxy.model_calls += 1
        upstream = proxy.connection_factory()
        with proxy.lock:
            proxy.connections.add(upstream)
        started = False
        stream_socket = None
        try:
            if not proxy.permitted():
                self.send_error(403)
                return
            key = proxy.model_key()
            if not isinstance(key, str) or not key or '\r' in key or '\n' in key:
                raise ValueError('Invalid model credential')
            if upstream.sock is None:
                upstream.connect()
            stream_socket = upstream.sock
            with proxy.lock:
                proxy.stream_sockets.add(stream_socket)
            if not proxy.permitted():
                self.send_error(403)
                return
            upstream.request('POST', '/v1/responses', body=payload, headers={
                'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                'Accept': 'text/event-stream', 'Accept-Encoding': 'identity', 'Connection': 'close'})
            del key
            # A quiet model is not a failed task. Explicit cancellation closes
            # the tracked upstream socket; SSE browser lifetimes are separate.
            if upstream.sock:
                upstream.sock.settimeout(None)
            response = upstream.getresponse()
            if response.status != 200 or response.getheader('Content-Type', '').split(';')[0] != 'text/event-stream':
                self.send_error(502)
                return
            self.connection.settimeout(None)
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.end_headers()
            started = True
            total = 0
            while proxy.permitted():
                chunk = response.read1(16384)
                if not chunk:
                    break
                if not proxy.permitted():
                    break
                total += len(chunk)
                if total > 32 * 1024 * 1024:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except Exception:
            if not started:
                self.send_error(502)
        finally:
            upstream.close()
            with proxy.lock:
                proxy.connections.discard(upstream)
                proxy.stream_sockets.discard(stream_socket)
