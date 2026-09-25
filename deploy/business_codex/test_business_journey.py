"""Pure journey guards: no Frappe site, model, Redis, business write or service."""
import copy
import importlib.util
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('business_journey_tests_target', Path(__file__).with_name('serve_business_journey.py'))
j = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(j)
RUN = 'a5fa54b8-94fd-4f05-a0d9-36a97f7c5379'
TASK = 'd3fe839b-b713-4633-a0bb-e57c889e65b7'
CLAIM = '017e09b5-779b-4b1b-944b-1794e2a4df2d'


def record(profile='business-save'):
    return {'run_id': RUN, 'profile': profile, 'site': j.qa.SITE, 'source_sha256': {}, 'previous': {'old_failure_retained': True}}


def send(profile='business-save'):
    return {'request_id': TASK, 'message': j.requested_message(profile), 'day': j.DAY,
            'meal': j.MEAL, 'stream': 1, 'view_context': {'view': 'classroom_day', 'day': j.DAY,
                'meal': j.MEAL, 'group': j.fixture.GROUP}}


def attendance():
    return {'group': j.fixture.GROUP, 'day': j.DAY, 'revision': 'a' * 64,
            'changes': [{'student': j.fixture.STUDENTS[0], 'status': 'Present'}]}


def row(doctype, name, **scope):
    return {'doctype': doctype, 'name': name, 'scope': scope, 'fields': j.flatten(scope)}


def snapshot(rows=()):
    values = {value['doctype'] + ':' + value['name']: value for value in rows}
    return {'site': j.qa.SITE, 'records': values, 'sha256': j.digest(values), 'scope': 'bounded test business records'}


class PureTestCase(unittest.TestCase):
    def setUp(self):
        # The production path is intentionally Linux-only. No directory is
        # created here; only parser tests use a platform-native lexical root.
        root = Path(__file__).resolve().parent / 'not-created-test-root'
        for target, key, value in ((j.qa, 'ROOT', root), (j, 'ROOT', root / 'business-journeys')):
            handle = patch.object(target, key, value)
            handle.start()
            self.addCleanup(handle.stop)


class BoundaryTests(PureTestCase):
    def call(self, command, values, method='POST', profile='business-save', **env):
        return j.request_policy(record(profile), command, values, method,
                                {'PATH_INFO': '/api/method/' + command, **env})

    def test_profiles_have_fixed_natural_language_without_a_second_approval(self):
        for profile in j.PROFILES:
            self.assertTrue(j.send_allowed(send(profile), profile))
        self.assertIn('实际登记', j.requested_message('business-save'))

    def test_arbitrary_message_day_pupil_attachment_and_admin_rpc_refused(self):
        for field, value in (('message', '删除所有数据'), ('day', '2026-09-14'), ('stream', True),
                             ('file_name', 'private.xlsx'), ('request_id', '../x')):
            values = send()
            values[field] = value
            self.assertFalse(j.send_allowed(values, 'business-save'))
        for command in ('upload_file', 'frappe.client.set_value', 'tongjianyun.meal_chat.send_message',
                        'tongjianyun.classroom.save_attendance', j.old.WORKER_METHOD):
            self.assertFalse(self.call(command, {}))

    def test_native_login_only_teacher_no_alias_cmd(self):
        values = {'usr': j.fixture.TEACHER, 'pwd': 'synthetic-not-a-real-secret'}
        self.assertTrue(self.call('login', values))
        self.assertFalse(self.call('login', {**values, 'usr': 'Administrator'}))
        self.assertFalse(self.call('login', {**values, 'cmd': 'login'}))
        self.assertFalse(self.call('login', values, PATH_INFO='/api/v2/method/login'))

    def test_catalog_canonical_view_allowed_but_not_arbitrary_doctype_or_new_form(self):
        choice = {'view': 'frappe_catalog', 'day': j.DAY, 'meal': j.MEAL, 'kind': 'doctype', 'offset': 0}
        self.assertTrue(j.selection_allowed(choice, 'catalog'))
        self.assertFalse(j.selection_allowed(choice, 'business-save'))
        for key, value in (('kind', 'report'), ('offset', 20), ('offset', True), ('app', 'unknown'), ('components', [])):
            self.assertFalse(j.selection_allowed({**choice, key: value}, 'catalog'))
        self.assertFalse(j.selection_allowed({'view': 'frappe_new', 'doctype': 'User'}, 'catalog'))

    def test_cursor_and_cancel_only_this_run_task(self):
        with patch.object(j.old, 'private_read', return_value={'request_id': TASK}):
            self.assertTrue(self.call(j.old.API + 'stream_events', {'task_id': TASK, 'after': TASK + ':2'}, 'GET'))
            self.assertFalse(self.call(j.old.API + 'stream_events', {'task_id': TASK}, 'GET', HTTP_LAST_EVENT_ID=RUN + ':1'))
            self.assertTrue(self.call(j.old.API + 'cancel_task', {'task_id': TASK}))
            self.assertFalse(self.call(j.old.API + 'cancel_task', {'task_id': RUN}))
            self.assertFalse(self.call(j.old.API + 'get_conversation', {'before': RUN}, 'GET'))

    def test_auth_guard_does_not_bypass_native_csrf_or_invent_login(self):
        frappe = SimpleNamespace(session=SimpleNamespace(user=j.fixture.TEACHER), PermissionError=PermissionError,
            request=SimpleNamespace(path='/api/method/' + j.old.API + 'send_message'), form_dict=send())
        with patch.object(j, 'reserve') as reserve:
            native = Mock(side_effect=PermissionError('native CSRF'))
            with self.assertRaises(PermissionError):
                j.authenticated_guard(record(), frappe, native)()
            reserve.assert_not_called()
            native = Mock()
            j.authenticated_guard(record(), frappe, native)()
            native.assert_called_once()
            reserve.assert_called_once()


