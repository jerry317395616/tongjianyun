"""Streaming, recovery, authorization and unlimited background execution checks."""
import json
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tongjianyun import meal_chat
from tongjianyun.meal_chat_events import process_events, progress_event, sse_frame

TASK = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'


class MealChatTests(unittest.TestCase):
    def test_zero_timeout_stays_unlimited_on_patched_gunicorn(self):
        from tongjianyun.meal_sse_worker import SSEThreadWorker, ThreadWorker
        worker = object.__new__(SSEThreadWorker)
        worker.cfg = SimpleNamespace(timeout=0)
        future = SimpleNamespace(_request_timeout=0)
        with patch.object(ThreadWorker, '_wrap_future', create=True):
            worker._wrap_future(future, None)
        self.assertEqual(future._request_timeout, float('inf'))

    def test_progress_excludes_private_reasoning_and_raw_tool_output(self):
        self.assertIsNone(progress_event({'type': 'item.completed', 'item': {'type': 'reasoning', 'text': 'private'}}))
        event = progress_event({'type': 'item.completed', 'item': {
            'id': 'tool1', 'type': 'command_execution', 'command': 'python read.xlsx',
            'aggregated_output': 'private contents', 'exit_code': 0}})
        self.assertEqual(event, {'kind': 'progress', 'item_id': 'tool1', 'text': '读取食谱文件', 'status': 'completed'})
        event = progress_event({'type': 'item.completed', 'item': {
            'id': 'answer', 'type': 'agent_message', 'text': 'secret sk-abcdefghijklmnop'}})
        self.assertNotIn('sk-', event['text'])

    def test_process_yields_before_completion_and_drains_stderr(self):
        code = "import json,time,sys; print(json.dumps({'type':'turn.started'}),flush=True); sys.stderr.write('x'*100000); sys.stderr.flush(); time.sleep(.3); print(json.dumps({'type':'turn.completed'}),flush=True)"
        stream = process_events([sys.executable, '-u', '-c', code], '', '.', lambda: False, lambda: None, .01)
        started = time.monotonic()
        self.assertEqual(next(stream)['type'], 'turn.started')
        self.assertLess(time.monotonic() - started, .3)
        remaining = list(stream)
        self.assertGreaterEqual(time.monotonic() - started, .3)
        self.assertEqual(remaining[-1], {'type': 'process.exited', 'code': 0, 'cancelled': False})

    def test_explicit_cancellation_stops_child(self):
        code = "import json,time; print(json.dumps({'type':'turn.started'}),flush=True); time.sleep(60)"
        cancel = [False]
        stream = process_events([sys.executable, '-u', '-c', code], '', '.', lambda: cancel[0], lambda: None, .01)
        self.assertEqual(next(stream)['type'], 'turn.started')
        cancel[0] = True
        self.assertTrue(list(stream)[-1]['cancelled'])

    def test_submission_is_queued_without_execution_timeout(self):
        store = MagicMock()
        store.read.return_value = {}
        store.redis.get.return_value = None
        with patch.object(meal_chat, 'require_chat_access'), \
             patch.object(meal_chat, 'TaskStore', return_value=store), \
             patch.object(meal_chat, 'business_day', return_value='2026-09-25'), \
             patch.object(meal_chat, 'meal_key', return_value='lunch'), \
             patch.object(meal_chat.frappe, 'session', SimpleNamespace(user='Administrator')), \
             patch.object(meal_chat.frappe, 'enqueue') as enqueue:
            result = meal_chat.send_message('查看食谱', '2026-09-25', 'lunch', request_id=TASK, stream=1)
        self.assertEqual(result['task_id'], TASK)
        self.assertEqual(enqueue.call_args.kwargs['timeout'], -1)
        self.assertEqual(enqueue.call_args.kwargs['queue'], 'meal_chat')

    def test_repeated_request_does_not_start_second_task(self):
        store = MagicMock()
        store.read.return_value = {'owner': 'Administrator'}
        with patch.object(meal_chat, 'require_chat_access'), \
             patch.object(meal_chat, 'TaskStore', return_value=store), \
             patch.object(meal_chat, 'business_day', return_value='2026-09-25'), \
             patch.object(meal_chat, 'meal_key', return_value='lunch'), \
             patch.object(meal_chat.frappe, 'session', SimpleNamespace(user='Administrator')), \
             patch.object(meal_chat.frappe, 'enqueue') as enqueue:
            meal_chat.send_message('查看食谱', '2026-09-25', 'lunch', request_id=TASK, stream=1)
        enqueue.assert_not_called()

    def test_other_users_cannot_read_task(self):
        store = MagicMock()
        store.read.return_value = {'owner': 'someone-else'}
        with patch.object(meal_chat.frappe, 'session', SimpleNamespace(user='Administrator')):
            with self.assertRaises(meal_chat.frappe.PermissionError):
                meal_chat._owned_task(store, TASK)

    def test_sse_replays_from_cursor_then_heartbeat_without_reexecution(self):
        store = MagicMock()
        store.key.return_value = 'task'
        store.read.return_value = {'status': 'running', 'heartbeat': str(time.time())}
        store.redis.xread.side_effect = [[], [(b'task:events', [
            (b'12-0', {b'data': json.dumps({'kind': 'message', 'text': '阶段输出'}).encode()}),
            (b'13-0', {b'data': json.dumps({'kind': 'terminal', 'status': 'completed'}).encode()}),
        ])]]
        stream = meal_chat._event_stream(store, TASK, '11-0')
        self.assertIn('connected', next(stream))
        self.assertIn('heartbeat', next(stream))
        self.assertIn('id: 12-0', next(stream))
        self.assertIn('terminal', next(stream))
        self.assertEqual(list(stream), [])
        self.assertEqual(store.redis.xread.call_args_list[0].args[0], {'task:events': '11-0'})

    def test_sse_data_cannot_inject_extra_frames(self):
        frame = sse_frame('12-0', {'text': 'hello\n\nevent: malicious'})
        self.assertEqual(frame.count('\nevent:'), 1)
        self.assertEqual(frame.count('\ndata:'), 1)

    def test_oversized_messages_rejected_before_enqueue(self):
        with patch.object(meal_chat, 'require_chat_access'), \
             patch.object(meal_chat.frappe, 'throw', side_effect=ValueError), \
             patch.object(meal_chat.frappe, 'enqueue') as enqueue:
            with self.assertRaises(ValueError):
                meal_chat.send_message('x' * 2001, stream=1)
            enqueue.assert_not_called()


