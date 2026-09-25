"""Host-only business write admission, receipts and resource fences.

NOT a whitelisted method, a permission grant, or a database transaction runner.
The service must provide a fresh authorizer and a trusted native transaction
adapter. The service composes this ledger with native execution observations;
that candidate wiring does not itself enable production business chat.

One private SQLite file is shared by ALL ordinary-business tasks on ONE site.
It must remain outside every model mount. No pupil payload, model token or
database credential is persisted here. A receipt proves an acknowledged commit;
it is never a continuing read grant. An interrupted commit cannot be inferred
from equal business values and is never replayed automatically.

Integration order: open_task immediately after the durable worker claim; admit
tools through execute; close_task BEFORE revoking/draining the proxy; combine
the native observation with observe in BOTH worker and fresh web processes.
close_task is permanent, including when it precedes open_task. Existing host
calls must settle/close their database connections before active_writes is zero.
Crashes retain active entries: neither a timeout nor a missing native unit clears
them. A separately implemented trusted recovery procedure will be required to
prove that an interrupted host connection is drained.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Protocol
import uuid

from tongjianyun.business_agent_tasks import ExecutionObservation, TaskIdentity, WorkerClaim
from tongjianyun.business_agent_transport import private_directory

TOOLS = frozenset({'attendance_save', 'meal_save', 'recipe_save'})
MEALS = frozenset({'breakfast', 'morning_snack', 'lunch', 'afternoon_snack', 'dinner'})
CALL_ID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
MAX_ARGUMENT_BYTES = 128 * 1024


class NativeWriteTransaction(Protocol):
    """Trusted adapter, constructed without opening a DB connection.

The factory is construction-only: no DB connection, spawned worker, deferred
write, or business side effect before begin is invoked by the ledger. Thus a
factory failure is a provable no-start, not an uncertain database operation.

begin/save/commit/rollback/close operate in ONE fresh, owner-bound Frappe
context, never the RQ/request connection. save calls only the original native
service with the ORIGINAL revision. No method automatically retries. The
adapter must not commit within save or run an external side effect.

