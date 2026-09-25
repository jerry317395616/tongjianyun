"""Fresh owner-bound native transactions for the business write ledger.

Trusted deployment code constructs FrappeWriteAdapter with the fixed site and
sites directory. The model never chooses an actor, connection, Python method,
SQL, permission bypass, or transaction instruction. This module is not an RPC.

Use adapter.transaction_factory / adapter.authorize / adapter.fresh_read with
BusinessWriteLedger and BusinessWrites. A factory constructs without opening a
connection. begin/save/commit/rollback/close then run synchronously on the same
host thread in one EMPTY Context(), not the request/RQ connection. The original
classroom services retain all revision, roster, scope, date, lock and change-
reason checks. Their small save receipt is NOT evidence that commit succeeded.

Only the ledger's durable commit ACK is a commit receipt. A commit exception is
unknown even if closing a connection succeeds. rollback never claims to undo an
attempted commit. Close proves host connection drainage, not business rollback.
The ledger owns cross-task fences, retries, cancellation and delivery decisions.

Readback runs AFTER close, through a different authority fresh context and its
complete same-query source registration. No student snapshot is stored in this
write transaction or returned from save. This adapter has no administrator
fallback and creates no additional approval step for clear user instructions.
"""
from __future__ import annotations

from collections import defaultdict
from contextvars import Context
import threading
from typing import Callable

import frappe

from tongjianyun.business_agent_authority import FreshFrappeChecks, FrappeBusinessAuthority, _identity, _account
from tongjianyun.business_agent_tasks import WorkerClaim
from tongjianyun.business_agent_tools import BusinessBinding, _validate_arguments, validate_binding


WRITE_TOOLS = frozenset({'attendance_save', 'meal_save'})


def _arguments(tool, arguments):
    if not isinstance(tool, str) or tool not in WRITE_TOOLS:
        raise ValueError('Only registered native business writes are available')
    return _validate_arguments(tool, arguments)


def _selection(tool, args):
    choice = {'view': 'classroom_day' if tool == 'attendance_save' else 'meal_counts',
              'group': args['group'], 'day': args['day']}
    if tool == 'meal_save':
        choice['meal'] = args['meal']
    return choice


class FrappeWriteAdapter:
    """Concrete callbacks; the store and its worker claim are trusted objects.

    A separate authority is deliberately constructed with FreshFrappeChecks,
    rather than allowing a read callback to reuse the write transaction. The
    optional configuration guard is trusted deployment/QA code, never payload.
    """
    def __init__(self, site, sites_path, *, store, before_connect: Callable | None = None):
        checks = FreshFrappeChecks(site, sites_path, before_connect=before_connect)
        if (getattr(store, 'site', None) != site or not callable(getattr(store, 'binding_state', None))):
            raise ValueError('The fixed-site business task store is required')
        self.site, self.sites_path = checks.site, checks.sites_path
        self.store, self.before_connect = store, before_connect
        self.authority = FrappeBusinessAuthority(site, run_check=checks)
        self._transactions = set()
        self._lock = threading.RLock()

    def _claim(self, claim):
        if not isinstance(claim, WorkerClaim):
            raise frappe.PermissionError('A trusted business worker claim is required')
        _identity(claim.identity, self.site)
        # Administrator has its own project workflow. This ordinary-business
        # adapter must never be usable as a privileged fallback.
        if claim.identity.owner == 'Administrator':
            raise frappe.PermissionError('Administrator project execution is not a business write fallback')

    def _state(self, claim):
        self._claim(claim)
        state = self.store.binding_state(claim)  # exact token + current complete task scopes
        expected = {'owner': claim.identity.owner, 'site': self.site,
                    'task_id': claim.identity.task_id, 'mode': 'business', 'status': 'running'}
        if (not isinstance(state, dict) or any(state.get(key) != value for key, value in expected.items())
                or 'cancel_requested' not in state or state['cancel_requested'] not in (False, 0, '0')):
            raise frappe.PermissionError('Business task is no longer active')
        return state

    def authorize(self, claim, tool, arguments):
        """Fresh ledger gate, including replay; no business data is returned.

        Original service permissions remain decisive for writes. In particular,
        class read permission is not converted into generic DocType write rights.
        The trusted task store also rechecks every previously registered source.
        """
        args = _arguments(tool, arguments)
        self._state(claim)
        self.authority.view_scopes(claim.identity, _selection(tool, args))
        def native_capability():
            from tongjianyun import classroom
            _account(claim.identity.owner, self.site)
            group = classroom._scope(args['group'])
            day = classroom._day(args['day'])
            capability = 'attendance_write' if tool == 'attendance_save' else 'meals_write'
            if classroom._capabilities(day).get(capability) is not True:
                raise frappe.PermissionError('Current native business write capability is unavailable')
            if tool == 'meal_save':
                from tongjianyun import student_meals
                student_meals._editor(group.name)
                name = student_meals.record_name(args['day'], group.name)
                if frappe.db.exists(student_meals.DOCTYPE, name):
                    frappe.get_doc(student_meals.DOCTYPE, name).check_permission('write')
                else:
                    frappe.has_permission(student_meals.DOCTYPE, 'create', throw=True)
        self.authority.run_check(claim.identity.owner, native_capability)
        self._state(claim)
        return True

    def transaction_factory(self, claim, tool, arguments):
        """Ledger contract: pure construction, no DB or task-store read yet."""
        self._claim(claim)
        transaction = NativeWriteTransaction(self, claim, tool, _arguments(tool, arguments))
        with self._lock:
            self._transactions.add(transaction)
        return transaction

    def _closed(self, transaction):
        with self._lock:
            self._transactions.discard(transaction)

    def fresh_read(self, claim, tool, arguments):
        """Separate post-close read; exceptions never reinterpret the commit.

        BusinessWrites invokes this only after a committed, drained outcome;
        it handles failed/revoked readback without repeating the saved operation.
        The same callback is used for receipt replay, never a saved pupil cache.
        """
        args = _arguments(tool, arguments)
        self.authorize(claim, tool, args)
        with self._lock:
            if any(tx.claim == claim for tx in self._transactions):
                raise RuntimeError('Write contexts must drain before business readback')
        reader = self.authority.read_attendance if tool == 'attendance_save' else self.authority.read_meals
        result = reader(self.store, claim, group=args['group'], day=args['day'])
        self.authorize(claim, tool, args)
        return result


