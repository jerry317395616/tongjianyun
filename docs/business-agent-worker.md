# Business task execution contract

This is the non-root site-user queue worker for the existing durable business
task store. It reuses the one installed Codex binary through the reviewed native
sandbox. It does not install a launcher, grant any Frappe role, enable a teacher
chat endpoint, or fall back to the administrator runner.

## Actual integration

`business_agent_service.run_task(owner, task_id)` is the non-whitelisted RQ
entry. The native Frappe queue selects the site; only owner and task ID enter the
queue. The service verifies the RQ job and authenticated enqueue user.

```python
runtime = UnixLauncherRuntime(site=site, sites_path=sites_path)
store = BusinessTaskStore(
    fixed_directory, site, authorize=authority,
    observe_execution=runtime.observe, observe_queue=queue.observe,
)
worker = BusinessWorker(
    store, runtime,
    read_attendance=lambda claim, **args:
        authority.read_attendance(store, claim, **args),
    model_key=read_fixed_private_model_key,
    read_tools=BusinessReads(authority, store).dispatch,
)
result = worker.run(identity, store.job_id(identity))
```

`fixed_directory` is exactly
`<sites>/<site>/private/business-codex/tasks`, already created by deployment as
the site OS user with mode 0700. The worker creates only a new task-UUID
subdirectory and a private `proxy.sock`; it refuses an existing task directory.
The same runtime instance supplies the store observer and worker execution.
The browser's SID never enters the queue, prompt, proxy or launcher.

`runtime.ready()` performs an authenticated handshake, not a configuration-only
check. Without the separately installed trusted launcher it returns false.
The service additionally requires the enable flag, private credential and live
dedicated queue worker. This module alone is not evidence of deployment.

## Lifecycle and authority

1. A durable claim is acquired exactly once. A duplicate queue delivery never
   starts or resumes another model, including after worker failure.
2. A bound native-control lease and private `TaskProxy` are created. The proxy
   authorizes every tool/model request against this exact business task. Model
   credentials stay in that trusted proxy; only a task token reaches the sandbox.
3. Native stdout feeds `CodexEventProjector`; stdout is parsed incrementally,
   including pipe chunks delivered after process exit. Raw stderr is counted
   only. Tool output, reasoning and command contents do not become public events.
4. Tool reads use the trusted actor and register all same-query source scopes
   before returning data. The view event contains a selection only; the browser
   loads the complete view afresh as its current logged-in user.
5. Cancel/revoke first closes the proxy capability, then stops this exact native
   unit. `stopping` is not `cancelled`. Only the store's trusted observation may
   finish: exact claim/unit, process exit, empty cgroup, drained pipes and no
   active writes. Success additionally requires the local parsed completed turn
   and committed public answer.

SSE disconnection reads durable history on reconnect; it does not restart or
cancel execution. There is no overall task deadline. Individual control framing
has a 30-second timeout; this accommodates the native unit's stop grace period
and does not become a model lifetime limit. Output sizes and parser complexity
remain bounded.

Worker errors return fixed codes and `automatic_retry_allowed: false`, not raw
exception text. Unknown process/cleanup results remain unverified; they are not
reported as success or used to re-execute. A fresh observer after worker death
has no local completed-turn projection. Trusted `store.reconcile` can close such
tasks only as failed/cancelled after an actual closed lease and exit proof.

## Current enabled tool surface

`classroom_read(group, day)` calls the existing
`FrappeBusinessAuthority.read_attendance`, including the complete historical
Student Attendance/Student Leave Application dependencies used in the revision.
The worker then registers and publishes `classroom_day` selection. The service
also supplies `BusinessReads.dispatch` for `scene_bootstrap` (current permitted
class discovery) and `class_students_read` (paginated native roster). Both use
complete same-query source registration; only a complete first page provides a
current visible-class count. A page size or scan-limited result is not a total.
See `business-agent-reads.md`. An identity,
site, SQL, filesystem path or permission-bypass parameter is rejected.

