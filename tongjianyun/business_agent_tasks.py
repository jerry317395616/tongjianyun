"""Durable ordinary-business task/event core; NOT a public HTTP endpoint.

One shared Codex installation, separate task identities and execution contexts.
Trusted web code derives authenticated_owner from its session, never a request
payload. Trusted workers alone retain dispatch/worker tokens. This module does
not enqueue, execute Codex, grant Frappe permissions or fall back to meal_chat.

SQLite task state, outbox and per-task event sequences commit atomically with
FULL synchronization in a private directory outside all model mounts. Queue
delivery is reconciled using an authoritative observer, never a heartbeat age.
The independent queue is business_codex; duplicate deliveries cannot claim an
already claimed task. A browser disconnect only closes its generator.

authorize(identity, scopes) MUST freshly check the enabled account and every
registered business scope in its own Frappe context. Called outside SQLite transactions,
including before every SSE event, so a suspended generator retains no original
web session authority. Revocation requests stopping before any more tools run.
Actual cgroup shutdown and in-flight write drainage belong to the supervisor.
observe_execution(identity, claim_id) MUST inspect that exact process/cgroup
and write ledger; elapsed time, a missing heartbeat, or a model statement is NOT
terminal evidence. Cancellation cannot undo previously committed business work.
Crash reconciliation additionally requires the supervisor's irreversible proof
that the worker lease is closed. A process exit alone must not steal a live
worker's opportunity to drain stdout and finish its public projection.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import time
from typing import Callable
import uuid

from tongjianyun.business_agent_transport import private_directory
from tongjianyun.meal_chat_events import public_text, sse_frame

QUEUE = 'business_codex'
ACTIVE = frozenset({'queued', 'running', 'stopping'})
TERMINAL = frozenset({'completed', 'failed', 'cancelled'})
MAX_EVENT_BYTES = 32768
MAX_CONTEXT_BYTES = 8192
MAX_PAGE = 100
MAX_SCOPES = 256


@dataclass(frozen=True)
class TaskIdentity:
    site: str
    owner: str
    task_id: str
    mode: str = 'business'


@dataclass(frozen=True)
class WorkerClaim:
    identity: TaskIdentity
    claim_id: str
    token: str


@dataclass(frozen=True)
class DispatchTicket:
    identity: TaskIdentity
    queue: str
    job_id: str
    token: str


@dataclass(frozen=True)
class ExecutionObservation:
    claim_id: str
    state: str  # running / exited / unknown / never_started_and_sealed
    active_writes: int
    exit_code: int | None = None
    turn_completed: bool = False
    lease_closed: bool = False  # trusted supervisor proof, never a timeout guess


@dataclass(frozen=True)
class QueueObservation:
    job_id: str
    state: str  # present / absent / unknown, obtained from the actual queue


def _json(value, maximum):
    def inspect(node, depth=0):
        if depth > 8:
            raise ValueError('JSON nesting exceeds task limit')
        if type(node) is dict:
            if len(node) > 64 or any(not isinstance(key, str) or len(key) > 64 for key in node):
                raise ValueError('Invalid JSON object keys')
            for item in node.values():
                inspect(item, depth + 1)
        elif type(node) is list:
            if len(node) > MAX_SCOPES:
                raise ValueError('JSON array exceeds task limit')
            for item in node:
                inspect(item, depth + 1)
        elif node is not None and type(node) not in (str, int, float, bool):
            raise ValueError('Task data must be finite JSON')
    inspect(value)
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))
    if len(encoded.encode()) > maximum:
        raise ValueError('Task data exceeds size limit')
    return encoded


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('Expected canonical UUID')
    return value


def _owner(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 140 or value == 'Guest' or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid authenticated account')
    return value


def _hash(token):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', token):
        raise PermissionError('Invalid worker capability')
    return hashlib.sha256(token.encode()).hexdigest()


def _execution_observation(value, claim_id):
    if (not isinstance(value, ExecutionObservation) or value.claim_id != claim_id
            or type(value.active_writes) is not int or value.active_writes < 0
            or type(value.turn_completed) is not bool or type(value.lease_closed) is not bool
            or (value.exit_code is not None and type(value.exit_code) is not int)
            or not isinstance(value.state, str)
            or value.state not in {'running', 'exited', 'unknown', 'never_started_and_sealed'}):
        raise ValueError('Invalid execution observation')
    if value.state == 'never_started_and_sealed' and (value.active_writes != 0
            or value.exit_code is not None or value.turn_completed or not value.lease_closed):
        # This proof is an irreversible supervisor tombstone, not an invented
        # process exit. It certifies no start was accepted and no later start
        # can be accepted for this exact claim. Missing-unit observations alone
        # must remain unknown and can never be converted into this state.
        raise ValueError('Invalid never-started execution seal')
    return value


def _cursor(value, task_id):
    if value == '0':
        return 0
    if not isinstance(value, str) or not value.startswith(task_id + ':'):
        raise ValueError('Event cursor belongs to another task')
    sequence = value[len(task_id) + 1:]
    if not re.fullmatch(r'0|[1-9][0-9]{0,18}', sequence) or int(sequence) > 9223372036854775807:
        raise ValueError('Invalid event cursor')
    return int(sequence)


def _selection(value):
    if type(value) is not dict or not isinstance(value.get('view'), str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', value['view']):
        raise ValueError('Expected a registered view selection')
    # Registry-specific semantic permissions are checked by the business tool
    # BEFORE trusted publication, and again by the browser on opening a view.
    forbidden = {'owner', 'actor', 'site', 'task_id', 'mode', 'worker_token', 'token', 'password',
                 'api_key', 'html', 'javascript', 'sql', 'method', 'code', 'stdout', 'stderr', 'reasoning'}
    def inspect(node):
        if type(node) is dict:
            if set(node) & forbidden or any(not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', key) for key in node):
                raise ValueError('View selection contains execution or identity fields')
            for item in node.values():
                inspect(item)
        elif type(node) is list:
            for item in node:
                inspect(item)
    # The bounded JSON pass precedes recursion for hostile nested input.
    _json(value, MAX_CONTEXT_BYTES)
    inspect(value)
    return json.loads(_json(value, MAX_CONTEXT_BYTES))


def public_event(value):
    """Finite public projection, never raw Codex JSONL, tool output or reasoning."""
    if type(value) is not dict:
        raise ValueError('Invalid public event')
    kind = value.get('kind')
    fields = {'status': {'kind', 'text'}, 'message': {'kind', 'item_id', 'text'},
              'progress': {'kind', 'item_id', 'text', 'status'},
              'view': {'kind', 'version', 'selection', 'title'}}
    if not isinstance(kind, str) or kind not in fields or set(value) != fields[kind]:
        raise ValueError('Unsupported public event schema')
    result = dict(value)
    for field in ('text', 'title'):
        if field in result:
            if not isinstance(result[field], str) or not result[field].strip() or len(result[field]) > 16000:
                raise ValueError('Invalid public text')
            result[field] = public_text(result[field])
    if 'item_id' in result and (not isinstance(result['item_id'], str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', result['item_id'])):
        raise ValueError('Invalid public item id')
    if kind == 'progress' and (not isinstance(result['status'], str) or result['status'] not in {'running', 'completed', 'failed'}):
        raise ValueError('Invalid progress state')
    if kind == 'view':
        if type(result['version']) is not int or result['version'] != 1:
            raise ValueError('Invalid view version')
        result['selection'] = _selection(result['selection'])
    return json.loads(_json(result, MAX_EVENT_BYTES))


def authority_scope(value):
    """Trusted adapter descriptors, not model-provided permission assertions.

