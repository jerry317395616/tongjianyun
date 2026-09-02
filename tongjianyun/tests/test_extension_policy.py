import unittest

from tongjianyun.extension_policy import evaluate_extension_change


class TestExtensionPolicy(unittest.TestCase):
	def test_non_structural_extension_is_owned_by_tongjianyun(self):
		decision = evaluate_extension_change("form-ui")

		self.assertTrue(decision.allowed)
		self.assertEqual(decision.owner_app, "tongjianyun")
		self.assertFalse(decision.structural_change)

	def test_field_extension_requires_explicit_confirmation(self):
		preview = evaluate_extension_change("add-field")
		confirmed = evaluate_extension_change("add-field", explicitly_confirmed=True)

		self.assertFalse(preview.allowed)
		self.assertTrue(preview.requires_explicit_confirmation)
		self.assertTrue(confirmed.allowed)

	def test_forbidden_structure_changes_cannot_be_confirmed(self):
		for change_kind in ("add-doctype", "modify-upstream-doctype-json", "database-ddl"):
			with self.subTest(change_kind=change_kind):
				decision = evaluate_extension_change(change_kind, explicitly_confirmed=True)

				self.assertFalse(decision.allowed)
				self.assertFalse(decision.requires_explicit_confirmation)

	def test_unknown_change_kind_is_rejected(self):
		with self.assertRaisesRegex(ValueError, "未知的扩展变更类型"):
			evaluate_extension_change("invented-change")


if __name__ == "__main__":
	unittest.main()
