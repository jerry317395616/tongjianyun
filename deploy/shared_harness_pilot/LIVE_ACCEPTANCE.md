# Shared runtime live acceptance — 2026-09-07

The candidate is **not promoted**. Production remains unchanged.

## Verified against the real local runtime

- Clean private temporary profile starts successfully on loopback port 13093.
- Unauthenticated employee status returns 401.
- Signed handoffs for both pilot teachers exchange successfully.
- Each account sees only its own newly created session; cross-account reads fail.
- Frappe permission-filtered Student query completes (currently returns no rows).
- Real Qwen turn settles and produces an assistant text history record.
- Temporary runtime is terminated after verification; no permanent second Harness.

The credentials provider now references the existing protected credentials file by
path. No credential contents are copied into this repository or emitted.

## Promotion blocker

The live read-only pilot verification reports both teachers still assigned to their
respective groups (中班 / 大班), but **zero assigned and zero visible students**.
This differs from the earlier 101 / 119 acceptance baseline. Therefore a non-empty
cross-class student isolation acceptance cannot currently be certified. No student
or group membership has been changed by these checks. Do not weaken this gate just
because empty lists trivially do not overlap.

`smoke_shared_runtime.py` runs `accept_shared_http.py` and deliberately returns a
failed promotion gate if the student sample is empty, even when the HTTP protocol
and model response pass. `accept_shared_identity.py` remains the separate full
two-class read-isolation acceptance. Browser acceptance is still outstanding.

Next: confirm which current non-empty classes the two pilot accounts should use,
then rerun full data isolation acceptance before proxy/public entry cutover.
No DocType, schema, permissions metadata, or business records were modified.
