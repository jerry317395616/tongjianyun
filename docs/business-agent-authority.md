# Ordinary-business authority integration

This adapter is executable but **does not enable a web endpoint or ordinary-user
Codex chat**. Existing administrator `meal_chat.TaskStore`, publishing, and root
runner remain separate. One Codex installation can serve distinct task identities;
no business-mode request may fall back to the administrator runner.

## Minimal wiring

```python
from tongjianyun.business_agent_authority import (
    FreshFrappeChecks, FrappeBusinessAuthority,
)
from tongjianyun.business_agent_tasks import BusinessTaskStore, TaskIdentity

# These values come from trusted service configuration, not model/request JSON.
authority = FrappeBusinessAuthority(
    FIXED_SITE,
    run_check=FreshFrappeChecks(
        FIXED_SITE, FIXED_SITES_PATH,
        before_connect=verify_config_before_connection,
    ),
)
store = BusinessTaskStore(
    PRIVATE_TASK_DIRECTORY, FIXED_SITE,
    authorize=authority,
    observe_execution=supervisor_observation,
    observe_queue=queue_observation,
)

# Web request: Frappe authentication has ALREADY succeeded. No set_user here.
viewer = authority.capture_viewer()
identity = TaskIdentity(FIXED_SITE, viewer.owner, SERVER_REQUEST_UUID)
scopes = authority.view_scopes(identity, VALIDATED_INITIAL_SELECTION)
store.create(viewer.owner, identity.task_id, message, context,
             authority_scopes=scopes)

# SSE: viewer is a trusted-memory closure, NEVER stored in task/model/event JSON.
stream = store.stream(identity, after=LAST_EVENT_ID,
    authorize_viewer=lambda task: authority.viewer_active(viewer, task))
```

`FreshFrappeChecks` uses `Context().run`, native
`connect(set_admin_as_user=False)`, a fresh database connection and actor each
time, and `destroy()` for that context only. It never commits/rolls back the
caller's transaction or mutates/resumes/extends the browser session. The actual
server's Frappe ContextVar implementation and native session storage were checked.
Native Frappe permission/cache invalidation remains authoritative: this is not a
new generic permission fingerprint or atomic revocation lock.

An expired viewer stops only its SSE. Account disable or loss of any previously
registered source scope makes `store.authorize` fail, which requests task
`stopping`. The supervisor still must revoke tools, stop/drain the exact sandbox
and in-flight writes, and provide execution evidence before terminal cancellation.
No web caller/model supplies terminal status, owner, site or worker token.

## Executable first reader

The trusted worker may route `classroom_read` to:

```python
result = authority.read_attendance(store, claim, group=args['group'], day=args['day'])
# Only now may result be delivered to the model or used to emit an answer.
```

This calls the original `_scope`, `_attendance` and `_capabilities`. The private
keyword-only `source_observer` receives a frozen `AttendanceReadSources` object
from the **same queries**, containing all attendance/leave IDs contributing to
the revision, not only the latest rows selected by `attendance_facts`. The
adapter requires exactly one observation with matching group/day/revision.
It persists the whole scope batch atomically using `register_authorities`,
reauthorizes the full task union, then returns the existing small roster/counts/
revision shape. The model receives no source authority descriptors or extra
document bodies. This is a read adapter, not a second attendance write workflow.
The default `_attendance` return and public HTTP signatures are unchanged; HTTP
endpoints never accept or forward the private observer.

## Exact remaining tool hook points

Do not expose an unmodified `tools.dispatch` result as if registration were
complete. Its current result shapes deliberately discard source identifiers.
Do not monkeypatch global Frappe readers, infer dependencies from model text,
or reread changed data and assume it describes the original result.

- `business_agent_tools._classroom_read`: pass a trusted `source_observer` to
  `classroom._attendance(group, day, source_observer=...)`. Construct
  `attendance_read_set(captured_sources)` from that observer's complete source
  object and call `authority.register_read(store, claim, read_set)` before
  delivery. **Even the original `_attendance` result's student rows are
  insufficient:** they only carry latest attendance/leave IDs, whereas the
  revision includes older rows too. The new executable `read_attendance`
  already supplies this behavior without changing tools.py.
- `business_agent_tools._meal_read`: `classroom.get_meals` returns the original
  `record`, before tools.py strips its name/doctype. Existing-record dependencies
  include class read, MEALS projection, every source Student and that exact Class
  Meal Confirmation document. For a new unsaved estimate, `student_meals._load`
  discards the original `calculate_student_details` attendance/leave IDs while
  making rows; capture those exact source rows there before discarding them.
  Register the snapshot's Student/Attendance/Leave dependencies as well as class
  and finite field-projection capabilities. A later query is not a substitute.
