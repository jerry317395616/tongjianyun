"""Trusted Frappe authority adapter for ordinary-business tasks, not an RPC API.

Use ``authority(identity, scopes)`` as BusinessTaskStore.authorize. Every call
uses a NEW Frappe context/connection, so SSE never retains the request's actor,
permission caches or REPEATABLE READ snapshot. No caller transaction is committed
or rolled back. Native role/metadata caches retain Frappe's native invalidation
contract; this is not a new generic permission fingerprint.

The web layer captures a Viewer AFTER Frappe authenticates the request. Its SID
is a credential: retain it only in trusted memory, never model/task/event JSON.
Viewer expiry stops a stream, whereas account/scope revocation stops the task.

Admission scopes are NOT the read set. Before delivering business data or public
text derived from it, the trusted service must register its actual ReadSet via
register_read. The private classroom source observer captures ALL attendance/
leave IDs from the same queries, before latest-row/model projection drops them.
Do not infer a read set from model JSON or re-query after a read and assume it
describes that read. Unknown projections/capabilities and incomplete read sets
fail closed. New services can extend the finite trusted registry in code.

There is deliberately no admin runner, arbitrary method, SQL, role assignment,
host command, database commit, or model-controlled owner/site in this module.
"""
from __future__ import annotations

from contextvars import Context
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Callable
import uuid

import frappe

from tongjianyun.business_agent_tasks import TaskIdentity, WorkerClaim, MAX_SCOPES, authority_scope
from tongjianyun.business_agent_tools import VIEW_FIELDS, _validate_arguments

CLASS_MEAL = 'Tongjianyun Class Meal Confirmation'
CONTROL_DOCTYPES = frozenset({
    'User', 'Role', 'Role Profile', 'User Permission', 'DocShare', 'DocPerm', 'Custom DocPerm',
    'DocType', 'DocField', 'Custom Field', 'Property Setter', 'Server Script', 'Client Script',
    'Scheduled Job Type', 'System Console', 'System Settings', 'Social Login Key',
    'OAuth Client', 'OAuth Bearer Token', 'Integration Request',
})
ROSTER = 'projection:class-roster:v1'
GROUPS = 'projection:class-discovery:v1'
ATTENDANCE = 'projection:attendance:v1'
MEALS = 'projection:class-meals:v1'
MEAL_ESTIMATES = 'projection:class-meal-estimates:v1'
SCENE = 'scene:business:v1'
CATALOG = 'catalog:business:v1'


class MealReadScopeLimit(ValueError):
    """No partial roster may be returned when complete source registration fails."""
    def __init__(self, *, single_read):
        self.single_read = single_read
        super().__init__('Complete meal read exceeds the business source scope budget')


def _deny():
    # Never relay raw DB exceptions, missing document values or credentials.
    raise frappe.PermissionError('Business authority is unavailable or has been revoked')


def _identity(identity, site):
    if (not isinstance(identity, TaskIdentity) or identity.site != site or identity.mode != 'business'
            or not isinstance(identity.owner, str) or identity.owner == 'Guest'
            or not 1 <= len(identity.owner) <= 140 or any(ord(c) < 32 for c in identity.owner)):
        _deny()
    try:
        if str(uuid.UUID(identity.task_id)) != identity.task_id:
            _deny()
    except (ValueError, TypeError, AttributeError):
        _deny()


def _scopes(values):
    if not isinstance(values, (list, tuple)) or len(values) > MAX_SCOPES:
        raise ValueError('Invalid bounded business read set')
    unique = {}
    for value in values:
        scope = authority_scope(value)
        unique[json.dumps(scope, sort_keys=True, ensure_ascii=False)] = scope
    return tuple(unique.values())


def _read(doctype, document=None):
    result = {'kind': 'document' if document is not None else 'doctype', 'doctype': doctype, 'actions': ['read']}
    if document is not None:
        result['document'] = document
    return result


def _class(group):
    return {'kind': 'class', 'group': group, 'actions': ['read']}


def _capability(name):
    return {'kind': 'capability', 'name': name}


@dataclass(frozen=True)
class Viewer:
    """Captured from an authenticated request, never deserialized from payload."""
    site: str
    owner: str
    sid: str = field(repr=False)


