"""Pure recipe journey boundaries; no server/site/Redis/model/credentials used."""
from contextlib import ExitStack, nullcontext, redirect_stdout, redirect_stderr
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

SPEC = importlib.util.spec_from_file_location('recipe_journey_tests_target', Path(__file__).with_name('serve_recipe_journey.py'))
j = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(j)
RUN = '3cbd2365-c50d-46c8-814c-6835d50f27de'
TASK = '59d4c72a-bfd2-442c-bf5f-f375ce4cd3ed'
OPERATION = '6d3d5837-818d-48c5-b1a5-fdc25c9f70ef'
FILE = 'synthetic-file-id'


def record():
    return {'run_id': RUN, 'site': j.qa.SITE, 'owner': j.OWNER, 'profile': j.PROFILE,
            'day': j.DAY, 'week_end': j.END, 'state': 'prepared', 'source_sha256': {}}


def attachment():
    return {'run_id': RUN, 'site': j.qa.SITE, 'owner': j.OWNER, 'file_id': FILE,
            'filename': j.filename(RUN), 'sha256': hashlib.sha256(j.upload_bytes(RUN)).hexdigest()}


def send():
    return {'request_id': TASK, 'message': j.requested_message(RUN), 'day': j.DAY,
            'meal': j.MEAL, 'stream': 1, 'file_name': FILE,
            'view_context': {'view': 'recipe_week', 'day': j.DAY, 'meal': j.MEAL}}


def recipe_args():
    return {'day': j.DAY, 'recipe': None, 'revision': '', 'payload': j.payload(RUN)}


def proof():
    return {'status': 'completed', 'native': {'state': 'exited', 'lease_closed': True,
            'active_writes': 0, 'exit_code': 0},
            'host': {'closed': True, 'active': 0, 'uncertain': 0, 'committed': [OPERATION]}}


def baseline():
    return {'site': j.qa.SITE, 'files': {'original-file': 'original'},
            'recipes': {doctype: ({j.PARENT_RECIPE: {'recipe': j.PARENT_RECIPE, 'sha256': 'old'}}
                if doctype == 'Tongjianyun Recipe' else {}) for doctype in (
                    'Tongjianyun Recipe', 'Tongjianyun Recipe Dish', 'Tongjianyun Recipe Ingredient', 'Version')},
            'parent': {'recipe': j.PARENT_RECIPE, 'sha256': 'old-parent'},
            'account': {'/roles/0': 'role-hash', '/last_login': 'old-login'}}


class PureTestCase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.temp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(j, 'folder', side_effect=lambda _: self.temp))

    def patch(self, obj, name, **kwargs):
        return self.stack.enter_context(patch.object(obj, name, **kwargs))

    def storage(self):
        def write(path, value):
            with path.open('x', encoding='utf-8') as stream:
                json.dump(value, stream)
        self.patch(j.old, 'exclusive_json', side_effect=write)
        self.patch(j.old, 'private_read', side_effect=lambda path: json.loads(path.read_text(encoding='utf-8')))
        self.patch(j.previous, 'lock', side_effect=lambda *args, **kwargs: nullcontext())


