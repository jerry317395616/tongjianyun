"""Pure catalog adapter tests with the real durable task/scope store.

Native permission/metadata services are explicit in-memory test doubles here,
not fake live evidence. These tests do not open Frappe, Redis, a server or model.
Existing native authority tests and later isolated E2E acceptance remain needed.
"""
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

from tongjianyun import business_agent_catalog as catalog
from tongjianyun.business_agent_tasks import BusinessTaskStore, TaskIdentity, QueueObservation, ExecutionObservation


class ReadSet:
    def __init__(self, scopes):
        self.scopes = tuple(scopes)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.site, self.owner, self.actor = 'qa.localhost', 'user@example.invalid', 'outer-request'
        self.identity = TaskIdentity(self.site, self.owner, str(uuid.uuid4()))
        self.account_enabled = True
        self.apps = {'erpnext', 'education'}
        self.modules = {'Accounts': 'erpnext', 'Stock': 'erpnext', 'Education': 'education'}
        self.blocked = set()
        self.rows = [self.entry('Invoice', 'Accounts'), self.entry('Receipt', 'Stock'),
                     self.entry('Student', 'Education'), self.entry('User', 'Accounts')]
        self.readable = {'Invoice', 'Receipt', 'Student', 'User'}
        self.creatable = {'Invoice', 'Receipt'}
        self.documents = {('Invoice', 'INV-1')}
        self.row_visible = {('Invoice', 'INV-1')}
        self.singles = set()
        self.trace = []
        self.after_catalog = self.before_registration = None
        self.gates = SimpleNamespace(_account=self.account, _projection=self.projection,
            _doctype=self.doctype, _read=self.read_scope,
            _capability=lambda name: {'kind':'capability','name':name}, SCENE='scene:business:v1',
            CATALOG='catalog:business:v1', CONTROL_DOCTYPES={'User', 'DocType', 'Server Script'}, ReadSet=ReadSet)
        self.native = SimpleNamespace(selection=self.selection, module_apps=self.module_apps,
            catalog_entries=Mock(side_effect=self.native_catalog),
            entry_selection=lambda kind, name, choice: {'view':'frappe_'+kind,kind:name,
                **{key:choice[key] for key in ('day','meal') if key in choice}},
            native_view=Mock(side_effect=AssertionError('Do not read unregistered native summary')),
            operation_capabilities=Mock(side_effect=AssertionError('Do not read workflow capabilities')))
        self.frappe = SimpleNamespace(get_installed_apps=lambda: sorted(self.apps))
        self.stack.enter_context(patch.object(catalog, '_services', return_value=(self.frappe,self.gates,self.native)))
        test = self
        class Authority:
            site = test.site
            def run_check(self, owner, callback):
                previous = test.actor
                test.actor = owner
                try:
                    return callback()
                finally:
                    test.actor = previous
            def __call__(self, identity, scopes):
                try:
                    def check():
                        test.account(identity.owner, identity.site)
                        for scope in scopes:
                            test.check_scope(scope)
                        return True
                    return self.run_check(identity.owner, check)
                except PermissionError:
                    return False
            def view_scopes(self, identity, choice):
                def read():
                    test.account(identity.owner,identity.site)
                    scopes = [{'kind':'view','selection':choice}]
                    if choice['view']=='frappe_catalog':
                        scopes.append(test.gates._capability(test.gates.CATALOG))
                    else:
                        scopes.append(test.read_scope(choice['doctype']))
                        if choice['view']=='frappe_document':
                            scopes.append(test.read_scope(choice['doctype'],choice['document']))
                        if choice['view']=='frappe_new':
                            scopes.append({'kind':'doctype','doctype':choice['doctype'],'actions':['create','read']})
                    for scope in scopes:
                        test.check_scope(scope)
                    return tuple(scopes)
                return self.run_check(identity.owner,read)
            def register_read(self, store, claim, read_set):
                test.trace.append('register')
                if test.before_registration:
                    callback,test.before_registration=test.before_registration,None
                    callback()
                if not self(claim.identity,read_set.scopes):
                    raise PermissionError('revoked before data publication')
                store.register_authorities(claim,read_set.scopes)
                store.binding_state(claim)
        self.authority = Authority()
        self.store = BusinessTaskStore(directory,self.site,authorize=self.authority,
            observe_queue=lambda job:QueueObservation(job,'present'),
            observe_execution=lambda identity,claim:ExecutionObservation(claim,'running',0))
        self.store.create(self.owner,self.identity.task_id,'Find my available business',{'day':'2026-09-17','meal':'lunch'})
        ticket=self.store.take_dispatch(self.identity)
        self.store.acknowledge_dispatch(ticket)
        self.claim=self.store.claim(self.identity,ticket.job_id)
        self.reader=catalog.BusinessCatalog(self.authority,self.store)

    @staticmethod
    def entry(name,module):
        return {'kind':'doctype','name':name,'module':module,'title':'合成 '+name,'note':'native metadata'}

    @staticmethod
    def read_scope(name, document=None):
        return {'kind':'document' if document else 'doctype','doctype':name,'actions':['read'],
                **({'document':document} if document else {})}

    def account(self,owner,site):
        if not self.account_enabled or owner!=self.owner or site!=self.site or self.actor!=owner:
            raise PermissionError('wrong account context')

    def projection(self,name):
        self.account(self.owner,self.site)
        if name not in {self.gates.SCENE,self.gates.CATALOG}:
            raise PermissionError('unknown metadata capability')

    def module_apps(self):
        self.account(self.owner,self.site)
        return {module:app for module,app in self.modules.items() if app in self.apps and module not in self.blocked}

    def doctype(self,name,actions):
        self.account(self.owner,self.site)
        if name in self.gates.CONTROL_DOCTYPES or name not in self.readable or ('create' in actions and name not in self.creatable):
            raise PermissionError('native type denied')
        row=next(row for row in self.rows if row['name']==name)
        if row['module'] not in self.module_apps():
            raise PermissionError('module not available')
        return SimpleNamespace(name=name,module=row['module'],issingle=name in self.singles)

    def check_scope(self,scope):
        kind=scope['kind']
        if kind=='capability':
            self.projection(scope['name'])
        elif kind in {'doctype','document'}:
            self.doctype(scope['doctype'],scope['actions'])
            if kind=='document' and ((scope['doctype'],scope['document']) not in self.documents
                                    or (scope['doctype'],scope['document']) not in self.row_visible):
                raise PermissionError('original record or list/row permission denied')
        elif kind=='view':
            choice=scope['selection']
            if choice['view']=='frappe_catalog':
                if choice.get('kind')!='doctype':
                    raise PermissionError('unaudited native kind')
                if choice.get('app') and choice['app'] not in self.apps:
                    raise PermissionError('not installed')
                if choice.get('module') and choice['module'] not in self.module_apps():
                    raise PermissionError('module denied')
            else:
                self.doctype(choice['doctype'],['read'])
        else:
            raise PermissionError('unknown source type')

    def selection(self,choice,day,meal):
        self.account(self.owner,self.site)
        result={key:value for key,value in choice.items() if key!='view'}
        result.setdefault('day',day)
        result.setdefault('meal',meal)
        if choice['view']=='frappe_catalog':
            result.setdefault('offset',0)
        return result

    def native_catalog(self,choice,modules):
        self.account(self.owner,self.site)
        self.assertEqual(choice['kind'],'doctype')
        self.trace.append('catalog')
        rows=[dict(row) for row in self.rows if row['module'] in modules and row['name'] in self.readable
              and (not choice.get('keyword') or choice['keyword'].casefold() in (row['name']+' '+row['title']).casefold())]
        if self.after_catalog:
            callback,self.after_catalog=self.after_catalog,None
            callback()
        return rows

    def read(self,**args):
        return self.reader.dispatch(self.claim,'business_catalog_read',args)

    def view(self,**choice):
        return self.reader.dispatch(self.claim,'business_view',{'selection':choice})

    def test_all_installed_business_not_only_classroom_and_no_control_types(self):
        result=self.read()
        self.assertEqual([row['doctype'] for row in result['entries']],['Student','Invoice','Receipt'])
        self.assertEqual(result['visible_entry_count'],3)
        self.assertNotIn('User',str(result))
        self.assertIn('不是业务记录',result['scope'])
        self.assertEqual(self.actor,'outer-request')
        self.native.catalog_entries.assert_called_once()
        self.assertEqual(self.trace,['catalog','register'])

    def test_page_plus_lookahead_registered_before_result(self):
        result=self.read(page_size=1)
        self.assertTrue(result['has_more'])
        self.assertIsNone(result['visible_entry_count'])
        scopes=self.store.required_scopes(self.identity)
        self.assertIn(self.read_scope('Student'),scopes)
        self.assertIn(self.read_scope('Invoice'),scopes)
        self.assertNotIn(self.read_scope('Receipt'),scopes)
        self.assertFalse(any(event['kind']=='view' for event in self.store.events(self.identity)))

    def test_keyset_next_pages_never_invent_global_counts(self):
        first=self.read(page_size=1)
        second=self.read(page_size=1,cursor=first['next_cursor'])
        third=self.read(page_size=1,cursor=second['next_cursor'])
        self.assertEqual(second['entries'][0]['doctype'],'Invoice')
        self.assertEqual(third['entries'][0]['doctype'],'Receipt')
        self.assertIsNone(second['visible_entry_count'])
        self.assertIsNone(third['visible_entry_count'])
        self.assertFalse(third['has_more'])
        self.assertIsNone(third['next_cursor'])

    def test_cursor_contains_only_delivered_key_and_is_bound_to_filters(self):
        result=self.read(page_size=1)
        key=catalog._decode_cursor(result['next_cursor'],catalog._filter_digest({}))
        self.assertEqual(key,('education','Education','Student'))
        with self.assertRaises(ValueError):
            self.read(keyword='Invoice',cursor=result['next_cursor'])

    def test_current_native_filtering_and_installed_module_boundaries(self):
        self.readable.remove('Invoice')
        self.assertEqual([r['doctype'] for r in self.read(app='erpnext')['entries']],['Receipt'])
        with self.assertRaises(PermissionError):
            self.read(app='source_only_not_installed')
        with self.assertRaises(PermissionError):
            self.read(app='education',module='Stock')

    def test_disabled_module_is_not_exposed(self):
        self.blocked.add('Stock')
        result=self.read()
        self.assertNotIn('Receipt',str(result))

    def test_empty_visible_catalog_is_entry_zero_not_business_zero(self):
        self.readable.clear()
        result=self.read()
        self.assertEqual(result['visible_entry_count'],0)
        self.assertFalse(result['has_more'])
        self.assertEqual(result['entries'],[])
        self.assertTrue(any(scope['kind']=='capability' for scope in self.store.required_scopes(self.identity)))

    def test_keyword_reuses_native_catalog_search_not_separate_module_inventory(self):
        result=self.read(keyword='Invoice')
        self.assertEqual(result['entries'][0]['doctype'],'Invoice')
        self.assertEqual(self.native.catalog_entries.call_args.args[0]['keyword'],'Invoice')

    def test_source_revoked_after_query_prevents_data_delivery(self):
        self.after_catalog=lambda:self.readable.remove('Student')
        with self.assertRaises(PermissionError):
            self.read(page_size=1)
        self.assertNotIn('register',self.trace)

    def test_lookahead_permission_revoked_prevents_has_more_leak(self):
        self.before_registration=lambda:self.readable.remove('Invoice')
        with self.assertRaises(PermissionError):
            self.read(page_size=1)
        self.assertNotIn(self.read_scope('Student'),self.store.required_scopes(self.identity))

    def test_old_registered_source_rechecked_before_next_result(self):
        self.read(page_size=1)
        self.readable.remove('Student')
        with self.assertRaises(PermissionError):
            self.read(keyword='Receipt')

    def test_budget_exhausted_is_not_an_empty_catalog_or_partial_source_set(self):
        with patch.object(catalog,'MAX_SCOPES',3):
            result=self.read()
        self.assertFalse(result['available'])
        self.assertEqual(result['error'],'scope_budget_exhausted')
        self.assertNotIn('entries',result)
        self.assertNotIn('visible_entry_count',result)
        self.native.catalog_entries.assert_not_called()

    def test_budget_shrinks_page_and_keeps_complete_lookahead(self):
        with patch.object(catalog,'MAX_SCOPES',5):
            result=self.read(page_size=30)
        self.assertEqual(result['page_count'],1)
        self.assertTrue(result['budget_limited'])
        self.assertIn(self.read_scope('Invoice'),self.store.required_scopes(self.identity))

    def test_doc_view_publishes_only_selection_and_registers_record_scope(self):
        result=self.view(view='frappe_document',doctype='Invoice',document='INV-1')
        self.assertTrue(result['display_requested'])
        self.assertFalse(result['executed_business_operation'])
        self.assertIn(self.read_scope('Invoice','INV-1'),self.store.required_scopes(self.identity))
        event=self.store.events(self.identity)[-1]
        self.assertEqual(event['kind'],'view')
        self.assertEqual(set(event),{'id','kind','version','selection','title'})
        self.assertEqual(event['selection']['document'],'INV-1')
        self.assertNotIn('route',result)
        self.native.native_view.assert_not_called()
        self.native.operation_capabilities.assert_not_called()

    def test_document_permission_does_not_bypass_list_row_restriction(self):
        self.row_visible.clear()
        with self.assertRaises(PermissionError):
            self.view(view='frappe_document',doctype='Invoice',document='INV-1')
        self.assertFalse(any(e['kind']=='view' for e in self.store.events(self.identity)))

    def test_new_form_requires_create_permission_but_never_saves(self):
        result=self.view(view='frappe_new',doctype='Invoice')
        self.assertTrue(result['display_requested'])
        self.assertFalse(result['executed_business_operation'])
        with self.assertRaises(PermissionError):
            self.view(view='frappe_new',doctype='Student')

    def test_single_and_weekly_recipe_new_forms_use_existing_workflow(self):
        self.singles.add('Invoice')
        with self.assertRaises(PermissionError):
            self.view(view='frappe_new',doctype='Invoice')
        self.rows.append(self.entry('Tongjianyun Recipe','Stock'))
        self.readable.add('Tongjianyun Recipe')
        self.creatable.add('Tongjianyun Recipe')
        with self.assertRaises(PermissionError):
            self.view(view='frappe_new',doctype='Tongjianyun Recipe')

    def test_native_catalog_view_forces_doctype_kind(self):
        result=self.view(view='frappe_catalog',app='erpnext')
        self.assertEqual(result['selection']['kind'],'doctype')
        self.assertEqual(self.store.events(self.identity)[-1]['selection']['kind'],'doctype')

    def test_control_types_denied_on_direct_native_view(self):
        for view in ('frappe_doctype','frappe_new','frappe_document'):
            with self.assertRaises(PermissionError):
                self.view(view=view,doctype='User',**({'document':self.owner} if view=='frappe_document' else {}))

    def test_view_budget_failure_does_not_publish(self):
        with patch.object(catalog,'MAX_SCOPES',1):
            result=self.view(view='frappe_doctype',doctype='Invoice')
        self.assertFalse(result['available'])
        self.assertFalse(any(e['kind']=='view' for e in self.store.events(self.identity)))

    def test_revoke_between_scope_registration_and_emit_prevents_publish(self):
        self.before_registration=lambda:setattr(self,'account_enabled',False)
        with self.assertRaises(PermissionError):
            self.view(view='frappe_doctype',doctype='Invoice')

    def test_forged_identity_cross_site_and_cancelled_claim_are_denied(self):
        with self.assertRaises(PermissionError):
            self.reader.dispatch(replace(self.claim,identity=replace(self.identity,site='other.localhost')),'business_catalog_read',{})
        with self.assertRaises(PermissionError):
            self.reader.dispatch(replace(self.claim,identity=replace(self.identity,owner='other@example.invalid')),'business_catalog_read',{})
        self.store.cancel(self.identity)
        with self.assertRaises(PermissionError):
            self.read()

    def test_unexpected_native_kind_or_duplicate_source_is_not_silently_trusted(self):
        self.rows.append(dict(self.rows[0]))
        with self.assertRaises(ValueError):
            self.read()
        self.rows.pop()
        self.rows[0]['kind']='report'
        with self.assertRaises(ValueError):
            self.read()


