"""Owner-private, versioned data-only proposals for ordinary business tasks.

This is not a schema writer. Model tools persist finite draft specifications in
a fixed private repository; they cannot hand off, activate, change roles or call
an administrator runner. Browser handoff methods require a live captured Viewer
and an explicitly named recipient/revision. Acceptance copies that exact draft
through the original manager-owned File proposal service, NOT activation.

The wrapper authorizer must be the task store's authorizer, including SSE replay.
Every delivered draft carries its immutable owner/revision capability and all
Link DocType dependencies. Existing task dependencies are never discarded.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import uuid

from tongjianyun.business_agent_tasks import TaskIdentity, WorkerClaim, MAX_SCOPES, authority_scope
from tongjianyun.business_agent_transport import private_directory, strict_json

CAP_PREFIX = 'proposal:v1:'
MAX_BYTES = 40000
TOOL_INSTRUCTIONS = {
    'proposal_create': ('proposal_create 参数仅 {spec:对象}。先发现已有业务；确实缺少时保存自己的数据型草稿，不创建类型、业务记录或权限。'
        'v1 spec 的精确字段为 {key:3到39位小写字母数字下划线且字母开头,title:1到80字,description:1到1000字,fields:1到24个字段}。'
        '每字段只接受 {fieldname:字母开头的小写字母数字下划线,label:标签,fieldtype:类型,reqd?:0或1,options?:选项}；'
        '类型仅 Data、Small Text、Date、Datetime、Int、Float、Currency、Check、Select、Link。Select 的 options 是换行分隔选项；'
        'Link 的 options 是已发现且自己可读的业务DocType，不能关联用户/权限/配置；其他类型不传options。'
        '示例 {"spec":{"key":"visitor_log","title":"访客登记","description":"记录到访时间，不是出入审批",'
        '"fields":[{"fieldname":"visited_on","label":"日期","fieldtype":"Date","reqd":1}]}}。'
        '不要增加code、HTML、角色、defaults或任意公式。v2在上述spec加version:2、tables、calculations、workflow；'
        'tables最多2个{fieldname,label,reqd?:0或1,fields:最多12个同规则字段}；calculations最多8个固定计算，'
        '仅{op:"multiply",table:明细名,target:明细金额字段,sources:[数量字段,单价字段]}或'
        '{op:"sum",table:明细名,target:主表金额字段,source:明细金额字段}；相关字段须为数值类型且目标为Currency。'
        'workflow只能null或{template:"review"}，不能传角色/自定义流程；v2至少包含明细表或该固定复核流程。'
        '复杂专业集成不由多建几个字段代替。返回左侧预览请求，不代表浏览器已加载或业务已启用。'),
    'proposal_read': 'proposal_read 参数 {proposal_id,revision?:64位摘要}，只读自己的草稿；省略 revision 读当前版本。返回 spec 供继续修改，可同时请求左侧预览。历史版本不是当前版本。',
    'proposal_update': 'proposal_update 参数 {proposal_id,expected_revision,spec:完整有限蓝图}。先读真实当前版本再修改，expected_revision 为读取的摘要；冲突重新读取，不覆盖别人的并发修改。只保存草稿，不更改数据库结构。',
    'proposal_list': 'proposal_list 参数 {cursor?:上页next_cursor,page_size?:1到20}，分页发现自己的已保存方案，不枚举其他用户；page_count 不是已启用业务数。使用返回编号继续读取；scope_budget_exhausted 不是空结果。',
}


def _services():
    import frappe
    from tongjianyun import business_agent_authority, business_blueprints, business_blueprints_v2
    return frappe, business_agent_authority, business_blueprints, business_blueprints_v2


def _json(value):
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if len(encoded.encode()) > MAX_BYTES:
            raise ValueError('Proposal exceeds finite size')
        return encoded
    except (TypeError, RecursionError, UnicodeError) as error:
        raise ValueError('Expected finite proposal JSON') from error


def _id(value):
    if not isinstance(value, str):
        raise ValueError('Invalid proposal identifier')
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError('Noncanonical proposal identifier')
    except (ValueError, AttributeError) as error:
        raise ValueError('Invalid proposal identifier') from error
    return value


def _revision(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('Invalid proposal revision')
    return value


def _owner(value):
    if not isinstance(value, str) or value == 'Guest' or not 1 <= len(value) <= 140 or value != value.strip() or any(ord(c) < 32 for c in value):
        raise PermissionError('A real business account is required')
    return value


def canonical_selection(value):
    if type(value) is not dict or set(value) != {'view', 'proposal_id', 'revision'} or value['view'] != 'business_proposal':
        raise ValueError('Expected a version-bound private proposal selection')
    return {'view': 'business_proposal', 'proposal_id': _id(value['proposal_id']), 'revision': _revision(value['revision'])}


def _choice(record):
    return canonical_selection({'view': 'business_proposal', 'proposal_id': record['proposal_id'], 'revision': record['revision']})


def _capability(proposal_id, revision):
    return {'kind': 'capability', 'name': CAP_PREFIX + _id(proposal_id) + ':' + _revision(revision)}


def _links(spec):
    fields = [*spec['fields'], *[field for table in spec.get('tables', []) for field in table['fields']]]
    return sorted({field['options'] for field in fields if field['fieldtype'] == 'Link'})


def _arguments(tool, value):
    if type(value) is not dict:
        raise ValueError('Expected finite proposal arguments')
    args = strict_json(_json(value))
    schemas = {'proposal_create': ({'spec'}, {'spec'}),
               'proposal_update': ({'proposal_id', 'expected_revision', 'spec'}, {'proposal_id', 'expected_revision', 'spec'}),
               'proposal_read': ({'proposal_id', 'revision'}, {'proposal_id'}),
               'proposal_list': ({'cursor', 'page_size'}, set())}
    if tool not in schemas or set(args) - schemas[tool][0] or not schemas[tool][1] <= set(args):
        raise ValueError('Unexpected proposal tool or arguments')
    for key in ('proposal_id', 'cursor'):
        if key in args:
            _id(args[key])
    for key in ('revision', 'expected_revision'):
        if key in args:
            _revision(args[key])
    if 'spec' in args:
        if type(args['spec']) is not dict:
            raise ValueError('Proposal spec must be a finite object')
        args['spec'] = _services()[2].validate_spec(args['spec'])
    if tool == 'proposal_list':
        size = args.setdefault('page_size', 10)
        if type(size) is not int or not 1 <= size <= 20:
            raise ValueError('Invalid proposal page size')
    return args


class ProposalConflict(ValueError):
    """Current draft differs from the actor's expected revision."""