class ContractTests(PureTestCase):
    def call(self, command, values, method='POST', **env):
        return j.request_policy(record(), command, values, method,
                                {'PATH_INFO': '/api/method/' + command, **env})

    def test_every_command_requires_explicit_uuid_and_no_alternate_owner_or_week(self):
        for args in ([], ['check'], ['--run-id', '../x'], ['--run-id', RUN, '--owner', 'Administrator'],
                     ['--run-id', RUN, '--day', j.native.DAY], ['--run-id', RUN, '--site', 'production']):
            with self.subTest(args=args), patch.object(j, 'environment') as environment, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    j.main(args)
                environment.assert_not_called()

    def test_default_check_is_read_only_and_does_not_prepare(self):
        self.patch(j, 'check', return_value=(object(), {'baseline': {}, 'model_started': False}))
        prepare = self.patch(j, 'prepare')
        with redirect_stdout(io.StringIO()):
            result = j.main(['--run-id', RUN])
        self.assertTrue(result['read_only'])
        prepare.assert_not_called()

    def test_file_permission_probe_uses_current_native_insert_owner_without_writing(self):
        frappe = MagicMock()
        frappe.local.site, frappe.session.user = j.qa.SITE, j.OWNER
        probe = MagicMock()
        def get_doc(value):
            # The original File permission denies an ownerless new document.
            probe.has_permission.return_value = value.get('owner') == frappe.session.user
            return probe
        frappe.get_doc.side_effect = get_doc
        j.file_create_probe(frappe, RUN)
        frappe.get_doc.assert_called_once_with({'doctype': 'File', 'is_private': 1,
            'file_name': j.filename(RUN), 'owner': j.OWNER})
        probe.has_permission.assert_called_once_with('create')
        probe.insert.assert_not_called()
        probe.save.assert_not_called()
        frappe.set_user.assert_not_called()
        frappe.db.commit.assert_not_called()

    def test_file_permission_probe_cannot_switch_actor_or_bypass_native_denial(self):
        for site, owner in ((j.qa.SITE, 'Administrator'), ('production', j.OWNER)):
            frappe = MagicMock()
            frappe.local.site, frappe.session.user = site, owner
            with self.assertRaises(PermissionError):
                j.file_create_probe(frappe, RUN)
            frappe.get_doc.assert_not_called()
            frappe.set_user.assert_not_called()
        frappe = MagicMock()
        frappe.local.site, frappe.session.user = j.qa.SITE, j.OWNER
        frappe.get_doc.return_value.has_permission.return_value = False
        with self.assertRaises(PermissionError):
            j.file_create_probe(frappe, RUN)
        frappe.get_doc.return_value.insert.assert_not_called()
        frappe.get_doc.return_value.save.assert_not_called()

    def test_synthetic_data_separates_new_week_and_preserved_parent(self):
        from tongjianyun.business_agent_recipes import normalize_payload, week_bounds
        self.assertEqual(week_bounds(j.DAY), (j.DAY, j.END))
        self.assertNotEqual(j.DAY, j.native.DAY)
        self.assertEqual(normalize_payload(j.payload(RUN)), j.payload(RUN))
        self.assertEqual(j.payload(RUN)['days'][0]['portions'][0]['dishIngredientRows'], [])
        self.assertIn(RUN.encode(), j.upload_bytes(RUN))
        self.assertLess(len(j.upload_bytes(RUN)), 4096)

    def test_login_native_manager_only_and_canonical_routes(self):
        values = {'usr': j.OWNER, 'pwd': 'nonsecret-test-placeholder'}
        self.assertTrue(self.call('login', values))
        for actor in ('Administrator', j.native.OWNER, 'unrelated@example.invalid'):
            self.assertFalse(self.call('login', {**values, 'usr': actor}))
        self.assertFalse(self.call('login', values, PATH_INFO='/api/v2/method/login'))
        self.assertFalse(self.call('login', {**values, 'cmd': 'login'}))

    def test_send_requires_exact_request_native_file_and_fixed_week(self):
        self.patch(j, 'uploaded', return_value=attachment())
        self.assertTrue(j.send_allowed(record(), send()))
        for field, value in (('file_name', 'another-file'), ('message', 'modify old recipe'),
                             ('day', j.native.DAY), ('stream', True), ('request_id', '../x'),
                             ('view_context', {'view': 'frappe_new', 'doctype': 'User'})):
            self.assertFalse(j.send_allowed(record(), {**send(), field: value}))

    def test_no_original_admin_rpc_direct_save_generic_crud_or_retry(self):
        self.patch(j, 'registered_task', return_value=TASK)
        for command in ('upload_file', 'tongjianyun.meal_chat.send_message',
                        'tongjianyun.meal_scene.create_recipe_draft', 'tongjianyun.meal_scene.save_recipe_edit',
                        'frappe.client.insert', j.API + 'retry_dispatch'):
            self.assertFalse(self.call(command, {'task_id': TASK}))

    def test_only_registered_task_sse_cancel_and_history(self):
        self.patch(j, 'registered_task', return_value=TASK)
        self.patch(j, 'manager_tasks', return_value=[TASK])
        self.assertTrue(self.call(j.API + 'get_conversation', {}, 'GET'))
        self.assertTrue(self.call(j.API + 'stream_events', {'task_id': TASK, 'after': TASK + ':2'}, 'GET'))
        self.assertTrue(self.call(j.API + 'cancel_task', {'task_id': TASK}))
        self.assertFalse(self.call(j.API + 'stream_events', {'task_id': RUN}, 'GET'))
        self.assertFalse(self.call(j.API + 'stream_events', {'task_id': TASK}, 'GET', HTTP_LAST_EVENT_ID=RUN + ':1'))
        self.assertFalse(self.call(j.API + 'get_conversation', {'before': RUN}, 'GET'))
        self.patch(j, 'manager_tasks', return_value=[TASK, RUN])
        self.assertFalse(self.call(j.API + 'get_conversation', {}, 'GET'))

    def test_frontend_overview_and_immediate_get_recipe_use_committed_target(self):
        self.assertTrue(self.call('tongjianyun.meal_scene.get_overview', {'day': j.DAY, 'meal': j.MEAL}, 'GET'))
        self.assertFalse(self.call('tongjianyun.meal_scene.get_overview', {'day': j.native.DAY}, 'GET'))
        self.patch(j, 'committed_target', return_value='trusted-new-recipe')
        self.assertTrue(self.call('tongjianyun.meal_scene.get_recipe', {'recipe': 'trusted-new-recipe'}, 'GET'))
        self.assertFalse(self.call('tongjianyun.meal_scene.get_recipe', {'recipe': j.PARENT_RECIPE}, 'GET'))
        self.assertFalse(self.call('tongjianyun.meal_scene.get_recipe', {'recipe': 'model-invented'}, 'GET'))

    def test_authentication_runs_before_any_upload_or_task_reservation(self):
        frappe = SimpleNamespace(PermissionError=PermissionError, session=SimpleNamespace(user=j.OWNER),
            request=SimpleNamespace(path='/api/method/' + j.API + 'send_message',
                                    environ={'tgy.recipe_request_id': RUN}), form_dict=send())
        reserve = self.patch(j, 'reserve')
        auth = Mock(side_effect=PermissionError('native auth or CSRF'))
        with self.assertRaises(PermissionError):
            j.authenticated_guard(record(), frappe, auth)()
        reserve.assert_not_called()
        auth = Mock()
        j.authenticated_guard(record(), frappe, auth)()
        auth.assert_called_once()
        reserve.assert_called_once_with(record(), send(), frappe, http_id=RUN)


