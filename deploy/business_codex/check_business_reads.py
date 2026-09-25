"""Fixed isolated-QA read acceptance; no model, queue, login or business writes.

All Frappe connections enforce session TRANSACTION READ ONLY. A NEW private
artifact directory holds only test-task SQLite metadata and sanitized evidence;
it is not the site's live business-codex/tasks directory. No fixture cleanup or
permission mutation. Use the already existing synthetic teacher and class.
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
OTHER = 'QA Teacher 9680e04d9f Other'
DAY = '2026-09-16'


def run():
    if sys.flags.optimize:
        raise RuntimeError('QA guards may not be disabled')
    qa.config_guard()
    frappe = qa.runtime()
    from tongjianyun import business_agent_reads as reads, business_agent_authority as gates, classroom
    from tongjianyun.business_agent_tasks import BusinessTaskStore, TaskIdentity, QueueObservation, ExecutionObservation
    for module in (reads, gates, classroom):
        assert Path(module.__file__).resolve().is_relative_to(qa.SOURCE)
    assert Path(__file__).resolve().is_relative_to(qa.SOURCE)
    folder = qa.safe_target(qa.ROOT / ('business-reads-readonly-' + uuid.uuid4().hex[:10]))
    folder.mkdir(mode=0o700)
    output = folder / 'evidence.json'
    evidence = {'version': 1, 'site': qa.SITE, 'checks': [], 'all_passed': False,
        'business_writes': False, 'users_modified': False, 'sessions_mutated': False,
        'codex_executed': False, 'queue_used': False, 'production_access': False,
        'session_transaction_read_only': True, 'scope_store': str(folder),
        'store_purpose': 'Synthetic claimed task for source-aware read acceptance only; never queued or launched',
        'source_hashes': {Path(module.__file__).name: qa.digest_file(Path(module.__file__))
                          for module in (reads, gates, classroom)},
        'script_sha256': qa.digest_file(Path(__file__))}

    def check(name, value):
        item = {'name': name, 'passed': bool(value)}
        evidence['checks'].append(item)
        qa.private_json(output, evidence)
        print(json.dumps(item), flush=True)
        if not value:
            raise AssertionError(name)

    def before_connect():
        qa.config_guard()
        qa.guard(frappe.conf)

    def read_only():
        frappe.db.sql('SET SESSION TRANSACTION READ ONLY')
        if frappe.db.sql('SELECT @@session.tx_read_only')[0][0] != 1:
            raise RuntimeError('QA read-only mode is not active')
        frappe.flags.read_only = True

    runner = gates.FreshFrappeChecks(qa.SITE, str(qa.SITES), before_connect=before_connect)
    def readonly_runner(owner, callback):
        def guarded():
            read_only()
            return callback()
        return runner(owner, guarded)

    adapter = gates.FrappeBusinessAuthority(qa.SITE, run_check=readonly_runner)
    store = BusinessTaskStore(folder, qa.SITE, authorize=adapter,
        observe_queue=lambda job: QueueObservation(job, 'unknown'),
        observe_execution=lambda identity, claim: ExecutionObservation(claim, 'unknown', 0))
    identity = TaskIdentity(qa.SITE, OWNER, str(uuid.uuid4()))
    try:
        frappe.init(qa.SITE, sites_path=str(qa.SITES))
        before_connect()
        frappe.connect(set_admin_as_user=False)
        frappe.set_user(OWNER)
        read_only()
        outer = (frappe.db._get_current_object(), frappe.session.sid, frappe.local.request_cache)
        store.create(OWNER, identity.task_id, '隔离QA：只读班级发现与名单分页', {'day': DAY})
        ticket = store.take_dispatch(identity)
        # Deliberate synthetic local delivery, NOT a real queue or native task.
        store.acknowledge_dispatch(ticket)
        claim = store.claim(identity, ticket.job_id)
        reader = reads.BusinessReads(adapter, store)
        scene = reader.dispatch(claim, 'scene_bootstrap', {'day': DAY, 'page_size': 25})
        check('native_teacher_class_discovery_has_only_assigned_class',
              scene['groups_available'] and [r['group'] for r in scene['groups']] == [GROUP]
              and scene['visible_group_count'] == 1 and not scene['has_more'])
        check('native_field_permissions_enable_roster_and_attendance_navigation',
              {'class_students_read', 'classroom_read'} <= set(scene['supported_tools']))
        first = reader.dispatch(claim, 'class_students_read', {'group': GROUP, 'page_size': 1})
        check('first_page_does_not_misreport_total', first['page_count'] == 1 and first['has_more'] is True
              and first['visible_class_count'] is None and first['next_cursor'])
        scoped = store.required_scopes(identity)
        check('first_page_persists_both_returned_and_lookahead_student_sources',
              len([s for s in scoped if s.get('kind') == 'document' and s.get('doctype') == 'Student']) == 2)
        second = reader.dispatch(claim, 'class_students_read',
                                 {'group': GROUP, 'page_size': 1, 'cursor': first['next_cursor']})
        check('second_page_finishes_without_claiming_school_count', second['page_count'] == 1
              and second['has_more'] is False and second['visible_class_count'] is None)
        native = readonly_runner(OWNER, lambda: classroom._roster(classroom._scope(GROUP)))
        combined = first['students'] + second['students']
        check('page_sequence_matches_original_native_roster_order',
              combined == [{key: row[key] for key in ('student', 'student_name')} for row in native])
        complete = reader.dispatch(claim, 'class_students_read', {'group': GROUP})
        check('complete_first_page_has_exact_visible_class_count', complete['visible_class_count'] == len(native) == 2)
        denied = False
        try:
            reader.dispatch(claim, 'class_students_read', {'group': OTHER})
        except (PermissionError, frappe.PermissionError):
            denied = True
        check('other_class_denied', denied)
        events = store.events(identity)
        views = [e for e in events if e['kind'] == 'view']
        check('only_selection_view_events_no_student_payload', bool(views)
              and all(e['selection'] == {'view': 'class_students', 'group': GROUP, 'offset': 0} for e in views)
              and all('students' not in e and 'html' not in e for e in events))
        check('outer_connection_actor_session_cache_unchanged', frappe.session.user == OWNER
              and frappe.db._get_current_object() is outer[0] and frappe.session.sid == outer[1]
              and frappe.local.request_cache is outer[2])
        evidence['scope_count'] = len(store.required_scopes(identity))
        evidence['all_passed'] = True
    except BaseException as error:
        evidence['failure_type'] = type(error).__name__
        raise
    finally:
        qa.private_json(output, evidence)
        frappe.destroy()
        print(json.dumps({'evidence': str(output), 'all_passed': evidence['all_passed']}), flush=True)


if __name__ == '__main__':
    run()