class ToolTests(PureTestCase):
    def test_finite_save_exact_student_status_day_and_fresh_revision(self):
        self.assertTrue(j.tool_allowed('business-save', 'attendance_save', attendance()))
        for key, value in (('day', '2026-09-14'), ('group', 'another'), ('revision', ''),
                           ('changes', [{'student': j.fixture.STUDENTS[1], 'status': 'Present'}]),
                           ('changes', [{'student': j.fixture.STUDENTS[0], 'status': 'Absent'}])):
            self.assertFalse(j.tool_allowed('business-save', 'attendance_save', {**attendance(), key: value}))
        self.assertFalse(j.tool_allowed('catalog', 'attendance_save', attendance()))

    def test_unrequested_meals_attachments_proposals_and_raw_operations_rejected(self):
        for profile in j.PROFILES:
            for tool in ('meal_save', 'meal_read', 'attachment_read', 'proposal_create', 'execute_sql', 'shell'):
                self.assertFalse(j.tool_allowed(profile, tool, {}))

    def test_fixed_read_scope_no_pagination_or_other_dates(self):
        self.assertTrue(j.tool_allowed('business-save', 'classroom_read', {'group': j.fixture.GROUP, 'day': j.DAY}))
        self.assertTrue(j.tool_allowed('catalog', 'business_catalog_read', {}))
        self.assertFalse(j.tool_allowed('catalog', 'business_catalog_read', {'cursor': 'x'}))
        self.assertFalse(j.tool_allowed('catalog', 'business_catalog_read', {'page_size': True}))
        self.assertFalse(j.tool_allowed('business-save', 'scene_bootstrap', {'day': j.DAY, 'after': 'other'}))

    def test_guard_binds_site_owner_task_before_any_intent(self):
        claim = SimpleNamespace(identity=SimpleNamespace(site=j.qa.SITE, owner=j.fixture.TEACHER, task_id=RUN))
        with patch.object(j, 'pin'), patch.object(j.old, 'private_read', return_value={'request_id': TASK}), patch.object(j.old, 'exclusive_json') as write:
            self.assertFalse(j.tool_guard(record(), claim, 'attendance_save', attendance()))
            write.assert_not_called()

    def test_second_revision_refused_but_same_intent_replay_allowed(self):
        claim = SimpleNamespace(identity=SimpleNamespace(site=j.qa.SITE, owner=j.fixture.TEACHER, task_id=TASK))
        def read(path):
            return {'request_id': TASK} if path.name == 'attempt.json' else {'task_id': TASK, 'digest': j.digest(attendance())}
        with patch.object(j, 'pin'), patch.object(j, 'lock', return_value=nullcontext()), patch.object(j.old, 'private_read', side_effect=read), patch.object(Path, 'exists', return_value=True), patch.dict('sys.modules', {'tongjianyun.business_agent_writes': SimpleNamespace(_arguments=lambda tool, args: args)}):
            self.assertTrue(j.tool_guard(record(), claim, 'attendance_save', attendance()))
            self.assertFalse(j.tool_guard(record(), claim, 'attendance_save', {**attendance(), 'revision': 'b' * 64}))


