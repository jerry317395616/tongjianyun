"""Preserve cancelled asset history during native acquisition cancellation.

Frappe's class extension keeps Purchase Receipt/Invoice controllers, permission
checks, cancellation links, stock and GL methods intact. Only their inherited
asset-cleanup helpers differ: cancelled documents are history, not disposable
auto-created drafts. No new RPC or permission bypass is introduced.
"""
import frappe
from frappe import _
from frappe.model.delete_doc import check_permission_and_not_submitted
from frappe.utils import get_link_to_form


class PreserveAssetHistory:
    def _asset_acquisition_cancellation(self):
        return self.doctype in {'Purchase Receipt', 'Purchase Invoice'} and self.docstatus == 2

    def delete_linked_asset(self):
        if not self._asset_acquisition_cancellation():
            return super().delete_linked_asset()
        if self.doctype == 'Purchase Invoice' and not self.get('update_stock'):
            return
        # The native helper uses reference_name alone and can pick an unrelated
        # acquisition type or a cancelled Transfer. Never delete that history.
        movement = frappe.db.get_value('Asset Movement', {
            'reference_doctype': self.doctype, 'reference_name': self.name,
            'docstatus': ['!=', 2],
        }, 'name')
        if movement:
            # Keep the native permission and submitted-document rejection.
            frappe.delete_doc('Asset Movement', movement, force=1)

    def update_fixed_asset(self, field, delete_asset=False):
        if not delete_asset or not self._asset_acquisition_cancellation():
            return super().update_fixed_asset(field, delete_asset=delete_asset)
        expected = 'purchase_receipt' if self.doctype == 'Purchase Receipt' else 'purchase_invoice'
        if field != expected:
            frappe.throw(_('Asset acquisition reference does not match the source document.'))
        # This narrow cancellation branch follows BuyingController's normal
        # cleanup/detach behavior, but checks cancelled history BEFORE auto-delete.
        for row in self.get('items'):
            if not row.is_fixed_asset:
                continue
            automatic = frappe.db.get_value('Item', row.item_code, 'auto_create_assets')
            assets = frappe.get_all('Asset', filters={field: self.name, 'item_code': row.item_code})
            for record in assets:
                asset = frappe.get_doc('Asset', record.name)
                if asset.docstatus == 1:
                    # Same prerequisite as the native manual-asset branch. In
                    # auto-create mode native delete_doc also rejects submission;
                    # rejecting here avoids deleting anything before that check.
                    frappe.throw(_(
                        'Cannot cancel this document as it is linked with the submitted asset {asset_link}. '
                        'Please cancel the asset to continue.'
                    ).format(asset_link=get_link_to_form('Asset', asset.name)))
                movements = list(dict.fromkeys(frappe.get_all('Asset Movement Item',
                    filters={'asset': asset.name}, pluck='parent', limit_page_length=0))) if automatic else []
                if movements:
                    submitted = frappe.db.get_value('Asset Movement', {
                        'name': ['in', movements], 'docstatus': 1,
                    }, 'name')
                    if submitted:
                        # Native automatic cleanup refuses a submitted movement,
                        # even if its Asset has already been cancelled. Keep that
                        # exact permission/status check without deleting history.
                        check_permission_and_not_submitted(frappe.get_doc('Asset Movement', submitted))
                if asset.docstatus == 2:
                    continue
                has_history = bool(movements and frappe.db.exists('Asset Movement', {
                    'name': ['in', movements], 'docstatus': 2,
                }))
                if automatic and not has_history:
                    for movement in movements:
                        frappe.delete_doc('Asset Movement', movement, force=1)
                    frappe.delete_doc('Asset', asset.name, force=1)
                    continue
                # Preserve even a draft Asset when it has cancelled movement
                # history. Detach the cancelled acquisition like native manual
                # drafts; the historical movement keeps its immutable source link.
                asset.set(field, None)
                asset.supplier = None
                asset.flags.ignore_validate_update_after_submit = True
                asset.flags.ignore_mandatory = True
                asset.flags.ignore_validate = True
                asset.save()
