#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
url="${APP_BASE_URL:-}"
if [[ -z "$url" ]]; then
  url="http://$(terraform -chdir="$root/infra/aws" output -raw load_balancer_dns_name)"
fi
url="${url%/}"

status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "$url/")"
[[ "$status" == "200" ]] || { echo "Home page returned HTTP $status" >&2; exit 1; }
scheme="${url%%://*}"
hostport="${url#*://}"
hostport="${hostport%%/*}"
for port in 3001 3002 3003 3004 3005; do
  status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "$scheme://$hostport:$port/" 2>/dev/null || true)"
  [[ "$status" == "200" ]] || { echo "Frontend on port $port returned HTTP ${status:-no-response}" >&2; exit 1; }
done

# Exercise Student 3 through its public frontend proxy, which reaches the
# private backend and durable database without exposing backend ports.
student3_url="$scheme://$hostport:3003"
run_id="$(date -u +%Y%m%d%H%M%S)-$$"
email="release2-check-$run_id@example.invalid"
customer_id=""
cleanup() {
  if [[ -n "$customer_id" ]]; then
    curl --silent --show-error --output /dev/null -X POST \
      "$student3_url/customers/$customer_id/delete" || true
  fi
}
trap cleanup EXIT

curl --fail --silent --show-error -X POST "$student3_url/customers" \
  --data-urlencode "name=Release 2 validation $run_id" \
  --data-urlencode "email=$email" \
  --data-urlencode "phone=" --data-urlencode "address=" \
  --data-urlencode "loyalty_tier=Bronze" \
  --data-urlencode "joined_at=2026-01-01" >/dev/null
table="$(curl --fail --silent --show-error --get "$student3_url/partials/customers" \
  --data-urlencode "search=$email")"
customer_id="$(python3 -c 'import re,sys; m=re.search("hx-get=./customers/([0-9]+).",sys.stdin.read()); print(m.group(1) if m else "")' <<<"$table")"
[[ -n "$customer_id" ]] || { echo "Student 3 create/list through database failed." >&2; exit 1; }

updated="$(curl --fail --silent --show-error -X POST "$student3_url/customers/$customer_id" \
  --data-urlencode "name=Release 2 validation $run_id" \
  --data-urlencode "email=$email" \
  --data-urlencode "phone=" --data-urlencode "address=" \
  --data-urlencode "loyalty_tier=Silver" \
  --data-urlencode "joined_at=2026-01-01")"
grep -q "Silver" <<<"$updated"
curl --fail --silent --show-error -X POST "$student3_url/customers/$customer_id/delete" >/dev/null
customer_id=""
table="$(curl --fail --silent --show-error --get "$student3_url/partials/customers" \
  --data-urlencode "search=$email")"
grep -q "No customers match" <<<"$table"

if [[ "${EXERCISE_RECOVERY:-no}" == "yes" ]]; then
  # A nonexistent path gives a reversible 404 check without changing a service or data.
  status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "$url/__release2-controlled-invalid-endpoint")"
  [[ "$status" == "404" ]] || { echo "Controlled invalid endpoint returned HTTP $status, expected 404" >&2; exit 1; }
  status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "$url/")"
  [[ "$status" == "200" ]] || { echo "Recovery check returned HTTP $status" >&2; exit 1; }
fi

mkdir -p "$root/reports"
printf '{"checked_at":"%s","base_url":"%s","home":"200","frontend_ports":[3001,3002,3003,3004,3005],"student3_crud":"create-update-delete-and-database-list-verified","controlled_recovery":"%s"}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$url" "${EXERCISE_RECOVERY:-no}" \
  | tee "$root/reports/aws-runtime-validation.json"