class NativeWriteTransaction:
    """One synchronous, never-retried native transaction; created by the adapter."""
    def __init__(self, adapter, claim, tool, arguments):
        self.adapter, self.claim, self.tool, self._arguments = adapter, claim, tool, arguments
        self._context = Context()
        self._thread = None
        self._database = None
        self._initialised = False
        self._closed = False
        self._phase = 'new'
        self._commit_attempted = False
        self._lock = threading.RLock()
        self._binding = BusinessBinding(claim.identity.owner, adapter.site, claim.identity.task_id,
                                        lambda task_id: adapter._state(claim))

    def _on_thread(self):
        if self._thread is not None and threading.get_ident() != self._thread:
            raise RuntimeError('Native write lifecycle must stay on its owner thread')
        if self._closed:
            raise RuntimeError('Native write context is closed')

    def _guard(self):
        if (getattr(frappe.local, 'site', None) != self.adapter.site
                or frappe.session.user != self.claim.identity.owner
                or getattr(frappe.local, 'db', None) is not self._database):
            raise frappe.PermissionError('Native write lost its fixed actor, site or connection')
        frappe.local.request_cache = defaultdict(dict)
        self.adapter.authorize(self.claim, self.tool, self._arguments)
        # Locking current read prevents a REPEATABLE READ snapshot from making
        # an already-disabled account look enabled. Held through commit/rollback.
        validate_binding(self._binding, lock_owner=True)

    def begin(self):
        with self._lock:
            self._on_thread()
            if self._phase != 'new':
                raise RuntimeError('Native write has already begun')
            self._thread, self._phase = threading.get_ident(), 'beginning'
            def open_context():
                self._initialised = True  # even partially failed init needs destroy
                frappe.init(self.adapter.site, sites_path=self.adapter.sites_path)
                if self.adapter.before_connect:
                    self.adapter.before_connect()
                if getattr(frappe.local, 'site', None) != self.adapter.site:
                    raise frappe.PermissionError('Native write site changed before connection')
                frappe.connect(set_admin_as_user=False)
                self._database = frappe.local.db
                frappe.set_user(self.claim.identity.owner)
                self._guard()
            self._context.run(open_context)
            self._phase = 'begun'

    def save(self):
        with self._lock:
            self._on_thread()
            if self._phase != 'begun':
                raise RuntimeError('Native save requires one fresh, unsaved transaction')
            self._phase = 'saving'
            def save_native():
                from tongjianyun import classroom
                self._guard()
                args = self._arguments
                if self.tool == 'attendance_save':
                    receipt = classroom.save_attendance(args['group'], args['day'], args['changes'], args['revision'])
                    valid = type(receipt) is dict and set(receipt) == {'saved'} and type(receipt['saved']) is int
                    valid = valid and receipt['saved'] == len(args['changes'])
                else:
                    receipt = classroom.save_meal(args['group'], args['day'], args['meal'], args['students'],
                                                  args['revision'], int(args['confirm']), args.get('change_reason', ''))
                    valid = type(receipt) is dict and set(receipt) == {'saved'} and receipt['saved'] is True
                if not valid:
                    raise RuntimeError('Original service did not return its bounded save receipt')
                return dict(receipt)
            try:
                receipt = self._context.run(save_native)
            except BaseException:
                self._phase = 'save_failed'
                raise
            self._phase = 'saved'
            return receipt  # pending commit, not a delivered pupil snapshot

    def commit(self):
        with self._lock:
            self._on_thread()
            if self._phase != 'saved':
                raise RuntimeError('Only one successful native save may be committed')
            def commit_native():
                self._guard()
                self._commit_attempted, self._phase = True, 'committing'
                self._database.commit()
            try:
                self._context.run(commit_native)
            except BaseException:
                if self._commit_attempted:
                    self._phase = 'uncertain'
                raise
            self._phase = 'committed'

    def rollback(self):
        with self._lock:
            self._on_thread()
            if self._commit_attempted:
                return False  # connection cleanup cannot undo/clarify an unknown commit
            if self._phase == 'rolled_back':
                return True
            try:
                if self._database is not None:
                    self._context.run(self._database.rollback)
            except Exception:
                self._phase = 'rollback_failed'
                return False
            self._phase = 'rolled_back'
            return True

    def close(self):
        with self._lock:
            if self._closed:
                return True
            self._on_thread()
            def destroy():
                # Close the exact owned DB even if a broken callback replaced
                # framework local.db. Then destroy only this isolated Context.
                if self._database is not None:
                    self._database.close()
                if self._initialised:
                    frappe.destroy()
            try:
                self._context.run(destroy)
            except Exception:
                return False  # ledger retains host-active evidence; no invented drainage
            self._closed = True
            self.adapter._closed(self)
            return True
