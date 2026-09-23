"""Teacher entry and server-side scope regression; no production writes."""
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import frappe
from frappe import _dict
from tongjianyun import workspace_entry as entry, classroom
from tongjianyun.www import tongjianyun_entry as page


def assignment(groups=1, employee=True, instructor=True, readable=True):
    return {"employee_linked": employee, "instructor_linked": instructor,
            "class_linked": bool(groups), "can_read_classroom": readable,
            "groups": [{"name": "C"+str(i+1), "student_group_name": "测试班"+str(i+1)} for i in range(groups)]}


def model(groups=1, multi=False):
    a = assignment(groups)
    return {**a, "profiles": entry.choose_profiles("teacher", {"Instructor", *( ["System Manager"] if multi else [])}, a, True)}


class EntryClassificationTests(unittest.TestCase):
    def test_business_operator_is_not_a_teacher_or_director(self):
        result = entry.choose_profiles("operator", ["Tongjianyun Business Operator"], assignment(0, False, False), True)
        self.assertEqual([p["id"] for p in result], ["business"])
        self.assertNotIn("园长", str(result))

    def test_assignment_plus_business_base_role_defaults_to_teacher(self):
        result = entry.choose_profiles("teacher", ["Tongjianyun Business Operator"], assignment(), True)
        self.assertEqual([p["id"] for p in result], ["teacher"])

    def test_explicit_teacher_without_assignment_needs_setup(self):
        result = entry.choose_profiles("teacher", ["Instructor"], assignment(0, False, False), False)
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["enabled"])
        self.assertIn("员工", result[0]["description"])

    def test_no_read_permission_disables_teacher(self):
        a = assignment(0, readable=False)
        result = entry.choose_profiles("teacher", ["Instructor"], a, True)
        self.assertFalse(result[0]["enabled"])
        self.assertIn("读取权限", result[0]["description"])

    def test_teacher_with_management_or_health_can_choose(self):
        for role in ["System Manager", "Education Manager", "Tongjianyun Health Manager"]:
            with self.subTest(role=role):
                choices = entry.choose_profiles("teacher", ["Instructor", role], assignment(), True)
                self.assertEqual([p["id"] for p in choices], ["teacher", "business"])

    def test_no_route_for_unavailable_existing_page(self):
        choices = entry.choose_profiles("teacher", ["Instructor", "Tongjianyun Health Manager"], assignment(), False)
        self.assertEqual([p["id"] for p in choices], ["teacher"])

    def test_admin_without_assignment_keeps_workbench(self):
        choices = entry.choose_profiles("Administrator", ["System Manager"], assignment(0, False, False), True)
        self.assertEqual([p["id"] for p in choices], ["business"])

    def test_unknown_identity_cannot_get_teacher_by_name(self):
        self.assertEqual(entry.choose_profiles("张老师", [], assignment(0, False, False), False), [])


class EntryRoutingTests(unittest.TestCase):
    def test_single_class_direct_route(self):
        result = entry.resolve_entry(model())
        url = urlparse(result["destination"])
        self.assertEqual(url.path, "/tongjianyun-classroom")
        self.assertEqual(parse_qs(url.query), {"workspace": ["teacher"], "class": ["C1"]})

    def test_multiple_classes_require_choice(self):
        result = entry.resolve_entry(model(2))
        self.assertIsNone(result["destination"])
        self.assertEqual(result["view"], "classes")

    def test_multiple_identities_require_choice(self):
        result = entry.resolve_entry(model(1, multi=True))
        self.assertIsNone(result["destination"])
        self.assertEqual(result["view"], "profiles")

    def test_multiple_identities_still_explain_unconfigured_teacher(self):
        result = entry.resolve_entry(model(0, multi=True))
        self.assertIsNone(result["destination"])
        self.assertEqual(result["view"], "profiles")

    def test_forced_choice_does_not_auto_open_single_class(self):
        self.assertEqual(entry.resolve_entry(model(), choose=True)["view"], "classes")

    def test_foreign_or_revoked_class_is_rejected(self):
        for m in [model(), model(0)]:
            with self.assertRaises(frappe.PermissionError):
                entry.resolve_entry(m, "teacher", "FOREIGN")

    def test_unknown_identity_and_open_redirect_rejected(self):
        for profile in ["Administrator", "health", "https://evil.example", "//evil.example"]:
            with self.assertRaises(frappe.PermissionError):
                entry.resolve_entry(model(), profile)

    def test_class_identifier_is_encoded_as_data(self):
        m = model()
        m["groups"][0]["name"] = "班一/?next=https://evil.example#x&role=admin"
        result = entry.resolve_entry(m)
        url = urlparse(result["destination"])
        self.assertEqual(url.path, "/tongjianyun-classroom")
        self.assertEqual(set(parse_qs(url.query)), {"class", "workspace"})

    def test_business_keeps_old_route_without_loop(self):
        m = {"profiles": [{"id":"business","enabled":True}], "groups": []}
        self.assertEqual(entry.resolve_entry(m)["destination"], entry.WORKBENCH)

    def test_disabled_teacher_gets_setup_screen(self):
        self.assertEqual(entry.resolve_entry(model(0), "teacher")["view"], "setup")

    def test_redirect_is_temporary_not_301(self):
        with patch.object(entry.frappe.local, "flags", _dict()):
            with self.assertRaises(frappe.Redirect) as caught:
                entry.temporary_redirect("/tongjianyun-classroom?workspace=teacher&class=C1")
            self.assertEqual(caught.exception.http_status_code, 303)