Adapters register every relevant class/document scope before exposing its data
to the model. Unknown capabilities must fail closed in the application-specific
authorizer. This is a protocol, not a generic Frappe permission fingerprint.
"""
    schemas = {'class': {'kind', 'group', 'actions'}, 'doctype': {'kind', 'doctype', 'actions'},
               'document': {'kind', 'doctype', 'document', 'actions'}, 'view': {'kind', 'selection'},
               'capability': {'kind', 'name'}, 'attachment': {'kind', 'descriptor'},
               'recipe': {'kind', 'recipe'}}
    if type(value) is not dict or not isinstance(value.get('kind'), str) or value['kind'] not in schemas or set(value) != schemas[value['kind']]:
        raise ValueError('Invalid registered authority scope')
    result = dict(value)
    if value['kind'] == 'recipe':
        # Native recipe edits replace detail row IDs. The dedicated aggregate
        # source follows the original whole-recipe/history permission contract,
        # not a generic exemption for missing/deleted arbitrary documents.
        from tongjianyun.business_agent_recipes import normalize_source
        result = normalize_source(value)
    elif value['kind'] == 'attachment':
        from tongjianyun.business_agent_attachments import normalize_descriptor
        result['descriptor'] = normalize_descriptor(value['descriptor'])
    elif value['kind'] == 'view':
        result['selection'] = _selection(value['selection'])
    else:
        for key in set(value) - {'kind', 'actions'}:
            if not isinstance(value[key], str) or not 1 <= len(value[key]) <= 140 or any(ord(c) < 32 for c in value[key]):
                raise ValueError('Invalid authority scope identifier')
    if 'actions' in value:
        actions = value['actions']
        if type(actions) is not list or not actions or any(not isinstance(action, str) or action not in
                {'read', 'create', 'write', 'submit', 'cancel', 'delete'} for action in actions) or len(actions) != len(set(actions)):
            raise ValueError('Invalid scope actions')
        result['actions'] = sorted(actions)
    return json.loads(_json(result, MAX_CONTEXT_BYTES))


class BusinessTaskStore:
    def __init__(self, directory, site, *, authorize: Callable, observe_execution: Callable,
                 observe_queue: Callable, clock=time.time, seal_execution: Callable | None = None):
        self.directory = private_directory(directory)
        if not isinstance(site, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', site):
            raise ValueError('Invalid site')
        if not all(callable(value) for value in (authorize, observe_execution, observe_queue, clock)):
            raise ValueError('Trusted authorization and runtime observers are required')
        if seal_execution is not None and not callable(seal_execution):
            raise ValueError('Invalid trusted before-start sealer')
        self.site, self.authorize = site, authorize
        self.observe_execution, self.observe_queue, self.clock = observe_execution, observe_queue, clock
        self.seal_execution = seal_execution
        self.path = self.directory / 'business-tasks.sqlite3'
        if self.path.exists() and (self.path.is_symlink() or not self.path.is_file()):
            raise ValueError('Invalid task database')
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            info = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (os.name == 'posix' and (
                info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077)):
            raise ValueError('Task database must be a private single-link file')
        # SQLite derives new journal permissions from the 0600 database. Reject
        # unsafe pre-existing sidecars before SQLite can recover/follow them.
        for suffix in ('-journal', '-wal', '-shm'):
            sidecar = Path(str(self.path) + suffix)
            if sidecar.exists() or sidecar.is_symlink():
                info = sidecar.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (os.name == 'posix' and (
                        info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077)):
                    raise ValueError('Task journal must be a private single-link file')
        with self._transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS identity (id INTEGER PRIMARY KEY CHECK(id=1), site TEXT NOT NULL)')
            row = db.execute('SELECT site FROM identity WHERE id=1').fetchone()
            if row and row['site'] != site:
                raise PermissionError('Task store belongs to another site')
            db.execute('INSERT OR IGNORE INTO identity VALUES (1, ?)', (site,))
            db.execute('CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, owner TEXT NOT NULL, '
                       "mode TEXT NOT NULL CHECK(mode='business'), status TEXT NOT NULL, message TEXT NOT NULL, "
                       'context TEXT NOT NULL, digest TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, '
                       'cancel_requested INTEGER NOT NULL DEFAULT 0, claim_id TEXT, worker_hash TEXT, '
                       'sequence INTEGER NOT NULL DEFAULT 0, answer_seen INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS events (task_id TEXT NOT NULL, sequence INTEGER NOT NULL, '
                       'payload TEXT NOT NULL, PRIMARY KEY(task_id, sequence), FOREIGN KEY(task_id) REFERENCES tasks(task_id))')
            db.execute('CREATE TABLE IF NOT EXISTS outbox (task_id TEXT PRIMARY KEY, state TEXT NOT NULL, '
                       'job_id TEXT NOT NULL UNIQUE, token_hash TEXT, FOREIGN KEY(task_id) REFERENCES tasks(task_id))')
            db.execute('CREATE TABLE IF NOT EXISTS authorities (task_id TEXT NOT NULL, digest TEXT NOT NULL, '
                       'descriptor TEXT NOT NULL, PRIMARY KEY(task_id,digest), FOREIGN KEY(task_id) REFERENCES tasks(task_id))')

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('PRAGMA foreign_keys=ON')
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self):
        with self._connection() as db:
            with db:
                db.execute('BEGIN IMMEDIATE')
                yield db

    def _identity(self, identity):
        if not isinstance(identity, TaskIdentity) or identity.site != self.site or identity.mode != 'business':
            raise PermissionError('Business task identity mismatch')
        _owner(identity.owner)
        _uuid(identity.task_id)

    def _row(self, db, identity):
        self._identity(identity)
        row = db.execute('SELECT * FROM tasks WHERE task_id=?', (identity.task_id,)).fetchone()
        if not row or row['owner'] != identity.owner or row['mode'] != 'business':
            raise PermissionError('Task is not owned by this account')
        return row

    def _owned(self, identity):
        with self._connection() as db:
            return dict(self._row(db, identity))

    def _access(self, identity):
        self._owned(identity)
        for _ in range(3):
            scopes = self.required_scopes(identity)
            try:
                allowed = self.authorize(identity, scopes) is True
            except Exception:
                allowed = False
            if not allowed:
                break
            if scopes == self.required_scopes(identity):
                return self._owned(identity)
        self.revoke(identity)
        raise PermissionError('Current account or registered business scope is no longer authorized')

    def required_scopes(self, identity):
        """Trusted authorizer inspection, not a public data/permission endpoint."""
        with self._connection() as db:
            self._row(db, identity)
            return [json.loads(row[0]) for row in db.execute('SELECT descriptor FROM authorities WHERE task_id=? '
                     'ORDER BY digest', (identity.task_id,)).fetchall()]

    def register_authority(self, claim, descriptor):
        """Must succeed BEFORE an adapter exposes matching data or executes a write."""
        return self.register_authorities(claim, (descriptor,))[0]

    def register_authorities(self, claim, descriptors):
        """Atomically register one trusted, bounded batch before releasing data.

        Validate every descriptor and the complete old/new union before any
        insert. Check the concurrent persisted union again after commit, without
        holding a SQLite transaction across framework authorization. A failed
        post-check can retain the full batch as stricter dependencies, but never
        returns authority to deliver its data. No scope is removed or widened.
        """
        if not isinstance(descriptors, (list, tuple)) or len(descriptors) > MAX_SCOPES:
            raise ValueError('Invalid bounded business authority batch')
        unique = {}
        for descriptor in descriptors:
            descriptor = authority_scope(descriptor)
            encoded = _json(descriptor, MAX_CONTEXT_BYTES)
            unique[encoded] = descriptor
        batch = tuple(unique.values())
        self._worker(claim, access=True)
        scopes = self.required_scopes(claim.identity)
        proposed = [*scopes, *(descriptor for descriptor in batch if descriptor not in scopes)]
        if len(proposed) > MAX_SCOPES:
            raise ValueError('Task authority scope limit reached; do not expose more data')
        if self.authorize(claim.identity, proposed) is not True:
            raise PermissionError('New business scope is not authorized; its data must not be delivered')
        rows = [(claim.identity.task_id, hashlib.sha256(encoded.encode()).hexdigest(), encoded)
                for encoded in unique]
        with self._transaction() as db:
            row = self._row(db, claim.identity)
            if row['status'] != 'running' or row['cancel_requested']:
                raise PermissionError('Task no longer accepts new business scopes')
            current = {item[0] for item in db.execute('SELECT digest FROM authorities WHERE task_id=?',
                                                    (claim.identity.task_id,)).fetchall()}
            if len(current | {item[1] for item in rows}) > MAX_SCOPES:
                raise ValueError('Task authority scope limit reached')
            db.executemany('INSERT OR IGNORE INTO authorities VALUES (?, ?, ?)', rows)
        state = self._access(claim.identity)
        if state['status'] != 'running' or state['cancel_requested']:
            raise PermissionError('Task no longer accepts new business scopes')
        return batch

    def _event(self, db, identity, value):
        encoded = _json(value, MAX_EVENT_BYTES)
        db.execute('UPDATE tasks SET sequence=sequence+1, updated=? WHERE task_id=?', (self.clock(), identity.task_id))
        sequence = db.execute('SELECT sequence FROM tasks WHERE task_id=?', (identity.task_id,)).fetchone()[0]
        db.execute('INSERT INTO events VALUES (?, ?, ?)', (identity.task_id, sequence, encoded))
        return identity.task_id + ':' + str(sequence)

    def create(self, authenticated_owner, request_id, message, context=None, *, authority_scopes=()):
        identity = TaskIdentity(self.site, _owner(authenticated_owner), _uuid(request_id))
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 8000:
            raise ValueError('A bounded business request is required')
        if context is None:
            context = {}
        if type(context) is not dict or set(context) - {'day', 'meal', 'selection', 'business_area', 'attachments'}:
            raise ValueError('Invalid business context')
        if 'selection' in context:
            context = {**context, 'selection': _selection(context['selection'])}
        if 'attachments' in context:
            from tongjianyun.business_agent_attachments import normalize_descriptor, source_scope
            attachments = context['attachments']
            if type(attachments) is not list or len(attachments) != 1:
                raise ValueError('Exactly one trusted attachment is supported per request')
            context = {**context, 'attachments': [normalize_descriptor(attachments[0])]}
            # A bound file is a dependency from admission onward, not only
            # after the model elects to read it. It cannot outlive revocation.
            authority_scopes = (*authority_scopes, source_scope(context['attachments'][0]))
        for field in set(context) - {'selection', 'attachments'}:
            if not isinstance(context[field], str) or len(context[field]) > 140:
                raise ValueError('Invalid business context field')
        encoded = _json(context, MAX_CONTEXT_BYTES)
        if type(authority_scopes) not in (list, tuple) or len(authority_scopes) > MAX_SCOPES:
            raise ValueError('Invalid initial task scopes')
        initial = [authority_scope(value) for value in authority_scopes]
        if 'selection' in context:
            initial.append(authority_scope({'kind': 'view', 'selection': context['selection']}))
        initial_by_key = {_json(value, MAX_CONTEXT_BYTES): value for value in initial}
        initial = [initial_by_key[key] for key in sorted(initial_by_key)]
        if len(initial) > MAX_SCOPES:
            raise ValueError('Initial scope limit exceeded')
        digest = hashlib.sha256((message.strip() + '\n' + encoded + '\n' + _json(initial, 1024 * 1024)).encode()).hexdigest()
        message = public_text(message.strip())
        if self.authorize(identity, initial) is not True:
            raise PermissionError('Current account cannot create this task')
        with self._transaction() as db:
            existing = db.execute('SELECT * FROM tasks WHERE task_id=?', (identity.task_id,)).fetchone()
            if existing:
                self._row(db, identity)
                if existing['digest'] != digest:
                    raise ValueError('Request id cannot be reused for a different request')
                return {'identity': identity, 'created': False, 'status': existing['status']}
            now = self.clock()
            db.execute('INSERT INTO tasks (task_id, owner, mode, status, message, context, digest, created, updated) '
                       'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                       (identity.task_id, identity.owner, 'business', 'queued', message, encoded, digest, now, now))
            db.execute('INSERT INTO outbox VALUES (?, ?, ?, NULL)', (identity.task_id, 'pending', self.job_id(identity)))
            for scope in initial:
                descriptor = _json(scope, MAX_CONTEXT_BYTES)
                db.execute('INSERT INTO authorities VALUES (?, ?, ?)',
                           (identity.task_id, hashlib.sha256(descriptor.encode()).hexdigest(), descriptor))
            self._event(db, identity, {'kind': 'status', 'text': '已收到，正在准备处理…'})
        return {'identity': identity, 'created': True, 'status': 'queued'}

    def job_id(self, identity):
        self._identity(identity)
        return 'business-codex-' + hashlib.sha256(self.site.encode()).hexdigest()[:16] + '-' + identity.task_id

    def task(self, identity):
        self._access(identity)
        row = self._owned(identity)
        return {'task_id': identity.task_id, 'mode': 'business', 'status': row['status'],
                'message': row['message'], 'context': json.loads(row['context']),
                'cancel_requested': bool(row['cancel_requested']), 'last_event_id': identity.task_id + ':' + str(row['sequence'])}

    def find_task(self, identity):
        """Trusted submission lookup; collisions still enforce exact ownership."""
        self._identity(identity)
        with self._connection() as db:
            exists = db.execute('SELECT 1 FROM tasks WHERE task_id=?', (identity.task_id,)).fetchone()
        return self.task(identity) if exists else None

    def active_task(self, authenticated_owner):
        """All active rows, not a bounded history page; caller serializes submits.

        First attempt trusted crash drainage without exposing old business
        data. A revoked old scope must not permanently block this owner's new
        authorized work once the exact execution/lease has safely ended. Any
        unknown or failed observation keeps the active row; reading its content
        still requires full current authority and cannot silently free a slot.
        """
        owner = _owner(authenticated_owner)
        while True:
            with self._connection() as db:
                row = db.execute("SELECT task_id FROM tasks WHERE owner=? AND status IN ('queued','running','stopping') "
                                 'ORDER BY rowid LIMIT 1', (owner,)).fetchone()
            if not row:
                return None
            identity = TaskIdentity(self.site, owner, row['task_id'])
            try:
                status = self.reconcile(identity)
            except Exception:
                # Best effort cleanup only. Failure is NEVER proof of absence.
                status = None
            if status in TERMINAL:
                continue
            task = self.task(identity)  # never expose revoked prior-scope data
            if task['status'] in ACTIVE:
                return task
            # A live worker may have finished during the separate observation.

    def history(self, authenticated_owner, *, before=None, limit=20):
        """Current-account task index; each returned task is reauthorized.

