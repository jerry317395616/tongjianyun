"""Fixed isolated-QA meal reads. Default prepare; --run creates evidence only.

All connections are database-enforced READ ONLY. No model, real queue, service
startup, login/session mutation, fixture creation, role change or business write.
The retained private SQLite store is test metadata, separate from live tasks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unified_business'))
import serve_isolated_browser as qa

OWNER = 'teacher-scope-9680e04d9f@example.invalid'
GROUP = 'QA Teacher 9680e04d9f Assigned'
OTHER = 'QA Teacher 9680e04d9f Other'
SAVED_DAY = '2026-09-16'
EMPTY_DAY = '2026-09-15'
MEAL = 'breakfast'


def setup():
    if sys.flags.optimize:
        raise RuntimeError('QA guards may not be disabled')
    qa.config_guard()
    state = json.loads(qa.safe_target(qa.STATE).read_text())
    assert (state['owner'], state['site'], state['teacher'], state['group']) == (qa.TASK, qa.SITE, OWNER, GROUP)
    frappe = qa.runtime()
    from tongjianyun import business_agent_authority as gates, business_agent_reads as reads
    from tongjianyun import classroom, student_meals, daily_meals
    modules = (gates, reads, classroom, student_meals, daily_meals)
    assert all(Path(module.__file__).resolve().is_relative_to(qa.SOURCE) for module in modules)
    assert Path(__file__).resolve().is_relative_to(qa.SOURCE)

    def before_connect():
        qa.config_guard()
        qa.guard(frappe.conf)

    def readonly():
        frappe.db.sql('SET SESSION TRANSACTION READ ONLY')
        if frappe.db.sql('SELECT @@session.tx_read_only')[0][0] != 1:
            raise RuntimeError('Read-only QA transaction was not enforced')
        frappe.flags.read_only = True

    runner = gates.FreshFrappeChecks(qa.SITE, str(qa.SITES), before_connect=before_connect)
    def readonly_runner(owner, callback):
        def guarded():
            readonly()
            return callback()
        return runner(owner, guarded)
    return frappe, modules, readonly_runner, before_connect, readonly


def preflight(frappe, runner):
    from tongjianyun import business_agent_authority as gates, student_meals, classroom
    from tongjianyun.attendance_scope import allowed_groups
    def check():
        gates._account(OWNER, qa.SITE)
        roles = set(frappe.get_roles())
        assert {'Instructor', 'Academics User'} <= roles
        assert not roles & {'System Manager', 'Education Manager', 'Tongjianyun Business Operator'}
        assert allowed_groups() == [GROUP]
        classroom._scope(GROUP)
        gates._projection(gates.MEALS)
        gates._projection(gates.MEAL_ESTIMATES)
        assert frappe.db.exists(student_meals.DOCTYPE, student_meals.record_name(SAVED_DAY, GROUP))
        assert not frappe.db.exists(student_meals.DOCTYPE, student_meals.record_name(EMPTY_DAY, GROUP))
        return {'status': 'ready', 'site': qa.SITE, 'saved_day': SAVED_DAY, 'empty_day': EMPTY_DAY,
                'saved_snapshot_present': True, 'empty_day_has_no_snapshot': True,
                'source_field_permissions': True, 'business_writes': False, 'model_calls': 0}
    return runner(OWNER, check)


def protected_digest(frappe):
    """Only own-class readable sources; hash payloads, never persist raw data."""
    from tongjianyun import classroom, student_meals
    result = {}
    group = classroom._scope(GROUP)
    targets = [('Student Group', group.name)]
    targets.extend(('Student', row['student']) for row in classroom._roster(group))
    for doctype, filters in (
        (student_meals.DOCTYPE, {'student_group': GROUP}),
        ('Student Attendance', {'student_group': GROUP}),
        ('Student Leave Application', {'student_group': GROUP}),
    ):
        names = frappe.get_list(doctype, filters=filters, pluck='name', limit_page_length=1001)
        assert len(names) <= 1000, 'Fixed synthetic read coverage exceeded'
        targets.extend((doctype, name) for name in names)
    for doctype, name in targets:
        doc = frappe.get_doc(doctype, name)
        doc.check_permission('read')
        raw = json.dumps(doc.as_dict(), sort_keys=True, ensure_ascii=False, default=str).encode()
        # The evidence only contains a combined digest and record count.
        result[doctype + ':' + name] = hashlib.sha256(raw).hexdigest()
    raw = json.dumps(result, sort_keys=True).encode()
    return {'records': len(result), 'sha256': hashlib.sha256(raw).hexdigest()}


def execute(frappe, modules, runner, before_connect, readonly, prepared):
    from tongjianyun import business_agent_authority as gates, business_agent_reads as reads, classroom, student_meals
    from tongjianyun.business_agent_tasks import BusinessTaskStore, TaskIdentity, QueueObservation, ExecutionObservation
    folder = qa.safe_target(qa.ROOT / ('business-meal-reads-readonly-' + uuid.uuid4().hex[:10]))
    folder.mkdir(mode=0o700)
    output = folder / 'evidence.json'
    evidence = {'version': 1, 'site': qa.SITE, 'checks': [], 'all_passed': False, 'preflight': prepared,
                'business_writes': False, 'sessions_mutated': False, 'users_modified': False,
                'codex_executed': False, 'queue_used': False, 'production_access': False,
                'session_transaction_read_only': True, 'scope_store': str(folder),
                'store_purpose': 'Synthetic claimed read-only task metadata, never queued or launched',
                'source_hashes': {Path(module.__file__).name: qa.digest_file(Path(module.__file__)) for module in modules},
                'script_sha256': qa.digest_file(Path(__file__))}
    def check(name, condition):
        item = {'name': name, 'passed': bool(condition)}
        evidence['checks'].append(item)
        qa.private_json(output, evidence)
        print(json.dumps(item), flush=True)
        if not condition:
            raise AssertionError(name)

    adapter = gates.FrappeBusinessAuthority(qa.SITE, run_check=runner)
    store = BusinessTaskStore(folder, qa.SITE, authorize=adapter,
        observe_queue=lambda job: QueueObservation(job, 'unknown'),
        observe_execution=lambda identity, claim: ExecutionObservation(claim, 'unknown', 0))
    identity = TaskIdentity(qa.SITE, OWNER, str(uuid.uuid4()))
    try:
        frappe.init(qa.SITE, sites_path=str(qa.SITES))
        before_connect()
        frappe.connect(set_admin_as_user=False)
        frappe.set_user(OWNER)
        readonly()
        outer = (frappe.db._get_current_object(), frappe.session.sid, frappe.local.request_cache)
        evidence['protected_before'] = runner(OWNER, lambda: protected_digest(frappe))
        store.create(OWNER, identity.task_id, '隔离QA：只读本班逐餐情况', {'day': SAVED_DAY, 'meal': MEAL})
        ticket = store.take_dispatch(identity)
        store.acknowledge_dispatch(ticket)  # Synthetic local delivery, no real queue.
        claim = store.claim(identity, ticket.job_id)
        reader = reads.BusinessReads(adapter, store)
        saved = reader.dispatch(claim, 'meal_read', {'group': GROUP, 'day': SAVED_DAY})
        check('stored_snapshot_has_exact_class_and_revision', saved['group'] == GROUP and saved['day'] == SAVED_DAY
              and bool(saved['revision']) and len(saved['students']) == 2)
        check('stored_lunch_actual_and_other_meals_unknown_are_distinct',
              saved['meals']['lunch']['actual'] == 1 and saved['meals']['lunch']['complete']
              and all(saved['meals'][meal]['actual'] is None for meal in student_meals.MEALS if meal != 'lunch'))
        required = store.required_scopes(identity)
        check('saved_snapshot_document_scope_is_persisted', gates._read(student_meals.DOCTYPE,
              student_meals.record_name(SAVED_DAY, GROUP)) in required)
        check('saved_snapshot_does_not_rederive_attendance_sources',
              not any(scope.get('doctype') in {'Student Attendance', 'Student Leave Application'} for scope in required))

        empty = reader.dispatch(claim, 'meal_read', {'group': GROUP, 'day': EMPTY_DAY})
        check('initial_snapshot_stays_unsaved_and_all_actuals_unknown', not empty['revision']
              and len(empty['students']) == 2 and all(f['actual'] is None and not f['complete'] for f in empty['meals'].values()))
        check('initial_native_expected_is_not_misreported_as_actual',
              all(type(f['expected']) is int for f in empty['meals'].values()) and empty['meals']['dinner']['expected'] == 0
              and empty['meals']['dinner']['actual'] is None)

        def original_sources():
            captured = []
            raw = classroom._get_meals(GROUP, EMPTY_DAY, source_observer=captured.append)
            assert len(captured) == 1 and captured[0].revision == raw['revision']
            return gates.meal_read_set(captured[0]), raw
        sources, native = runner(OWNER, original_sources)
        check('complete_original_estimate_sources_registered_and_still_authorized',
              all(scope in store.required_scopes(identity) for scope in sources.scopes) and adapter(identity, sources.scopes))
        check('source_projection_reuses_original_meal_facts', native['meals'] == empty['meals'])
        check('result_has_only_fixed_minimal_projection', all(set(result) == {'group', 'day', 'scope', 'revision', 'meals', 'students'}
              and all('attendance_hint' not in row and 'leave_reason' not in row and 'parent' not in row for row in result['students'])
              for result in (saved, empty)))
        events = store.events(identity)
        views = [event for event in events if event['kind'] == 'view']
        check('exactly_one_scoped_context_meal_view_per_read', len(views) == 2
              and [event['selection'] for event in views] == [
                  {'view': 'meal_counts', 'group': GROUP, 'day': day, 'meal': MEAL} for day in (SAVED_DAY, EMPTY_DAY)]
              and all('students' not in event and 'html' not in event for event in events))
        denied = False
        try:
            reader.dispatch(claim, 'meal_read', {'group': OTHER, 'day': EMPTY_DAY})
        except (PermissionError, frappe.PermissionError):
            denied = True
        check('other_class_denied_without_extra_view', denied and len(store.events(identity)) == len(events))
        check('outer_context_unchanged', frappe.session.user == OWNER and frappe.db._get_current_object() is outer[0]
              and frappe.session.sid == outer[1] and frappe.local.request_cache is outer[2])
        evidence['protected_after'] = runner(OWNER, lambda: protected_digest(frappe))
        check('fresh_connection_business_source_digest_unchanged', evidence['protected_before'] == evidence['protected_after'])
        check('new_meal_record_not_created', runner(OWNER, lambda: not frappe.db.exists(
              student_meals.DOCTYPE, student_meals.record_name(EMPTY_DAY, GROUP))))
        evidence['scope_count'] = len(store.required_scopes(identity))
        evidence['all_passed'] = True
    except BaseException as error:
        evidence['failure_type'] = type(error).__name__
        raise
    finally:
        qa.private_json(output, evidence)
        frappe.destroy()
        print(json.dumps({'evidence': str(output), 'all_passed': evidence['all_passed']}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Run only read-only QA and preserve test metadata/evidence')
    args = parser.parse_args()
    frappe, modules, runner, before_connect, readonly = setup()
    prepared = preflight(frappe, runner)
    print(json.dumps(prepared), flush=True)
    if args.run:
        execute(frappe, modules, runner, before_connect, readonly, prepared)


if __name__ == '__main__':
    main()