class BaselineTests(PureTestCase):
    def test_leaf_hashes_are_deterministic_and_contain_no_raw_sensitive_value(self):
        values = {'student_name': 'Synthetic Child', 'status': 'Present', 'children': [{'amount': 2}]}
        self.assertEqual(j.flatten(values), j.flatten(dict(reversed(list(values.items())))))
        self.assertTrue(all(len(value) == 64 for value in j.flatten(values).values()))
        self.assertNotIn('Synthetic Child', str(j.flatten(values)))

    def test_only_new_target_attendance_and_native_daily_summary_are_expected(self):
        rows = [row('Student Attendance', 'NEW', student_group=j.fixture.GROUP, student=j.fixture.STUDENTS[0], date=j.DAY, status='Present'),
                row('Tongjianyun Daily Meal Confirmation', 'DAILY', meal_date=j.DAY)]
        result = j.difference(snapshot(), snapshot(rows), 'business-save')
        self.assertTrue(result['protected_passed'])
        self.assertEqual(len(result['expected']), 2)
        self.assertFalse(result['raw_unchanged'])
        self.assertFalse(result['historical_digest_difference_explained'])
        self.assertFalse(j.difference(snapshot(), snapshot(rows), 'catalog')['protected_passed'])

    def test_different_student_date_old_row_edits_deletions_and_unexpected_types_fail(self):
        good = row('Student Attendance', 'A', student_group=j.fixture.GROUP, student=j.fixture.STUDENTS[0], date=j.DAY, status='Present')
        for key, value in (('student', j.fixture.STUDENTS[1]), ('date', '2026-09-14'), ('status', 'Absent')):
            changed = copy.deepcopy(good)
            changed['scope'][key] = value
            changed['fields'] = j.flatten(changed['scope'])
            self.assertFalse(j.difference(snapshot(), snapshot([changed]), 'business-save')['protected_passed'])
        changed = copy.deepcopy(good)
        changed['fields']['/extra'] = 'a' * 64
        self.assertFalse(j.difference(snapshot([good]), snapshot([changed]), 'business-save')['protected_passed'])
        self.assertFalse(j.difference(snapshot([good]), snapshot(), 'business-save')['protected_passed'])
        self.assertFalse(j.difference(snapshot(), snapshot([row('Student', 'NEW')]), 'business-save')['protected_passed'])

    def test_audit_side_effects_only_for_new_exact_targets(self):
        attendance_row = row('Student Attendance', 'A', student_group=j.fixture.GROUP, student=j.fixture.STUDENTS[0], date=j.DAY, status='Present')
        comment = row('Comment', 'C', reference_doctype='Student Attendance', reference_name='A', comment_type='Info')
        self.assertTrue(j.difference(snapshot(), snapshot([attendance_row, comment]), 'business-save')['protected_passed'])
        self.assertFalse(j.difference(snapshot(), snapshot([comment]), 'business-save')['protected_passed'])
        comment['scope']['comment_type'] = 'Comment'
        self.assertFalse(j.difference(snapshot(), snapshot([attendance_row, comment]), 'business-save')['protected_passed'])

    def test_login_fields_visible_not_global_user_change_mask(self):
        user = row('User', j.fixture.TEACHER)
        user['fields'] = j.flatten({'enabled': 1, 'last_login': 'before'})
        changed = copy.deepcopy(user)
        changed['fields'] = j.flatten({'enabled': 1, 'last_login': 'after'})
        result = j.difference(snapshot([user]), snapshot([changed]), 'catalog')
        self.assertTrue(result['protected_passed'])
        self.assertFalse(result['raw_unchanged'])
        self.assertEqual(result['authentication_metadata'][0]['fields'], ['/last_login'])
        changed['fields'] = j.flatten({'enabled': 0, 'last_login': 'after'})
        self.assertFalse(j.difference(snapshot([user]), snapshot([changed]), 'catalog')['protected_passed'])


