"""The shared launcher never promotes a request-selected identity or destination."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from tongjianyun import harness_shared_login as mod


class SharedLoginTests(unittest.TestCase):
    def setUp(self):
        self.fake = SimpleNamespace(
            session=SimpleNamespace(user="teacher@example.invalid"),
            conf={"tongjianyun_shared_harness_enabled": 1,
                  "tongjianyun_shared_harness_users": ["teacher@example.invalid"]},
            local=SimpleNamespace(site="child.myyr.top", response={}, response_headers=Mock()),
            db=SimpleNamespace(get_value=Mock(return_value=SimpleNamespace(enabled=1, user_type="System User"))),
            PermissionError=PermissionError, throw=Mock(side_effect=PermissionError("not admitted")),
        )
        self.launcher = Mock(side_effect=lambda: self.fake.local.response.update({
            "type": "redirect", "location": "https://harness.myyr.top/sso?token=synthetic-handoff",
        }))
        self.context = patch.object(mod, "frappe", self.fake)
        self.context.start()
        self.addCleanup(self.context.stop)
        self.core = patch.object(mod.harness_auth, "launch", self.launcher)
        self.core.start()
        self.addCleanup(self.core.stop)

    def call(self):
        # Frappe's argument validator wraps whitelisted methods; this suite
        # checks the business function independently of request construction.
        return mod.launch.__wrapped__() if hasattr(mod.launch, "__wrapped__") else mod.launch()

    def test_guest_returns_to_this_entry_after_login(self):
        self.fake.session.user = "Guest"
        self.call()
        target = urlsplit(self.fake.local.response["location"])
        self.assertEqual(target.path, "/login")
        self.assertEqual(parse_qs(target.query), {"redirect-to": [mod.LAUNCH_PATH]})
        self.launcher.assert_not_called()
        self.fake.db.get_value.assert_not_called()

    def test_admitted_user_uses_employee_exchange_and_no_cache(self):
        self.call()
        self.assertEqual(self.fake.local.response["location"],
                         "https://harness.myyr.top/employee/sso?token=synthetic-handoff")
        self.fake.db.get_value.assert_called_once_with(
            "User", "teacher@example.invalid", ["enabled", "user_type"], as_dict=True)
        self.fake.local.response_headers.set.assert_any_call("Referrer-Policy", "no-referrer")
        self.fake.local.response_headers.set.assert_any_call("Cache-Control", "no-store")

    def test_missing_or_malformed_enablement_is_denied(self):
        for value in [None, 0, "1", "false", 2]:
            with self.subTest(value=value):
                self.fake.conf["tongjianyun_shared_harness_enabled"] = value
                with self.assertRaises(PermissionError):
                    self.call()
        self.launcher.assert_not_called()

    def test_unknown_or_malformed_allowlist_is_denied(self):
        for users in [None, [], "teacher@example.invalid", ["other"], [1], [" a"], ["a", "a"]]:
            with self.subTest(users=users):
                self.fake.conf["tongjianyun_shared_harness_users"] = users
                with self.assertRaises(PermissionError):
                    self.call()
        self.launcher.assert_not_called()

    def test_administrator_has_no_employee_fallback(self):
        self.fake.session.user = "Administrator"
        self.fake.conf["tongjianyun_shared_harness_users"] = ["Administrator"]
        with self.assertRaises(PermissionError):
            self.call()
        self.launcher.assert_not_called()

    def test_other_site_cannot_issue_child_identity(self):
        self.fake.local.site = "other.example.invalid"
        with self.assertRaises(PermissionError):
            self.call()
        self.launcher.assert_not_called()

    def test_disabled_missing_and_website_users_are_denied(self):
        for user in [None, SimpleNamespace(enabled=0, user_type="System User"),
                     SimpleNamespace(enabled=1, user_type="Website User")]:
            with self.subTest(user=user):
                self.fake.db.get_value.return_value = user
                with self.assertRaises(PermissionError):
                    self.call()
        self.launcher.assert_not_called()

    def test_unexpected_core_destination_is_not_returned(self):
        self.launcher.side_effect = lambda: self.fake.local.response.update({
            "type": "redirect", "location": "https://other.example.invalid/sso?token=synthetic",
        })
        with self.assertRaises(PermissionError):
            self.call()
        self.assertNotIn("location", self.fake.local.response)


if __name__ == "__main__":
    unittest.main()
