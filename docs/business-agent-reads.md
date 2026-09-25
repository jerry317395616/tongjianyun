# Source-aware discovery and class roster

Trusted worker integration:

```python
reads = BusinessReads(authority, store)
result = reads.dispatch(claim, tool_name, arguments)
# TOOL_INSTRUCTIONS is a fixed {tool_name: Chinese usage description} mapping.
```

The trusted outer worker supplies `WorkerClaim`. Neither tool accepts owner,
site, task, SQL, method, file path, permission overrides or write instructions.
`scene_bootstrap` does not publish a view. `class_students_read` **already
publishes** a selection-only `class_students` event with that claim after full
source registration; do not emit it a second time. Its display receipt means
requested, not that the browser has loaded the view.

| Tool | Arguments | Meaning of returned counts |
| --- | --- | --- |
| `scene_bootstrap` | Required `day`; optional `meal`, `after`, `page_size` | `page_count` is this page. `visible_group_count` exists only when the first page contains all currently visible enabled classes. Never a school-wide guarantee. |
| `class_students_read` | Required canonical `group`; optional `cursor`, `page_size` | `page_count` is this page. `visible_class_count` is non-null only when scanning from the first page finishes completely. It is current visible enabled membership, not attendance, meals or historical enrollment. |

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
this trusted tool registry separately; these two tools are not a claim that all
Frappe business operations have already been integrated.

Re-runnable isolated acceptance: `deploy/business_codex/check_business_reads.py`.
It uses the fixed existing QA configuration and teacher, enforces MariaDB
session read-only mode on every connection, creates only private QA task
metadata/evidence, and never invokes a queue, model, login, role change or
production endpoint. Student names/IDs and session data are absent from its
evidence and console output.