class ReservationTests(PureTestCase):
    def test_duplicate_exact_request_has_no_new_baseline_or_model(self):
        values = send()
        actual = {'request_id': TASK, 'payload_sha256': j.digest(values), 'site': j.qa.SITE, 'owner': j.fixture.TEACHER}
        with patch.object(j, 'lock', return_value=nullcontext()), patch.object(Path, 'exists', return_value=True), patch.object(j.old, 'private_read', return_value=actual), patch.object(j, 'snapshot') as capture:
            j.reserve(record(), values, Mock())
            capture.assert_not_called()
            with self.assertRaises(PermissionError):
                j.reserve(record(), {**values, 'request_id': RUN}, Mock())

    def test_changed_prepared_business_baseline_never_reset(self):
        with patch.object(j, 'lock', return_value=nullcontext()), patch.object(Path, 'exists', return_value=False), patch.object(j, 'assert_empty'), patch.object(j.old, 'private_read', return_value=snapshot()), patch.object(j, 'snapshot', return_value=snapshot([row('Student', 'unexpected')])), patch.object(j.old, 'exclusive_json') as write:
            with self.assertRaises(PermissionError):
                j.reserve(record(), send(), Mock())
            write.assert_not_called()

    def test_prepare_rejects_root_before_touching_lock_or_config(self):
        with patch.object(j, 'environment', side_effect=PermissionError), patch.object(j, 'lock') as acquire:
            with self.assertRaises(PermissionError):
                j.prepare(RUN, 'business-save')
            acquire.assert_not_called()

    def test_path_traversal_and_invalid_profile_rejected(self):
        for value in ('../other', '/tmp/x', RUN.upper(), None):
            with self.assertRaises(ValueError):
                j.folder(value)
        with self.assertRaises(ValueError):
            j.prepare(RUN, 'root')

    def test_source_pin_includes_actual_native_boundary_not_just_script(self):
        for name in ('tongjianyun/business_agent_execution.py', 'tongjianyun/business_agent_writes.py',
                     'tongjianyun/business_agent_write_adapter.py', 'tongjianyun/business_agent_catalog.py',
                     'tongjianyun/business_agent_worker.py', 'tongjianyun/meal_views.py',
                     'tongjianyun/public/meal_scene/views.js'):
            self.assertIn(name, j.SOURCE_FILES)

    def test_interrupted_baseline_write_never_overwrites_or_creates_attempt(self):
        with patch.object(j, 'lock', return_value=nullcontext()), patch.object(Path, 'exists', return_value=False), patch.object(j, 'assert_empty'), patch.object(j.old, 'private_read', return_value=snapshot()), patch.object(j, 'snapshot', return_value=snapshot()), patch.object(j.old, 'exclusive_json', side_effect=FileExistsError) as write:
            with self.assertRaises(FileExistsError):
                j.reserve(record(), send(), Mock())
            write.assert_called_once()
            self.assertEqual(write.call_args.args[0].name, 'model-baseline.json')

    def test_prepare_uses_new_run_files_and_only_owned_config_keys(self):
        report = {**record(), 'baseline': snapshot(), 'model_started': False}
        def read(path):
            return {'workers': {'foreign': {'timeout': 30}}, 'unrelated': 17} if path.name == 'common_site_config.json' else {'unrelated': 18}
        with patch.object(j, 'environment'), patch.object(j, 'lock', return_value=nullcontext()), patch.object(j, 'check', return_value=(Mock(), report)), patch.object(j, 'idle_queue'), patch.object(Path, 'exists', return_value=False), patch.object(Path, 'mkdir'), patch.object(j.old, 'private_read', side_effect=read), patch.object(j.old, 'exclusive_json') as create, patch.object(j.old, 'atomic_json') as replace, patch.dict('sys.modules', {'tongjianyun.business_agent_transport': SimpleNamespace(private_directory=lambda path: path)}):
            result = j.prepare(RUN, 'business-save')
            self.assertFalse(result['model_started'])
            self.assertEqual({call.args[0].name for call in create.call_args_list}, {'request.lock', 'prepare-baseline.json', 'run.json'})
            self.assertTrue(all(call.args[0].parent.name == RUN for call in create.call_args_list))
            common = next(call.args[1] for call in replace.call_args_list if call.args[0].name == 'common_site_config.json')
            self.assertEqual(common['workers']['foreign'], {'timeout': 30})
            self.assertEqual(common['unrelated'], 17)
            self.assertEqual(common['workers'][j.old.QUEUE], {'timeout': -1})
            self.assertFalse(any(call.args[0] in {j.old.ATTEMPT, j.old.CONFIG_STATE} for call in replace.call_args_list))

    def test_prepare_partial_config_failure_keeps_preparing_record_for_exact_restore(self):
        report = {**record(), 'baseline': snapshot(), 'model_started': False}
        writes = []
        def replace(path, value):
            writes.append(path)
            if path.name == 'common_site_config.json':
                raise OSError('simulated full disk')
        with patch.object(j, 'environment'), patch.object(j, 'lock', return_value=nullcontext()), patch.object(j, 'check', return_value=(Mock(), report)), patch.object(j, 'idle_queue'), patch.object(Path, 'exists', return_value=False), patch.object(Path, 'mkdir'), patch.object(j.old, 'private_read', return_value={}), patch.object(j.old, 'exclusive_json') as create, patch.object(j.old, 'atomic_json', side_effect=replace), patch.dict('sys.modules', {'tongjianyun.business_agent_transport': SimpleNamespace(private_directory=lambda path: path)}):
            with self.assertRaises(OSError):
                j.prepare(RUN, 'business-save')
            persisted = next(call.args[1] for call in create.call_args_list if call.args[0].name == 'run.json')
            self.assertEqual(persisted['state'], 'preparing')
            self.assertNotIn('run.json', [path.name for path in writes])


