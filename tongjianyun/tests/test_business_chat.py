"""Durable-store/web contracts. No model, server launch or business DB writes."""
from contextlib import ExitStack, nullcontext
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import uuid

import frappe
from tongjianyun import business_chat as http
from tongjianyun import business_agent_service as service
from tongjianyun.business_agent_authority import Viewer
from tongjianyun.business_agent_tasks import BusinessTaskStore, TaskIdentity, ExecutionObservation, QueueObservation


class BusinessChatApplicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.site, self.owner = 'qa.localhost', 'teacher@example.invalid'
        self.viewer = Viewer(self.site, self.owner, 's' * 32)
        self.allowed, self.session_active = True, True
        self.queue_state = 'absent'
        self.queue = SimpleNamespace(site=self.site, enqueue=MagicMock())
        self.authority = SimpleNamespace(site=self.site, capture_viewer=lambda: self.viewer,
            viewer_active=lambda viewer, *args: self.session_active and isinstance(viewer, Viewer) and viewer.site == self.site,
            view_scopes=MagicMock(return_value=()))
        self.store = BusinessTaskStore(Path(self.tmp.name).resolve(), self.site,
            authorize=lambda identity, scopes: self.allowed,
            observe_execution=lambda identity, claim_id: ExecutionObservation(claim_id, 'running', 0),
            observe_queue=lambda job_id: QueueObservation(job_id, self.queue_state))
        self.app = service.BusinessChatApplication(self.store, self.authority, self.queue, lock=lambda *args: nullcontext())
        self.id = str(uuid.uuid4())
        self.identity = TaskIdentity(self.site, self.owner, self.id)
        self.context = {'day': '2026-09-16', 'meal': 'lunch'}

    def submit(self, **kwargs):
        return self.app.submit(self.viewer, kwargs.get('task_id', self.id), kwargs.get('message', '查询本班学生'),
                               kwargs.get('context', self.context))

    def running(self):
        self.submit()
        return self.store.claim(self.identity, self.store.job_id(self.identity))

    def test_submit_uses_trusted_owner_and_separate_queue(self):
        result = self.submit()
        self.assertTrue(result['accepted'])
        ticket = self.queue.enqueue.call_args.args[0]
        self.assertEqual(ticket.identity, self.identity)
        self.assertEqual(ticket.queue, 'business_codex')
        self.assertNotIn('sid', str(result))
        self.assertNotIn(ticket.token, str(result))

    def test_same_id_same_payload_is_deduplicated_when_job_present(self):
        self.submit()
        self.queue_state = 'present'
        self.assertTrue(self.submit()['accepted'])
        self.assertEqual(self.queue.enqueue.call_count, 1)

    def test_same_id_different_request_is_not_accepted(self):
        self.submit()
        with self.assertRaises(ValueError):
            self.submit(message='另一个请求')
        with self.assertRaises(ValueError):
            self.submit(context={**self.context, 'day': '2026-09-17'})
        self.assertEqual(self.queue.enqueue.call_count, 1)

    def test_other_active_task_returned_without_creating_second(self):
        self.submit()
        new_id = str(uuid.uuid4())
        result = self.submit(task_id=new_id)
        self.assertEqual(result, {'accepted': False, 'task_id': self.id, 'status': 'queued'})
        self.assertIsNone(self.store.find_task(TaskIdentity(self.site, self.owner, new_id)))

    def attach_adapter(self):
        self.descriptor = {'version':1, 'file_id':'FILE-1', 'display_name':'meal.csv', 'format':'csv',
                           'size':20, 'sha256':'a'*64, 'revision':'b'*64}
        self.app.attachments = SimpleNamespace(prepare=MagicMock(return_value=self.descriptor))
        return self.app.attachments

    def test_attachment_prepared_with_trusted_identity_bound_and_registered_before_dispatch(self):
        adapter = self.attach_adapter()
        result = self.app.submit(self.viewer, self.id, '分析食谱', self.context, file_name='FILE-1')
        self.assertTrue(result['accepted'])
        adapter.prepare.assert_called_once_with(self.identity, 'FILE-1')
        self.assertEqual(self.store.task(self.identity)['context']['attachments'], [self.descriptor])
        self.assertIn({'kind':'attachment','descriptor':self.descriptor}, self.store.required_scopes(self.identity))
        self.assertEqual(self.app.conversation(self.viewer)['tasks'][0]['file_name'], 'meal.csv')

    def test_same_request_cannot_substitute_or_modify_attachment(self):
        adapter = self.attach_adapter()
        self.app.submit(self.viewer, self.id, '分析', self.context, file_name='FILE-1')
        self.queue_state = 'present'
        self.assertTrue(self.app.submit(self.viewer, self.id, '分析', self.context, file_name='FILE-1')['accepted'])
        adapter.prepare.return_value = {**self.descriptor, 'sha256':'c'*64}
        with self.assertRaises(ValueError):
            self.app.submit(self.viewer, self.id, '分析', self.context, file_name='FILE-1')
        self.assertEqual(self.queue.enqueue.call_count, 1)

    def test_existing_task_file_error_is_not_reported_as_never_accepted(self):
        from tongjianyun.business_agent_attachments import AttachmentInputError
        adapter = self.attach_adapter()
        self.app.submit(self.viewer, self.id, '分析', self.context, file_name='FILE-1')
        adapter.prepare.side_effect = AttachmentInputError('invalid_content')
        with self.assertRaises(PermissionError):
            self.app.submit(self.viewer, self.id, '分析', self.context, file_name='FILE-1')
        self.assertEqual(self.queue.enqueue.call_count, 1)

    def test_attachment_permission_failure_creates_no_task_and_does_not_dispatch(self):
        adapter = self.attach_adapter()
        adapter.prepare.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            self.app.submit(self.viewer, self.id, '分析', self.context, file_name='FILE-1')
        self.assertIsNone(self.store.find_task(self.identity))
        self.queue.enqueue.assert_not_called()

    def test_other_active_task_does_not_read_or_bind_unsent_attachment(self):
        self.submit()
        adapter = self.attach_adapter()
        result = self.app.submit(self.viewer, str(uuid.uuid4()), '分析', self.context, file_name='FILE-1')
        self.assertFalse(result['accepted'])
        adapter.prepare.assert_not_called()

    def test_caller_cannot_supply_a_trusted_attachment_descriptor(self):
        self.attach_adapter()
        with self.assertRaises(ValueError):
            self.app.submit(self.viewer, self.id, '分析', {**self.context, 'attachments':[self.descriptor]})
        self.queue.enqueue.assert_not_called()

    def test_unconfigured_attachment_adapter_fails_not_silent_drop(self):
        with self.assertRaises(ValueError):
            self.app.submit(self.viewer, self.id, '分析', self.context, file_name='FILE-1')
        self.assertIsNone(self.store.find_task(self.identity))

    def test_active_lookup_is_not_limited_by_recent_history(self):
        self.submit()
        with self.store._transaction() as db:
            for i in range(25):
                new_id = str(uuid.uuid4())
                # Synthetic store fixtures only, no Frappe/database business data.
                db.execute('INSERT INTO tasks (task_id,owner,mode,status,message,context,digest,created,updated) '
                           'VALUES (?,?,?,?,?,?,?,?,?)', (new_id,self.owner,'business','completed','done','{}',str(i),0,0))
        self.assertEqual(self.store.active_task(self.owner)['task_id'], self.id)

    def test_different_owners_do_not_share_active_or_history(self):
        self.submit()
        other = replace(self.viewer, owner='other@example.invalid')
        result = self.app.submit(other, str(uuid.uuid4()), '其他班', self.context)
        self.assertTrue(result['accepted'])
        history = self.app.conversation(other)
        self.assertEqual(len(history['tasks']), 1)
        self.assertNotEqual(history['tasks'][0]['task_id'], self.id)
        for method in (lambda: self.app.cancel(other, self.id), lambda: self.app.event_page(other, self.id),
                       lambda: self.app.retry_dispatch(other, self.id)):
            with self.assertRaises(PermissionError):
                method()

    def test_request_uuid_collision_cannot_be_adopted_by_another_owner(self):
        self.submit()
        with self.assertRaises(PermissionError):
            self.app.submit(replace(self.viewer, owner='other'), self.id, '查询本班学生', self.context)

    def test_enqueue_response_loss_keeps_task_and_waits_for_observation(self):
        self.queue.enqueue.side_effect = ConnectionError('private redis address')
        result = self.submit()
        self.assertEqual(result['delivery'], 'unconfirmed')
        self.assertEqual(self.store.task(self.identity)['status'], 'queued')
        self.queue_state = 'unknown'
        self.app.retry_dispatch(self.viewer, self.id)
        self.assertEqual(self.queue.enqueue.call_count, 1)
        self.queue_state = 'present'
        self.app.retry_dispatch(self.viewer, self.id)
        self.assertEqual(self.queue.enqueue.call_count, 1)

    def test_verified_lost_unclaimed_job_can_redispatch_same_identity(self):
        self.submit()
        self.queue_state = 'absent'
        self.app.retry_dispatch(self.viewer, self.id)
        self.assertEqual(self.queue.enqueue.call_count, 2)
        self.assertEqual(self.queue.enqueue.call_args.args[0].identity, self.identity)

    def test_claimed_task_is_never_reexecuted_even_if_queue_job_disappears(self):
        claim = self.running()
        self.queue_state = 'absent'
        self.app.retry_dispatch(self.viewer, self.id)
        self.assertEqual(self.queue.enqueue.call_count, 1)
        self.assertEqual(self.store.binding_state(claim)['status'], 'running')

    def test_cancelled_unclaimed_task_cannot_redispatch(self):
        self.submit()
        self.assertEqual(self.app.cancel(self.viewer, self.id)['status'], 'cancelled')
        self.app.retry_dispatch(self.viewer, self.id)
        self.assertEqual(self.queue.enqueue.call_count, 1)

    def test_running_cancel_is_stopping_not_false_terminal(self):
        self.running()
        self.assertEqual(self.app.cancel(self.viewer, self.id)['status'], 'stopping')
        self.assertFalse(self.submit(task_id=str(uuid.uuid4()))['accepted'])

    def test_dead_worker_history_reconciles_without_restart_or_success_claim(self):
        claim = self.running()
        self.store.observe_execution = lambda identity,claim_id: ExecutionObservation(claim_id,'exited',0,0,True,True)
        history = self.app.conversation(self.viewer)
        self.assertEqual(history['tasks'][0]['status'],'failed')
        self.assertEqual(history['tasks'][0]['events'][-1]['kind'],'terminal')
        self.assertEqual(self.queue.enqueue.call_count,1)

    def test_runtime_observation_error_does_not_block_cancel(self):
        self.running()
        self.store.observe_execution = MagicMock(side_effect=ConnectionError)
        self.assertEqual(self.app.cancel(self.viewer,self.id)['status'],'stopping')
        self.assertEqual(self.queue.enqueue.call_count,1)

    def test_closed_lease_cancel_is_proven_then_terminal(self):
        self.running()
        self.store.observe_execution = lambda identity,claim_id: ExecutionObservation(claim_id,'exited',0,0,False,True)
        self.assertEqual(self.app.cancel(self.viewer,self.id)['status'],'cancelled')

    def test_history_event_pages_are_contiguous_and_do_not_jump_to_tip(self):
        claim = self.running()
        for i in range(215):
            self.store.emit(claim, {'kind': 'message', 'item_id': 'answer', 'text': str(i)})
        history = self.app.conversation(self.viewer)
        task = history['tasks'][0]
        events = task['events']
        self.assertEqual(len(events), 100)
        self.assertNotEqual(task['next_after'], task['last_event_id'])
        cursor = task['next_after']
        while cursor:
            page = self.app.event_page(self.viewer, self.id, cursor)
            events.extend(page['events'])
            cursor = page['next_after']
        self.assertEqual(len(events), 217)
        self.assertEqual([e['id'] for e in events], [self.id + ':' + str(i) for i in range(1, 218)])

    def test_cursor_from_another_task_rejected_before_stream_response(self):
        self.submit()
        with self.assertRaises(ValueError):
            self.app.stream(self.viewer, self.id, str(uuid.uuid4()) + ':1')

    def test_stream_logout_does_not_cancel_task(self):
        self.running()
        stream = self.app.stream(self.viewer, self.id)
        next(stream)
        self.session_active = False
        self.assertIn('event: unavailable', next(stream))
        self.assertEqual(self.store._owned(self.identity)['status'], 'running')
        stream.close()

    def test_lost_business_authority_denies_history_and_requests_stop(self):
        self.running()
        self.allowed = False
        with self.assertRaises(PermissionError):
            self.app.conversation(self.viewer)
        self.assertEqual(self.store._owned(self.identity)['status'], 'stopping')

    def test_selection_admission_is_checked_before_task_creation(self):
        self.authority.view_scopes.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            self.submit(context={**self.context, 'selection': {'view': 'classroom_day', 'group': 'FOREIGN'}})
        self.assertIsNone(self.store.find_task(self.identity))

    def test_disabled_browser_session_creates_no_task(self):
        self.session_active = False
        with self.assertRaises(PermissionError):
            self.submit()
        self.assertIsNone(self.store.find_task(self.identity))


class BusinessChatHttpTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.account = self.stack.enter_context(patch.object(http, 'require_account'))
        self.stack.enter_context(patch.object(http, 'mark_private_response'))
        self.app = MagicMock()
        self.factory = self.stack.enter_context(patch.object(http, 'application', return_value=(self.app, MagicMock())))
        self.viewer = self.app.viewer.return_value
        self.id = str(uuid.uuid4())
        self.stack.enter_context(patch('tongjianyun.meal_scene.business_day', return_value='2026-09-16'))
        self.stack.enter_context(patch('tongjianyun.meal_scene.meal_key', return_value='lunch'))

    def test_login_checked_before_store_or_runtime(self):
        self.account.side_effect = frappe.PermissionError
        with self.assertRaises(frappe.PermissionError):
            http.send_message(message='hi', stream=1)
        self.factory.assert_not_called()

    def test_send_uses_authenticated_viewer_not_request_identity(self):
        http.send_message(message='查人数', request_id=self.id, stream=1)
        self.factory.assert_called_once_with(require_ready=True)
        self.app.submit.assert_called_once_with(self.viewer, self.id, '查人数', {'day':'2026-09-16','meal':'lunch'})

    def test_cancel_and_history_do_not_require_live_launcher_or_model_key(self):
        http.cancel_task(self.id)
        self.factory.assert_called_with(require_ready=False)
        http.get_conversation()
        self.factory.assert_called_with(require_ready=False)

    def test_no_actor_site_command_or_path_arguments(self):
        for kwargs in ({'owner':'Administrator'}, {'site':'other'}, {'mode':'admin'}, {'command':'whoami'}, {'directory':'/'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(TypeError):
                http.send_message(message='hi', stream=1, **kwargs)
        self.app.submit.assert_not_called()

    def test_invalid_attachment_identifiers_rejected_before_submission(self):
        for attachment in ('', {'path':'/private/file'}, 'x'*141, 'File\0name'):
            with self.subTest(attachment=attachment), self.assertRaises(frappe.ValidationError):
                http.send_message(message='read', file_name=attachment, stream=1)
        self.app.submit.assert_not_called()

    def test_attachment_id_is_passed_only_to_the_trusted_application(self):
        http.send_message(message='分析表格', file_name='FILE-1', request_id=self.id, stream=1)
        self.app.submit.assert_called_once_with(self.viewer, self.id, '分析表格',
            {'day':'2026-09-16','meal':'lunch'}, file_name='FILE-1')

    def test_file_only_request_means_analysis_not_an_implicit_write(self):
        http.send_message(file_name='FILE-1', request_id=self.id, stream=1)
        self.assertEqual(self.app.submit.call_args.args[2], '请分析上传的文件。')

    def test_attachment_input_errors_are_fixed_helpful_messages_not_parser_details(self):
        from tongjianyun.business_agent_attachments import AttachmentInputError
        self.app.submit.side_effect = AttachmentInputError('encoding')
        with self.assertRaises(frappe.ValidationError) as error:
            http.send_message(message='分析', file_name='FILE-1', request_id=self.id, stream=1)
        self.assertIn('UTF-8', str(error.exception))
        self.assertTrue(frappe.local.response['business_request_not_accepted'])
        self.app.submit.side_effect = ValueError('/private/path raw cell secret')
        with self.assertRaises(frappe.ValidationError) as error:
            http.send_message(message='分析', file_name='FILE-1', request_id=self.id, stream=1)
        self.assertNotIn('/private', str(error.exception))

    def test_bad_message_uuid_and_context_fail_before_submit(self):
        values = ({'message':['x']}, {'message':''}, {'message':'x'*8001}, {'request_id':'../escape'},
                  {'view_context':'{"view":"students","view":"frappe_new"}'},
                  {'view_context':{'view':'students','actor':'Administrator'}}, {'view_context':{'view':'students','html':'<script>'}})
        for kwargs in values:
            with self.subTest(kwargs=str(kwargs)[:80]), self.assertRaises(frappe.ValidationError):
                http.send_message(**{'message':'hi','stream':1,**kwargs})
        self.app.submit.assert_not_called()

    def test_sse_respects_last_event_id_and_disables_buffering(self):
        self.app.stream.return_value = iter([': heartbeat\n\n'])
        with patch.object(frappe, 'get_request_header', return_value=self.id + ':7'):
            response = http.stream_events(self.id, after='0')
        self.app.stream.assert_called_once_with(self.viewer, self.id, self.id + ':7')
        self.assertEqual(response.headers['X-Accel-Buffering'], 'no')
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertIn(': heartbeat', response.get_data(as_text=True))

    def test_private_exception_details_not_returned(self):
        self.factory.side_effect = OSError('private model key path')
        with self.assertRaises(frappe.PermissionError) as error:
            http.get_conversation()
        self.assertNotIn('private model key path', str(error.exception))

    def test_get_endpoints_do_not_enqueue_or_allow_get_writes(self):
        for method in (http.send_message, http.cancel_task, http.retry_dispatch):
            self.assertEqual(tuple(frappe.allowed_http_methods_for_whitelisted_func[method]), ('POST',))
        for method in (http.get_conversation, http.get_events, http.stream_events):
            # This native Frappe adds its read-only QUERY method to GET APIs.
            methods = set(frappe.allowed_http_methods_for_whitelisted_func[method])
            self.assertIn('GET', methods)
            self.assertTrue(methods <= {'GET', 'QUERY'})
        self.assertNotIn(service.run_task, frappe.whitelisted)


class BusinessQueueTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(frappe, 'local', SimpleNamespace(site='qa.localhost')))
        self.queue = service.FrappeBusinessQueue('qa.localhost')
        self.get_job = self.stack.enter_context(patch('frappe.utils.background_jobs.get_job'))

    def test_unknown_or_network_error_is_not_absence(self):
        self.get_job.side_effect = ConnectionError
        self.assertEqual(self.queue.observe('job').state, 'unknown')
        self.get_job.side_effect = None
        self.get_job.return_value.get_status.return_value = 'alien'
        self.assertEqual(self.queue.observe('job').state, 'unknown')

    def test_native_rq_statuses_classified_without_age_heuristic(self):
        for status in ('queued','started','deferred','scheduled'):
            self.get_job.return_value.get_status.return_value = status
            self.assertEqual(self.queue.observe('job').state, 'present')
        for status in ('finished','failed','stopped','canceled'):
            self.get_job.return_value.get_status.return_value = status
            self.assertEqual(self.queue.observe('job').state, 'absent')
        self.get_job.return_value = None
        self.assertEqual(self.queue.observe('job').state, 'absent')

    def test_wrong_site_cannot_observe_or_enqueue(self):
        frappe.local.site = 'other'
        with self.assertRaises(PermissionError):
            self.queue.observe('job')
        self.get_job.assert_not_called()

    def test_rq_receives_only_server_identity_not_prompt_credentials_or_claim(self):
        from tongjianyun.business_agent_tasks import DispatchTicket
        identity = TaskIdentity('qa.localhost','teacher',str(uuid.uuid4()))
        with patch.object(frappe, 'enqueue') as enqueue:
            self.queue.enqueue(DispatchTicket(identity,'business_codex','job','t'*43))
        kwargs = enqueue.call_args.kwargs
        self.assertEqual(kwargs, dict(queue='business_codex',timeout=-1,is_async=True,enqueue_after_commit=False,
            deduplicate=True,retry=None,job_id='job',owner='teacher',task_id=identity.task_id))
        self.assertEqual(enqueue.call_args.args, (service.WORKER_METHOD,))

    def test_readiness_requires_actual_worker_on_business_queue(self):
        worker = MagicMock(last_heartbeat=datetime.now(timezone.utc)-timedelta(seconds=2))
        worker.get_state.return_value = 'idle'
        worker.queue_names.return_value = ['bench:business_codex']
        with patch('rq.Worker.all', return_value=[worker]), patch('frappe.utils.background_jobs.get_queue',
                return_value=SimpleNamespace(name='bench:business_codex')):
            self.assertTrue(self.queue.ready())
            worker.queue_names.return_value = ['bench:meal_chat']
            self.assertFalse(self.queue.ready())
            worker.queue_names.return_value = ['bench:business_codex']
            worker.last_heartbeat = datetime.now(timezone.utc)-timedelta(hours=1)
            self.assertFalse(self.queue.ready())

    def test_switch_alone_cannot_enable_chat(self):
        with patch.object(frappe, 'conf', {'business_codex_enabled':1}), \
                patch.object(service,'_configured_runtime') as runtime, patch.object(service,'_model_key') as key:
            runtime.return_value.ready.return_value = False
            self.assertFalse(service.available())
            key.assert_not_called()

    def test_disabled_switch_does_not_touch_runtime_or_key(self):
        for value in (None,False,0,'1','true',{},[]):
            with patch.object(frappe,'conf',{'business_codex_enabled':value}), patch.object(service,'_configured_runtime') as runtime:
                self.assertFalse(service.available())
                runtime.assert_not_called()


@unittest.skipUnless(os.name == 'posix', 'Linux deployment guard')
class SubmissionLockTests(unittest.TestCase):
    def test_private_lock_serializes_and_releases(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name).resolve()
            with service.submission_lock(path, 'teacher'):
                with patch.object(service.time, 'monotonic', side_effect=[0,4]), self.assertRaises(ValueError):
                    with service.submission_lock(path, 'teacher'):
                        self.fail('concurrent submission acquired owner lock')
            with service.submission_lock(path, 'teacher'):
                pass

    def test_symlink_lock_is_not_opened(self):
        import hashlib
        with tempfile.TemporaryDirectory() as name:
            path = Path(name).resolve()
            target = path / ('submit-' + hashlib.sha256(b'teacher').hexdigest() + '.lock')
            target.symlink_to(path / 'other')
            with self.assertRaises(OSError):
                with service.submission_lock(path, 'teacher'):
                    self.fail('opened symlink')


@unittest.skipUnless(os.name == 'posix', 'Linux private deployment files')
class BusinessDeploymentGateTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tmp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.sites = Path(self.tmp).resolve()
        self.site = 'qa.localhost'
        self.directory = self.sites / self.site / 'private' / 'business-codex' / 'tasks'
        self.directory.mkdir(parents=True, mode=0o700)
        self.stack.enter_context(patch.object(frappe,'local',SimpleNamespace(site=self.site,sites_path=str(self.sites))))
        self.stack.enter_context(patch.object(frappe,'conf',{'business_codex_enabled':0}))

    def provision_store(self):
        return BusinessTaskStore(self.directory,self.site,authorize=lambda *args:True,
            observe_execution=lambda identity,claim_id:ExecutionObservation(claim_id,'unknown',0),
            observe_queue=lambda job_id:QueueObservation(job_id,'unknown'))

    def test_unprovisioned_store_does_not_claim_chat_available(self):
        with patch.object(service,'available') as runtime:
            self.assertFalse(service.chat_access()['allowed'])
        runtime.assert_not_called()

    def test_existing_history_survives_disabled_executor(self):
        self.provision_store()
        with patch.object(service,'available',return_value=False):
            access = service.chat_access()
        self.assertTrue(access['allowed'])
        self.assertFalse(access['can_submit'])

    def test_read_application_does_not_touch_key_or_launcher_readiness(self):
        self.provision_store()
        with patch.object(service,'_configured_runtime') as runtime, patch.object(service,'_model_key') as key:
            app, composed = service.application(require_ready=False)
            self.assertEqual(app.store.directory,self.directory)
            self.assertIs(composed.native, runtime.return_value)
            self.assertIs(composed.write_ledger, app.writes.ledger)
            self.assertEqual(app.store.observe_execution, composed.observe)
            self.assertEqual(app.store.seal_execution, composed.seal_before_start)
            self.assertIs(app.recipes.store, app.store)
            self.assertIs(app.recipes.authority, app.authority)
            runtime.return_value.ready.assert_not_called()
            key.assert_not_called()

    def test_recipe_and_class_writes_share_ledger_but_route_exact_adapters(self):
        self.provision_store()
        with patch.object(service, '_configured_runtime'), \
                patch('tongjianyun.business_agent_write_adapter.FrappeWriteAdapter') as classroom, \
                patch('tongjianyun.business_agent_recipes.RecipeWriteAdapter') as recipe:
            app, runtime = service.application(require_ready=False)
        classroom.assert_called_once_with(self.site, str(self.sites), store=app.store)
        recipe.assert_called_once_with(self.site, str(self.sites), store=app.store, authority=app.authority)
        self.assertIs(app.recipes, recipe.return_value.reader)
        self.assertIs(runtime.write_ledger, app.writes.ledger)
        claim, args, operation = object(), {'payload': 'not interpreted by router'}, str(uuid.uuid4())
        app.writes.ledger.authorize(claim, 'recipe_save', args)
        recipe.return_value.authorize.assert_called_once_with(claim, 'recipe_save', args)
        app.writes.transaction_factory(claim, 'recipe_save', args, operation_id=operation)
        recipe.return_value.transaction_factory.assert_called_once_with(claim, 'recipe_save', args, operation_id=operation)
        app.writes.fresh_read(claim, 'recipe_save', args, operation_id=operation)
        recipe.return_value.fresh_read.assert_called_once_with(claim, 'recipe_save', args, operation_id=operation)
        for tool in ('attendance_save', 'meal_save'):
            app.writes.ledger.authorize(claim, tool, args)
            app.writes.transaction_factory(claim, tool, args)
            app.writes.fresh_read(claim, tool, args)
            classroom.return_value.authorize.assert_called_with(claim, tool, args)
            classroom.return_value.transaction_factory.assert_called_with(claim, tool, args)
            classroom.return_value.fresh_read.assert_called_with(claim, tool, args)
            for callback in (app.writes.transaction_factory, app.writes.fresh_read):
                with self.assertRaises(ValueError):
                    callback(claim, tool, args, operation_id=operation)
        for callback in (app.writes.ledger.authorize, app.writes.transaction_factory, app.writes.fresh_read):
            with self.assertRaises(PermissionError):
                callback(claim, 'arbitrary_method', args)

    def test_new_submission_disabled_before_key_runtime_or_store(self):
        with patch.object(service,'_configured_runtime') as runtime, patch.object(service,'_model_key') as key:
            with self.assertRaises(PermissionError):
                service.application(require_ready=True)
            runtime.assert_not_called()
            key.assert_not_called()

    def test_world_readable_store_is_not_advertised(self):
        self.provision_store()
        (self.directory/'business-tasks.sqlite3').chmod(0o644)
        self.assertFalse(service.chat_access()['allowed'])

    def test_model_key_is_private_bounded_and_never_follows_symlinks(self):
        key = self.sites / 'credential'
        key.write_text('qa-placeholder-credential-only\n')
        key.chmod(0o600)
        with patch.object(service,'MODEL_KEY_PATH',key):
            self.assertEqual(service._model_key(),'qa-placeholder-credential-only')
            key.chmod(0o644)
            with self.assertRaises(PermissionError):
                service._model_key()
        key.chmod(0o600)
        link = self.sites / 'credential-link'
        link.symlink_to(key)
        with patch.object(service,'MODEL_KEY_PATH',link), self.assertRaises(PermissionError):
            service._model_key()
