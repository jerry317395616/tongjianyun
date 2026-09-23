"""Navigation compatibility only. No database writes or permission changes."""
import unittest
from unittest.mock import patch

import frappe
from frappe import _dict
from tongjianyun import legacy_entry as service


class LegacyEntryTests(unittest.TestCase):
    def invoke(self, path='/desk/tongjianyun-workbench', method='GET', user='teacher', profiles=None):
        model = {'profiles': profiles if profiles is not None else [{'id':'teacher','enabled':True}]}
        with patch.object(service.frappe.local, 'request', _dict(path=path,method=method), create=True), \
             patch.object(service.frappe, 'session', _dict(user=user)), \
             patch.object(service, 'entry_model', return_value=model) as load, \
             patch.object(service, 'mark_private_response') as private, \
             patch.object(service, 'temporary_redirect') as redirect:
            service.redirect_legacy_teacher_page(_dict())
            return load, private, redirect

    def test_assigned_teacher_redirects_to_fixed_entry(self):
        _, private, redirect=self.invoke()
        private.assert_called_once()
        redirect.assert_called_once_with('/tongjianyun-entry')

    def test_trailing_slash_is_compatible(self):
        self.invoke(path='/desk/tongjianyun-workbench/')[2].assert_called_once()

    def test_unassigned_teacher_goes_to_existing_setup_not_another_class(self):
        self.invoke(profiles=[{'id':'teacher','enabled':False}])[2].assert_called_once_with('/tongjianyun-entry')

    def test_manager_preserves_original_workbench(self):
        self.invoke(user='Administrator',profiles=[{'id':'business','enabled':True}])[2].assert_not_called()

    def test_dual_role_preserves_original_workbench(self):
        self.invoke(profiles=[{'id':'teacher','enabled':True},{'id':'business','enabled':True}])[2].assert_not_called()

    def test_unknown_identity_is_not_promoted(self):
        self.invoke(profiles=[])[2].assert_not_called()

    def test_guest_remains_in_native_login_flow(self):
        load, _, redirect=self.invoke(user='Guest')
        load.assert_not_called(); redirect.assert_not_called()

    def test_head_request_uses_same_private_redirect(self):
        self.invoke(method='HEAD')[2].assert_called_once()

    def test_writes_are_never_redirected(self):
        for method in ('POST','PUT','PATCH','DELETE'):
            with self.subTest(method=method):
                load, _, redirect=self.invoke(method=method)
                load.assert_not_called(); redirect.assert_not_called()

    def test_other_pages_and_api_remain_unchanged(self):
        for path in ('/apps','/desk','/tongjianyun-entry','/tongjianyun-classroom',
                     '/desk/tongjianyun-recipe-workbench','/api/method/frappe.desk.desk_page.getpage',
                     '/desk/tongjianyun-workbench-something'):
            with self.subTest(path=path):
                load, _, redirect=self.invoke(path=path)
                load.assert_not_called(); redirect.assert_not_called()