class PriorEvidenceTests(PureTestCase):
    def values(self):
        return {'status': 'failed', 'events': [], 'native': {'state': 'exited', 'lease_closed': True, 'active_writes': 0},
                'host': {'present': False, 'closed': False, 'active': 0, 'uncertain': 0}}

    def test_prior_hash_failure_refuses_before_any_cleanup_or_new_reservation(self):
        with patch.object(j.qa, 'digest_file', return_value='changed'), patch.object(j, 'task_proof') as proof, patch.object(j.old, 'exclusive_json') as write:
            with self.assertRaises(PermissionError):
                j.prior_proof()
            proof.assert_not_called()
            write.assert_not_called()

    def test_missing_unit_never_overrides_unknown_native_or_uncertain_host(self):
        def hashes(path):
            return j.OLD_REPORT_HASH if path.name.startswith('business-browser-result') else j.OLD_ATTEMPT_HASH if path.name == 'business-browser-attempt.json' else 'x' * 64
        def read(path):
            return {'state': 'restored'} if path.name == 'business-browser-config.json' else {'running': False, 'pid': 9999999}
        for field, change in (('native', {'state': 'unknown'}), ('native', {'lease_closed': False}),
                              ('host', {'uncertain': 1}), ('host', {'active': 1}), ('host', {'present': True, 'closed': False})):
            proof = self.values()
            proof[field].update(change)
            with patch.object(j.qa, 'digest_file', side_effect=hashes), patch.object(j.old, 'private_read', side_effect=read), patch.object(Path, 'exists', return_value=False), patch.object(j, 'task_proof', return_value=proof), patch.object(j, 'unit_proof') as unit:
                with self.assertRaises(PermissionError):
                    j.prior_proof()
                unit.assert_not_called()

    def test_readiness_check_cannot_prepare_or_run_model(self):
        class FakeWorker:
            def __init__(self, tool_guard=None):
                raise AssertionError('check must not construct a worker')
        native = Mock()
        native.return_value.ready.return_value = True
        module = SimpleNamespace(UnixLauncherRuntime=native, BusinessWorker=FakeWorker)
        with patch.object(j, 'environment', return_value=Mock()), patch.object(j.qa, 'verify_asset_evidence'), patch.object(j, 'prior_proof', return_value={}), patch.object(j, 'assert_empty') as empty, patch.object(j, 'snapshot', return_value=snapshot()), patch.object(j, 'pin', return_value={}), patch.object(j.old, 'exclusive_json') as write, patch.dict('sys.modules', {'tongjianyun.business_agent_worker': module}):
            _, result = j.check('business-save')
            self.assertFalse(result['model_started'])
            empty.assert_called_once()
            write.assert_not_called()

    def test_source_drift_rejects_even_if_prepared_file_matches_old_process(self):
        with patch.object(j.qa, 'digest_file', return_value='changed'):
            with self.assertRaises(PermissionError):
                j.pin({'source_sha256': j.LOADED_HASHES})


