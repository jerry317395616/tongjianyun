# Fixed-assets acceptance: native acquisition and movement

## Candidate history fix, 2026-09-25 — isolated QA only

The Tongjianyun candidate now preserves cancelled Asset Movement history when
cancelling a native asset acquisition. It has **not been deployed to production**.
No ERPNext core source, production data, permissions, or site configuration was
changed. This is acquisition/movement acceptance, not complete asset-module,
browser, or Codex-driven write acceptance.

The final candidate passed four independent CNY 1,200 native lifecycles, each
with 39 checks, using the actual Frappe extended controllers (not monkeypatches):

| Acquisition | Asset creation | QA run | Result |
| --- | --- | --- | --- |
| Purchase Receipt | Manual | `d9d00de556` | 39/39 |
| Purchase Receipt | Automatic | `4f29d4652a` | 39/39 |
| Purchase Invoice (`update_stock=1`) | Manual | `bd978af31d` | 39/39 |
| Purchase Invoice (`update_stock=1`) | Automatic | `14e972f4bc` | 39/39 |

Every case checks native CWIP/liability GL, asset capitalization, exact source
item, quantity validation, location transfer and cancellation, refusal to cancel
an acquisition with a submitted asset, no-role denial (including source
cancellation), both financial reversals, and a fresh connection. The cancelled
Asset, both cancelled movements, movement child rows, reference type/name,
creation/modified timestamps and pre-existing Asset Activities survive. All
tested account balances return to that run's exact starting values, **not an
assumed zero**. Each report has `all_movement_history_preserved=true` and
`native_financial_reversal_complete=true`.

### Narrow compatibility extension

`tongjianyun.asset_history.PreserveAssetHistory` is registered through
`extend_doctype_class` for Purchase Receipt and Purchase Invoice. It replaces
only the two inherited acquisition cleanup helpers during cancellation:

- Cancelled movements and cancelled assets are history and are retained.
- Movement lookup includes both the reference DocType and name. A document from
  a different source type is not selected merely because its name matches.
- A still-submitted asset is refused. In automatic mode, the native
  `check_permission_and_not_submitted` check also refuses submitted movements,
  including ones without an acquisition reference.
- An unused automatic draft without cancelled movement history retains native
  `delete_doc(..., force=1)` cleanup, including native delete permission checks.
- A draft with cancelled movement history is retained and detached from the
  cancelled acquisition using native-style field clearing and `save()`; normal
  save permissions remain in effect. The historical movements are not rewritten.
- Non-cancellation/normal update paths delegate to the native methods. There is
  no `on_cancel` override, RPC endpoint, `ignore_permissions`, manual GL update,
  direct SQL state manipulation, or bypass of native source cancellation checks.

The native detach path already uses validation/mandatory flags because its source
has just been cancelled; the extension keeps those flags only for draft detach,
not financial posting or permission bypass. Compatibility was verified against
installed ERPNext `5b2952aa23305961326ffa3b557d5d0fb755f460` and its Frappe
class-extension mechanism. ERPNext upgrades must rerun these regressions because
the overridden helper behavior is version-dependent.

### Additional real draft-boundary regressions

Purchase Receipt run `f551b376ce` and stock Purchase Invoice run `006d9e4330`
each passed 14 checks. Native automatic draft creation/cleanup is exercised,
not mocked: an unused draft is deleted on source cancellation; a second draft
with a cancelled movement is kept; an additional submitted movement without a
source reference blocks cancellation. After that movement is cancelled, source
cancellation succeeds and a fresh connection verifies both cancelled sources,
the detached draft, the exact movement parent/child snapshots, and restored GL.
Native draft deletion can revert the naming series and reuse a deleted unused
draft's name; the report explicitly records this behavior.

The 14 focused unit tests cover delegation, exact source filtering, preservation,
submitted-record rejection, automatic cleanup, no stock invoice behavior, draft
detach and save/delete permission errors. Six standard-library guard tests pass
without any Frappe or database connection.

### Retained test failures and audit evidence

Two new incomplete runs were retained without cleanup or fabricated history:

- `d4341f00b0` stopped after 17 checks because the original activity-count test
  assumed a hand-created Asset. Native automatic creation uses `db_insert`, so
  it does not emit the additional "Asset created" activity. The corrected test
  explicitly distinguishes creation modes while still requiring submission and
  both movement activities. Its submitted synthetic asset/transfer remain.
- `08f37839bc` stopped after 7 checks because the test initially assumed a new
  automatic draft must get a different name after deleting the first draft.
  Native naming-series rollback legitimately reused it. The original cancelled
  source and second submitted source/draft remain. The corrected test records
  name reuse rather than changing native naming behavior.

Consequently later run baselines include these retained synthetic positions
(Fixed Asset CNY 1,200; CWIP CNY 1,200). Passing runs restore **their own** starting
balances. This is not a claim that the whole QA company has zero open positions.

All reports are private under
`/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925/`:
`asset-lifecycle-<run>.json`, `asset-draft-boundaries-<run>.json`, and
`asset-lifecycle-incomplete-<run>.json`. Earlier pre-fix evidence below remains
unchanged, including its deleted movement records; the fix does not reconstruct
historical data that was already deleted.

## Original pre-fix result, 2026-09-25

