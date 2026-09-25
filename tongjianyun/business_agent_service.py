"""Authenticated web/queue wiring for the isolated business agent.

No task is accepted until the fixed native launcher responds to a readiness
handshake. Merely setting business_codex_enabled never installs that launcher.
The original administrator meal_chat path is not a fallback. The RQ worker and
web service use the site OS identity, not root, and share a private durable store.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import stat
import time

import frappe

from tongjianyun.business_agent_authority import FreshFrappeChecks, FrappeBusinessAuthority
from tongjianyun.business_agent_tasks import BusinessTaskStore, TaskIdentity, QueueObservation, QUEUE
from tongjianyun.business_agent_transport import private_directory

WORKER_METHOD = 'tongjianyun.business_agent_service.run_task'
MODEL_KEY_PATH = Path('/home/zyd/frappe/.codex-deepseek/private/api-key')


@contextmanager
def submission_lock(directory, owner):
    """OS-held owner lock: worker/web crashes release it; no expiring lease."""
    import fcntl  # This deployment is Linux; no unlocked fallback.
    folder = private_directory(directory)
    name = 'submit-' + hashlib.sha256(owner.encode()).hexdigest() + '.lock'
    fd = os.open(folder / name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise PermissionError('Submission lock is not private')
        deadline = time.monotonic() + 3
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ValueError('Another submission is still being accepted')
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)


def _model_key():
    """Fixed deployment credential, kept solely in the trusted model proxy."""
    path = MODEL_KEY_PATH
    if path.resolve(strict=True) != path:
        raise PermissionError('Unsafe model credential path')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or not 20 <= info.st_size <= 512):
            raise PermissionError('Unsafe model credential')
        raw = os.read(fd, 513)
        if len(raw) != info.st_size:
            raise PermissionError('Unstable model credential')
    finally:
        os.close(fd)
    value = raw.decode('ascii').strip()
    if not 20 <= len(value) <= 512 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise PermissionError('Invalid model credential')
    return value


class FrappeBusinessQueue:
    def __init__(self, site):
        self.site = site

    def _context(self):
        if frappe.local.site != self.site:
            raise PermissionError('Queue site context changed')

    def observe(self, job_id):
        """Network failures are unknown; never an excuse to start another job."""
        self._context()
        try:
            from frappe.utils.background_jobs import get_job
            job = get_job(job_id)
            if job is None:
                return QueueObservation(job_id, 'absent')
            status = job.get_status(refresh=True)
            status = getattr(status, 'value', status)
            if status in {'queued', 'started', 'deferred', 'scheduled'}:
                state = 'present'
            elif status in {'finished', 'failed', 'stopped', 'canceled'}:
                # Core still refuses replay after ANY worker claim. Terminal
                # RQ jobs may only be redelivered if they never claimed a task.
                state = 'absent'
            else:
                state = 'unknown'
            return QueueObservation(job_id, state)
        except Exception:
            return QueueObservation(job_id, 'unknown')

    def ready(self):
        """Admission health hint, never task-exit or cancellation evidence."""
        self._context()
        try:
            from rq import Worker
            from frappe.utils.background_jobs import get_queue
            queue = get_queue(QUEUE)
            for worker in Worker.all(queue=queue):
                stamp = worker.last_heartbeat
                if isinstance(stamp, datetime):
                    stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
                    age = (datetime.now(timezone.utc) - stamp).total_seconds()
                    if 0 <= age <= 120 and worker.get_state() in {'idle', 'busy'} and queue.name in worker.queue_names():
                        return True
        except Exception:
            pass
        return False

    def enqueue(self, ticket):
        self._context()
        if ticket.queue != QUEUE or ticket.identity.site != self.site:
            raise PermissionError('Invalid business queue dispatch')
        return frappe.enqueue(WORKER_METHOD, queue=QUEUE, timeout=-1, is_async=True,
            enqueue_after_commit=False, deduplicate=True, retry=None, job_id=ticket.job_id,
            owner=ticket.identity.owner, task_id=ticket.identity.task_id)


class BusinessChatApplication:
    """Transport-independent application; identity comes from a trusted Viewer."""
    def __init__(self, store, authority, queue, *, lock=submission_lock):
        if store.site != authority.site or store.site != queue.site:
            raise PermissionError('Business application site mismatch')
        self.store, self.authority, self.queue, self.lock = store, authority, queue, lock

    def viewer(self):
        return self.authority.capture_viewer()

    def _viewer(self, viewer):
        if not self.authority.viewer_active(viewer):
            raise PermissionError('Browser session is no longer active')

    def identity(self, viewer, task_id):
        self._viewer(viewer)
        return TaskIdentity(self.store.site, viewer.owner, task_id)

    def submit(self, viewer, request_id, message, context):
        identity = self.identity(viewer, request_id)
        scopes = self.authority.view_scopes(identity, context['selection']) if 'selection' in context else ()
        with self.lock(self.store.directory, viewer.owner):
            # An identical id must retain the ORIGINAL payload digest, even if
            # another task is active. Never accept an id for a different request.
            existing = self.store.find_task(identity)
            active = self.store.active_task(viewer.owner)
            if not existing and active:
                return {'accepted': False, 'task_id': active['task_id'], 'status': active['status']}
            result = self.store.create(viewer.owner, request_id, message, context, authority_scopes=scopes)
            self._viewer(viewer)
            # Dispatching/acknowledged jobs are reconciled against the real RQ
            # entry. No timeout, heartbeat-age or HTTP-response retry assumption.
            delivery = self._dispatch(identity)
            return {'accepted': True, 'task_id': request_id, 'status': result['status'], 'delivery': delivery}

    def _dispatch(self, identity):
        self.store.recover_dispatch(identity)
        ticket = self.store.take_dispatch(identity)
        if ticket:
            try:
                self.queue.enqueue(ticket)
                self.store.acknowledge_dispatch(ticket)
            except Exception:
                # Queue response may have been lost AFTER enqueue. Preserve
                # outbox state; a network retry cannot become another task.
                return 'unconfirmed'
        return 'recorded'

    def retry_dispatch(self, viewer, task_id):
        identity = self.identity(viewer, task_id)
        with self.lock(self.store.directory, viewer.owner):
            task = self.store.task(identity)
            delivery = self._dispatch(identity) if task['status'] == 'queued' else 'recorded'
            return {'task_id': task_id, 'status': task['status'], 'delivery': delivery}

    def event_page(self, viewer, task_id, after='0'):
        identity = self.identity(viewer, task_id)
        self._reconcile(identity)
        events = self.store.events(identity, after, limit=100)
        self._viewer(viewer)
        return {'task_id': task_id, 'events': events,
                'next_after': events[-1]['id'] if len(events) == 100 else None}

    def _reconcile(self, identity):
        try:
            self.store.reconcile(identity)
        except Exception:
            # Observation unavailable is not execution absence. Preserve the
            # active task and still permit its authenticated cancellation.
            pass

    def conversation(self, viewer, before=None):
        self._viewer(viewer)
        history = self.store.history(viewer.owner, before=before, limit=20)
        result = []
        for task in reversed(history['tasks']):
            page = self.event_page(viewer, task['task_id'])
            task = self.store.task(TaskIdentity(self.store.site, viewer.owner, task['task_id']))
            context = task['context']
            result.append({**task, **page, 'day': context.get('day'), 'meal': context.get('meal'), 'file_name': ''})
        self._viewer(viewer)
        return {'mode': 'business', 'tasks': result, 'next_before': history['next_before']}

    def cancel(self, viewer, task_id):
        identity = self.identity(viewer, task_id)
        status = self.store.cancel(identity)
        self._reconcile(identity)
        status = self.store.task(identity)['status']
        return {'task_id': task_id, 'status': status}

    def stream(self, viewer, task_id, after='0'):
        identity = self.identity(viewer, task_id)
        self.store.events(identity, after, limit=1)  # Validate BEFORE HTTP 200.
        self._reconcile(identity)
        source = self.store.stream(identity, after, authorize_viewer=lambda task: self.authority.viewer_active(viewer, task))
        def events():
            try:
                for frame in source:
                    yield frame
                    if frame.startswith(': heartbeat'):
                        self._reconcile(identity)
            finally:
                source.close()  # Browser disconnect never cancels execution.
        return events()


def _configured_runtime():
    from tongjianyun.business_agent_worker import UnixLauncherRuntime
    site = frappe.local.site
    sites_path = str(Path(frappe.local.sites_path).resolve(strict=True))
    return UnixLauncherRuntime(site=site, sites_path=sites_path)


def _enabled():
    value = frappe.conf.get('business_codex_enabled')
    return type(value) in (bool, int) and value == 1


def available():
    """Readiness hint only. Every mutating request checks again independently."""
    if not _enabled():
        return False
    try:
        runtime = _configured_runtime()
        return runtime.ready() is True and FrappeBusinessQueue(frappe.local.site).ready() and bool(_model_key())
    except Exception:
        return False


def chat_access():
    """History/cancel remain reachable while the executor is offline/disabled."""
    try:
        sites = Path(frappe.local.sites_path).resolve(strict=True)
        directory = private_directory(sites / frappe.local.site / 'private' / 'business-codex' / 'tasks')
        path = directory / 'business-tasks.sqlite3'
        info = path.lstat()
        allowed = (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                   and info.st_uid == os.geteuid() and not info.st_mode & 0o077)
    except Exception:
        allowed = False
    can_submit = allowed and available()
    return {'allowed': allowed, 'can_submit': can_submit,
            'reason': '' if can_submit else '后台助手暂不可用，仍可查看已有记录或停止任务。' if allowed
            else '当前账号的业务对话尚未开通，可先在左侧办理已有权限的业务。'}


def application(*, require_ready=False):
    if require_ready and not _enabled():
        raise PermissionError('Business Codex is not enabled')
    runtime = _configured_runtime()
    if require_ready and runtime.ready() is not True:
        raise PermissionError('Isolated business runtime is unavailable')
    if require_ready:
        _model_key()  # Never retain or disclose this secret in tasks.
    site, sites_path = frappe.local.site, str(Path(frappe.local.sites_path).resolve(strict=True))
    directory = Path(sites_path) / site / 'private' / 'business-codex' / 'tasks'
    # Deployment creates this 0700 path as the site owner. A request cannot
    # provision filesystem roots, choose a path or silently fix bad permissions.
    private_directory(directory)
    authority = FrappeBusinessAuthority(site, run_check=FreshFrappeChecks(site, sites_path))
    queue = FrappeBusinessQueue(site)
    if require_ready and not queue.ready():
        raise PermissionError('Business queue worker is unavailable')
    store = BusinessTaskStore(directory, site, authorize=authority,
                              observe_execution=runtime.observe, observe_queue=queue.observe,
                              seal_execution=runtime.seal_before_start)
    return BusinessChatApplication(store, authority, queue), runtime


def run_task(owner, task_id):
    """RQ-only entry (NOT whitelisted); native RQ fixes site/user before this."""
    from rq import get_current_job
    from frappe.utils.background_jobs import create_job_id
    from tongjianyun.business_agent_worker import BusinessWorker
    from tongjianyun.business_agent_reads import BusinessReads
    app, runtime = application(require_ready=True)
    identity = TaskIdentity(app.store.site, owner, task_id)
    job = get_current_job()
    if (job is None or job.id != create_job_id(app.store.job_id(identity))
            or frappe.session.user != owner):
        raise PermissionError('Trusted business queue identity is required')
    worker = BusinessWorker(app.store, runtime,
        read_attendance=lambda claim, **args: app.authority.read_attendance(app.store, claim, **args),
        read_tools=BusinessReads(app.authority, app.store).dispatch,
        model_key=_model_key)
    return worker.run(identity, app.store.job_id(identity))
