#!/usr/bin/env bash
# Multi-server system test of the whole integrated local deployment (all five students).
#   Terminal 1: docker compose up --build              (frontends, backends, databases, Ollama)
#   Terminal 2: bash scripts/run-ai-services.sh        (native AI-Mode, MCP, RAG, Multi-Agent)
#   Terminal 3: bash scripts/multi-server-check-all.sh (this script)
# The terminal shows one line per check; every response body goes to the log as well.
# Exit code 1 if any check fails.
set -uo pipefail
cd "$(dirname "$0")/.."
log="${1:-docs/evidence/group/release-2/05-multi-server-check-all.log}"
mkdir -p "$(dirname "$log")"
failures=0
: > "$log"
say() { echo "$*" | tee -a "$log"; }

say "# Multi-server system test, all five students, $(date -u +%Y-%m-%dT%H:%M:%SZ) at $(git rev-parse --short HEAD)"
say ""
say "## Terminal 1 - Docker Compose (containerised microservices)"
docker compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}' | tee -a "$log"
say ""
say "## Terminal 2 - native host services (not containerised)"
if docker compose config --services | grep -qE '^(ai-mode|mcp|mcp-server|rag|rag-server|multi-agent)$'; then
  say "FAIL AI services must not be Compose services"; failures=$((failures + 1))
else
  say "ok   no AI service is a Compose service"
fi

# check <label> <expected HTTP code> <curl args...>
check() {
  local label=$1 expected=$2; shift 2
  local body code
  body="$(curl -s -m 120 -w '\n%{http_code}' "$@")"
  code="${body##*$'\n'}"
  body="${body%$'\n'*}"
  if [[ "$code" == "$expected" ]]; then say "ok   $label -> HTTP $code"; else
    say "FAIL $label -> HTTP ${code:-none} (expected $expected)"; failures=$((failures + 1)); fi
  echo "     ${body:0:400}" >> "$log"
}

check "AI-Mode      :7001/health" 200 http://localhost:7001/health
check "MCP server   :7002/health" 200 http://localhost:7002/health
check "RAG server   :7003/health" 200 http://localhost:7003/health
check "Multi-Agent  :7004/health" 200 http://localhost:7004/health
check "Ollama       :11434/api/tags" 200 http://localhost:11434/api/tags

say ""
say "## Terminal 3 - every student: frontend -> backend/API -> database"
check "home page    :3000/" 200 http://localhost:3000/
# student|frontend health|database health|backend health|backend -> database
students=(
  "1 Product Catalogue|http://localhost:3001/health|http://localhost:9001/health|http://localhost:8001/health|http://localhost:8001/api/products"
  "2 Customer Orders|http://localhost:3002/actuator/health|http://localhost:9002/actuator/health|http://localhost:8002/actuator/health|http://localhost:8002/api/orders"
  "3 Customer Accounts|http://localhost:3003/health|http://localhost:9003/health|http://localhost:8003/health|http://localhost:8003/api/customers"
  "4 Inventory and Stock|http://localhost:3004/health|http://localhost:9004/health|http://localhost:8004/health|http://localhost:8004/api/stock"
  "5 Reviews and Ratings|http://localhost:3005/health|http://localhost:9005/health|http://localhost:8005/health|http://localhost:8005/api/reviews"
)
for entry in "${students[@]}"; do
  IFS='|' read -r name frontend database backend data <<<"$entry"
  say "- Student $name"
  check "  frontend   ${frontend#http://localhost}" 200 "$frontend"
  check "  database   ${database#http://localhost}" 200 "$database"
  check "  backend    ${backend#http://localhost}" 200 "$backend"
  check "  backend -> database  GET ${data#http://localhost}" 200 "$data"
done

say ""
say "## Backends -> shared AI services (Student 1 path through all four)"
# Use a product that exists: earlier CRUD tests may have deleted the first ones.
product_id="$(curl -s -m 10 http://localhost:8001/api/products | grep -o '"id": *[0-9]*' | head -1 | grep -o '[0-9]*$')"
product_id="${product_id:-1}"
check "backend -> MCP          check_product_listing" 200 -X POST http://localhost:8001/api/products/$product_id/mcp-check \
  -H 'Content-Type: application/json' -d '{}'
check "backend -> RAG          grounded answer" 200 -X POST http://localhost:8001/api/catalogue/ask \
  -H 'Content-Type: application/json' -d '{"question":"What makes a product listing ready to publish?"}'
check "backend -> Multi-Agent  start listing review" 202 -X POST http://localhost:8001/api/products/$product_id/multi-agent \
  -H 'Content-Type: application/json' -d '{}'

say ""
say "failures=$failures   (full responses: $log)"
exit $((failures > 0))
