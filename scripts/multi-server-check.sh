#!/usr/bin/env bash
# Multi-server system test for the local deployment (criterion 1 evidence).
#   Terminal 1: docker compose up --build              (frontends, backends, databases)
#   Terminal 2: bash scripts/run-ai-services.sh        (native AI-Mode, MCP, RAG, Multi-Agent)
#   Terminal 3: bash scripts/multi-server-check.sh     (this script)
# Every request and response is written to the log; exit code 1 if any check fails.
set -uo pipefail
cd "$(dirname "$0")/.."
log="${1:-docs/evidence/student-1/release-2/05-multi-server-check.log}"
mkdir -p "$(dirname "$log")"
failures=0
exec > >(tee "$log") 2>&1

echo "# Multi-server system test $(date -u +%Y-%m-%dT%H:%M:%SZ) at $(git rev-parse --short HEAD)"
echo
echo "## Terminal 1 - Docker Compose (containerised microservices)"
docker compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Ports}}'
echo
echo "## Terminal 2 - native host services (not containerised)"
docker compose config --services | grep -E '^(ai-mode|mcp|mcp-server|rag|rag-server|multi-agent)$' \
  && { echo "FAIL AI services must not be Compose services"; failures=$((failures + 1)); } \
  || echo "ok   no AI service is a Compose service"

# check <label> <expected HTTP code> <curl args...>
check() {
  local label=$1 expected=$2; shift 2
  local body code
  body="$(curl -s -m 120 -w '\n%{http_code}' "$@")"
  code="${body##*$'\n'}"
  body="${body%$'\n'*}"
  if [[ "$code" == "$expected" ]]; then echo "ok   $label -> HTTP $code"; else
    echo "FAIL $label -> HTTP ${code:-none} (expected $expected)"; failures=$((failures + 1)); fi
  echo "     ${body:0:400}"
}

check "AI-Mode     :7001/health" 200 http://localhost:7001/health
check "MCP server  :7002/health" 200 http://localhost:7002/health
check "RAG server  :7003/health" 200 http://localhost:7003/health
check "Multi-Agent :7004/health" 200 http://localhost:7004/health

echo
echo "## Terminal 3 - Student 1 end to end: frontend -> backend/API -> database and AI services"
check "frontend    :3001/" 200 http://localhost:3001/ -o /dev/null
check "database    :9001/health" 200 http://localhost:9001/health
check "backend     :8001/health (database + all four AI services)" 200 http://localhost:8001/health
check "backend -> database  GET /api/products" 200 http://localhost:8001/api/products -o /dev/null
check "backend -> MCP       check_product_listing" 200 -X POST http://localhost:8001/api/products/1/mcp-check \
  -H 'Content-Type: application/json' -d '{}'
check "backend -> RAG       grounded answer" 200 -X POST http://localhost:8001/api/catalogue/ask \
  -H 'Content-Type: application/json' -d '{"question":"What makes a product listing ready to publish?"}'
check "backend -> Multi-Agent  start listing review" 202 -X POST http://localhost:8001/api/products/1/multi-agent \
  -H 'Content-Type: application/json' -d '{}'

echo
echo "failures=$failures"
exit $((failures > 0))
