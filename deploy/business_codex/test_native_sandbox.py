"""Pure construction, credential, client and relay boundary tests; no model calls."""
from __future__ import annotations

import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys
import tempfile
import threading
import unittest
from unittest import mock

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import business_tool
import native_sandbox
import sandbox_entry

TASK = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


class NativeSandboxTests(unittest.TestCase):
    def test_canonical_task_only(self):
        self.assertEqual(native_sandbox.validate_task_id(TASK), TASK)
        for bad in ("", "../x", TASK.upper(), TASK.replace("-", ""), TASK + "\n", 42, None):
            with self.subTest(bad=bad), self.assertRaises((ValueError, TypeError, AttributeError)):
                native_sandbox.validate_task_id(bad)

    def test_fixed_system_manager_and_identity(self):
        args = native_sandbox.build_systemd_command(TASK)
        self.assertEqual(args[0], "/usr/bin/systemd-run")
        for arg in ("--pipe", "--wait", "--collect", "--property=DynamicUser=yes",
                    "--property=KillMode=control-group", "--property=NoNewPrivileges=yes",
                    "--property=CapabilityBoundingSet=", "--property=PrivateNetwork=yes"):
            self.assertIn(arg, args)
        self.assertNotIn("--user", args)
        self.assertFalse(any("codex-deepseek-admin" in arg for arg in args))
        self.assertTrue(args[-3].endswith("native_sandbox.py"))

    def test_no_secret_in_argv(self):
        args = native_sandbox.build_systemd_command(TASK)
        self.assertTrue(any("LoadCredential=task-token:" in arg for arg in args))
        self.assertFalse(any("Bearer" in arg or re.search(r"sk-[A-Za-z0-9]{16,}", arg) for arg in args))

    def test_proc_protection_moved_inside_without_disabling_outer_identity(self):
        args = native_sandbox.build_systemd_command(TASK)
        self.assertEqual(native_sandbox.PROC_ISOLATION_REVISION, 'bwrap-ro-v2')
        for item in ('ProtectKernelTunables=no', 'ProtectKernelLogs=no', 'ProtectHostname=no',
                     'ProtectProc=invisible', 'DynamicUser=yes', 'NoNewPrivileges=yes',
                     'CapabilityBoundingSet=', 'PrivateNetwork=yes'):
            self.assertIn('--property=' + item, args)
        for name in ('syslog', 'sethostname', 'setdomainname'):
            self.assertIn(name, native_sandbox.DENIED_SYSCALLS)

    def test_two_tasks_have_distinct_units_credentials_and_directories(self):
        other = "ffffffff-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        self.assertNotEqual(native_sandbox.unit_name(TASK), native_sandbox.unit_name(other))
        self.assertNotEqual(native_sandbox.runtime_path(TASK), native_sandbox.runtime_path(other))
        self.assertNotEqual(native_sandbox.build_systemd_command(TASK), native_sandbox.build_systemd_command(other))

    def test_bwrap_boundaries_and_filter_are_mandatory(self):
        credentials = Path("/run/credentials") / native_sandbox.unit_name(TASK)
        args = native_sandbox.build_bwrap_command(TASK, credentials, 7)
        for option in ("--unshare-user", "--unshare-all", "--disable-userns", "--new-session",
                       "--cap-drop", "--clearenv", "--seccomp"):
            self.assertIn(option, args)
        self.assertEqual(args[args.index("--seccomp") + 1], "7")
        proc_index = args.index('--proc')
        self.assertEqual(args[proc_index:proc_index + 4], ['--proc', '/proc', '--remount-ro', '/proc'])
        self.assertNotIn("--share-net", args)
        self.assertNotIn("/usr", args)
        self.assertNotIn("/", args)
        self.assertNotIn("/home/zyd/frappe", args)
        self.assertEqual(args[-1], "/opt/business-codex/sandbox_entry.py")

    def test_rejects_credential_path_and_filter_injection(self):
        for path in (Path("/tmp"), Path("/run/credentials/other.service")):
            with self.assertRaises(ValueError):
                native_sandbox.build_bwrap_command(TASK, path, 7)
        for fd in (None, True, -1, 0, "7"):
            with self.assertRaises(ValueError):
                native_sandbox.build_bwrap_command(TASK, Path("/run/credentials") / native_sandbox.unit_name(TASK), fd)

    @unittest.skipUnless(sys.platform == "linux", "Linux identity API")
    def test_ordinary_or_root_identity_cannot_run(self):
        for uid in (0, 1000, 65534):
            with mock.patch.object(os, "geteuid", return_value=uid), self.assertRaises(PermissionError):
                native_sandbox.run_task(TASK)

    def test_codex_is_direct_ephemeral_and_not_admin_resume(self):
        args = sandbox_entry.codex_argv()
        self.assertEqual(args[0], "/opt/business-codex/codex")
        for flag in ("--no-daemon", "--json", "--ephemeral", "--skip-git-repo-check"):
            self.assertIn(flag, args)
        self.assertIn('web_search="disabled"', args)
        self.assertIn("mcp_servers={}", args)
        self.assertIn("plugins={}", args)
        self.assertNotIn("resume", args)
        self.assertNotIn("--search", args)
        self.assertFalse(any(re.search(r"sk-[A-Za-z0-9]{16,}", arg) for arg in args))

    def test_entry_refuses_host_without_seccomp(self):
        with mock.patch.object(Path, "read_text", return_value="NoNewPrivs:\t1\nSeccomp:\t0\n"), self.assertRaises(PermissionError):
            sandbox_entry.require_outer_sandbox()

    def test_runtime_rejects_symlink_owner_and_mutability(self):
        for uid, mode in ((1000, stat.S_IFREG | 0o755), (0, stat.S_IFREG | 0o775),
                          (0, stat.S_IFLNK | 0o777), (0, stat.S_IFDIR | 0o755)):
            path = mock.Mock()
            path.parents = []
            path.lstat.return_value = mock.Mock(st_uid=uid, st_mode=mode)
            with self.subTest(uid=uid, mode=mode), self.assertRaises(PermissionError):
                native_sandbox.require_root_owned_file(path)

    @unittest.skipUnless(sys.platform == "linux", "Linux seccomp API")
    def test_real_compiled_filter_is_sealed(self):
        fd = native_sandbox.export_seccomp_fd()
        try:
            self.assertGreater(os.fstat(fd).st_size, 64)
            with self.assertRaises(OSError):
                os.write(fd, b"overwrite")
        finally:
            os.close(fd)

    @unittest.skipUnless(sys.platform == "linux", "Linux seccomp API")
    def test_no_library_is_fail_closed(self):
        with mock.patch.object(native_sandbox.ctypes.util, "find_library", return_value=None), self.assertRaises(RuntimeError):
            native_sandbox.export_seccomp_fd()


