#!/usr/bin/env bash
set -euo pipefail

bench_root="$(realpath "${1:?Usage: bash scripts/check-site.sh /path/to/test-bench}")"
site=tjy-demo.test
db_port="${TJY_DB_PORT:-3306}"
redis_url="${TJY_REDIS_URL:-redis://127.0.0.1:6379}"
: "${TJY_DB_PASSWORD:?Set a root password for the disposable database instance}"
cd "$bench_root/sites"
if [[ -e "$site" ]]; then
  echo "The disposable site already exists in $bench_root" >&2
  exit 1
fi

bench() {
  "$bench_root/env/bin/python" -m frappe.utils.bench_helper frappe "$@"
}

bench set-config -g redis_cache "$redis_url"
bench set-config -g redis_queue "$redis_url"
bench set-config -g redis_socketio "$redis_url"
bench new-site "$site" --db-host 127.0.0.1 --db-port "$db_port" \
  --db-root-password "$TJY_DB_PASSWORD" --admin-password "$(openssl rand -hex 20)"
bench --site "$site" install-app erpnext education tongjianyun
bench --site "$site" set-config tongjianyun_demo 1 --parse
bench --site "$site" execute tongjianyun.demo.seed
bench --site "$site" execute tongjianyun.demo.verify
bench --site "$site" migrate
bench --site "$site" execute tongjianyun.demo.seed
bench --site "$site" execute tongjianyun.demo.verify
