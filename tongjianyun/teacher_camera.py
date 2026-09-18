"""Internal trusted-recognizer bridge. Not whitelisted; no camera/face inference here.

The caller owns commit/rollback. Never accept this envelope directly from a camera
or browser: identity, scores and liveness must come from a trusted recognizer.
"""
import hashlib
import math
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


class Rejected(ValueError):
    pass


def prepare(event, config, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(event, dict) or not isinstance(config, dict):
        raise Rejected('invalid_payload')
    for field in ('event_id', 'camera_id', 'subject_id'):
        if not isinstance(event.get(field), str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', event[field]):
            raise Rejected('invalid_identifier')
    camera = config.get('cameras', {}).get(event['camera_id'])
    if not camera or camera.get('enabled') is not True:
        raise Rejected('camera_not_enabled')
    # Direction is provisioned, never inferred from last sighting or caller input.
    if camera.get('direction') not in ('IN', 'OUT'):
        raise Rejected('direction_not_configured')
    subject = config.get('subjects', {}).get(event['subject_id'])
    if not subject or subject.get('consent') is not True or not subject.get('employee'):
        raise Rejected('subject_not_authorized')
    if event.get('face_count') != 1 or isinstance(event.get('face_count'), bool):
        raise Rejected('ambiguous_face')
    if event.get('liveness_passed') is not True:
        raise Rejected('liveness_required')
    for field, setting in (('confidence', 'min_confidence'), ('margin', 'min_margin')):
        value, threshold = event.get(field), config.get(setting)
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not 0 <= x <= 1 for x in (value, threshold)):
            raise Rejected('scores_not_configured')
        if value < threshold:
            raise Rejected('recognition_uncertain')
    try:
        instant = datetime.fromisoformat(event['occurred_at'].replace('Z', '+00:00'))
        if instant.tzinfo is None or now.tzinfo is None:
            raise ValueError()
    except (KeyError, TypeError, AttributeError, ValueError):
        raise Rejected('invalid_timestamp') from None
    age = (now - instant).total_seconds()
    if age < -30 or age > 300:
        raise Rejected('timestamp_out_of_window')
    digest = hashlib.sha256((event['camera_id'] + '\0' + event['event_id']).encode()).hexdigest()
    return {'name': 'TJYCAM-' + digest, 'employee': subject['employee'],
            'instant': instant, 'log_type': camera['direction'],
            'device_id': 'tongjianyun-camera:' + event['camera_id']}


def ingest(event, *, dry_run=True):
    """Run under a permissioned service account. Dry-run is always the default."""
    import frappe

    if frappe.session.user == 'Guest' or not frappe.has_permission('Employee Checkin', 'create'):
        raise frappe.PermissionError('Employee Checkin create permission required')
    config = frappe.conf.get('tongjianyun_teacher_camera') or {}
    try:
        prepared = prepare(event, config)
    except Rejected as exc:
        return {'status': 'rejected', 'reason': str(exc)}
    if not dry_run and config.get('enabled') is not True:
        return {'status': 'disabled'}
    employee = frappe.db.get_value('Employee', prepared['employee'], ['name', 'status'],
                                   as_dict=True, for_update=not dry_run)
    if not employee or employee.status != 'Active' or not frappe.has_permission('Employee', 'read', doc=employee.name):
        return {'status': 'rejected', 'reason': 'employee_not_available'}
    local_time = prepared['instant'].astimezone(ZoneInfo(frappe.utils.get_system_timezone())).replace(tzinfo=None, microsecond=0)
    existing = frappe.db.get_value('Employee Checkin', prepared['name'], ['name', 'employee', 'time', 'log_type'], as_dict=True)
    if existing:
        if existing.employee != prepared['employee'] or existing.log_type != prepared['log_type'] or frappe.utils.get_datetime(existing.time) != local_time:
            return {'status': 'rejected', 'reason': 'event_id_conflict'}
        return {'status': 'duplicate', 'checkin': existing.name}
    # Employee row lock serializes different camera events for the same teacher.
    duplicate = frappe.db.get_value('Employee Checkin', {
        'employee': prepared['employee'], 'log_type': prepared['log_type'],
        'time': ['between', [local_time - timedelta(seconds=60), local_time + timedelta(seconds=60)]],
    }, 'name')
    if duplicate:
        return {'status': 'duplicate', 'checkin': duplicate}
    if dry_run:
        return {'status': 'preview', 'employee': prepared['employee'], 'log_type': prepared['log_type'],
                'time': str(local_time), 'skip_auto_attendance': 1}
    doc = frappe.get_doc({'doctype': 'Employee Checkin', 'employee': prepared['employee'],
                         'time': local_time, 'log_type': prepared['log_type'],
                         'device_id': prepared['device_id'], 'skip_auto_attendance': 1})
    doc.insert(set_name=prepared['name'])
    return {'status': 'created', 'checkin': doc.name, 'skip_auto_attendance': 1}
