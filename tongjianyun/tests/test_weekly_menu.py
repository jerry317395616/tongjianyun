import json
from pathlib import Path
import unittest


class WeeklyMenuMetadataTests(unittest.TestCase):
    def test_sidebar_and_native_report_use_a_script_report(self):
        root = Path(__file__).resolve().parents[1] / "tongjianyun"
        sidebar = json.loads((root / "sidebar/tongjianyun.json").read_text(encoding="utf-8"))
        report = json.loads((root / "report/tongjianyun_weekly_menu/tongjianyun_weekly_menu.json").read_text(encoding="utf-8"))
        self.assertEqual(sidebar["items"][0]["link_to"], report["name"])
        self.assertEqual(report["report_type"], "Script Report")
        self.assertEqual(report["module"], "Tongjianyun")
        self.assertEqual(report["ref_doctype"], "Meal Planning Week")
        self.assertIsNone(report.get("reference_report"))

    def test_report_owns_a_complete_weekly_interface(self):
        path = Path(__file__).resolve().parents[1] / "tongjianyun/report/tongjianyun_weekly_menu/tongjianyun_weekly_menu.js"
        script = path.read_text(encoding="utf-8")
        self.assertIn('const reportName = "Tongjianyun Weekly Menu";', script)
        self.assertIn('frappe.query_reports[reportName]', script)
        self.assertIn('after_datatable_render(datatable)', script)
        self.assertIn('历史供餐人数待确认', script)