class SchemaTests(unittest.TestCase):
    def test_received_inbox_is_exact_navigation_not_a_native_data_view(self):
        choice = {'view': 'business_proposal_inbox', 'folder': 'received'}
        clean = catalog._arguments('business_view', {'selection': choice})['selection']
        self.assertEqual(clean, dict(choice, state='pending'))
        self.assertNotIn('state', choice)
        self.assertNotIn('business_proposal_inbox', catalog.NATIVE_VIEWS)
        page = dict(choice, state='all', cursor=str(uuid.uuid4()))
        self.assertEqual(catalog._arguments('business_view', {'selection': page})['selection'], page)
        self.assertIn('business_proposal_inbox', catalog.TOOL_INSTRUCTIONS['business_view'])

    def test_received_inbox_does_not_admit_identity_actions_or_other_proposal_views(self):
        choice = {'view': 'business_proposal_inbox', 'folder': 'received'}
        invalid = [dict(choice, **{name: value}) for name, value in (
            ('owner', 'Administrator'), ('site', 'other.localhost'), ('recipient', 'other@example.invalid'),
            ('actor', 'Administrator'), ('method', 'accept_handoff'), ('activate', True),
            ('day', '2026-09-21'), ('meal', 'lunch'), ('cursor', 'not-a-canonical-uuid'),
            ('state', 'accepted'), ('folder', 'sent'))]
        invalid += [{'view': 'business_proposal_inbox'},
                    {'view': 'business_proposal_handoff', 'handoff_id': str(uuid.uuid4())},
                    {'view': 'business_blueprint', 'proposal_id': 'FILE-1'}]
        for selection in invalid:
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                catalog._arguments('business_view', {'selection': selection})

    def test_no_actor_execution_schema_upload_or_arbitrary_view(self):
        for args in ({'owner':'Administrator'},{'site':'elsewhere'},{'kind':'report'},
                     {'page_size':True},{'page_size':31},{'cursor':'0-0'},{'keyword':'   '}):
            with self.assertRaises(ValueError):
                catalog._arguments('business_catalog_read',args)
        for selection in ({'view':'project_catalog'},{'view':'frappe_report','report':'General Ledger'},
            {'view':[]},{'view':'frappe_catalog','meal':[]},
            {'view':'frappe_catalog','kind':'page'},{'view':'frappe_catalog','owner':'Administrator'},
            {'view':'frappe_catalog','offset':True},{'view':'frappe_doctype','doctype':'User','html':'<script>'},
            {'view':'frappe_doctype'},{'view':'frappe_document','doctype':'Invoice'},
            {'view':'frappe_new','doctype':'Invoice','method':'submit'}):
            with self.assertRaises(ValueError):
                catalog._arguments('business_view',{'selection':selection})
        with self.assertRaises(ValueError):
            catalog._arguments('business_view',{'selection':{'view':'frappe_catalog'},'publish':False})

    def test_arguments_finite_bounded_and_unknown_tool_rejected(self):
        for tool,args in (('os.system',{}),('business_catalog_read',{'keyword':'x'*9000}),
                          ('business_catalog_read',{'page_size':float('nan')}),('business_view',[])):
            with self.assertRaises(ValueError):
                catalog._arguments(tool,args)

    def test_cursor_rejects_wrong_revision_schema_and_noncanonical_encoding(self):
        filters=catalog._filter_digest({})
        cursor=catalog._encode_cursor(('erpnext','Stock','Receipt'),filters)
        self.assertEqual(catalog._decode_cursor(cursor,filters),('erpnext','Stock','Receipt'))
        for invalid in (cursor+'=',cursor+'\n','x',catalog._encode_cursor(('erpnext','Stock','Receipt'),'b'*64)):
            with self.assertRaises(ValueError):
                catalog._decode_cursor(invalid,filters)


if __name__=='__main__':
    unittest.main()