Generic business views, meal reads and writes remain disabled
in this execution path until their exact source contracts are integrated. Their
presence in another dispatch registry is not permission to expose them here.
The runtime observer's `active_writes=0` is valid **only for this read-only
surface**. Adding writes requires a durable write-ledger drainage observer, not
merely adding a tool name. This initial surface does not reduce the project's
intended eventual all-business scope.

## Fixed privileged launcher protocol

Socket: `/run/tongjianyun-business-codex/control.sock`. No caller-selectable
socket, program, environment, model key or mount list. Root-owned path components
and `SO_PEERCRED` authenticate the daemon. The daemon must independently match
the peer UID against its root-owned site mapping; model/HTTP fields cannot change
that mapping. Root never opens the Frappe task store or selects a business actor.

Messages are four-byte network-order length followed by finite UTF-8 JSON,
maximum 384 KiB, with duplicate keys forbidden. Every request has `version: 1`,
`profile: "business-native-v1"`, `op` and configured `site`. Task requests add
canonical `task_id` and `claim_id`. A bound persistent connection owns the lease.

| Operation | Additional request fields | Exact successful response fields |
| --- | --- | --- |
| `ready` | none | `ok`, `version`, `profile`, `native_revision: "bwrap-ro-v2"`, `ready` |
| `bind` | none | `ok`, `unit`, `bound` |
| `start` | `prompt`, `proxy_path`, `token` | `ok`, `unit`, `started` |
| `poll` | `wait_ms: 1000` | `ok`, `stdout` (base64), `stderr_bytes`, `execution` |
| `stop` | none | execution proof below |
| `observe` | none | execution proof below |
| `seal_before_start` | none | permanent never-started proof, or existing actual proof |
| `release` | none | `ok`, `unit`, `cleaned` |

An execution proof has exactly `ok`, `unit`, `claim_id`, `state`, `exit_code`,
`cgroup_empty`, `stdout_eof`, `lease_closed`. The three flags are strict booleans.
The unit must be `tgy-business-codex-<task UUID>.service`. A live executing lease must
report `lease_closed: false`, even if the process has just exited. `stdout_eof`
means actual EOF and all queued chunks delivered (or explicitly discarded by
trusted cancellation), not merely that a child has exited. Poll chunks are at
most 64 KiB. The client continues draining output without treating incomplete
pipe delivery as terminal proof.

The independent `never_started_and_sealed` state has `exit_code: null` and all
three flags true. It means a root-owned, fsync-persisted tombstone permanently
excludes any delayed bind/start, not a fabricated process exit. The store calls
external sealing only after persistent cancellation and an unknown observation.
That external operation never seals an existing bound/attempted task. A bound
lease can stop itself before any launch attempt, under the same state lock,
using this proof; the original worker may finish only failed/cancelled, never
completed. Normal history reads cannot guess that a slow pre-bind worker died.

The fixed proxy path is
`<sites>/<site>/private/business-codex/tasks/<UUID>/proxy.sock`. The daemon must
verify the path's site ownership and relay only that socket into its private
native input directory. It must reuse `native_sandbox.build_systemd_command`,
keep a durable task/claim launch tombstone before starting, and never retry an
uncertain launch. Lease disconnect closes the relay before stopping/draining its
unit. Release removes only that task's validated runtime artifacts and retains
the actual execution proof for same-site peer-authorized recovery.

The QA daemon adds fixed `BindsTo`/`After` dependencies on its own service and
closes leases concurrently within one 40-second shutdown deadline. PID1 stops
dependent task units even if the daemon is killed; this is not itself business
completion evidence. A restarted daemon retains unknown outcomes without retry.

The client cannot enforce implementation details inside an untrusted daemon:
installing/auditing that privileged component and a real isolated acceptance run
are separate deployment prerequisites, not implied by client unit tests.
