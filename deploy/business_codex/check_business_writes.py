"""Fixed synthetic QA native-write acceptance. Default: read-only preparation.

--run explicitly writes ONE attendance and ONE class lunch on the verified empty
2026-09-14 fixture day. Two stale-revision attempts must roll back. All records,
private task metadata, the one-shot marker and evidence are retained. The native
services also create/refresh this day's Daily Confirmation and add a meal Info
Comment; these are expected retained outputs, not just two database records.
No model, queue worker, service, session, account, role or production is changed.
Do not remove the attempt marker or pick another date to retry unknown results.
"""
from __future__ import annotations

import argparse
from contextvars import Context
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_meal_reads as fixture

qa = fixture.qa
OWNER, GROUP, OTHER = fixture.OWNER, fixture.GROUP, fixture.OTHER
DAY, MEAL = '2026-09-14', 'lunch'
ATTEMPT = qa.ROOT / 'business-native-write-20260926-attempt.json'


def isolation(frappe):
    value = frappe.db.sql('SELECT @@session.tx_isolation')[0][0]
    if value != 'REPEATABLE-READ':
        raise RuntimeError('Acceptance requires the native default REPEATABLE-READ; do not change it for the test')
    return value


def assert_empty_target(frappe):
    """QA-only metadata guard; stop on any existing source, never overwrite it."""
    from tongjianyun import daily_meals, student_meals
    filters = (
        ('Student Attendance', {'date': DAY}),
        ('Student Leave Application', {'from_date': ['<=', DAY], 'to_date': ['>=', DAY]}),
        (student_meals.DOCTYPE, {'meal_date': DAY}),
        (daily_meals.CONFIRMATION_DOCTYPE, {'meal_date': DAY}),
        (daily_meals.ADJUSTMENT_DOCTYPE, {'meal_date': DAY}),
    )
    for doctype, choice in filters:
        if frappe.db.exists(doctype, choice):
            raise RuntimeError('Fixed synthetic write day has existing sources; no write is permitted')


def protected_digest(frappe):
    """Read-permitted own-class originals excluding the only new test day."""
    from tongjianyun import classroom, student_meals
    group = classroom._scope(GROUP)
    targets = [('Student Group', GROUP), *(('Student', row['student']) for row in classroom._roster(group))]
    for doctype, filters in (
        (student_meals.DOCTYPE, {'student_group': GROUP, 'meal_date': ['!=', DAY]}),
        ('Student Attendance', {'student_group': GROUP, 'date': ['!=', DAY]}),
        ('Student Leave Application', {'student_group': GROUP}),
    ):
        names = frappe.get_list(doctype, filters=filters, pluck='name', limit_page_length=1001)
        if len(names) > 1000:
            raise RuntimeError('Synthetic fixture record bound exceeded')
        targets.extend((doctype, name) for name in names)
    hashes = {}
    for doctype, name in targets:
        doc = frappe.get_doc(doctype, name)
        doc.check_permission('read')
        data = json.dumps(doc.as_dict(), ensure_ascii=False, sort_keys=True, default=str).encode()
        hashes[doctype + ':' + name] = hashlib.sha256(data).hexdigest()
    return {'records': len(hashes), 'sha256': hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()}


def prepare(frappe, readonly_runner):
    if qa.safe_target(ATTEMPT).exists():
        raise RuntimeError('A native-write attempt already exists; inspect its retained evidence, never rerun')
    from tongjianyun import classroom, business_agent_authority as gates
    from tongjianyun.attendance_scope import allowed_groups
    def check():
        gates._account(OWNER, qa.SITE)
        if (allowed_groups() != [GROUP] or set(frappe.get_roles()) &
                {'System Manager', 'Education Manager', 'Tongjianyun Business Operator'}):
            raise PermissionError('Expected only the fixed synthetic ordinary teacher')
        group = classroom._scope(GROUP)
        if len(classroom._roster(group)) != 2:
            raise RuntimeError('Expected the untouched two-pupil synthetic fixture')
        gates._projection(gates.ATTENDANCE)
        gates._projection(gates.MEALS)
        gates._projection(gates.MEAL_ESTIMATES)
        capabilities = classroom._capabilities(classroom._day(DAY))
        if not capabilities['attendance_write'] or not capabilities['meals_write']:
            raise PermissionError('Original native fixture capabilities do not permit this acceptance')
        assert_empty_target(frappe)
        return {'status': 'prepared_read_only', 'site': qa.SITE, 'day': DAY, 'meal': MEAL,
                'isolation': isolation(frappe), 'empty_day_verified': True,
                'planned_native_commits': ['one_pupil_attendance', 'one_complete_class_lunch'],
                'planned_stale_revision_rollbacks': 2, 'business_writes_performed': False,
                'model_calls': 0, 'before': protected_digest(frappe)}
    return readonly_runner(OWNER, check)


