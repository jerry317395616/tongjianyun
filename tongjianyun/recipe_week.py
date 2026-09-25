"""One current recipe per site/calendar week; archived records are history.

The existing Recipe model is site-wide (it has no campus field). Serialize
writes on its DocType row until commit/rollback, including the empty-week case.
No Redis lease or process-local mutex can protect that database invariant.
"""
from datetime import timedelta

import frappe
from frappe.utils import getdate

RECIPE = 'Tongjianyun Recipe'


def lock_recipe_writes():
    frappe.db.sql('SELECT `name` FROM `tabDocType` WHERE `name` = %s FOR UPDATE', (RECIPE,))


def week_bounds(start, end):
    if not start or not end:
        frappe.throw('请填写食谱的开始和结束日期。')
    start, end = getdate(start), getdate(end)
    monday = start - timedelta(days=start.weekday())
    sunday = monday + timedelta(days=6)
    if not start <= end <= sunday:
        frappe.throw('一份食谱只能属于同一自然周（周一至周日），请按周分别编排。')
    return monday, sunday


def validate_weekly_recipe(doc):
    if doc.get('is_deleted') or doc.get('workflow_status') == '已归档':
        return
    monday, sunday = week_bounds(doc.week_start, doc.week_end)
    lock_recipe_writes()
    # Locking reads see the latest commit even under REPEATABLE READ.
    conflicts = frappe.db.sql('''SELECT `name` FROM `tabTongjianyun Recipe`
        WHERE COALESCE(`is_deleted`, 0) = 0
          AND COALESCE(`workflow_status`, '') != '已归档'
          AND `week_start` <= %s AND COALESCE(`week_end`, `week_start`) >= %s
          AND `name` != %s LIMIT 1 FOR UPDATE''', (sunday, monday, doc.name or ''))
    if conflicts:
        # Do not disclose a potentially unreadable recipe's identity or contents.
        frappe.throw(f'{monday} 这一周已有食谱。请编辑本周现有食谱，不要新建或另存副本；'
                     '如有历史重复记录，请先确认保留哪一份并将其余归档。')
