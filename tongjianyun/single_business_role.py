"""Explicit one-time consolidation; Administrator only, caller commits after verification."""
from collections import defaultdict
import frappe
from tongjianyun.business_access import ROLE, PROFILE, BITS

LEGACY = tuple('Tongjianyun ' + suffix for suffix in (
    'Administrator', 'Director', 'Teacher', 'Nutrition', 'Academic', 'Health',
    'Kitchen', 'Procurement', 'Food Safety', 'Finance', 'Service'))


def preview():
    if frappe.session.user != 'Administrator':
        raise frappe.PermissionError('Administrator required')
    permissions = {dt: frappe.get_all(dt, filters={'role': ['in', LEGACY]}, fields=['*'])
                   for dt in ('DocPerm', 'Custom DocPerm')}
    links = frappe.get_all('Has Role', filters={'role': ['in', LEGACY]}, fields=['*'])
    return {'roles': frappe.get_all('Role', filters={'name': ['in', LEGACY]}, fields=['*']),
            'permissions': permissions, 'links': links}


def migrate(business_users):
    data = preview()
    assert set(business_users) == set(frappe.get_all('User Role Profile', filters={'role_profile': PROFILE}, pluck='parent'))
    changed_types=set()
    for dt, rows in data['permissions'].items():
        groups=defaultdict(list)
        for row in rows:groups[(row.parent, row.permlevel or 0, row.if_owner or 0)].append(row)
        for (parent,level,owner), entries in groups.items():
            if not frappe.db.exists('DocType',parent):
                # Retired DocTypes may leave permission rows, not live business records.
                for row in entries:frappe.delete_doc(dt,row.name)
                continue
            existing=frappe.db.get_value(dt, {'parent':parent,'role':ROLE,'permlevel':level,'if_owner':owner})
            doc=frappe.get_doc(dt,existing) if existing else frappe.get_doc({
                'doctype':dt,'parent':parent,'parenttype':'DocType','parentfield':'permissions',
                'role':ROLE,'permlevel':level,'if_owner':owner})
            for bit in BITS:
                doc.set(bit,max([int(doc.get(bit) or 0)]+[int(r.get(bit) or 0) for r in entries]))
            doc.share=0
            doc.save()
            for row in entries:frappe.delete_doc(dt,row.name)
            changed_types.add(parent)
    parents={(r.parenttype,r.parent,r.parentfield) for r in data['links']}
    # Profile first; User.save synchronizes its role table from this profile.
    for dt,name,field in sorted(parents,key=lambda r:r[0]!='Role Profile'):
        doc=frappe.get_doc(dt,name)
        rows=[];seen=set()
        for row in doc.get(field):
            value=row.role
            if value in LEGACY:
                if dt=='User' and name not in business_users:
                    continue  # Do not promote test/service accounts to whole-school business access.
                value=ROLE
            if value in seen:continue
            seen.add(value);row.role=value;rows.append(row)
        doc.set(field,rows)
        doc.save()
    from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype
    for dt in changed_types:
        validate_permissions_for_doctype(dt)
        frappe.clear_cache(doctype=dt)
    for dt in ('Has Role','DocPerm','Custom DocPerm'):
        assert not frappe.db.exists(dt,{'role':['in',LEGACY]}),dt
    deleted=[]
    for role in LEGACY:
        if frappe.db.exists('Role',role):
            frappe.delete_doc('Role',role)
            deleted.append(role)
    frappe.clear_cache()
    return {'deleted_roles':deleted,'permission_types':len(changed_types),'updated_parents':len(parents)}
