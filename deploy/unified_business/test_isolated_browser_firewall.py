"""Keyless WSGI boundary tests; no sites, credentials, servers or database."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


spec = importlib.util.spec_from_file_location("qa_web", Path(__file__).with_name("serve_isolated_browser.py"))
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)


class FirewallTests(unittest.TestCase):
    def call(self, path, method="GET", query="", body=b"", content_type="application/json", host=None, site=None):
        application = Mock(return_value=[b"business application"])
        environ = {"HTTP_HOST": host or f"{web.SITE}:{web.PORT}", "PATH_INFO": path,
                   "REQUEST_METHOD": method, "QUERY_STRING": query, "CONTENT_TYPE": content_type,
                   "CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body)}
        if site:
            environ["HTTP_X_FRAPPE_SITE_NAME"] = site
        response = Mock()
        with patch.object(web, "config_guard", return_value={"unified_browser_acceptance": 1, "maintenance_mode": 0}):
            result = web.QAFirewall(application)(environ, response)
        return application, response, result, environ

    def test_agent_send_cancel_upload_and_private_runner_are_blocked(self):
        for method in ("tongjianyun.meal_chat.send_message", "tongjianyun.meal_chat.cancel_task",
                       "tongjianyun.meal_chat.run_task", "upload_file", "frappe.utils.background_jobs.enqueue"):
            with self.subTest(method=method):
                app, response, result, _ = self.call("/api/method/" + method, "POST", body=b"{}")
                app.assert_not_called()
                self.assertEqual(response.call_args.args[0], "403 Forbidden")

    def test_v2_slash_and_double_encoded_aliases_do_not_bypass(self):
        for path in ("/api/v2/method/tongjianyun/meal_chat/send_message",
                     "/api/method/tongjianyun%252emeal_chat%252esend_message"):
            with self.subTest(path=path):
                app, _, _, _ = self.call(path, "POST", body=b"{}")
                app.assert_not_called()

    def test_form_json_and_query_cmd_cannot_bypass(self):
        bad = "tongjianyun.meal_chat.send_message"
        cases = [("/", "GET", "cmd=" + bad, b"", "application/json"),
                 ("/", "GET", "", json.dumps({"cmd": bad}).encode(), "application/json"),
                 ("/", "GET", "", ("cmd=" + bad).encode(), "application/x-www-form-urlencoded"),
                 ("/", "POST", "", json.dumps({"cmd": bad}).encode(), "application/json"),
                 ("/api/method/login", "POST", "", ("cmd=" + bad).encode(), "application/x-www-form-urlencoded")]
        for path, method, query, body, content_type in cases:
            with self.subTest(path=path, method=method):
                app, _, _, _ = self.call(path, method, query, body, content_type)
                app.assert_not_called()

    def test_large_get_body_is_rejected_before_application(self):
        app, response, _, _ = self.call("/", body=b" " * (1024 * 1024 + 1))
        app.assert_not_called()
        self.assertEqual(response.call_args.args[0], "403 Forbidden")

    def test_safe_reads_reach_real_business_application(self):
        for method in web.READ_METHODS:
            with self.subTest(method=method):
                app, _, _, _ = self.call("/api/method/" + method)
                app.assert_called_once()

    def test_only_explicit_writes_reach_real_business_application_and_body_is_rewound(self):
        for method in web.WRITE_METHODS:
            with self.subTest(method=method):
                body = b'{"student_group":"QA","students":[]}'
                app, _, _, environ = self.call("/api/method/" + method, "POST", body=body)
                app.assert_called_once()
                self.assertEqual(environ["wsgi.input"].read(), body)

    def test_host_and_site_switching_are_rejected(self):
        for host, site in (("child.myyr.top", None), (None, "child.myyr.top")):
            app, response, _, _ = self.call("/login", host=host, site=site)
            app.assert_not_called()
            self.assertEqual(response.call_args.args[0], "403 Forbidden")

    def test_generic_native_resource_write_and_multipart_are_blocked(self):
        for path, content_type in (("/api/resource/Server Script", "application/json"),
                                   ("/api/method/login", "multipart/form-data")):
            app, _, _, _ = self.call(path, "POST", body=b"{}", content_type=content_type)
            app.assert_not_called()

    def test_health_has_no_secret_and_does_not_connect_to_application(self):
        app, response, result, _ = self.call("/__qa__/health")
        app.assert_not_called()
        self.assertEqual(response.call_args.args[0], "200 OK")
        self.assertEqual(set(json.loads(result[0])), {"site", "port", "loopback_only", "codex_execution_blocked"})


class AssetEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        values = {"ROOT": root, "SITES": root / "sites", "SOURCE": root / "candidate",
                  "BENCH": root / "bench", "ASSETS": root / "sites/assets",
                  "STATE": root / "fixture.json", "CREDENTIALS": root / "credentials.json",
                  "ASSET_MARKER": root / "asset-evidence.json", "APPS": ("tongjianyun",)}
        for key, value in values.items():
            patcher = patch.object(web, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        guard = patch.object(web, "config_guard", return_value={})
        guard.start()
        self.addCleanup(guard.stop)
        public = web.SOURCE / "tongjianyun/public"
        for filename in web.CRITICAL_ASSETS:
            path = public / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture " + filename)
        (public / "meal_scene/views.js").write_text(";".join(web.REQUIRED_RENDERERS))
        (public / "meal_scene/chat.js").write_text("import './views.js?v=fixture-1';")
        template = web.SOURCE / "tongjianyun/www/tongjianyun-meal-scene.html"
        template.parent.mkdir(parents=True)
        template.write_text('<script src="/assets/tongjianyun/meal_scene/chat.js?v=fixture-1"></script>')
        (web.BENCH / "sites/assets").mkdir(parents=True)
        for name in ("assets.json", "assets-rtl.json"):
            (web.BENCH / "sites/assets" / name).write_text('{}')
        (web.SITES / web.SITE).mkdir(parents=True)
        for path in (web.STATE, web.CREDENTIALS, web.SITES / web.SITE / "site_config.json",
                     web.SITES / "common_site_config.json"):
            path.write_text('{"synthetic":true}')

    def test_asset_refresh_is_versioned_without_database_or_fixture_work(self):
        with patch.object(web, "connect") as connect, patch.object(web, "prepare_fixture") as fixtures, \
             patch.object(web, "enable_isolated_web") as config:
            result = web.refresh_assets()
        connect.assert_not_called()
        fixtures.assert_not_called()
        config.assert_not_called()
        self.assertTrue(result["asset_only"])
        self.assertTrue(result["fixtures_and_credentials_unchanged"])
        self.assertEqual(result["assets"]["files_verified"], len(web.CRITICAL_ASSETS))
        self.assertEqual(result["assets"]["chat_views_import"], ["./views.js?v=fixture-1"])
        self.assertEqual(set(result["assets"]["critical_sha256"]), set(web.CRITICAL_ASSETS))

    def test_stale_candidate_without_required_components_is_rejected(self):
        (web.SOURCE / "tongjianyun/public/meal_scene/views.js").write_text("old renderer")
        with self.assertRaises(AssertionError):
            web.refresh_assets()
        self.assertFalse(web.ASSETS.exists())

    def test_changed_source_or_copy_is_rejected_until_refreshed(self):
        web.refresh_assets()
        source = web.SOURCE / "tongjianyun/public/meal_scene/views.js"
        source.write_text(source.read_text() + ";new code")
        with self.assertRaises(AssertionError):
            web.verify_asset_evidence()
        web.refresh_assets()
        copied = web.ASSETS / "tongjianyun/meal_scene/views.js"
        copied.write_text("stale copy")
        with self.assertRaises(AssertionError):
            web.verify_asset_evidence()

    def test_template_version_change_requires_refresh(self):
        web.refresh_assets()
        template = web.SOURCE / "tongjianyun/www/tongjianyun-meal-scene.html"
        template.write_text(template.read_text().replace("fixture-1", "fixture-2"))
        with self.assertRaises(AssertionError):
            web.verify_asset_evidence()

    def test_asset_only_contract_detects_unexpected_fixture_change(self):
        def changed():
            web.STATE.write_text("changed unexpectedly")
            return {}
        with patch.object(web, "copy_public_assets", side_effect=changed), self.assertRaises(AssertionError):
            web.refresh_assets()


if __name__ == "__main__":
    unittest.main()