class NativeJobTests(PureTestCase):
    def job(self):
        return SimpleNamespace(origin='fixed', func_name='frappe.utils.background_jobs.execute_job', args=(),
            timeout=-1, retries_left=0, _success_callback_name=None, _stopped_callback_name=None,
            _failure_callback_name='frappe.utils.background_jobs.truncate_failed_registry',
            kwargs={'site': j.qa.SITE, 'user': j.fixture.TEACHER, 'method': j.old.WORKER_METHOD,
                'job_name': j.old.WORKER_METHOD, 'event': None, 'is_async': True,
                'kwargs': {'owner': j.fixture.TEACHER, 'task_id': TASK}})

    def test_only_reserved_real_frappe_run_task_is_consumed(self):
        with patch.object(j.old, 'private_read', return_value={'request_id': TASK}):
            j.validate_job(record(), self.job(), 'fixed', 'fixed')
            for field, value in (('timeout', 300), ('retries_left', 1), ('_success_callback_name', 'evil'), ('func_name', 'other')):
                job = self.job()
                setattr(job, field, value)
                with self.assertRaises(PermissionError):
                    j.validate_job(record(), job, 'fixed', 'fixed')
            job = self.job()
            job.kwargs['kwargs']['task_id'] = RUN
            with self.assertRaises(PermissionError):
                j.validate_job(record(), job, 'fixed', 'fixed')

    def test_missing_unit_is_not_a_native_exit_proof(self):
        completed = SimpleNamespace(returncode=0, stdout='LoadState=not-found\nActiveState=inactive\nMainPID=0\nControlGroup=\n')
        with patch.object(j.subprocess, 'run', return_value=completed):
            self.assertEqual(j.unit_proof(TASK)['LoadState'], 'not-found')
        # unit_proof is supplementary; task_proof/lease/host remain mandatory.
        self.assertNotIn('lease_closed', completed.stdout)
        completed.stdout = 'ActiveState=active\nMainPID=12\nControlGroup=/system.slice/task\n'
        with patch.object(j.subprocess, 'run', return_value=completed), self.assertRaises(PermissionError):
            j.unit_proof(TASK)


class IdleQueueTests(PureTestCase):
    def run_idle(self, *, pending=0, started=0, workers=(), active=False):
        frappe = Mock(conf={})  # No custom workers/business_codex configuration.
        db = Mock()
        db.execute.return_value.fetchone.return_value = object() if active else None
        connection = object()
        queue = SimpleNamespace(name='native-bench-id:business_codex', count=pending, connection=connection)
        queue_class = Mock(return_value=queue)
        registry = Mock()
        registry.get_job_count.return_value = started
        class Registry:
            def __init__(self, **kwargs):
                self.get_job_count = registry.get_job_count
            @property
            def count(self):
                raise AssertionError('Implicit started-registry cleanup is forbidden')
        background = SimpleNamespace(generate_qname=Mock(return_value=queue.name), get_redis_conn=Mock(return_value=connection),
                                     get_queue=Mock(side_effect=AssertionError('Unconfigured get_queue must not be used')))
        worker = SimpleNamespace(all=Mock(side_effect=AssertionError('Worker.all can SREM stale registration')))
        registration = SimpleNamespace(get_keys=Mock(return_value=set(workers)))
        modules = {'frappe.utils.background_jobs': background, 'rq': SimpleNamespace(Queue=queue_class, Worker=worker),
                   'rq.registry': SimpleNamespace(StartedJobRegistry=Registry), 'rq.worker_registration': registration}
        with patch.dict('sys.modules', modules), patch.object(j, 'read_db', return_value=nullcontext(db)), patch.object(j.qa, 'guard'):
            if pending or started or workers or active:
                with self.assertRaises(PermissionError):
                    j.idle_queue(frappe)
            else:
                j.idle_queue(frappe)
        background.get_queue.assert_not_called()
        worker.all.assert_not_called()
        if not active:
            queue_class.assert_called_once_with(queue.name, connection=connection)
            background.generate_qname.assert_called_once_with(j.old.QUEUE)
            frappe.destroy.assert_called_once()
        if not active and not pending:
            registry.get_job_count.assert_called_once_with(cleanup=False)
        return registration

    def test_unconfigured_custom_queue_still_has_exact_read_only_idle_proof(self):
        registration = self.run_idle()
        self.assertEqual(registration.get_keys.call_count, 1)

    def test_pending_and_expired_started_entries_block_without_cleanup(self):
        self.run_idle(pending=1)
        self.run_idle(started=1)

    def test_stale_worker_registration_is_not_deleted_or_silently_ignored(self):
        self.run_idle(workers={'rq:worker:old-or-live'})

    def test_active_task_blocks_before_redis_inspection(self):
        registration = self.run_idle(active=True)
        registration.get_keys.assert_not_called()