@dataclass(frozen=True)
class ReadSet:
    """Actual source identifiers retained by trusted readers, not model output.

    Use attendance_read_set for classroom._attendance's private source observer.
    Other trusted readers explicitly include every source record used, including
    each student behind aggregates, and the fixed field projection capability.
    No generic 'complete=True' assertion can turn a stripped result into a set.
    """
    scopes: tuple

    def __post_init__(self):
        object.__setattr__(self, 'scopes', _scopes(self.scopes))


class FreshFrappeChecks:
    """Concrete fresh-context runner, configured once by trusted deployment code.

    ``before_connect`` can enforce the existing QA/live configuration guard.
    The fixed sites_path and site are never read from an HTTP/model argument.
    Context() (not copy_context()) isolates Frappe's ContextVar local storage.
    Native connect(set_admin_as_user=False) never boots this check as admin.
    """
    def __init__(self, site, sites_path, *, before_connect: Callable | None = None):
        if not isinstance(site, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', site):
            raise ValueError('Invalid configured site')
        path = Path(sites_path)
        if not path.is_absolute() or not path.is_dir():
            raise ValueError('An existing absolute trusted sites directory is required')
        if before_connect is not None and not callable(before_connect):
            raise ValueError('Invalid configuration guard')
        self.site, self.sites_path, self.before_connect = site, str(path.resolve()), before_connect

    def __call__(self, owner, callback):
        def run():
            try:
                frappe.init(self.site, sites_path=self.sites_path)
                if self.before_connect:
                    self.before_connect()
                if frappe.local.site != self.site:
                    _deny()
                frappe.connect(set_admin_as_user=False)
                frappe.set_user(owner)
                return callback()
            finally:
                # Closing this fresh connection rolls back only ITS read txn.
                # Do not call Session.resume/update/delete or db.commit here.
                frappe.destroy()
        return Context().run(run)


def _account(owner, site):
    if getattr(frappe.local, 'site', None) != site or frappe.session.user != owner:
        _deny()
    flags = getattr(frappe.local, 'flags', {}) or {}
    if any(flags.get(key) for key in ('ignore_permissions', 'in_install', 'in_migrate', 'in_patch')):
        _deny()
    user = frappe.db.get_value('User', owner, ['enabled', 'user_type'], as_dict=True)
    if not user or user.get('enabled') not in (True, 1) or user.get('user_type') != 'System User':
        _deny()


def _doctype(doctype, actions):
    from tongjianyun.frappe_project_views import _doctype as native_doctype, module_apps
    if doctype in CONTROL_DOCTYPES:
        _deny()
    meta = native_doctype(doctype, module_apps())  # installed, unblocked, non-child, readable
    for action in actions:
        if not frappe.has_permission(doctype, action):
            _deny()
    return meta


def _document(doctype, name, actions):
    meta = _doctype(doctype, actions)
    if meta.issingle and name != doctype:
        _deny()
    doc = frappe.get_doc(doctype, name)
    for action in actions:
        doc.check_permission(action)
    # Document hooks and list query restrictions are distinct in Frappe.
    # Replays require BOTH; a DocShare must not bypass a teacher row hook.
    if 'read' in actions and not meta.issingle:
        names = frappe.get_list(doctype, filters={'name': name}, pluck='name', limit_page_length=1)
        if name not in names:
            _deny()


def _fields(doctype, fields, *, parenttype=None):
    from frappe.model import get_permitted_fields
    allowed = get_permitted_fields(doctype, parenttype=parenttype, user=frappe.session.user, permission_type='read')
    if not set(fields) <= set(allowed):
        _deny()


def _table_field(doctype, fieldname):
    # Native get_permitted_fields deliberately omits non-column Table fields.
    # Their own permlevel must be checked separately, then each child's fields
    # through get_permitted_fields(child, parenttype=doctype).
    meta = frappe.get_meta(doctype)
    field = meta.get_field(fieldname)
    if (not field or field.fieldtype not in {'Table', 'Table MultiSelect'} or not field.options
            or field.permlevel not in meta.get_permlevel_access(permission_type='read', user=frappe.session.user)):
        _deny()
    return field.options


def _projection(name):
    if name in {SCENE, CATALOG}:
        from tongjianyun.scene_access import require_scene_account
        require_scene_account()
        return
    if name == GROUPS:
        _doctype('Student Group', ['read'])
        _fields('Student Group', ('student_group_name', 'academic_year', 'disabled'))
        return
    if name not in {ROSTER, ATTENDANCE, MEALS, MEAL_ESTIMATES}:
        _deny()
    for dt in ('Student Group', 'Student'):
        _doctype(dt, ['read'])
    _fields('Student', ('student_name', 'enabled'))
    _fields('Student Group', ('student_group_name', 'academic_year', 'disabled'))
    roster_child = _table_field('Student Group', 'students')
    if roster_child != 'Student Group Student':
        _deny()
    _fields(roster_child, ('student', 'active', 'group_roll_number'), parenttype='Student Group')
    if name in {ATTENDANCE, MEAL_ESTIMATES}:
        for dt, fields in (
            ('Student Attendance', ('student', 'student_group', 'date', 'status')),
            ('Student Leave Application', ('student', 'student_group', 'from_date', 'to_date', 'mark_as_present')),
        ):
            _doctype(dt, ['read'])
            _fields(dt, fields)
    if name == MEAL_ESTIMATES:
        # The original estimate path uses the group's stored display name,
        # attendance linkage and leave reasons; these are not model output but
        # may not silently bypass the native field-level read policy either.
        _fields(roster_child, ('student_name',), parenttype='Student Group')
        _fields('Student Attendance', ('leave_application',))
        _fields('Student Leave Application', ('reason',))
    if name == MEALS:
        _doctype(CLASS_MEAL, ['read'])
        _fields(CLASS_MEAL, ('student_group', 'meal_date', 'status'))
        child = _table_field(CLASS_MEAL, 'students')
        from tongjianyun.student_meals import MEALS as meal_names
        _fields(child, ('student', 'student_name', *meal_names, *(m + '_expected' for m in meal_names)), parenttype=CLASS_MEAL)


def _view_dependencies(selection):
    """Admission dependencies, NOT the actual records behind a returned summary."""
    from tongjianyun.meal_views import selection as canonical_selection
    checked = _validate_arguments('business_view', {'selection': selection})['selection']
    choice = canonical_selection(checked)
    if choice['view'] not in VIEW_FIELDS:
        _deny()
    view = choice['view']
    result = [{'kind': 'view', 'selection': choice}]
    if view == 'frappe_catalog':
        # Even an administrator's BUSINESS task cannot turn into project mode.
        if choice.get('kind') not in (None, '', 'doctype'):
            _deny()
        from tongjianyun.frappe_project_views import module_apps
        modules = module_apps()
        if choice.get('app') and choice['app'] not in frappe.get_installed_apps():
            _deny()
        if choice.get('module') and (choice['module'] not in modules or
                (choice.get('app') and modules[choice['module']] != choice['app'])):
            _deny()
        result.append(_capability(CATALOG))
    elif view.startswith('frappe_'):
        dt = choice['doctype']
        result.append(_read(dt))
        if view == 'frappe_document':
            result.append(_read(dt, choice['document']))
        elif view == 'frappe_new':
            result.append({'kind': 'doctype', 'doctype': dt, 'actions': ['create', 'read']})
    else:
        result.append(_capability(ATTENDANCE if view == 'classroom_day' else MEALS if view == 'meal_counts' else ROSTER))
        if choice.get('group'):
            # Canonical IDs only. UI label resolution happens in the trusted
            # original reader before producing a published selection/read set.
            result.append(_class(choice['group']))
    return _scopes(result)


def _check_scope(scope):
    kind = scope['kind']
    if kind == 'capability':
        _projection(scope['name'])
    elif kind == 'class':
        # Class read does NOT mean generic Student Group write/create permission.
        # Domain writes must still pass original attendance/meal save services.
        if scope['actions'] != ['read']:
            _deny()
        from tongjianyun.classroom import _scope
        _scope(scope['group'])
    elif kind == 'doctype':
        _doctype(scope['doctype'], scope['actions'])
    elif kind == 'document':
        _document(scope['doctype'], scope['document'], scope['actions'])
    elif kind == 'attachment':
        # File access is its native document policy, not a grant to browse
        # the File DocType or arbitrary paths. The descriptor is host-bound.
        from tongjianyun.business_agent_attachments import check_source
        check_source(scope['descriptor'])
    elif kind == 'view':
        from tongjianyun.scene_access import require_view_access
        # Reject unknown/admin views BEFORE require_view_access can use its
        # administrator fallback. All other scopes are recursively finite.
        dependencies = _view_dependencies(scope['selection'])
        require_view_access(scope['selection']['view'])
        for dependency in dependencies:
            if dependency['kind'] != 'view':
                _check_scope(dependency)
    else:
        _deny()


class FrappeBusinessAuthority:
    def __init__(self, site, *, run_check: Callable):
        if not isinstance(site, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', site) or not callable(run_check):
            raise ValueError('A fixed site and fresh trusted context runner are required')
        if getattr(run_check, 'site', site) != site:
            raise ValueError('Permission runner belongs to a different site')
        self.site, self.run_check = site, run_check

    def __call__(self, identity, scopes):
        """Exact BusinessTaskStore.authorize contract; fail closed, no raw errors."""
        try:
            _identity(identity, self.site)
            required = _scopes(scopes)
            def check():
                _account(identity.owner, self.site)
                for scope in required:
                    _check_scope(scope)
                # Fresh connection prevents stale snapshots across callbacks;
                # this is not a promise of atomic revocation mid-delivery.
                return True
            return self.run_check(identity.owner, check) is True
        except Exception:
            return False

    def capture_viewer(self):
        """Call only after native web authentication, BEFORE set_user/task dispatch."""
        owner = getattr(frappe.session, 'user', None)
        sid = getattr(frappe.session, 'sid', None)
        if (getattr(frappe.local, 'site', None) != self.site or not isinstance(owner, str)
                or owner == 'Guest' or not isinstance(sid, str) or sid in ('Guest', owner)
                or not 16 <= len(sid) <= 256 or any(ord(c) < 33 for c in sid)):
            _deny()
        viewer = Viewer(self.site, owner, sid)
        if not self.viewer_active(viewer):
            _deny()
        return viewer

    def viewer_active(self, viewer, identity=None):
        """Browser-only gate. A false result must NOT be turned into task.cancel."""
        try:
            if not isinstance(viewer, Viewer) or viewer.site != self.site:
                return False
            if identity is not None:
                _identity(identity, self.site)
                if identity.owner != viewer.owner:
                    return False
            def check():
                _account(viewer.owner, self.site)
                return _live_session(viewer)
            return self.run_check(viewer.owner, check) is True
        except Exception:
            return False

    def view_scopes(self, identity, selection):
        """Trusted web initial context: resolve an audited selection, check its admission."""
        _identity(identity, self.site)
        def resolve():
            _account(identity.owner, self.site)
            result = _view_dependencies(selection)
            for scope in result:
                _check_scope(scope)
            return result
        return self.run_check(identity.owner, resolve)

    def register_read(self, store, claim, read_set):
        """Worker-only barrier before data/message/publication delivery.

        The task store rechecks every OLD dependency as well as the proposed
        union, and persists dependencies before anything reaches the model.
        Batch registration authorizes and persists the entire union atomically.
        This does not claim that arbitrary caller-created ReadSet is complete.
        """
        if not isinstance(claim, WorkerClaim) or not isinstance(read_set, ReadSet):
            _deny()
        _identity(claim.identity, self.site)
        if not self(claim.identity, read_set.scopes):
            _deny()
        store.register_authorities(claim, read_set.scopes)
        # Re-authorize the full persisted union, not only this result's subset.
        state = store.binding_state(claim)
        if state['status'] != 'running' or state['cancel_requested'] not in (False, 0, '0'):
            _deny()

    def read_attendance(self, store, claim, *, group, day):
        """Executable reference integration for the registered classroom_read tool.

        Capture dependencies from the SAME original-service read, register them,
        freshly recheck the full task union, then return the minimum projection.
        Reads only; existing save services/ledger still own writes and revisions.
        ``claim`` is trusted worker state, never an argument accepted from model.
        """
        if not isinstance(claim, WorkerClaim):
            _deny()
        _identity(claim.identity, self.site)
        args = _validate_arguments('classroom_read', {'group': group, 'day': day})
        state = store.binding_state(claim)
        if state['status'] != 'running' or state['cancel_requested'] not in (False, 0, '0'):
            _deny()
        def read():
            from tongjianyun import classroom
            _account(claim.identity.owner, self.site)
            _projection(ATTENDANCE)
            doc, date = classroom._scope(args['group']), classroom._day(args['day'])
            captured = []
            raw = classroom._attendance(doc, date, source_observer=captured.append)
            if (len(captured) != 1 or not isinstance(captured[0], classroom.AttendanceReadSources)
                    or captured[0].group != doc.name or captured[0].day != str(date)
                    or captured[0].revision != raw['revision']):
                _deny()
            read_set = attendance_read_set(captured[0])
            result = {'group': doc.name, 'day': str(date), 'scope': '当前账号有权查看的本班有效名单',
                      'revision': raw['revision'], 'counts': raw['counts'],
                      'students': [{key: row.get(key) for key in ('student', 'student_name', 'status', 'source')}
                                   for row in raw['students']],
                      'attendance_write': classroom._capabilities(date)['attendance_write']}
            return result, read_set
        result, read_set = self.run_check(claim.identity.owner, read)
        self.register_read(store, claim, read_set)
        return result

    def read_meals(self, store, claim, *, group, day):
        """Original class-day meal snapshot, with same-query dependencies.

        Existing snapshots depend on their saved class-meal document; first
        reads additionally depend on every native estimate attendance/leave
        source. Expected values remain estimates, never actual attendance.
        Nothing is saved or confirmed by opening this reader.
        """
        if not isinstance(claim, WorkerClaim):
            _deny()
        _identity(claim.identity, self.site)
        args = _validate_arguments('meal_read', {'group': group, 'day': day})
        state = store.binding_state(claim)
        if state['status'] != 'running' or state['cancel_requested'] not in (False, 0, '0'):
            _deny()
        def read():
            from tongjianyun import classroom, student_meals
            _account(claim.identity.owner, self.site)
            _projection(MEALS)
            captured = []
            raw = classroom._get_meals(args['group'], args['day'], source_observer=captured.append)
            record = raw['record']
            if (len(captured) != 1 or not isinstance(captured[0], student_meals.ClassMealReadSources)
                    or captured[0].group != args['group'] or captured[0].day != args['day']
                    or captured[0].revision != raw['revision']
                    or record.get('student_group') != args['group'] or str(record.get('meal_date')) != args['day']
                    or tuple(row['student'] for row in record.get('students', [])) != captured[0].students
                    or (captured[0].record is not None and record.get('name') != captured[0].record)):
                _deny()
            read_set = meal_read_set(captured[0])
            if captured[0].estimates is not None:
                _projection(MEAL_ESTIMATES)
            fields = ('student', 'student_name', *sorted(student_meals.MEALS),
                      *(meal + '_expected' for meal in sorted(student_meals.MEALS)))
            result = {'group': args['group'], 'day': args['day'],
                      'scope': '当前账号有权查看的本班餐次名单；预计值不是实际就餐，未确认不计为零',
                      'revision': raw['revision'], 'meals': raw['meals'],
                      'students': [{key: row.get(key) for key in fields} for row in record.get('students', [])]}
            return result, read_set
        result, read_set = self.run_check(claim.identity.owner, read)
        combined = {_json_scope(scope) for scope in (*store.required_scopes(claim.identity), *read_set.scopes)}
        if len(combined) > MAX_SCOPES:
            raise MealReadScopeLimit(single_read=False)
        self.register_read(store, claim, read_set)
        return result


def attendance_read_set(sources):
    """Use ONLY the trusted observer's complete same-query source object.

    Both raw/public attendance rows have already selected the latest record per
    pupil. Neither can reconstruct every record used by the revision. All source
    IDs, including older rows, remain private; no names/reasons are stored here.
    """
    from tongjianyun.classroom import AttendanceReadSources
    if not isinstance(sources, AttendanceReadSources):
        raise ValueError('Complete same-query attendance sources are required; projected rows are insufficient')
    scopes = [_class(sources.group), _capability(ATTENDANCE)]
    for dt, records in (('Student', sources.students), ('Student Attendance', sources.attendance_records),
                        ('Student Leave Application', sources.leave_records)):
        if type(records) is not tuple:
            raise ValueError('Invalid immutable attendance source identifiers')
        scopes.extend(_read(dt, name) for name in records)
    return ReadSet(tuple(scopes))


def meal_read_set(sources):
    """All native snapshot/estimate sources; never reconstruct from public rows."""
    from tongjianyun.student_meals import ClassMealReadSources, DOCTYPE
    from tongjianyun.daily_meals import StudentMealReadSources
    if not isinstance(sources, ClassMealReadSources) or type(sources.students) is not tuple:
        raise ValueError('Complete same-query meal sources are required')
    _validate_arguments('meal_read', {'group': sources.group, 'day': sources.day})
    if (not isinstance(sources.revision, str) or len(sources.revision) > 64
            or len(set(sources.students)) != len(sources.students)):
        raise ValueError('Invalid meal source revision or roster')
    scopes = [_class(sources.group), _read('Student Group', sources.group), _capability(MEALS),
              *(_read('Student', name) for name in sources.students)]
    if sources.record is not None:
        if not sources.revision or sources.estimates is not None:
            raise ValueError('Stored meal source must be a saved snapshot, not a new estimate')
        scopes.append(_read(DOCTYPE, sources.record))
    else:
        estimate = sources.estimates
        if (sources.revision or not isinstance(estimate, StudentMealReadSources)
                or estimate.day != sources.day or estimate.groups != (sources.group,)
                or estimate.adjustment_records != ()):
            raise ValueError('Original student estimates are required; aggregate adjustments are not this service')
        if any(type(getattr(estimate, key)) is not tuple for key in
               ('groups', 'students', 'attendance_records', 'leave_records', 'adjustment_records')):
            raise ValueError('Estimate source identifiers must be immutable')
        if not set(sources.students) <= set(estimate.students):
            raise ValueError('Meal estimate is missing student sources')
        scopes.append(_capability(MEAL_ESTIMATES))
        for dt, records in (('Student', estimate.students), ('Student Attendance', estimate.attendance_records),
                            ('Student Leave Application', estimate.leave_records)):
            scopes.extend(_read(dt, name) for name in records)
    canonical = {_json_scope(scope): authority_scope(scope) for scope in scopes}
    if len(canonical) > MAX_SCOPES:
        raise MealReadScopeLimit(single_read=True)
    return ReadSet(tuple(canonical.values()))


def _json_scope(scope):
    return json.dumps(authority_scope(scope), sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _session_row(sid):
    # Sessions is a native table, not an ordinary DocType with a creation field.
    # db.get_value's default creation ordering is invalid on the actual table.
    table = frappe.qb.DocType('Sessions')
    rows = (frappe.qb.from_(table).select(table.user, table.sessiondata, table.lastupdate, table.status)
            .where(table.sid == sid).limit(1).run(as_dict=True))
    return rows[0] if rows else None


def _live_session(viewer):
    """Read-only equivalent of native expiry checks; never resume/extend a SID.

    The DB row must still exist even when Redis has stale session data. Redis
    last_updated can be newer because native sessions persist DB periodically.
    No values from here are returned to the model, logs, tasks or SSE.
    """
    from frappe.sessions import get_expiry_in_seconds
    from frappe.utils import get_datetime, now_datetime
    if (not isinstance(viewer.sid, str) or not 16 <= len(viewer.sid) <= 256
            or viewer.sid in ('Guest', viewer.owner) or any(ord(c) < 33 for c in viewer.sid)):
        return False
    row = _session_row(viewer.sid)
    if not row or row.get('user') != viewer.owner or row.get('status') != 'Active':
        return False
    raw = row.get('sessiondata') or '{}'
    if not isinstance(raw, str) or len(raw) > 65536:
        return False
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get('user', viewer.owner) != viewer.owner:
        return False
    cached = frappe.cache.hget('session', viewer.sid)
    if cached:
        if not isinstance(cached, dict) or cached.get('user') != viewer.owner or not isinstance(cached.get('data'), dict):
            return False
        data = cached['data']
        if data.get('user', viewer.owner) != viewer.owner:
            return False
    updated = data.get('last_updated') or row.get('lastupdate')
    if not updated:
        return False
    seconds = min(get_expiry_in_seconds(), get_expiry_in_seconds(data.get('session_expiry')))
    age = (now_datetime() - get_datetime(updated)).total_seconds()
    if seconds <= 0 or age < 0 or age > seconds:
        return False
    if data.get('session_end'):
        end = datetime.fromisoformat(data['session_end'])
        if end.tzinfo is None or datetime.now(timezone.utc) >= end:
            return False
    return True