class ProposalRepository:
    """Fixed-site private SQLite; immutable versions and atomic draft receipts.

    Provision the exact directory with mode 0700 as the site OS user first.
    Do not mount it into a model sandbox. The host's private directory is the
    security boundary; untrusted same-UID processes are not supported.
    """
    def __init__(self, site, sites_path):
        if not isinstance(site, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', site):
            raise ValueError('Invalid fixed site')
        self.site = site
        self.directory = private_directory(Path(sites_path) / site / 'private' / 'business-codex' / 'proposals')
        self.path = self.directory / 'proposals.sqlite3'
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            self._inode = self._file(os.fstat(fd))
        finally:
            os.close(fd)
        with self._connection(write=True) as db:
            db.execute('CREATE TABLE IF NOT EXISTS binding (site TEXT NOT NULL UNIQUE)')
            rows = db.execute('SELECT site FROM binding').fetchall()
            if rows and rows != [(site,)]:
                raise PermissionError('Proposal repository belongs to another site')
            if not rows:
                db.execute('INSERT INTO binding VALUES (?)', (site,))
            db.execute('CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, owner TEXT NOT NULL, business_key TEXT NOT NULL, head TEXT NOT NULL, version INTEGER NOT NULL, UNIQUE(owner,business_key))')
            db.execute('CREATE TABLE IF NOT EXISTS versions (id TEXT NOT NULL, revision TEXT NOT NULL, version INTEGER NOT NULL, spec TEXT NOT NULL, task_id TEXT NOT NULL, PRIMARY KEY(id,revision), UNIQUE(id,version))')
            db.execute('CREATE TABLE IF NOT EXISTS receipts (task_id TEXT NOT NULL, call_id TEXT NOT NULL, owner TEXT NOT NULL, digest TEXT NOT NULL, id TEXT NOT NULL, revision TEXT NOT NULL, PRIMARY KEY(task_id,call_id))')
            db.execute('CREATE TABLE IF NOT EXISTS handoffs (id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, revision TEXT NOT NULL, sender TEXT NOT NULL, recipient TEXT NOT NULL, purpose TEXT NOT NULL, state TEXT NOT NULL, receipt TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS task_gates (task_id TEXT PRIMARY KEY, owner TEXT NOT NULL, claim_id TEXT NOT NULL, token_hash TEXT, closed INTEGER NOT NULL CHECK(closed IN (0,1)))')

    @staticmethod
    def _file(info):
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (os.name == 'posix' and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077)):
            raise PermissionError('Proposal database must be private and single-linked')
        return info.st_dev, info.st_ino

    def _check(self):
        private_directory(self.directory)
        if self.path.is_symlink() or self._file(self.path.stat(follow_symlinks=False)) != self._inode:
            raise PermissionError('Proposal repository file changed')
        # SQLite creates journals from the database's 0600 mode. Reject an
        # existing non-private/symlink sidecar instead of chmod after opening.
        for suffix in ('-journal', '-wal', '-shm'):
            path = Path(str(self.path) + suffix)
            if path.is_symlink():
                raise PermissionError('Unsafe proposal journal')
            if path.exists():
                self._file(path.stat(follow_symlinks=False))

    @contextmanager
    def _connection(self, *, write=False):
        self._check()
        db = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        try:
            self._check()
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA synchronous=FULL')
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    def _identity(self, identity):
        if not isinstance(identity, TaskIdentity) or identity.site != self.site or identity.mode != 'business':
            raise PermissionError('Proposal task identity does not match this site')
        _owner(identity.owner)
        _id(identity.task_id)

    def _claim(self, claim):
        if not isinstance(claim, WorkerClaim):
            raise PermissionError('A trusted proposal worker claim is required')
        self._identity(claim.identity)
        _id(claim.claim_id)
        if not isinstance(claim.token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', claim.token):
            raise PermissionError('Invalid proposal worker capability')
        return hashlib.sha256(claim.token.encode()).hexdigest()

    def open_task(self, claim):
        """Trusted runtime BEFORE native bind; cannot reopen a closed task gate.

        This is not a model tool or claim authenticator: the task store already
        issued the claim to the trusted runtime. Persist only a token hash.
        """
        token_hash = self._claim(claim)
        with self._connection(write=True) as db:
            row = db.execute('SELECT owner,claim_id,token_hash,closed FROM task_gates WHERE task_id=?', (claim.identity.task_id,)).fetchone()
            expected = (claim.identity.owner, claim.claim_id, token_hash, 0)
            if row is not None and row != expected:
                raise PermissionError('Proposal task gate is closed or belongs to another claim')
            if row is None:
                db.execute('INSERT INTO task_gates VALUES (?,?,?,?,0)', (claim.identity.task_id, claim.identity.owner, claim.claim_id, token_hash))
        return True

    def close_task(self, identity, claim_id):
        """Trusted runtime only; literal True is a durable SQLite drain barrier.

        BEGIN IMMEDIATE serializes with every draft write. It waits until any
        earlier mutation commits/rolls back and then prevents ALL later writes.
        Missing gates are permanently sealed too, blocking a late native bind.
        Timeout/exception is UNKNOWN, never a positive drained observation.
        """
        self._identity(identity)
        _id(claim_id)
        with self._connection(write=True) as db:
            row = db.execute('SELECT owner,claim_id FROM task_gates WHERE task_id=?', (identity.task_id,)).fetchone()
            if row is not None and row != (identity.owner, claim_id):
                raise PermissionError('Cannot close a different proposal claim')
            if row is None:
                db.execute('INSERT INTO task_gates VALUES (?,?,?,NULL,1)', (identity.task_id, identity.owner, claim_id))
            else:
                db.execute('UPDATE task_gates SET closed=1 WHERE task_id=?', (identity.task_id,))
        return True

    def _open_gate(self, db, claim):
        token_hash = self._claim(claim)
        row = db.execute('SELECT owner,claim_id,token_hash,closed FROM task_gates WHERE task_id=?', (claim.identity.task_id,)).fetchone()
        if row != (claim.identity.owner, claim.claim_id, token_hash, 0):
            raise PermissionError('Proposal writing is sealed for this task')

    def _record(self, db, owner, proposal_id, revision=None):
        _owner(owner)
        _id(proposal_id)
        if revision is not None:
            _revision(revision)
        head = db.execute('SELECT head,version FROM drafts WHERE id=? AND owner=?', (proposal_id, owner)).fetchone()
        if not head:
            raise PermissionError('Private proposal is unavailable')
        row = db.execute('SELECT revision,version,spec FROM versions WHERE id=? AND revision=?', (proposal_id, revision or head[0])).fetchone()
        if not row:
            raise PermissionError('Private proposal revision is unavailable')
        bp = _services()[2]
        spec = bp.validate_spec(strict_json(row[2]))
        if bp.revision(spec) != row[0]:
            raise PermissionError('Private proposal revision is corrupt')
        return {'proposal_id': proposal_id, 'revision': row[0], 'version': row[1], 'current_revision': head[0],
                'is_current': row[0] == head[0], 'spec': spec, 'state': 'draft', 'enabled': False}

    def read(self, owner, proposal_id, revision=None):
        with self._connection() as db:
            return self._record(db, owner, proposal_id, revision)

    def list(self, owner, *, cursor=None, size=10):
        _owner(owner)
        if cursor is not None:
            _id(cursor)
        if type(size) is not int or not 1 <= size <= 20:
            raise ValueError('Invalid bounded page')
        with self._connection() as db:
            ids = db.execute('SELECT id FROM drafts WHERE owner=? AND id>? ORDER BY id LIMIT ?', (owner, cursor or '', size + 1)).fetchall()
            # Include lookahead dependencies: has_more is derived from it too.
            return [self._record(db, owner, row[0]) for row in ids]

    def mutate(self, claim, tool, args, call_id, *, authorize):
        self._claim(claim)
        identity = claim.identity
        if tool not in {'proposal_create', 'proposal_update'} or not isinstance(call_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', call_id):
            raise ValueError('Expected a bound finite draft mutation')
        args = _arguments(tool, args)
        digest = hashlib.sha256(_json({'tool': tool, 'args': args}).encode()).hexdigest()
        spec, bp = args['spec'], _services()[2]
        revision = bp.revision(spec)
        authorize()  # Before entering the writer, including idempotent replay.
        with self._connection(write=True) as db:
            self._open_gate(db, claim)
            authorize()  # Never begin a new proposal write after stop/revocation.
            receipt = db.execute('SELECT owner,digest,id,revision FROM receipts WHERE task_id=? AND call_id=?', (identity.task_id, call_id)).fetchone()
            if receipt:
                if receipt[:2] != (identity.owner, digest):
                    raise PermissionError('Draft operation ID was already used differently')
                result = self._record(db, identity.owner, receipt[2], receipt[3])
            else:
                if tool == 'proposal_create':
                    old = db.execute('SELECT id,head FROM drafts WHERE owner=? AND business_key=?', (identity.owner, spec['key'])).fetchone()
                    if old and old[1] != revision:
                        raise ProposalConflict('A draft with this key exists; read it and update its revision')
                    proposal_id = old[0] if old else str(uuid.uuid4())
                    if not old:
                        db.execute('INSERT INTO drafts VALUES (?,?,?,?,?)', (proposal_id, identity.owner, spec['key'], revision, 1))
                        db.execute('INSERT INTO versions VALUES (?,?,?,?,?)', (proposal_id, revision, 1, _json(spec), identity.task_id))
                else:
                    proposal_id = args['proposal_id']
                    old = self._record(db, identity.owner, proposal_id)
                    if old['spec']['key'] != spec['key']:
                        raise ValueError('The business key is immutable; create a distinct draft instead')
                    if old['revision'] != args['expected_revision']:
                        raise ProposalConflict('Draft changed; read the current revision before editing')
                    if revision != old['revision']:
                        # Content versions are immutable, not an edit counter.
                        # A→B→A selects the original immutable A version; its
                        # saved content and old read capabilities never change.
                        existing = db.execute('SELECT version FROM versions WHERE id=? AND revision=?', (proposal_id, revision)).fetchone()
                        number = db.execute('SELECT MAX(version)+1 FROM versions WHERE id=?', (proposal_id,)).fetchone()[0]
                        if existing:
                            number = existing[0]
                        else:
                            db.execute('INSERT INTO versions VALUES (?,?,?,?,?)', (proposal_id, revision, number, _json(spec), identity.task_id))
                        db.execute('UPDATE drafts SET head=?,version=? WHERE id=?', (revision, number, proposal_id))
                        db.execute("UPDATE handoffs SET state='stale' WHERE proposal_id=? AND state='pending'", (proposal_id,))
                db.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?)', (identity.task_id, call_id, identity.owner, digest, proposal_id, revision))
                result = self._record(db, identity.owner, proposal_id, revision)
            authorize()  # Atomic SQLite commit follows only a fresh live check.
        return result

    def handoff(self, owner, proposal_id, revision, recipient, *, authorize):
        _owner(recipient)
        if owner == recipient:
            raise ValueError('A handoff requires a distinct named manager')
        with self._connection(write=True) as db:
            authorize()
            record = self._record(db, owner, proposal_id, revision)
            if not record['is_current']:
                raise ProposalConflict('Only the current exact draft may be handed off')
            row = db.execute("SELECT id FROM handoffs WHERE proposal_id=? AND revision=? AND recipient=? AND state='pending'", (proposal_id, revision, recipient)).fetchone()
            grant = row[0] if row else str(uuid.uuid4())
            if not row:
                db.execute('INSERT INTO handoffs VALUES (?,?,?,?,?,?,?,NULL)', (grant, proposal_id, revision, owner, recipient, 'review_and_activate', 'pending'))
            authorize()
        return {'handoff_id': grant, 'proposal_id': proposal_id, 'revision': revision, 'state': 'pending', 'enabled': False}

    def grant(self, recipient, grant_id):
        _id(grant_id)
        with self._connection() as db:
            row = db.execute('SELECT proposal_id,revision,sender,recipient,purpose,state,receipt FROM handoffs WHERE id=? AND recipient=?', (grant_id, _owner(recipient))).fetchone()
            if not row or row[4] != 'review_and_activate' or row[5] == 'stale':
                raise PermissionError('No current explicit proposal handoff')
            record = self._record(db, row[2], row[0], row[1])
            if row[5] == 'pending' and not record['is_current']:
                raise PermissionError('Proposal handoff is stale')
            return {'handoff_id': grant_id, 'sender': row[2], 'recipient': row[3], 'state': row[5],
                    'record': record, 'receipt': strict_json(row[6]) if row[6] else None}

    def transition(self, recipient, grant_id, before, after, *, receipt=None):
        # Trusted browser bridge only. States do not accept a model assertion of
        # completion. Unknown native commit outcome permanently fences retries.
        if (before, after) not in {('pending', 'copying'), ('copying', 'accepted'), ('copying', 'uncertain')}:
            raise ValueError('Invalid handoff transition')
        with self._connection(write=True) as db:
            count = db.execute('UPDATE handoffs SET state=?,receipt=? WHERE id=? AND recipient=? AND state=?',
                (after, _json(receipt) if receipt else None, _id(grant_id), _owner(recipient), before)).rowcount
            if count != 1:
                raise ProposalConflict('Handoff changed or its result is not yet known')


class ProposalAuthority:
    """Finite extension of the existing authorizer; unknown scopes remain denied."""
    def __init__(self, base_authority, repository):
        if base_authority.site != repository.site:
            raise PermissionError('Proposal authority site mismatch')
        self.base, self.repository = base_authority, repository
        self.site, self.run_check = base_authority.site, base_authority.run_check

    def __getattr__(self, name):
        return getattr(self.base, name)

    def validate_spec(self, owner, spec):
        _, gates, bp, _ = _services()
        def check():
            gates._account(owner, self.site)
            clean = bp.validate_spec(spec)
            bp._validate_links(clean)
            for name in _links(clean):
                gates._doctype(name, ['read'])
            return clean
        return self.run_check(owner, check)

    def scopes(self, record):
        return (_capability(record['proposal_id'], record['revision']),
                *({'kind': 'doctype', 'doctype': name, 'actions': ['read']} for name in _links(record['spec'])))

    def __call__(self, identity, scopes):
        try:
            self.repository._identity(identity)
            if not isinstance(scopes, (tuple, list)) or len(scopes) > MAX_SCOPES:
                return False
            native, proposals = [], []
            for raw in scopes:
                scope = authority_scope(raw)
                if scope['kind'] == 'capability' and scope['name'].startswith(CAP_PREFIX):
                    suffix = scope['name'][len(CAP_PREFIX):]
                    if len(suffix) != 101 or suffix[36] != ':':
                        return False
                    proposals.append((_id(suffix[:36]), _revision(suffix[37:])))
                elif scope['kind'] == 'view' and scope['selection'].get('view') == 'business_proposal':
                    choice = canonical_selection(scope['selection'])
                    proposals.append((choice['proposal_id'], choice['revision']))
                else:
                    native.append(scope)
            if self.base(identity, tuple(native)) is not True:
                return False
            for proposal_id, revision in set(proposals):
                record = self.repository.read(identity.owner, proposal_id, revision)
                self.validate_spec(identity.owner, record['spec'])
            return True
        except Exception:
            return False

    def view_scopes(self, identity, selection):
        if type(selection) is not dict or selection.get('view') != 'business_proposal':
            return self.base.view_scopes(identity, selection)
        self.repository._identity(identity)
        choice = canonical_selection(selection)
        record = self.repository.read(identity.owner, choice['proposal_id'], choice['revision'])
        scopes = ({'kind': 'view', 'selection': choice}, *self.scopes(record))
        if not self(identity, scopes):
            raise PermissionError('Private proposal access was revoked')
        return scopes

    def register_read(self, store, claim, read_set):
        # Use the original full-union barrier with THIS wrapper's authorization,
        # not base.register_read (which correctly rejects unknown capabilities).
        _services()[1].FrappeBusinessAuthority.register_read(self, store, claim, read_set)


def _preview(record):
    _, _, bp, v2 = _services()
    spec = record['spec']
    component = {'type': 'business_proposal', 'proposal_id': record['proposal_id'], 'revision': record['revision'],
                 'title': spec['title'], 'description': spec['description'], 'fields': bp._definition(spec)['fields'],
                 'state': 'proposed', 'doctype': bp.doctype_name(spec), 'can_activate': False,
                 'warnings': ['这是私有数据型草稿，尚未核验、创建或启用业务结构；不是已有业务记录。',
                              '只有明确交接给具备原结构权限的管理者后，才能另外核验并启用；模型不能启用。',
                              '原蓝图初始仅 System Manager 可用；启用不代表提案者已获得业务权限。']}
    if spec.get('version') == 2:
        component.update(v2.preview_extra(spec))
    if not record['is_current']:
        component['warnings'].append('当前展示历史版本，不是最新草稿。')
    return {'view': 'business_proposal', 'title': spec['title'], 'subtitle': '个人方案草稿 · 版本 ' + str(record['version']),
            'selection': _choice(record), 'components': [component], 'actions': [],
            'source': '当前用户私有版本化方案；未创建、启用结构或更改业务数据'}


class BusinessProposals:
    def __init__(self, authority, store, repository):
        if not isinstance(authority, ProposalAuthority) or authority.site != store.site or repository is not authority.repository:
            raise PermissionError('A single bound proposal authority/repository is required')
        self.authority, self.store, self.repository = authority, store, repository

    def _active(self, claim):
        if not isinstance(claim, WorkerClaim):
            raise PermissionError('Trusted worker claim required')
        self.repository._identity(claim.identity)
        expected = {'site': claim.identity.site, 'owner': claim.identity.owner, 'task_id': claim.identity.task_id,
                    'mode': 'business', 'status': 'running', 'cancel_requested': '0'}
        if self.store.binding_state(claim) != expected:
            raise PermissionError('Business task is no longer running')

    def _register(self, claim, records):
        gates = _services()[1]
        scopes = self._source_scopes(records)
        self.authority.register_read(self.store, claim, gates.ReadSet(scopes))
        self._active(claim)

    def _source_scopes(self, records):
        # ReadSet rejects an oversized raw list BEFORE its own deduplication.
        # Shared Link sources must count once, exactly as in the budget check;
        # retain every distinct revision and every lookahead dependency.
        unique = {}
        for record in records:
            for raw in self.authority.scopes(record):
                scope = authority_scope(raw)
                unique[_json(scope)] = scope
        return tuple(unique.values())

    def _budget(self, claim, records):
        scopes = (*self.store.required_scopes(claim.identity),
                  *self._source_scopes(records))
        return len({_json(scope) for scope in scopes}) <= MAX_SCOPES

    def _budget_result(self, claim, *, mutation=False):
        self._active(claim)
        return {'available': False, 'error': 'scope_budget_exhausted', 'retry': 'new_task',
                'draft_may_be_saved': mutation, 'business_executed': False,
                'message': '本任务来源权限额度不足，不能完整展示；不是没有草稿。请在新任务先查询已有草稿，勿假定保存失败后重复新建。'}

    def dispatch(self, claim, tool, arguments, call_id):
        args = _arguments(tool, arguments)
        self._active(claim)
        if tool == 'proposal_list':
            records = self.repository.list(claim.identity.owner, cursor=args.get('cursor'), size=args['page_size'])
            if not self._budget(claim, records):
                return self._budget_result(claim)
            self._register(claim, records)
            page = records[:args['page_size']]
            return {'entries': [{key: record[key] for key in ('proposal_id', 'revision', 'version', 'state', 'enabled')} |
                                {'title': record['spec']['title'], 'selection': _choice(record)} for record in page],
                    'page_count': len(page), 'has_more': len(records) > len(page),
                    'next_cursor': page[-1]['proposal_id'] if len(records) > len(page) else None,
                    'scope': '仅当前账号私有草稿，不是已启用业务数量；实时分页，不保证跨页快照'}
        if tool in {'proposal_create', 'proposal_update'}:
            def authorize():
                self._active(claim)
                self.authority.validate_spec(claim.identity.owner, args['spec'])
            record = self.repository.mutate(claim, tool, args, call_id, authorize=authorize)
        else:
            record = self.repository.read(claim.identity.owner, args['proposal_id'], args.get('revision'))
        if not self._budget(claim, [record]):
            return self._budget_result(claim, mutation=tool in {'proposal_create', 'proposal_update'})
        self._register(claim, [record])
        choice = _choice(record)
        self.store.emit(claim, {'kind': 'view', 'version': 1, 'selection': choice, 'title': record['spec']['title']})
        self._active(claim)
        return {**record, 'selection': choice, 'display_requested': True, 'business_executed': False,
                'note': '仅保存或读取私有草稿；左侧显示需浏览器再次核权，不表示业务已创建或启用。'}

    def _viewer(self, viewer):
        if not self.authority.viewer_active(viewer):
            raise PermissionError('An active authenticated browser session is required')

    def preview_owned(self, viewer, proposal_id, revision):
        self._viewer(viewer)
        record = self.repository.read(viewer.owner, _id(proposal_id), _revision(revision))
        self.authority.validate_spec(viewer.owner, record['spec'])
        result = _preview(record)
        self._viewer(viewer)
        return result

    def _manager(self, owner, spec):
        frappe, gates, bp, _ = _services()
        def check():
            gates._account(owner, self.authority.site)
            bp._access()  # Original native manager gate, never relaxed.
            types = ['DocType']
            if spec.get('version') == 2 and spec.get('workflow'):
                types += ['Workflow', 'Workflow State', 'Workflow Action Master']
            if not all(frappe.has_permission(name, 'create') for name in types):
                raise PermissionError('Recipient lacks original structure permissions')
            bp._validate_links(spec)
            for name in _links(spec):
                gates._doctype(name, ['read'])
        self.authority.run_check(owner, check)

    def handoff(self, viewer, proposal_id, revision, recipient):
        """Trusted authenticated POST only; explicit exact-version recipient grant.

        Never register this method as a model tool. Does not message anybody,
        change schema or make all managers readers of the user's private draft.
        """
        self._viewer(viewer)
        record = self.repository.read(viewer.owner, proposal_id, revision)
        def authorize():
            self._viewer(viewer)
            self.authority.validate_spec(viewer.owner, record['spec'])
            self._manager(_owner(recipient), record['spec'])
        return self.repository.handoff(viewer.owner, proposal_id, revision, recipient, authorize=authorize)

    def preview_handoff(self, viewer, handoff_id):
        self._viewer(viewer)
        grant = self.repository.grant(viewer.owner, handoff_id)
        self._manager(viewer.owner, grant['record']['spec'])
        result = _preview(grant['record'])
        # A recipient cannot use owner-only business_proposal navigation.
        result.pop('selection')
        result['handoff_id'], result['handoff_state'] = handoff_id, grant['state']
        result['source'] = '提案者明确授权给当前管理者的固定版本；未启用结构'
        self._viewer(viewer)
        return result

    def accept_handoff(self, viewer, handoff_id):
        """Copy via original service as recipient; activation remains separate.

        An unknown File commit response is durably fenced, never retried. This
        bridge deliberately does not claim multi-database exactly-once recovery.
        """
        self._viewer(viewer)
        grant = self.repository.grant(viewer.owner, handoff_id)
        spec = grant['record']['spec']
        self._manager(viewer.owner, spec)
        frappe, gates, bp, _ = _services()
        if grant['state'] == 'accepted':
            receipt = grant['receipt']
            def verify():
                gates._account(viewer.owner, self.authority.site)
                if bp.revision(bp._load(receipt['proposal_id'])) != grant['record']['revision']:
                    raise PermissionError('Accepted private proposal has changed')
            self.authority.run_check(viewer.owner, verify)
            self._viewer(viewer)
            return receipt
        if grant['state'] != 'pending':
            return {'state': 'uncertain', 'enabled': False, 'retry_allowed': False,
                    'note': '管理者私有文件的提交结果待核实，不能盲目再次接受。'}
        self._viewer(viewer)
        self.repository.transition(viewer.owner, handoff_id, 'pending', 'copying')
        try:
            def copy():
                gates._account(viewer.owner, self.authority.site)
                # bp.propose rechecks original native permissions and refuses
                # existing structures; it creates ONLY the recipient's File.
                result = bp.propose(spec)
                if (type(result) is not dict or not isinstance(result.get('proposal_id'), str)
                        or not 1 <= len(result['proposal_id']) <= 140
                        or any(ord(c) < 32 for c in result['proposal_id'])
                        or result.get('revision') != grant['record']['revision']
                        or result.get('state') != 'proposed'):
                    raise ValueError('Original proposal service returned an unverified receipt')
                self._viewer(viewer)
                self._manager(viewer.owner, spec)
                frappe.db.commit()
                return {'proposal_id': result['proposal_id'], 'revision': result['revision'],
                        'state': 'accepted', 'enabled': False,
                        'selection': {'view': 'business_blueprint', 'proposal_id': result['proposal_id']},
                        'note': '已复制为当前管理者的原生私有方案；未启用，仍需原版本绑定启用与结构核验。'}
            receipt = self.authority.run_check(viewer.owner, copy)
            self.repository.transition(viewer.owner, handoff_id, 'copying', 'accepted', receipt=receipt)
        except BaseException:
            # Conservatively fence even a pre-commit exception. We cannot use
            # a failed response as proof no File side effect/commit occurred.
            self.repository.transition(viewer.owner, handoff_id, 'copying', 'uncertain')
            raise
        self._viewer(viewer)
        return receipt
