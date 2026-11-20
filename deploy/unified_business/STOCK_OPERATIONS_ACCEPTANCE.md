# Source-bound inventory verification and restricted native repair

## Release boundary

Production supports **read-only verification**, not repair. The service has a
hard-coded repair gate for the fixed isolated acceptance site, resolved site
path, QA database host/port/name/user, marker, Redis endpoints and paused
scheduler configuration. There is no production `enable_repair` flag. Direct
POST calls outside that exact environment fail before acquiring business locks
or mutating records. Do not present the production business view as a deployed
inventory repair feature.

The candidate contains `stock_operations.inspect_stock()` and
`stock_operations.repair_stock()` to retain and test the complete proposed
contract. It does not modify ERPNext, start a global worker, change native
permissions, or automatically fix historical records.

## Contract

`inspect_stock(source_doctype, source_name)` allows only Purchase Receipt
(including returns) and Stock Entry. Submitted/cancelled source SLEs determine
the Item/Warehouse pairs. Drafts return `not_posted`, not a false completion.
It verifies original document/field/mask permissions and an enabled user, then
returns:

- Exact source, company, stock currency and SHA-256 revision bound to the actor.
- Per-pair current Bin quantity/value, last effective SLE quantity/value,
  identity/time, unit, differences and repair eligibility/reason.
- Relevant unfinished/failed native valuation jobs, including other vouchers
  affecting the same Item/Warehouse. Hidden relevant jobs cause a permission
  denial instead of being treated as absent.
- Summary status `not_posted`, `pending`, `blocked`, `mismatch` or `consistent`.

Only a completed ledger comparison is claimed. Values describe **current**
inventory for pairs implicated by the source, not inventory at the source's
historical posting time. Never aggregate incompatible item units/currencies.
This does not reconcile GL, batch/serial subledgers, reservations, supplier
invoices or payment.

`repair_stock(source_doctype, source_name, targets, revision, confirm)` requires
POST, `confirm='recalculate'`, the matching fresh revision, and exact
`[{item_code, warehouse}]` targets from eligible discrepancy rows. Bin names,
arbitrary columns/SQL, unrelated pairs, duplicate targets, Guest, disabled
accounts, insufficient original write permissions, pending valuation and
unnecessary/repeated repairs are rejected. Default Stock Manager roles do not
grant Bin write; this service does not grant it either.

The test-only write path locks the source, deterministic SLE ranges, original
Item/Warehouse/Bin and relevant valuation rows. It checks MariaDB repeatable-read
or serializable isolation **and** `innodb_snapshot_isolation=1`, rereads the
revision, calls `Bin.recalculate_values()`, and verifies source/ledger stability
and quantity/value consistency. It adds a source-linked Info Comment with the
actor, revision and exact targets. It never commits independently. Postcondition
failure rolls back the savepoint; a native deadlock/CHECKREAD conflict rolls
back the entire transaction because MariaDB has already removed savepoints.
Conflicts are not automatically retried.

Native `Bin.recalculate_values()` also recomputes valuation rate, planned,
indented, ordered, reserved, production/subcontract/production-plan reservations
and projected quantities. It is **not** a two-column quantity/value update.
The UI confirmation must state that complete native scope. Bounds are 20 pairs,
2,000 SLEs per pair, and 1,000 candidate valuation jobs; exceeding them stops the
operation, rather than treating a truncated history as complete. Only FIFO and
Moving Average are supported by this comparison; Standard Cost is blocked for
separate native analysis.

## Real isolated acceptance

Latest complete evidence run: `96887eaea8`, **35 real assertions**. The candidate
unit suite has **21 tests**. Evidence is retained at:

`/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925/stock-operations-96887eaea8.json`

The runner `check_stock_operations.py` checks the fixed QA config before
connecting, clears inherited DB/Redis overrides, uses only synthetic fixtures
and the retained synthetic Company, and never copies production records. Native
repost execution is limited to that new Item/Warehouse and its exact receipts.
Those native jobs commit internally; prior partial/failed runs are retained.

Verified evidence:

1. Receipt 5 at rate 3 creates quantity 5/value 15. Return 2 then cancellation
   restores quantity 5 but leaves native Bin value 9 versus effective SLE 15.
2. Queued valuation forbids repair and completion claims. Completing only its
   original native jobs still leaves the reproduced Bin discrepancy observable.
3. Unauthorized/read-only/Guest/disabled actors, stale revisions, GET, missing
   explicit confirmation, arbitrary Bin fields/targets and duplicates fail.
4. Explicit test repair restores value 9 to 15 while preserving quantity 5,
   cancelled source status, original receipt rows and correct derived totals.
5. Two independent same-revision repairs commit exactly once. Native stock
   submission blocks while repair locks are held and can proceed after release;
   this contention probe rolls back its synthetic write.
6. A later real Stock Entry adds one; a fresh connection sees quantity 6/value
   18 and the exact newest effective ledger identity.

### Important native concurrency dependency

The installed `stock_balance.update_bin_qty()` obtains Bin through a normal
non-locking `get_bin()` read, then uses whole-row `db_update()`. A normal PO
submit first updates Item.last_purchase_rate and was blocked by the adapter's
Item lock. The separate native **PO Close** path does not take that Item lock.

The runner therefore executes the actual permission-checked PO `update_status`
service in a second process. A transparent test-only wrapper observes its
original `get_bin()` result without changing returned data or native writes.
It reads stale value 9, waits on the real Bin row lock while the adapter restores
15, and then attempts the stale whole-row write. On the recorded QA database:

- MariaDB `11.8.8-MariaDB-ubu2404`
- `REPEATABLE-READ`
- `innodb_snapshot_isolation = 1`

the stale write fails with native CHECKREAD 1020 (`QueryDeadlockError`), its
transaction rolls back, and value remains 15. **No successful stale overwrite
was observed in this tested configuration.** This is an engine-dependent
conflict rejection, not evidence that every ERPNext native writer takes the
adapter's locks. MR/Sales Order/manufacturing/reservation races and production
database deployment semantics remain unverified, which is why production repair
is hard-disabled in this release.

## Left business view integration

Use a `stock_reconciliation` selection containing only `source_doctype` and
`source_name`. Render quantity and value pairs separately with units and stock
currency, pending-job warnings and fresh-view action. Show a repair control only
when the backend returns eligible exact targets, using its revision and a
second explicit confirmation. Never dispatch a repair merely because the
assistant selected the diagnostic view. After a successful test repair, rerun
inspection; after any conflict, ask for a fresh check rather than blind retry.

Browser rendering/confirmation and the production read-only route are root
integration responsibilities; this evidence is backend/service acceptance only.
