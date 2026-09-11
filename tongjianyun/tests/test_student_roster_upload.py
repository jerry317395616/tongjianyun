import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from frappe import _dict
from tongjianyun import student_roster_upload as r


class RosterUploadTests(unittest.TestCase):
    def test_title_and_alias_headers(self):
        self.assertEqual(r.header_map([['幼儿园名单'], [], ['幼儿姓名','出生日期','班级']]), (2,{0:'student_name',1:'date_of_birth',2:'class_name'},False))

    def test_duplicate_headers_rejected(self):
        with self.assertRaises(ValueError):
            r.header_map([['姓名','学生姓名']])

    def test_csv_chinese_encoding(self):
        self.assertEqual(r.read_sheets('姓名,班级\n样例,小班'.encode('gb18030'),'a.csv')[0][1][1],['样例','小班'])

    def test_file_limits(self):
        for content, name in [(b'x'* (5*1024*1024+1),'a.csv'), (b'', 'a.exe')]:
            with self.assertRaises(ValueError): r.read_sheets(content,name)

    def test_dates_do_not_infer_age(self):
        for value in ['3岁', '01/02/03', '2022年9月', '=TODAY()']:
            with self.assertRaises(ValueError): r.normalize({'student_name':'样例','date_of_birth':value})
        with patch.object(r,'nowdate',return_value='2026-09-11'):
            self.assertEqual(r.normalize({'student_name':'样例','date_of_birth':'2022年9月1日'})['date_of_birth'],'2022-09-01')

    def test_unknown_fields_not_imported(self):
        self.assertEqual(r.normalize({'student_name':'样例','enabled':0,'roles':'System Manager'}),{'student_name':'样例'})

    def test_summary_and_multiline_are_not_students(self):
        for name in ['合计', '共20人', '张三\n李四']:
            with self.assertRaises(ValueError): r.normalize({'student_name':name})

    def test_model_invalid_column_rejected(self):
        with patch.object(r.HeaderClient,'_bounded',AsyncMock(return_value={'header':0,'columns':[{'column':10,'field':'student_name'}]})):
            with self.assertRaises(ValueError): r.header_map([['幼儿的名字']],use_ai=True)

    def test_ai_receives_labels_not_student_rows(self):
        model=AsyncMock(return_value={'header':0,'columns':[{'column':0,'field':'student_name'}]})
        with patch.object(r.HeaderClient,'_bounded',model):
            r.header_map([['幼儿的名字'],['模拟儿童'],['13812345678']],use_ai=True)
        payload=model.call_args.args[0]
        self.assertNotIn('模拟儿童',payload)
        self.assertNotIn('13812345678',payload)

    def test_name_only_match_requires_review(self):
        with patch.object(r.frappe,'get_all',return_value=[_dict(name='ST1',date_of_birth='2022-09-01')]):
            with self.assertRaises(ValueError): r.assess({'student_name':'样例'},[])

    def test_existing_identity_is_not_overwritten(self):
        student=MagicMock(enabled=1)
        student.get.side_effect=lambda field: {'student_name':'原名','date_of_birth':'2022-09-01'}.get(field)
        with patch.object(r.frappe,'get_all',side_effect=[['ST1'],[]]),patch.object(r.frappe,'get_doc',return_value=student):
            with self.assertRaises(ValueError): r.assess({'student_name':'新名','student_id':'ST1'},[])

    def test_missing_class_not_guessed(self):
        with patch.object(r.frappe,'get_all',return_value=[]):
            with self.assertRaises(ValueError): r.assess({'student_name':'样例','date_of_birth':'2022-09-01'},[])

    def test_age_suggestion_only_when_enabled(self):
        group=MagicMock(academic_year='2026-2027',max_strength=0)
        groups=[_dict(name='中班',student_group_name='中班',academic_year='2026-2027')]
        with patch.object(r.frappe,'get_all',return_value=[]),patch.object(r.frappe,'get_doc',return_value=group),patch.object(r,'nowdate',return_value='2026-09-11'):
            result=r.assess({'student_name':'样例','date_of_birth':'2022-09-01'},groups,auto_age=True)
            self.assertEqual(result['group'],'中班')
            self.assertEqual(result['action'],'create')

    def test_task_owned_by_actor(self):
        with patch.object(r,'_access'),patch.object(r.frappe,'cache') as cache,patch.object(r.frappe,'session',_dict(user='B')),patch.object(r.frappe,'throw',side_effect=ValueError):
            cache.get_value.return_value={'actor':'A'}
            with self.assertRaises(ValueError): r._load('a'*32)

    def test_no_metadata_or_permission_bypass(self):
        from pathlib import Path
        source=Path(r.__file__).read_text()
        for forbidden in ['ignore_permissions=True', 'ignore_mandatory', 'db.sql(', 'Custom Field', 'Property Setter']:
            self.assertNotIn(forbidden,source)


if __name__ == '__main__': unittest.main()