class BusinessClientTests(unittest.TestCase):
    def test_exact_tool_request(self):
        value = {"tool": "get_view", "arguments": {"view": "classroom_day"}, "call_id": "abc_def_123"}
        self.assertEqual(json.loads(business_tool.validate_request(value)), value)
        for mutation in ({"actor": "Administrator"}, {"path": "/admin"}):
            with self.assertRaises(ValueError):
                business_tool.validate_request(dict(value, **mutation))

    def test_bad_tool_request_types_and_bounds(self):
        for value in (None, [], {}, {"tool": "../../", "arguments": {}, "call_id": "abcdefgh"},
                      {"tool": "get_view", "arguments": [], "call_id": "abcdefgh"},
                      {"tool": "get_view", "arguments": {}, "call_id": "x"},
                      {"tool": "get_view", "arguments": {"x": float("nan")}, "call_id": "abcdefgh"},
                      {"tool": "get_view", "arguments": {"x": "x" * 131072}, "call_id": "abcdefgh"}):
            with self.subTest(value=str(value)[:50]), self.assertRaises(ValueError):
                business_tool.validate_request(value)

    def test_credential_does_not_accept_header_injection(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "credential"
            for data in (b"x" * 32 + b"\r\nInjected: 1", b"x", b"x" * 257):
                path.write_bytes(data)
                with self.assertRaises(ValueError):
                    business_tool.read_token(path)
            path.write_bytes(b"x" * 48)
            self.assertEqual(business_tool.read_token(path), "x" * 48)

    def test_tool_error_is_not_replayed_or_echoed(self):
        connection = mock.Mock()
        connection.getresponse.return_value.status = 403
        connection.getresponse.return_value.read.return_value = b"sensitive upstream details"
        with mock.patch.object(business_tool, "UnixHTTPConnection", return_value=connection), mock.patch.object(business_tool, "read_token", return_value="x" * 48):
            with self.assertRaisesRegex(RuntimeError, "HTTP 403") as error:
                business_tool.call_tool({"tool": "get_view", "arguments": {}, "call_id": "abcdefgh"})
        self.assertNotIn("sensitive", str(error.exception))
        self.assertEqual(connection.request.call_count, 1)
        self.assertEqual(connection.request.call_args.args[:2], ("POST", "/tools/call"))
        connection.close.assert_called_once()

    def test_tool_success(self):
        connection = mock.Mock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read.return_value = b'{"ok":true}'
        with mock.patch.object(business_tool, "UnixHTTPConnection", return_value=connection), mock.patch.object(business_tool, "read_token", return_value="x" * 48):
            self.assertEqual(business_tool.call_tool({"tool": "get_view", "arguments": {}, "call_id": "abcdefgh"}), {"ok": True})
        methods = [call[0] for call in connection.mock_calls]
        self.assertLess(methods.index("connect"), methods.index("request"))
        self.assertLess(methods.index("request"), methods.index("sock.settimeout"))
        self.assertLess(methods.index("sock.settimeout"), methods.index("getresponse"))
        connection.sock.settimeout.assert_called_once_with(None)


@unittest.skipUnless(sys.platform == "linux", "HTTP relay runs inside the Linux-only native sandbox")
class RelayTests(unittest.TestCase):
    def setUp(self):
        self.token = "x" * 48
        self.client = mock.Mock()
        self.client.http.client.HTTPException = http.client.HTTPException
        # Production uses fixed 9111; tests allocate a private ephemeral port.
        original = sandbox_entry.ThreadingHTTPServer
        with mock.patch.object(sandbox_entry, "ThreadingHTTPServer", side_effect=lambda address, handler: original(("127.0.0.1", 0), handler)):
            self.server = sandbox_entry.make_relay(self.client, self.token)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, method, path, body=b"{}", headers=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def test_only_fixed_path_and_method(self):
        for method, path in (("GET", "/v1/responses"), ("CONNECT", "host:443"), ("POST", "/tools/call"),
                             ("POST", "/v1/responses?x=1"), ("POST", "http://host/v1/responses")):
            self.assertIn(self.request(method, path, body=b"")[0], (403, 405))
        self.client.UnixHTTPConnection.assert_not_called()

    def test_requires_exact_task_bearer(self):
        self.assertEqual(self.request("POST", "/v1/responses", headers={"Content-Type": "application/json"})[0], 401)
        self.assertEqual(self.request("POST", "/v1/responses", headers={"Authorization": "Bearer wrong", "Content-Type": "application/json"})[0], 401)
        self.client.UnixHTTPConnection.assert_not_called()

    def test_does_not_follow_upstream_redirect(self):
        self.client.UnixHTTPConnection.return_value.getresponse.return_value.status = 302
        status, body = self.request("POST", "/v1/responses", headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        self.assertEqual((status, body), (502, b""))
        self.assertEqual(self.client.UnixHTTPConnection.return_value.request.call_count, 1)

    def test_rejects_chunked_and_oversized_body_before_proxy(self):
        headers = {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"}
        self.assertEqual(self.request("POST", "/v1/responses", headers=dict(headers, **{"Transfer-Encoding": "chunked"}))[0], 403)
        self.assertEqual(self.request("POST", "/v1/responses", headers=dict(headers, **{"Content-Length": "8388609"}))[0], 400)
        self.client.UnixHTTPConnection.assert_not_called()

    def test_duplicate_authorization_and_length_are_rejected(self):
        for header in ("Authorization", "Content-Length"):
            connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
            connection.putrequest("POST", "/v1/responses")
            connection.putheader("Authorization", "Bearer " + self.token)
            connection.putheader("Content-Length", "2")
            connection.putheader("Content-Type", "application/json")
            connection.putheader(header, "2" if header == "Content-Length" else "Bearer " + self.token)
            connection.endheaders(b"{}")
            response = connection.getresponse()
            self.assertIn(response.status, (400, 401))
            response.read()
            connection.close()
        self.client.UnixHTTPConnection.assert_not_called()

    def test_streams_only_fixed_model_destination(self):
        response = self.client.UnixHTTPConnection.return_value.getresponse.return_value
        response.status = 200
        response.getheader.return_value = "text/event-stream"
        response.read1.side_effect = [b"data: {}\n\n", b""]
        status, body = self.request("POST", "/v1/responses", headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json", "X-Forwarded-Host": "other"})
        self.assertEqual((status, body), (200, b"data: {}\n\n"))
        call = self.client.UnixHTTPConnection.return_value.request.call_args
        self.assertEqual(call.args, ("POST", "/v1/responses"))
        self.assertNotIn("X-Forwarded-Host", call.kwargs["headers"])
        upstream = self.client.UnixHTTPConnection.return_value
        methods = [call[0] for call in upstream.mock_calls]
        self.assertLess(methods.index("connect"), methods.index("request"))
        self.assertLess(methods.index("request"), methods.index("sock.settimeout"))
        self.assertLess(methods.index("sock.settimeout"), methods.index("getresponse"))
        upstream.sock.settimeout.assert_called_once_with(None)


if __name__ == "__main__":
    unittest.main()