rollback returns literal True only after a confirmed full precommit rollback.
close returns literal True only after the host connection/callbacks are drained.
A failure/None is NOT proof. commit returning normally acknowledges its commit.
The factory receives trusted claim and a detached copy of validated arguments.
For recipe_save only, the ledger additionally supplies keyword operation_id:
its persisted reservation UUID, never an input field or task/call-derived ID.
The original attendance/meal factories keep their three-argument contract.
"""
    def begin(self) -> None: ...
    def save(self) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> bool: ...
    def close(self) -> bool: ...


@dataclass(frozen=True)
class WriteOutcome:
    status: str  # committed / rolled_back / uncertain / in_progress / blocked
    operation_id: str | None
    replayed: bool = False
    active: bool = False


@dataclass(frozen=True)
class HostWriteObservation:
    identity: TaskIdentity
    claim_id: str
    registered: bool
    admission_closed: bool
    active_writes: int
    uncertain_writes: int
    operations: int


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('Expected a canonical UUID')
    return value


def _identity(identity, site):
    if (not isinstance(identity, TaskIdentity) or identity.site != site or identity.mode != 'business'
            or not isinstance(identity.owner, str) or not 1 <= len(identity.owner) <= 140
            or identity.owner == 'Guest' or any(ord(c) < 32 for c in identity.owner)):
        raise PermissionError('Invalid business write identity')
    _uuid(identity.task_id)
    return identity


def _claim(claim, site):
    if not isinstance(claim, WorkerClaim):
        raise PermissionError('A verified worker claim is required')
    _identity(claim.identity, site)
    _uuid(claim.claim_id)
    if not isinstance(claim.token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', claim.token):
        raise PermissionError('Invalid worker claim capability')
    return hashlib.sha256(claim.token.encode()).hexdigest()


def _text(value, maximum=140, *, empty=False):
    if (not isinstance(value, str) or (not value and not empty) or len(value) > maximum
            or any(ord(c) < 32 for c in value)):
        raise ValueError('Invalid business write value')
    return value


def _arguments(tool, arguments):
    """Finite existing tools only; native services still own permissions/rules."""
    if not isinstance(tool, str) or tool not in TOOLS or type(arguments) is not dict:
        raise ValueError('Unsupported business write')
    if tool == 'recipe_save':
        from tongjianyun.business_agent_recipes import normalize_arguments
        return normalize_arguments(tool, arguments)
    common = {'group', 'day', 'revision'}
    required = common | ({'changes'} if tool == 'attendance_save' else {'meal', 'students', 'confirm'})
    allowed = required | ({'change_reason'} if tool == 'meal_save' else set())
    if set(arguments) - allowed or not required <= set(arguments):
        raise ValueError('Unexpected business write fields')
    _text(arguments['group'])
    day = arguments['day']
    if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
        raise ValueError('Expected a canonical business date')
    _text(arguments['revision'], 64, empty=True)
    if tool == 'attendance_save' and not re.fullmatch(r'[a-f0-9]{64}', arguments['revision']):
        raise ValueError('The original attendance revision is required')
    rows = arguments['changes' if tool == 'attendance_save' else 'students']
    if type(rows) is not list or not 1 <= len(rows) <= 500:
        raise ValueError('Expected a bounded nonempty student list')
    seen = set()
    for row in rows:
        if type(row) is not dict:
            raise ValueError('Invalid student entry')
        if tool == 'attendance_save':
            if (set(row) - {'student', 'status', 'leave_reason'} or not {'student', 'status'} <= set(row)
                    or not isinstance(row['status'], str) or row['status'] not in {'Present', 'Absent', 'Leave'}):
                raise ValueError('Invalid attendance entry')
            if 'leave_reason' in row:
                _text(row['leave_reason'], 1000, empty=True)
            if row['status'] == 'Leave' and not str(row.get('leave_reason', '')).strip():
                raise ValueError('Leave requires its original business reason')
        elif (set(row) != {'student', 'value'} or not isinstance(row['value'], str)
                or row['value'] not in {'就餐', '不就餐', '不供餐'}):
            raise ValueError('Invalid meal entry')
        _text(row['student'])
        if row['student'] in seen:
            raise ValueError('Duplicate student entry')
        seen.add(row['student'])
    if tool == 'meal_save':
        if not isinstance(arguments['meal'], str) or arguments['meal'] not in MEALS or type(arguments['confirm']) is not bool:
            raise ValueError('Invalid meal or business confirmation state')
        if 'change_reason' in arguments:
            _text(arguments['change_reason'], 1000, empty=True)
    encoded = json.dumps(arguments, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))
    if len(encoded.encode()) > MAX_ARGUMENT_BYTES:
        raise ValueError('Business write is too large')
    # Sort students for the operation digest: order is not a new write intent.
    detached = json.loads(encoded)
    key = 'changes' if tool == 'attendance_save' else 'students'
    detached[key].sort(key=lambda row: row['student'])
    if tool == 'meal_save':
        detached.setdefault('change_reason', '')
    else:
        for row in detached[key]:
            row.setdefault('leave_reason', '')
    return detached


def _digest(tool, args):
    return hashlib.sha256(json.dumps({'tool': tool, 'arguments': args}, ensure_ascii=False,
                                    sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _resources(tool, args):
    if tool == 'recipe_save':
        from tongjianyun.business_agent_recipes import resource_keys
        # Ledger identity already binds the complete database to exactly ONE
        # site. Week/aggregate locks deliberately do not include owner or task.
        return resource_keys(args)
    # Both native paths can update the daily confirmation. All meals share a
    # class-day document/revision. Do not fence only a meal, user, task or call.
    return tuple(sorted(json.dumps(key, ensure_ascii=False, separators=(',', ':')) for key in (
        ['class_day', args['group'], args['day']], ['daily_confirmation', args['day']])))


class BusinessWriteLedger:
    def __init__(self, directory, site, *, authorize):
        if not isinstance(site, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', site):
            raise ValueError('Invalid fixed site')
        if not callable(authorize):
            raise ValueError('A fresh claim AND target-scope authorizer is required')
        self.directory, self.site, self.authorize = private_directory(directory), site, authorize
        self.path = self.directory / 'business-writes.sqlite3'
        if self.path.is_symlink():
            raise ValueError('Symlink write ledger is forbidden')
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            info = os.fstat(descriptor)
            self._file_id = (info.st_dev, info.st_ino)
            self._check_file(info)
        finally:
            os.close(descriptor)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS identity (id INTEGER PRIMARY KEY CHECK(id=1), site TEXT NOT NULL)')
            row = db.execute('SELECT site FROM identity WHERE id=1').fetchone()
            if row and row[0] != site:
                raise PermissionError('Write ledger belongs to another site')
            db.execute('INSERT OR IGNORE INTO identity VALUES (1, ?)', (site,))
            db.execute('CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, owner TEXT NOT NULL, '
                       'claim_id TEXT NOT NULL, token_hash TEXT, closed INTEGER NOT NULL CHECK(closed IN (0,1)))')
            db.execute('CREATE TABLE IF NOT EXISTS operations (operation_id TEXT PRIMARY KEY, digest TEXT NOT NULL UNIQUE, '
                       "state TEXT NOT NULL CHECK(state IN ('reserved','committing','committed','rolled_back','uncertain')), "
                       'active INTEGER NOT NULL CHECK(active IN (0,1)))')
            db.execute('CREATE TABLE IF NOT EXISTS aliases (task_id TEXT NOT NULL REFERENCES tasks(task_id), '
                       'call_id TEXT NOT NULL, digest TEXT NOT NULL, operation_id TEXT REFERENCES operations(operation_id), '
                       'PRIMARY KEY(task_id,call_id))')
            db.execute('CREATE TABLE IF NOT EXISTS resources (resource TEXT PRIMARY KEY, '
                       'operation_id TEXT NOT NULL REFERENCES operations(operation_id))')

    def _check_file(self, info):
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or (info.st_dev, info.st_ino) != self._file_id or (os.name == 'posix' and (
                    info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077))):
            raise ValueError('Write ledger must be a private, unchanged single-link file')

    @contextmanager
    def _connect(self):
        private_directory(self.directory)
        if self.path.is_symlink():
            raise ValueError('Symlink write ledger is forbidden')
        self._check_file(self.path.stat(follow_symlinks=False))
        # SQLite may recover an old journal before applying our PRAGMAs. Match
        # the task store's boundary before it can follow an unsafe sidecar.
        for suffix in ('-journal', '-wal', '-shm'):
            try:
                sidecar = Path(str(self.path) + suffix).lstat()
            except FileNotFoundError:
                continue  # A concurrent legitimate transaction can remove it.
            if (not stat.S_ISREG(sidecar.st_mode) or sidecar.st_nlink != 1
                    or os.name == 'posix' and (sidecar.st_uid != os.geteuid() or stat.S_IMODE(sidecar.st_mode) & 0o077)):
                raise ValueError('Write journal must be a private single-link file')
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('PRAGMA journal_mode=DELETE')
            with db:
                yield db
        finally:
            db.close()

    def _task(self, db, identity, claim_id):
        row = db.execute('SELECT owner, claim_id, token_hash, closed FROM tasks WHERE task_id=?',
                         (identity.task_id,)).fetchone()
        if row and (row[0] != identity.owner or row[1] != claim_id):
            raise PermissionError('Write gate belongs to another owner or claim')
        return row

    def _admit(self, db, claim):
        digest = _claim(claim, self.site)
        row = self._task(db, claim.identity, claim.claim_id)
        if not row or row[3] or not row[2] or not hmac.compare_digest(row[2], digest):
            raise PermissionError('Business write admission is closed or unbound')

    def _authorize(self, claim, tool, args):
        # Detached arguments prevent a buggy callback from changing the digest.
        if self.authorize(claim, tool, json.loads(json.dumps(args))) is not True:
            raise PermissionError('Business write authority is no longer valid')

    def open_task(self, claim):
        """Trusted worker only, immediately after store.claim; never reopen."""
        token_hash = _claim(claim, self.site)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._task(db, claim.identity, claim.claim_id)
            if row:
                self._admit(db, claim)
            else:
                db.execute('INSERT INTO tasks VALUES (?, ?, ?, ?, 0)',
                           (claim.identity.task_id, claim.identity.owner, claim.claim_id, token_hash))

    def close_task(self, identity, claim_id):
        """Trusted cancellation/worker path; permanently stops new admission.

        This is NOT drainage: use observe afterwards. A close-before-open
        tombstone prevents a delayed worker from admitting a write.
        """
        _identity(identity, self.site)
        _uuid(claim_id)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._task(db, identity, claim_id)
            if row:
                db.execute('UPDATE tasks SET closed=1 WHERE task_id=?', (identity.task_id,))
            else:
                db.execute('INSERT INTO tasks VALUES (?, ?, ?, NULL, 1)',
                           (identity.task_id, identity.owner, claim_id))
        return self.observe(identity, claim_id)

    def require_delivery(self, claim, tool, arguments):
        args = _arguments(tool, arguments)
        _claim(claim, self.site)
        self._authorize(claim, tool, args)
        with self._connect() as db:
            self._admit(db, claim)

    @staticmethod
    def _outcome(row, replayed=False):
        operation_id, state, active = row
        return WriteOutcome('in_progress' if state in {'reserved', 'committing'} else state,
                            operation_id, replayed, bool(active))

    def _reserve(self, claim, call_id, tool, args):
        digest = _digest(tool, args)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._admit(db, claim)
            alias = db.execute('SELECT digest, operation_id FROM aliases WHERE task_id=? AND call_id=?',
                               (claim.identity.task_id, call_id)).fetchone()
            if alias:
                if alias[0] != digest:
                    raise ValueError('A call ID cannot be reused for another write')
                if alias[1] is None:
                    return None, WriteOutcome('blocked', None, True)
                row = db.execute('SELECT operation_id, state, active FROM operations WHERE operation_id=?',
                                 (alias[1],)).fetchone()
                return None, self._outcome(row, True)
            row = db.execute('SELECT operation_id, state, active FROM operations WHERE digest=?', (digest,)).fetchone()
            if row:
                db.execute('INSERT INTO aliases VALUES (?, ?, ?, ?)',
                           (claim.identity.task_id, call_id, digest, row[0]))
                return None, self._outcome(row, True)
            resources = _resources(tool, args)
            conflict = any(db.execute('SELECT 1 FROM resources WHERE resource=?', (key,)).fetchone()
                           for key in resources)
            if conflict:
                # Consume this call but disclose neither the foreign task nor
                # its owner/payload/operation. Retrying it will not start later.
                db.execute('INSERT INTO aliases VALUES (?, ?, ?, NULL)',
                           (claim.identity.task_id, call_id, digest))
                return None, WriteOutcome('blocked', None)
            operation_id = str(uuid.uuid4())
            db.execute("INSERT INTO operations VALUES (?, ?, 'reserved', 1)", (operation_id, digest))
            db.execute('INSERT INTO aliases VALUES (?, ?, ?, ?)',
                       (claim.identity.task_id, call_id, digest, operation_id))
            db.executemany('INSERT INTO resources VALUES (?, ?)', ((key, operation_id) for key in resources))
            return operation_id, None

    def _start_commit(self, claim, operation_id):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._admit(db, claim)
            changed = db.execute("UPDATE operations SET state='committing' WHERE operation_id=? "
                                 "AND state='reserved' AND active=1", (operation_id,)).rowcount
            if changed != 1:
                raise RuntimeError('Write commit reservation is no longer valid')

    def _settle(self, operation_id, state, drained):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('UPDATE operations SET state=?, active=? WHERE operation_id=? '
                                 "AND state IN ('reserved','committing') AND active=1",
                                 (state, int(not drained), operation_id)).rowcount
            if changed != 1:
                raise RuntimeError('Write result cannot be overwritten')
            if drained and state in {'committed', 'rolled_back'}:
                db.execute('DELETE FROM resources WHERE operation_id=?', (operation_id,))

    def execute(self, claim, call_id, tool, arguments, *, transaction_factory):
        """Execute ONCE; no transaction factory is called for replay/conflict.

        The factory must return NativeWriteTransaction, not a model-selected
        callable. An uncertain operation holds its resources across ALL tasks.
        If close cannot prove drainage, the durable active marker remains set.
        """
        _claim(claim, self.site)
        if not isinstance(call_id, str) or not CALL_ID.fullmatch(call_id) or not callable(transaction_factory):
            raise ValueError('Invalid write call or trusted transaction factory')
        args = _arguments(tool, arguments)
        self._authorize(claim, tool, args)
        operation_id, replay = self._reserve(claim, call_id, tool, args)
        if replay is not None:
            self.require_delivery(claim, tool, args)
            return replay
        transaction = None
        begin_attempted = commit_started = committed = rolled_back = drained = False
        interrupt = None
        try:
            trusted = {'operation_id': operation_id} if tool == 'recipe_save' else {}
            transaction = transaction_factory(claim, tool, json.loads(json.dumps(args)), **trusted)
            begin = transaction.begin
            if not callable(begin):
                raise TypeError('Trusted transaction must provide begin')
            begin_attempted = True
            begin()
            self.require_delivery(claim, tool, args)
            transaction.save()
            self.require_delivery(claim, tool, args)
            self._start_commit(claim, operation_id)
            commit_started = True
            transaction.commit()
            committed = True
        except BaseException as error:
            if not begin_attempted:
                # This proof comes from OUR control flow and the fixed trusted
                # construction-only factory contract, not an exception string
                # or an adapter's claimed timeout. No DB stage was invoked.
                rolled_back = True
            elif transaction is not None:
                try:
                    rolled_back = transaction.rollback() is True and not commit_started
                except BaseException as rollback_error:
                    rolled_back = False
                    if not isinstance(rollback_error, Exception):
                        interrupt = rollback_error
            if not isinstance(error, Exception):
                interrupt = error
        finally:
            if not begin_attempted:
                drained = True
            elif transaction is not None:
                try:
                    drained = transaction.close() is True
                except BaseException as error:
                    if not isinstance(error, Exception):
                        interrupt = error
            state = 'committed' if committed else 'rolled_back' if rolled_back else 'uncertain'
            # If this persistence fails, reserved/committing+active survives.
            # Do not invent a receipt or clear its fence in an exception path.
            self._settle(operation_id, state, drained)
        if interrupt is not None:
            raise interrupt
        return WriteOutcome(state, operation_id, active=not drained)

    def observe(self, identity, claim_id):
        """Trusted status only, no student data and no time-based recovery."""
        _identity(identity, self.site)
        _uuid(claim_id)
        with self._connect() as db:
            # Consistent gate + operation snapshot even during finish/cancel.
            db.execute('BEGIN')
            row = self._task(db, identity, claim_id)
            if not row:
                return HostWriteObservation(identity, claim_id, False, False, 0, 0, 0)
            operations = db.execute('SELECT DISTINCT o.operation_id, o.state, o.active FROM operations o '
                                    'JOIN aliases a ON a.operation_id=o.operation_id WHERE a.task_id=?',
                                    (identity.task_id,)).fetchall()
            return HostWriteObservation(identity, claim_id, True, bool(row[3]),
                                        sum(item[2] for item in operations),
                                        sum(item[1] == 'uncertain' for item in operations), len(operations))

    def observer(self, native_observer):
        """Inject into store.observe_execution in worker AND fresh web contexts."""
        def observe(identity, claim_id):
            native = native_observer(identity, claim_id)
            return combine_execution(native, self.observe(identity, claim_id))
        return observe


def combine_execution(native, host):
    """Never promote an OS state; never certify success from an uncertain write.

    An absent/open host gate is unknown, not zero completed writes. Permanent
    native no-start seals are usable only with a closed, empty host gate. Apply
    this composition to seal_execution responses too; do not bypass it when a
    fresh web process cancels a task before the worker has opened its gate.
    """
    if (not isinstance(native, ExecutionObservation) or not isinstance(host, HostWriteObservation)
            or native.claim_id != host.claim_id
            or native.state not in {'running', 'exited', 'unknown', 'never_started_and_sealed'}
            or type(native.active_writes) is not int or native.active_writes < 0
            or type(native.turn_completed) is not bool or type(native.lease_closed) is not bool
            or (native.exit_code is not None and type(native.exit_code) is not int)
            or type(host.registered) is not bool or type(host.admission_closed) is not bool
            or any(type(value) is not int or value < 0 for value in (
                host.active_writes, host.uncertain_writes, host.operations))
            or host.active_writes > host.operations or host.uncertain_writes > host.operations
            or not host.registered and (host.admission_closed or host.operations)):
        raise ValueError('Invalid host/native execution evidence')
    if native.state == 'never_started_and_sealed' and (
            native.active_writes or native.exit_code is not None or native.turn_completed or not native.lease_closed):
        raise ValueError('Invalid native never-started proof')
    active = native.active_writes + host.active_writes
    if (not host.registered or not host.admission_closed
            or native.state == 'never_started_and_sealed' and host.operations):
        return replace(native, state='running' if native.state == 'running' else 'unknown',
                       active_writes=active, turn_completed=False)
    return replace(native, active_writes=active,
                   turn_completed=native.turn_completed and not host.uncertain_writes)


def _recipe_readback(site, operation_id, args, readback):
    """Validate the exact reserved target and page scope, not a match by week.

    The trusted RecipeWriteAdapter registers native aggregate source authority
    before returning and publishes its own finite view. A single returned page
    is usable display data, never an assertion that the full week was verified.
    """
    from tongjianyun.business_agent_recipes import write_plan, week_bounds
    plan = write_plan(site, operation_id, args)
    start, end = week_bounds(args['day'])
    metadata = args['payload']['recipe']
    selection = {'view': 'recipe_week', 'day': args['day'], 'meal': 'lunch'}
    if (type(readback) is not dict or readback.get('recipe') != plan.target_recipe
            or readback.get('operation_id') != plan.operation_id or readback.get('day') != args['day']
            or readback.get('calendar_week_start') != start or readback.get('calendar_week_end') != end
            or readback.get('week_start') != metadata['weekStart'] or readback.get('week_end') != metadata['weekEnd']
            or readback.get('visible_recipe_found') is not True or readback.get('selection') != selection):
        raise ValueError('Fresh recipe readback is outside the reserved target/scope')
    rows, total, count = readback.get('dishes'), readback.get('dish_count'), readback.get('page_count')
    more, complete = readback.get('has_more'), readback.get('complete')
    if (type(rows) is not list or type(total) is not int or type(count) is not int
            or not 0 <= count <= total <= 10000 or count != len(rows)
            or type(readback.get('offset')) is not int or readback['offset'] != 0
            or type(more) is not bool or type(complete) is not bool
            or more != (count < total) or complete != (not more)
            or more and (count == 0 or type(readback.get('next_offset')) is not int or readback['next_offset'] != count)
            or not more and readback.get('next_offset') is not None):
        raise ValueError('Fresh recipe page cannot certify complete-week readback')
    return selection, complete


class BusinessWrites:
    """Finite worker adapter; framework-native callbacks are mandatory.

    fresh_read runs AFTER execute's write connection has closed, in a NEW
    connection via authority.read_attendance/read_meals or the native recipe
    aggregate reader. It must register the
    complete source read-set. publish_view must register view authority before
    emitting a selection, never embed a stale student snapshot in a view event.
    Neither callback is selected by a model. Clear natural-language writes do
    not require another approval; meal.confirm is the original business state.
    Recipe callbacks receive the ledger's immutable operation_id keyword even
    for cross-task replay. Recipe fresh_read already publishes its authorized
    selection; this layer validates it without emitting a duplicate view event.
    """
    def __init__(self, ledger, *, transaction_factory, fresh_read, publish_view):
        if not isinstance(ledger, BusinessWriteLedger) or not all(callable(callback) for callback in (
                transaction_factory, fresh_read, publish_view)):
            raise ValueError('Trusted business write callbacks are required')
        self.ledger, self.transaction_factory = ledger, transaction_factory
        self.fresh_read, self.publish_view = fresh_read, publish_view

    def dispatch(self, claim, tool, arguments, call_id):
        args = _arguments(tool, arguments)
        outcome = self.ledger.execute(claim, call_id, tool, args, transaction_factory=self.transaction_factory)
        result = {'status': outcome.status, 'operation_id': outcome.operation_id, 'replayed': outcome.replayed,
                  'committed': True if outcome.status == 'committed' else False if outcome.status == 'rolled_back' else None,
                  'retry_allowed': False, 'readback_available': False, 'host_write_active': outcome.active}
        if tool == 'recipe_save':
            result['readback_complete'] = False
        if outcome.status != 'committed' or outcome.active:
            return result
        self.ledger.require_delivery(claim, tool, args)
        try:
            trusted = {'operation_id': outcome.operation_id} if tool == 'recipe_save' else {}
            readback = self.fresh_read(claim, tool, json.loads(json.dumps(args)), **trusted)
            if tool == 'recipe_save':
                selection, complete = _recipe_readback(self.ledger.site, outcome.operation_id, args, readback)
            elif type(readback) is not dict or readback.get('group') != args['group'] or readback.get('day') != args['day']:
                raise ValueError('Fresh business readback is for another target')
        except Exception:
            # A commit receipt is not undone by a read failure. Recheck access
            # and return no stored names, old results, or suggestion to rewrite.
            self.ledger.require_delivery(claim, tool, args)
            return result
        self.ledger.require_delivery(claim, tool, args)
        if tool == 'recipe_save':
            return {**result, 'readback_available': True, 'readback_complete': complete,
                    'readback': readback, 'selection': selection}
        selection = {'view': 'classroom_day' if tool == 'attendance_save' else 'meal_counts',
                     'group': args['group'], 'day': args['day']}
        if tool == 'meal_save':
            selection['meal'] = args['meal']
        self.publish_view(claim, selection)
        self.ledger.require_delivery(claim, tool, args)
        return {**result, 'readback_available': True, 'readback': readback, 'selection': selection}
