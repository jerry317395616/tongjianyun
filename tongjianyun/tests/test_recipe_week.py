import unittest
from copy import deepcopy
from datetime import date
from unittest.mock import patch, MagicMock

import frappe
from frappe import _dict
from tongjianyun import recipe_week as week, recipe_storage as storage


class RecipeWeekTests(unittest.TestCase):
    def test_calendar_week_not_rolling_seven_days(self):
        self.assertEqual(week.week_bounds('2026-09-23', '2026-09-25'), (date(2026,9,21), date(2026,9,27)))
        for start,end in [('2026-09-25','2026-09-28'), ('2026-09-23','2026-09-22'), (None,None)]:
            with patch.object(frappe, 'throw', side_effect=ValueError), self.assertRaises(ValueError):
                week.week_bounds(start,end)

    def test_week_conflict_is_locked_and_does_not_disclose_record(self):
        doc=_dict(name='R',week_start='2026-09-23',week_end='2026-09-25',workflow_status='草稿')
        with patch.object(frappe.db,'sql',side_effect=[[],[('private-recipe',)]]) as query, patch.object(frappe,'throw',side_effect=ValueError):
            with self.assertRaises(ValueError) as error:week.validate_weekly_recipe(doc)
            self.assertNotIn('private-recipe',str(error.exception))
            self.assertIn('FOR UPDATE',query.call_args_list[0].args[0])
            self.assertIn('FOR UPDATE',query.call_args_list[1].args[0])
            self.assertEqual(query.call_args_list[1].args[1], (date(2026,9,27),date(2026,9,21),'R'))

    def test_archive_does_not_compete_with_current_week_but_restoring_does(self):
        doc=_dict(name='OLD',week_start='2026-09-21',week_end='2026-09-25',workflow_status='已归档')
        with patch.object(frappe.db,'sql',return_value=[('CURRENT',)]) as query,patch.object(frappe,'throw',side_effect=ValueError):
            week.validate_weekly_recipe(doc);query.assert_not_called()
            doc.workflow_status='草稿'
            with self.assertRaises(ValueError):week.validate_weekly_recipe(doc)

    def test_missing_or_stale_revision_rejected_before_any_recipe_write(self):
        doc=MagicMock(name='document');doc.name='R';doc.modified='new';doc.get.return_value=False
        for revision in ['', 'old']:
            with patch.object(storage,'_require_recipe_write'),patch.object(week,'lock_recipe_writes'), \
                 patch.object(frappe.db,'exists',return_value='R'),patch.object(frappe.db,'get_value',return_value='new'), \
                 patch.object(frappe,'get_doc',return_value=doc),patch.object(frappe,'throw',side_effect=ValueError),patch.object(storage,'_save_doc') as save:
                with self.assertRaises(ValueError):
                    storage.save_recipe_payload({'recipe':{'recipeId':'R','weekStart':'2026-09-21','weekEnd':'2026-09-25','revision':revision}})
                save.assert_not_called()

    def test_locked_day_cannot_be_changed_or_removed(self):
        doc=MagicMock();doc.name='R';doc.modified='v1';doc.week_start='2026-09-21';doc.week_end='2026-09-25';doc.get.return_value=False
        old={'date':'2026-09-21','locked':True,'portions':[{'slot':'lunch','dishes':['米饭'],'dishIngredientRows':[]}]}
        changed=deepcopy(old);changed['portions'][0]['dishes']=['粥']
        for days in [[],[changed]]:
            with patch.object(storage,'_require_recipe_write'),patch.object(week,'lock_recipe_writes'), \
                 patch.object(frappe.db,'exists',return_value='R'),patch.object(frappe.db,'get_value',return_value='v1'), \
                 patch.object(frappe,'get_doc',return_value=doc),patch.object(frappe,'throw',side_effect=ValueError), \
                 patch.object(storage,'_current_recipe_payload',return_value={'days':[old]}),patch.object(storage,'_save_doc') as save:
                with self.assertRaises(ValueError):
                    storage.save_recipe_payload({'recipe':{'recipeId':'R','weekStart':'2026-09-21','weekEnd':'2026-09-25','revision':'v1'},'days':days})
                save.assert_not_called()
