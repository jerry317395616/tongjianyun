"""Trusted transport tests: no framework connection, external model or money."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import stat
import sys
import tempfile
import threading
import time
import unittest
from contextlib import closing
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

from tongjianyun.business_agent_transport import (
    DurableWriteLedger, MODEL, TaskProxy, model_payload, strict_json,
)


@dataclass
class Receipt:
    status: str
    result: dict | None = None
    replayed: bool = False


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name).resolve()
        if os.name == 'posix':
            self.directory.chmod(0o700)
        self.identity = {'site': 'qa.localhost', 'owner': 'teacher', 'task_id': 'task-one', 'mode': 'business'}
        self.binding = SimpleNamespace(**self.identity)
        self.commits, self.rollbacks, self.operations = [], [], []
        self.active = True
        self.ledger = self.make_ledger()
        self.digest = hashlib.sha256(b'canonical operation with revision').hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def validate(self, _):
        if not self.active:
            raise PermissionError('Task stopped')

    def make_ledger(self, **kwargs):
        return DurableWriteLedger(self.directory, self.identity, validate=self.validate,
                                  commit=kwargs.get('commit', lambda: self.commits.append(True)),
                                  rollback=lambda: self.rollbacks.append(True), outcome=Receipt)

    def operation(self):
        self.operations.append(True)
        return {'readback': {'count': 1}, 'transaction': 'pending_commit'}

    def test_commit_precedes_receipt_and_replay_does_not_write(self):
        first = self.ledger(self.binding, 'call-one', self.digest, self.operation)
        self.assertEqual(first.status, 'committed')
        again = self.ledger(self.binding, 'call-one', self.digest, self.operation)
        self.assertEqual(again.result, first.result)
        self.assertTrue(again.replayed)
        self.assertEqual(len(self.operations), 1)
        self.assertEqual(len(self.commits), 1)

    def test_new_call_id_same_digest_also_deduplicates(self):
        self.ledger(self.binding, 'call-one', self.digest, self.operation)
        again = self.ledger(self.binding, 'call-two', self.digest, self.operation)
        self.assertTrue(again.replayed)
        self.assertEqual(len(self.operations), 1)
        with self.assertRaises(ValueError):
            self.ledger(self.binding, 'call-two', 'f' * 64, self.operation)

    def test_reusing_id_for_other_payload_fails(self):
        self.ledger(self.binding, 'call-one', self.digest, self.operation)
        with self.assertRaises(ValueError):
            self.ledger(self.binding, 'call-one', 'f' * 64, self.operation)

    def test_new_revision_has_new_digest_and_can_write(self):
        self.ledger(self.binding, 'call-one', self.digest, self.operation)
        result = self.ledger(self.binding, 'call-two', 'f' * 64, self.operation)
        self.assertFalse(result.replayed)
        self.assertEqual(len(self.operations), 2)

    def test_intent_survives_reopen_and_is_never_retried(self):
        with closing(sqlite3.connect(self.ledger.path)) as db:
            with db:
                db.execute('INSERT INTO writes VALUES (?, ?, ?, NULL)', ('call-one', self.digest, 'intent'))
        result = self.make_ledger()(self.binding, 'call-two', self.digest, self.operation)
        self.assertEqual(result.status, 'uncertain')
        self.assertTrue(result.replayed)
        self.assertEqual(self.operations, [])

    def test_commit_failure_leaves_uncertainty_not_false_success(self):
        def unknown_commit():
            raise OSError('Connection lost during COMMIT')
        ledger = self.make_ledger(commit=unknown_commit)
        self.assertEqual(ledger(self.binding, 'call-one', self.digest, self.operation).status, 'uncertain')
        result = self.make_ledger()(self.binding, 'call-one', self.digest, self.operation)
        self.assertEqual(result.status, 'uncertain')
        self.assertEqual(len(self.operations), 1)
        self.assertEqual(self.rollbacks, [True])

    def test_cancellation_before_commit_rolls_back(self):
        def cancel_during_operation():
            self.active = False
            return self.operation()
        with self.assertRaises(PermissionError):
            self.ledger(self.binding, 'call-one', self.digest, cancel_during_operation)
        self.assertEqual(self.commits, [])
        self.assertEqual(self.rollbacks, [True])

    def test_replayed_receipt_still_requires_current_authority(self):
        self.ledger(self.binding, 'call-one', self.digest, self.operation)
        self.active = False
        with self.assertRaises(PermissionError):
            self.ledger(self.binding, 'call-one', self.digest, self.operation)

    def test_wrong_binding_or_ledger_identity_fails(self):
        with self.assertRaises(PermissionError):
            self.ledger(SimpleNamespace(**{**self.identity, 'owner': 'other'}), 'call-one', self.digest, self.operation)
        with self.assertRaises(ValueError):
            DurableWriteLedger(self.directory, {**self.identity, 'owner': 'other'},
                               validate=self.validate, commit=lambda: None, rollback=lambda: None, outcome=Receipt)

    def test_parallel_duplicate_executes_once(self):
        outcomes = []
        threads = [threading.Thread(target=lambda: outcomes.append(
            self.ledger(self.binding, 'call-one', self.digest, self.operation))) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(outcomes), 5)
        self.assertEqual(len(self.operations), 1)
        self.assertEqual(sum(not result.replayed for result in outcomes), 1)

    def test_malformed_call_id_and_nonfinite_results_are_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger(self.binding, '../bad', self.digest, self.operation)
        with self.assertRaises(ValueError):
            self.ledger(self.binding, 'call-one', self.digest, lambda: {'bad': float('nan')})
        self.assertEqual(self.commits, [])


class ModelPayloadTests(unittest.TestCase):
    def valid(self, **extra):
        return {'model': MODEL, 'stream': True, 'input': [], 'tools': [{'type': 'function', 'name': 'local'}], **extra}

    def test_storage_disabled_and_only_fixed_model(self):
        self.assertFalse(json.loads(model_payload(self.valid(store=True)))['store'])
        for bad in [self.valid(model='other'), self.valid(stream=False), self.valid(previous_response_id='foreign'),
                    self.valid(background=True), self.valid(max_output_tokens=1000000)]:
            with self.assertRaises(ValueError):
                model_payload(bad)

    def test_external_tools_and_file_fetches_blocked(self):
        for kind in ['web_search', 'mcp', 'code_interpreter', 'computer']:
            with self.assertRaises(ValueError):
                model_payload(self.valid(tools=[{'type': kind}]))
        for kind in ['input_image', 'input_file', 'computer_screenshot']:
            with self.assertRaises(ValueError):
                model_payload(self.valid(input=[{'content': [{'type': kind, 'file_url': 'http://localhost'}]}]))

    def test_hosted_conversation_prompt_and_item_references_are_rejected(self):
        for key, value in [('conversation', 'conv_other'), ('conversation', {'id': 'conv_other'}),
                           ('prompt', {'id': 'pmpt_other', 'version': '1'}),
                           ('previous_response_id', ''), ('conversation', {}), ('prompt', {})]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                model_payload(self.valid(**{key: value}))
        for input_value in [[{'type': 'item_reference', 'id': 'msg_other'}],
                            [{'content': [{'type': 'item_reference', 'id': 'msg_other'}]}]]:
            with self.assertRaises(ValueError):
                model_payload(self.valid(input=input_value))
        # A complete inline history is self-contained, unlike a hosted ID lookup.
        inline = [{'role': 'user', 'content': [{'type': 'input_text', 'text': 'How many students?'}]}]
        self.assertEqual(json.loads(model_payload(self.valid(input=inline)))['input'], inline)

    def test_strict_json_rejects_duplicate_and_nonfinite(self):
        for value in [b'{"actor":1,"actor":2}', b'{"n":NaN}', b'{"n":Infinity}']:
            with self.assertRaises(ValueError):
                strict_json(value)


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__('localhost', timeout=3)
        self.path = str(path)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(3)
        self.sock.connect(self.path)


class FakeSocket:
    def settimeout(self, _):
        pass

    def shutdown(self, _):
        pass


class FakeUpstream:
    def __init__(self, status=200, content_type='text/event-stream'):
        self.status, self.content_type = status, content_type
        self.sock = None
        self.requests = []
        self.chunks = [b'data: {"type":"response.completed"}\n\n', b'']
        self.closed = False

    def connect(self):
        self.sock = FakeSocket()

    def request(self, *args, **kwargs):
        self.requests.append((args, kwargs))

    def getresponse(self):
        return self

    def getheader(self, *_):
        return self.content_type

    def read1(self, _):
        return self.chunks.pop(0)

    def close(self):
        self.closed = True


@unittest.skipUnless(os.name == 'posix', 'Unix HTTP acceptance runs on the target Linux host')
class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tgy-proxy-')
        self.directory = Path(self.temp.name).resolve()
        self.directory.chmod(0o700)
        self.token = secrets.token_urlsafe(32)
        self.active = True
        self.calls = []
        self.proxy = TaskProxy(self.directory, self.token, authorize=lambda: self.active,
                               tool_handler=self.tool).start()

    def tearDown(self):
        self.proxy.close()
        self.temp.cleanup()

    def tool(self, tool, arguments, call_id):
        self.calls.append((tool, arguments, call_id))
        return {'count': 2}

    def request(self, path='/tools/call', payload=None, token=None, method='POST'):
        client = UnixConnection(self.proxy.path)
        if payload is None:
            payload = {'tool': 'scene_bootstrap', 'arguments': {}, 'call_id': 'call-one'}
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        client.request(method, path, body, {'Authorization': 'Bearer ' + (token or self.token),
                                          'Content-Type': 'application/json'})
        response = client.getresponse()
        status, data = response.status, response.read()
        client.close()
        return status, data

    def test_authenticated_exact_tool_reaches_handler(self):
        status, data = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data), {'result': {'count': 2}})
        self.assertEqual(len(self.calls), 1)

    def test_foreign_bearer_and_cancelled_task_rejected(self):
        self.assertEqual(self.request(token=secrets.token_urlsafe(32))[0], 403)
        self.active = False
        self.assertEqual(self.request()[0], 403)
        self.assertEqual(self.calls, [])

    def test_no_generic_proxy_or_alternate_path(self):
        for path in ['http://example.com/tools/call', '/tools/call?actor=Administrator', '/tools%2Fcall', '/v1/models']:
            self.assertEqual(self.request(path)[0], 404)
        # Unsupported methods are rejected at headers; sending a JSON body can
        # race the deliberate connection close and obscure the actual 501.
        self.assertEqual(self.request(method='CONNECT', payload=b'')[0], 501)
        self.assertEqual(self.request(method='GET', payload=b'')[0], 501)
        self.assertEqual(self.calls, [])

    def test_envelope_identity_injection_and_duplicates_rejected(self):
        self.assertEqual(self.request(payload={'tool': 'read', 'arguments': {}, 'call_id': 'x', 'actor': 'Administrator'})[0], 400)
        self.assertEqual(self.request(payload=b'{"tool":"read","tool":"write","arguments":{},"call_id":"x"}')[0], 400)
        self.assertEqual(self.calls, [])

    def test_ambiguous_http_framing_rejected(self):
        for framing in ['Content-Length: 2\r\nContent-Length: 2', 'Content-Length: 2\r\nTransfer-Encoding: chunked']:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect(str(self.proxy.path))
            request = ('POST /tools/call HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer ' + self.token
                       + '\r\nContent-Type: application/json\r\n' + framing + '\r\n\r\n{}')
            sock.sendall(request.encode())
            self.assertIn(b'400', sock.recv(1024).split(b'\r\n')[0])
            sock.close()
        self.assertEqual(self.calls, [])

    def test_existing_socket_is_not_replaced(self):
        with self.assertRaises(ValueError):
            TaskProxy(self.directory, self.token, authorize=lambda: True, tool_handler=self.tool)

    @unittest.skipUnless(sys.platform == 'linux', 'Requires Linux procfs descriptor paths')
    def test_long_socket_path_binds_and_serves_without_chdir(self):
        directory = self.directory
        for index in range(4):
            directory = directory / (str(index) + '-private-task-directory-' + 'x' * 36)
            directory.mkdir(mode=0o700)
        canonical = directory / 'proxy.sock'
        self.assertGreater(len(os.fsencode(canonical)), 108)
        working_directory = Path.cwd()
        proxy = TaskProxy(directory, self.token, authorize=lambda: True, tool_handler=self.tool).start()
        try:
            self.assertEqual(proxy.path, canonical)
            self.assertEqual(Path.cwd(), working_directory)
            self.assertTrue(canonical.is_socket())
            self.assertEqual(stat.S_IMODE(canonical.stat().st_mode), 0o600)
            self.assertLess(len(os.fsencode(proxy.server.server_address)), 108)
            client = UnixConnection(proxy.server.server_address)
            try:
                client.request('POST', '/tools/call',
                               json.dumps({'tool': 'scene_bootstrap', 'arguments': {}, 'call_id': 'long-path'}),
                               {'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
                response = client.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read()), {'result': {'count': 2}})
            finally:
                client.close()
        finally:
            descriptor = proxy._directory_fd
            proxy.close()
        self.assertFalse(canonical.exists())
        with self.assertRaises(OSError):
            os.fstat(descriptor)
        proxy.close()  # idempotent: no reused descriptor or replacement is touched

    @unittest.skipUnless(sys.platform == 'linux', 'Requires Linux descriptor-relative cleanup')
    def test_renamed_parent_cleanup_does_not_touch_replacement_directory(self):
        original, moved = self.directory / 'task', self.directory / 'original-task'
        original.mkdir(mode=0o700)
        proxy = TaskProxy(original, self.token, authorize=lambda: True, tool_handler=self.tool).start()
        replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            original.rename(moved)
            original.mkdir(mode=0o700)
            replacement.bind(str(original / 'proxy.sock'))
            replacement_info = (original / 'proxy.sock').stat()
            self.assertTrue((moved / 'proxy.sock').is_socket())
            proxy.close()
            self.assertFalse((moved / 'proxy.sock').exists())
            self.assertEqual((original / 'proxy.sock').stat().st_ino, replacement_info.st_ino)
            self.assertTrue((original / 'proxy.sock').is_socket())
        finally:
            proxy.close()
            replacement.close()

    @unittest.skipUnless(sys.platform == 'linux', 'Requires Linux pinned socket inode')
    def test_replaced_socket_inode_is_never_unlinked_by_close(self):
        original_inode = self.proxy.path.stat().st_ino
        self.proxy.path.unlink()
        replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            replacement.bind(str(self.proxy.path))
            replacement_info = self.proxy.path.stat()
            self.assertNotEqual(replacement_info.st_ino, original_inode)
            self.proxy.close()
            self.assertEqual(self.proxy.path.stat().st_ino, replacement_info.st_ino)
            self.assertTrue(self.proxy.path.is_socket())
        finally:
            replacement.close()

    @unittest.skipUnless(sys.platform == 'linux', 'Requires Linux descriptor lifecycle')
    def test_failed_activation_cleans_created_inode_and_descriptors(self):
        directory = self.directory / 'failed-start'
        directory.mkdir(mode=0o700)
        descriptors_before = set(os.listdir('/proc/self/fd'))
        with patch('tongjianyun.business_agent_transport._Server.server_activate',
                   side_effect=RuntimeError('test activation failure')):
            with self.assertRaises(RuntimeError):
                TaskProxy(directory, self.token, authorize=lambda: True, tool_handler=self.tool)
        self.assertFalse((directory / 'proxy.sock').exists())
        self.assertEqual(set(os.listdir('/proc/self/fd')), descriptors_before)

    @unittest.skipUnless(sys.platform == 'linux', 'Requires Linux descriptor lifecycle')
    def test_existing_socket_rejection_closes_directory_descriptor(self):
        descriptors_before = set(os.listdir('/proc/self/fd'))
        with self.assertRaises(ValueError):
            TaskProxy(self.directory, self.token, authorize=lambda: True, tool_handler=self.tool)
        self.assertEqual(set(os.listdir('/proc/self/fd')), descriptors_before)

    def test_model_not_configured_and_wrong_model_fail_closed(self):
        payload = {'model': MODEL, 'stream': True, 'input': []}
        self.assertEqual(self.request('/v1/responses', payload)[0], 503)
        self.assertEqual(self.request('/v1/responses', {**payload, 'model': 'other'})[0], 400)

    def test_framework_exception_does_not_expose_secrets_or_paths(self):
        def failing(*_):
            raise RuntimeError('secret /home/zyd/site_config.json sk-private-key')
        self.proxy.tool_handler = failing
        status, data = self.request()
        self.assertEqual(status, 502)
        self.assertNotIn(b'secret', data)
        self.assertNotIn(b'/home/', data)

    def test_revocation_during_tool_does_not_deliver_result(self):
        def revoke(*_):
            self.active = False
            return {'private': 'content'}
        self.proxy.tool_handler = revoke
        status, data = self.request()
        self.assertEqual(status, 403)
        self.assertNotIn(b'private', data)

    def test_model_stream_fixed_destination_and_secret_kept_outside(self):
        upstream = FakeUpstream()
        self.proxy.connection_factory = lambda: upstream
        self.proxy.model_key = lambda: 'test-upstream-secret'
        status, body = self.request('/v1/responses', {'model': MODEL, 'stream': True, 'input': []})
        self.assertEqual(status, 200)
        self.assertIn(b'response.completed', body)
        self.assertNotIn(b'test-upstream-secret', body)
        self.assertEqual(upstream.requests[0][0], ('POST', '/v1/responses'))
        headers = upstream.requests[0][1]['headers']
        self.assertEqual(headers['Authorization'], 'Bearer test-upstream-secret')
        self.assertNotIn(self.token, str(headers))
        self.assertTrue(upstream.closed)

    def test_upstream_redirect_error_and_non_sse_are_not_forwarded(self):
        for upstream in [FakeUpstream(302), FakeUpstream(401), FakeUpstream(200, 'text/html')]:
            self.proxy.connection_factory = lambda: upstream
            self.proxy.model_key = lambda: 'test-upstream-secret'
            status, body = self.request('/v1/responses', {'model': MODEL, 'stream': True, 'input': []})
            self.assertEqual(status, 502)
            self.assertNotIn(b'test-upstream-secret', body)
            self.assertEqual(len(upstream.requests), 1)

    def test_model_resource_limit_is_not_an_execution_deadline(self):
        self.proxy.max_model_calls = 1
        self.proxy.connection_factory = FakeUpstream
        self.proxy.model_key = lambda: 'test-upstream-secret'
        payload = {'model': MODEL, 'stream': True, 'input': []}
        self.assertEqual(self.request('/v1/responses', payload)[0], 200)
        self.assertEqual(self.request('/v1/responses', payload)[0], 429)

    def test_quiet_connection_close_stream_is_interruptible(self):
        left, right = socket.socketpair()
        connected = threading.Event()
        upstream = http.client.HTTPConnection('unused', timeout=3)
        upstream.sock = left
        def serve_quiet_stream():
            right.recv(65536)
            right.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n')
            connected.set()
        peer = threading.Thread(target=serve_quiet_stream)
        peer.start()
        self.proxy.connection_factory = lambda: upstream
        self.proxy.model_key = lambda: 'test-upstream-secret'
        results = []
        reader = threading.Thread(target=lambda: results.append(self.request('/v1/responses',
            {'model': MODEL, 'stream': True, 'input': []})))
        reader.start()
        try:
            self.assertTrue(connected.wait(2))
            deadline = time.monotonic() + 2
            while upstream.sock is not None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertIsNone(upstream.sock)
            self.proxy.close()
            reader.join(timeout=2)
            self.assertFalse(reader.is_alive(), 'quiet SSE remained blocked after explicit cancellation')
            self.assertEqual(results[0][0], 200)
        finally:
            right.close()
            left.close()
            peer.join(timeout=2)

    def test_credential_mount_requires_system_identity(self):
        if os.geteuid() == 0:
            self.skipTest('Runs with the ordinary QA operator')
        with self.assertRaises(PermissionError):
            TaskProxy(self.directory, self.token, authorize=lambda: True, tool_handler=self.tool,
                      credential_mount=True)


if __name__ == '__main__':
    unittest.main()
