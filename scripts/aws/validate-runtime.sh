#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
url="${APP_BASE_URL:-}"
if [[ -z "$url" ]]; then
  url="http://$(terraform -chdir="$root/infra/aws" output -raw load_balancer_dns_name)"
fi
url="${url%/}"

# Right after terraform apply the new tasks are still starting and the load balancer
# answers 503 until they pass health checks, so wait (up to WAIT_SECONDS) for each page.
wait_for_200() {
  local name=$1 target=$2 status="" waited=0
  while :; do
    # --location: Student 2's frontend redirects / to /orders.
    status="$(curl --silent --location --output /dev/null --write-out '%{http_code}' --max-time 10 "$target" 2>/dev/null || true)"
    [[ "$status" == "200" ]] && return 0
    if (( waited >= ${WAIT_SECONDS:-600} )); then
      echo "$name returned HTTP ${status:-no-response} after ${waited}s" >&2
      exit 1
    fi
    sleep 10
    waited=$((waited + 10))
  done
}

wait_for_200 "Home page" "$url/"
scheme="${url%%://*}"
hostport="${url#*://}"
hostport="${hostport%%/*}"
for port in 3001 3002 3003 3004 3005; do
  wait_for_200 "Frontend on port $port" "$scheme://$hostport:$port/"
done

# Exercise Student 3 through its public frontend proxy, which reaches the
# private backend and durable database without exposing backend ports.
student3_url="$scheme://$hostport:3003"
run_id="$(date -u +%Y%m%d%H%M%S)-$$"
email="release2-check-$run_id@example.invalid"
customer_id=""
student1_url="$scheme://$hostport:3001"
product_id=""
cleanup() {
  if [[ -n "$customer_id" ]]; then
    curl --silent --show-error --output /dev/null -X POST \
      "$student3_url/customers/$customer_id/delete" || true
  fi
  if [[ -n "$product_id" ]]; then
    curl --silent --show-error --output /dev/null -X POST \
      "$student1_url/products/$product_id/delete" || true
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

# Student 1 Product Catalogue CRUD through its public frontend proxy, then the
# Release 1/2 AI services must be reported disabled by the cloud backend.
sku="SKU-AWS-$(date -u +%H%M%S)$$"
product_form=(--data-urlencode "sku=$sku" --data-urlencode "name=Release 2 cloud check"
  --data-urlencode "category=Audio" --data-urlencode "status=draft"
  --data-urlencode "description=Created by validate-runtime.sh to verify cloud CRUD.")
curl --fail --silent --show-error -X POST "$student1_url/products" \
  "${product_form[@]}" --data-urlencode "price=42.00" >/dev/null
table="$(curl --fail --silent --show-error --get "$student1_url/partials/products" \
  --data-urlencode "search=$sku")"
product_id="$(python3 -c 'import re,sys; m=re.search("product-row-([0-9]+)",sys.stdin.read()); print(m.group(1) if m else "")' <<<"$table")"
[[ -n "$product_id" ]] || { echo "Student 1 create/list through database failed." >&2; exit 1; }
updated="$(curl --fail --silent --show-error -X POST "$student1_url/products/$product_id" \
  "${product_form[@]}" --data-urlencode "price=43.50")"
grep -q "Updated" <<<"$updated"
curl --fail --silent --show-error -X POST "$student1_url/products/$product_id/delete" >/dev/null
product_id=""
table="$(curl --fail --silent --show-error --get "$student1_url/partials/products" \
  --data-urlencode "search=$sku")"
grep -q "No products match" <<<"$table"
curl --fail --silent --show-error "$student1_url/health" | python3 -c '
import json, sys
backend = json.load(sys.stdin)["backend"]
for key in ("ai_mode", "mcp_server", "rag_server", "multi_agent_server"):
    assert backend[key] == {"status": "disabled"}, key
'

if [[ "${EXERCISE_RECOVERY:-no}" == "yes" ]]; then
  # A nonexistent path gives a reversible 404 check without changing a service or data.
  status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "$url/__release2-controlled-invalid-endpoint")"
  [[ "$status" == "404" ]] || { echo "Controlled invalid endpoint returned HTTP $status, expected 404" >&2; exit 1; }
  status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "$url/")"
  [[ "$status" == "200" ]] || { echo "Recovery check returned HTTP $status" >&2; exit 1; }
fi

mkdir -p "$root/reports"
printf '{"checked_at":"%s","base_url":"%s","home":"200","frontend_ports":[3001,3002,3003,3004,3005],"student3_crud":"create-update-delete-and-database-list-verified","student1_crud":"create-update-delete-and-database-list-verified","student1_ai_services":"disabled","controlled_recovery":"%s"}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$url" "${EXERCISE_RECOVERY:-no}" \
  | tee "$root/reports/aws-runtime-validation.json"
