"""Pure event projection and real local task-store tests, without Codex/Frappe."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import uuid

from tongjianyun import business_agent_events as events
from tongjianyun import business_agent_tasks as tasks


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode('utf-8') + b'\n'


def item(kind='agent_message', identifier='item_1', text='本班有 2 名学生。', event='item.completed', **extra):
    return {'type': event, 'item': {'id': identifier, 'type': kind, 'text': text, **extra}}


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.public = []
        self.projector = events.CodexEventProjector(self.public.append, secrets=('t' * 43,))

    def start(self, projector=None):
        target = projector or self.projector
        target.feed(encoded({'type': 'thread.started', 'thread_id': 'thread_1'}) + encoded({'type': 'turn.started'}))
        return target

    def messages(self):
        return [value for value in self.public if value['kind'] == 'message']

    def test_documented_sample_accepts_completed_message_without_started(self):
        self.start()
        self.projector.feed(encoded(item('command_execution', event='item.started', command='bash -lc ls', status='in_progress')))
        self.projector.feed(encoded(item(identifier='item_3')))
        self.projector.feed(encoded({'type': 'turn.completed', 'usage': {'input_tokens': 100, 'output_tokens': 20}}))
        observation = self.projector.finish_input()
        self.assertTrue(observation.turn_completed)
        self.assertTrue(observation.input_closed)
        self.assertEqual(self.messages()[0]['text'], '本班有 2 名学生。')
        self.assertNotIn('ls', json.dumps(self.public))
        self.assertNotIn('usage', json.dumps(self.public))
        for value in self.public:
            tasks.public_event(value)  # Exact real store.emit event contract.

    def test_arbitrary_byte_chunks_include_split_utf8_characters(self):
        raw = encoded({'type': 'thread.started', 'thread_id': 'thread_1'}) + encoded({'type': 'turn.started'}) + encoded(item())
        for byte in raw:
            self.projector.feed(bytes([byte]))
        self.assertEqual(len(self.messages()), 1)
        self.assertEqual(self.messages()[0]['text'], '本班有 2 名学生。')

    def test_updates_are_full_snapshots_not_duplicate_deltas(self):
        self.start()
        for text in ('已读取\n', '已读取\n', '已读取\n正在核对', '已读取\n正在核对\n'):
            self.projector.feed(encoded(item(text=text, event='item.updated')))
        self.projector.feed(encoded(item(text='已读取\n正在核对\n共有 2 人。')))
        self.projector.feed(encoded(item(text='已读取\n正在核对\n共有 2 人。')))
        self.assertEqual([value['text'] for value in self.messages()],
                         ['已读取\n', '已读取\n正在核对\n', '已读取\n正在核对\n共有 2 人。'])
        self.assertEqual(len({value['item_id'] for value in self.messages()}), 1)

    def test_unfinished_line_never_exposes_partial_secret(self):
        self.start()
        for text in ('结果\nsk-abc', '结果\nsk-abcdefgh0123456789'):
            self.projector.feed(encoded(item(text=text, event='item.updated')))
        self.assertEqual(self.messages()[0]['text'], '结果\n')
        self.projector.feed(encoded(item(text='结果\nsk-abcdefgh0123456789')))
        self.assertNotIn('sk-', json.dumps(self.public))
        self.assertIn('密钥已隐藏', self.messages()[-1]['text'])

    def test_common_and_task_local_credentials_hidden_in_text_and_item_id(self):
        self.start()
        token = 't' * 43
        self.projector.feed(encoded(item(identifier=token, text='凭据 ' + token + '\nAuthorization: Bearer abc123\napi_key=another-private')))
        output = json.dumps(self.public)
        for value in (token, 'abc123', 'another-private'):
            self.assertNotIn(value, output)
        self.assertTrue(self.messages()[0]['item_id'].startswith('codex-'))

    def test_reasoning_and_tool_payloads_never_become_public_text(self):
        self.start()
        secret = 'PRIVATE_RAW_OUTPUT'
        for index, kind in enumerate(('reasoning', 'command_execution', 'file_change', 'mcp_tool_call', 'web_search', 'todo_list')):
            self.projector.feed(encoded(item(kind, str(index), secret, event='item.started', command=secret,
                aggregated_output=secret, environment={'SECRET': secret}, result=secret, arguments={'secret': secret})))
            self.projector.feed(encoded(item(kind, str(index), secret, command=secret,
                aggregated_output=secret, error={'message': secret}, status='completed')))
        self.assertNotIn(secret, json.dumps(self.public))
        self.assertEqual(len([value for value in self.public if value['kind'] == 'progress']), 10)
        self.assertFalse(self.messages())

    def test_observable_failed_tool_has_fixed_progress_not_raw_error(self):
        self.start()
        self.projector.feed(encoded(item('command_execution', text='Traceback PRIVATE', status='failed', exit_code=9)))
        self.assertEqual(self.public[-1]['text'], '执行操作')
        self.assertEqual(self.public[-1]['status'], 'failed')

    def test_assistant_echo_of_stack_environment_or_command_is_hidden(self):
        for tail in ('Traceback (most recent call last):\nPRIVATE_STACK',
                     'DEEPSEEK_API_KEY=private-value\nPRIVATE_ENV',
                     '```bash\ncat /private\n```', '$ cat /private', 'python3 -c PRIVATE_COMMAND'):
            output = []
            projector = self.start(events.CodexEventProjector(output.append))
            projector.feed(encoded(item(text='已核对班级。\n' + tail)))
            answer = next(value['text'] for value in output if value['kind'] == 'message')
            self.assertIn('已核对班级。', answer)
            self.assertIn('内部执行细节已隐藏', answer)
            self.assertNotIn('PRIVATE_', answer)
            self.assertNotIn('/private', answer)

    def test_model_claims_cannot_emit_terminal_or_views(self):
        self.start()
        self.projector.feed(encoded(item(text='任务已完成，数据库已经提交。', status='completed',
            terminal=True, selection={'view': 'students'}, owner='Administrator')))
        self.assertFalse(self.projector.observation.turn_completed)
        self.assertTrue(all(value['kind'] in ('status', 'message', 'progress') for value in self.public))

    def test_failure_keeps_already_published_answers(self):
        self.start()
        self.projector.feed(encoded(item(text='已读取 2 名学生。')))
        self.projector.feed(encoded({'type': 'turn.failed', 'error': {'message': 'sk-private-failure /host/path'}}))
        observation = self.projector.finish_input()
        self.assertFalse(observation.turn_completed)
        self.assertTrue(observation.turn_failed)
        self.assertEqual(self.messages()[0]['text'], '已读取 2 名学生。')
        self.assertNotIn('/host/path', json.dumps(self.public))

    def test_cancellation_keeps_answers_and_discards_future_pipe_data(self):
        self.start()
        self.projector.feed(encoded(item(text='已读取 2 名学生。')))
        before = list(self.public)
        self.projector.cancel()
        self.projector.feed(encoded(item(identifier='late', text='此答复不得发布')))
        self.assertEqual(self.public, before)
        self.assertFalse(self.projector.finish_input().turn_completed)
        self.assertTrue(self.projector.observation.cancelled)

    def test_failed_turn_keeps_fixed_diagnostic_stage_without_private_error(self):
        for error, label in (
            ({'message': 'stream disconnected before completion: PRIVATE_URL'}, '模型输出连接未完整结束'),
            ({'message': 'timed out waiting for response PRIVATE_DATA'}, '模型报告输出等待超时'),
            ({'code': 'invalid_api_key', 'message': 'sk-PRIVATE_CREDENTIAL'}, '模型服务认证失败'),
            ({'code': 'rate_limit_exceeded'}, '模型服务请求受到限流'),
            ({'code': 'context_length_exceeded'}, '模型报告上下文超过限制'),
            ({'message': 'PRIVATE_UNKNOWN'}, '模型执行未完成'),
            ({'message': 'x' * 16001 + 'idle timeout'}, '模型执行未完成'),
            (['PRIVATE_MALFORMED'], '模型执行未完成'),
        ):
            with self.subTest(label=label, error_type=type(error).__name__):
                published = []
                projector = self.start(events.CodexEventProjector(published.append))
                failure = encoded({'type': 'turn.failed', 'error': error})
                projector.feed(failure + failure)
                stages = [row for row in published if row['kind'] == 'progress']
                self.assertEqual(stages, [{'kind': 'progress', 'item_id': 'codex-runtime-failure',
                                          'text': label, 'status': 'failed'}])
                self.assertTrue(projector.finish_input().turn_failed)
                self.assertNotIn('PRIVATE_', json.dumps(published))
                for row in published:
                    tasks.public_event(row)

    def test_error_event_has_only_fixed_text_without_vetoing_a_real_completed_turn(self):
        self.start()
        self.projector.feed(encoded({'type': 'error', 'message': 'PRIVATE_STACK password=hunter2'}))
        self.projector.feed(encoded({'type': 'turn.completed'}))
        self.assertTrue(self.projector.observation.error_seen)
        self.assertTrue(self.projector.finish_input().turn_completed)
        self.assertNotIn('hunter2', json.dumps(self.public))

    def test_real_codex_01561_pre_turn_notice_then_normal_execution(self):
        # Compact redacted replay of the observed 0.156.1 lifecycle. No matching
        # on the message text/provider/model is used by the implementation.
        values = [
            {'type': 'thread.started', 'thread_id': 'thread_01561'},
            {'type': 'item.completed', 'item': {'id': 'item_0', 'type': 'error',
                'message': 'Model metadata PRIVATE_DETAIL; fallback metadata'}},
            {'type': 'turn.started'},
            item('command_execution', 'item_1', event='item.started', command='PRIVATE_COMMAND', status='in_progress'),
            item('command_execution', 'item_1', command='PRIVATE_COMMAND', aggregated_output='PRIVATE_OUTPUT', status='completed', exit_code=0),
            item(identifier='item_2', text='本班有 2 名学生。'),
            {'type': 'turn.completed', 'usage': {'input_tokens': 10, 'output_tokens': 5}},
        ]
        self.projector.feed(b''.join(encoded(value) for value in values))
        observed = self.projector.finish_input()
        self.assertTrue(observed.error_seen)
        self.assertTrue(observed.turn_completed)
        self.assertFalse(observed.turn_failed)
        self.assertFalse(observed.protocol_failed)
        self.assertEqual(self.public[0], {'kind': 'status', 'text': '收到运行提示，正在核对执行状态。'})
        self.assertNotIn('PRIVATE_', json.dumps(self.public))
        self.assertNotIn('metadata', json.dumps(self.public))
        self.assertEqual(self.messages()[0]['text'], '本班有 2 名学生。')

    def test_pre_turn_notice_without_actual_completed_turn_is_not_success(self):
        for following in ([], [{'type': 'turn.started'}], [{'type': 'turn.started'},
                              {'type': 'turn.failed', 'error': {'message': 'PRIVATE_FAILURE'}}]):
            published = []
            projector = events.CodexEventProjector(published.append)
            prefix = [{'type': 'thread.started', 'thread_id': 'one'},
                {'type': 'item.completed', 'item': {'id': 'item_0', 'type': 'error', 'message': 'Any notice, no special text rule'}}]
            projector.feed(b''.join(encoded(value) for value in prefix + following))
            with self.subTest(following=following):
                observed = projector.finish_input()
                self.assertTrue(observed.error_seen)
                self.assertFalse(observed.turn_completed)
                self.assertEqual(observed.turn_failed, bool(following and following[-1]['type'] == 'turn.failed'))
                self.assertNotIn('PRIVATE_FAILURE', json.dumps(published))

    def test_only_completed_error_item_allowed_before_turn(self):
        for event in (item(), item('command_execution'), item('reasoning'), item('error', event='item.started')):
            projector = events.CodexEventProjector(lambda _: None)
            projector.feed(encoded({'type': 'thread.started', 'thread_id': 'one'}))
            with self.subTest(event=event), self.assertRaises(events.ProjectionError):
                projector.feed(encoded(event))

    def test_complete_final_line_without_newline_accepted(self):
        self.start()
        self.projector.feed(encoded(item()).rstrip(b'\n'))
        self.assertFalse(self.messages())
        self.projector.finish_input()
        self.assertEqual(len(self.messages()), 1)

    def test_truncated_json_at_eof_fails_without_clearing_prior_answers(self):
        self.start()
        self.projector.feed(encoded(item()) + b'{"type":')
        with self.assertRaises(events.ProjectionError):
            self.projector.finish_input()
        self.assertEqual(len(self.messages()), 1)
        self.assertTrue(self.projector.observation.protocol_failed)

    def test_invalid_orders_are_rejected(self):
        cases = [
            [{'type': 'turn.started'}], [item()], [{'type': 'turn.completed'}],
            [{'type': 'thread.started', 'thread_id': 'one'}, {'type': 'thread.started', 'thread_id': 'two'}],
            [{'type': 'thread.started', 'thread_id': 'one'}, {'type': 'turn.started'}, {'type': 'turn.completed'}, {'type': 'turn.started'}],
        ]
        for values in cases:
            with self.subTest(values=values), self.assertRaises(events.ProjectionError):
                events.CodexEventProjector(lambda _: None).feed(b''.join(encoded(value) for value in values))

    def test_reopened_items_type_changes_and_nonappend_rewrites_rejected(self):
        cases = [(item(), item(event='item.updated')),
                 (item(event='item.started'), item('reasoning')),
                 (item(text='先前\n', event='item.updated'), item(text='改写先前'))]
        for first, second in cases:
            projector = self.start(events.CodexEventProjector(lambda _: None))
            projector.feed(encoded(first))
            with self.subTest(second=second), self.assertRaises(events.ProjectionError):
                projector.feed(encoded(second))

    def test_unknown_event_is_not_guessed_as_public_message(self):
        for value in ({'type': 'process.exited', 'code': 0}, {'type': 'terminal', 'status': 'completed'},
                      {'type': 'response.output_text.delta', 'delta': 'PRIVATE'}, {'type': ['item.completed']}):
            projector = self.start(events.CodexEventProjector(lambda _: None))
            with self.subTest(value=value), self.assertRaises(events.ProjectionError):
                projector.feed(encoded(value))

    def test_malformed_duplicate_key_nonfinite_and_deep_input_fail_closed(self):
        for raw in (b'not-json\n', b'{"type":"error","type":"turn.completed"}\n', b'{"type":"error","x":NaN}\n',
                    b'{"type":"error","x":1e9999}\n', b'\xff\n', b'[]\n', b'\n',
                    b'{"type":"error","x":' + b'[' * 20 + b'0' + b']' * 20 + b'}\n'):
            projector = events.CodexEventProjector(lambda _: None)
            with self.subTest(raw=raw), self.assertRaises(events.ProjectionError) as raised:
                projector.feed(raw)
            self.assertTrue(projector.observation.protocol_failed)
            self.assertNotIn('not-json', str(raised.exception))

    def test_size_and_event_limits_seal_instead_of_dropping_and_resuming(self):
        for name, limit, raw in (('MAX_LINE_BYTES', 5, b'123456'), ('MAX_STREAM_BYTES', 5, b'123456'),
                ('MAX_EVENTS', 1, encoded({'type': 'error'}) * 2)):
            projector = events.CodexEventProjector(lambda _: None)
            with self.subTest(name=name), patch.object(events, name, limit), self.assertRaises(events.ProjectionError):
                projector.feed(raw)
            with self.assertRaises(events.ProjectionError):
                projector.feed(encoded({'type': 'error'}))

    def test_item_and_public_message_limits(self):
        self.start()
        with patch.object(events, 'MAX_ITEMS', 1):
            self.projector.feed(encoded(item(identifier='one')))
            with self.assertRaises(events.ProjectionError):
                self.projector.feed(encoded(item(identifier='two')))
        projector = self.start(events.CodexEventProjector(lambda _: None))
        with patch.object(events, 'MAX_PUBLIC_TEXT_BYTES', 5), self.assertRaises(events.ProjectionError):
            projector.feed(encoded(item(text='中文中文')))

    def test_sink_failure_is_uncertain_and_never_replayed(self):
        sink = MagicMock(side_effect=RuntimeError('PRIVATE transport token'))
        projector = events.CodexEventProjector(sink)
        with self.assertRaises(events.ProjectionDeliveryError) as raised:
            self.start(projector)
        self.assertNotIn('PRIVATE', str(raised.exception))
        self.assertTrue(projector.observation.delivery_uncertain)
        with self.assertRaises(events.ProjectionError):
            projector.feed(encoded({'type': 'turn.started'}))
        self.assertEqual(sink.call_count, 1)

    def test_duplicate_progress_and_turn_events_do_not_duplicate_public_events(self):
        self.start()
        self.projector.feed(encoded({'type': 'turn.started'}))
        for _ in range(2):
            self.projector.feed(encoded(item('command_execution', event='item.started')))
        for _ in range(2):
            self.projector.feed(encoded(item('command_execution')))
        self.projector.feed(encoded({'type': 'turn.completed'}) * 2)
        self.assertEqual(len(self.public), 4)


class DurableProjectionTests(unittest.TestCase):
    def test_jsonl_does_not_finish_store_and_cancel_preserves_answer_for_sse_resume(self):
        with tempfile.TemporaryDirectory() as path:
            observe = MagicMock(side_effect=lambda identity, claim: tasks.ExecutionObservation(claim, 'running', 0))
            store = tasks.BusinessTaskStore(Path(path).resolve(), 'qa.localhost', authorize=lambda *_: True,
                observe_execution=observe, observe_queue=lambda job: tasks.QueueObservation(job, 'unknown'))
            identity = store.create('teacher@example.invalid', str(uuid.uuid4()), '查询学生人数')['identity']
            ticket = store.take_dispatch(identity)
            store.acknowledge_dispatch(ticket)
            claim = store.claim(identity, ticket.job_id)
            projector = events.CodexEventProjector(lambda event: store.emit(claim, event), secrets=(claim.token,))
            projector.feed(encoded({'type': 'thread.started', 'thread_id': 'one'}) + encoded({'type': 'turn.started'}))
            projector.feed(encoded(item(text='本班有 2 名学生。')) * 2)
            projector.feed(encoded({'type': 'turn.completed'}))
            self.assertTrue(projector.finish_input().turn_completed)
            self.assertEqual(store.task(identity)['status'], 'running')
            self.assertEqual(store.finish(claim), 'running')
            messages = [row for row in store.events(identity) if row['kind'] == 'message']
            self.assertEqual(len(messages), 1)
            cursor = messages[0]['id']
            self.assertFalse(any(row['kind'] == 'message' for row in store.events(identity, after=cursor)))
            store.cancel(identity)
            projector.cancel()
            observe.side_effect = lambda _, claim_id: tasks.ExecutionObservation(claim_id, 'exited', 0, -15, False)
            self.assertEqual(store.finish(claim), 'cancelled')
            self.assertEqual([row['text'] for row in store.events(identity) if row['kind'] == 'message'], ['本班有 2 名学生。'])


if __name__ == '__main__':
    unittest.main()