@unittest.skipUnless(importlib.util.find_spec('werkzeug'), 'Real multipart parser requires the existing Linux Frappe test environment')
class MultipartTests(PureTestCase):
    def environ(self, *, name=None, raw=None, private='1', extra=None, second=False):
        from werkzeug.test import EnvironBuilder
        data = {'file': (io.BytesIO(j.upload_bytes(RUN) if raw is None else raw), name or j.filename(RUN), 'text/plain'),
                'is_private': private}
        if extra:
            data.update(extra)
        if second:
            data['file'] = [data['file'], (io.BytesIO(b'other'), 'other.txt', 'text/plain')]
        builder = EnvironBuilder(path='/api/method/upload_file', method='POST', data=data)
        self.addCleanup(builder.close)
        return builder.get_environ()

    def test_exact_multipart_is_replayed_unchanged_for_native_upload(self):
        env = self.environ()
        body = env['wsgi.input'].read()
        env['wsgi.input'] = io.BytesIO(body)
        self.assertTrue(j.multipart_allowed(record(), env))
        self.assertEqual(env['wsgi.input'].read(), body)

    def test_multipart_rejects_alternative_native_upload_paths_or_private_false(self):
        cases = [dict(extra={key: 'untrusted'}) for key in (
            'method', 'file_url', 'library_file_name', 'chunk_index', 'doctype', 'docname', 'cmd')]
        cases += [dict(private='0'), dict(name='other.txt'), dict(raw=b'other'), dict(second=True)]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                self.assertFalse(j.multipart_allowed(record(), self.environ(**kwargs)))

    def test_multipart_rejects_alias_query_transfer_encoding_and_oversize(self):
        for key, value in (('PATH_INFO', '/api/v2/method/upload_file'), ('QUERY_STRING', 'method=evil'),
                           ('HTTP_TRANSFER_ENCODING', 'chunked'), ('CONTENT_LENGTH', '16385')):
            env = self.environ()
            env[key] = value
            self.assertFalse(j.multipart_allowed(record(), env))


