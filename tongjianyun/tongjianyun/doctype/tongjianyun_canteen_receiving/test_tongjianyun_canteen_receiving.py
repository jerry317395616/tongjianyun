from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from tongjianyun.canteen_ops import purchasing


class ReceivingReviewTests(TestCase):
    def setUp(self):
        self.row = SimpleNamespace(idx=1, delivery_item="line", accepted_qty=0, reason="待现场核对")
        doc = SimpleNamespace(company="园所", canteen="食堂", delivery="配送单", arrived_at="2026-11-27",
                              items=[self.row], photo=None, position=None, purchase_receipt=None, verified_delivery_note=None)
        self.handler = purchasing.Receiving(doc)
        delivery = SimpleNamespace(items=[SimpleNamespace(name="line", quantity=3)])
        policy = SimpleNamespace(require_dual_review=False, require_photo=False, require_location=False,
                                 require_supplier_credential=False)

        def require(condition, message):
            if not condition:
                raise ValueError(message)

        for name in ("lock_company", "unique_active", "attached_file"):
            self.enterContext(patch.object(purchasing, name))
        self.enterContext(patch.object(purchasing, "linked", return_value=delivery))
        self.enterContext(patch.object(purchasing, "submitted", side_effect=lambda doc: doc))
        self.enterContext(patch.object(purchasing, "active_policy", return_value=policy))
        self.enterContext(patch.object(purchasing, "frappe", session=SimpleNamespace(user="reviewer")))
        self.enterContext(patch.object(purchasing, "require", side_effect=require))
        self.enterContext(patch.object(purchasing, "now_datetime", return_value="2026-11-27 10:00"))

    def test_unchecked_or_partial_row_needs_an_actual_reason(self):
        for amount in (0, 1):
            with self.subTest(accepted=amount):
                self.row.accepted_qty = amount
                with self.assertRaisesRegex(ValueError, "短送或拒收原因"):
                    self.handler.before_submit()

    def test_all_short_with_an_actual_reason_can_be_recorded_without_stock(self):
        self.row.reason = "现场清点，本批未随车送达"
        with patch.object(purchasing, "_mapped_receipt") as receive:
            self.handler.before_submit()
            receive.assert_not_called()
        self.assertEqual(self.handler.doc.reviewer, "reviewer")


class DeliveryNoteTests(TestCase):
    def setUp(self):
        self.day = purchasing.getdate("2026-11-27")
        self.row = SimpleNamespace(item_code="米", lot_number="B1")
        self.rule = SimpleNamespace(evidence_type="送货单", require_matching_batch=True, require_expiry=False)
        self.note = SimpleNamespace(name="note", evidence_type="送货单", item_code=None, lot_number=None,
                                    reference_no="D1", attachment="/private/files/d1.pdf", valid_until=None)
        self.delivery = SimpleNamespace(evidence=[self.note])

    def problems(self, *rules):
        return purchasing.evidence_problems(self.delivery, self.row, None, self.day, rules=rules or [self.rule])

    def test_legacy_unscoped_delivery_note_covers_all_lots_of_this_delivery_only(self):
        for lot in ("B1", "B2", None):
            self.row.lot_number = lot
            self.assertEqual(self.problems(), [])
        self.assertTrue(purchasing.note_verifies_line(self.note, [self.rule]))
        self.assertFalse(purchasing.note_verifies_line(None, [self.rule]))
        self.delivery.evidence = []
        self.assertEqual(self.problems(), ["缺少送货单"])

    def test_scoped_slip_and_special_certificates_remain_scoped(self):
        self.note.item_code, self.note.lot_number = "米", "B2"
        self.assertTrue(self.problems())
        self.note.lot_number = "B1"
        self.assertEqual(self.problems(), [])
        self.rule.evidence_type = self.note.evidence_type = "检疫证明"
        self.note.item_code = self.note.lot_number = None
        self.assertTrue(self.problems())
        self.assertFalse(purchasing.note_verifies_line(self.note, [self.rule]))

    def test_ordinary_slip_preserves_expiry_and_other_evidence_requirements(self):
        specific = SimpleNamespace(evidence_type="检疫证明", require_matching_batch=True, require_expiry=False)
        self.assertEqual(self.problems(self.rule, specific), ["缺少检疫证明"])
        self.assertFalse(purchasing.note_verifies_line(self.note, [self.rule, specific]))
        self.rule.require_expiry = True
        self.assertTrue(self.problems())
        self.assertFalse(purchasing.note_verifies_line(self.note, [self.rule]))
        self.note.valid_until = "2026-11-26"
        self.assertTrue(self.problems())
        self.note.valid_until = "2026-11-27"
        self.assertEqual(self.problems(), [])
