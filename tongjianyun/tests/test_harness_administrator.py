"""Administrator business policy and ORM dispatch, without production mutations."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tongjianyun import harness_administrator as mod


class Field(SimpleNamespace):
    def get(self, key):
        return getattr(self, key, None)


class AdministratorTests(unittest.TestCase):
    def setUp(self):
        self.fields = {
            "first_name": Field(fieldtype="Data", read_only=0),
            "student_name": Field(fieldtype="Data", read_only=1),
            "api_key": Field(fieldtype="Data", read_only=0),
            "pin": Field(fieldtype="Password", read_only=0),
            "guardians": Field(fieldtype="Table", read_only=0),
            "script": Field(fieldtype="Code", read_only=0),
        }
        self.meta = SimpleNamespace(module="Education", issingle=0, istable=0,
                                    is_virtual=0, get_field=self.fields.get)
        self.values = {"first_name": "Before"}
        self.doc = Mock(name="document")
        self.doc.name = "EDU-TEST"
        self.doc.modified = "2026-09-08 01:00:00"
        self.doc.docstatus = 0
        self.doc.get.side_effect = self.values.get
        self.doc.set.side_effect = self.values.__setitem__
        self.fake = SimpleNamespace(
            local=SimpleNamespace(site=mod.SITE), session=SimpleNamespace(user="Administrator"),
            conf={mod.ENABLE_KEY: 1},
            db=SimpleNamespace(get_value=Mock(return_value=SimpleNamespace(enabled=1, user_type="System User")),
                               exists=Mock(return_value=False), commit=Mock()),
            get_meta=Mock(return_value=self.meta), get_doc=Mock(return_value=self.doc),
            has_permission=Mock(return_value=True), get_list=Mock(return_value=[{"name": "EDU-TEST"}]),
        )
        patcher = patch.object(mod, "frappe", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def preview(self, **kwargs):
        return mod.preview_change("update", "Student", name="EDU-TEST", changes={"first_name": "After"}, **kwargs)

    def test_exact_administrator_only(self):
        for user in ["Guest", "admin", "administrator", "teacher@example.invalid"]:
            self.fake.session.user = user
            with self.subTest(user=user), self.assertRaises(PermissionError):
                self.preview()
        self.fake.get_meta.assert_not_called()

    def test_site_and_feature_gate(self):
        for enabled in [0, None, "1", 2]:
            self.fake.conf[mod.ENABLE_KEY] = enabled
            with self.subTest(enabled=enabled), self.assertRaises(PermissionError):
                self.preview()
        self.fake.conf[mod.ENABLE_KEY] = 1
        self.fake.local.site = "other.example.invalid"
        with self.assertRaises(PermissionError):
            self.preview()

    def test_disabled_or_website_account_is_denied(self):
        for user in [None, SimpleNamespace(enabled=0, user_type="System User"),
                     SimpleNamespace(enabled=1, user_type="Website User")]:
            self.fake.db.get_value.return_value = user
            with self.assertRaises(PermissionError):
                self.preview()

    def test_structural_doctypes_rejected_before_metadata_lookup(self):
        for doctype in list(mod.PROTECTED_TYPES) + [value.lower() for value in mod.PROTECTED_TYPES]:
            with self.subTest(doctype=doctype), self.assertRaises(PermissionError):
                mod.preview_change("delete", doctype, name="x")
        self.fake.get_meta.assert_not_called()

    def test_single_child_virtual_and_framework_modules_are_denied(self):
        for attr in ["issingle", "istable", "is_virtual"]:
            setattr(self.meta, attr, 1)
            with self.subTest(attr=attr), self.assertRaises(PermissionError):
                self.preview()
            setattr(self.meta, attr, 0)
        for module in mod.PROTECTED_MODULES:
            self.meta.module = module
            with self.subTest(module=module), self.assertRaises(PermissionError):
                self.preview()

    def test_unsafe_fields_denied_for_reads_and_writes(self):
        for field in ["api_key", "pin", "guardians", "script", "unknown", "name as x", "*"]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                mod.read_documents("Student", fields=[field])
            with self.subTest(field=field), self.assertRaises(ValueError):
                mod.preview_change("update", "Student", name="x", changes={field: "value"})

    def test_system_and_computed_fields_cannot_be_written(self):
        for field in list(mod.IMMUTABLE) + ["student_name"]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                mod.preview_change("update", "Student", name="x", changes={field: "x"})

    def test_read_uses_permission_aware_list_with_bounded_explicit_fields(self):
        self.assertEqual(mod.read_documents("Student"), [{"name": "EDU-TEST"}])
        self.fake.get_list.assert_called_once_with("Student", fields=["name"], filters={},
            limit_start=0, limit_page_length=20, order_by="name asc")

    def test_filter_and_pagination_bypasses_rejected(self):
        for kwargs in [{"filters": {"api_key": "x"}}, {"filters": {"name": ["like", "%"]}},
                       {"filters": {"name": {"sql": "x"}}}, {"limit": True}, {"limit": 101},
                       {"start": -1}, {"fields": []}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                mod.read_documents("Student", **kwargs)

    def test_preview_never_saves_or_commits(self):
        preview = self.preview()
        self.assertEqual(preview.as_dict()["before"]["first_name"], "Before")
        self.doc.save.assert_not_called()
        self.doc.insert.assert_not_called()
        self.fake.db.commit.assert_not_called()

    def test_update_locks_and_uses_normal_save_then_reloads(self):
        result = mod.apply_preview(self.preview())
        self.fake.get_doc.assert_any_call("Student", "EDU-TEST", for_update=True)
        self.doc.save.assert_called_once_with(ignore_version=False)
        self.doc.reload.assert_called_once_with()
        self.assertEqual(result["after"]["first_name"], "After")
        self.assertEqual(result["transaction"], "pending_adapter_commit")
        self.fake.db.commit.assert_not_called()

    def test_stale_preview_does_not_write(self):
        preview = self.preview()
        self.doc.modified = "2026-09-08 02:00:00"
        with self.assertRaises(ValueError):
            mod.apply_preview(preview)
        self.doc.save.assert_not_called()

    def test_identity_and_enablement_rechecked_on_apply(self):
        preview = self.preview()
        self.fake.session.user = "teacher@example.invalid"
        with self.assertRaises(PermissionError):
            mod.apply_preview(preview)
        self.doc.save.assert_not_called()

    def test_orm_errors_propagate_without_commit(self):
        self.doc.save.side_effect = ValueError("business validation failed")
        with self.assertRaisesRegex(ValueError, "business validation"):
            mod.apply_preview(self.preview())
        self.fake.db.commit.assert_not_called()
        self.doc.reload.assert_not_called()

    def test_create_uses_frappe_naming_and_insert(self):
        preview = mod.preview_change("create", "Student", changes={"first_name": "New"})
        mod.apply_preview(preview)
        self.fake.get_doc.assert_any_call({"doctype": "Student", "first_name": "New"})
        self.doc.insert.assert_called_once_with()

    def test_lifecycle_uses_orm_without_force_or_ignore_permissions(self):
        for operation in ["submit", "cancel", "delete"]:
            with self.subTest(operation=operation):
                preview = mod.preview_change(operation, "Student", name="EDU-TEST")
                mod.apply_preview(preview)
                getattr(self.doc, operation).assert_called_once_with()

    def test_delete_verifies_removal(self):
        self.fake.db.exists.return_value = True
        preview = mod.preview_change("delete", "Student", name="EDU-TEST")
        with self.assertRaisesRegex(RuntimeError, "verification"):
            mod.apply_preview(preview)

    def test_wire_dict_is_not_a_trusted_preview(self):
        with self.assertRaises(ValueError):
            mod.apply_preview(self.preview().as_dict())

    def test_nonfinite_and_nested_write_values_rejected(self):
        for value in [float("nan"), float("inf"), {}, [], "x" * 20001]:
            with self.assertRaises(ValueError):
                mod.preview_change("update", "Student", name="x", changes={"first_name": value})

    def test_create_name_and_extra_lifecycle_changes_rejected(self):
        with self.assertRaises(ValueError):
            mod.preview_change("create", "Student", name="user-chosen")
        with self.assertRaises(ValueError):
            mod.preview_change("delete", "Student", name="x", changes={"first_name": "x"})


if __name__ == "__main__":
    unittest.main()
