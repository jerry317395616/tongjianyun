# Procurement and stock lifecycle acceptance

## Scope and evidence

The runner `check_procurement_stock_lifecycle.py` refuses every site except the
fixed isolated site documented in `ISOLATED_LIFECYCLE_QA.md`. It creates new
synthetic Supplier, Item and Warehouse records and reuses only the retained
synthetic `QA Meal` Company. It does not copy production data, start workers,
change ERPNext source, bypass permissions, or write SQL document statuses.

Latest completed run: `c5c971c156`, 41 assertions passed. Evidence is retained at:

`/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925/procurement-stock-lifecycle-c5c971c156.json`

These assertions include native repair checks. The report intentionally says
`native_flow_complete_without_repair: false`; this is **not** evidence that the
unmodified native cancellation flow is defect-free.

Verified path: PO draft and submit; official PO-to-receipt mapper; receipt 4 then
6 against an order of 10; stock ledger and Bin quantity; configured over-receipt
rejection; return 2; cancel return; cancel both receipts; cancel order; permission
denials; fresh-connection verification. Drafts never alter actual stock. Duplicate
submit is native idempotence without new stock entries; duplicate cancel is
rejected by native validation without a second reversal.

Record views were verified against the exact synthetic document and Item IDs,
native operation routes, task-owned SSE selection, and current warehouse Bin.
This is a backend integration acceptance, **not** a browser-rendering acceptance.

## Finding 1: mapped returns must cross the normal Document boundary

In the installed ERPNext version, `PurchaseReceipt.__init__` constructs
return-specific status updaters only when `is_return` is already true.
`purchase_receipt.mapper.make_purchase_return()` sets that flag after building
its first Python object. Calling that object's `insert()/submit()` directly
updated stock and PO received quantity, but left PO Item `returned_qty` at zero.

The native Desk path serializes the mapped result and constructs a new Document
when saving. Server-side business adapters should use that same boundary:

```python
mapped = make_purchase_return(original_receipt_name)
# Apply the user's requested return rows/quantities to the draft payload.
draft = frappe.get_doc(mapped.as_dict())
draft.insert()
draft.submit()
```

Do not add `ignore_permissions`, mutate DocType metadata, or update quantities
directly in SQL. Verify the saved return references the exact original receipt
and that PO `received_qty` and `returned_qty` both match the intended movement.

## Finding 2: successful cancellation/reposting can leave stale Bin values

This installed ERPNext version reproduced all three mismatches below, even after
the applicable native `Repost Item Valuation` job reached `Completed`:

| Operation | Actual quantity | Stale Bin value | Correct value |
| --- | ---: | ---: | ---: |
| Cancel return of 2 at rate 3 | 10 | 24 | 30 |
| Cancel second receipt of 6 | 4 | 30 | 12 |
| Cancel first receipt of 4 | 0 | 12 | 0 |

Source inspection points to `stock_ledger.update_entries_after`: the constructor
initializes `prev_sle_dict`, but `build()` calls `initialize_reposting()`, which
clears it. When cancelling the latest valid ledger position leaves no future
valid rows to process, `update_bin()` iterates an empty dictionary. Quantity is
updated elsewhere while the prior Bin stock value remains.

The runner preserves every pre-repair state under `observed_defects`. It then
verifies the existing permission-checked `Bin.recalculate_values()` method reads
the last valid stock ledger and restores the correct quantity/value. These calls
are listed separately under `verified_native_repairs`. No ERPNext patch has been
deployed or made by this test.

## Required business-operation completion checks

For a future Codex business-operation adapter, a returned document ID or changed
`docstatus` is not sufficient evidence of completion:

1. Read back the exact persisted PO, receipt/return, and their child links.
2. Check actual received/returned quantities and configured allowance.
3. Verify stock ledger and Bin quantity for the exact Item/Warehouse.
4. Check relevant native valuation jobs. A queued/failed job is pending work,
   not a completed financial result. Never drain a global queue for one request.
5. Read back Bin value as well as quantity. If the known discrepancy is present,
   report it; after authorized native repair, reread and verify again. Never set
   stock values directly to the expected answer.
6. Publish the exact saved document selection and refresh the stock business
   view. A dispatched SSE view is not proof the browser has loaded it.

The acceptance site deliberately has no worker. Its runner executes only native
valuation jobs matching the synthetic Item/Warehouse or its exact receipt IDs.
Those native jobs commit internally; partial fixtures can therefore remain after
a failed acceptance run. They are retained as evidence, never automatically
deleted or silently reset.

Not yet covered: serialized/batched or expiring food stock, multi-currency/tax
accounting, complex approvals, multiple simultaneous operators, supplier billing
and payment, or rendered browser interaction. These need separate scenarios.