class ConfigAndBaselineTests(PureTestCase):
    def test_all_three_owned_config_settings_restore_and_unrelated_keys_survive(self):
        for site, common in (({}, {}), ({'business_codex_scene_mode': None, 'business_codex_enabled': 0},
                {'workers': {j.old.QUEUE: {'timeout': 120}, 'other': {'timeout': 60}}})):
            original = copy.deepcopy((site, common))
            before = j.config_before(site, common)
            site.update(j.CONFIG_VALUES)
            common['workers'] = {**common.get('workers', {}), j.old.QUEUE: {'timeout': -1}}
            site['unrelated'] = 'preserve'
            j.restore_fields(site, common, before)
            self.assertEqual({key: value for key, value in site.items() if key != 'unrelated'}, original[0])
            self.assertEqual(common, original[1])
            self.assertEqual(site['unrelated'], 'preserve')

    def test_foreign_config_change_stops_before_any_field_is_mutated(self):
        site, common = {}, {}
        before = j.config_before(site, common)
        site.update(j.CONFIG_VALUES)
        site['business_codex_scene_mode'] = 'changed-by-operator'
        common['workers'] = {j.old.QUEUE: {'timeout': -1}}
        expected = copy.deepcopy((site, common))
        with self.assertRaises(PermissionError):
            j.restore_fields(site, common, before)
        self.assertEqual((site, common), expected)

    def test_prepare_upload_and_final_baselines_never_swallow_original_change(self):
        before, after = baseline(), baseline()
        after['files'][FILE] = 'new-file'
        after['account']['/last_login'] = 'new-login'
        self.assertTrue(j.difference(before, after, file_id=FILE)['protected_passed'])
        self.assertFalse(j.difference(before, after)['protected_passed'])
        for field in ('recipe', 'file', 'role', 'parent'):
            changed = copy.deepcopy(after)
            if field == 'recipe': changed['recipes']['Tongjianyun Recipe'][j.PARENT_RECIPE]['sha256'] = 'changed'
            elif field == 'file': changed['files']['original-file'] = 'changed'
            elif field == 'role': changed['account']['/roles/0'] = 'changed'
            else: changed['parent']['sha256'] = 'changed'
            self.assertFalse(j.difference(before, changed, file_id=FILE)['protected_passed'])