The web layer authenticates the owner even when this empty index has no task to
authorize. No per-task capability, model thread ID or worker token is returned.
"""
        owner = _owner(authenticated_owner)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('Invalid history page size')
        with self._connection() as db:
            values = [owner]
            clause = ''
            if before is not None:
                identity = TaskIdentity(self.site, owner, _uuid(before))
                self._row(db, identity)
                rowid = db.execute('SELECT rowid FROM tasks WHERE task_id=?', (before,)).fetchone()[0]
                clause = ' AND rowid<?'
                values.append(rowid)
            values.append(limit + 1)
            rows = db.execute('SELECT task_id FROM tasks WHERE owner=?' + clause + ' ORDER BY rowid DESC LIMIT ?', values).fetchall()
        page = []
        for row in rows[:limit]:
            identity = TaskIdentity(self.site, owner, row['task_id'])
            try:
                page.append(self.task(identity))
            except PermissionError:
                if not self._history_may_omit(identity):
                    raise
        # Use the last scanned row, not the last visible one: an entirely
        # unavailable page must neither loop nor hide earlier authorized work.
        return {'tasks': page, 'next_before': rows[limit - 1]['task_id'] if len(rows) > limit else None}

    def _history_may_omit(self, identity):
        """Never turn account revocation or undrained work into an empty history.

        A removed/changed private attachment may revoke an old terminal task,
        but cannot suppress this owner's unrelated authorized conversations.
        No content, source ids or file metadata from the omitted task is sent.
        """
        row = self._owned(identity)
        return row['status'] in TERMINAL and self.authorize(identity, ()) is True

    def binding_state(self, claim):
        """Trusted BusinessBinding.read_task adapter; never expose worker token."""
        row = self._worker(claim, access=True)
        return {'site': self.site, 'owner': claim.identity.owner, 'task_id': claim.identity.task_id,
                'mode': 'business', 'status': row['status'], 'cancel_requested': str(row['cancel_requested'])}

    def _worker(self, claim, *, access):
        if not isinstance(claim, WorkerClaim):
            raise PermissionError('Worker claim is required')
        row = self._access(claim.identity) if access else self._owned(claim.identity)
        if row['claim_id'] != claim.claim_id or not row['worker_hash'] or not hmac.compare_digest(row['worker_hash'], _hash(claim.token)):
            raise PermissionError('Worker capability does not match task')
        return row

    def take_dispatch(self, identity):
        self._access(identity)
        token = secrets.token_urlsafe(32)
        with self._transaction() as db:
            task = self._row(db, identity)
            row = db.execute('SELECT * FROM outbox WHERE task_id=?', (identity.task_id,)).fetchone()
            if task['status'] != 'queued' or task['cancel_requested'] or row['state'] != 'pending':
                return None
            db.execute('UPDATE outbox SET state=?, token_hash=? WHERE task_id=?', ('dispatching', _hash(token), identity.task_id))
        return DispatchTicket(identity, QUEUE, self.job_id(identity), token)

    def acknowledge_dispatch(self, ticket):
        if not isinstance(ticket, DispatchTicket) or ticket.queue != QUEUE or ticket.job_id != self.job_id(ticket.identity):
            raise PermissionError('Invalid queue dispatch ticket')
        with self._transaction() as db:
            self._row(db, ticket.identity)
            row = db.execute('SELECT * FROM outbox WHERE task_id=?', (ticket.identity.task_id,)).fetchone()
            if not row['token_hash'] or not hmac.compare_digest(row['token_hash'], _hash(ticket.token)):
                raise PermissionError('Dispatch ticket mismatch')
            if row['state'] not in {'dispatching', 'dispatched'}:
                raise ValueError('Dispatch is not active')
            db.execute('UPDATE outbox SET state=? WHERE task_id=?', ('dispatched', ticket.identity.task_id))

    def recover_dispatch(self, identity):
        """No age-based retry: only observed absence before any worker claim."""
        self._owned(identity)
        with self._connection() as db:
            before = dict(db.execute('SELECT * FROM outbox WHERE task_id=?', (identity.task_id,)).fetchone())
        # An acknowledged/present queue entry can still disappear before claim.
        # Reconcile it too, but never infer absence from elapsed time or retry a
        # claimed task. The outbox compare-and-swap below protects a new delivery
        # from an older observation made outside the SQLite transaction.
        if before['state'] not in {'dispatching', 'dispatched'}:
            return before['state']
        observation = self.observe_queue(before['job_id'])  # outside any SQLite lock
        if not isinstance(observation, QueueObservation) or observation.job_id != before['job_id']:
            raise ValueError('Invalid queue observation')
        if observation.state not in {'present', 'absent', 'unknown'}:
            raise ValueError('Invalid queue observation state')
        with self._transaction() as db:
            task = self._row(db, identity)
            current = db.execute('SELECT * FROM outbox WHERE task_id=?', (identity.task_id,)).fetchone()
            if dict(current) != before:
                return current['state']
            if observation.state == 'present':
                state = 'dispatched'
            elif observation.state == 'absent' and task['status'] == 'queued' and not task['claim_id'] and not task['cancel_requested']:
                state = 'pending'
            else:
                return current['state']
            # Keep the dispatch generation when merely observing presence.
            # Clearing both old/new delivered ticket hashes would allow an ABA
            # cycle: a stale absence could mistake a newer observed delivery
            # for its original snapshot and reset that delivery to pending.
            if state == 'dispatched':
                db.execute('UPDATE outbox SET state=? WHERE task_id=?', (state, identity.task_id))
            else:
                db.execute('UPDATE outbox SET state=?, token_hash=NULL WHERE task_id=?', (state, identity.task_id))
            return state

    def claim(self, identity, job_id):
        self._access(identity)
        if job_id != self.job_id(identity):
            raise PermissionError('Wrong business queue job')
        token, claim_id = secrets.token_urlsafe(32), str(uuid.uuid4())
        with self._transaction() as db:
            row = self._row(db, identity)
            outbox = db.execute('SELECT state FROM outbox WHERE task_id=?', (identity.task_id,)).fetchone()
            if row['status'] != 'queued' or row['cancel_requested'] or row['claim_id']:
                return None
            if outbox['state'] not in {'dispatching', 'dispatched'}:
                raise PermissionError('No trusted queue dispatch exists')
            db.execute('UPDATE tasks SET status=?, claim_id=?, worker_hash=? WHERE task_id=?',
                       ('running', claim_id, _hash(token), identity.task_id))
            self._event(db, identity, {'kind': 'status', 'text': '助手已开始处理…'})
        return WorkerClaim(identity, claim_id, token)

    def emit(self, claim, event):
        event = public_event(event)
        self._worker(claim, access=True)
        with self._transaction() as db:
            row = self._row(db, claim.identity)
            if row['status'] != 'running' or row['cancel_requested']:
                raise PermissionError('Task no longer accepts model/tool events')
            if event['kind'] == 'message':
                db.execute('UPDATE tasks SET answer_seen=1 WHERE task_id=?', (claim.identity.task_id,))
            return self._event(db, claim.identity, event)

    def _stop(self, identity, text):
        with self._transaction() as db:
            row = self._row(db, identity)
            if row['status'] in TERMINAL or row['status'] == 'stopping':
                return row['status']
            status = 'cancelled' if row['status'] == 'queued' and not row['claim_id'] else 'stopping'
            db.execute('UPDATE tasks SET status=?, cancel_requested=1 WHERE task_id=?', (status, identity.task_id))
            event = {'kind': 'terminal', 'status': status, 'text': '任务尚未执行，已停止。'} if status == 'cancelled' else {'kind': 'status', 'text': text}
            self._event(db, identity, event)
            return status

    def cancel(self, identity):
        self._access(identity)
        return self._stop(identity, '正在停止；已提交的业务不会自动撤销，请核对记录。')

    def revoke(self, identity):
        """Trusted authority/supervisor only: stop tools even after UI is denied."""
        return self._stop(identity, '账号权限已变化，正在停止任务并核对执行结果。')

    def reconcile(self, identity):
        """Conservatively settle a claimed task whose trusted worker lease ended.

        Internal only: callers still authenticate the browser before exposing
        task data. No lost worker token is re-created, no outbox is reset, and
        no model is resumed. Only the fixed supervisor can prove an exact
        claimed execution exited, its writes drained AND its worker lease
        irreversibly closed. A missing unit, old heartbeat, queue failure or
        elapsed time is insufficient. Without the lost worker's projection,
        this path can only fail or cancel, never infer business completion.

        Only a persisted cancellation may ask the supervisor to atomically
        seal a never-bound claim against ALL future starts. That independent
        never_started_and_sealed proof can only cancel, not fail/complete. A
        normal running task is never sealed merely because its unit is missing
        or time has passed; a real bind/start racing the seal is resolved by
        the supervisor's permanent, locked task ledger, not by this web process.
        """
        before = self._owned(identity)  # ownership first, even for terminal rows
        if before['status'] in TERMINAL or not before['claim_id']:
            return before['status']
        try:
            self._access(identity)
        except PermissionError:
            pass  # Revocation requests stop; trusted cleanup must still work.
        before = self._owned(identity)
        if before['status'] in TERMINAL:
            return before['status']
        observation = _execution_observation(
            self.observe_execution(identity, before['claim_id']), before['claim_id'])
        if (observation.state == 'unknown' and before['cancel_requested'] and self.seal_execution is not None):
            current = self._owned(identity)
            if (current['status'] not in {'running', 'stopping'} or not current['cancel_requested']
                    or current['claim_id'] != before['claim_id'] or current['worker_hash'] != before['worker_hash']):
                return current['status']
            observation = _execution_observation(
                self.seal_execution(identity, before['claim_id']), before['claim_id'])
        sealed = observation.state == 'never_started_and_sealed'
        drained = observation.state == 'exited' and not observation.active_writes and observation.lease_closed
        if not drained and not sealed:
            return self._owned(identity)['status']
        try:
            self._access(identity)
        except PermissionError:
            pass
        with self._transaction() as db:
            row = self._row(db, identity)
            if (row['status'] not in {'running', 'stopping'} or row['claim_id'] != before['claim_id']
                    or row['worker_hash'] != before['worker_hash']):
                return row['status']
            if sealed and not row['cancel_requested']:
                return row['status']
            # Read cancellation under the write lock; a concurrent stop cannot
            # be overwritten using the pre-observation status snapshot.
            status = 'cancelled' if row['cancel_requested'] else 'failed'
            db.execute('UPDATE tasks SET status=? WHERE task_id=?', (status, identity.task_id))
            text = ('任务已停止；已提交的业务不会自动撤销，请核对记录。' if status == 'cancelled'
                    else '执行连接已中断，任务未确认完成；请先核对业务记录再决定下一步。')
            self._event(db, identity, {'kind': 'terminal', 'status': status, 'text': text})
            return status

    def finish(self, claim):
        """No model-supplied terminal status: derive it from the real supervisor."""
        row = self._worker(claim, access=False)
        if row['status'] in TERMINAL:
            return row['status']
        try:
            self._access(claim.identity)
        except PermissionError:
            pass  # Revoke first, then let the trusted supervisor finish drainage.
        row = self._owned(claim.identity)
        observation = _execution_observation(
            self.observe_execution(claim.identity, claim.claim_id), claim.claim_id)  # no SQLite lock held
        sealed = observation.state == 'never_started_and_sealed'
        if (observation.state != 'exited' and not sealed) or observation.active_writes:
            return row['status']
        with self._transaction() as db:
            row = self._row(db, claim.identity)
            if row['status'] in TERMINAL:
                return row['status']
            # The original worker may close its bound-but-never-started lease.
            # Its permanent seal allows failure/cancellation without inventing
            # an exit code; it can NEVER establish a completed business turn.
            status = ('cancelled' if row['cancel_requested'] else 'completed' if not sealed and observation.exit_code == 0
                      and observation.turn_completed and row['answer_seen'] else 'failed')
            db.execute('UPDATE tasks SET status=? WHERE task_id=?', (status, claim.identity.task_id))
            text = {'completed': '本次处理结束，请查看答复和业务视图。',
                    'failed': '本次任务未完成，请先核对业务记录再决定下一步。',
                    'cancelled': '任务已停止；已提交的业务不会自动撤销，请核对记录。'}[status]
            self._event(db, claim.identity, {'kind': 'terminal', 'status': status, 'text': text})
            return status

    def events(self, identity, after='0', limit=MAX_PAGE):
        cursor = _cursor(after, identity.task_id)
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE:
            raise ValueError('Invalid event page size')
        self._access(identity)
        with self._connection() as db:
            task = self._row(db, identity)
            if cursor > task['sequence']:
                raise ValueError('Cursor is beyond this task; do not borrow another task cursor')
            rows = db.execute('SELECT sequence, payload FROM events WHERE task_id=? AND sequence>? '
                              'ORDER BY sequence LIMIT ?', (identity.task_id, cursor, limit)).fetchall()
        # The producer may have registered another scope and emitted its data
        # after the first access check. Authorize this fixed page again outside
        # the read connection; never deliver those newly scoped events using an
        # earlier authority snapshot. SSE also rechecks after each suspension.
        self._access(identity)
        return [{'id': identity.task_id + ':' + str(row['sequence']), **json.loads(row['payload'])} for row in rows]

    def stream(self, identity, after='0', *, authorize_viewer, pause=time.sleep, poll_seconds=1):
        """Replayable SSE with periodic and per-event current-user checks.

