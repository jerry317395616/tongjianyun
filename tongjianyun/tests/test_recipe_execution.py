import unittest
from unittest.mock import MagicMock, patch
from frappe import _dict
from tongjianyun import recipe_execution as flow
from tongjianyun import recipe_procurement as p


class ExecutionTests(unittest.TestCase):
    def test_stock_price_is_converted_not_inflated(self):
        for unit in ("g", ""):
            rows=[_dict(uom=unit, price_list_rate=0.003, valid_from=None, valid_upto=None)]
            db=MagicMock()
            db.get_value.return_value="g"
            with patch.object(p.frappe,"db",db), patch.object(p.frappe,"get_all",return_value=rows), patch.object(p,"nowdate",return_value="2026-09-11"):
                self.assertEqual(p._current_buying_price("X","Buying","Kg"),3)

    def test_kg_quote_preserves_stock_quantity(self):
        lines=[dict(uom="g", qty=3300)]
        with patch.object(p.frappe, "db", MagicMock()):
            p._normalize_purchase_units(lines)
        self.assertEqual(lines[0], dict(uom="Kg", qty=3.3, stock_uom="g", stock_qty=3300, conversion_factor=1000))

    def test_litre_quote_preserves_stock_quantity(self):
        lines=[dict(uom="Millilitre", qty=1234)]
        with patch.object(p.frappe, "db", MagicMock()):
            p._normalize_purchase_units(lines)
        self.assertEqual(lines[0]["uom"], "Litre")
        self.assertEqual(lines[0]["qty"], 1.234)

    def test_pieces_and_existing_kg_unchanged(self):
        lines=[dict(uom="Nos", qty=3), dict(uom="Kg", qty=0.25)]
        p._normalize_purchase_units(lines)
        self.assertEqual(lines, [dict(uom="Nos", qty=3), dict(uom="Kg", qty=0.25)])

    def test_missing_uom_does_not_create_metadata(self):
        db=MagicMock()
        db.exists.return_value=False
        with patch.object(p.frappe, "db", db), patch.object(p.frappe, "throw", side_effect=ValueError), self.assertRaises(ValueError):
            p._normalize_purchase_units([dict(uom="g",qty=3)])

    def test_existing_request_cannot_silently_change_price(self):
        doc=MagicMock()
        doc.items=[_dict(schedule_date="2026-09-07",item_code="X",uom="Kg",qty=3,rate=8)]
        plan={"lines":[dict(doc.items[0], rate=9)]}
        with patch.object(p,"_read",return_value=doc), patch.object(flow.frappe,"throw",side_effect=ValueError), self.assertRaises(ValueError):
            flow._assert_existing_request_matches("MR",plan)

    def test_existing_matching_request_can_continue(self):
        doc=MagicMock()
        doc.items=[_dict(schedule_date="2026-09-07",item_code="X",uom="Kg",qty=3,rate=8)]
        with patch.object(p,"_read",return_value=doc):
            flow._assert_existing_request_matches("MR",{"lines":doc.items})

    def test_partial_order_coverage_cannot_be_completed(self):
        request=MagicMock()
        request.items=[_dict(ordered_qty=2,stock_qty=3)]
        with patch.object(p,"_read",return_value=request), patch.object(flow.frappe,"throw",side_effect=ValueError), self.assertRaises(ValueError):
            flow._verify_settlement({"name":"MR","purchase_orders":["PO"]})

    def test_other_unpaid_invoice_cannot_be_ignored(self):
        request=MagicMock()
        request.items=[_dict(ordered_qty=3,stock_qty=3)]
        order=MagicMock(per_received=100,per_billed=100)
        with patch.object(p,"_read",side_effect=[request,order]), patch.object(p,"_linked_active_documents",return_value=[_dict(outstanding_amount=10),_dict(outstanding_amount=0)]), patch.object(flow.frappe,"throw",side_effect=ValueError), self.assertRaises(ValueError):
            flow._verify_settlement({"name":"MR","purchase_orders":["PO"]})

    def test_public_state_does_not_expose_execution_identity_or_inputs(self):
        result=flow._public(dict(status="running",actor="user",fallback_count=10,job_id="internal"))
        self.assertNotIn("actor",result)
        self.assertNotIn("job_id",result)
        self.assertNotIn("fallback_count",result)

    def test_facts_confirmation_required(self):
        with patch.object(flow,"_access"), patch.object(flow.frappe,"throw",side_effect=ValueError), self.assertRaises(ValueError):
            flow.start("recipe","revision",confirmed=0)

    def test_non_integer_people_rejected(self):
        with patch.object(flow,"_access"), self.assertRaises(ValueError):
            flow.start("recipe","revision",confirmed=1,fallback_count=1.5)

    def test_draft_preview_never_changes_recipe(self):
        doc=MagicMock(is_deleted=False,workflow_status="草稿")
        with patch.object(p,"_read",return_value=doc), patch.object(p.frappe,"get_list",return_value=[]), patch.object(p.frappe,"db",MagicMock(count=MagicMock(return_value=0))), patch.object(p.frappe,"throw",side_effect=ValueError):
            with self.assertRaises(ValueError):
                p._source("recipe",allow_draft=True)
        doc.save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