class AssignmentTests(unittest.TestCase):
    def test_only_current_user_active_chain_and_permission_filtered_classes(self):
        with patch.object(entry, "require_account"), patch.object(entry.frappe, "session", _dict(user="teacher")), \
                patch.object(entry.frappe, "has_permission", return_value=True), \
                patch.object(entry.frappe, "get_all", side_effect=[["E1"], ["I1"], ["C1", "C2", "C1"]]) as get_all, \
                patch.object(entry.frappe, "get_list", return_value=[_dict(name="C1", student_group_name="班一")]) as get_list:
            result = entry.teaching_assignment()
            self.assertEqual([g["name"] for g in result["groups"]], ["C1"])
            self.assertEqual(get_all.call_args_list[0].kwargs["filters"], {"user_id":"teacher", "status":"Active"})
            self.assertEqual(get_all.call_args_list[1].kwargs["filters"], {"employee":["in",["E1"]],"status":"Active"})
            self.assertEqual(get_all.call_args_list[2].kwargs["filters"]["parenttype"], "Student Group")
            self.assertEqual(get_all.call_args_list[2].kwargs["filters"]["parentfield"], "instructors")
            self.assertEqual(get_list.call_args.kwargs["filters"], {"name":["in",["C1","C2"]],"disabled":0})

    def test_no_employee_never_queries_unbounded_classes(self):
        with patch.object(entry, "require_account"), patch.object(entry.frappe, "get_all", return_value=[]), \
                patch.object(entry.frappe, "has_permission", return_value=True), patch.object(entry.frappe, "get_list") as read:
            self.assertEqual(entry.teaching_assignment()["groups"], [])
            read.assert_not_called()

    def test_missing_read_permission_never_reads_class_labels(self):
        with patch.object(entry, "require_account"), patch.object(entry.frappe, "get_all", side_effect=[["E"],["I"],["C"]]), \
                patch.object(entry.frappe, "has_permission", return_value=False), patch.object(entry.frappe, "get_list") as read:
            self.assertFalse(entry.teaching_assignment()["can_read_classroom"])
            read.assert_not_called()

    def test_guest_disabled_and_website_accounts_rejected(self):
        for user, account in [("Guest", None), ("off",_dict(enabled=0,user_type="System User")), ("parent",_dict(enabled=1,user_type="Website User"))]:
            with patch.object(entry.frappe, "session", _dict(user=user)), patch.object(entry.frappe.db, "get_value", return_value=account):
                with self.assertRaises(frappe.PermissionError): entry.require_account()


