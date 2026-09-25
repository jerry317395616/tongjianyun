"""Independent READ ONLY baseline/readback for the existing synthetic teacher.

Uses the versioned loopback QA guard. Never creates users, changes roles, reads
credentials or saves business documents. `prepare` must precede browser writes;
`verify` never treats an after-save snapshot as a pre-save baseline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import uuid

import serve_isolated_browser as qa

DAY = '2026-09-17'
MEAL = 'lunch'
TEACHER = 'teacher-scope-9680e04d9f@example.invalid'
GROUP = 'QA Teacher 9680e04d9f Assigned'
STUDENTS = ('EDU-STU-2026-00012', 'EDU-STU-2026-00013')
BASELINE = qa.ROOT / 'teacher-browser-baseline-20260917.json'
MANAGER_ROLES = {'System Manager', 'Education Manager', 'Tongjianyun Business Operator'}


def stable(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def digest(value):
    return hashlib.sha256(json.dumps(stable(value), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def fixture():
    qa.config_guard()
    state = json.loads(qa.safe_target(qa.STATE).read_text())
    assert (state['owner'], state['site'], state['teacher'], state['group'], state['meal']) == (
        qa.TASK, qa.SITE, TEACHER, GROUP, MEAL)
    # Existing manager fixture intentionally retains its earlier date.
    assert state['day'] == '2026-09-18'
    return {key: state[key] for key in ('owner', 'site', 'teacher', 'group', 'meal')}


def check_account(frappe):
    assert frappe.session.user == TEACHER
    account = frappe.db.get_value('User', TEACHER, ['enabled', 'user_type'], as_dict=True)
    assert account and account.enabled and account.user_type == 'System User'
    roles = set(frappe.get_roles())
    assert {'Instructor', 'Academics User'} <= roles and not roles & MANAGER_ROLES
    from tongjianyun.attendance_scope import allowed_groups
    assert allowed_groups() == [GROUP]
    return sorted(roles)


def teacher_facts(frappe):
    from tongjianyun import classroom
    group = classroom._scope(GROUP, workspace='teacher')
    roster = classroom._roster(group)
    assert [row['student'] for row in roster] == list(STUDENTS), 'Roster/order changed; do not guess UI row identity'
    attendance = classroom._attendance(group, classroom._day(DAY))
    assert [row['student'] for row in attendance['students']] == list(STUDENTS)
    meals = classroom.get_meals(GROUP, DAY, workspace='teacher')
    return attendance, meals


def expected_fields(record, meal_keys):
    return {row['student']: {meal: row[meal + '_expected'] for meal in meal_keys}
            for row in record.get('students', [])}


def protected_snapshot(frappe):
    """QA diagnostic, under Administrator; hashes only, never grants teacher reads."""
    assert frappe.session.user == 'Administrator'
    result = {}
    for doctype, date_field in [('Student Attendance', 'date'),
                                ('Tongjianyun Class Meal Confirmation', 'meal_date'),
                                ('Tongjianyun Daily Meal Confirmation', 'meal_date')]:
        fields = ['name', date_field] + (['student_group'] if doctype != 'Tongjianyun Daily Meal Confirmation' else [])
        records = frappe.get_all(doctype, fields=fields, limit_page_length=1001)
        assert len(records) <= 1000, 'Fixture volume exceeded guarded diagnostic bound'
        for row in records:
            target = str(row.get(date_field)) == DAY and (doctype == 'Tongjianyun Daily Meal Confirmation' or row.student_group == GROUP)
            if not target:
                result[doctype + ':' + row.name] = digest(frappe.get_doc(doctype, row.name).as_dict())
    groups = frappe.get_all('Student Group', filters={'name': ['like', 'QA Teacher 9680e04d9f%']}, pluck='name')
    assert GROUP in groups and len(groups) == 2
    for name in groups:
        result['Student Group:' + name] = digest(frappe.get_doc('Student Group', name).as_dict())
    return result


def prepare():
    identity = fixture()
    if BASELINE.exists():
        baseline = json.loads(qa.safe_target(BASELINE).read_text())
        assert baseline['fixture'] == identity and baseline['day'] == DAY
        assert baseline['mode'] == 'pre_save_baseline' and baseline['students'] == list(STUDENTS)
        print(json.dumps({'status': 'existing_baseline_preserved', 'baseline_file': str(BASELINE),
                          'day': DAY, 'group': GROUP, 'business_writes': False}))
        return 0
    frappe = qa.connect()
    try:
        frappe.db.sql('START TRANSACTION READ ONLY')
        from frappe.utils import now_datetime
        from tongjianyun import student_meals
        captured_at = str(now_datetime())
        protected = protected_snapshot(frappe)
        frappe.set_user(TEACHER)
        roles = check_account(frappe)
        attendance, meals = teacher_facts(frappe)
        statuses = {row['student']: row['status'] for row in attendance['students']}
        assert statuses == dict.fromkeys(STUDENTS, 'Unknown')
        assert not frappe.db.exists('Student Attendance', {'student_group': GROUP, 'date': DAY})
        assert not frappe.db.exists(student_meals.DOCTYPE, {'student_group': GROUP, 'meal_date': DAY})
        assert all(meals['actual'][meal + '_count'] is None for meal in student_meals.MEALS)
        assert not meals['revision']
        assert set(expected_fields(meals['record'], student_meals.MEALS)) == set(STUDENTS)
        baseline = {'version': 1, 'mode': 'pre_save_baseline', 'fixture': identity,
                    'day': DAY, 'meal': MEAL, 'students': list(STUDENTS), 'roles': roles,
                    'captured_at': captured_at, 'statuses': statuses,
                    'expected': expected_fields(meals['record'], student_meals.MEALS),
                    'protected_hashes': protected, 'business_writes': False,
                    'read_only_transaction': True, 'student_names_recorded': False}
    finally:
        frappe.db.rollback()
        frappe.destroy()
    qa.private_json(BASELINE, baseline)
    print(json.dumps({'status': 'prepared', 'baseline_file': str(BASELINE), 'day': DAY, 'group': GROUP,
                      'protected_records': len(protected), 'business_writes': False, 'student_names_output': False}))
    return 0


def verify():
    identity = fixture()
    baseline = json.loads(qa.safe_target(BASELINE).read_text())
    assert baseline['mode'] == 'pre_save_baseline' and baseline['fixture'] == identity and baseline['day'] == DAY
    assert baseline['students'] == list(STUDENTS) and baseline['read_only_transaction'] and not baseline['business_writes']
    checks = []
    evidence = {'fixture': identity, 'day': DAY, 'meal': MEAL, 'baseline_file': str(BASELINE),
                'new_connection': True, 'read_only_transaction': True, 'business_writes': False,
                'production_writes': False, 'roles_changed': False, 'codex_executed': False,
                'student_names_recorded': False, 'audit_diagnostics_as': 'Administrator',
                'business_reads_as': TEACHER}
    def check(label, condition):
        checks.append({'check': label, 'passed': bool(condition)})
    def denied(label, call):
        try:
            call()
        except (frappe.PermissionError, frappe.ValidationError):
            check(label, True)
        else:
            check(label, False)
    frappe = qa.connect()
    try:
        frappe.db.sql('START TRANSACTION READ ONLY')
        from tongjianyun import classroom, student_meals, meal_chat, meal_views, scene_access
        check('cross_class_other_dates_and_rosters_unchanged', protected_snapshot(frappe) == baseline['protected_hashes'])
        frappe.set_user(TEACHER)
        check('original_teacher_roles_preserved', check_account(frappe) == baseline['roles'])
        attendance, meals = teacher_facts(frappe)
        statuses = {row['student']: row['status'] for row in attendance['students']}
        check('attendance_first_present_second_unknown', statuses == dict(zip(STUDENTS, ('Present', 'Unknown'))))
        native = frappe.get_list('Student Attendance', filters={'student_group': GROUP, 'date': DAY},
            fields=['name', 'student', 'status', 'docstatus', 'owner', 'modified_by', 'creation'], limit_page_length=0)
        check('one_native_attendance_not_second_student_or_cancelled_copy', len(native) == 1
              and native[0].student == STUDENTS[0] and native[0].status == 'Present' and native[0].docstatus == 1)
        check('attendance_true_teacher_actor', bool(native) and all(row.owner == TEACHER and row.modified_by == TEACHER for row in native))
        check('attendance_created_after_baseline', bool(native) and all(str(row.creation) >= baseline['captured_at'] for row in native))
        record = meals['record']
        by_student = {row['student']: row for row in record.get('students', [])}
        check('exact_class_meal_identity', record['name'] == student_meals.record_name(DAY, GROUP)
              and record['student_group'] == GROUP and str(record['meal_date']) == DAY and set(by_student) == set(STUDENTS))
        check('lunch_first_eaten_second_not_eaten', {key: row[MEAL] for key, row in by_student.items()} == dict(zip(STUDENTS, ('已就餐', '未就餐'))))
        check('actual_lunch_one_and_complete', meals['actual']['lunch_count'] == 1 and meals['meals'][MEAL]['complete'])
        other = [meal for meal in student_meals.MEALS if meal != MEAL]
        check('other_four_meals_still_unknown', all(row[meal] == '未确认' for row in by_student.values() for meal in other)
              and all(meals['actual'][meal + '_count'] is None and not meals['meals'][meal]['complete'] for meal in other))
        check('expected_matches_independent_presave_baseline', expected_fields(record, student_meals.MEALS) == baseline['expected'])
        check('class_day_not_falsely_confirmed', record['status'] == '待确认' and not record.get('confirmed_by') and not record.get('confirmed_at'))
        check('meal_true_teacher_actor', record['owner'] == TEACHER and record['modified_by'] == TEACHER)
        check('meal_created_after_baseline', str(record['creation']) >= baseline['captured_at'])
        for action in ('read', 'create', 'write'):
            check('teacher_daily_' + action + '_still_denied', not frappe.has_permission('Tongjianyun Daily Meal Confirmation', action))
        denied('root_codex_chat_still_denied', meal_chat.require_chat_access)
        denied('project_directory_still_denied', lambda: meal_views.get_view({'view': 'project_catalog'}))
        denied('native_daily_record_still_denied', lambda: meal_views.get_view({'view': 'frappe_doctype', 'doctype': 'Tongjianyun Daily Meal Confirmation'}))
        bootstrap = scene_access.get_bootstrap(day=DAY, meal=MEAL, group=GROUP)
        check('teacher_bootstrap_has_no_codex_execution', not bootstrap['chat']['allowed'])
        check('teacher_own_view_reads_actual_one', meal_views.get_view({'view': 'meal_counts', 'day': DAY, 'meal': MEAL, 'group': GROUP})['summary']['facts']['actual'] == 1)
        # Audit evidence is a privileged QA diagnostic. No Version/Comment read
        # permission is added to the teacher or the ordinary scene response.
        frappe.set_user('Administrator')
        comments = frappe.get_all('Comment', filters={'reference_doctype': student_meals.DOCTYPE,
            'reference_name': record['name'], 'comment_type': 'Info'},
            fields=['name', 'owner', 'comment_email', 'creation', 'content'], limit_page_length=0)
        markers = [row for row in comments if '午餐实际就餐已按班级名单核对' in (row.content or '')]
        check('one_native_lunch_audit_marker_with_true_actor', len(markers) == 1 and all(
            row.owner == TEACHER and row.comment_email == TEACHER and str(row.creation) >= baseline['captured_at'] for row in markers))
        daily = frappe.db.get_value('Tongjianyun Daily Meal Confirmation', {'meal_date': DAY},
            ['name', 'status', 'confirmed_by', 'confirmed_at'], as_dict=True)
        check('daily_summary_not_falsely_confirmed', bool(daily) and daily.status == '待确认' and not daily.confirmed_by and not daily.confirmed_at)
        evidence.update(statuses=statuses, actual=meals['actual'], expected=meals['expected'],
            class_meal=record['name'], attendance_records=[row.name for row in native],
            audit_markers=[{key: row[key] for key in ('name', 'owner', 'comment_email', 'creation')} for row in markers],
            daily=daily, protected_records=len(baseline['protected_hashes']))
    finally:
        frappe.db.rollback()
        frappe.destroy()
    evidence.update(checks=checks, passed=sum(row['passed'] for row in checks), total=len(checks),
                    status='passed' if checks and all(row['passed'] for row in checks) else 'failed')
    output = qa.ROOT / ('teacher-browser-readback-' + uuid.uuid4().hex[:10] + '.json')
    qa.private_json(output, stable(evidence))
    print(json.dumps({'evidence_file': str(output), 'status': evidence['status'], 'passed': evidence['passed'],
                      'total': evidence['total'], 'checks': checks, 'business_writes': False,
                      'student_names_output': False}, ensure_ascii=False))
    return 0 if evidence['status'] == 'passed' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'verify'])
    args = parser.parse_args()
    raise SystemExit(prepare() if args.mode == 'prepare' else verify())
