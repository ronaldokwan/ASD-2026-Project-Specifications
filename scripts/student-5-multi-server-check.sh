#!/usr/bin/env bash
# Student 5 multi-server system test for the local deployment.
#   Terminal 1: docker compose up --build                       (frontends, backends, databases, Ollama)
#   Terminal 2: PYTHON_BIN=python3.11 bash scripts/run-ai-services.sh   (native AI-Mode, MCP, RAG, Multi-Agent)
#   Terminal 3: bash scripts/student-5-multi-server-check.sh    (this script)
set -uo pipefail
cd "$(dirname "$0")/.."
log="${1:-docs/evidence/student-5/release-2/05-multi-server-check.log}"
mkdir -p "$(dirname "$log")"
exec > >(tee "$log") 2>&1
failures=0

line()   { printf '%s\n' "────────────────────────────────────────────────────────────────"; }
header() { echo; printf '%s\n' "$1"; }
result() {  # result <ok|fail> <label> <detail>
  local mark="✓"
  [ "$1" = ok ] || { mark="✗"; failures=$((failures + 1)); }
  printf '  %s  %-30s %s\n' "$mark" "$2" "$3"
}
http() { curl -s -o /dev/null -m "${2:-10}" -w '%{http_code}' "$1"; }
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)" 2>/dev/null; }

line
printf '  Student 5 · Reviews and Ratings · multi-server check\n'
printf '  %s UTC · commit %s\n' "$(date -u '+%Y-%m-%d %H:%M')" "$(git rev-parse --short HEAD)"
line

header "Terminal 1 · Docker Compose (containerised)"
docker compose ps --format '{{.Service}}|{{.State}}|{{.Ports}}' \
  | grep -E '^(student-5|ollama)' | sort \
  | while IFS='|' read -r svc state ports; do
      port=$(sed -nE 's/.*:([0-9]+)->.*/\1/p' <<<"$ports" | head -1)
      if [ "$state" = running ]; then mark="✓"; else mark="✗"; fi
      printf '  %s  %-30s %-9s :%s\n' "$mark" "$svc" "$state" "$port"
    done

header "Terminal 2 · native host services (not in Compose)"
if docker compose config --services | grep -qE '^(ai-mode|mcp|mcp-server|rag|rag-server|multi-agent)$'; then
  result fail "AI services outside Compose" "an AI service is a Compose service"
else
  result ok "AI services outside Compose" "none in docker-compose.yml"
fi
for svc in "AI-Mode:7001" "MCP server:7002" "RAG server:7003" "Multi-Agent server:7004"; do
  name=${svc%%:*}; port=${svc##*:}; code=$(http "localhost:$port/health")
  [ "$code" = 200 ] && result ok "$name  :$port" "HTTP $code" || result fail "$name  :$port" "HTTP $code"
done

header "Student 5 paths"
code=$(http localhost:3005/)
[ "$code" = 200 ] && result ok "Frontend UI  :3005" "HTTP $code" || result fail "Frontend UI  :3005" "HTTP $code"
status=$(curl -s -m 10 localhost:8005/health | json 'd["status"]')
[ "$status" = ok ] && result ok "Backend/API  :8005" "$status" || result fail "Backend/API  :8005" "${status:-unreachable}"
status=$(curl -s -m 10 localhost:9005/health | json 'd["status"]')
[ "$status" = ok ] && result ok "Database  :9005" "$status" || result fail "Database  :9005" "${status:-unreachable}"

reviews=$(curl -s -m 10 localhost:8005/api/reviews)
count=$(json 'len(d["reviews"])' <<<"$reviews")
[ -n "$count" ] && result ok "Backend -> Database" "$count reviews" || result fail "Backend -> Database" "no reviews returned"
first=$(json 'd["reviews"][0]["review_id"]' <<<"$reviews")
sku=$(json 'd["reviews"][0]["product_sku"]' <<<"$reviews")

status=$(curl -s -m 10 localhost:8005/health | json 'd["ai_mode"]["status"]')
[ "$status" = ok ] && result ok "Backend -> AI-Mode" "$status" || result fail "Backend -> AI-Mode" "${status:-unreachable}"

code=$(curl -s -o /dev/null -m 30 -w '%{http_code}' -X POST localhost:8005/api/reviews/moderate \
  -H 'Content-Type: application/json' \
  -d "{\"product_sku\":\"$sku\",\"review_text\":\"Great sound and the battery lasts all day.\",\"rating\":5}")
[ "$code" = 200 ] && result ok "Backend -> MCP" "check_review_quality, HTTP $code" || result fail "Backend -> MCP" "HTTP $code"

echo "     (RAG answers through the LLM, allow up to 2 minutes)"
code=$(curl -s -o /dev/null -m 150 -w '%{http_code}' -X POST localhost:8005/api/reviews/ask \
  -H 'Content-Type: application/json' -d "{\"product_sku\":\"$sku\",\"question\":\"How is the sound quality?\"}")
[ "$code" = 200 ] && result ok "Backend -> RAG" "grounded answer, HTTP $code" || result fail "Backend -> RAG" "HTTP $code"

code=$(http "localhost:8005/api/reviews/$first/multi-agent/history")
[ "$code" = 200 ] && result ok "Backend -> Multi-Agent" "workflow history, HTTP $code" || result fail "Backend -> Multi-Agent" "HTTP $code"

echo
line
if [ "$failures" -eq 0 ]; then
  printf '  ALL CHECKS PASSED · log: %s\n' "$log"
else
  printf '  %s CHECK(S) FAILED · log: %s\n' "$failures" "$log"
fi
line
exit $((failures > 0))