def mark_attempt(folder):
    path = qa.safe_target(ATTEMPT)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump({'site': qa.SITE, 'day': DAY, 'evidence': str(folder / 'evidence.json'),
                   'purpose': 'Explicit one-shot native QA write; never automatic retry'}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    if os.name == 'posix':
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def require_prepared(prepared):
    if (not isinstance(prepared, dict) or prepared.get('status') != 'prepared_read_only'
            or prepared.get('site') != qa.SITE or prepared.get('day') != DAY
            or prepared.get('isolation') != 'REPEATABLE-READ' or prepared.get('empty_day_verified') is not True):
        raise RuntimeError('Explicit fixed-site read-only preparation is required')


def execute(frappe, readonly_runner, before_connect, readonly, prepared):
    require_prepared(prepared)
    from tongjianyun import business_agent_authority as gates, classroom, student_meals, daily_meals, attendance_scope
    from tongjianyun import business_agent_write_adapter as native, business_agent_writes as writes
    from tongjianyun import business_agent_tasks as tasks, business_agent_tools as tools
    from tongjianyun.business_agent_tasks import BusinessTaskStore, TaskIdentity, QueueObservation, ExecutionObservation
    source_modules = (gates, native, writes, classroom, student_meals, daily_meals, attendance_scope, tasks, tools)
    if (not Path(__file__).resolve().is_relative_to(qa.SOURCE)
            or not all(Path(module.__file__).resolve().is_relative_to(qa.SOURCE) for module in source_modules)):
        raise RuntimeError('Acceptance must use only the candidate source')
    # Recheck immediately before reserving the one-shot marker. Never reuse a
    # previous prepared report as permission to overwrite new fixture records.
    readonly_runner(OWNER, lambda: assert_empty_target(frappe))
    folder = qa.safe_target(qa.ROOT / ('business-native-write-' + uuid.uuid4().hex[:10]))
    folder.mkdir(mode=0o700)
    mark_attempt(folder)
    output = folder / 'evidence.json'
    evidence = {'version': 1, 'site': qa.SITE, 'day': DAY, 'checks': [], 'all_passed': False,
                'preparation': prepared, 'model_calls': 0, 'queue_used': False, 'production_access': False,
                'users_modified': False, 'sessions_modified': False, 'retained_records': True,
                'protected_digest_scope': 'Own-class Student/Student Group and preexisting Attendance/Leave/ClassMeal sources only; not a whole-QA database digest',
                'expected_native_side_effects': ['target-day Daily Confirmation create/refresh', 'target class-meal Info Comment'],
                'store_purpose': 'Synthetic ledger acceptance only; no runner is launched',
                'script_sha256': qa.digest_file(Path(__file__)),
                'source_hashes': {Path(module.__file__).name: qa.digest_file(Path(module.__file__)) for module in source_modules}}
    qa.private_json(output, evidence)  # even initialization failure leaves a retained, non-success report
    def check(name, passed):
        item = {'name': name, 'passed': bool(passed)}
        evidence['checks'].append(item)
        qa.private_json(output, evidence)
        print(json.dumps(item), flush=True)
        if not passed:
            raise AssertionError(name)

    reader = gates.FrappeBusinessAuthority(qa.SITE, run_check=readonly_runner)
    store_dir, ledger_dir = folder / 'tasks', folder / 'writes'
    store_dir.mkdir(mode=0o700)
    ledger_dir.mkdir(mode=0o700)
    store = BusinessTaskStore(store_dir, qa.SITE, authorize=reader,
        observe_queue=lambda job: QueueObservation(job, 'unknown'),
        observe_execution=lambda identity, claim: ExecutionObservation(claim, 'unknown', 0))
    identity = TaskIdentity(qa.SITE, OWNER, str(uuid.uuid4()))
    adapter = native.FrappeWriteAdapter(qa.SITE, str(qa.SITES), store=store, before_connect=before_connect)
    ledger = writes.BusinessWriteLedger(ledger_dir, qa.SITE, authorize=adapter.authorize)
    stale_context, stale_open, claim = Context(), False, None
    transactions = []
    class ObservedTransaction:
        def __init__(self, transaction): self.transaction = transaction
        def begin(self):
            self.transaction.begin()
            self.transaction._context.run(lambda: isolation(frappe))
        def save(self): return self.transaction.save()
        def commit(self): return self.transaction.commit()
        def rollback(self): return self.transaction.rollback()
        def close(self): return self.transaction.close()
    def factory(current, tool, arguments):
        tx = adapter.transaction_factory(current, tool, arguments)
        if tx._database is not None:
            raise RuntimeError('Factory unexpectedly connected before begin')
        transactions.append(tx)
        return ObservedTransaction(tx)
    def publish(current, selection):
        scopes = adapter.authority.view_scopes(current.identity, selection)
        adapter.authority.register_read(store, current, gates.ReadSet(scopes))
        store.emit(current, {'kind': 'view', 'version': 1, 'selection': selection, 'title': '隔离QA原生提交回读'})
    business = writes.BusinessWrites(ledger, transaction_factory=factory, fresh_read=adapter.fresh_read, publish_view=publish)
    try:
        store.create(OWNER, identity.task_id, '隔离QA：明确登记一名学生出勤并核对午餐', {'day': DAY, 'meal': MEAL})
        ticket = store.take_dispatch(identity)
        store.acknowledge_dispatch(ticket)
        claim = store.claim(identity, ticket.job_id)  # local metadata, not RQ/model execution
        ledger.open_task(claim)
        initial = reader.read_attendance(store, claim, group=GROUP, day=DAY)
        pupil_ids = [row['student'] for row in initial['students']]
        check('initial_roster_has_two_unknown_students', len(pupil_ids) == 2 and
              all(row['status'] == 'Unknown' for row in initial['students']))
        def open_stale():
            frappe.init(qa.SITE, sites_path=str(qa.SITES))
            before_connect()
            frappe.connect(set_admin_as_user=False)
            frappe.set_user(OWNER)
            readonly()
            isolation(frappe)
            return frappe.db.count('Student Attendance', {'student_group': GROUP, 'date': DAY})
        stale_open = True
        check('old_read_only_snapshot_started_empty', stale_context.run(open_stale) == 0)
        attendance_args = {'group': GROUP, 'day': DAY, 'revision': initial['revision'],
                           'changes': [{'student': pupil_ids[0], 'status': 'Present'}]}
        saved = business.dispatch(claim, 'attendance_save', attendance_args, 'attendance-initial')
        check('attendance_commit_ack_and_full_fresh_readback', saved['status'] == 'committed'
              and saved['readback_available'] and not saved['host_write_active']
              and next(row['status'] for row in saved['readback']['students'] if row['student'] == pupil_ids[0]) == 'Present')
        check('default_repeatable_read_old_snapshot_cannot_substitute_for_fresh_read', stale_context.run(
            lambda: frappe.db.count('Student Attendance', {'student_group': GROUP, 'date': DAY})) == 0)
        check('new_source_registered_before_delivery', any(scope.get('doctype') == 'Student Attendance'
              and scope.get('kind') == 'document' for scope in store.required_scopes(identity)))
        replay = business.dispatch(claim, 'attendance_save', attendance_args, 'attendance-replay-new-id')
        check('same_digest_new_call_returns_receipt_without_transaction', replay['replayed']
              and replay['operation_id'] == saved['operation_id'] and len(transactions) == 1)
        conflict_args = {**attendance_args, 'changes': [{'student': pupil_ids[0], 'status': 'Absent'}]}
        conflict = business.dispatch(claim, 'attendance_save', conflict_args, 'attendance-stale-conflict')
        check('native_attendance_stale_revision_rolls_back', conflict['status'] == 'rolled_back'
              and conflict['committed'] is False and not conflict['host_write_active'])
        current = reader.read_attendance(store, claim, group=GROUP, day=DAY)
        check('attendance_conflict_did_not_change_committed_revision', current['revision'] == saved['readback']['revision'])

        meal_initial = reader.read_meals(store, claim, group=GROUP, day=DAY)
        check('no_meal_actual_fabricated_from_attendance', not meal_initial['revision']
              and all(item['actual'] is None for item in meal_initial['meals'].values()))
        meal_args = {'group': GROUP, 'day': DAY, 'meal': MEAL, 'revision': meal_initial['revision'], 'confirm': True,
                     'students': [{'student': sid, 'value': '就餐' if sid == pupil_ids[0] else '不就餐'} for sid in pupil_ids]}
        meal_saved = business.dispatch(claim, 'meal_save', meal_args, 'meal-initial')
        check('one_meal_commit_and_other_actuals_stay_unknown', meal_saved['status'] == 'committed'
              and meal_saved['readback_available'] and meal_saved['readback']['meals'][MEAL]['actual'] == 1
              and all(item['actual'] is None for meal, item in meal_saved['readback']['meals'].items() if meal != MEAL))
        stale_meal = {**meal_args, 'change_reason': '仅QA验证旧修订拒绝，绝不覆盖已核对记录',
                      'students': [{'student': sid, 'value': '不就餐'} for sid in pupil_ids]}
        meal_conflict = business.dispatch(claim, 'meal_save', stale_meal, 'meal-stale-conflict')
        check('native_meal_stale_revision_rolls_back', meal_conflict['status'] == 'rolled_back'
              and meal_conflict['committed'] is False and not meal_conflict['host_write_active'])
        meal_current = reader.read_meals(store, claim, group=GROUP, day=DAY)
        check('meal_conflict_did_not_change_committed_snapshot', meal_current == meal_saved['readback'])
        denied = False
        try:
            business.dispatch(claim, 'meal_save', {**meal_args, 'group': OTHER}, 'foreign-class-denied')
        except (PermissionError, frappe.PermissionError):
            denied = True
        check('other_class_denied_before_new_transaction', denied and len(transactions) == 4)
        check('all_native_write_connections_closed_and_no_uncertain_operation',
              all(tx._closed for tx in transactions) and ledger.observe(identity, claim.claim_id).active_writes == 0
              and ledger.observe(identity, claim.claim_id).uncertain_writes == 0)
        views = [event for event in store.events(identity) if event['kind'] == 'view']
        check('view_events_contain_only_current_selection_not_pupil_snapshots', len(views) == 3 and
              all('students' not in event and event['selection']['group'] == GROUP and event['selection']['day'] == DAY for event in views))
        evidence['protected_after'] = readonly_runner(OWNER, lambda: protected_digest(frappe))
        check('preexisting_own_class_source_digest_unchanged', evidence['protected_after'] == prepared['before'])
        def retained_counts():
            return {
                'attendance': frappe.db.count('Student Attendance', {'student_group': GROUP, 'date': DAY}),
                'class_meal': frappe.db.count(student_meals.DOCTYPE, {'student_group': GROUP, 'meal_date': DAY}),
                'daily_confirmation': frappe.db.count(daily_meals.CONFIRMATION_DOCTYPE, {'meal_date': DAY}),
                'daily_adjustment': frappe.db.count(daily_meals.ADJUSTMENT_DOCTYPE, {'meal_date': DAY}),
                'meal_info_comments': frappe.db.count('Comment', {'reference_doctype': student_meals.DOCTYPE,
                    'reference_name': student_meals.record_name(DAY, GROUP), 'comment_type': 'Info'}),
            }
        evidence['retained_native_records'] = readonly_runner(OWNER, retained_counts)
        counts = evidence['retained_native_records']
        check('expected_native_records_and_comment_retained', counts['attendance'] == 1 and counts['class_meal'] == 1
              and counts['daily_confirmation'] == 1 and counts['daily_adjustment'] == 0 and counts['meal_info_comments'] >= 1)
        evidence['all_passed'] = True
    except BaseException as error:
        evidence['failure_type'] = type(error).__name__
        raise
    finally:
        if claim is not None:
            ledger.close_task(identity, claim.claim_id)
            observation = ledger.observe(identity, claim.claim_id)
            evidence['host_gate'] = {'admission_closed': observation.admission_closed,
                                     'active_writes': observation.active_writes, 'uncertain_writes': observation.uncertain_writes}
        if stale_open:
            stale_context.run(frappe.destroy)
        qa.private_json(output, evidence)
        print(json.dumps({'evidence': str(output), 'all_passed': evidence['all_passed']}), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Explicitly execute the fixed, one-shot synthetic QA writes and retain records')
    args = parser.parse_args(argv)
    frappe, _, runner, before_connect, readonly = fixture.setup()
    prepared = prepare(frappe, runner)
    print(json.dumps(prepared), flush=True)
    if args.run:
        execute(frappe, runner, before_connect, readonly, prepared)


if __name__ == '__main__':
    main()