class TeacherScopeTests(unittest.TestCase):
    def test_teacher_intersection_does_not_use_broad_manager_groups(self):
        with patch.object(entry, "teacher_groups", return_value=["C1"]), patch.object(classroom, "allowed_groups") as broad:
            self.assertEqual(classroom._groups("teacher"), ["C1"])
            broad.assert_not_called()

    def test_old_business_workspace_keeps_original_permission_logic(self):
        with patch.object(classroom, "allowed_groups", return_value=["C1","C2"]):
            self.assertEqual(classroom._groups(), ["C1","C2"])
            self.assertEqual(classroom._groups("business"), ["C1","C2"])

    def test_unknown_workspace_rejected(self):
        with self.assertRaises(frappe.PermissionError): classroom._groups("admin")

    def test_foreign_group_rejected_before_document_read(self):
        with patch.object(classroom, "require_user"), patch.object(entry, "teacher_groups", return_value=["C1"]), patch.object(classroom.frappe, "get_doc") as read:
            with self.assertRaises(frappe.PermissionError): classroom._scope("C2", "teacher")
            read.assert_not_called()

    def test_empty_teacher_scope_returns_empty_not_first_visible_class(self):
        with patch.object(classroom, "require_user"), patch.object(classroom, "_groups", return_value=[]), \
                patch.object(classroom, "today", return_value="2026-09-23"), patch.object(classroom, "now_datetime", return_value="2026-09-23 10:00:00"), \
                patch.object(classroom.frappe.db, "get_value", return_value="老师"), patch.object(classroom, "_scope") as scope:
            result = classroom.get_overview(workspace="teacher")
            self.assertEqual(result["workspace"], "teacher")
            self.assertIsNone(result["group"])
            self.assertEqual(result["groups"], [])
            scope.assert_not_called()

    def test_all_teacher_writes_validate_scope_first(self):
        calls = [
            lambda: classroom.save_attendance("C2","2026-09-23",[],"rev", workspace="teacher"),
            lambda: classroom.add_record("C2","S2","2026-09-23","General","观察", workspace="teacher"),
            lambda: classroom.save_health("C2","2026-09-23",{}, workspace="teacher"),
            lambda: classroom.save_meals("C2","2026-09-23",[], workspace="teacher"),
            lambda: classroom.get_meals("C2","2026-09-23", workspace="teacher"),
            lambda: classroom.get_health("C2","2026-09-23", workspace="teacher"),
        ]
        for invoke in calls:
            with patch.object(classroom, "_scope", side_effect=frappe.PermissionError) as scope, \
                    patch("tongjianyun.student_meals.save_class_meals") as save:
                with self.assertRaises(frappe.PermissionError): invoke()
                self.assertEqual(scope.call_args.args, ("C2", "teacher"))
                save.assert_not_called()

    def test_meal_read_does_not_leak_other_group_index(self):
        payload = {"record":{"student_group":"C1"},"revision":"r","expected":{},"actual":{},"groups":[{"name":"SECRET-C2"}]}
        with patch.object(classroom, "_scope", return_value=_dict(name="C1")), patch("tongjianyun.student_meals.get_class_meals", return_value=payload):
            result = classroom.get_meals("C1","2026-09-23",workspace="teacher")
            self.assertEqual(set(result), {"record","revision","expected","actual"})
            self.assertNotIn("SECRET-C2", str(result))

    def test_meal_save_delegates_without_overriding_validation(self):
        with patch.object(classroom, "_scope", return_value=_dict(name="C1")), patch.object(classroom, "_capabilities", return_value={"meals_write":True}), patch("tongjianyun.student_meals.save_class_meals") as save:
            result=classroom.save_meals("C1","2026-09-23",[{"student":"S1"}],"r",1,"核对",workspace="teacher")
            save.assert_called_once_with("2026-09-23","C1",[{"student":"S1"}],"r",1,"核对")
            self.assertTrue(result["saved"])

    def test_locked_meals_do_not_write(self):
        with patch.object(classroom, "_scope"), patch.object(classroom, "_capabilities", return_value={"meals_write":False}), patch("tongjianyun.student_meals.save_class_meals") as save:
            with self.assertRaises(frappe.PermissionError): classroom.save_meals("C1","2026-09-23",[],workspace="teacher")
            save.assert_not_called()


class EntryPageTests(unittest.TestCase):
    def test_personal_entry_response_headers_are_private_and_not_json_payload(self):
        with patch.object(entry.frappe.local, "response_headers", {"Vary":"Accept-Encoding"}, create=True):
            entry.mark_private_response()
            self.assertIn("no-store", frappe.local.response_headers["Cache-Control"])
            self.assertEqual(set(frappe.local.response_headers["Vary"].split(", ")), {"Accept-Encoding","Cookie"})

    def test_guest_returns_to_fixed_gateway_not_supplied_external_url(self):
        with patch.object(page.frappe, "session", _dict(user="Guest")), patch.object(entry, "mark_private_response"), patch.object(entry, "entry_model") as read, patch.object(page.frappe.local, "flags", _dict()):
            with self.assertRaises(frappe.Redirect): page.get_context(_dict())
            destination = frappe.local.flags.redirect_location
            self.assertEqual(parse_qs(urlparse(destination).query)["redirect-to"], [entry.ENTRY])
            read.assert_not_called()

    def test_roles_are_derived_not_taken_from_request(self):
        m = {**model(), "checks":{}, "business_available":False, "user_label":"老师"}
        with patch.object(page.frappe, "session", _dict(user="teacher")), patch.object(entry,"mark_private_response"), patch.object(entry,"entry_model", return_value=m), patch.object(page.frappe,"form_dict", _dict(role="Administrator",user="other",next="https://evil.example")), patch.object(page.frappe.local,"flags",_dict()):
            with self.assertRaises(frappe.Redirect): page.get_context(_dict())
            self.assertTrue(frappe.local.flags.redirect_location.startswith(entry.CLASSROOM+"?"))
            self.assertNotIn("evil",frappe.local.flags.redirect_location)

    def test_picker_rechecks_current_permissions_each_request(self):
        m = {**model(0), "checks":{}, "business_available":False, "user_label":"老师"}
        with patch.object(page.frappe,"session",_dict(user="teacher")), patch.object(entry,"mark_private_response"), patch.object(entry,"entry_model",return_value=m), patch.object(page.frappe,"form_dict",_dict(profile="teacher", **{"class":"C1"})):
            with self.assertRaises(frappe.PermissionError): page.get_context(_dict())


if __name__ == "__main__":
    unittest.main()
