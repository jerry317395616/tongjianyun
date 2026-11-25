#!/usr/bin/env bash
set -euo pipefail

bench_root="${1:?Usage: bash scripts/bootstrap-bench.sh /path/to/empty-directory}"
app_root="$(cd "$(dirname "$0")/.." && pwd)"
bench_root="$(realpath -m "$bench_root")"
if [[ -e "$bench_root" ]]; then
  echo "Choose a directory that does not yet exist: $bench_root" >&2
  exit 1
fi

mkdir -p "$bench_root"/{apps,sites/assets,logs,config}
fetch_app() {
  local name="$1" revision="$2" destination="$bench_root/apps/$1"
  git init -q "$destination"
  git -C "$destination" remote add origin "https://github.com/frappe/$name.git"
  git -C "$destination" fetch --depth=1 origin "$revision"
  git -C "$destination" checkout -q --detach FETCH_HEAD
}

fetch_app frappe f97abad5e29703d9bde092d563c95f70e6bf3847
fetch_app erpnext 3768e9c98b1f4aff2e388c6267a79e0aaa4cae7c
fetch_app education 444cc8efc10005c160d64b9f8fea8507a4d9392a
ln -s "$app_root" "$bench_root/apps/tongjianyun"
printf '%s\n' frappe erpnext education tongjianyun > "$bench_root/sites/apps.txt"
printf '{}\n' > "$bench_root/sites/common_site_config.json"

python -m venv "$bench_root/env"
"$bench_root/env/bin/python" -m pip install \
  -e "$bench_root/apps/frappe" -e "$bench_root/apps/erpnext" \
  -e "$bench_root/apps/education" -e "$bench_root/apps/tongjianyun"
for app in frappe erpnext education tongjianyun; do
  ln -s "$bench_root/apps/$app/$app/public" "$bench_root/sites/assets/$app"
done
