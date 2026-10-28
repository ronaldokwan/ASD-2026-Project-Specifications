#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
url="${APP_BASE_URL:-}"
if [[ -z "$url" ]]; then
  url="http://$(terraform -chdir="$root/infra/aws" output -raw load_balancer_dns_name)"
fi
url="${url%/}"

# Resolve readiness targets from Terraform state so this also honours configured names.
cluster_name="$(terraform -chdir="$root/infra/aws" output -raw ecs_cluster_name)"
service_map="$(terraform -chdir="$root/infra/aws" output -json ecs_service_names | python3 -c '
import json, sys
for key, name in sorted(json.load(sys.stdin).items()):
    print("{}\t{}".format(key, name))
')"
target_group_map="$(terraform -chdir="$root/infra/aws" output -json frontend_target_group_arns | python3 -c '
import json, sys
for key, arn in sorted(json.load(sys.stdin).items()):
    print("{}\t{}".format(key, arn))
')"
health_check_map="$(terraform -chdir="$root/infra/aws" output -json frontend_dependency_health_checks | python3 -c '
import json, sys
for key, check in sorted(json.load(sys.stdin).items()):
    print("{}\t{}\t{}".format(key, check["port"], check["path"]))
')"

service_names=()
while IFS=$'\t' read -r key name; do
  [[ -n "$key" ]] || continue
  service_names+=("$name")
done <<< "$service_map"

target_group_keys=()
target_group_arns=()
while IFS=$'\t' read -r key arn; do
  [[ -n "$key" ]] || continue
  target_group_keys+=("$key")
  target_group_arns+=("$arn")
done <<< "$target_group_map"

health_keys=()
health_ports=()
health_paths=()
while IFS=$'\t' read -r key port path; do
  [[ -n "$key" ]] || continue
  health_keys+=("$key")
  health_ports+=("$port")
  health_paths+=("$path")
done <<< "$health_check_map"

