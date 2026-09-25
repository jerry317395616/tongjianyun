# Shared Codex: native weekly recipe integration

2026-09-26 candidate implementation. This is one part of the full-project goal,
not a claim that every business workflow or unknown extension is complete.

## Execution path

The ordinary business worker exposes `recipe_read` and, only with the same
durable write runtime installed, `recipe_save`. It shares the Codex binary,
task store and write ledger with the other business tools. The recipe reader
must use the exact store and its authorizer, including proposal/attachment
source checks where present; a same-site but different authorizer is rejected.

`recipe_read` uses a fresh owner-bound native context and complete original
recipe visibility. Dish pages retain ingredient amounts and original units;
content hashes prevent mixing pages after an edit. Empty visibility is not a
claim that the site has no recipe. Historical task replay checks the recipe
aggregate's current native permissions, matching the original history reader
without retaining grants to deleted/rebuilt detail row IDs.

`recipe_save` passes a finite full replacement to the original services. It
does not create a second copy when editing, change dates, bypass locked days,
archive, publish, procure, or confirm actual meals. Original unchanged-portion
quantity metadata is preserved by `save_recipe_edit`; changed portions follow
that native service's existing invalidation behavior.

Only the ledger's reserved immutable operation UUID determines a new recipe's
identity. The same UUID reaches transaction construction and independent
readback, including receipt replays. The model cannot supply an actor, site,
operation UUID, recipe ID for creation, or lifecycle fields. Existing recipes
keep their original identity and `modified` conflict check and full history.

Site/week and existing-recipe resource fences cover concurrent requests across
users/tasks. Commit uncertainty or an undrained connection never becomes a
successful save and never releases the unknown-result fence for blind retry.
The original database also enforces one current recipe per natural week with
locking current reads. Only an acknowledged commit followed by a new native
read permits readback; `readback_complete=false` explicitly means a partial
page, not full-week verification. The recipe reader publishes the authorized
left-view selection once per readback, without a duplicate publisher.

## Verification boundaries

The native QA checker is `deploy/business_codex/check_recipe_native.py`.
Prepare is read-only; run requires an explicit UUID and retains its synthetic
records, attempt, operation identities, receipts and evidence. It is fixed to
the existing isolated QA database, future week 2037-01-05 through 2037-01-11,
and the existing synthetic teacher or explicitly selected synthetic manager.
The teacher currently lacks recipe permissions and must stop without changes.
The manager uses existing System Manager/Academics User permissions; success
under that account does not prove teacher authority and does not add roles.

The test recipe deliberately has no ingredients, so the original empty-source
rule prevents ingredient matching from being queued. This checks the native
save/history/uniqueness chain, not real upload parsing, model interpretation,
RQ, browser SSE, ingredient matching, publishing, or procurement. Baselines
cover Recipe, Dish, Ingredient and corresponding Versions, not the whole site.

Actual native run `2bb159c6-4ff6-4f73-afdd-3a7e5cddd9ef` passed **9/9** checks:
two native commit acknowledgements, the same recipe identity after editing,
retained original history, and two fully drained rollbacks specifically
classified from original service errors as stale revision and duplicate week.
An unrelated rollback cannot count as either negative test. The final host
gate is closed with zero active or uncertain writes. Independent review found
that all four recipe baseline tables were empty before this run: the baseline
check therefore proves no additional out-of-run records in this empty fixture,
NOT preservation of a nonempty preexisting recipe library. Only this run's
synthetic recipe and history remain. Nonempty-library protection still needs
separate real acceptance rather than a vacuous unchanged-baseline claim.

Evidence path:
`/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925/business-recipe-native-2bb159c6-4ff6-4f73-afdd-3a7e5cddd9ef/evidence.json`

Evidence SHA256:
`eab1f730c3360c496fe0332067732c3bcc86d4a5ceb466534d32761bad768b16`.
Checker SHA256:
`dcfe4c7efd022a2ec267b73dd557b9e374f45843a06735e563e80c26c1e2e728`.
The UUID must not be rerun or its retained week adopted for another test.

Before execution, independent review caught an RR snapshot window in the QA
empty-week guard. It was fixed to use locking current reads after the weekly
lock, and preflight was repeated against the new hashes. Read-only preflight
and post-commit readback remain normal read-only queries. Native service
uniqueness already used locking current reads and did not need replacement.

The production checkout remains separate; syncing this candidate does not
deploy it. No production restart, migration, role or AppArmor change occurred.

Final candidate verification: Linux/Frappe database-enforced read-only suite
**1086/1086**, frontend component suite **177/177**, Linux deployment pure suite
**302/302**. The 25 native-checker pure tests are included in 302, not additive.
An independent new read-only connection matched the final native snapshot and
baseline; its transaction verified `tx_read_only=1`. The private synthetic task
is intentionally not marked completed without real runtime proof; only its
host-write ledger is closed. It is not an active web/RQ task.

## Remaining full-goal work

Complete real upload -> Codex -> unique weekly recipe edit -> browser readback,
including ingredient preservation, before claiming that user journey. Verify
the real two-account proposal handoff/acceptance/activation path, then extend
the same actual-execution contract across the other professional Frappe state
chains, independent services, and unknown complex code development/deployment.
Do not replace those requirements with tool counts or passing unit tests.
