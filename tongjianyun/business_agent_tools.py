"""Narrow business tools for a separately isolated, task-bound Codex runner.

This is NOT an HTTP whitelist or an operating-system isolation boundary. Only
the trusted broker constructs BusinessBinding after authenticating its runner.
The model supplies a tool name and finite JSON arguments, never a site, actor,
Python method, SQL, file path, permission bypass or transaction instruction.

Writes require a durable external execute_write callback. Its contract is:
reserve (site, owner, task_id, call_id, digest) before operation; never rerun an
in-flight/uncertain intent (including a new call_id with the same digest); run
operation and validate_binding again before commit; commit/rollback itself;
persist the outcome before responding. A crash between commit and recording the
outcome is UNCERTAIN, not permission to retry. Revision changes distinguish
legitimate subsequent edits. This module never commits or rolls back.

publish_view(binding, event) must atomically revalidate live task ownership and
append the selection-only event. Browser reads the view again as its own user.
It must not reuse the administrator/root-runner publishing endpoint.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Any

import frappe


MEALS = frozenset({'breakfast', 'morning_snack', 'lunch', 'afternoon_snack', 'dinner'})
VIEW_FIELDS = {
    'students': {'presentation'},
    'class_students': {'group', 'offset'},
    'classroom_day': {'group', 'offset'},
    'meal_counts': {'group'},
    'frappe_catalog': {'app', 'module', 'kind', 'keyword', 'offset'},
    'frappe_doctype': {'doctype'},
    'frappe_document': {'doctype', 'document'},
    'frappe_new': {'doctype'},
    'business_proposal': {'proposal_id', 'revision'},
}
MAX_ARGUMENT_BYTES = 128 * 1024
MAX_ROSTER = 500
_ID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')


@dataclass(frozen=True)
class WriteOutcome:
    status: str  # committed or uncertain; never inferred from operation returning
    result: dict | None = None
    replayed: bool = False


@dataclass(frozen=True)
class BusinessBinding:
    owner: str
    site: str
    task_id: str
    read_task: Callable[[str], Mapping]
    publish_view: Callable[['BusinessBinding', dict], Any] | None = None
    execute_write: Callable[['BusinessBinding', str, str, Callable], WriteOutcome] | None = None
    call_id: str | None = None


def _denied(message):
    raise frappe.PermissionError(message)


def validate_binding(binding: BusinessBinding, *, lock_owner=False):
    """Public pre-operation/pre-commit guard for the trusted write executor.

read_task must return a fresh task_id/owner/site/mode/status/cancel_requested.
    This performs the account check against the bound owner, not the ambient actor.
    A trusted write executor passes lock_owner=True: native SELECT FOR UPDATE
    reads current User state even under REPEATABLE READ and retains the account
    lock until the caller's commit/rollback. Cancellation is checked before each
    stage, not a promise to undo a write that has already committed.