class EvidenceTests(PureTestCase):
    def active_native(self):
        return {'status': 'completed', 'task_id': TASK,
            'native': {'state': 'exited', 'lease_closed': True, 'exit_code': 0, 'active_writes': 1},
            'host': {'present': True, 'closed': True, 'active': 0, 'uncertain': 0, 'committed': 1},
            'events': []}

    def test_native_active_write_blocks_final_baseline_even_with_clean_host(self):
        with patch.object(j, 'environment'), patch.object(j, 'load', return_value=record()), patch.object(j.old, 'private_read', return_value={'request_id': TASK}), patch.object(j, 'task_proof', return_value=self.active_native()), patch.object(j, 'snapshot') as capture, patch.object(j.old, 'exclusive_json') as write:
            with self.assertRaises(PermissionError):
                j.evidence(RUN)
            capture.assert_not_called()
            write.assert_not_called()

    def test_native_active_write_blocks_restore_before_unit_and_config_actions(self):
        def read(path):
            return {'run_id': RUN} if path.name == 'business-journey-active.json' else {'request_id': TASK}
        with patch.object(j, 'environment'), patch.object(j, 'lock', return_value=nullcontext()), patch.object(j, 'load', return_value={**record(), 'state': 'prepared'}), patch.object(j.old, 'private_read', side_effect=read), patch.object(Path, 'exists', lambda path: path.name == 'attempt.json'), patch.object(j, 'task_proof', return_value=self.active_native()), patch.object(j, 'unit_proof') as unit, patch.object(j.old, 'atomic_json') as replace:
            with self.assertRaises(PermissionError):
                j.restore(RUN)
            unit.assert_not_called()
            replace.assert_not_called()

    def test_failed_or_uncertain_state_never_becomes_success_and_reports_are_unique(self):
        proof = {'status': 'completed', 'task_id': TASK,
            'doctype_scope_count': 2,
            'native': {'state': 'exited', 'lease_closed': True, 'exit_code': 0, 'active_writes': 0},
            'host': {'present': True, 'closed': True, 'active': 0, 'uncertain': 0, 'committed': 0},
            'events': [{'kind': 'message'}, {'kind': 'view', 'selection': {'view': 'frappe_catalog', 'day': j.DAY, 'meal': j.MEAL}}]}
        def read(path):
            return {'request_id': TASK} if path.name == 'attempt.json' else snapshot()
        with patch.object(j, 'environment', return_value=Mock()), patch.object(j, 'load', return_value=record('catalog')), patch.object(j, 'pin', return_value={}), patch.object(j.old, 'private_read', side_effect=read), patch.object(j, 'snapshot', return_value=snapshot()), patch.object(j, 'task_proof', side_effect=lambda task: copy.deepcopy(proof)), patch.object(j, 'rq_proof', return_value={'status': 'finished', 'started': True, 'result_status': 'completed'}), patch.object(j, 'fresh_readback', return_value={'passed': True}), patch.object(j.old, 'exclusive_json') as write:
            first = j.evidence(RUN)
            self.assertTrue(first['backend_passed'])
            self.assertFalse(first['browser_sse_and_display_verified'])
            proof['status'] = 'failed'
            self.assertFalse(j.evidence(RUN)['backend_passed'])
            paths = [call.args[0] for call in write.call_args_list]
            self.assertEqual(len(set(paths)), 4)
            self.assertTrue(all(path.parent.name == RUN for path in paths))
            proof['host']['uncertain'] = 1
            with self.assertRaises(PermissionError):
                j.evidence(RUN)
            self.assertEqual(write.call_count, 4)


if __name__ == '__main__':
    unittest.main()
