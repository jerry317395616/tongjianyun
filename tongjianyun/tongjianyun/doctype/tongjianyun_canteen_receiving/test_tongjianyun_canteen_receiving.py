from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from tongjianyun.canteen_ops import purchasing


class ReceivingReviewTests(TestCase):
    def setUp(self):
        self.row = SimpleNamespace(idx=1, delivery_item="line", accepted_qty=0, reason="待现场核对")
        doc = SimpleNamespace(company="园所", canteen="食堂", delivery="配送单", arrived_at="2026-11-27",
                              items=[self.row], photo=None, position=None, purchase_receipt=None)
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
