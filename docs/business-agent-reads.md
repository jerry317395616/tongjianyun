# Source-aware discovery, class roster and meal reads

Trusted worker integration:

```python
reads = BusinessReads(authority, store)
result = reads.dispatch(claim, tool_name, arguments)
# TOOL_INSTRUCTIONS is a fixed {tool_name: Chinese usage description} mapping.
```

The trusted outer worker supplies `WorkerClaim`. No tool accepts owner,
site, task, SQL, method, file path, permission overrides or write instructions.
`scene_bootstrap` does not publish a view. `class_students_read` **already
publishes** a selection-only `class_students` event with that claim after full
source registration; do not emit it a second time. Its display receipt means
requested, not that the browser has loaded the view.

| Tool | Arguments | Meaning of returned counts |
| --- | --- | --- |
| `scene_bootstrap` | Required `day`; optional `meal`, `after`, `page_size` | `page_count` is this page. `visible_group_count` exists only when the first page contains all currently visible enabled classes. Never a school-wide guarantee. |
| `class_students_read` | Required canonical `group`; optional `cursor`, `page_size` | `page_count` is this page. `visible_class_count` is non-null only when scanning from the first page finishes completely. It is current visible enabled membership, not attendance, meals or historical enrollment. |
| `meal_read` | Required canonical `group` and `day`; no additional model-selected meal or write arguments | Five native meal facts: `expected` is an estimate, `actual: null` is unknown, not zero. A saved class-day snapshot may have only one meal actually confirmed. |

Page size defaults to 25 and is at most 50. Copy `next_after`/`next_cursor`
exactly to continue. A roster cursor contains a revision and candidate scan
position only, without student IDs or credentials. It grants no authority and
can be reused in a new authorized task. Membership/order changes invalidate it.
Each page is a current native read, not a promised multi-request database
snapshot. The browser's existing pagination is independent of this model cursor.

Class discovery reuses `attendance_scope.allowed_groups()` and permission-aware
`frappe.get_list`. Identity links are used only for authorization; employee or
instructor records and the current user's full name are not sent to the model.
Navigation is limited to projections whose current native field/DocType checks
succeed. No class permission is distinct from a genuinely empty permitted list.

Roster pagination and the original full roster share `_roster_members` for
active membership, original roll-number/student ordering and deduplication.
`_roster_page` scans bounded candidate batches through native permission-filtered
enabled-Student queries. Its private source observer records **every actual row
from those same queries**, including the extra row used to establish that another
page exists. It never reconstructs that read set using a later business query.
Group document and assignment scopes cover membership, while Student document
scopes and projection capabilities cover each returned/derived student fact.

The original `_roster` signature and result are unchanged. Native field checks
now explicitly include the child `group_roll_number` field used for ordering.
The private page helper is not whitelisted and callbacks are not accepted over
HTTP. No generic native document payload or HTML is returned to the model.

After 500 candidate memberships in one request, `has_more: null` and
`scan_limited: true` mean remaining visible rows are unknown. A valid
`next_cursor` continues scanning. Zero rows in such a page is **not** zero class
enrollment. The persistent 256-scope task limit is not bypassed: pages shrink to
available capacity, including lookahead sources. Insufficient capacity returns
`available: false`, `error: "scope_budget_exhausted"`, `retry: "new_task"` and no
fake empty roster. Old dependencies are never dropped to make room.

The complete source union is authorized and persisted before result or view
delivery, then the task is rechecked. Losing a previously read class or even a
non-returned lookahead student's permission prevents old event replay. No
administrator runner fallback is available. Further business domains extend
this trusted tool registry separately; these tools are not a claim that all
Frappe business operations have already been integrated.

Re-runnable isolated acceptance: `deploy/business_codex/check_business_reads.py`.
It uses the fixed existing QA configuration and teacher, enforces MariaDB
session read-only mode on every connection, creates only private QA task
metadata/evidence, and never invokes a queue, model, login, role change or
production endpoint. Student names/IDs and session data are absent from its
evidence and console output.

## Native class-meal source contract

`authority.read_meals(store, claim, group=..., day=...)` calls the new private
`classroom._get_meals` / `student_meals._get_class_meals` observer chain. The
original public signatures and default service behavior remain unchanged.
Callbacks are trusted Python-only inputs, not accepted by any HTTP method.

- Saved snapshot: register the original class-meal document, its group and every
  snapshot Student, together with the native field projection. Do not recompute
  stored expected values from today's attendance or demand unrelated attendance
  permissions for a stored snapshot.
- No snapshot: the original `_calculate_student_details` captures group,
  enabled Student, fallback-name Student, and **all returned attendance/leave
  record IDs from the exact original queries**, before latest-record selection.
  The adapter checks the additional estimate-source field permissions and
  registers every dependency before returning any data. No later query is used
  to reconstruct the dependency list.
- Student-level estimates do not apply daily aggregate adjustments. Their
  `adjustment_records` is explicitly empty; the adapter rejects a claimed
  nonempty adjustment source rather than silently pretending the separate
  whole-school adjustment calculation has been audited here.

The successful projection is exactly `group`, `day`, `scope`, `revision`,
`meals`, `students`, matching the existing narrow meal tool. It never includes
the full document, attachment paths, attendance hints, leave reasons or the
other-class selector from the legacy response. Opening this tool does not save,
confirm, or revise any meal. Expected dinner zero is not proof of no service.

The reader does not truncate a class meal into a misleading partial roster.
Repeated Student dependencies are deduplicated before counting the 256-source
limit. If this complete read alone exceeds it, `scope_budget_exhausted` returns
`retry: use_business_view`; starting another identical task cannot fix it. If
only accumulated task dependencies exhaust capacity, the retry is `new_task`.
Neither error returns a partial student list or publishes a view.

`BusinessReads.dispatch(..., 'meal_read', ...)` owns the single `meal_counts`
view event. It uses the argument's exact group/day and the trusted task's meal
context (default lunch when absent), registers the selection and rechecks task
authority before/after publishing. The model cannot select another meal through
this tool's parameters. Do not emit the view again in the worker.

Re-runnable acceptance: `deploy/business_codex/check_meal_reads.py` performs
read-only preflight by default. `--run` additionally retains a new private QA
metadata/evidence directory; it does not run a model or write business records.
The fixed tests read the existing 2026-09-16 snapshot and first verify that the
2026-09-15 snapshot is absent. Every connection is database-enforced READ ONLY.
Evidence includes source-code hashes, scope coverage, precise view context and
fresh-connection before/after business-source digests, not raw pupil data.
