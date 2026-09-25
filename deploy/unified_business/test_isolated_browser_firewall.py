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
                body = b'{}' if method == "logout" else b'{"student_group":"QA","students":[]}'
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


class BlueprintBoundaryTests(unittest.TestCase):
    call = FirewallTests.call
    def setUp(self):
        self.fixture = {"manager": "browser-manager-02e16a31d7@example.invalid", "doctype": "Tongjianyun Advanced browser_estimate_a123456789",
                        "proposal_id": "qa-private-proposal", "revision": "a" * 64,
                        "children": {"estimate_lines": "TGY Extension Row qaexact"}}
        patcher = patch.object(web, "blueprint_fixture", return_value=self.fixture)
        patcher.start()
        self.addCleanup(patcher.stop)

    def document(self):
        return {"doctype": self.fixture["doctype"], "name": "new-qa-1", "__islocal": 1,
                "owner": self.fixture["manager"], "title": "Synthetic only", "docstatus": 0,
                "estimate_lines": [{"doctype": self.fixture["children"]["estimate_lines"],
                    "parent": "new-qa-1", "parenttype": self.fixture["doctype"], "parentfield": "estimate_lines",
                    "item_label": "Synthetic item", "quantity": 2.5, "unit_price": 3.8}]}

    def rpc(self, command, values, **kwargs):
        return self.call("/api/method/" + command, "POST", body=json.dumps(values).encode(), **kwargs)

    def test_exact_activation_and_native_draft_save_reach_application(self):
        cases = [("tongjianyun.business_blueprints.activate", {"proposal_id": self.fixture["proposal_id"], "revision": self.fixture["revision"]}),
                 ("frappe.desk.form.save.savedocs", {"doc": json.dumps(self.document()), "action": "Save"})]
        for command, values in cases:
            app, _, _, _ = self.rpc(command, values)
            app.assert_called_once()

    def test_activation_cannot_change_proposal_revision_or_http_verb(self):
        base = {"proposal_id": self.fixture["proposal_id"], "revision": self.fixture["revision"]}
        for extra in ({"proposal_id": "another-proposal"}, {"revision": "b" * 64}, {"doctype": "User"}):
            app, _, _, _ = self.rpc("tongjianyun.business_blueprints.activate", {**base, **extra})
            app.assert_not_called()
        app, _, _, _ = self.call("/api/method/tongjianyun.business_blueprints.activate", "GET", body=json.dumps(base).encode())
        app.assert_not_called()

    def test_scoped_reads_only_accept_exact_extension_and_no_injected_document(self):
        for command, values in (
            ("frappe.desk.form.load.getdoctype", {"doctype": self.fixture["doctype"], "with_parent": "1"}),
            ("frappe.desk.form.load.getdoctype", {"doctype": self.fixture["children"]["estimate_lines"]}),
            ("frappe.desk.form.load.getdoc", {"doctype": self.fixture["doctype"], "name": "qa-record"}),
            ("frappe.desk.form.load.get_docinfo", {"doctype": self.fixture["doctype"], "name": "qa-record"}),
            ("frappe.model.workflow.get_transitions", {"doc": json.dumps(self.document())}),
            ("frappe.model.utils.user_settings.get", {"doctype": self.fixture["doctype"]}),
            ("frappe.model.utils.user_settings.save", {"doctype": self.fixture["doctype"], "user_settings": {"Form": {}}}),
        ):
            app, _, _, _ = self.rpc(command, values)
            app.assert_called_once()
            changed = {**values, "doctype": "User"}
            app, _, _, _ = self.rpc(command, changed)
            app.assert_not_called()
        app, _, _, _ = self.rpc("frappe.desk.form.load.get_docinfo", {"doc": json.dumps(self.document())})
        app.assert_not_called()

    def test_foreign_parent_child_flags_and_submitted_states_are_rejected(self):
        changes = [lambda d: d.update(doctype="User"), lambda d: d.update(flags={"ignore_permissions": True}),
                   lambda d: d.update(owner="Administrator"), lambda d: d.update(docstatus=1),
                   lambda d: d.update(workflow_state="扩展·通过"), lambda d: d.update(amended_from="another-record"),
                   lambda d: d["estimate_lines"][0].update(doctype="Has Role"),
                   lambda d: d["estimate_lines"][0].update(parenttype="User"),
                   lambda d: d["estimate_lines"][0].update(parent="foreign-record"),
                   lambda d: d["estimate_lines"][0].update(parentfield="roles"),
                   lambda d: d["estimate_lines"][0].update(flags={"ignore_permissions": True}),
                   lambda d: d["estimate_lines"][0].update(extra_nested=[{"doctype": "User"}])]
        for change in changes:
            doc = self.document()
            change(doc)
            app, _, _, _ = self.rpc("frappe.desk.form.save.savedocs", {"doc": doc, "action": "Save"})
            app.assert_not_called()

    def test_native_grid_display_flags_do_not_allow_arbitrary_flags(self):
        doc = self.document()
        doc["estimate_lines"][0].update(__unedited=False, __checked=0)
        app, _, _, _ = self.rpc("frappe.desk.form.save.savedocs", {"doc": doc, "action": "Save"})
        app.assert_called_once()
        doc["estimate_lines"][0]["__unedited"] = {"ignore_permissions": True}
        app, _, _, _ = self.rpc("frappe.desk.form.save.savedocs", {"doc": doc, "action": "Save"})
        app.assert_not_called()
        for action in ("Submit", "Cancel", "Update"):
            app, _, _, _ = self.rpc("frappe.desk.form.save.savedocs", {"doc": self.document(), "action": action})
            app.assert_not_called()

    def test_transition_read_reloads_identity_but_does_not_allow_save_with_stale_parent(self):
        doc = self.document()
        doc["name"] = "saved-record"
        read, _, _, _ = self.rpc("frappe.model.workflow.get_transitions", {"doc": doc})
        read.assert_called_once()
        write, _, _, _ = self.rpc("frappe.desk.form.save.savedocs", {"doc": doc, "action": "Save"})
        write.assert_not_called()
        for values in ({"doc": doc, "workflow": {"is_active": 1}},
                       {"doc": {**doc, "flags": {"ignore_permissions": True}}},
                       {"doc": {**doc, "doctype": "User"}}):
            app, _, _, _ = self.rpc("frappe.model.workflow.get_transitions", values)
            app.assert_not_called()

    def test_all_path_cmd_aliases_receive_the_same_payload_checks(self):
        from urllib.parse import urlencode
        command = "frappe.desk.form.save.savedocs"
        body = {"doc": json.dumps(self.document()), "action": "Save"}
        for path in ("/api/method/", "/api/v1/method/", "/api/v2/method/"):
            app, _, _, _ = self.call(path + command, "POST", body=json.dumps(body).encode())
            app.assert_called_once()
        for content_type, raw in (("application/json", json.dumps({"cmd": command, **body}).encode()),
                                  ("application/x-www-form-urlencoded", urlencode({"cmd": command, **body}).encode())):
            app, _, _, _ = self.call("/", "POST", body=raw, content_type=content_type)
            app.assert_called_once()
        app, _, _, _ = self.call("/api/method/login", "POST", body=json.dumps({"cmd": command, **body}).encode())
        app.assert_not_called()
        app, _, _, _ = self.call("/api/method/" + command, "POST", query=urlencode({"doc": '{"doctype":"User"}'}), body=json.dumps(body).encode())
        app.assert_not_called()

    def test_duplicate_json_form_query_and_nested_doc_keys_fail_closed(self):
        cases = [("", b'{"action":"Save","action":"Cancel"}', "application/json"),
                 ("", b'action=Save&action=Cancel', "application/x-www-form-urlencoded"),
                 ("action=Save&action=Save", b'{}', "application/json"),
                 ("", json.dumps({"action": "Save", "doc": '{"doctype":"User","doctype":"' + self.fixture["doctype"] + '"}'}).encode(), "application/json")]
        for query, body, content_type in cases:
            app, _, _, _ = self.call("/api/method/frappe.desk.form.save.savedocs", "POST", query=query, body=body, content_type=content_type)
            app.assert_not_called()

    def test_preview_is_bound_to_the_seeded_private_proposal(self):
        from urllib.parse import urlencode
        for proposal, expected in ((self.fixture["proposal_id"], True), ("foreign", False)):
            query = urlencode({"selection_json": json.dumps({"view": "business_blueprint", "proposal_id": proposal})})
            app, _, _, _ = self.call("/api/method/tongjianyun.meal_views.get_view", query=query)
            self.assertEqual(app.called, expected)

    def test_native_auth_and_csrf_are_not_invented_or_removed(self):
        body = json.dumps({"proposal_id": self.fixture["proposal_id"], "revision": self.fixture["revision"]}).encode()
        for headers in ({}, {"HTTP_COOKIE": "sid=synthetic", "HTTP_X_FRAPPE_CSRF_TOKEN": "synthetic-token"}):
            environ = {"HTTP_HOST": f"{web.SITE}:{web.PORT}", "PATH_INFO": "/api/method/tongjianyun.business_blueprints.activate",
                       "REQUEST_METHOD": "POST", "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(body)),
                       "wsgi.input": io.BytesIO(body), **headers}
            seen = []
            def application(env, start):
                seen.append(dict(env))
                start("403 Forbidden", [])  # Stand-in for native auth/CSRF rejection.
                return [b"native CSRF rejection"]
            with patch.object(web, "config_guard", return_value={"unified_browser_acceptance": 1, "maintenance_mode": 0}):
                result = web.QAFirewall(application)(environ, Mock())
            self.assertEqual(result, [b"native CSRF rejection"])
            self.assertEqual({key: seen[0][key] for key in headers}, headers)
            self.assertEqual("HTTP_X_FRAPPE_CSRF_TOKEN" in seen[0], "HTTP_X_FRAPPE_CSRF_TOKEN" in headers)
            self.assertNotIn("ignore_csrf", seen[0])

    def test_missing_seed_fails_closed_for_new_capabilities(self):
        with patch.object(web, "blueprint_fixture", side_effect=FileNotFoundError):
            app, _, _, _ = self.rpc("frappe.desk.form.save.savedocs", {"doc": self.document(), "action": "Save"})
        app.assert_not_called()


