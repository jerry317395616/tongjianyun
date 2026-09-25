"""Real teacher business-tool/ledger acceptance, in the fixed isolated QA only.

No Codex/model, production, account-role changes, migration or web service.
The preflight day is fixed and must be unused across the entire synthetic site.
Every attempt preserves a marker/evidence; an interrupted attempt is NOT rerun.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unified_business'))
import serve_isolated_browser as qa

DAY = '2026-09-16'
MEAL = 'lunch'
TEACHER = 'teacher-scope-9680e04d9f@example.invalid'
GROUP = 'QA Teacher 9680e04d9f Assigned'
OTHER = 'QA Teacher 9680e04d9f Other'
STUDENTS = ('EDU-STU-2026-00012', 'EDU-STU-2026-00013')
MARKER = qa.ROOT / 'business-tools-20260916.json'
DOCS = (('Student Attendance', 'date'), ('Tongjianyun Class Meal Confirmation', 'meal_date'),
        ('Tongjianyun Daily Meal Confirmation', 'meal_date'))


def stable(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def digest(value):
    return hashlib.sha256(json.dumps(stable(value), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def fixture_guard():
    if sys.flags.optimize:
        raise RuntimeError('Optimized Python would disable inherited QA assertions; execution is refused')
    qa.config_guard()
    state = json.loads(qa.safe_target(qa.STATE).read_text())
    assert (state['owner'], state['site'], state['teacher'], state['group']) == (
        qa.TASK, qa.SITE, TEACHER, GROUP)
    assert DAY not in {'2026-09-17', '2026-09-18', '2026-09-25'}
    return state


def untouched_day(frappe):
    for doctype, field in DOCS:
        assert not frappe.db.exists(doctype, {field: DAY}), 'QA day is already used; preserve records and stop'
    assert not frappe.db.exists('Student Leave Application', {'from_date': ['<=', DAY], 'to_date': ['>=', DAY]}), \
        'A leave overlaps the proposed fixture day; do not reinterpret that history'


def account_guard(frappe):
    previous = frappe.session.user
    try:
        frappe.set_user(TEACHER)
        account = frappe.db.get_value('User', TEACHER, ['enabled', 'user_type'], as_dict=True)
        assert account and account.enabled and account.user_type == 'System User'
        roles = set(frappe.get_roles())
        assert {'Instructor', 'Academics User'} <= roles
        assert not roles & {'System Manager', 'Education Manager', 'Tongjianyun Business Operator'}
        from tongjianyun.attendance_scope import allowed_groups
        from tongjianyun.classroom import _scope, _roster
        assert allowed_groups() == [GROUP]
        assert [row['student'] for row in _roster(_scope(GROUP))] == list(STUDENTS)
        return sorted(roles)
    finally:
        frappe.set_user(previous)


def protected_snapshot(frappe):
    assert frappe.session.user == 'Administrator'
    result = {}
    for doctype, field in DOCS:
        fields = ['name', field] + (['student_group'] if doctype != 'Tongjianyun Daily Meal Confirmation' else [])
        rows = frappe.get_all(doctype, fields=fields, limit_page_length=1001)
        assert len(rows) <= 1000, 'QA diagnostic scope exceeded its fixed bound'
        for row in rows:
            target = str(row.get(field)) == DAY and (doctype == 'Tongjianyun Daily Meal Confirmation' or row.student_group == GROUP)
            if not target:
                result[doctype + ':' + row.name] = digest(frappe.get_doc(doctype, row.name).as_dict())
    for name in (GROUP, OTHER):
        result['Student Group:' + name] = digest(frappe.get_doc('Student Group', name).as_dict())
    result['User:' + TEACHER] = digest(frappe.get_doc('User', TEACHER).as_dict())
    return result


def connect():
    frappe = qa.connect()
    # Fresh account checks must not accidentally share an old RR snapshot. This
    # affects this dedicated connection only, not site/global database settings.
    frappe.db.rollback()
    frappe.db.sql('SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED')
    return frappe


def preflight():
    fixture_guard()
    assert not MARKER.exists(), 'An attempt already exists; inspect retained evidence, never rerun blindly'
    frappe = connect()
    try:
        frappe.db.sql('START TRANSACTION READ ONLY')
        untouched_day(frappe)
        roles = account_guard(frappe)
        protected = protected_snapshot(frappe)
        print(json.dumps({'status': 'ready', 'site': qa.SITE, 'day': DAY,
                          'protected_records': len(protected), 'teacher_roles': roles, 'business_writes': False}))
    finally:
        frappe.db.rollback()
        frappe.destroy()


def execute():
    fixture_guard()
    assert not MARKER.exists(), 'An attempt already exists; inspect retained evidence, never rerun blindly'
    frappe = connect()
    from redis import Redis, WatchError
    from tongjianyun import business_agent_tools as tools, business_agent_transport as transport, student_meals
    for module in (tools, transport):
        assert Path(module.__file__).resolve().is_relative_to(qa.SOURCE)
    run = uuid.uuid4().hex[:10]
    task_id = str(uuid.uuid4())
    directory = qa.safe_target(qa.ROOT / ('business-tools-' + run))
    output = qa.safe_target(directory / 'evidence.json')
    redis = None
    evidence = {'version': 1, 'run_id': run, 'site': qa.SITE, 'task_id': task_id, 'day': DAY, 'meal': MEAL,
                'teacher': TEACHER, 'group': GROUP, 'checks': [], 'status': 'preflight',
                'production_writes': False, 'codex_executed': False, 'browser_ui_tested': False,
                'existing_user_roles_changed': False, 'existing_users_disabled': False,
                'source': {module.__name__: qa.digest_file(Path(module.__file__)) for module in (tools, transport)},
                'transaction_isolation': 'READ COMMITTED on QA connection only'}

    def record(label, condition):
        assert condition, label
        evidence['checks'].append(label)
        qa.private_json(output, stable(evidence))
        print(json.dumps({'passed': label}), flush=True)

    def denied(label, operation, expected=None):
        try:
            operation()
        except expected or (frappe.PermissionError, frappe.ValidationError, ValueError):
            record(label, True)
        else:
            raise AssertionError(label + ': unexpectedly accepted')

    try:
        untouched_day(frappe)
        roles = account_guard(frappe)
        protected = protected_snapshot(frappe)
        directory.mkdir(mode=0o700)
        qa.private_json(MARKER, {'run_id': run, 'evidence': str(output), 'day': DAY,
                                 'site': qa.SITE, 'state': 'attempt_started_do_not_repeat'})
        evidence.update(status='running', roles_before=roles, protected_before=protected)
        qa.private_json(output, evidence)
        disabled = 'business-tools-disabled-' + run + '@example.invalid'
        frappe.get_doc({'doctype': 'User', 'email': disabled, 'first_name': 'Disabled QA ' + run,
                        'enabled': 0, 'user_type': 'System User', 'send_welcome_email': 0,
                        'roles': [{'role': 'Instructor'}]}).insert()
        frappe.db.commit()
        evidence['new_disabled_synthetic_user'] = disabled
        account = frappe.db.get_value('User', disabled, ['enabled', 'user_type'], as_dict=True)
        record('negative_fixture_is_disabled_from_creation_and_system_user', account.enabled == 0 and account.user_type == 'System User')

        redis = Redis.from_url(frappe.conf.redis_queue, decode_responses=True)
        key = f'business-codex-qa:v1:{qa.SITE}:{task_id}:task'
        events = key + ':events'
        assert not redis.exists(key) and 'meal-chat' not in key
        task = {'task_id': task_id, 'owner': TEACHER, 'site': qa.SITE, 'mode': 'business',
                'status': 'running', 'cancel_requested': '0'}
        redis.hset(key, mapping=task)
        evidence['qa_redis_task_key'] = key

        def read_task(wanted):
            assert wanted == task_id
            return redis.hgetall(key)

        def publish(binding, event):
            tools.validate_binding(binding)
            with redis.pipeline() as pipe:
                pipe.watch(key)
                assert pipe.hgetall(key) == task
                assert set(event) == {'kind', 'version', 'selection', 'title'} and event['kind'] == 'view'
                pipe.multi()
                pipe.xadd(events, {'data': json.dumps(event, ensure_ascii=False)})
                try:
                    pipe.execute()
                except WatchError:
                    raise frappe.PermissionError('QA task changed before publication')

        identity = {field: task[field] for field in ('site', 'owner', 'task_id', 'mode')}
        ledger = transport.DurableWriteLedger(directory, identity, validate=lambda bound: tools.validate_binding(bound, lock_owner=True),
                    commit=frappe.db.commit, rollback=frappe.db.rollback, outcome=tools.WriteOutcome)
        binding = tools.BusinessBinding(TEACHER, qa.SITE, task_id, read_task, publish, ledger)
        context = {'group': GROUP, 'day': DAY}
        attendance = tools.dispatch(binding, 'classroom_read', context)
        meals = tools.dispatch(binding, 'meal_read', context)
        record('fresh_teacher_roster_and_unknown_attendance', [row['student'] for row in attendance['students']] == list(STUDENTS)
               and all(row['status'] == 'Unknown' for row in attendance['students']))
        record('fresh_meal_revision_empty_all_actual_unknown', not meals['revision']
               and all(facts['actual'] is None for facts in meals['meals'].values()))
        evidence['expected_before'] = {row['student']: {meal: row[meal + '_expected'] for meal in student_meals.MEALS}
                                       for row in meals['students']}
        bootstrap = tools.dispatch(binding, 'scene_bootstrap', {**context, 'meal': MEAL})
        record('bootstrap_keeps_teacher_class_scope', bootstrap['scope'] == {'group_count': 1, 'selected_group': GROUP})
        view = tools.dispatch(binding, 'business_view', {'selection': {'view': 'classroom_day', **context}})
        record('view_publishes_only_selection_not_full_business_payload', view['display_requested'] and 'components' not in view
               and redis.xlen(events) == 1)

        denied('foreign_class_read_denied', lambda: tools.dispatch(binding, 'classroom_read', {'group': OTHER, 'day': DAY}))
        denied('foreign_class_meal_read_denied', lambda: tools.dispatch(binding, 'meal_read', {'group': OTHER, 'day': DAY}))
        denied('root_project_view_denied', lambda: tools.dispatch(binding, 'business_view', {'selection': {'view': 'project_catalog'}}))
        denied('actor_override_argument_denied', lambda: tools.dispatch(binding, 'classroom_read', {**context, 'actor': 'Administrator'}))
        for field, value in [('mode', 'admin_project'), ('cancel_requested', '1'), ('status', 'complete'), ('owner', 'Administrator')]:
            redis.hset(key, field, value)
            denied('changed_task_' + field + '_denied', lambda: tools.dispatch(binding, 'classroom_read', context))
            redis.hset(key, field, task[field])
        redis.hset(key, 'owner', disabled)
        denied('real_disabled_account_denied', lambda: tools.dispatch(replace(binding, owner=disabled), 'classroom_read', context))
        redis.hset(key, 'owner', TEACHER)
        record('negative_checks_restore_broker_actor', frappe.session.user == 'Administrator')

        att_args = {**context, 'revision': attendance['revision'],
                    'changes': [{'student': STUDENTS[0], 'status': 'Present'}]}
        att_binding = replace(binding, call_id='attendance-original')
        att_result = tools.dispatch(att_binding, 'attendance_save', att_args)
        record('attendance_tool_committed_true_teacher_fact', att_result['committed'] and not att_result['replayed']
               and [row['status'] for row in att_result['readback']['students']] == ['Present', 'Unknown'])
        again = tools.dispatch(att_binding, 'attendance_save', att_args)
        alias = tools.dispatch(replace(binding, call_id='attendance-alias'), 'attendance_save', att_args)
        record('attendance_same_call_and_same_digest_new_call_only_replay', again['replayed'] and alias['replayed']
               and again['readback'] == att_result['readback'] == alias['readback'])
        denied('alias_cannot_change_operation_after_receipt', lambda: tools.dispatch(
            replace(binding, call_id='attendance-alias'), 'attendance_save', {**att_args, 'revision': 'b' * 64}))
        # Attendance recomputation may legitimately update derived estimates;
        # reread before the meal write and preserve all unrelated meal values.
        meals = tools.dispatch(binding, 'meal_read', context)
        evidence['meal_before_write'] = meals
        meal_args = {**context, 'meal': MEAL, 'revision': meals['revision'], 'confirm': True,
                     'students': [{'student': STUDENTS[0], 'value': '就餐'}, {'student': STUDENTS[1], 'value': '不就餐'}]}
        meal_result = tools.dispatch(replace(binding, call_id='meal-original'), 'meal_save', meal_args)
        record('meal_tool_committed_lunch_one_only', meal_result['committed'] and not meal_result['replayed']
               and meal_result['readback']['meals'][MEAL]['actual'] == 1)
        repeat = tools.dispatch(replace(binding, call_id='meal-original'), 'meal_save', meal_args)
        alias = tools.dispatch(replace(binding, call_id='meal-alias'), 'meal_save', meal_args)
        record('meal_same_call_and_same_digest_new_call_only_replay', repeat['replayed'] and alias['replayed'])
        evidence['receipt_revisions'] = {'attendance': att_result['readback']['revision'], 'meal': meal_result['readback']['revision']}
        record('tool_calls_always_restore_original_broker_actor', frappe.session.user == 'Administrator')

        # A completely new connection verifies persisted records, never a mock
        # write acknowledgement or this transaction's in-memory Document cache.
        frappe.db.rollback()
        frappe.destroy()
        frappe = connect()
        frappe.db.sql('START TRANSACTION READ ONLY')
        record('protected_cross_class_other_dates_user_roles_and_rosters_unchanged', protected_snapshot(frappe) == protected)
        record('original_teacher_roles_preserved', account_guard(frappe) == roles)
        fresh_attendance = tools.dispatch(binding, 'classroom_read', context)
        fresh_meals = tools.dispatch(binding, 'meal_read', context)
        record('new_connection_attendance_is_one_present_one_unknown', [row['status'] for row in fresh_attendance['students']] == ['Present', 'Unknown'])
        by_student = {row['student']: row for row in fresh_meals['students']}
        record('new_connection_meal_has_exact_full_roster_and_actual_states', set(by_student) == set(STUDENTS)
               and by_student[STUDENTS[0]][MEAL] == '已就餐' and by_student[STUDENTS[1]][MEAL] == '未就餐')
        record('other_four_meals_unchanged_and_unknown', all(
            by_student[row['student']][meal] == row[meal]
            and by_student[row['student']][meal + '_expected'] == row[meal + '_expected']
            for row in meals['students'] for meal in student_meals.MEALS if meal != MEAL)
               and all(fresh_meals['meals'][meal]['actual'] is None for meal in student_meals.MEALS if meal != MEAL))
        native = frappe.get_all('Student Attendance', filters={'student_group': GROUP, 'date': DAY},
            fields=['name', 'student', 'status', 'docstatus', 'owner', 'modified_by'], limit_page_length=0)
        record('one_native_attendance_no_duplicate_and_teacher_audit', len(native) == 1 and native[0].student == STUDENTS[0]
               and native[0].status == 'Present' and native[0].docstatus == 1
               and native[0].owner == native[0].modified_by == TEACHER)
        record_doc = frappe.get_doc(student_meals.DOCTYPE, student_meals.record_name(DAY, GROUP))
        record('class_meal_true_teacher_owner_and_not_false_whole_day_confirmation', record_doc.owner == record_doc.modified_by == TEACHER
               and record_doc.status == '待确认' and not record_doc.confirmed_by and not record_doc.confirmed_at)
        comments = frappe.get_all('Comment', filters={'reference_doctype': student_meals.DOCTYPE,
            'reference_name': record_doc.name, 'comment_type': 'Info'}, fields=['owner', 'comment_email', 'content'], limit_page_length=0)
        markers = [row for row in comments if '午餐实际就餐已按班级名单核对' in (row.content or '')]
        record('one_native_meal_audit_marker_despite_retries', len(markers) == 1 and markers[0].owner == markers[0].comment_email == TEACHER)
        daily = frappe.db.get_value('Tongjianyun Daily Meal Confirmation', {'meal_date': DAY}, ['name', 'status'], as_dict=True)
        record('derived_daily_record_not_falsely_confirmed', daily and daily.status == '待确认')
        evidence.update(retained_records={'attendance': [row.name for row in native], 'class_meal': record_doc.name,
                                          'daily': daily.name, 'disabled_user': disabled},
                        new_connection_readback=True, status='passed')
        redis.hset(key, 'status', 'complete')
        denied('completed_task_real_redis_denied', lambda: tools.dispatch(binding, 'meal_read', context))
        qa.private_json(output, stable(evidence))
        print(json.dumps({'status': 'passed', 'run_id': run, 'passed': len(evidence['checks']),
                          'evidence_file': str(output), 'production_writes': False, 'codex_executed': False}))
        return 0
    except BaseException as error:
        evidence.update(status='failed', failure={'type': type(error).__name__, 'message': str(error)})
        if output.parent.exists():
            qa.private_json(output, stable(evidence))
        if redis is not None:
            redis.hset(key, 'status', 'failed')
        print(json.dumps({'status': 'failed', 'run_id': run, 'passed': len(evidence['checks']),
                          'evidence_file': str(output), 'failure_type': type(error).__name__}), flush=True)
        raise
    finally:
        if getattr(frappe.local, 'site', None):
            frappe.db.rollback()
            frappe.destroy()
        if redis is not None:
            redis.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Perform the retained synthetic teacher writes after all guards')
    args = parser.parse_args()
    raise SystemExit(execute() if args.execute else preflight())