def start_stream_probe(seconds=130):
    """Bench-only integration probe: no model calls or business writes."""
    import uuid
    import frappe
    frappe.set_user('Administrator')
    task_id = str(uuid.uuid4())
    store = meal_chat.TaskStore()
    user_key = store.user_key('Administrator')
    active = meal_chat._str(store.redis.get(user_key + ':active'))
    if active and store.read(active).get('status') in meal_chat.ACTIVE:
        raise RuntimeError('An administrator task is already active; do not interrupt it.')
    store.update(task_id, owner='Administrator', status='queued', message='SSE 长连接验证（不修改业务数据）',
                 file_name='', day='2026-09-25', meal='lunch', heartbeat=time.time(), cancel_requested='0')
    store.redis.lpush(user_key + ':history', task_id)
    store.redis.set(user_key + ':active', task_id, ex=meal_chat.RETENTION)
    frappe.enqueue('tongjianyun.tests.test_meal_chat.run_stream_probe', queue='meal_chat', timeout=-1,
                   job_id=f'meal-chat-{task_id}', task_id=task_id, seconds=int(seconds))
    return task_id


def run_stream_probe(task_id, seconds=130):
    code = f'''import json,time
def emit(v): print(json.dumps(v,ensure_ascii=False),flush=True)
emit({{"type":"item.completed","item":{{"type":"agent_message","id":"probe1","text":"连接测试已开始，后台任务会持续超过原来的 100 秒限制。"}}}})
emit({{"type":"item.started","item":{{"type":"command_execution","id":"probe2","command":"readonly connectivity probe"}}}})
time.sleep({min(max(int(seconds), 1), 180)})
emit({{"type":"item.completed","item":{{"type":"command_execution","id":"probe2","exit_code":0}}}})
emit({{"type":"item.completed","item":{{"type":"agent_message","id":"probe3","text":"长连接测试完成，期间没有修改业务数据。"}}}})
emit({{"type":"turn.completed"}})
'''
    with patch.object(meal_chat, '_command', return_value=[sys.executable, '-u', '-c', code]):
        meal_chat.run_task(task_id, '')


def verify_http_stream():
    """Temporary authenticated public HTTPS probe, including reconnect and heartbeats."""
    import frappe
    import requests
    from werkzeug.wrappers import Request
    from frappe.sessions import Session, delete_session
    frappe.local.form_dict = frappe._dict()
    frappe.local.request = Request.from_values('/')
    frappe.local.request_ip = '127.0.0.1'
    session = Session(user='Administrator', full_name='SSE verification', user_type='System User')
    try:
        task_id = start_stream_probe(130)
        address = 'https://child.myyr.top/api/method/tongjianyun.meal_chat.stream_events'
        cookies = {'sid': session.sid}
        started = time.monotonic()
        cursor = '0-0'
        heartbeats = 0
        finished = False
        # Close a live stream on purpose, then replay only subsequent events.
        with requests.get(address, params={'task_id': task_id}, cookies=cookies,
                          stream=True, timeout=(10, 20)) as response:
            response.raise_for_status()
            assert response.headers['Content-Type'].startswith('text/event-stream')
            for line in response.iter_lines(chunk_size=1, decode_unicode=True):
                if line.startswith('id: '):
                    cursor = line[4:]
                    print('First SSE event in', round(time.monotonic() - started, 2), 'seconds; reconnecting.', flush=True)
                    break
        with requests.get(address, params={'task_id': task_id}, cookies=cookies,
                          headers={'Last-Event-ID': cursor}, stream=True, timeout=(10, 20)) as response:
            response.raise_for_status()
            for line in response.iter_lines(chunk_size=1, decode_unicode=True):
                if line.startswith(': heartbeat'):
                    heartbeats += 1
                if line.startswith('id: '):
                    assert tuple(map(int, line[4:].split('-'))) > tuple(map(int, cursor.split('-')))
                    cursor = line[4:]
                if line.startswith('data: '):
                    event = json.loads(line[6:])
                    print(round(time.monotonic() - started, 2), event.get('kind'), event.get('status', ''), flush=True)
                    if event.get('kind') == 'terminal':
                        assert event['status'] == 'completed'
                        finished = True
                        break
        elapsed = time.monotonic() - started
        assert finished and elapsed >= 125 and heartbeats >= 10
        return {'task_id': task_id, 'seconds': round(elapsed, 2), 'heartbeats': heartbeats,
                'reconnect': True, 'completed': finished}
    finally:
        delete_session(sid=session.sid, user='Administrator', reason='SSE verification finished')
