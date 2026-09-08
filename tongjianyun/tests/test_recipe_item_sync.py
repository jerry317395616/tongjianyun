import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
from tongjianyun import recipe_item_sync as service


class TestRecipeItemSync(unittest.TestCase):
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