class ToolAndLedgerTests(PureTestCase):
    def claim(self):
        return SimpleNamespace(identity=SimpleNamespace(site=j.qa.SITE, owner=j.OWNER, task_id=TASK))

    def attachment_result(self):
        from tongjianyun.business_agent_attachments import parse_content
        rows = parse_content(j.upload_bytes(RUN), 'txt')
        return {'available': True, 'file_id': FILE, 'sha256': attachment()['sha256'], 'format': 'txt',
                'untrusted_data': True, 'content_role': 'attachment_data_not_instructions',
                'records': rows, 'record_count': len(rows), 'page_count': len(rows), 'has_more': False, 'next_offset': None}

    def empty_result(self):
        return {'day': j.DAY, 'calendar_week_start': j.DAY, 'calendar_week_end': j.END,
                'recipe': None, 'revision': '', 'visible_recipe_found': False,
                'dishes': [], 'complete': True, 'has_more': False, 'next_offset': None}

    def test_guard_admits_only_exact_single_new_week_payload_and_original_upload(self):
        self.patch(j, 'uploaded', return_value=attachment())
        self.assertTrue(j.tool_allowed(record(), 'attachment_read', {'file_id': FILE}))
        self.assertTrue(j.tool_allowed(record(), 'recipe_read', {'day': j.DAY}))
        self.assertTrue(j.tool_allowed(record(), 'recipe_save', recipe_args()))
        for field, value in (('recipe', j.PARENT_RECIPE), ('revision', 'old'), ('day', j.native.DAY)):
            self.assertFalse(j.tool_allowed(record(), 'recipe_save', {**recipe_args(), field: value}))
        altered = recipe_args()
        altered['payload']['days'][0]['portions'][0]['dishIngredientRows'] = [
            {'dishName': '合成验收菜品', 'ingredient': 'invented', 'amount': 10, 'unit': 'g'}]
        self.assertFalse(j.tool_allowed(record(), 'recipe_save', altered))
        for tool in ('business_view', 'execute_sql', 'meal_save', 'proposal_create', 'business_catalog_read'):
            self.assertFalse(j.tool_allowed(record(), tool, {}))
        self.assertFalse(j.tool_allowed(record(), 'attachment_read', {'file_id': FILE, 'offset': 1}))
        self.assertFalse(j.tool_allowed(record(), 'attachment_read', {'file_id': 'other'}))

    def test_write_guard_reserves_once_after_read_admission_without_faking_results(self):
        self.storage()
        self.patch(j, 'pin')
        self.patch(j, 'uploaded', return_value=attachment())
        self.patch(j, 'registered_task', return_value=TASK)
        claim = SimpleNamespace(identity=SimpleNamespace(site=j.qa.SITE, owner=j.OWNER, task_id=TASK))
        self.assertFalse(j.tool_guard(record(), claim, 'recipe_save', recipe_args()))
        self.assertTrue(j.tool_guard(record(), claim, 'attachment_read', {'file_id': FILE}))
        self.assertTrue(j.tool_guard(record(), claim, 'recipe_read', {'day': j.DAY}))
        # Admissions/scopes alone must never stand in for successful reads.
        self.assertFalse(j.tool_guard(record(), claim, 'recipe_save', recipe_args()))
        result = self.attachment_result()
        original = copy.deepcopy(result)
        j.read_observer(record(), claim, 'attachment_read', {'file_id': FILE}, result)
        self.assertEqual(result, original)
        j.read_observer(record(), claim, 'recipe_read', {'day': j.DAY}, self.empty_result())
        self.assertTrue(j.tool_guard(record(), claim, 'recipe_save', recipe_args()))
        self.assertFalse(j.tool_guard(record(), claim, 'recipe_save', recipe_args()))
        logs = [json.loads(path.read_text()) for path in self.temp.glob('tool-*.json')]
        self.assertEqual(sum(row['tool'] == 'recipe_save' and row['allowed'] for row in logs), 1)
        self.assertTrue(all(row['outcome'] == 'not_observed_by_guard' for row in logs))
        self.assertTrue(all('payload' not in row and 'arguments' not in row for row in logs))

    def test_incomplete_or_wrong_source_results_never_create_success_witness(self):
        self.storage()
        self.patch(j, 'pin')
        self.patch(j, 'uploaded', return_value=attachment())
        self.patch(j, 'registered_task', return_value=TASK)
        for change in ({'has_more': True}, {'sha256': 'wrong'}, {'file_id': 'other'},
                       {'records': []}, {'untrusted_data': False}, {'page_count': 1}):
            result = {**self.attachment_result(), **change}
            j.read_observer(record(), self.claim(), 'attachment_read', {'file_id': FILE}, result)
            self.assertFalse((self.temp / 'attachment-read-success.json').exists())
        for change in ({'recipe': 'old'}, {'complete': False}, {'visible_recipe_found': True}, {'day': j.native.DAY}):
            j.read_observer(record(), self.claim(), 'recipe_read', {'day': j.DAY}, {**self.empty_result(), **change})
            self.assertFalse((self.temp / 'week-read-success.json').exists())

    def test_any_foreign_claim_cannot_read_or_write(self):
        self.storage()
        self.patch(j, 'pin')
        self.patch(j, 'registered_task', return_value=TASK)
        for change in ({'owner': 'Administrator'}, {'site': 'production'}, {'task_id': RUN}):
            identity = {'site': j.qa.SITE, 'owner': j.OWNER, 'task_id': TASK, **change}
            claim = SimpleNamespace(identity=SimpleNamespace(**identity))
            self.assertFalse(j.tool_guard(record(), claim, 'recipe_save', recipe_args()))
        self.assertFalse((self.temp / 'write-intent.json').exists())

    def test_committed_target_uses_real_operation_id_before_offline_evidence(self):
        from tongjianyun.business_agent_recipes import write_plan
        self.patch(j, 'registered_task', return_value=TASK)
        self.patch(j, 'task_proof', return_value={**proof(), 'status': 'running'})
        self.patch(j.old, 'private_read', return_value={'task_id': TASK, 'arguments_sha256': j.digest(recipe_args())})
        self.assertEqual(j.committed_target(record()), write_plan(j.qa.SITE, OPERATION, recipe_args()).target_recipe)

    def test_pending_uncertain_or_multiple_commits_never_authorize_frontend_recipe(self):
        self.patch(j, 'registered_task', return_value=TASK)
        for change in ({'active': 1}, {'uncertain': 1}, {'committed': []}, {'committed': [OPERATION, RUN]}):
            value = proof()
            value['host'].update(change)
            with patch.object(j, 'task_proof', return_value=value), self.assertRaises(PermissionError):
                j.committed_target(record())


