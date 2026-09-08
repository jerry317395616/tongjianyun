"""Confirmation replay, uncertain outcomes and transaction-coupled auditing."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tongjianyun import harness_administrator_approvals as service


class AuditDoc(SimpleNamespace):
    def insert(self):
        if self.ledger.fail_result and self.tool_name.startswith(service.RESULT_PREFIX):
            if self.status == "成功" or self.ledger.fail_failure:
                raise RuntimeError("audit unavailable")
        self.name = "MCPA-TEST-" + str(self.ledger.serial)
        self.ledger.serial += 1
        self.ledger.rows[self.name] = {key: value for key, value in vars(self).items() if key != "ledger"}
        return self

    def check_permission(self, permission):
        assert permission == "read"


class Ledger:
    def __init__(self):
        self.rows, self.saved = {}, ({}, 0)
        self.serial, self.business_count = 1, 0
        self.fail_result, self.fail_failure = False, False
        self.calls = []

    def get_doc(self, doctype, name=None, **kwargs):
        self.calls.append((doctype, name, kwargs))
        data = doctype if isinstance(doctype, dict) else self.rows[name]
        return AuditDoc(**data, ledger=self)

    def get_list(self, doctype, *, filters, fields, limit_page_length):
        return [{field: row.get(field) for field in fields} for row in self.rows.values()
                if all(row.get(key) == value for key, value in filters.items())][:limit_page_length]

    def commit(self):
        self.saved = deepcopy(self.rows), self.business_count

    def rollback(self):
        self.rows, self.business_count = deepcopy(self.saved)


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger()
        self.now = 1000
        self.binding = "a" * 64
        self.meta = SimpleNamespace(get_field=lambda field: SimpleNamespace(fieldtype=service.AUDIT_FIELDS[field]))
        self.fake = SimpleNamespace(conf={service.WRITE_ENABLE_KEY: 1}, db=self.ledger,
            get_doc=self.ledger.get_doc, get_list=self.ledger.get_list, get_meta=Mock(return_value=self.meta))
        self.plan = {"site": "child.myyr.top", "user": "Administrator", "operation": "create",
                     "doctype": "Student", "name": None, "count": 1, "changes": {"first_name": "Synthetic"}}
        payload = json.dumps(self.plan)
        preview = service.business.Preview(payload, hashlib.sha256(payload.encode()).hexdigest())
        self.admin = Mock()
        self.apply = Mock(side_effect=self.write)
        for patcher in [patch.object(service, "frappe", self.fake),
                        patch.object(service.business, "_administrator", self.admin),
                        patch.object(service.business, "preview_change", Mock(return_value=preview)),
                        patch.object(service.business, "apply_preview", self.apply),
                        patch.object(service.time, "time", lambda: self.now)]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, preview):
        self.ledger.business_count += 1
        return {"name": "SYNTHETIC", "doctype": "Student", "transaction": "pending_adapter_commit"}

    def create(self):
        return service.create_preview(self.binding, "create", "Student", changes={"first_name": "Synthetic"})

    def confirm(self, preview):
        return service.confirm_preview(self.binding, preview["preview_id"], preview["digest"])

    def test_preview_saves_audit_only(self):
        preview = self.create()
        self.assertEqual(preview["state"], "awaiting_confirmation")
        self.assertEqual(len(self.ledger.rows), 1)
        self.assertEqual(self.ledger.business_count, 0)
        self.apply.assert_not_called()

    def test_confirm_commits_business_and_receipt_once(self):
        preview = self.create()
        result = self.confirm(preview)
        again = self.confirm(preview)
        self.assertEqual(result["state"], "succeeded")
        self.assertFalse(result["replayed"])
        self.assertTrue(again["replayed"])
        self.assertEqual(self.ledger.business_count, 1)
        self.apply.assert_called_once()
        self.assertEqual(len(self.ledger.rows), 3)
        self.assertNotIn("transaction", result["result"])
        self.assertIn((service.AUDIT, preview["preview_id"], {"for_update": True}), self.ledger.calls)

    def test_success_receipt_is_replayable_after_preview_expiry(self):
        preview = self.create()
        self.confirm(preview)
        self.now += 10000
        self.assertTrue(self.confirm(preview)["replayed"])
        self.apply.assert_called_once()

    def test_expired_unconfirmed_preview_never_executes(self):
        preview = self.create()
        self.now += service.TTL_SECONDS
        with self.assertRaisesRegex(ValueError, "expired"):
            self.confirm(preview)
        self.apply.assert_not_called()

    def test_binding_and_digest_mismatch_never_execute(self):
        preview = self.create()
        for binding, digest in [("b" * 64, preview["digest"]), (self.binding, "c" * 64)]:
            with self.assertRaises(PermissionError):
                service.confirm_preview(binding, preview["preview_id"], digest)
        self.apply.assert_not_called()

    def test_tampered_stored_payload_is_denied(self):
        preview = self.create()
        row = self.ledger.rows[preview["preview_id"]]
        envelope = json.loads(row["request_summary"])
        envelope["payload"] += " "
        row["request_summary"] = json.dumps(envelope)
        with self.assertRaises(PermissionError):
            self.confirm(preview)
        self.apply.assert_not_called()

    def test_unknown_claim_never_retries(self):
        preview = self.create()
        service._log(service.CLAIM_PREFIX + preview["preview_id"], "写入", "成功", self.plan, {}, {"state": "accepted"})
        self.ledger.commit()
        self.assertEqual(self.confirm(preview)["state"], "outcome_unknown")
        self.apply.assert_not_called()

    def test_business_error_is_terminal_and_redacted(self):
        preview = self.create()
        self.apply.side_effect = ValueError("private-validation-value")
        first = self.confirm(preview)
        again = self.confirm(preview)
        self.assertEqual(first["state"], "failed")
        self.assertEqual(first["error_type"], "ValueError")
        self.assertTrue(again["replayed"])
        self.apply.assert_called_once()
        self.assertNotIn("private-validation-value", json.dumps(self.ledger.rows))

    def test_success_audit_failure_rolls_back_business_change(self):
        preview = self.create()
        self.ledger.fail_result = True
        result = self.confirm(preview)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(self.ledger.business_count, 0)
        self.assertTrue(self.confirm(preview)["replayed"])
        self.apply.assert_called_once()

    def test_all_audit_failure_preserves_unknown_claim_without_retry(self):
        preview = self.create()
        self.ledger.fail_result = self.ledger.fail_failure = True
        self.assertEqual(self.confirm(preview)["state"], "outcome_unknown")
        self.assertEqual(self.confirm(preview)["state"], "outcome_unknown")
        self.assertEqual(self.ledger.business_count, 0)
        self.apply.assert_called_once()

    def test_schema_mismatch_blocks_without_migration(self):
        self.meta.get_field = lambda field: None
        with self.assertRaisesRegex(RuntimeError, "schema"):
            self.create()
        self.assertEqual(self.ledger.rows, {})

    def test_disabled_gate_and_non_admin_are_denied(self):
        self.fake.conf[service.WRITE_ENABLE_KEY] = 0
        with self.assertRaises(PermissionError):
            self.create()
        self.fake.conf[service.WRITE_ENABLE_KEY] = 1
        self.admin.side_effect = PermissionError("not Administrator")
        with self.assertRaises(PermissionError):
            self.create()
        self.assertEqual(self.ledger.rows, {})

    def test_unbound_session_is_denied(self):
        for binding in [None, "Administrator", "", "a" * 63]:
            with self.assertRaises(PermissionError):
                service.create_preview(binding, "create", "Student")

    def test_commit_acknowledgement_failure_is_unknown_not_retried(self):
        preview = self.create()
        commit = self.ledger.commit
        calls = 0
        def uncertain_commit():
            nonlocal calls
            calls += 1
            commit()
            if calls == 2:
                raise ConnectionError("lost commit acknowledgement")
        self.ledger.commit = uncertain_commit
        self.assertEqual(self.confirm(preview)["state"], "outcome_unknown")
        self.assertEqual(self.confirm(preview)["state"], "succeeded")
        self.apply.assert_called_once()


if __name__ == "__main__":
    unittest.main()