- `business_agent_tools._write`: original-service readback registration must
  happen before any data/message is released, both initial execution and durable
  receipt replay. Newly created source documents are invisible to an independent
  permission connection until commit. Keep the internal pending read set with
  the trusted operation outcome, register after authoritative commit/current
  readback and before response. Do **not** turn postcommit registration failure
  into rollback or permission to repeat the write. Ledger and original save
  validators continue to own atomicity, revision, roster, date locks and reasons.
- `business_agent_tools._business_view`: before its publisher or summary result
  is delivered, register the actual source read set captured by the underlying
  reader. `view_scopes` only resolves entry permissions; it is not this read set.
  `meal_views.students_view` has `visible` Student IDs and `memberships` groups;
  `class_students_view` has the full `roster` (not just its page);
  `business_views.classroom_view` must likewise install the private source
  observer when calling `_attendance`, not derive sources from its latest rows.
  For native documents register the exact DocType/document read scopes; native
  catalog snapshots need every admitted entry dependency used in their counts,
  not merely the visible page. Metadata-only summaries must stay metadata-only.
- `scene_access.get_bootstrap`: register the actual local `groups` contributing
  to the returned count/selection before the original service discards the list.
  Business mode must filter any admin-only navigation instead of using the
  admin chat/calendar fallback; the authority allows only the current eight
  audited business/native DocType selections.

Publication uses the private worker claim and `store.emit` after read-set
registration, never `meal_views.publish_for_task` (administrator/root path).
Browser view fetching still runs its original native permissions as the viewer.

## Extension boundary

The current task scope schema is sufficient for finite class, DocType, document,
view and fixed projection capabilities. Unknown capability names and unaudited
view types are denied. Class scope is deliberately read-only, not a permission
to modify Student Group. Native DocType/document actions still use original
permissions and row hooks; this adapter does not implement a generic save API.
Control-plane DocTypes (users/roles/schema/scripts/integration credentials) cannot
be opened by a business task, even when its owner also administers the site.

Source scopes accumulate for the whole task because old text may be replayed.
Losing G1 while retaining G2 still denies G1-derived history. Student source
document scopes also cover later transfer out of an otherwise retained class.
The core's 256-scope bound fails closed; it is not silently truncated. Larger
rosters/long conversations need an explicitly designed compact scoped read-set
format or new tasks, not removal of the bound or identity checks. This module
does not claim coverage for arbitrary SQL reports, arbitrary app RPCs, field
projections not in its finite registry, attachments or future business actions.

## Verification performed

- Linux pure tests exercise authority and real durable task-core integration;
  mocks do not connect to a database or mutate accounts.
- Same-pupil history regression includes two attendance and two leave records:
  all four are captured without re-querying; revoking either older record denies
  replay even while both latest records remain readable. Missing, duplicated or
  revision-mismatched observer results cannot be delivered.
- Existing isolated QA: enabled teacher's `class_students`, `classroom_day`,
  `meal_counts` admission/field permissions passed; other class denied; existing
  two-pupil attendance's actual source permissions passed.
- Caller DB object, actor, SID, request cache and usable connection unchanged.
- Existing one teacher session: DB JSON, native Redis envelope and active viewer
  check passed; no login/session refresh, user/role changes or business writes.
- Private evidence:
  `/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925/business-authority-readonly-f18d9d333b.json`.
- Re-runnable script: `deploy/business_codex/check_business_authority.py`.
  It uses the fixed isolated QA configuration, pins every MariaDB connection to
  session-level READ ONLY, retains new private evidence per run, and does not
  provision data or sessions. If the existing session expires, the evidence
  explicitly says active-session coverage is unavailable; it never creates one.
- This evidence's adapter SHA-256 is
  `f691618037b5780194d404fa40e812733b6c7ed3c47c61806feb5f1d18b70eca`;
  classroom SHA-256 is
  `477ee6bb022281dfa568734d8997e79eb763d9353bb546a712fc737c55467945`;
  script SHA-256 is
  `483a1becc47f970f7993611d860932df683cfa50e24f94738de0fc9aa7a7af20`.
  All matched the final local and overlay files when verified. Earlier evidence
  is retained, but predates the complete-history-source correction and does not
  certify that correction.
- No model was started, no production data modified, no teacher chat enabled.
