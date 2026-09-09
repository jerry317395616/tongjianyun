import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
from tongjianyun import recipe_item_sync as service


class TestRecipeItemSync(unittest.TestCase):
    def test_progress_reports_batch_and_retry_without_payload(self):
        progress = MagicMock()
        with patch.object(service, "request_classification", side_effect=[
                ValueError("private"), [], []]), patch.object(service, "validate_proposals"):
            service.classify_batches(None, [{"key": str(i)} for i in range(21)], [], progress)
        self.assertEqual([call.args for call in progress.call_args_list], [(1, 2, 1), (1, 2, 2), (2, 2, 1)])
        self.assertNotIn("private", str(progress.call_args_list))

    def test_batch_failure_preserves_other_successes(self):
        pending = [{"key": str(i)} for i in range(41)]
        with patch.object(service, "request_classification", side_effect=[
                [{"key": "0"}], ValueError("private"), ValueError("private"), [{"key": "40"}]]), \
             patch.object(service, "validate_proposals"):
            rows, errors = service.classify_batches(None, pending, [])
        self.assertEqual(rows, [{"key": "0"}, {"key": "40"}])
        self.assertEqual(errors[0]["batch"], 2)
        self.assertEqual(errors[0]["code"], "invalid_classification")
        self.assertEqual(len(errors[0]["keys"]), 20)
        self.assertNotIn("private", str(errors))

    def test_transient_service_failure_retries(self):
        with patch.object(service, "request_classification", side_effect=[service.ClassificationUnavailable("private"), [{"key":"a"}]] ) as call, \
             patch.object(service, "validate_proposals"):
            rows, errors = service.classify_batches(None, [{"key":"a"}], [])
        self.assertEqual(call.call_count, 2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(errors, [])

    def test_total_failure_is_bounded_and_sanitized(self):
        with patch.object(service, "request_classification", side_effect=RuntimeError("private")) as call:
            rows, errors = service.classify_batches(None, [{"key":"a"}], [])
        self.assertEqual(call.call_count, 2)
        self.assertEqual(rows, [])
        self.assertEqual(errors[0]["code"], "unexpected_error")
        self.assertNotIn("private", str(errors))

    def test_global_group_validation_failure_preserves_prior_batch(self):
        with patch.object(service, "request_classification", return_value=[{"key":"a"}]), \
             patch.object(service, "validate_proposals", side_effect=[None, ValueError(), ValueError()]):
            rows, errors = service.classify_batches(None, [{"key":str(i)} for i in range(21)], [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(errors[0]["batch"], 2)

    def test_status_distinguishes_failure_review_and_partial(self):
        for mappings, failed, unresolved, status in [({}, True, [1], "failed"),
                ({"a":{}}, True, [1], "partial"), ({}, False, [1], "needs_review"),
                ({"a":{}}, False, [], "completed")]:
            result = {"mappings":mappings,"classification_failed":failed,"unresolved":unresolved}
            service.summarize_result(result)
            self.assertEqual(result["status"], status)

    def test_enqueue_only_after_commit_with_no_actor_override(self):
        callbacks = []
        db = SimpleNamespace(after_commit=SimpleNamespace(add=callbacks.append))
        with patch.object(service, "source_snapshot", return_value={"revision": "r"}), \
             patch.object(service, "_permission"), patch.object(service, "_state"), \
             patch.object(service.frappe, "db", db), \
             patch.object(service.frappe, "session", SimpleNamespace(user="teacher")), \
             patch.object(service.frappe, "enqueue") as enqueue:
            self.assertEqual(service.schedule_after_save("recipe")["status"], "queued")
            enqueue.assert_not_called()
            self.assertEqual(len(callbacks), 1)
            callbacks[0]()
            args = enqueue.call_args.kwargs
            self.assertEqual(args["recipe"], "recipe")
            self.assertTrue(args["deduplicate"])
            self.assertNotIn("user", args)
            self.assertNotIn("ignore_permissions", args)

    def test_failed_queue_does_not_raise_into_save(self):
        callbacks = []
        with patch.object(service, "source_snapshot", return_value={"revision": "r"}), \
             patch.object(service, "_permission"), patch.object(service, "_state") as state, \
             patch.object(service.frappe, "db", SimpleNamespace(after_commit=SimpleNamespace(add=callbacks.append))), \
             patch.object(service.frappe, "session", SimpleNamespace(user="teacher")), \
             patch.object(service.frappe, "enqueue", side_effect=RuntimeError("private")):
            service.schedule_after_save("recipe")
            callbacks[0]()
            self.assertEqual(state.call_args.args[1]["status"], "failed")
            self.assertNotIn("private", str(state.call_args))

    def test_permission_failure_does_not_enqueue(self):
        with patch.object(service, "source_snapshot", side_effect=PermissionError), \
             patch.object(service.frappe, "enqueue") as enqueue:
            self.assertEqual(service.schedule_after_save("recipe")["status"], "blocked")
            enqueue.assert_not_called()

    def test_soup_never_matches_even_if_item_exists(self):
        with patch.object(service.frappe, "get_list") as query:
            mapping, reason = service._match({"ingredient": "绿豆银耳汤", "unit": "ml"})
            self.assertIsNone(mapping)
            self.assertTrue(reason)
            query.assert_not_called()

    def test_duplicate_name_not_auto_selected(self):
        with patch.object(service.frappe, "get_list", return_value=[{}, {}]):
            mapping, reason = service._match({"ingredient": "大米", "unit": "g"})
            self.assertIsNone(mapping)
            self.assertIn("多个", reason)

    def test_unit_mismatch_rejected(self):
        with patch.object(service.frappe, "get_list", return_value=[SimpleNamespace(name="x")]), \
             patch.object(service, "_read", side_effect=[SimpleNamespace(name="x", stock_uom="Kg"), SimpleNamespace(enabled=1)]):
            mapping, reason = service._match({"ingredient": "牛奶", "unit": "ml"})
            self.assertIsNone(mapping)
            self.assertIn("换算", reason)

    def test_stale_task_never_applies(self):
        with patch.object(service, "_state"), \
             patch.object(service, "source_snapshot", return_value={"revision": "new"}), \
             patch.object(service, "make_plan", return_value={"revision": "new"}), \
             patch.object(service, "apply_plan") as apply:
            service.run_sync("recipe", "old")
            apply.assert_not_called()

    def test_worker_error_rollback_sanitized(self):
        with patch.object(service, "_state") as state, \
             patch.object(service, "source_snapshot", return_value={"revision": "r"}), \
             patch.object(service, "make_plan", side_effect=RuntimeError("private")), \
             patch.object(service.frappe, "db", MagicMock()) as db:
            self.assertEqual(service.run_sync("recipe", "r"), {"status": "failed"})
            db.rollback.assert_called_once()
            self.assertNotIn("private", str(state.call_args))