The dedicated isolated QA site completed a native CNY 1,200 fixed-asset
acquisition and financial reversal with 34 checks in run `d1df72a92b`.
It also exposed a native cancellation history defect. This is **not** complete
asset-module acceptance, browser acceptance, or evidence that every movement
record survives native receipt cancellation.

The tested chain was:

1. Insert and submit a synthetic `Purchase Receipt`: debit CWIP, credit
   Asset Received But Not Billed, exact balanced CNY 1,200 GL.
2. Insert a native `Asset` linked to the exact receipt item; duplicate quantity
   is refused. Submit the asset: debit Fixed Asset, credit CWIP, plus the native
   initial Receipt movement. Total CWIP nets to zero.
3. Submit a native `Asset Movement` from Receiving to Classroom. Location changes;
   acquisition amount and capitalization GL do not. Invalid source, same source
   and target, and a backdated transfer are refused.
4. Cancel the transfer: the original Receiving location is restored.
5. Cancel the asset: capitalization reverses and the initial movement is cancelled.
   The purchase receipt cannot be cancelled while its asset remains submitted.
6. Cancel the receipt: acquisition GL reverses. A fresh Frappe connection verifies
   cancelled receipt/asset state, exact source-row links, no active GL, and all
   three asset-account balances restored to their pre-run values.

The case uses `auto_create_assets=0`, CWIP enabled, and no depreciation. Neither
stock ledger nor depreciation schedule is created. All fixtures are synthetic,
the native validators and document methods run normally, and no direct SQL
balance, status, location or asset updates are performed by the test.

## Permission and scene evidence

- A new no-role synthetic user cannot read the Asset, create or cancel an Asset
  Movement, or open the Asset business view. Location and submitted movement
  remain unchanged after these rejected actions.
- Administrator business-view responses resolve the exact Asset, Asset Movement,
  and Purchase Receipt native document routes. These are backend response checks,
  **not** actual browser-save or conversational agent-execution evidence.
- There is no role grant to a real user, external payment, production mutation,
  worker, scheduler, or production/QA configuration change in this runner.

## Native cancellation defect: movement history can be deleted

Installed ERPNext's
`erpnext.controllers.buying_controller.BuyingController.delete_linked_asset()`
selects one `Asset Movement` by `reference_name == receipt.name` and force-deletes
it on Purchase Receipt cancellation. This happens even with automatic asset
creation disabled. The method does not distinguish the native initial Receipt
movement from a later Transfer linked to the same receipt.

In the completed run, receipt `MAT-PRE-2026-00038` and asset
`ACC-ASS-2026-00002` remain cancelled with reversed GL. Initial movement
`ACC-ASM-2026-00003` remains cancelled, but cancelled Transfer
`ACC-ASM-2026-00004` was deleted by native cancellation. The runner records full
pre-cancellation movement snapshots and the exact missing record rather than
misreporting preserved history. The financial reversal is complete, but
`all_movement_history_preserved` is explicitly false.

The first run `37f612dc82` deliberately failed the original strict history
assertion after 28 passed checks. Its incomplete report and committed synthetic
records remain available. A fresh read confirmed that its transfer was also
removed by the same native method. No native code was patched and no deleted
movement was fabricated or restored.

The candidate extension and strict regressions above address this tested history
defect for future cancellations. They do not alter these original reports or
retroactively restore missing movements. Production remains unchanged until a
separate reviewed deployment.

## Evidence and rerun

The complete report is private on the server:

`/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925/asset-lifecycle-d1df72a92b.json`

The incomplete first report is retained alongside it:

`/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925/asset-lifecycle-incomplete-37f612dc82.json`

Run only with the exact isolated source/sites paths:

```sh
UNIFIED_BUSINESS_SOURCE=/home/zyd/frappe/remote-workspace/unified-business-20260925 \
UNIFIED_BUSINESS_SITES=/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925/sites \
/home/zyd/frappe/native-bench/env/bin/python \
/home/zyd/frappe/remote-workspace/unified-business-20260925/deploy/unified_business/check_asset_lifecycle.py
```

The runner validates the exact QA sites directory, site marker, DB loopback port
23316 and database/user `tgy_blueprint_qa`, no DB socket, Redis loopback port
23379, paused/disabled scheduler and disabled developer mode. It repeats effective
configuration validation before every DB connection and verifies candidate view
module source paths. The separate standard-library test
`deploy/unified_business/test_asset_lifecycle_guard.py` checks guard rejection
without importing Frappe or connecting to a database.

Appending `--inspect-run d1df72a92b` performs read-only inspection of the exact
retained run's source, asset and movement records; it does not create fixtures.
For the candidate regression, append `--auto-create` for automatic assets,
`--source-invoice` for a stock Purchase Invoice, or both. Append
`--auto-create --draft-boundaries` (optionally `--source-invoice`) for the native
draft cleanup/history boundary chain. `--unit-tests` runs the 14 unit tests in
the same strictly guarded site context without creating lifecycle fixtures.
The lifecycle refreshes only the isolated QA `app_hooks` cache and asserts that
both controllers load the candidate extension before creating fixtures.

## Still untested

Depreciation posting and cancellation, employee-custodian issue/return,
maintenance and repair, revaluation, disposal/sale, grouped and composite assets,
multi-currency acquisition, ordinary-user positive permissions, asset browser
editing/saving and Codex-driven asset writes still require their own acceptance.
