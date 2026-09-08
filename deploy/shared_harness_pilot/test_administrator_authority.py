"""Signed administrator admission and unchanged employee authority."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock

from administrator_authority import AdministratorAuthority, Configuration


class AuthorityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 100
        self.config = Configuration(Path("/unused-test.sock"), 1000, "child.myyr.top", b"synthetic-test-key" * 3,
                                    {"teacher": None}, 300, 16, 4, 5, ("Student",), "single-user")
        self.worker = AsyncMock(side_effect=lambda op, args, timeout: {"enabled": True} if op == "check" else {"rows": []})
        self.read = AsyncMock(return_value={"rows": []})
        self.authority = AdministratorAuthority(self.config, worker=self.worker,
            enabled=AsyncMock(return_value=True), read=self.read, clock=lambda: self.now)
        self.now = 102

    async def login(self, user):
        row = {"iss": self.config.issuer, "sub": user, "iat": 101, "exp": 150,
               "jti": (user + "_synthetic_nonce_12345678")}
        enc = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
        body = enc(json.dumps(row).encode())
        signature = enc(hmac.digest(self.config.secret, body.encode(), "sha256"))
        result = await self.authority.execute({"version": 1, "operation": "login", "value": body + "." + signature})
        return result["cookie"]

    def request(self, cookie, doctype="Item"):
        return {"version": 1, "operation": "read", "value": {"credential": cookie,
            "operation": "frappe_list_documents", "arguments": {"doctype": doctype}}}

    async def test_signed_administrator_can_read_outside_employee_scope(self):
        cookie = await self.login("Administrator")
        self.assertEqual(await self.authority.execute(self.request(cookie)), {"rows": []})
        self.worker.assert_any_await("frappe_list_documents", {"doctype": "Item"}, 5)
        self.read.assert_not_awaited()

    async def test_teacher_cannot_use_administrator_scope(self):
        cookie = await self.login("teacher")
        with self.assertRaises(ValueError):
            await self.authority.execute(self.request(cookie))
        self.worker.assert_not_awaited()

    async def test_teacher_reads_still_use_original_executor(self):
        cookie = await self.login("teacher")
        await self.authority.execute(self.request(cookie, "Student"))
        self.read.assert_awaited_once()
        self.worker.assert_not_awaited()

    async def test_unknown_account_is_not_admitted(self):
        with self.assertRaises(ValueError):
            await self.login("admin")

    async def test_invalid_cookie_cannot_invoke_worker(self):
        with self.assertRaises(PermissionError):
            await self.authority.execute(self.request("x" * 43))
        self.worker.assert_not_awaited()

    async def test_request_identity_override_and_write_operation_rejected(self):
        cookie = await self.login("Administrator")
        request = self.request(cookie)
        request["value"]["arguments"]["user"] = "Administrator"
        with self.assertRaises(ValueError):
            await self.authority.execute(request)
        request = self.request(cookie)
        request["value"]["operation"] = "frappe_apply_document_update"
        with self.assertRaises(ValueError):
            await self.authority.execute(request)

    async def test_disabled_admin_loses_existing_login(self):
        cookie = await self.login("Administrator")
        self.worker.side_effect = None
        self.worker.return_value = {"enabled": False}
        with self.assertRaises(PermissionError):
            await self.authority.execute(self.request(cookie))
        self.assertEqual(self.authority.sessions, {})

    async def test_logout_while_reading_discards_result(self):
        cookie = await self.login("Administrator")
        async def worker(op, args, timeout):
            if op == "check":
                return {"enabled": True}
            await self.authority.execute({"version": 1, "operation": "logout", "value": cookie})
            return {"rows": []}
        self.worker.side_effect = worker
        with self.assertRaises(PermissionError):
            await self.authority.execute(self.request(cookie))
        self.assertEqual(self.authority.readers, set())

    async def test_duplicate_admin_read_rejected(self):
        cookie = await self.login("Administrator")
        self.authority.readers.add("Administrator")
        with self.assertRaises(ValueError):
            await self.authority.execute(self.request(cookie))

    def app_request(self, cookie, action="preview", session="session-11111111-1111-1111-1111-111111111111", args=None):
        return {"version": 1, "operation": "application", "value": {"credential": cookie,
            "sessionId": session, "action": action, "arguments": args or {}}}

    async def test_employee_cannot_preview_review_or_confirm(self):
        cookie = await self.login("teacher")
        self.assertEqual(await self.authority.execute(self.app_request(cookie, "capabilities")), {"previews": False})
        for action in ["preview", "review", "confirm"]:
            with self.assertRaises(PermissionError):
                await self.authority.execute(self.app_request(cookie, action))
        self.worker.assert_not_awaited()

    async def test_binding_is_derived_not_caller_supplied(self):
        cookie = await self.login("Administrator")
        await self.authority.execute(self.app_request(cookie))
        first = [call.args for call in self.worker.await_args_list if call.args[0] == "application"][-1][1]
        self.assertRegex(first["session_hash"], r"^[a-f0-9]{64}$")
        self.assertNotIn(cookie, json.dumps(first))
        await self.authority.execute(self.app_request(cookie, session="session-22222222-2222-2222-2222-222222222222"))
        second = [call.args for call in self.worker.await_args_list if call.args[0] == "application"][-1][1]
        self.assertNotEqual(first["session_hash"], second["session_hash"])
        request = self.app_request(cookie)
        request["value"]["session_hash"] = "a" * 64
        with self.assertRaises(ValueError):
            await self.authority.execute(request)

    async def test_logout_during_confirmation_does_not_release_result(self):
        cookie = await self.login("Administrator")
        async def worker(op, args, timeout):
            if op == "check":
                return {"enabled": True}
            await self.authority.execute({"version": 1, "operation": "logout", "value": cookie})
            return {"state": "succeeded"}
        self.worker.side_effect = worker
        with self.assertRaises(PermissionError):
            await self.authority.execute(self.app_request(cookie, "confirm"))


if __name__ == "__main__":
    unittest.main()