pause is a trusted scheduler, not a model input. Closing this iterator never
enqueues, cancels, restarts or completes a task. No execution-duration deadline.
authorize_viewer checks the CURRENT browser session/owner, not an expired
request-local session snapshot. Viewer logout stops only this stream; account
or business-scope revocation stops the task through the separate authorizer.
"""
        _cursor(after, identity.task_id)
        if not callable(authorize_viewer) or not callable(pause) or not isinstance(poll_seconds, (float, int)) or isinstance(poll_seconds, bool) or not 0 < poll_seconds <= 10:
            raise ValueError('Invalid SSE poll interval')
        def viewer():
            try:
                allowed = authorize_viewer(identity) is True
            except Exception:
                allowed = False
            if not allowed:
                raise PermissionError('Browser session is no longer authorized for this task')
        cursor = after
        viewer()
        self._access(identity)
        yield 'retry: 2000\n: connected\n\n'
        while True:
            try:
                viewer()
                rows = self.events(identity, cursor)
                for event in rows:
                    viewer()
                    self._access(identity)  # generator may have been suspended between yields
                    cursor = event['id']
                    yield sse_frame(cursor, {key: value for key, value in event.items() if key != 'id'})
                    if event.get('kind') == 'terminal':
                        return
                task = self._access(identity)
                if task['status'] in TERMINAL and _cursor(cursor, identity.task_id) >= task['sequence']:
                    yield 'event: closed\ndata: {}\n\n'
                    return
            except PermissionError:
                yield 'event: unavailable\ndata: {}\n\n'
                return
            if not rows:
                yield ': heartbeat\n\n'
                pause(poll_seconds)
