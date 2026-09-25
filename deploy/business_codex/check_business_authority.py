"""Re-runnable read-only authority acceptance on the ONE existing isolated QA.

No login/session refresh, users/roles, business data, model, queues or production.
Uses the established config guard before EVERY connection, pins session-level
MariaDB READ ONLY, and retains private hash-bound evidence. Never prints SIDs,
session bodies, database credentials, pupil identities/names or raw exceptions.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unified_business'))
import serve_isolated_browser as qa

OWNER = 'teacher-scope-9680e04d9f@example.invalid'
GROUP = 'QA Teacher 9680e04d9f Assigned'
OTHER_GROUP = 'QA Teacher 9680e04d9f Other'
DAY = '2026-09-16'  # Existing synthetic rows; READ ONLY, never fixture creation.


def run():
    if sys.flags.optimize:
        raise RuntimeError('QA configuration assertions may not be disabled')
    qa.config_guard()
    frappe = qa.runtime()
    from tongjianyun import business_agent_authority as authority, classroom
    from tongjianyun.business_agent_tasks import TaskIdentity
    assert Path(authority.__file__).resolve().is_relative_to(qa.SOURCE)
    assert Path(classroom.__file__).resolve().is_relative_to(qa.SOURCE)
    assert Path(__file__).resolve().is_relative_to(qa.SOURCE)
    output = qa.safe_target(qa.ROOT / ('business-authority-readonly-' + uuid.uuid4().hex[:10] + '.json'))
    evidence = {'version': 1, 'site': qa.SITE, 'checks': [], 'business_writes': False,
                'sessions_mutated': False, 'users_modified': False, 'codex_executed': False,
                'production_access': False, 'session_transaction_read_only': True,
                'source_sha256': qa.digest_file(Path(authority.__file__)),
                'classroom_sha256': qa.digest_file(Path(classroom.__file__)),
                'script_sha256': qa.digest_file(Path(__file__))}

    def check(name, condition):
        evidence['checks'].append({'name': name, 'passed': bool(condition)})
        qa.private_json(output, evidence)
        print(json.dumps(evidence['checks'][-1]), flush=True)
        if not condition:
            raise AssertionError(name)

    def read_only():
        # Session variable only. No persistent DB settings or business writes.
        frappe.db.sql('SET SESSION TRANSACTION READ ONLY')
        if frappe.db.sql('SELECT @@session.tx_read_only')[0][0] != 1:
            raise RuntimeError('Read-only QA transaction was not enforced')
        frappe.flags.read_only = True

    def before_connect():
        qa.config_guard()
        qa.guard(frappe.conf)

    runner = authority.FreshFrappeChecks(qa.SITE, str(qa.SITES), before_connect=before_connect)

    def readonly_runner(owner, callback):
        def guarded():
            read_only()
            return callback()
        return runner(owner, guarded)

    adapter = authority.FrappeBusinessAuthority(qa.SITE, run_check=readonly_runner)
    identity = TaskIdentity(qa.SITE, OWNER, str(uuid.uuid4()))  # Not enqueued or stored.
    try:
        frappe.init(qa.SITE, sites_path=str(qa.SITES))
        before_connect()
        frappe.connect(set_admin_as_user=False)
        frappe.set_user(OWNER)
        read_only()
        original = (frappe.db._get_current_object(), frappe.session.sid, frappe.local.request_cache)
        check('enabled_teacher_account', adapter(identity, []))
        for view in ('class_students', 'classroom_day', 'meal_counts'):
            scopes = adapter.view_scopes(identity, {'view': view, 'group': GROUP, 'day': DAY})
            check(view + '_native_projection', adapter(identity, scopes))
        check('other_class_denied', not adapter(identity, [authority._class(OTHER_GROUP)]))

        def sources():
            from tongjianyun.classroom import _scope, _attendance, _day
            captured = []
            raw = _attendance(_scope(GROUP), _day(DAY), source_observer=captured.append)
            check('same_query_complete_source_observer_matches_revision', len(captured) == 1
                  and captured[0].group == GROUP and captured[0].day == DAY
                  and captured[0].revision == raw['revision'])
            return authority.attendance_read_set(captured[0]), len(raw['students'])
        read_set, count = readonly_runner(OWNER, sources)
        check('actual_attendance_student_source_permissions', count == 2 and adapter(identity, read_set.scopes))
        check('outer_database_identity_unchanged', frappe.db._get_current_object() is original[0])
        check('outer_actor_sid_request_cache_unchanged', frappe.session.user == OWNER
              and frappe.session.sid == original[1] and frappe.local.request_cache is original[2])
        check('outer_connection_still_usable', bool(frappe.db.get_value('User', OWNER, 'enabled')))

        def sessions():
            from frappe.sessions import get_expiry_in_seconds
            check('native_expiry_none_and_default_match', get_expiry_in_seconds(None) == get_expiry_in_seconds())
            table = frappe.qb.DocType('Sessions')
            rows = (frappe.qb.from_(table).select(table.sid, table.sessiondata)
                    .where(table.user == OWNER).where(table.status == 'Active').run(as_dict=True))
            result = {'existing_sessions': len(rows), 'db_json_objects': 0,
                      'cached_native_envelopes': 0, 'active_viewers': 0}
            for row in rows:
                data = json.loads(row.sessiondata or '{}')
                result['db_json_objects'] += int(isinstance(data, dict))
                cached = frappe.cache.hget('session', row.sid)
                if cached:
                    result['cached_native_envelopes'] += int(isinstance(cached, dict)
                        and cached.get('user') == OWNER and isinstance(cached.get('data'), dict))
                result['active_viewers'] += int(authority._live_session(authority.Viewer(qa.SITE, OWNER, row.sid)))
            return result
        session_shapes = readonly_runner(OWNER, sessions)
        evidence['session_shapes'] = session_shapes
        check('native_session_rows_parse_without_creating_sessions',
              session_shapes['db_json_objects'] == session_shapes['existing_sessions'])
        # Sessions may have legitimately expired between QA runs. Do not create
        # a login or claim active-session coverage when none exists anymore.
        evidence['active_session_coverage'] = session_shapes['active_viewers'] > 0
        evidence['all_passed'] = True
    except BaseException as error:
        evidence['all_passed'] = False
        evidence['failure_type'] = type(error).__name__
        raise
    finally:
        qa.private_json(output, evidence)
        frappe.destroy()
        print(json.dumps({'evidence': str(output), 'all_passed': evidence.get('all_passed', False)}), flush=True)


if __name__ == '__main__':
    run()
