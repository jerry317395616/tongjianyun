from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from frappe import _dict

from tongjianyun import food_safety_context as service


class FoodSafetyContextTests(unittest.TestCase):
    def test_recent_procurement_uses_tongjianyun_erpnext_orders(self):
        requests = [
            _dict(
                name="MR-1",
                title="童健云食谱采购 · R1",
                status="已提交",
                docstatus=1,
                transaction_date="2026-09-18",
                modified="2026-09-18 10:00:00",
            )
        ]
        orders = [
            _dict(
                name="PO-1",
                title="2026-09-18 · 供应商",
                status="To Receive and Bill",
                supplier_name="供应商",
                transaction_date="2026-09-18",
                grand_total=123.45,
                per_received=50,
                modified="2026-09-18 11:00:00",
            )
        ]

        def get_all(doctype, *args, **kwargs):
            if doctype == "Material Request":
                self.assertEqual(
                    kwargs["filters"]["title"],
                    ["like", service.PROCUREMENT_REQUEST_TITLE_PREFIX + "%"],
                )
                return requests
            if doctype == "Purchase Order Item":
                return [_dict(parent="PO-1")]
            if doctype == "Purchase Order":
                return orders
            return []

        with patch.object(service.frappe, "db", MagicMock()) as db,              patch.object(service.frappe, "get_all", side_effect=get_all):
            db.exists.return_value = True
            db.table_exists.return_value = True
            result = service._recent_procurement_summaries()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "ERPNext Purchase Order")
        self.assertEqual(result[0]["amount"], 123.45)
        self.assertEqual(result[0]["received_percent"], 50.0)


if __name__ == "__main__":
    unittest.main()
