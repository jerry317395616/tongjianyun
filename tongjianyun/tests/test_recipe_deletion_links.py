import unittest
from unittest.mock import MagicMock, patch

from frappe import _dict

from tongjianyun import recipe_storage as service


class DeletionLinksTests(unittest.TestCase):
    def recipe(self):
        return _dict(
            name="R1",
            recipe_id="R1",
            title="Recipe",
            week_start=None,
            week_end=None,
            workflow_status="已归档",
            is_deleted=0,
        )

    def test_no_procurement_allows_delete(self):
        doc = self.recipe()
        with patch.object(service, "_doctype_available", return_value=True),              patch.object(service.frappe, "db", MagicMock()) as db,              patch.object(service.frappe, "get_all", return_value=[]),              patch.object(service, "_can_restore_recipe", return_value=True):
            db.table_exists.return_value = True
            self.assertEqual(service._recipe_business_links(doc), [])
            self.assertTrue(service._recipe_actions(doc)["can_delete"])

    def test_erpnext_procurement_chain_blocks_deletion(self):
        doc = self.recipe()

        def get_all(doctype, *args, **kwargs):
            if doctype == "Material Request":
                self.assertEqual(
                    kwargs["filters"]["title"],
                    service.PROCUREMENT_REQUEST_TITLE_PREFIX + "R1",
                )
                return ["MR1", "MR2"]
            if doctype == "Purchase Order Item":
                return ["PO1", "PO1", "PO2"]
            if doctype == "Purchase Receipt Item":
                return ["PR1"]
            if doctype == "Purchase Invoice Item":
                return ["PI1", "PI2"]
            return []

        with patch.object(service, "_doctype_available", return_value=True),              patch.object(service.frappe, "db", MagicMock()) as db,              patch.object(service.frappe, "get_all", side_effect=get_all):
            db.table_exists.return_value = True
            links = service._recipe_business_links(doc)

        self.assertEqual(
            links,
            [
                {"doctype": "Material Request", "label": "采购需求", "count": 2},
                {"doctype": "Purchase Order", "label": "采购订单", "count": 2},
                {"doctype": "Purchase Receipt", "label": "采购收货", "count": 1},
                {"doctype": "Purchase Invoice", "label": "采购发票", "count": 2},
            ],
        )
        self.assertFalse(service._recipe_actions(doc, links)["can_delete"])


if __name__ == "__main__":
    unittest.main()
