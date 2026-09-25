"""No database writes: spy on native entry points before any workflow task."""
import copy
import unittest
from unittest.mock import MagicMock, patch

import frappe

from tongjianyun import business_blueprint_workflow as guard
from tongjianyun import business_blueprints as bp
from tongjianyun import business_blueprints_v2 as v2
from tongjianyun.tests.test_business_blueprints_v2 import SPEC


class WorkflowDoc(dict):
    __getattr__ = dict.get

    def get_doc_before_save(self):
        return self.get('_before')

    def is_new(self):
        return not self.get('name')


class BlueprintWorkflowGuardTests(unittest.TestCase):
    def setUp(self):
        self.spec = bp.validate_spec(SPEC)
        self.dt = bp.doctype_name(self.spec)
        self.record = {'doctype': self.dt, 'name': 'synthetic-only'}

    def test_invalid_manifest_blocks_native_apply_before_any_task(self):
        with patch.object(v2, '_runtime_spec', side_effect=frappe.ValidationError('manifest invalid')), \
             patch('frappe.model.workflow.apply_workflow') as native:
            with self.assertRaises(frappe.ValidationError):
                guard.apply_workflow(self.record, '扩展·复核通过')
            native.assert_not_called()

    def test_invalid_manifest_blocks_transition_conditions_and_bulk_queue(self):
        with patch.object(v2, '_runtime_spec', side_effect=frappe.ValidationError('workflow drift')), \
             patch('frappe.model.workflow.get_transitions') as transitions, \
             patch('frappe.model.workflow.bulk_workflow_approval') as bulk:
            with self.assertRaises(frappe.ValidationError):
                guard.get_transitions(self.record)
            with self.assertRaises(frappe.ValidationError):
                guard.bulk_workflow_approval(['synthetic-only'], self.dt, '扩展·复核通过')
            transitions.assert_not_called()
            bulk.assert_not_called()

    def test_valid_owned_record_is_checked_before_delegating_unchanged_native_arguments(self):
        order = []
        with patch.object(v2, '_runtime_spec', side_effect=lambda _: order.append('guard') or self.spec), \
             patch('frappe.model.workflow.apply_workflow', side_effect=lambda *args: order.append('native') or 'native-result') as native:
            self.assertEqual(guard.apply_workflow(self.record, '扩展·送审'), 'native-result')
            native.assert_called_once_with(self.record, '扩展·送审')
        self.assertEqual(order, ['guard', 'native'])

    def test_unrelated_native_workflows_keep_original_semantics_and_do_not_read_blueprint_metadata(self):
        record = {'doctype': 'Purchase Order', 'name': 'synthetic-only'}
        with patch.object(v2, '_runtime_spec') as runtime, \
             patch('frappe.model.workflow.apply_workflow', return_value='apply') as apply, \
             patch('frappe.model.workflow.get_transitions', return_value='transitions') as transitions, \
             patch('frappe.model.workflow.bulk_workflow_approval', return_value='bulk') as bulk:
            self.assertEqual(guard.apply_workflow(record, 'Submit'), 'apply')
            self.assertEqual(guard.get_transitions(record, workflow='native-value', raise_exception=True), 'transitions')
            self.assertEqual(guard.bulk_workflow_approval(['synthetic-only'], 'Purchase Order', 'Submit'), 'bulk')
            transitions.assert_called_once_with(record, workflow='native-value', raise_exception=True)
            runtime.assert_not_called()
            self.assertEqual(apply.call_count, 1)
            self.assertEqual(bulk.call_count, 1)

    def test_owned_transitions_reject_caller_supplied_workflow_before_native_evaluation(self):
        with patch.object(v2, '_runtime_spec', return_value=self.spec), \
             patch.object(frappe, 'throw', side_effect=frappe.ValidationError), \
             patch('frappe.model.workflow.get_transitions') as native:
            with self.assertRaises(frappe.ValidationError):
                guard.get_transitions(self.record, workflow={'condition': 'unexpected'})
            native.assert_not_called()

    def test_manifest_is_validated_without_requiring_already_installed_workflow(self):
        meta = frappe._dict(description=v2.manifest(self.spec), is_submittable=1, fields=[])
        with patch.object(frappe, 'get_meta', return_value=meta), patch.object(v2, 'state') as state:
            self.assertEqual(guard._owned_spec(self.dt), self.spec)
            state.assert_not_called()
        with patch.object(frappe, 'get_meta', return_value=frappe._dict(description='missing', is_submittable=1, fields=[])), \
             patch.object(frappe, 'throw', side_effect=frappe.ValidationError):
            with self.assertRaises(frappe.ValidationError):
                guard._owned_spec(self.dt)

    def test_fixed_workflow_can_be_initially_inserted_but_tasks_conditions_and_permission_drift_cannot(self):
        expected = v2.workflow_definition(self.spec)
        with patch.object(guard, '_owned_spec', return_value=self.spec), \
             patch.object(frappe, 'throw', side_effect=frappe.ValidationError):
            guard.validate_workflow_metadata(WorkflowDoc(expected), 'before_insert')
            for mutate in [lambda d: d['transitions'][0].update(transition_tasks='unexpected'),
                           lambda d: d['transitions'][0].update(condition='True'),
                           lambda d: d['states'][0].update(update_field='title', update_value='unexpected'),
                           lambda d: d['transitions'][0].update(allowed='Guest'),
                           lambda d: d.update(is_active=0),
                           lambda d: d.update(override_status=1)]:
                doc = WorkflowDoc(copy.deepcopy(expected))
                mutate(doc)
                with self.subTest(doc=doc), self.assertRaises(frappe.ValidationError):
                    guard.validate_workflow_metadata(doc, 'before_validate')

    def test_retargeting_or_deleting_owned_workflow_is_blocked_using_old_binding(self):
        expected = v2.workflow_definition(self.spec)
        doc = WorkflowDoc({**expected, 'name': expected['workflow_name'], 'document_type': 'Purchase Order',
                           '_before': {'document_type': self.dt}})
        with patch.object(guard, '_owned_spec', side_effect=lambda dt: self.spec if dt == self.dt else None), \
             patch.object(frappe, 'db', MagicMock()), patch.object(frappe, 'throw', side_effect=frappe.ValidationError):
            with self.assertRaises(frappe.ValidationError):
                guard.validate_workflow_metadata(doc, 'before_validate')
            with self.assertRaises(frappe.ValidationError):
                guard.validate_workflow_metadata(WorkflowDoc(expected), 'on_trash')

    def test_v1_and_unrelated_metadata_are_left_unchanged(self):
        meta = frappe._dict(description='Business blueprint old-v1\nTitle', is_submittable=0, fields=[])
        with patch.object(frappe, 'get_meta', return_value=meta):
            self.assertIsNone(guard._owned_spec(bp.PREFIX + 'old_v1'))
        with patch.object(guard, '_owned_spec', return_value=None), patch.object(frappe, 'db', MagicMock()):
            guard.validate_workflow_metadata(WorkflowDoc(document_type='Purchase Order'), 'before_insert')

    def test_direct_native_workflow_child_writes_and_reparenting_are_blocked(self):
        row = frappe._dict(doctype='Workflow Transition', name='synthetic-row',
                           parent='unrelated-workflow', parenttype='Workflow')
        def lookup(doctype, name, *args, **kwargs):
            if doctype == 'Workflow Transition':
                return frappe._dict(parent='owned-workflow', parenttype='Workflow')
            return self.dt if name == 'owned-workflow' else 'Purchase Order'
        with patch.object(frappe, 'db', MagicMock()) as db, \
             patch.object(guard, '_owned_spec', side_effect=lambda dt: self.spec if dt == self.dt else None), \
             patch.object(frappe, 'throw', side_effect=frappe.ValidationError):
            db.get_value.side_effect = lookup
            for event in ('before_insert', 'before_validate', 'on_trash'):
                with self.subTest(event=event), self.assertRaises(frappe.ValidationError):
                    guard.validate_workflow_child_metadata(row, event)

    def test_unrelated_workflow_child_is_untouched(self):
        with patch.object(frappe, 'db', MagicMock()) as db, patch.object(guard, '_owned_spec', return_value=None):
            db.get_value.return_value = 'Purchase Order'
            guard.validate_workflow_child_metadata(frappe._dict(doctype='Workflow Transition',
                parenttype='Workflow', parent='native-workflow'), 'before_insert')

    def test_hooks_cover_metadata_lifecycle_and_all_native_http_workflow_entries(self):
        from tongjianyun import hooks
        for method in ('apply_workflow', 'get_transitions', 'bulk_workflow_approval'):
            self.assertEqual(hooks.override_whitelisted_methods['frappe.model.workflow.' + method],
                             'tongjianyun.business_blueprint_workflow.' + method)
        for event in ('before_insert', 'before_validate', 'on_trash'):
            self.assertEqual(hooks.doc_events['Workflow'][event],
                             'tongjianyun.business_blueprint_workflow.validate_workflow_metadata')
            for child in ('Workflow Transition', 'Workflow Document State'):
                self.assertEqual(hooks.doc_events[child][event],
                                 'tongjianyun.business_blueprint_workflow.validate_workflow_child_metadata')
