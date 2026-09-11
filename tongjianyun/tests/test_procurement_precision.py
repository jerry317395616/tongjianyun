import unittest
from unittest.mock import MagicMock, patch
from tongjianyun import procurement_precision as p
from tongjianyun import recipe_execution as e


class PrecisionTests(unittest.TestCase):
    def test_only_instance_quantities_change(self):
        row=MagicMock()
        row._precision={"main":{"rate":2}}
        doc=MagicMock()
        doc._precision={"items":{"rate":2}}
        doc.get.return_value=[row]
        p.apply_precision(doc)
        self.assertEqual(doc._precision["items"]["qty"],9)
        self.assertEqual(row._precision["main"]["qty"],9)
        self.assertEqual(doc._precision["items"]["rate"],2)
        self.assertEqual(row._precision["main"]["rate"],2)
        doc.save.assert_not_called()

    def test_other_material_requests_untouched(self):
        doc=MagicMock(doctype="Material Request",title="Other purchase")
        with patch.object(p,"apply_precision") as apply:
            p.before_validate(doc)
            apply.assert_not_called()

    def test_same_revision_restores_user_defaults(self):
        with patch.object(e,"_access"), patch.object(e.procurement,"default_scope",return_value={"company":"C"}), patch.object(e.procurement,"prepare",return_value={"ingredients":[],"meals":[]}), patch.object(e,"source_snapshot",return_value={"revision":"V1"}), patch.object(e,"_latest",return_value={"revision":"V1","fallback_count":23,"include_history":1}), patch.object(e,"status",return_value={}):
            result=e.inspect("R")
        self.assertEqual(result["fallback_count"],23)
        self.assertEqual(result["include_history"],1)

    def test_changed_revision_does_not_reuse_old_numbers(self):
        with patch.object(e,"_access"), patch.object(e.procurement,"default_scope",return_value={"company":"C"}), patch.object(e.procurement,"prepare",return_value={"ingredients":[],"meals":[]}), patch.object(e,"source_snapshot",return_value={"revision":"V2"}), patch.object(e,"_latest",return_value={"revision":"V1","fallback_count":23,"include_history":1}), patch.object(e,"status",return_value={}):
            result=e.inspect("R")
        self.assertIsNone(result["fallback_count"])
        self.assertEqual(result["include_history"],0)

    def test_html_error_is_readable_text(self):
        self.assertEqual(e._public({"message":"超出 <strong>0.4</strong> 克"})["message"], "超出  0.4  克")
