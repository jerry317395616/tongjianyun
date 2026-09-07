# Unified live deployment under /home/zyd/frappe

Effective 2026-09-07: one live shared Harness; no separate test deployment.
Validation scripts may exercise this live service. They do not create a second service.

| Directory | Purpose |
| --- | --- |
| native-bench/apps | Authoritative Frappe application source; business changes in tongjianyun |
| deepseek-harness | Harness source |
| config/harness | Active runtime, reverse-proxy and identity configuration; private credentials (never commit) |
| state/harness | Shared conversations, ownership, identity assertions and Unix socket |
| logs/harness | Proxy diagnostics; SSO access logging disabled |
| backups/harness | Cutover manifests; old configuration retained for rollback |
| dify | Existing Dify directory; not moved in this change |

systemd registration remains in ~/.config/systemd/user, as required for the zyd
user service manager. The active overrides are also recorded under config/harness.
The parent /home/zyd/frappe is now 0755 rather than 0775: the identity authority
requires socket parents not to be group-writable. No recursive permission changes.

## Live entry

https://harness.myyr.top redirects to /employee/chat/. Existing Frappe /sso links
now exchange only for an account-scoped employee session, not a Host session.
Admitted accounts: existing admin (317395616@qq.com) and the two teacher pilot
accounts. Administrator is not admitted. Frappe permissions continue to apply.
Read scope remains Student, Student Group, Student Attendance, Student Leave Application.
This does not yet grant recipe/ERP operations or writes.

Root and chat assets are public; employee APIs require authenticated account cookies.
All other routes, including Host RPC, are denied by the proxy.

## Acceptance and limitations

Public HTTPS HTML returns 200. Local live proxy acceptance passed signed login,
per-account conversation isolation, cross-account rejection, permission-filtered
read and a real Qwen response. The current Student result is empty, explicitly
accepted for live rollout by the operator; full non-empty data isolation is not
certified. Embedded browser navigation timed out, so visual verification is pending.

Old deepseek-harness-state, pre-fork backup, recovery directories and external
legacy configs remain intentionally untouched. This cutover organizes the active
shared Harness, not every existing platform service. No unrelated files deleted.

For rollback, stop the proxy, remove only the exact 90-shared-live.conf overrides
listed in backups/harness/<timestamp>/overrides.json, daemon-reload, restart the
three identity refresh services, authority and runtime, then start the proxy.
Original units and configs remain intact. No DocType/schema/data migration occurred.
