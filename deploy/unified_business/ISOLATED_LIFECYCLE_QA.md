# Isolated lifecycle acceptance site

This fixture is **not** the production `child.myyr.top` site. It was provisioned
from empty MariaDB storage with the existing Frappe runtime and standard app
install hooks. No production database or private configuration is copied.

## Fixed test scope

- Root: `/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925`
- Sites path: `<root>/sites`
- Site: `unified-business-acceptance.localhost`
- Database: `tgy_blueprint_qa` at `127.0.0.1:23316`
- Dedicated Redis: `127.0.0.1:23379` (cache DB 0, queue DB 1, socketio DB 2)
- Runtime: `/home/zyd/frappe/native-bench/env/bin/python`
- App dependencies: Frappe, ERPNext, Education, Tongjianyun
- Containers: `tgy-blueprint-lifecycle-qa-20260925-db` and `tgy-blueprint-lifecycle-qa-20260925-redis`
- Container ownership label: `codex.isolation.owner=tgy-blueprint-lifecycle-qa-20260925`

No HTTP service, worker, or scheduler is started. Both published container ports
bind exclusively to loopback. Random credentials are retained in private files
under the test root; do not print, commit, or copy them into test reports.

## Provision / resume safely

Copy `prepare_isolated_site.py` to
`/home/zyd/frappe/remote-workspace/prepare_blueprint_isolated_site.py`, then run:

```sh
/home/zyd/frappe/native-bench/env/bin/python \
  /home/zyd/frappe/remote-workspace/prepare_blueprint_isolated_site.py
```

The script reuses resources only if their ownership markers match. Existing
fully initialized sites are validated and missing dependency apps are installed.
A partial Frappe bootstrap is retained for inspection, never automatically
dropped or force-recreated. `--status` prints non-secret readiness metadata.

## Lifecycle test startup contract

Set `UNIFIED_BUSINESS_SITES` to the exact sites path above. Set
`UNIFIED_BUSINESS_SOURCE` to the candidate Tongjianyun source directory used by
the acceptance runner, without deploying it to production.

Before importing/initializing Frappe, remove inherited `FRAPPE_DB_*` and
`FRAPPE_REDIS_*` environment overrides and set `FRAPPE_BENCH_ROOT` to the test
root. Set `PYTHONDONTWRITEBYTECODE=1` to avoid source-tree bytecode artifacts.

The runner must validate these guards **before connecting or writing**:

1. `sites_path` resolves exactly under the dedicated remote-workspace test root.
2. Site name equals `unified-business-acceptance.localhost`.
3. Site configuration has `unified_business_acceptance == 1`.
4. DB host is `127.0.0.1`, port is `23316`, and name/user are `tgy_blueprint_qa`.
5. No `db_socket` is configured; all Redis URLs point to `127.0.0.1:23379`.
6. `developer_mode` remains disabled, and no workers/scheduler are running.

Use `frappe.init(site, sites_path=sites_path)` and `frappe.connect()`. The test
config supplies credentials automatically. Test synthetic records and custom
DocTypes only; do not read production data or copy fixtures from production.

## Evidence and retention

`ready.json` is a non-secret readiness report. `install.log` records standard
schema installation. Retain the dedicated site, DB data directory, and containers
until the parent task finishes acceptance. Cleanup is intentionally not automated:
verify the exact root and container ownership labels before stopping/removing
only these two test containers. Never use blanket Docker cleanup or broad deletes.
