# Two account permission tiers

Authorized deployment on child.myyr.top, 2026-09-11.

- Administrator keeps native superuser handling. Frappe does not attach role profiles to standard users.
- Explicitly selected internal users use the `童健云业务操作` Role Profile.
- Existing system roles and existing role profiles are retained. Guest, test and integration accounts are not selected automatically.
- The profile combines existing Tongjianyun role gates, I-ONE Agent User (not Agent Manager), and a constrained Business Operator role.
- Official business permissions are installed as site Custom DocPerm records, preserving prior permissions. No official application source, fields or table definitions change.
- Reference configuration is read-only. Account, role, script and system settings administration is excluded. Personal self-profile access remains native Frappe behavior.
- Business users can operate across the school's classes, not just their previous teacher assignments. ERPNext validation, locked-period checks and document state transitions still apply.
- Recipe restore accepts Business Operator plus recipe write permission; no System Manager role is necessary.

## Operations

`tongjianyun.business_access` is administrator-only and is not whitelisted. Call `plan()` and `snapshot(explicit_users)` before `install(explicit_users)`. The caller owns the transaction and must run `verify(explicit_users)` before commit. Never auto-discover or bulk upgrade all System Users.

The one-time deployment saved role assignments and previous Custom DocPerm rows in a private JSON file under `/home/zyd/frappe/backups/access-control/`, outside Git. Rollback must restore only those selected users and target permission rows using ORM, retaining other subsequent changes. A rolled-back Role Profile preview may leave its document-action lock; release only that preview's lock after confirming no committed profile/job exists.

## Verification

50 unit tests passed, including attendance scope, meal estimates and procurement regression checks. Transactional preflight confirmed required create/submit permissions, denied administration permissions and real read-only recipe execution inspection (25 meals) plus class list (3 groups) for both target accounts. No purchase, receipt, invoice or payment was executed for testing.

Future business accounts require explicit assignment to this profile by Administrator; service and parent accounts must not be assigned automatically. Browser and full financial workflow execution are not part of this permission-only verification.