"""
    if not isinstance(binding, BusinessBinding):
        _denied('Business task binding is required')
    if (not isinstance(binding.owner, str) or not 1 <= len(binding.owner) <= 140
            or binding.owner == 'Guest' or not isinstance(binding.site, str)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', binding.site)
            or not isinstance(binding.task_id, str) or not _ID.fullmatch(binding.task_id)
            or not callable(binding.read_task)):
        _denied('Invalid business task binding')
    if getattr(frappe.local, 'site', None) != binding.site:
        _denied('Business task site mismatch')
    task = binding.read_task(binding.task_id)
    if (not isinstance(task, Mapping)
            or any(task.get(key) != value for key, value in {
                'task_id': binding.task_id, 'owner': binding.owner, 'site': binding.site,
                'mode': 'business', 'status': 'running',
            }.items())
            or 'cancel_requested' not in task
            or task['cancel_requested'] not in (False, 0, '0')):
        _denied('Business task is no longer active or its binding changed')
    if type(lock_owner) is not bool:
        raise ValueError('lock_owner must be boolean')
    options = {'for_update': True} if lock_owner else {}
    try:
        account = frappe.db.get_value('User', binding.owner, ['enabled', 'user_type'], as_dict=True, **options)
    except (frappe.QueryDeadlockError, frappe.QueryTimeoutError) as error:
        if not lock_owner:
            raise
        # MariaDB innodb_snapshot_isolation may reject a locking current read
        # with 1020 instead of returning the changed row. In either case an old
        # snapshot is not permission. The caller rolls back the whole operation;
        # never retry or roll back only a savepoint inside this authority check.
        raise frappe.PermissionError('Current account state could not be verified; operation refused') from error
    if not account or account.get('enabled') not in (True, 1) or account.get('user_type') != 'System User':
        _denied('Business task owner must be an enabled System User')
    # A privileged bootstrap/migration context must not taint ordinary tools.
    flags = getattr(frappe.local, 'flags', {}) or {}
    if any(flags.get(key) for key in ('ignore_permissions', 'in_install', 'in_migrate', 'in_patch')):
        _denied('Permission-bypassing framework context is not allowed')
    return task


@contextmanager
def _actor(binding):
    original = frappe.session.user
    old_cache = getattr(frappe.local, 'request_cache', None)
    try:
        frappe.set_user(binding.owner)
        # set_user does not clear this cache. Never reuse another actor's scope.
        frappe.local.request_cache = defaultdict(dict)
        yield
    finally:
        frappe.set_user(original)
        frappe.local.request_cache = old_cache


def _object(value, allowed, required=()):
    if type(value) is not dict or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError('Tool arguments have missing or unsupported keys')
    return value


def _text(value, key, maximum=140, empty=False):
    if (not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip())
            or any(ord(c) < 32 and c not in '\n\t' for c in value)):
        raise ValueError('Invalid ' + key)
    return value


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('day must be YYYY-MM-DD')
    date.fromisoformat(value)


def _common(args):
    if 'day' in args:
        _day(args['day'])
    if 'meal' in args and (not isinstance(args['meal'], str) or args['meal'] not in MEALS):
        raise ValueError('Invalid meal')
    if 'group' in args:
        _text(args['group'], 'group')


def _validate_arguments(tool, value):
    # Reject non-JSON and non-finite values before touching any business service.
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError('Tool arguments must be finite JSON') from exc
    if len(raw.encode('utf-8')) > MAX_ARGUMENT_BYTES:
        raise ValueError('Tool arguments are too large')
    if tool == 'scene_bootstrap':
        _object(value, {'day', 'meal', 'group'}, {'day'})
    elif tool == 'business_view':
        _object(value, {'selection', 'publish'}, {'selection'})
        choice = value['selection']
        if type(choice) is not dict or not isinstance(choice.get('view'), str) or choice['view'] not in VIEW_FIELDS:
            raise ValueError('Business view is not available to this tool')
        _object(choice, {'view', 'day', 'meal'} | VIEW_FIELDS[choice['view']], {'view'})
        _common(choice)
        for key in set(choice) - {'view', 'day', 'meal', 'offset'}:
            _text(choice[key], key)
        if 'offset' in choice and (type(choice['offset']) is not int or not 0 <= choice['offset'] <= 100000):
            raise ValueError('Invalid offset')
        if 'publish' in value and type(value['publish']) is not bool:
            raise ValueError('publish must be boolean')
    elif tool in {'classroom_read', 'meal_read'}:
        _object(value, {'group', 'day'}, {'group', 'day'})
    elif tool == 'attendance_save':
        _object(value, {'group', 'day', 'changes', 'revision'}, {'group', 'day', 'changes', 'revision'})
        if not isinstance(value['revision'], str) or not re.fullmatch(r'[a-f0-9]{64}', value['revision']):
            raise ValueError('A fresh attendance revision is required')
        _rows(value['changes'], 'attendance')
    elif tool == 'meal_save':
        _object(value, {'group', 'day', 'meal', 'students', 'revision', 'confirm', 'change_reason'},
                {'group', 'day', 'meal', 'students', 'revision', 'confirm'})
        _text(value['revision'], 'revision', maximum=64, empty=True)
        if type(value['confirm']) is not bool:
            raise ValueError('confirm must explicitly be boolean')
        if 'change_reason' in value:
            _text(value['change_reason'], 'change_reason', maximum=1000, empty=True)
        _rows(value['students'], 'meals')
    else:
        raise ValueError('Unknown business tool')
    _common(value)
    # Defensive copy: an untrusted caller cannot alter validated objects in flight.
    return json.loads(raw)


def _rows(rows, kind):
    if type(rows) is not list or not 1 <= len(rows) <= MAX_ROSTER:
        raise ValueError('A nonempty bounded roster is required')
    seen = set()
    for row in rows:
        keys = {'student', 'status', 'leave_reason'} if kind == 'attendance' else {'student', 'value'}
        required = {'student', 'status'} if kind == 'attendance' else keys
        _object(row, keys, required)
        _text(row['student'], 'student')
        if row['student'] in seen:
            raise ValueError('Duplicate student')
        seen.add(row['student'])
        if kind == 'attendance':
            if not isinstance(row['status'], str) or row['status'] not in {'Present', 'Absent', 'Leave'}:
                raise ValueError('Invalid attendance status')
            if 'leave_reason' in row:
                _text(row['leave_reason'], 'leave_reason', maximum=1000, empty=True)
            if row['status'] == 'Leave' and not row.get('leave_reason', '').strip():
                raise ValueError('Leave requires its actual reason')
        elif not isinstance(row['value'], str) or row['value'] not in {'就餐', '不就餐', '不供餐'}:
            raise ValueError('Invalid meal state')


def _classroom_read(args):
    from tongjianyun import classroom
    group = classroom._scope(args['group'])
    day = classroom._day(args['day'])
    # Do not call get_overview: unrelated health/log/schedule data is unnecessary.
    for doctype in ('Student Attendance', 'Student Leave Application'):
        frappe.has_permission(doctype, 'read', throw=True)
    result = classroom._attendance(group, day)
    return {'group': group.name, 'day': str(day), 'scope': '当前账号有权查看的本班有效名单',
            'revision': result['revision'], 'counts': result['counts'],
            'students': [{key: row.get(key) for key in ('student', 'student_name', 'status', 'source')}
                         for row in result['students']],
            'attendance_write': classroom._capabilities(day)['attendance_write']}


def _meal_read(args):
    from tongjianyun.classroom import get_meals
    result = get_meals(args['group'], args['day'])
    fields = ('student', 'student_name', *sorted(MEALS), *(meal + '_expected' for meal in sorted(MEALS)))
    return {'group': args['group'], 'day': args['day'], 'scope': '当前账号有权查看的本班餐次名单',
            'revision': result['revision'], 'meals': result['meals'],
            'students': [{key: row.get(key) for key in fields} for row in result['record'].get('students', [])]}


def _business_view(binding, args):
    from tongjianyun.meal_views import get_view
    result = get_view(args['selection'])
    validate_binding(binding)
    published = False
    if args.get('publish', True):
        if not callable(binding.publish_view):
            raise ValueError('A trusted view publisher is not configured')
        # No raw HTML, arbitrary URL, table rows or document body travels to SSE.
        event = {'kind': 'view', 'version': 1, 'selection': result['selection'], 'title': result['title']}
        binding.publish_view(binding, event)
        published = True
    return {'title': result['title'], 'selection': result['selection'], 'summary': result.get('summary', {}),
            'display_requested': published,
            'delivery': '已发送展示请求；浏览器仍需按当前用户权限重新读取。' if published else '仅查询，未发送展示请求。'}


def _write(binding, tool, args):
    if (not callable(binding.execute_write) or not isinstance(binding.call_id, str)
            or not _ID.fullmatch(binding.call_id)):
        raise ValueError('Writes require a trusted call id and durable write executor')
    digest = hashlib.sha256(json.dumps({'tool': tool, 'arguments': args}, sort_keys=True,
                                     ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()).hexdigest()

    def operation():
        from tongjianyun import classroom
        validate_binding(binding)
        if frappe.session.user != binding.owner:
            _denied('Write operation lost its bound actor')
        if tool == 'attendance_save':
            classroom.save_attendance(args['group'], args['day'], args['changes'], args['revision'])
            readback = _classroom_read(args)
            choice = {'view': 'classroom_day', 'group': args['group'], 'day': args['day']}
        else:
            classroom.save_meal(args['group'], args['day'], args['meal'], args['students'], args['revision'],
                                int(args['confirm']), args.get('change_reason', ''))
            readback = _meal_read(args)
            choice = {'view': 'meal_counts', 'group': args['group'], 'day': args['day'], 'meal': args['meal']}
        validate_binding(binding)
        return {'readback': readback, 'selection': choice, 'transaction': 'pending_commit'}

    outcome = binding.execute_write(binding, binding.call_id, digest, operation)
    if not isinstance(outcome, WriteOutcome) or outcome.status not in {'committed', 'uncertain'}:
        raise RuntimeError('Durable write executor did not provide a valid transaction outcome')
    if outcome.status == 'uncertain':
        return {'status': 'uncertain', 'committed': None, 'retry_allowed': False,
                'message': '执行结果尚未核实，不得重复写入；请重新读取本班记录核对。'}
    if (not isinstance(outcome.result, dict) or outcome.result.get('transaction') != 'pending_commit'
            or not isinstance(outcome.result.get('readback'), dict) or not isinstance(outcome.result.get('selection'), dict)):
        raise RuntimeError('Committed outcome is missing its original readback')
    # A durable receipt is evidence of an earlier commit, NOT a continuing read
    # grant. Recheck today's class/document/roster permissions on every delivery,
    # including replay by a new call ID. Never return the stored pupil snapshot:
    # children may have left this teacher's readable roster since that write.
    validate_binding(binding)
    try:
        current = _classroom_read(args) if tool == 'attendance_save' else _meal_read(args)
    except frappe.PermissionError:
        raise
    except Exception:
        # Commit is already authoritative; a subsequent read failure must not
        # be represented as a failed/rolled-back write or invite a write retry.
        validate_binding(binding)
        return {'status': 'committed', 'committed': True, 'replayed': outcome.replayed,
                'readback_available': False, 'retry_allowed': False,
                'message': '已有提交回执，但当前回读失败；不要重复写入，请重新读取核对。'}
    validate_binding(binding)
    return {'status': 'committed', 'committed': True, 'replayed': outcome.replayed,
            'readback': current, 'readback_available': True, 'selection': outcome.result['selection'],
            'original_revision': outcome.result['readback'].get('revision'),
            'readback_scope': '已按当前账号权限重新读取；original_revision仅指原提交回执，未重复执行写入。'}


def dispatch(binding: BusinessBinding, tool_name: str, arguments: dict):
    """Dispatch one finite business tool under a freshly validated task owner."""
    if not isinstance(tool_name, str):
        raise ValueError('Unknown business tool')
    args = _validate_arguments(tool_name, arguments)
    validate_binding(binding)
    with _actor(binding):
        validate_binding(binding)
        if tool_name in {'attendance_save', 'meal_save'}:
            return _write(binding, tool_name, args)
        if tool_name == 'business_view':
            result = _business_view(binding, args)
        elif tool_name == 'scene_bootstrap':
            from tongjianyun.scene_access import get_bootstrap
            data = get_bootstrap(**args)
            result = {key: data[key] for key in ('version', 'day', 'meal', 'default_view', 'navigation', 'scope')}
        elif tool_name == 'classroom_read':
            result = _classroom_read(args)
        else:
            result = _meal_read(args)
        validate_binding(binding)
        return result