class NativeQueueAndLifecycleTests(PureTestCase):
    def job(self):
        return SimpleNamespace(origin='fixed-queue', func_name='frappe.utils.background_jobs.execute_job',
            args=[], timeout=-1, retries_left=None, _success_callback_name=None, _stopped_callback_name=None,
            _failure_callback_name='frappe.utils.background_jobs.truncate_failed_registry',
            kwargs={'site': j.qa.SITE, 'user': j.OWNER, 'method': j.old.WORKER_METHOD, 'event': None,
                    'job_name': j.old.WORKER_METHOD, 'is_async': True, 'kwargs': {'owner': j.OWNER, 'task_id': TASK}})

    def test_only_original_http_reserved_rq_job_can_execute(self):
        self.patch(j, 'registered_task', return_value=TASK)
        j.validate_job(record(), self.job(), 'fixed-queue', 'fixed-queue')
        for change in ({'site': 'production'}, {'user': 'Administrator'}, {'method': 'other'},
                       {'kwargs': {'owner': j.OWNER, 'task_id': RUN}}):
            job = self.job()
            job.kwargs.update(change)
            with self.assertRaises(PermissionError):
                j.validate_job(record(), job, 'fixed-queue', 'fixed-queue')
        job = self.job()
        job.retries_left = 1
        with self.assertRaises(PermissionError):
            j.validate_job(record(), job, 'fixed-queue', 'fixed-queue')

    def test_all_native_host_and_lease_conditions_are_required_for_drain(self):
        self.assertTrue(j.drained(proof()))
        for part, field, value in (('native', 'state', 'running'), ('native', 'lease_closed', False),
                ('native', 'active_writes', 1), ('host', 'closed', False), ('host', 'active', 1), ('host', 'uncertain', 1)):
            altered = proof()
            altered[part][field] = value
            self.assertFalse(j.drained(altered))

    def test_stop_and_restore_fail_before_signaling_or_config_write_if_not_drained(self):
        self.patch(j, 'environment', return_value=object())
        self.patch(j, 'load', return_value=record())
        self.patch(j.previous, 'lock', return_value=nullcontext())
        self.patch(j.old, 'private_read', return_value={'run_id': RUN})
        close = self.patch(j, 'close_admission')
        self.patch(j, 'drain_proof', side_effect=PermissionError('unknown host writes'))
        write = self.patch(j.old, 'atomic_json')
        signaler = self.patch(j.signal, 'pidfd_send_signal', create=True)
        with self.assertRaises(PermissionError):
            j.stop(RUN)
        with self.assertRaises(PermissionError):
            j.restore(RUN)
        signaler.assert_not_called()
        write.assert_not_called()
        self.assertEqual(close.call_count, 2)

    def test_sse_observer_keeps_no_message_body_and_cannot_claim_browser_delivery(self):
        observer = j.StreamEvidence()
        observer.observe(b'event: update\ndata: {"kind":"message","text":"private body"}\n')
        observer.observe(b'\nevent: update\ndata: {"kind":"ter')
        observer.observe(b'minal","status":"completed"}\n\nevent: closed\ndata: {}\n\n')
        self.assertEqual(observer.frames, 3)
        self.assertEqual(observer.kinds, {'message', 'terminal'})
        self.assertTrue(observer.closed)
        self.assertEqual(observer.buffer, b'')
        self.assertFalse(observer.invalid)

    def test_closing_admission_blocks_both_upload_and_submit_reservations(self):
        self.storage()
        j.close_admission(record())
        j.close_admission(record())  # Explicit later stop reuses the same closed fence.
        self.patch(j, 'send_allowed', return_value=True)
        read = self.patch(j, 'readonly')
        with self.assertRaises(PermissionError):
            j.reserve_upload(record(), object())
        with self.assertRaises(PermissionError):
            j.reserve(record(), send(), object())
        read.assert_not_called()
        self.assertFalse((self.temp / 'upload-intent.json').exists())
        self.assertFalse((self.temp / 'attempt.json').exists())

    def test_task_absence_does_not_prove_inflight_upload_or_send_is_drained(self):
        self.storage()
        j.old.exclusive_json(self.temp / 'upload-intent.json', {'run_id': RUN, 'http_request_id': RUN})
        tasks = self.patch(j, 'manager_tasks', return_value=[])
        self.patch(j, 'registered_task', return_value=None)
        with self.assertRaises(FileNotFoundError):
            j.drain_proof(record(), object())
        tasks.assert_not_called()
        self.assertFalse(j.mark_http_drained(record(), 'upload-drained.json', TASK))
        self.assertFalse((self.temp / 'upload-drained.json').exists())
        j.mark_http_drained(record(), 'upload-drained.json', RUN)
        self.assertEqual(j.drain_proof(record(), object()), {'task_absent': True, 'native_started': False})
        j.old.exclusive_json(self.temp / 'attempt.json', {'run_id': RUN})
        with self.assertRaises(FileNotFoundError):
            j.http_drained(record())


