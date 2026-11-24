import importlib.util
import json
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class Row(SimpleNamespace):
    def get(self, key):
        return getattr(self, key, None)


class TermProjectTests(unittest.TestCase):
    def setUp(self):
        self.frappe = SimpleNamespace(db=Mock(), get_all=Mock(), whitelist=lambda **kwargs: lambda fn: fn)
        utils = SimpleNamespace(escape_html=str, get_url_to_form=lambda *args: "/", getdate=self.to_date)
        common = SimpleNamespace(**{key: key for key in ("CANTEEN", "DAY", "TASK", "TERM", "WEEK")},
                                 dates=Mock(), company_doc=Mock(), linked=Mock(), lock_company=Mock(),
                                 permission=Mock(), require=Mock(), submitted=Mock())
        spec = importlib.util.spec_from_file_location("term_projects_test", Path(__file__).parents[1] / "canteen_ops/term_projects.py")
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "frappe": self.frappe, "frappe.utils": utils, "tongjianyun.canteen_ops.common": common,
        }):
            timetable_spec = importlib.util.spec_from_file_location("tongjianyun.canteen_ops.term_schedule",
                Path(__file__).parents[1] / "canteen_ops/term_schedule.py")
            self.schedule = importlib.util.module_from_spec(timetable_spec)
            timetable_spec.loader.exec_module(self.schedule)
            menu_spec = importlib.util.spec_from_file_location("tongjianyun.canteen_ops.task_menus",
                Path(__file__).parents[1] / "canteen_ops/task_menus.py")
            self.menus = importlib.util.module_from_spec(menu_spec)
            menu_spec.loader.exec_module(self.menus)
            with patch.dict(sys.modules, {timetable_spec.name: self.schedule, menu_spec.name: self.menus}):
                spec.loader.exec_module(self.module)
        self.term = SimpleNamespace(company="School", canteen="Kitchen", from_date="2026-11-25", to_date="2026-12-04")

    @staticmethod
    def to_date(value):
        return date.fromisoformat(value) if isinstance(value, str) else value

    def test_weeks_include_partial_first_and_last_week(self):
        weeks = self.schedule.build_weeks(self.term.from_date, self.term.to_date, {date(2026, 11, 27)})
        self.assertEqual(list(weeks), [date(2026, 11, 23), date(2026, 11, 30)])
        self.assertEqual(weeks[date(2026, 11, 23)]["days"], [date(2026, 11, 25), date(2026, 11, 26)])
        self.assertEqual(weeks[date(2026, 11, 30)]["due"]["准备采购"], date(2026, 11, 26))
        self.assertFalse(self.schedule.build_weeks("2026-11-28", "2026-12-01", {date(2026, 11, 30), date(2026, 12, 1)}))

    def test_submit_links_one_native_project_with_term_details(self):
        self.term.name = "TERM-1"
        self.term.project_title = "春季学期膳食"
        self.term.responsible_user = "manager@example.invalid"
        self.term.management_project = None
        self.frappe.get_doc = Mock()
        self.frappe.get_doc.return_value.insert.return_value.name = "PROJECT-1"

        self.module.attach_management_project(self.term)
        self.module.attach_management_project(self.term)

        self.assertEqual(self.term.management_project, "PROJECT-1")
        self.frappe.get_doc.assert_called_once_with({
            "doctype": "Project", "project_name": "春季学期膳食 · TERM-1", "company": "School",
            "expected_start_date": "2026-11-25", "expected_end_date": "2026-12-04",
            "percent_complete_method": "Task Completion",
            self.module.PROJECT_RESPONSIBLE: "manager@example.invalid",
        })
        self.frappe.get_doc.return_value.insert.assert_called_once_with(ignore_permissions=True)

    def test_submit_reuses_selected_project(self):
        self.term.management_project = "EXISTING-PROJECT"
        self.frappe.get_doc = Mock()

        self.module.attach_management_project(self.term)

        self.assertEqual(self.term.management_project, "EXISTING-PROJECT")
        self.frappe.get_doc.assert_not_called()

    def test_completion_comes_from_the_business_stage(self):
        week = SimpleNamespace(docstatus=0, kitchen_reconciled=False, kitchen_reconciled_at=None, procurement_snapshot=None)
        self.assertFalse(any(done for done, _ in self.module._week_steps(week, set(), "MR-1", 5)))
        week.docstatus = 1
        steps = self.module._week_steps(week, {1, 2}, "MR-1", 5)
        self.assertEqual(steps, [(True, "已审核"), (True, "已生成申请"), (False, "已日结 2/5 天"), (False, "待核销")])
        week.kitchen_reconciled, week.kitchen_reconciled_at = True, "2026-11-30 10:00:00"
        week.procurement_snapshot = json.dumps({"basis_hash": "frozen", "rows": [{"status": "covered"}]})
        steps = self.module._week_steps(week, set(range(5)), None, 5)
        self.assertTrue(all(done for done, _ in steps))
        self.assertEqual(steps[1], (True, "无需采购"))
        self.assertFalse(self.module._covered_by_stock('{"basis_hash":"x","rows":[{"status":"purchase","purchase_qty":"1"}]}'))
        self.assertFalse(self.module._covered_by_stock('{"rows":[]}'))

    def test_resolves_only_a_unique_compatible_canteen_or_confirmed_owner(self):
        a = Row(name="A", raw_warehouse="Raw", kitchen_warehouse="K1")
        b = Row(name="B", raw_warehouse="Raw", kitchen_warehouse="K2")
        w = Row(name="W", raw_material_warehouse="Raw", kitchen_warehouse=None, custom_tjy_canteen=None)
        resolve = lambda canteen, tasks: self.menus.resolve(canteen, [a, b], [w], tasks)
        self.assertEqual(resolve("A", []), (None, [w]))
        w.kitchen_warehouse = "K1"
        self.assertEqual(resolve("A", []), (w, [w]))
        self.assertEqual(resolve("B", []), (None, []))
        w.kitchen_warehouse = None
        task = Row(meal_week="W", canteen="A", docstatus=0, menu_confirmed=1)
        self.assertEqual(resolve("A", [task]), (w, [w]))
        self.assertEqual(resolve("B", [task]), (None, []))
        w.custom_tjy_canteen = "B"
        self.assertEqual(resolve("A", []), (None, []))

    def test_multiple_menus_need_a_choice_and_never_modify_submitted_tasks(self):
        monday = date(2026, 11, 23)
        site = Row(name="A", raw_warehouse="Raw", kitchen_warehouse="K")
        menus = [Row(name=n, raw_material_warehouse="Raw", kitchen_warehouse=None) for n in ("W1", "W2")]
        rows = [Row(name=str(i), docstatus=0, canteen="A", menu_confirmed=0, meal_week=None) for i in range(4)]
        rows.append(Row(name="historical", docstatus=1, canteen="A", menu_confirmed=0, meal_week="old"))
        scope = object.__new__(self.menus.WeekMenus)
        scope.sites, scope.weeks, scope.tasks = [site], {monday: menus}, {monday: rows}
        self.assertEqual(scope.match("A", monday), (None, menus))
        scope.apply(monday, confirmation=("A", "W2"))
        self.assertEqual(scope.match("A", monday), (menus[1], menus))
        self.assertEqual([c.args[1] for c in self.frappe.db.set_value.call_args_list], ["0", "1", "2", "3"])
        self.frappe.db.set_value.reset_mock()
        scope.weeks[monday] = []
        scope.apply(monday)
        self.assertEqual([c.args[1] for c in self.frappe.db.set_value.call_args_list], ["0", "1", "2", "3"])
        self.assertTrue(all(c.args[2]["meal_week"] is None for c in self.frappe.db.set_value.call_args_list))