[[ ${#service_names[@]} -gt 0 ]] || { echo "Terraform returned no ECS service names." >&2; exit 2; }
[[ ${#target_group_arns[@]} -gt 0 ]] || { echo "Terraform returned no frontend target groups." >&2; exit 2; }
[[ ${#health_keys[@]} -gt 0 ]] || { echo "Terraform returned no frontend dependency health paths." >&2; exit 2; }

wait_seconds="${READINESS_WAIT_SECONDS:-${WAIT_SECONDS:-600}}"
poll_seconds="${READINESS_POLL_SECONDS:-10}"
[[ "$wait_seconds" =~ ^[1-9][0-9]*$ ]] || { echo "READINESS_WAIT_SECONDS must be a positive integer." >&2; exit 2; }
[[ "$poll_seconds" =~ ^[1-9][0-9]*$ ]] || { echo "READINESS_POLL_SECONDS must be a positive integer." >&2; exit 2; }
readiness_started=$SECONDS
readiness_deadline=$((readiness_started + wait_seconds))

print_readiness_diagnostics() {
  local offset count batch_json i
  echo "ECS readiness diagnostics:" >&2
  for ((offset = 0; offset < ${#service_names[@]}; offset += 10)); do
    count=10
    (( offset + count > ${#service_names[@]} )) && count=$((${#service_names[@]} - offset))
    batch_json="$(aws ecs describe-services \
      --cluster "$cluster_name" \
      --services "${service_names[@]:offset:count}" \
      --cli-connect-timeout 5 --cli-read-timeout 10 \
      --output json 2>&1)" || {
      echo "Could not describe ECS services: $batch_json" >&2
      continue
    }
    python3 - "$batch_json" <<'PY' >&2
import json
import sys

response = json.loads(sys.argv[1])
for service in response.get("services", []):
    print("Service {}: status={}, desired={}, running={}, pending={}".format(
        service.get("serviceName"), service.get("status"),
        service.get("desiredCount"), service.get("runningCount"),
        service.get("pendingCount"),
    ))
    for deployment in service.get("deployments", []):
        print("  deployment: status={}, rollout={}, desired={}, running={}, pending={}".format(
            deployment.get("status"), deployment.get("rolloutState", "unknown"),
            deployment.get("desiredCount"), deployment.get("runningCount"),
            deployment.get("pendingCount"),
        ))
    for event in service.get("events", [])[:5]:
        print("  event {}: {}".format(event.get("createdAt"), event.get("message")))
for failure in response.get("failures", []):
    print("Service lookup failure: {} {}".format(
        failure.get("arn", failure.get("reason", "unknown")),
        failure.get("detail", ""),
    ))
PY
  done

  echo "ALB target-health diagnostics:" >&2
  for i in "${!target_group_arns[@]}"; do
    local target_json
    if ! target_json="$(aws elbv2 describe-target-health \
      --target-group-arn "${target_group_arns[$i]}" \
      --cli-connect-timeout 5 --cli-read-timeout 10 --output json 2>&1)"; then
      echo "Target group ${target_group_keys[$i]}: $target_json" >&2
      continue
    fi
    python3 - "${target_group_keys[$i]}" "$target_json" <<'PY' >&2
import json
import sys

key, raw = sys.argv[1:]
response = json.loads(raw)
descriptions = response.get("TargetHealthDescriptions", [])
if not descriptions:
    print("Target group {}: no registered targets".format(key))
for item in descriptions:
    health = item.get("TargetHealth", {})
    print("Target group {} target {}:{}: state={}, reason={}, description={}".format(
        key, item.get("Target", {}).get("Id"), item.get("Target", {}).get("Port"),
        health.get("State"), health.get("Reason", ""), health.get("Description", ""),
    ))
PY
  done
}

services_are_stable() {
  local offset count batch_json
  for ((offset = 0; offset < ${#service_names[@]}; offset += 10)); do
    count=10
    (( offset + count > ${#service_names[@]} )) && count=$((${#service_names[@]} - offset))
    batch_json="$(aws ecs describe-services \
      --cluster "$cluster_name" \
      --services "${service_names[@]:offset:count}" \
      --cli-connect-timeout 5 --cli-read-timeout 10 \
      --output json)" || return 1
    python3 - "$batch_json" <<'PY' || return 1
import json
import sys

response = json.loads(sys.argv[1])
if response.get("failures"):
    raise SystemExit(1)
for service in response.get("services", []):
    deployments = service.get("deployments", [])
    primary = [deployment for deployment in deployments
               if deployment.get("status") == "PRIMARY"]
    if (service.get("status") != "ACTIVE"
            or service.get("runningCount") != service.get("desiredCount")
            or service.get("pendingCount") != 0
            or len(primary) != 1):
        raise SystemExit(1)

    primary = primary[0]
    if (primary.get("desiredCount") != service.get("desiredCount")
            or primary.get("runningCount") != primary.get("desiredCount")
            or primary.get("pendingCount") != 0
            or primary.get("rolloutState") == "FAILED"):
        raise SystemExit(1)

    for deployment in deployments:
        if deployment is primary:
            continue
        if (deployment.get("desiredCount") == 0
                and deployment.get("runningCount") == 0
                and deployment.get("pendingCount") == 0):
            continue
        raise SystemExit(1)
PY
  done
}

target_groups_are_healthy() {
  local i target_json
  for i in "${!target_group_arns[@]}"; do
    target_json="$(aws elbv2 describe-target-health \
      --target-group-arn "${target_group_arns[$i]}" \
      --cli-connect-timeout 5 --cli-read-timeout 10 --output json)" || return 1
    python3 - "$target_json" <<'PY' || return 1
import json
import sys

descriptions = json.loads(sys.argv[1]).get("TargetHealthDescriptions", [])
states = [item.get("TargetHealth", {}).get("State") for item in descriptions]
if (not states or "healthy" not in states
        or any(state not in ("healthy", "draining") for state in states)):
    raise SystemExit(1)
PY
  done
}

wait_for_ecs_stability() {
  echo "Waiting up to ${wait_seconds}s for ECS services in $cluster_name to stabilise..."
  until services_are_stable; do
    if (( SECONDS >= readiness_deadline )); then
      echo "Timed out waiting for ECS services to stabilise after ${wait_seconds}s." >&2
      print_readiness_diagnostics
      exit 1
    fi
    sleep "$poll_seconds"
  done
  echo "All ECS services are stable."
}

wait_for_healthy_targets() {
  echo "Waiting up to ${wait_seconds}s for ALB targets to become healthy..."
  until target_groups_are_healthy; do
    if (( SECONDS >= readiness_deadline )); then
      echo "Timed out waiting for ALB targets to become healthy after ${wait_seconds}s." >&2
      print_readiness_diagnostics
      exit 1
    fi
    sleep "$poll_seconds"
  done
  echo "All frontend ALB targets are healthy."
}

# Terraform can submit ECS service updates before replacement tasks have finished
# starting. Wait for deployments, target registration, and dependency-aware health
# endpoints before running any state-changing CRUD probes.
wait_for_ecs_stability
wait_for_healthy_targets

# Also require each existing frontend/backend/database health path to pass. Frontend
# health handlers proxy to backend health; backend health handlers check their DB.
wait_for_200() {
  local name=$1 target=$2 status="" waited=0
  while :; do
    echo "Readiness GET $target" >&2
    # --location: Student 2's frontend redirects / to /orders.
    status="$(curl --silent --location --output /dev/null --write-out '%{http_code}' --max-time 10 "$target" 2>/dev/null || true)"
    [[ "$status" == "200" ]] && return 0
    if (( SECONDS >= readiness_deadline )); then
      waited=$((SECONDS - readiness_started))
      echo "$name returned HTTP ${status:-no-response} after ${waited}s" >&2
      print_readiness_diagnostics
      exit 1
    fi
    local remaining=$((readiness_deadline - SECONDS))
    sleep "$((remaining < poll_seconds ? remaining : poll_seconds))"
  done
}

wait_for_200 "Home page" "$url/"
scheme="${url%%://*}"
hostport="${url#*://}"
hostport="${hostport%%/*}"
for port in 3001 3002 3003 3004 3005; do
  wait_for_200 "Frontend on port $port" "$scheme://$hostport:$port/"
done

# The frontend health handlers call their backend health endpoints; those backend
# handlers check their database dependency. This verifies those existing checks
# through the public route as well as ECS's container health checks for each task.
for i in "${!health_keys[@]}"; do
  health_url="$scheme://$hostport:${health_ports[$i]}${health_paths[$i]}"
  [[ "${health_paths[$i]}" == "/" ]] && health_url="$url/"
  wait_for_200 "Health endpoint for ${health_keys[$i]}" "$health_url"
done

smoke_curl() {
  local method=$1 target=$2 status=0
  shift 2
  echo "Smoke test request: $method $target" >&2
  curl --fail --silent --show-error --request "$method" "$target" "$@" || status=$?
  if (( status != 0 )); then
    echo "Smoke test request failed with curl exit code $status." >&2
    print_readiness_diagnostics
    return "$status"
  fi
}

with_query() {
  python3 - "$1" "$2" "$3" <<'PY'
from urllib.parse import urlencode
import sys

base, key, value = sys.argv[1:]
print("{}?{}".format(base, urlencode({key: value})))
PY
}

# Exercise Student 3 through its public frontend proxy, which reaches the
# private backend and durable database without exposing backend ports.
student3_url="$scheme://$hostport:3003"
run_id="$(date -u +%Y%m%d%H%M%S)-$$"
email="release2-check-$run_id@example.invalid"
customer_id=""
student1_url="$scheme://$hostport:3001"
product_id=""
student5_url="$scheme://$hostport:3005"
review_id=""
cleanup() {
  if [[ -n "$customer_id" ]]; then
    echo "Cleanup request: POST $student3_url/customers/$customer_id/delete" >&2
    curl --silent --show-error --output /dev/null -X POST \
      "$student3_url/customers/$customer_id/delete" || true
  fi
  if [[ -n "$product_id" ]]; then
    echo "Cleanup request: POST $student1_url/products/$product_id/delete" >&2
    curl --silent --show-error --output /dev/null -X POST \
      "$student1_url/products/$product_id/delete" || true
  fi
  if [[ -n "$review_id" ]]; then
    echo "Cleanup request: POST $student5_url/reviews/$review_id/delete" >&2
    curl --silent --show-error --output /dev/null -X POST \
      "$student5_url/reviews/$review_id/delete" || true
  fi
}
trap cleanup EXIT

smoke_curl POST "$student3_url/customers" \
  --data-urlencode "name=Release 2 validation $run_id" \
  --data-urlencode "email=$email" \
  --data-urlencode "phone=" --data-urlencode "address=" \
  --data-urlencode "loyalty_tier=Bronze" \
  --data-urlencode "joined_at=2026-01-01" >/dev/null
customer_search_url="$(with_query "$student3_url/partials/customers" search "$email")"
table="$(smoke_curl GET "$customer_search_url")"
customer_id="$(python3 -c 'import re,sys; m=re.search("hx-get=./customers/([0-9]+).",sys.stdin.read()); print(m.group(1) if m else "")' <<<"$table")"
[[ -n "$customer_id" ]] || { echo "Student 3 create/list through database failed." >&2; exit 1; }

updated="$(smoke_curl POST "$student3_url/customers/$customer_id" \
  --data-urlencode "name=Release 2 validation $run_id" \
  --data-urlencode "email=$email" \
  --data-urlencode "phone=" --data-urlencode "address=" \
  --data-urlencode "loyalty_tier=Silver" \
  --data-urlencode "joined_at=2026-01-01")"
grep -q "Silver" <<<"$updated"
smoke_curl POST "$student3_url/customers/$customer_id/delete" >/dev/null
customer_id=""
table="$(smoke_curl GET "$customer_search_url")"
grep -q "No customers match" <<<"$table"

# Student 1 Product Catalogue CRUD through its public frontend proxy, then the
# Release 1/2 AI services must be reported disabled by the cloud backend.
sku="SKU-AWS-$(date -u +%H%M%S)$$"
product_form=(--data-urlencode "sku=$sku" --data-urlencode "name=Release 2 cloud check"
  --data-urlencode "category=Audio" --data-urlencode "status=draft"
  --data-urlencode "description=Created by validate-runtime.sh to verify cloud CRUD.")
smoke_curl POST "$student1_url/products" \
  "${product_form[@]}" --data-urlencode "price=42.00" >/dev/null
product_search_url="$(with_query "$student1_url/partials/products" search "$sku")"
table="$(smoke_curl GET "$product_search_url")"
product_id="$(python3 -c 'import re,sys; m=re.search("product-row-([0-9]+)",sys.stdin.read()); print(m.group(1) if m else "")' <<<"$table")"
[[ -n "$product_id" ]] || { echo "Student 1 create/list through database failed." >&2; exit 1; }
updated="$(smoke_curl POST "$student1_url/products/$product_id" \
  "${product_form[@]}" --data-urlencode "price=43.50")"
grep -q "Updated" <<<"$updated"
smoke_curl POST "$student1_url/products/$product_id/delete" >/dev/null
product_id=""
table="$(smoke_curl GET "$product_search_url")"
grep -q "No products match" <<<"$table"
# The bonus cloud AI profile (enable-cloud-ai.sh) sets EXPECT_CLOUD_AI=enabled instead.
ai_expected="${EXPECT_CLOUD_AI:-disabled}"
smoke_curl GET "$student1_url/health" | python3 -c '
import json, sys
backend = json.load(sys.stdin)["backend"]
for key in ("ai_mode", "mcp_server", "rag_server", "multi_agent_server"):
    if sys.argv[1] == "enabled":
        assert backend[key].get("status") == "ok", (key, backend[key])
    else:
        assert backend[key] == {"status": "disabled"}, key
' "$ai_expected"

# Student 5 Reviews and Ratings CRUD through its public frontend proxy.
review_sku="SKU-AWS-REV-$(date -u +%H%M%S)$$"
smoke_curl POST "$student5_url/reviews" \
  --data-urlencode "product_sku=$review_sku" \
  --data-urlencode "user_id=release2check" \
  --data-urlencode "rating=4" \
  --data-urlencode "review=Created by validate-runtime.sh to verify cloud CRUD." >/dev/null
review_search_url="$(with_query "$student5_url/partials/reviews" product_sku "$review_sku")"
table="$(smoke_curl GET "$review_search_url")"
# Skip the table's and form's own ids (review-table, review-form); rows are review-<uuid>.
review_id="$(python3 -c 'import re,sys; m=re.search("id=\"review-(?!table\"|form\")([^\"]+)\"",sys.stdin.read()); print(m.group(1) if m else "")' <<<"$table")"
[[ -n "$review_id" ]] || { echo "Student 5 create/list through database failed." >&2; exit 1; }
updated="$(smoke_curl POST "$student5_url/reviews/$review_id" \
  --data-urlencode "product_sku=$review_sku" \
  --data-urlencode "user_id=release2check" \
  --data-urlencode "rating=5" \
  --data-urlencode "review=Updated by validate-runtime.sh to verify cloud CRUD.")"
grep -q "updated" <<<"$updated"
smoke_curl POST "$student5_url/reviews/$review_id/delete" >/dev/null
review_id=""
table="$(smoke_curl GET "$review_search_url")"
grep -q "No reviews match" <<<"$table"

if [[ "${EXERCISE_RECOVERY:-no}" == "yes" ]]; then
  # A nonexistent path gives a reversible 404 check without changing a service or data.
  echo "Smoke test request: GET $url/__release2-controlled-invalid-endpoint" >&2
  status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "$url/__release2-controlled-invalid-endpoint")"
  [[ "$status" == "404" ]] || { echo "Controlled invalid endpoint returned HTTP $status, expected 404" >&2; exit 1; }
  echo "Smoke test request: GET $url/" >&2
  status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "$url/")"
  [[ "$status" == "200" ]] || { echo "Recovery check returned HTTP $status" >&2; exit 1; }
fi

mkdir -p "$root/reports"
printf '{"checked_at":"%s","base_url":"%s","home":"200","frontend_ports":[3001,3002,3003,3004,3005],"student3_crud":"create-update-delete-and-database-list-verified","student1_crud":"create-update-delete-and-database-list-verified","student1_ai_services":"%s","student5_crud":"create-update-delete-and-database-list-verified","controlled_recovery":"%s"}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$url" "$ai_expected" "${EXERCISE_RECOVERY:-no}" \
  | tee "$root/reports/aws-runtime-validation.json"