class DeskDiagnosticsTests(unittest.TestCase):
    call = FirewallTests.call

    def test_only_exact_readonly_boot_methods_and_parameters_are_allowed(self):
        translations = "frappe.translate.get_boot_translations"
        defaults = "frappe.core.doctype.session_default_settings.session_default_settings.get_session_default_values"
        app, _, _, _ = self.call("/api/method/" + translations, query="lang=zh&v=build")
        app.assert_called_once()
        app, _, _, _ = self.call("/api/method/" + defaults, "POST", body=b"{}")
        app.assert_called_once()
        for command, method, body in ((translations, "POST", b'{}'), (defaults, "POST", b'{"default_values":{"company":"OTHER"}}'),
             ("frappe.desk.page.setup_wizard.setup_wizard.setup_complete", "POST", b'{}'),
             ("frappe.desk.page.setup_wizard.setup_wizard.load_languages", "POST", b'{}'),
             (defaults.replace("get_session", "set_session"), "POST", b'{}')):
            app, _, _, _ = self.call("/api/method/" + command, method, body=body)
            app.assert_not_called()

    def test_teacher_bootstrap_is_get_only_without_actor_or_role_overrides(self):
        command = "tongjianyun.scene_access.get_bootstrap"
        app, _, _, _ = self.call("/api/method/" + command)
        app.assert_called_once()
        app, _, _, _ = self.call("/api/method/" + command, query="day=2026-09-17&meal=lunch&group=QA%20Teacher")
        app.assert_called_once()
        for method, query, body in (("POST", "", b'{}'), ("GET", "user=Administrator", b""),
                                   ("GET", "", b'{"role":"System Manager"}'),
                                   ("GET", "day=invalid&meal=lunch", b""), ("GET", "meal=invalid", b"")):
            app, _, _, _ = self.call("/api/method/" + command, method, query=query, body=body)
            app.assert_not_called()

    def test_native_empty_body_logout_does_not_allow_targeting_another_session(self):
        app, _, _, _ = self.call("/api/method/logout", "POST", content_type="", body=b"")
        app.assert_called_once()
        for query in ("user=Administrator", "sid=another-session", "session=another-session"):
            app, _, _, _ = self.call("/api/method/logout", "POST", query=query, content_type="", body=b"")
            app.assert_not_called()
        for command in ("login", "tongjianyun.classroom.save_meals", "tongjianyun.business_blueprints.activate"):
            app, _, _, _ = self.call("/api/method/" + command, "POST", content_type="", body=b"")
            app.assert_not_called()
        app, _, _, _ = self.call("/api/method/logout", "POST", body=b'{"user":"Administrator"}')
        app.assert_not_called()

    def test_diagnostics_never_print_parameter_values_or_unknown_keys_and_commands(self):
        secret = "aSyntheticSecretNotForLogs"
        with patch("builtins.print") as printed:
            self.call("/api/method/" + secret, "POST", body=json.dumps({secret: secret, "csrf_token": secret}).encode())
        text = " ".join(str(call) for call in printed.call_args_list)
        self.assertNotIn(secret, text)
        self.assertIn("unlisted-command", text)
        self.assertIn("unlisted-key", text)

    def test_deferred_responses_retain_request_local_diagnostics(self):
        callbacks = []
        app = web.QAFirewall(lambda env, response: callbacks.append(response) or [])
        with patch.object(web, "config_guard", return_value={"unified_browser_acceptance": 1, "maintenance_mode": 0}):
            for command in ("frappe.auth.get_logged_user", "tongjianyun.meal_chat.get_chat_access"):
                app({"HTTP_HOST": f"{web.SITE}:{web.PORT}", "PATH_INFO": "/api/method/" + command,
                     "REQUEST_METHOD": "GET", "QUERY_STRING": "", "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO()}, Mock())
        with patch("builtins.print") as printed:
            callbacks[1]("200 OK", [])
            callbacks[0]("403 Forbidden", [])
        logs = [json.loads(call.args[0]) for call in printed.call_args_list]
        self.assertEqual(logs[0]["qa_rpc"]["commands"], ["tongjianyun.meal_chat.get_chat_access"])
        self.assertEqual(logs[1]["qa_rpc"]["commands"], ["frappe.auth.get_logged_user"])
        self.assertFalse(hasattr(app, "audit_context"))


class AssetEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        values = {"ROOT": root, "SITES": root / "sites", "SOURCE": root / "candidate",
                  "BENCH": root / "bench", "ASSETS": root / "sites/assets",
                  "STATE": root / "fixture.json", "CREDENTIALS": root / "credentials.json",
                  "ASSET_MARKER": root / "asset-evidence.json", "SERVER_STATE": root / "server.json",
                  "BLUEPRINT_STATE": root / "blueprint-fixture.json", "DESK_STATE": root / "desk-readiness.json",
                  "APPS": ("tongjianyun",)}
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
                     web.SITES / "common_site_config.json", web.BLUEPRINT_STATE, web.DESK_STATE):
            path.write_text('{"synthetic":true}')

    def test_all_harness_path_constants_are_isolated_from_retained_qa_files(self):
        # Fail visibly if a future preserved path is added without fixture
        # isolation. Do not depend on real server marker existence or absence.
        for name, value in vars(web).items():
            if name.isupper() and isinstance(value, Path):
                with self.subTest(name=name):
                    self.assertTrue(value.resolve().is_relative_to(web.ROOT))

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

    def test_asset_refresh_preserves_existing_blueprint_and_desk_markers(self):
        markers = (web.BLUEPRINT_STATE, web.DESK_STATE)
        before = {path: path.read_bytes() for path in markers}
        web.refresh_assets()
        self.assertEqual(before, {path: path.read_bytes() for path in markers})
        for path in markers:
            def changed(target=path):
                target.write_text('unexpected marker change')
                return {}
            with self.subTest(marker=path.name), patch.object(web, "copy_public_assets", side_effect=changed), \
                 self.assertRaises(AssertionError):
                web.refresh_assets()


if __name__ == "__main__":
    unittest.main()
