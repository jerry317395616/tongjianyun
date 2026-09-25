"""Guard owned workflows before native code can evaluate conditions or tasks.

Document hooks alone run too late: Frappe applies transition tasks before
calling save/submit/cancel. Keep the native implementations, but validate the
owned schema at HTTP entry and reject edits to its fixed Workflow metadata.
Privileged raw SQL / server-code mutation is outside this application boundary.
"""
from __future__ import annotations

import base64
import json

import frappe

from tongjianyun import business_blueprints as bp
from tongjianyun import business_blueprints_v2 as v2


def _owned_spec(doctype):
    """Read the manifest without requiring the Workflow to already exist.

The install creates tables first, then inserts the fixed workflow. Runtime
entry points additionally verify the complete installed bundle below.
"""
    if not isinstance(doctype, str) or not doctype.startswith(bp.OWNED_PREFIXES):
        return None
    meta = frappe.get_meta(doctype, cached=False)
    description = meta.description or ''
    if (doctype.startswith(bp.PREFIX) and description.startswith('Business blueprint ') and not description.startswith(v2.MARKER)
            and not meta.is_submittable and not any(f.fieldtype == 'Table' for f in meta.fields)):
        return None  # Preserve v1 registrations and unrelated native workflows.
    try:
        header, encoded = description.split('\n', 1)
        if not header.startswith(v2.MARKER) or len(encoded) > bp.MAX_BYTES * 2:
            raise ValueError('missing manifest')
        spec = bp.validate_spec(json.loads(base64.b64decode(encoded, altchars=b'-_', validate=True)))
        if (spec.get('version') != 2 or bp.doctype_name(spec) != doctype
                or header != v2.MARKER + bp.revision(spec)):
            raise ValueError('manifest mismatch')
        return spec
    except (ValueError, TypeError, KeyError, UnicodeError):
        frappe.throw('受控复核流程的业务清单不完整，不能修改或执行。')


def _matches(doc, expected):
    keys = ('workflow_name', 'document_type', 'is_active', 'send_email_alert',
            'workflow_state_field', 'override_status')
    if v2._values(doc, keys) != v2._values(expected, keys):
        return False
    if doc.get('name') and doc.name != expected['workflow_name']:
        return False
    for kind, keys in [
        ('states', ('state', 'doc_status', 'allow_edit', 'send_email', 'update_field',
                    'update_value', 'evaluate_as_expression', 'is_optional_state', 'next_action_email_template')),
        ('transitions', ('state', 'action', 'next_state', 'allowed', 'allow_self_approval',
                         'send_email_to_creator', 'condition', 'transition_tasks')),
    ]:
        if [v2._values(row, keys) for row in doc.get(kind) or []] != [v2._values(row, keys) for row in expected[kind]]:
            return False
    return True


def validate_workflow_metadata(doc, method=None):
    """Run before Workflow.validate/set_active, also protecting re-target/delete."""
    targets = {doc.get('document_type')}
    old = doc.get_doc_before_save()
    if old:
        targets.add(old.get('document_type'))
    # on_trash and before_insert do not necessarily have _doc_before_save.
    if doc.get('name') and not doc.is_new():
        targets.add(frappe.db.get_value('Workflow', doc.name, 'document_type'))
    for doctype in targets:
        spec = _owned_spec(doctype)
        if not spec:
            continue
        if method == 'on_trash':
            frappe.throw('受控复核流程不能单独删除；请通过经审核的源码变更处理。')
        expected = v2.workflow_definition(spec)
        if not expected or not _matches(doc, expected):
            frappe.throw('受控复核流程与已确认业务清单不一致，不能修改、停用或添加条件/任务。')


def validate_workflow_child_metadata(doc, method=None):
    """Native client.save can save a child directly, without its parent hook.

Normal parent Workflow persistence uses child db_update, not child save hooks.
Check both the submitted and stored parent so a caller cannot re-parent a row
to evade this guard. Unrelated and v1 workflow rows retain native behavior.
"""
    parents = {doc.get('parent')} if doc.get('parenttype') == 'Workflow' else set()
    if doc.get('name'):
        stored = frappe.db.get_value(doc.doctype, doc.name, ['parent', 'parenttype'], as_dict=True)
        if stored and stored.parenttype == 'Workflow':
            parents.add(stored.parent)
    for parent in parents:
        doctype = frappe.db.get_value('Workflow', parent, 'document_type')
        if _owned_spec(doctype):
            frappe.throw('受控复核流程的状态和流转明细不能单独修改或删除。')


def _guard_doctype(doctype):
    if isinstance(doctype, str) and doctype.startswith((*bp.OWNED_PREFIXES, v2.ROW_PREFIX)):
        return v2._runtime_spec(frappe._dict(doctype=doctype))
    return None


def _guard_doc(doc):
    parsed = frappe.parse_json(doc)
    doctype = parsed.get('doctype') if hasattr(parsed, 'get') else None
    return _guard_doctype(doctype)


@frappe.whitelist(methods=['POST'])
def apply_workflow(doc, action):
    _guard_doc(doc)
    from frappe.model.workflow import apply_workflow as native_apply
    return native_apply(doc, action)


@frappe.whitelist()
def get_transitions(doc, workflow=None, raise_exception=False):
    owned = _guard_doc(doc)
    if owned and workflow is not None:
        frappe.throw('受控业务不能使用临时复核流程。')
    from frappe.model.workflow import get_transitions as native_transitions
    return native_transitions(doc, workflow=workflow, raise_exception=raise_exception)


@frappe.whitelist(methods=['POST'])
def bulk_workflow_approval(docnames, doctype, action):
    _guard_doctype(doctype)
    from frappe.model.workflow import bulk_workflow_approval as native_bulk
    return native_bulk(docnames, doctype, action)
