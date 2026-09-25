"""One-shot native recipe save acceptance on the existing isolated QA site.

Default prepare is READ ONLY. Explicit run + UUID retains every synthetic
recipe, native Version, task ledger and evidence. The fixed empty week is
2037-01-05 through 2037-01-11; no existing week/recipe may be adopted. Original
account permissions are required; missing permissions STOP, never grant roles.
Default actor is the teacher; --owner manager explicitly selects ONLY the
already existing synthetic QA manager. Its success is not teacher authority.

The fixture has named synthetic dishes but deliberately NO ingredient rows.
The original ingredient-sync empty-source check therefore blocks scheduling.
This tests native draft saves/history/conflicts, not ingredient matching,
model execution, RQ, HTTP, browser or production. No cleanup or retry exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_worker_live as worker_check

qa, fixture = worker_check.qa, worker_check.fixture
OWNER = fixture.TEACHER
MANAGER = 'browser-manager-02e16a31d7@example.invalid'
ACTORS = {'teacher': OWNER, 'manager': MANAGER}
DAY, END = '2037-01-05', '2037-01-11'
SOURCE_FILES = tuple(dict.fromkeys((*worker_check.SOURCE_FILES,
    'tongjianyun/business_agent_recipes.py', 'tongjianyun/business_agent_writes.py',
    'tongjianyun/business_agent_write_adapter.py', 'tongjianyun/meal_scene.py',
    'tongjianyun/recipe_storage.py', 'tongjianyun/recipe_week.py',
    'tongjianyun/recipe_item_sync.py', 'deploy/business_codex/check_recipe_native.py')))


def canonical(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('Canonical run UUID required')
    return value


def folder(run_id):
    return qa.safe_target(qa.ROOT / ('business-recipe-native-' + canonical(run_id)))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     default=str, allow_nan=False).encode()).hexdigest()


def source_hashes():
    return {name: qa.digest_file(qa.SOURCE / name) for name in SOURCE_FILES}


def environment():
    if os.name != 'posix' or os.geteuid() == 0 or sys.flags.optimize:
        raise PermissionError('Existing non-root Linux site user required')
    if Path(__file__).resolve() != qa.SOURCE / 'deploy/business_codex/check_recipe_native.py':
        raise PermissionError('Only the reviewed candidate script is allowed')
    fixture.fixture_guard()
    return qa.runtime()


def private_new(path, value):
    qa.safe_target(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    if os.name == 'posix':
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def payload(run_id, version):
    canonical(run_id)
    if version not in (1, 2, 3):
        raise ValueError('Only the three reviewed synthetic payloads are allowed')
    return {'recipe': {'title': 'SYNTHETIC QA ' + run_id, 'weekStart': DAY, 'weekEnd': END},
            'days': [{'date': DAY, 'day': 'Monday', 'portions': [{'slot': 'lunch',
                'dishes': ['Synthetic dish version ' + str(version)], 'dishIngredientRows': []}]}]}


def account_guard(frappe, owner):
    if owner not in ACTORS.values() or frappe.local.site != qa.SITE or frappe.session.user != owner:
        raise PermissionError('Only the two fixed existing synthetic QA actors are allowed')
    if owner == OWNER:
        fixture.account_guard(frappe)
        return
    account = frappe.db.get_value('User', owner, ['enabled', 'user_type'], as_dict=True)
    assigned = {row.role for row in frappe.get_doc('User', owner).roles}
    if (not account or account.enabled != 1 or account.user_type != 'System User'
            or assigned != {'System Manager', 'Academics User'}):
        raise PermissionError('Existing synthetic QA manager identity or roles changed')


def week_names(frappe, *, current=False):
    # QA-only global existence check, including deleted/archived/invisible rows.
    # This never grants a model or browser permission to see their content.
    # Only the trusted write guard, AFTER lock_recipe_writes, requests a
    # current locking read. Prepare and independent readback stay READ ONLY.
    if type(current) is not bool:
        raise ValueError('Trusted boolean read mode required')
    rows = frappe.db.sql('''SELECT name FROM `tabTongjianyun Recipe`
        WHERE week_start <= %s AND COALESCE(week_end, week_start) >= %s
        ORDER BY name LIMIT 1001''' + (' FOR UPDATE' if current else ''), (END, DAY))
    if len(rows) > 1000:
        raise PermissionError('Bounded QA week diagnostic exceeded')
    return [row[0] for row in rows]


def assert_empty_target(frappe, *, current=False):
    if week_names(frappe, current=current):
        raise PermissionError('Synthetic week already contains records; never adopt or overwrite them')
    if current:
        dishes = frappe.db.sql('''SELECT name FROM `tabTongjianyun Recipe Dish`
            WHERE meal_date BETWEEN %s AND %s LIMIT 1 FOR UPDATE''', (DAY, END))
    else:
        dishes = frappe.db.exists('Tongjianyun Recipe Dish', {'meal_date': ['between', [DAY, END]]})
    if dishes:
        raise PermissionError('Synthetic week already contains records; never adopt or overwrite them')


def baseline(frappe):
    """Read-only QA digest of all recipe aggregates and their Version records.

    Global metadata diagnostics do not imply user-visible access. Raw bodies
    never enter evidence. This is not a whole-site database baseline.
    """
    result = {}
    for doctype in ('Tongjianyun Recipe', 'Tongjianyun Recipe Dish', 'Tongjianyun Recipe Ingredient', 'Version'):
        filters = {'ref_doctype': 'Tongjianyun Recipe'} if doctype == 'Version' else {}
        names = frappe.get_all(doctype, filters=filters, pluck='name', order_by='name', limit_page_length=5001)
        if len(names) > 5000:
            raise PermissionError('Bounded recipe baseline may not truncate')
        records = {}
        for name in names:
            doc = frappe.get_doc(doctype, name)
            parent = name if doctype == 'Tongjianyun Recipe' else doc.docname if doctype == 'Version' else doc.recipe
            records[name] = {'recipe': parent, 'sha256': digest(doc.as_dict())}
        result[doctype] = records
    return result


def unchanged(before, after, owned):
    if set(before) != set(after):
        return False
    for doctype, prior in before.items():
        current = after[doctype]
        if any(current.get(name) != record for name, record in prior.items()):
            return False
        if any(current[name]['recipe'] not in owned for name in set(current) - set(prior)):
            return False
    return not set(before['Tongjianyun Recipe']) & set(owned)


def prepare(frappe, run_id, owner=OWNER):
    if owner not in ACTORS.values():
        raise PermissionError('Unreviewed QA actor')
    target = folder(run_id)
    if target.exists() or target.is_symlink():
        raise FileExistsError('Run reserved; retain and inspect evidence, never retry')
    from tongjianyun import business_agent_recipes as recipes, business_agent_writes as writes
    from tongjianyun import meal_scene as scene
    reader = worker_check.readonly_adapter(frappe)
    result = {'status': 'stopped_read_only', 'site': qa.SITE, 'run_id': run_id, 'day': DAY, 'week_end': END,
        'owner': owner, 'actor_scope': 'existing_qa_manager_native_permissions' if owner == MANAGER else 'original_qa_teacher_permissions',
        'source_sha256': source_hashes(), 'native_writes': 0, 'model_calls': 0, 'task_created': False,
        'ingredients_exercised': False, 'automatic_retry_allowed': False}
    def check():
        account_guard(frappe, owner)
        recipes.check_projection()
        scene.require_recipe_create()
        assert_empty_target(frappe)
        if frappe.db.sql('SELECT @@session.tx_isolation')[0][0] != 'REPEATABLE-READ':
            raise PermissionError('Native REPEATABLE-READ isolation required')
        # Current native schema and permission records are consumed above; no
        # bootstrap, sync of DocTypes or permission repair is performed here.
        if 'recipe_save' not in writes.TOOLS:
            raise PermissionError('Reviewed recipe ledger integration is unavailable')
        for version in (1, 2, 3):
            recipes.normalize_payload(payload(run_id, version))
        return baseline(frappe)
    try:
        before = reader.run_check(owner, check)
    except (PermissionError, frappe.PermissionError):
        result['stop_reason'] = 'Original QA authority, empty week or reviewed integration is unavailable; no elevation or write'
        return result
    return {**result, 'status': 'prepared_read_only', 'baseline': before,
            'empty_week_verified': True, 'planned_commits': 2, 'planned_rollbacks': 2,
            'scope': 'Draft create, same-identity edit, history, duplicate-week and stale-revision refusal; no ingredient rows'}


def require_prepared(prepared, run_id, owner=OWNER):
    if (type(prepared) is not dict or prepared.get('status') != 'prepared_read_only'
            or owner not in ACTORS.values() or prepared.get('owner') != owner
            or prepared.get('site') != qa.SITE or prepared.get('run_id') != canonical(run_id)
            or prepared.get('day') != DAY or prepared.get('week_end') != END
            or prepared.get('empty_week_verified') is not True or prepared.get('source_sha256') != source_hashes()):
        raise PermissionError('Successful fresh exact read-only preparation is required')


def native_snapshot(frappe, run_id, recipe, owner=OWNER):
    """Owner-bound native read; independent diagnostics use READ ONLY contexts."""
    from tongjianyun import meal_scene as scene, recipe_storage as storage
    account_guard(frappe, owner)
    current = scene.get_recipe(recipe)
    doc = frappe.get_doc('Tongjianyun Recipe', recipe)
    if (doc.owner != owner or doc.title != payload(run_id, 1)['recipe']['title']
            or str(doc.week_start) != DAY or str(doc.week_end) != END
            or doc.recipe_id != recipe or doc.is_deleted or doc.workflow_status != '草稿'):
        raise PermissionError('Readback is not this run\'s synthetic draft')
    histories = storage.get_recipe_history(recipe)['versions']
    snapshots = [storage.get_recipe_history(recipe, row['name'])['payload'] for row in histories]
    return {'name': recipe, 'revision': current['revision'], 'payload_sha256': digest(current['payload']),
            'dishes': [name for day in current['payload']['days'] for portion in day['portions'] for name in portion['dishes']],
            'history_payload_sha256': [digest(value) for value in snapshots],
            'history_names': [row['name'] for row in histories], 'week_names': week_names(frappe),
            'ingredient_count': frappe.db.count('Tongjianyun Recipe Ingredient', {'recipe': recipe})}


def native_rejection(error):
    """Exact original service messages only; never retain arbitrary DB errors."""
    message = str(error)
    if message in ('食谱已被其他人修改，请刷新后重新核对。',
                   '食谱已更新或缺少版本号。请重新读取这份食谱后再保存，不要另建副本。'):
        return 'stale_revision'
    if message == (DAY + ' 这一周已有食谱。请编辑本周现有食谱，不要新建或另存副本；'
                   '如有历史重复记录，请先确认保留哪一份并将其余归档。'):
        return 'duplicate_week'
    return 'other'


class ObservedTransaction:
    """Keep native adapter/ledger semantics; add a locked QA ownership guard."""
    def __init__(self, transaction, frappe, run_id, hashes, known, record, owner=OWNER):
        self.transaction, self.frappe, self.run_id = transaction, frappe, run_id
        self.hashes, self.known, self.record = hashes, known, record
        self.owner = owner

    def begin(self):
        self.transaction.begin()

    def guard(self):
        from tongjianyun.recipe_week import lock_recipe_writes
        if source_hashes() != self.hashes:
            raise PermissionError('Candidate source changed during acceptance')
        account_guard(self.frappe, self.owner)
        lock_recipe_writes()
        if not self.known:
            assert_empty_target(self.frappe, current=True)
        plan = self.transaction.recipe_plan
        args = plan.arguments
        if (args['day'] != DAY or args['payload'] not in [payload(self.run_id, n) for n in (1, 2, 3)]
                or set(week_names(self.frappe, current=True)) - set(self.known)):
            raise PermissionError('Only this run\'s exact payload and newly created week may be written')
        if args['recipe'] is None:
            if (self.frappe.db.exists('Tongjianyun Recipe', plan.target_recipe)
                    or self.frappe.db.exists('Tongjianyun Recipe', {'recipe_id': plan.target_recipe})):
                raise PermissionError('Reserved native recipe identity already exists')
        else:
            if args['recipe'] not in self.known:
                raise PermissionError('Cannot edit a recipe not created by this run')
            native_snapshot(self.frappe, self.run_id, args['recipe'], self.owner)

    def save(self):
        self.transaction._context.run(self.guard)
        try:
            value = self.transaction.save()
        except BaseException as error:
            self.record['save_error_type'] = type(error).__name__[:80]
            self.record['save_error_classification'] = native_rejection(error)
            raise
        if value.get('ingredient_sync_scheduled') is not False or value.get('ingredient_sync_completed') is not False:
            raise PermissionError('Empty synthetic recipe must not enqueue ingredient work')
        self.record['pending_recipe'] = value['recipe']
        return value

    def commit(self):
        self.record['commit_attempted'] = True
        self.transaction.commit()
        self.record['commit_acknowledged'] = True

    def rollback(self):
        value = self.transaction.rollback()
        self.record['rollback_acknowledged'] = value is True
        return value

    def close(self):
        value = self.transaction.close()
        self.record['connection_drained'] = value is True
        return value


def execute(frappe, run_id, prepared, owner=OWNER):
    require_prepared(prepared, run_id, owner)
    if prepare(frappe, run_id, owner) != prepared:
        raise PermissionError('Preflight changed; no recipe write permitted')
    target = folder(run_id)
    target.mkdir(mode=0o700)
    private_new(target / 'attempt.json', prepared)
    evidence = {'version': 1, 'run_id': run_id, 'site': qa.SITE, 'day': DAY, 'checks': [],
        'owner': owner, 'actor_scope': prepared['actor_scope'], 'teacher_authority_proven': False,
        'all_passed': False, 'transactions': [], 'retained': True, 'automatic_retry_allowed': False,
        'model_calls': 0, 'browser_exercised': False, 'http_exercised': False, 'rq_worker_exercised': False,
        'ingredient_matching_exercised': False, 'production_access': False, 'users_roles_shares_modified': False,
        'task_claims': 'Synthetic private SQLite only; no real runtime/worker execution proof',
        'source_sha256': prepared['source_sha256'], 'baseline_scope': 'Recipe/Dish/Ingredient and recipe Versions only'}
    private_new(target / 'initial-evidence.json', evidence)
    ledger, claim, store, identity = None, None, None, None
    owned, transactions = set(), []
    def check(name, passed):
        event = {'name': name, 'passed': passed is True}
        evidence['checks'].append(event)
        private_new(target / ('check-%03d.json' % len(evidence['checks'])), event)
        if passed is not True:
            raise AssertionError(name)
    try:
        from tongjianyun import business_agent_recipes as recipes, business_agent_writes as writes
        from tongjianyun.business_agent_tasks import BusinessTaskStore, TaskIdentity, QueueObservation, ExecutionObservation
        reader = worker_check.readonly_adapter(frappe)
        task_dir, write_dir = target / 'tasks', target / 'writes'
        task_dir.mkdir(mode=0o700)
        write_dir.mkdir(mode=0o700)
        store = BusinessTaskStore(task_dir, qa.SITE, authorize=reader,
            observe_queue=lambda job: QueueObservation(job, 'unknown'),
            observe_execution=lambda ident, current: ExecutionObservation(current, 'unknown', 0))
        def before_connect():
            qa.config_guard()
            qa.guard(frappe.conf)
            if source_hashes() != prepared['source_sha256']:
                raise PermissionError('Candidate changed')
        adapter = recipes.RecipeWriteAdapter(qa.SITE, str(qa.SITES), store=store,
            authority=reader, before_connect=before_connect)
        ledger = writes.BusinessWriteLedger(write_dir, qa.SITE, authorize=adapter.authorize)
        identity = TaskIdentity(qa.SITE, owner, run_id)
        store.create(owner, run_id, 'Explicit isolated synthetic recipe create and same-recipe edit acceptance', {'day': DAY})
        ticket = store.take_dispatch(identity)
        store.acknowledge_dispatch(ticket)
        claim = store.claim(identity, ticket.job_id)
        ledger.open_task(claim)
        def factory(current, tool, arguments, *, operation_id=None):
            tx = adapter.transaction_factory(current, tool, arguments, operation_id=operation_id)
            if tx._database is not None:
                raise RuntimeError('Factory connected before ledger begin')
            record = {'operation_id': operation_id, 'target_recipe': tx.recipe_plan.target_recipe,
                      'commit_attempted': False, 'commit_acknowledged': False, 'connection_drained': False}
            evidence['transactions'].append(record)
            # Persist planned identity BEFORE begin, retaining unknown commits.
            private_new(target / ('operation-' + canonical(operation_id) + '.json'), dict(record))
            transactions.append(tx)
            return ObservedTransaction(tx, frappe, run_id, prepared['source_sha256'], owned, record, owner)
        # BusinessRecipes registers/publishes its recipe view during fresh_read.
        business = writes.BusinessWrites(ledger, transaction_factory=factory,
            fresh_read=adapter.fresh_read, publish_view=lambda current, selection: None)
        def save(arguments, call_id):
            result = business.dispatch(claim, 'recipe_save', arguments, call_id)
            private_new(target / (call_id + '-receipt.json'), {
                key: value for key, value in result.items() if key not in ('readback', 'selection')})
            return result
        original = {'day': DAY, 'recipe': None, 'revision': '', 'payload': payload(run_id, 1)}
        created = save(original, 'create')
        check('create_acknowledged_and_independent_readback', created['status'] == 'committed'
              and created['readback_available'] is True and created['host_write_active'] is False)
        recipe = recipes.write_plan(qa.SITE, created['operation_id'], original).target_recipe
        owned.add(recipe)
        evidence['owned_recipes'] = sorted(owned)
        first = reader.run_check(owner, lambda: native_snapshot(frappe, run_id, recipe, owner))
        private_new(target / 'created-readback.json', first)
        check('created_one_draft_in_empty_week', first['week_names'] == [recipe]
              and first['ingredient_count'] == 0 and first['dishes'] == ['Synthetic dish version 1'])
        edited_args = {'day': DAY, 'recipe': recipe, 'revision': first['revision'], 'payload': payload(run_id, 2)}
        edited = save(edited_args, 'edit')
        check('edit_acknowledged_and_independent_readback', edited['status'] == 'committed'
              and edited['readback_available'] is True and edited['readback']['recipe'] == recipe)
        second = reader.run_check(owner, lambda: native_snapshot(frappe, run_id, recipe, owner))
        private_new(target / 'edited-readback.json', second)
        check('same_recipe_new_revision_and_original_history', second['week_names'] == [recipe]
              and second['revision'] != first['revision'] and second['dishes'] == ['Synthetic dish version 2']
              and first['payload_sha256'] in second['history_payload_sha256']
              and set(first['history_names']) < set(second['history_names']))
        stale = save({**edited_args, 'payload': payload(run_id, 3)}, 'stale-revision')
        def rejected(value, classification):
            records = [row for row in evidence['transactions'] if row['operation_id'] == value['operation_id']]
            return (value['status'] == 'rolled_back' and value['committed'] is False
                    and not value['host_write_active'] and len(records) == 1
                    and records[0].get('save_error_classification') == classification)
        check('native_stale_revision_refusal_rolled_back', rejected(stale, 'stale_revision'))
        duplicate = save({**original, 'payload': payload(run_id, 3)}, 'duplicate-week')
        check('native_duplicate_week_refusal_rolled_back', rejected(duplicate, 'duplicate_week'))
        final = reader.run_check(owner, lambda: native_snapshot(frappe, run_id, recipe, owner))
        private_new(target / 'final-readback.json', final)
        check('rejected_mutations_preserved_content_history_and_one_weekly_identity', final == second)
        after = reader.run_check(owner, lambda: baseline(frappe))
        private_new(target / 'final-baseline.json', after)
        check('all_existing_recipe_records_unchanged_and_new_records_owned', unchanged(prepared['baseline'], after, owned))
        observation = ledger.observe(identity, claim.claim_id)
        check('two_native_commit_acks_two_rollbacks_and_drained_connections',
              len(transactions) == 4 and all(tx._closed for tx in transactions)
              and sum(r['commit_acknowledged'] for r in evidence['transactions']) == 2
              and sum(r.get('rollback_acknowledged') is True for r in evidence['transactions']) == 2
              and observation.active_writes == observation.uncertain_writes == 0)
        evidence['all_passed'] = True
    except BaseException as error:
        evidence['failure_type'] = type(error).__name__
        raise
    finally:
        try:
            if ledger is not None and claim is not None:
                ledger.close_task(identity, claim.claim_id)
                observation = ledger.observe(identity, claim.claim_id)
                evidence['host_gate'] = {'admission_closed': observation.admission_closed,
                    'active_writes': observation.active_writes, 'uncertain_writes': observation.uncertain_writes}
        except BaseException as error:
            evidence['all_passed'] = False
            evidence['gate_close_failure_type'] = type(error).__name__
            raise
        finally:
            private_new(target / 'evidence.json', evidence)
            print(json.dumps({'evidence': str(target / 'evidence.json'), 'all_passed': evidence['all_passed']}), flush=True)
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('prepare', 'run'), default='prepare')
    parser.add_argument('--run-id', required=True, type=canonical)
    parser.add_argument('--owner', choices=tuple(ACTORS), default='teacher',
                        help='Fixed existing synthetic actor; manager success does not prove teacher authority')
    args = parser.parse_args(argv)
    frappe = environment()
    owner = ACTORS[args.owner]
    prepared = prepare(frappe, args.run_id, owner)
    if args.action == 'run' and prepared['status'] == 'prepared_read_only':
        return execute(frappe, args.run_id, prepared, owner)
    result = {key: value for key, value in prepared.items() if key != 'baseline'}
    if 'baseline' in prepared:
        result['baseline_sha256'] = digest(prepared['baseline'])
    print(json.dumps(result), flush=True)
    return result


if __name__ == '__main__':
    try:
        result = main()
        if result.get('status') == 'stopped_read_only':
            raise SystemExit(2)
    except Exception as error:
        print(json.dumps({'ok': False, 'error_type': type(error).__name__,
                          'detail': 'Stopped; preserve synthetic records/evidence; no automatic retry'}), flush=True)
        raise SystemExit(1) from None
