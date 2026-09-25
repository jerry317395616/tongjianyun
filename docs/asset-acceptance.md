# Fixed-assets acceptance: native acquisition and movement

## Result, 2026-09-25

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

Before claiming complete asset handling, the acquisition cancellation history
behavior needs a separately scoped native-compatible fix and regression test.
Do not silently declare this path fully covered because GL balances are correct.

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

## Still untested

Depreciation posting and cancellation, employee-custodian issue/return,
maintenance and repair, revaluation, disposal/sale, grouped and composite assets,
multi-currency acquisition, ordinary-user positive permissions, asset browser
editing/saving and Codex-driven asset writes still require their own acceptance.
