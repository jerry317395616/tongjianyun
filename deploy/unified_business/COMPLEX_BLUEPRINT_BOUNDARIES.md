# Complex blueprint boundary acceptance

The runner `check_complex_blueprint_boundaries.py` only accepts the fixed,
marker-protected isolated site described in `ISOLATED_LIFECYCLE_QA.md`. Each run
uses random synthetic business keys and ordinary permission-checked Document
writes. No production data is read or written.

## Final candidate result

After the candidate fixes, run `10305e0151` passed **57 of 57** checks with
`critical_findings: []` and `all_boundaries_passed: true`. Evidence:

`/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925/complex-blueprint-boundaries-10305e0151.json`

Both synthetic parent types use the independent `Tongjianyun Advanced `
namespace. The compound downgrade is now rejected; legal native new child rows
still work. All altered metadata, physical tables and columns were restored,
and a fresh connection verified active schemas and original record values.

## Coverage

- Child row names cannot adopt another parent's row, duplicate a row, impersonate
  a different child type, or silently reference a nonexistent persisted row.
- Normal ORM appends and native Desk `__islocal` new rows remain compatible.
- Direct child-document writes are blocked.
- Negative/nonfinite/nonnumeric/limit-breaking inputs, fractional Int sources,
  multiplication/sum overflow, empty required tables, missing required labels,
  and more than 500 rows are rejected.
- Stored calculated totals overwrite client-supplied amounts; no-workflow v2
  tables can still save and calculate normally.
- Ungranted users and Guest cannot create, update, activate, or read records.
- Missing/changed manifests, field changes, permission expansion, missing table
  fields, missing physical tables and missing physical columns stop activation
  and runtime writes. A combined v2-to-v1-looking metadata downgrade is tested.
- Metadata changes and physical-table/column renames affect only that run's
  synthetic types and are restored in `finally`; persisted rows and values are
  verified after restoration and through a new connection.

No arbitrary SQL business-state updates are used. Reversible SQL table/column
renames are solely physical-DDL fault injection for uniquely generated test
types, with validated exact identifiers. Activation may commit DDL and must not
be wrapped in a rollback-dependent savepoint. Negative record writes are rolled
back after each test. No previous test evidence is deleted.

## Independently reproduced defects

1. **Nonexistent persisted child name:** an existing row renamed to an unknown
   identifier was accepted. Frappe updated no child row at that identifier and
   removed the original row; the parent retained total 8 while its one remaining
   persisted child summed to 2. The fixture was rolled back. Evidence:
   `complex-blueprint-boundaries-ea4c95e6cd.json`. The candidate guard was then
   updated to reject missing non-local rows, while ordinary and `__islocal` new
   rows remain supported.
2. **Cached physical schema:** cached table/column introspection could report a
   physically missing table as active. A call to `table_exists(cached=False)`
   itself refreshes Frappe's table cache, so the test checks candidate state
   *before* doing diagnostic uncached reads. Candidate checks now read current
   physical tables and columns. Tables/columns are restored and caches refreshed
   in the fixture cleanup, not silently repaired by activation.
3. **Version downgrade bypass:** a table-only v2 type with its Table field removed
   and description replaced by a v1-looking marker had `state=conflict`, but a
   normal record save still succeeded through the legacy-v1 fast path. Evidence:
   `complex-blueprint-boundaries-f01f299336.json` (56 checks passed, 1 failed).
   The separate v2 parent namespace now prevents a v2 business from entering
   the legacy-v1 compatibility branch, verified in the final run above. Previous evidence remains
   retained, not rewritten as a passing run.

All evidence files are under:

`/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925/`

The earlier 54-check report `complex-blueprint-boundaries-16c94a835b.json`
predates the additional downgrade case and is not proof that case was fixed.

## Boundaries of this acceptance

These are server-side ORM and schema checks, not browser-rendering or concurrency
tests. They do not authorize arbitrary business code, permissions, SQL, workflows,
stock posting, or financial accounting through a blueprint. Native review
transition hardening and its role/owner behavior are tested separately.