class CallbackDrainTests(PureTestCase):
    def response(self, *, fail=False):
        calls = []
        class Response:
            def __iter__(self):
                calls.append('iterate')
                yield b'{"message":{"name":"native-file"}}'
                if fail:
                    raise RuntimeError('native callback not known to have completed')
                calls.append('completed')
            def close(self):
                calls.append('closed')
        def application(environ, start_response):
            j.old.exclusive_json(self.temp / 'upload-intent.json',
                                 {'run_id': RUN, 'http_request_id': environ['tgy.recipe_request_id']})
            start_response('200 OK', [('Content-Type', 'application/json')])
            return Response()
        return application, calls

    def boundary(self, *, fail=False):
        self.storage()
        self.patch(j, 'load', return_value=record())
        self.patch(j, 'multipart_allowed', return_value=True)
        self.patch(j, 'verify_upload', return_value=attachment())
        native, calls = self.response(fail=fail)
        boundary = j.Boundary(record(), native, object())
        env = {'PATH_INFO': '/api/method/upload_file', 'REQUEST_METHOD': 'POST',
               'HTTP_HOST': f'{j.qa.SITE}:{j.qa.PORT}'}
        return boundary, env, calls

    def test_native_upload_completion_and_close_precede_drained_receipt(self):
        boundary, env, calls = self.boundary()
        result = boundary(env, lambda *args: None)
        self.assertEqual(result, [b'{"message":{"name":"native-file"}}'])
        self.assertEqual(calls, ['iterate', 'completed', 'closed'])
        self.assertTrue((self.temp / 'upload-drained.json').exists())
        j.http_drained(record())

    def test_native_callback_exception_retains_intent_without_drain_proof(self):
        boundary, env, calls = self.boundary(fail=True)
        with self.assertRaises(RuntimeError):
            boundary(env, lambda *args: None)
        self.assertEqual(calls, ['iterate', 'closed'])
        self.assertFalse((self.temp / 'upload-drained.json').exists())
        with self.assertRaises(FileNotFoundError):
            j.http_drained(record())


if __name__ == '__main__':
    unittest.main()
